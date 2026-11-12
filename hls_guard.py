"""Copy-protection check for HLS sources before playback or an offline copy (0.5.40).

MediathekAtlas only plays and stores streams that any standard HLS player can open without
a DRM licence. A playlist that announces Widevine, PlayReady, FairPlay or SAMPLE-AES
(``#EXT-X-KEY`` / ``#EXT-X-SESSION-KEY`` with such a KEYFORMAT or METHOD) is refused; nothing
is circumvented. Plain AES-128 with the standard ``identity`` key format is ordinary HLS and
allowed. The master playlist and its first variant are read (size-limited, HTTPS only).
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

MAX_PLAYLIST = 2 * 1024 * 1024
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')
DRM_MESSAGE = ('Dieser Stream ist kopiergeschützt (DRM). MediathekAtlas spielt ihn nicht ab und speichert ihn '
               'nicht; bitte beim Anbieter ansehen.')
_ATTR = re.compile(r'([A-Z0-9\-]+)=("[^"]*"|[^,]*)')
_ALLOWED_METHODS = {'NONE', 'AES-128'}


class DrmProtected(ValueError):
    pass


def _attrs(line):
    return {k: v.strip('"') for k, v in _ATTR.findall(line.split(':', 1)[1] if ':' in line else '')}


def protection(text):
    """'' when the playlist is usable, otherwise the reason (e.g. 'SAMPLE-AES')."""
    for line in str(text or '').splitlines():
        line = line.strip()
        if not (line.startswith('#EXT-X-KEY') or line.startswith('#EXT-X-SESSION-KEY')):
            continue
        a = _attrs(line)
        method = a.get('METHOD', 'NONE').upper()
        keyformat = a.get('KEYFORMAT', 'identity').lower()
        if method not in _ALLOWED_METHODS:
            return method
        if method != 'NONE' and keyformat != 'identity':
            return keyformat
        if a.get('URI', '').lower().startswith('skd:') and method != 'NONE':
            return 'skd'
    return ''


def variants(text, base):
    out = []
    lines = str(text or '').splitlines()
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF'):
            for nxt in lines[i + 1:]:
                nxt = nxt.strip()
                if nxt and not nxt.startswith('#'):
                    out.append(urllib.parse.urljoin(base, nxt))
                    break
    return out


def _fetch(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Unerwartete Stream-Adresse')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=20) as response:
        final = response.geturl()
        if urllib.parse.urlsplit(final).scheme != 'https':
            raise ValueError('Unerwartete Stream-Adresse')
        data = response.read(MAX_PLAYLIST + 1)
    if len(data) > MAX_PLAYLIST:
        raise ValueError('Wiedergabeliste zu groß')
    return data.decode('utf-8', 'replace'), final


def check(url, fetch=None):
    """Raise DrmProtected for protected streams, ValueError for non-HLS answers."""
    fetch = fetch or _fetch
    text, final = fetch(url)
    if not text.lstrip('﻿').startswith('#EXTM3U'):
        raise ValueError('Der Anbieter lieferte keine HLS-Wiedergabeliste')
    reason = protection(text)
    found = variants(text, final)
    if not reason and found:
        sub, _ = fetch(found[0])
        reason = protection(sub)
    if reason:
        raise DrmProtected(DRM_MESSAGE)
    return {'variants': len(found), 'protected': False}

