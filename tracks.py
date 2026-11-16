"""Choice of audio track and subtitles in the in-app player (0.6.6).

Björn (14.11.2026, Plex title marked OmU): the stream played German with subtitles, but the
subtitles were neither shown nor selectable. Until 0.6.5 the player showed no subtitles at all:
ffmpeg ran with ``-sn`` and the browser never got a text track; hls.js loaded subtitle playlists,
but nothing let the viewer switch them on.

hls.js mode chooses audio and subtitles itself (web/player.js reads ``audioTracks`` and
``subtitleTracks``). Everything else is answered here:

* ``list_tracks(source)``: the audio tracks and subtitles of the source that is played through
  ffmpeg or directly (DASH from Plex, HLS through ffmpeg, broadcaster MP4 files, local files).
  Subtitles come from the provider (Plex sidecar files, the broadcaster's subtitle file of a
  Mediathek offer), from the DASH manifest (text adaptation sets with one file), from the HLS
  master playlist (WebVTT segment lists) or from the file itself (text subtitles, sidecar files).
  Audio tracks of an online stream come from ffprobe (DASH) or the master playlist (HLS).
* ``subtitle_vtt(source, track, offset)``: one subtitle as WebVTT, shifted by ``offset`` seconds
  (the remuxed stream restarts at the chosen position and begins at 0 again). SRT, WebVTT and
  TTML/EBU-TT (ARD, ZDF) are converted; image subtitles (PGS, DVB) are not offered.
* ``audio_index(source, track)``: the audio stream for ``ffmpeg -map 0:a:<n>``.

Nothing is decoded or circumvented: these are the provider's own text files. Standard library only.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import languages

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
MAX_TEXT = 8 * 1024 * 1024         # one subtitle file
MAX_SEGMENTS = 3000
MAX_TRACKS = 16
TTL = 600.0
TEXT_CODECS = {'subrip', 'srt', 'webvtt', 'mov_text', 'ass', 'ssa', 'text'}
SIDE_SUFFIXES = ('.srt', '.vtt')   # .ass would need a converter
_CACHE = {}
_LOCK = threading.Lock()


def _cached(key, make):
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] <= TTL:
            return hit[1]
    value = make()
    with _LOCK:
        _CACHE[key] = (now, value)
        for k in [k for k, v in _CACHE.items() if now - v[0] > TTL * 2]:
            _CACHE.pop(k, None)
    return value


def _get(url, headers=None, limit=MAX_TEXT):
    parts = urllib.parse.urlsplit(str(url or ''))
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Unerwartete Untertitel-Adresse')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*', **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as response:
        final = response.geturl()
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Untertiteldatei zu groß')
    return data, final


def _label(lang, name='', extra=''):
    c = languages.code(lang) or languages.code(name)
    base = languages.label(c) if c else (' '.join(str(name or '').split())[:40] or 'Unbekannte Sprache')
    if name and c and languages.code(name) != c and len(str(name)) <= 40 and str(name).casefold() != base.casefold():
        base += ' · ' + ' '.join(str(name).split())
    return base + (' · ' + extra if extra else ''), c


# --- manifests ------------------------------------------------------------------------------------

_ATTR = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')


def hls_tracks(text, base):
    """Audio renditions (order of the first audio group) and subtitle playlists of a master playlist."""
    audio, subs, group = [], [], None
    for raw in str(text or '').splitlines():
        line = raw.strip()
        if not line.startswith('#EXT-X-MEDIA:'):
            continue
        a = {k: v.strip('"') for k, v in _ATTR.findall(line.split(':', 1)[1])}
        kind = a.get('TYPE', '').upper()
        if kind == 'AUDIO':
            group = group or a.get('GROUP-ID')
            if a.get('GROUP-ID') == group:
                audio.append({'lang': a.get('LANGUAGE', ''), 'name': a.get('NAME', ''),
                              'ad': 'describes-video' in a.get('CHARACTERISTICS', '')})
        elif kind == 'SUBTITLES' and a.get('URI'):
            subs.append({'lang': a.get('LANGUAGE', ''), 'name': a.get('NAME', ''),
                         'url': urllib.parse.urljoin(base, a['URI']), 'format': 'hls-vtt',
                         'forced': a.get('FORCED', '').upper() == 'YES'})
    return audio, subs


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def dash_tracks(text, base):
    """Audio adaptation sets and text adaptation sets with one file (BaseURL) of an MPD."""
    try:
        root = ET.fromstring(str(text or '').encode('utf-8'))
    except ET.ParseError:
        return [], []
    audio, subs = [], []

    def base_of(node, current):
        for child in node:
            if _local(child.tag) == 'BaseURL' and (child.text or '').strip():
                return urllib.parse.urljoin(current, child.text.strip())
        return current
    root_base = base_of(root, base)
    for period in [n for n in root if _local(n.tag) == 'Period'][:1]:
        pbase = base_of(period, root_base)
        for aset in [n for n in period if _local(n.tag) == 'AdaptationSet']:
            mime = (aset.get('mimeType') or '').lower()
            ctype = (aset.get('contentType') or '').lower()
            reps = [n for n in aset if _local(n.tag) == 'Representation']
            mime = mime or (reps[0].get('mimeType') or '').lower() if reps else mime
            lang = aset.get('lang') or ''
            label = next((n.get('value') or (n.text or '') for n in aset if _local(n.tag) == 'Label'), '') or \
                next(((n.text or '') for n in aset if _local(n.tag) == 'Label'), '')
            roles = {(n.get('value') or '').lower() for n in aset if _local(n.tag) in ('Role', 'Accessibility')}
            if ctype == 'audio' or mime.startswith('audio/'):
                # ffmpeg (dashdec) makes one stream per representation, in manifest order
                audio.append({'lang': lang, 'name': label, 'ad': 'description' in roles, 'reps': max(1, len(reps))})
            elif ctype == 'text' or mime.startswith('text/') or 'ttml' in mime or 'vtt' in mime:
                abase = base_of(aset, pbase)
                for rep in reps[:1] or [aset]:
                    url = base_of(rep, abase)
                    if url == abase and url == pbase:
                        continue      # segmented text (SegmentTemplate): not offered
                    fmt = 'ttml' if 'ttml' in mime or url.lower().split('?')[0].endswith(('.ttml', '.xml', '.dfxp')) else \
                        'srt' if url.lower().split('?')[0].endswith('.srt') else 'vtt'
                    subs.append({'lang': lang, 'name': label, 'url': url, 'format': fmt,
                                 'forced': 'forced-subtitle' in roles or 'forced_subtitle' in roles})
    return audio, subs


def _probe(target, headers=None):
    """ffprobe streams of a file or an online address (DASH, MP4); [] without ffprobe."""
    import streaming
    binary = streaming.tool('ffprobe')
    if not binary:
        return []
    args = [binary, '-v', 'error', '-show_streams', '-of', 'json']
    if headers and str(target).startswith('http'):
        args += ['-headers', ''.join('%s: %s\r\n' % kv for kv in headers.items())]
    try:
        r = subprocess.run(args + [str(target)], capture_output=True, timeout=25)
        return json.loads(r.stdout).get('streams', []) if not r.returncode else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


# --- listing --------------------------------------------------------------------------------------

def _collect(source):
    """Internal list: (audio entries, subtitle entries) with addresses; cached per source."""
    kind = source.get('kind')
    key = (kind, source.get('path') or source.get('url') or '', tuple(sorted((s.get('url') or '') for s in source.get('subtitles') or [])))

    def make():
        audio, subs = [], []
        for s in (source.get('subtitles') or [])[:MAX_TRACKS]:
            if s.get('url'):
                subs.append({'lang': s.get('lang', ''), 'name': s.get('name', ''), 'url': s['url'],
                             'format': s.get('format') or 'auto', 'origin': s.get('origin') or 'provider',
                             'forced': bool(s.get('forced'))})
        if kind == 'file':
            path = Path(source['path'])
            streams = _probe(path)
            for n, st in enumerate(s for s in streams if s.get('codec_type') == 'audio'):
                audio.append({'lang': (st.get('tags') or {}).get('language', ''), 'name': (st.get('tags') or {}).get('title', ''),
                              'index': n})
            text = [s for s in streams if s.get('codec_type') == 'subtitle']
            for n, st in enumerate(text):
                if st.get('codec_name') in TEXT_CODECS:
                    subs.append({'lang': (st.get('tags') or {}).get('language', ''), 'name': (st.get('tags') or {}).get('title', ''),
                                 'file': str(path), 'index': n, 'format': 'ffmpeg', 'origin': 'file'})
            for side in sorted(path.parent.glob(glob_escape(path.stem) + '*'))[:MAX_TRACKS]:
                if side.suffix.lower() in SIDE_SUFFIXES and side != path:
                    tail = side.name[len(path.stem):-len(side.suffix)].strip('.-_ ')
                    subs.append({'lang': tail, 'name': tail, 'file': str(side), 'format': side.suffix.lower()[1:],
                                 'origin': 'file'})
        elif kind == 'url':
            url = source.get('url') or ''
            headers = source.get('headers') or None
            try:
                if source.get('hls'):
                    import hls_variants
                    text, final = hls_variants.load(url)[:2]
                    a, s = hls_tracks(text, final)
                    audio += [dict(x, index=n) for n, x in enumerate(a)]
                    subs += [dict(x, origin='stream') for x in s]
                elif re.search(r'(?i)\.mpd(?:\?|$)', url) or source.get('dash'):
                    raw, final = _get(url, headers, limit=4 * 1024 * 1024)
                    a, s = dash_tracks(raw.decode('utf-8', 'replace'), final)
                    subs += [dict(x, origin='stream') for x in s]
                    n = 0
                    for x in a:
                        audio.append(dict(x, index=n))
                        n += x['reps']
            except Exception:
                pass
        return audio[:MAX_TRACKS], subs[:MAX_TRACKS]
    return _cached(key, make)


def glob_escape(text):
    return re.sub(r'([*?\[\]])', r'[\1]', text)


def list_tracks(source):
    """What the player may offer: {'audio': [{id,label,lang,ad}], 'subtitles': [{id,label,lang,forced}]}.
    Audio is listed only when there is more than one track (the first is played by default)."""
    audio, subs = _collect(source)
    out_a, out_s = [], []
    for n, a in enumerate(audio):
        text, c = _label(a.get('lang'), a.get('name'), 'Audiodeskription' if a.get('ad') else '')
        out_a.append({'id': 'a%d' % n, 'label': text, 'lang': c, 'ad': bool(a.get('ad'))})
    for n, s in enumerate(subs):
        extra = 'nur fremdsprachige Stellen' if s.get('forced') else 'vom Sender' if s.get('origin') == 'provider' and source.get('provider') in (None, '', 'mediathek') else ''
        text, c = _label(s.get('lang'), s.get('name'), extra)
        out_s.append({'id': 's%d' % n, 'label': text, 'lang': c, 'forced': bool(s.get('forced'))})
    # A remuxed HLS stream is read from a one-level playlist (streaming.prepare): alternative audio
    # renditions are not part of it, so no choice is offered there (hls.js offers its own).
    many = len(out_a) > 1 and not source.get('hls')
    return {'audio': out_a if many else [], 'subtitles': out_s}


def observed(source):
    """Languages of the tracks for languages.remember (stream evidence)."""
    audio, subs = _collect(source)
    out = {}
    a = [c for c in (languages.code(x.get('lang')) or languages.code(x.get('name')) for x in audio) if c]
    s = [c for c in (languages.code(x.get('lang')) or languages.code(x.get('name')) for x in subs) if c]
    if a:
        out['audio'] = list(dict.fromkeys(a))
    if s:
        out['subtitles'] = list(dict.fromkeys(s))
    if any(x.get('ad') for x in audio):
        out['accessibility'] = [languages.ACCESS_AD]
    return out


def audio_index(source, track):
    """Index for ``-map 0:a:<n>`` or None (default track)."""
    m = re.fullmatch(r'a(\d{1,2})', str(track or ''))
    if not m:
        return None
    if source.get('hls'):
        return None
    audio, _ = _collect(source)
    n = int(m.group(1))
    return audio[n]['index'] if n < len(audio) else None


# --- conversion -----------------------------------------------------------------------------------

_TIME = re.compile(r'(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})')


def _seconds(text):
    m = _TIME.fullmatch(text.strip())
    if not m:
        raise ValueError(text)
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, '0')[:3]) / 1000


def _stamp(sec):
    sec = max(0.0, sec)
    ms = int(round(sec * 1000))
    return '%02d:%02d:%02d.%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def cues_from_vtt(text):
    """[(start, end, text)] of a WebVTT or SRT text."""
    out = []
    blocks = re.split(r'\n\s*\n', str(text or '').replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿'))
    for block in blocks:
        lines = [l for l in block.split('\n')]
        idx = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if idx is None:
            continue
        left, _, right = lines[idx].partition('-->')
        try:
            start, end = _seconds(left), _seconds(right.strip().split(' ')[0])
        except ValueError:
            continue
        body = '\n'.join(lines[idx + 1:]).strip()
        if body:
            out.append((start, end, body))
    return out


def _ttml_time(value, rate=25.0, tick=None):
    value = (value or '').strip()
    if not value:
        return None
    m = re.fullmatch(r'([\d.]+)(h|ms|m|s|f|t)', value)
    if m:
        n, unit = float(m.group(1)), m.group(2)
        return {'h': n * 3600, 'm': n * 60, 's': n, 'ms': n / 1000, 'f': n / rate, 't': n / (tick or 10000000)}[unit]
    m = re.fullmatch(r'(\d+):(\d{2}):(\d{2})(?:([.:])(\d+))?', value)
    if m:
        h, mi, s, sep, frac = m.groups()
        base = int(h) * 3600 + int(mi) * 60 + int(s)
        if frac:
            base += int(frac) / rate if sep == ':' else float('0.' + frac)
        return base
    return None


def cues_from_ttml(raw):
    """[(start, end, text)] of a TTML/EBU-TT-D/DFXP file (ARD, ZDF, arte, Plex)."""
    try:
        root = ET.fromstring(raw if isinstance(raw, bytes) else str(raw).encode('utf-8'))
    except ET.ParseError:
        return []
    rate = 25.0
    tick = None
    for k, v in root.attrib.items():
        if _local(k) == 'frameRate':
            try:
                rate = float(v)
            except ValueError:
                pass
        elif _local(k) == 'tickRate':
            try:
                tick = float(v)
            except ValueError:
                pass
    out = []

    def text_of(node):
        parts = [node.text or '']
        for child in node:
            parts.append('\n' if _local(child.tag) == 'br' else text_of(child))
            parts.append(child.tail or '')
        return ''.join(parts)

    def attr(node, name):
        return next((v for k, v in node.attrib.items() if _local(k) == name), None)
    for p in root.iter():
        if _local(p.tag) != 'p':
            continue
        start, end = _ttml_time(attr(p, 'begin'), rate, tick), _ttml_time(attr(p, 'end'), rate, tick)
        if start is None:
            continue
        if end is None:
            dur = _ttml_time(attr(p, 'dur'), rate, tick)
            end = start + (dur or 2.0)
        body = '\n'.join(' '.join(l.split()) for l in text_of(p).split('\n'))
        body = '\n'.join(l for l in body.split('\n') if l).strip()
        if body:
            out.append((start, end, html.escape(body, quote=False)))
    return out


def to_vtt(cues, offset=0.0):
    lines = ['WEBVTT', '']
    for start, end, body in sorted(cues, key=lambda c: c[0]):
        start, end = start - offset, end - offset
        if end <= 0:
            continue
        lines += ['%s --> %s' % (_stamp(start), _stamp(end)), body.replace('-->', '->'), '']
    return '\n'.join(lines) + '\n'


def _hls_cues(url, headers):
    raw, final = _get(url, headers, limit=2 * 1024 * 1024)
    text = raw.decode('utf-8', 'replace')
    segs = [urllib.parse.urljoin(final, l.strip()) for l in text.splitlines() if l.strip() and not l.startswith('#')]
    if not segs:
        return cues_from_vtt(text)
    cues, total = [], 0
    for seg in segs[:MAX_SEGMENTS]:
        data, _ = _get(seg, headers, limit=2 * 1024 * 1024)
        total += len(data)
        if total > MAX_TEXT:
            break
        cues += cues_from_vtt(data.decode('utf-8', 'replace'))
    seen, out = set(), []
    for c in cues:                       # a cue spanning two segments is repeated in both
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _decode(data):
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('cp1252', 'replace')


def _cues(entry, headers):
    fmt = entry.get('format') or 'auto'
    if entry.get('file'):
        path = Path(entry['file'])
        if fmt == 'ffmpeg':
            import streaming
            binary = streaming.tool('ffmpeg')
            if not binary:
                raise ValueError('ffmpeg fehlt')
            r = subprocess.run([binary, '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:s:%d' % entry['index'],
                                '-f', 'webvtt', 'pipe:1'], capture_output=True, timeout=120)
            if r.returncode:
                raise ValueError('Untertitel ließ sich nicht auslesen')
            return cues_from_vtt(_decode(r.stdout))
        data = path.read_bytes()[:MAX_TEXT]
        return cues_from_ttml(data) if fmt in ('ttml', 'xml') else cues_from_vtt(_decode(data))
    if fmt == 'hls-vtt':
        return _hls_cues(entry['url'], headers)
    data, _ = _get(entry['url'], headers)
    head = data[:400].lstrip().lower()
    if fmt in ('ttml', 'xml', 'dfxp') or (fmt == 'auto' and head.startswith((b'<?xml', b'<tt', b'<!--'))):
        return cues_from_ttml(data)
    return cues_from_vtt(_decode(data))


def subtitle_vtt(source, track, offset=0.0):
    m = re.fullmatch(r's(\d{1,2})', str(track or ''))
    if not m:
        raise ValueError('Unbekannte Untertitelspur')
    _, subs = _collect(source)
    n = int(m.group(1))
    if n >= len(subs):
        raise ValueError('Untertitel nicht mehr vorhanden; Player neu öffnen')
    entry = subs[n]
    key = ('cues', entry.get('url') or entry.get('file'), entry.get('index'))
    cues = _cached(key, lambda: _cues(entry, source.get('headers') or None))
    if not cues:
        raise ValueError('Die Untertiteldatei enthält keinen lesbaren Text')
    return to_vtt(cues, max(0.0, float(offset or 0)))
