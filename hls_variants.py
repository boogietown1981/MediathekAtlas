"""Quality levels of an HLS stream (0.5.63).

Björn (12.11.2026): live TV and streams of every provider stutter, start late and run behind,
on a slow internet connection.

Until now ffmpeg received the master playlist of the provider. It then opened every quality level
to analyse it (a start delay that grows with the number of levels) and always played the highest
one, whatever the connection could carry. This module reads the master playlist once, lets the
caller choose one level and writes a playlist that contains only this level (and its audio
track). ffmpeg then opens exactly one video and one audio stream.

Nothing is decoded or circumvented here: the playlist is the provider's own text, reduced to one
of its entries, with absolute addresses. Copy-protected streams are refused before by hls_guard.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.parse

import hls_guard

AUTO_HEIGHT = 720          # "Automatisch" starts here and steps down when the picture stalls
_ATTR = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')
_CACHE = {}
_LOCK = threading.Lock()
TTL = 45.0


def _attrs(line):
    return {k: v.strip('"') for k, v in _ATTR.findall(line.split(':', 1)[1] if ':' in line else '')}


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parse(text, base):
    """Quality levels of a master playlist, best first. [] for a media playlist."""
    lines = str(text or '').splitlines()
    out = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith('#EXT-X-STREAM-INF'):
            continue
        uri = next((n.strip() for n in lines[i + 1:] if n.strip() and not n.strip().startswith('#')), '')
        if not uri:
            continue
        if not _web(urllib.parse.urljoin(base, uri)):
            continue   # only addresses on the web: the list is later opened by ffmpeg as a local file
        a = _attrs(line)
        width, _, height = a.get('RESOLUTION', '').lower().partition('x')
        codecs = a.get('CODECS', '')
        if codecs and not re.search(r'(?i)avc|hvc|hev|vp0?9|av01', codecs):
            continue   # audio-only level
        out.append({'line': line, 'uri': uri, 'url': urllib.parse.urljoin(base, uri), 'height': _int(height), 'width': _int(width),
                    'bandwidth': _int(a.get('AVERAGE-BANDWIDTH')) or _int(a.get('BANDWIDTH')), 'audio': a.get('AUDIO', ''),
                    'codecs': codecs})
    # the same resolution is often offered several times (other servers, other bitrates): keep the
    # order of the provider within one resolution
    out.sort(key=lambda v: (-(v['height'] or 0), -(v['bandwidth'] or 0)))
    for n, v in enumerate(out):
        v['index'] = n
    return out


def label(variant):
    if variant.get('height'):
        return '%dp' % variant['height']
    if variant.get('bandwidth'):
        return '%.1f Mbit/s' % (variant['bandwidth'] / 1e6)
    return 'Standard'


def levels(variants):
    """What the player offers: one entry per resolution (the lowest bitrate of it), best first."""
    seen, out = set(), []
    for v in sorted(variants, key=lambda v: (-(v['height'] or 0), v['bandwidth'] or 0)):
        key = v['height'] or ('b', v['bandwidth'])
        if key in seen:
            continue
        seen.add(key)
        out.append({'id': str(v['height'] or v['bandwidth'] or 0), 'label': label(v), 'height': v['height'],
                    'bandwidth': v['bandwidth']})
    return out


def choose(variants, quality='auto'):
    """One level for a wish: 'max', 'auto' (up to 720p) or a height such as '480'.

    A height picks the best level that does not exceed it; if every level is larger, the smallest.
    Within one resolution the lowest bitrate wins: it is the one a weak connection can carry."""
    if not variants:
        return None
    wish = str(quality or 'auto').strip().lower()
    by_size = sorted(variants, key=lambda v: (v['height'] or 0, v['bandwidth'] or 0))
    if wish == 'max':
        top = by_size[-1]['height']
        return min((v for v in variants if v['height'] == top), key=lambda v: v['bandwidth'] or 0)
    limit = AUTO_HEIGHT if wish == 'auto' else _int(wish) or AUTO_HEIGHT
    if not any(v['height'] for v in variants):
        # no resolutions announced: treat the wish as a share of the bitrate ladder
        return by_size[-1] if limit >= 1080 else by_size[len(by_size) // 2] if limit >= 720 else by_size[0]
    fitting = [v for v in variants if 0 < v['height'] <= limit]
    if not fitting:
        return by_size[0]
    best = max(v['height'] for v in fitting)
    return min((v for v in fitting if v['height'] == best), key=lambda v: v['bandwidth'] or 0)


def single(text, base, variant):
    """Master playlist with only this level and the audio tracks it refers to; addresses absolute."""
    out = ['#EXTM3U']
    for raw in str(text or '').splitlines():
        line = raw.strip()
        if line.startswith('#EXT-X-VERSION') or line.startswith('#EXT-X-INDEPENDENT-SEGMENTS'):
            out.append(line)
        elif line.startswith('#EXT-X-MEDIA'):
            a = _attrs(line)
            if a.get('TYPE') == 'AUDIO' and variant.get('audio') and a.get('GROUP-ID') == variant['audio'] \
                    and _web(urllib.parse.urljoin(base, a.get('URI') or base)):
                out.append(_absolute(line, base))
    # subtitles and closed captions are not played by the in-app player (ffmpeg runs with -sn)
    stream = re.sub(r',?(?:SUBTITLES|CLOSED-CAPTIONS|VIDEO)=("[^"]*"|[^,]*)', '', variant['line'])
    out += [stream, variant['url'], '']
    return '\n'.join(out)


def _web(url):
    return re.match(r'(?i)^https?://[^\s"]+$', str(url or '')) is not None


def _absolute(line, base):
    return re.sub(r'URI="([^"]*)"', lambda m: 'URI="%s"' % urllib.parse.urljoin(base, m.group(1)), line)


def load(url, fetch=None, now=None):
    """(text, final address, levels) of a master playlist; levels is [] for anything else.
    Answers are kept for a moment because "play" and "stream" ask one after the other."""
    now = time.monotonic() if now is None else now
    with _LOCK:
        hit = _CACHE.get(url)
        if hit and now - hit[0] <= TTL:
            return hit[1]
    text, final = (fetch or hls_guard._fetch)(url)
    if not text.lstrip('﻿').startswith('#EXTM3U'):
        raise ValueError('Der Anbieter lieferte keine HLS-Wiedergabeliste')
    value = (text, final, parse(text, final))
    with _LOCK:
        _CACHE[url] = (now, value)
        for key in [k for k, v in _CACHE.items() if now - v[0] > TTL * 4]:
            _CACHE.pop(key, None)
    return value
