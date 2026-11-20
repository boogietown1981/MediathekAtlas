"""Live streams straight from private news broadcasters: WELT and n-tv (0.6.47).

Björn (20.11.2026, standing order): the Live-TV tab lacked the private news channels. Only public, freely
reachable streams are played here; copy protection is never bypassed.

* WELT: the official live stream of WELT's own CDN (``w-live2weltcms.akamaized.net``, the stream the player
  on welt.de uses; listed by the Free-TV/IPTV project, which only accepts free, official streams). Plain HLS,
  checked with hls_guard before every play like every other source. If it fails or turns out protected, the
  station keeps its link to welt.de and the diagnosis gets a ``sender_live_failed`` entry (station, error
  kind and HTTP status only).
* n-tv: no free official stream address is known (n-tv.de plays its live stream in RTL's own player; no
  free list carries an official address). n-tv is therefore listed as a link to n-tv.de only, like the
  Joyn and RTL+ channels, until a recording from a real browser shows an unprotected stream.

WELT is also a Samsung TV Plus channel; Live-TV merges both under one station (live_tv.STATIONS).
Not checked live from the build machine (welt.de and n-tv.de are not reachable there).
"""
from __future__ import annotations

import re
import time
import urllib.error

KEY = 'sender'
NAME = 'Direkt vom Sender'
SOURCE_TTL = 120
VALID_ID = re.compile(r'[a-z0-9]{2,20}')

# id, title, stream (None = link only), link, summary
STATIONS = (
    ('welt', 'WELT', 'https://w-live2weltcms.akamaized.net/hls/live/2041019/Welt-LivePGM/index.m3u8',
     'https://www.welt.de/tv-programm-live-stream/',
     'Nachrichten, Reportagen und Dokumentationen von WELT, live und kostenlos.'),
    ('ntv', 'n-tv', None, 'https://www.n-tv.de/mediathek/livestream/',
     'Nachrichten und Dokumentationen von n-tv. Der Livestream läuft im Player auf n-tv.de.'),
)
_SOURCES = {}


def _notify(event, **details):
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except (ImportError, OSError, RuntimeError):
        pass


def channels(root=None):
    """Channel rows for live_tv; ``stream`` is True when MediathekAtlas plays the station itself."""
    return [{'id': ident, 'title': title, 'number': number, 'stream': bool(url), 'web_url': link, 'summary': summary,
             'category': 'Nachrichten'}
            for number, (ident, title, url, link, summary) in enumerate(STATIONS, 1)]


def _station(ident):
    ident = str(ident or '')
    if not VALID_ID.fullmatch(ident):
        raise ValueError('Ungültiger Sender')
    for row in STATIONS:
        if row[0] == ident:
            return row
    raise ValueError('Sender nicht bekannt')


def play_source(root, ident, check=None, now=None):
    """Source for streaming.plan: the official HLS stream after the copy-protection check."""
    import hls_guard
    ident, title, url, link, _ = _station(ident)
    if not url:
        raise ValueError('%s bietet keinen frei abspielbaren Livestream an. Bitte auf %s ansehen.' % (title, link))
    now = time.time() if now is None else now
    cached = _SOURCES.get(ident)
    if not (cached and cached[0] > now):
        try:
            (check or hls_guard.check)(url)
        except hls_guard.DrmProtected:
            _notify('sender_live_failed', station=ident, error_type='drm', http_status=0)
            raise
        except urllib.error.HTTPError as exc:
            _notify('sender_live_failed', station=ident, error_type='http', http_status=exc.code)
            raise ValueError('%s-Livestream gerade nicht abrufbar (HTTP %d). Bitte auf %s ansehen.'
                             % (title, exc.code, link)) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            import netcheck
            _notify('sender_live_failed', station=ident, error_type=netcheck.kind(exc), http_status=0)
            raise ValueError(netcheck.with_cause('%s-Livestream ist nicht erreichbar' % title, exc)
                             + '. Bitte auf %s ansehen.' % link) from None
        _SOURCES[ident] = (now + SOURCE_TTL, url)
    return {'kind': 'url', 'url': url, 'hls': True, 'quality': '%s live (kostenlos)' % title, 'title': title,
            'duration': 0, 'provider': KEY, 'live': True}


def summary(root=None):
    return {'channels': len(STATIONS), 'playable': sum(1 for s in STATIONS if s[2])}
