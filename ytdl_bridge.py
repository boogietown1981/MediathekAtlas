"""ytdl-nightly bridge: resolve a Netzkino film page to its progressive MP4 file.

ytdl-nightly (github.com/boogietown1981/ytdl-nightly, a youtube-dl nightly build)
is vendored under vendor/ytdl_nightly. Its own NetzkinoIE still targets the
retired ``netzkino.de/#!/`` API, so MediathekAtlas registers a current extractor
for ``netzkino.de/details/<slug>`` on top of ytdl-nightly's InfoExtractor
(page download, Next.js parsing, geo/DRM error handling).

This module only *resolves* the file address. The download itself, the MKV
container, NFO/metadata sidecars and the file names are produced by the regular
Mediathek download pipeline (downloads.run / core.target), so Netzkino titles
are stored exactly like Mediathek videos.

Rules: DRM-protected titles are refused, HLS/DASH are not used, no cookies or
accounts, no geo bypass. Resolved addresses are never logged.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import urllib.parse
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / 'vendor' / 'ytdl_nightly'
PAGE_RE = re.compile(r'^https://(?:www\.)?netzkino\.de/details/(?P<id>[A-Za-z0-9._~-]{2,150})$')
PMD_BASE = 'https://pmd.netzkino-seite.netzkino.de/'
_LOCK = threading.Lock()
_CACHE = {}


class ResolveError(ValueError):
    """User-facing, URL-free German error message."""


def _vendor_info(base):
    try:
        return json.loads((base / 'VENDOR.json').read_text('utf-8'))
    except (OSError, ValueError):
        return {}


def load():
    """Import youtube_dl from an explicit checkout or the vendored copy (cached).

    MEDIATHEKATLAS_YTDL_DIR may point to a local ytdl-nightly checkout (the
    folder that contains ``youtube_dl``) to test a newer nightly without a build.
    """
    with _LOCK:
        if 'module' in _CACHE:
            return _CACHE['module']
        candidates = []
        override = os.environ.get('MEDIATHEKATLAS_YTDL_DIR')
        if override:
            candidates.append(Path(override).expanduser())
        candidates.append(VENDOR)
        last_error = None
        for base in candidates:
            if not (base / 'youtube_dl' / '__init__.py').is_file():
                continue
            if 'youtube_dl' in sys.modules:
                module = sys.modules['youtube_dl']
            else:
                sys.path.insert(0, str(base))
                try:
                    import youtube_dl as module  # noqa: E402
                except Exception as exc:  # broken checkout: try the next one
                    last_error = exc
                    sys.path.remove(str(base))
                    continue
            from youtube_dl.version import __version__
            _CACHE['module'] = module
            _CACHE['info'] = {'ok': True, 'version': __version__, 'path': str(base),
                              'source': 'override' if base != VENDOR else 'vendored',
                              'commit': _vendor_info(base).get('commit', '')}
            return module
        _CACHE['info'] = {'ok': False, 'version': None, 'path': None,
                          'error': 'ytdl-nightly nicht gefunden' if last_error is None
                          else 'ytdl-nightly konnte nicht geladen werden'}
        raise ResolveError('ytdl-nightly ist in dieser Installation nicht verfügbar')


def status():
    try:
        load()
    except ResolveError:
        pass
    return dict(_CACHE.get('info') or {'ok': False})


def page_url(value):
    value = str(value or '').strip()
    if not PAGE_RE.fullmatch(value):
        raise ResolveError('Nur Netzkino-Filmseiten (netzkino.de/details/…) können offline geladen werden')
    return 'https://www.netzkino.de/details/' + PAGE_RE.fullmatch(value).group('id')


def _iter_dehydrated(next_data):
    queries = (((next_data or {}).get('props') or {}).get('__dehydratedState') or {}).get('queries')
    for query in queries if isinstance(queries, list) else []:
        data = (((query or {}).get('state') or {}).get('data') or {})
        inner = data.get('data') if isinstance(data, dict) else None
        if isinstance(inner, dict):
            yield from (v for v in inner.values() if isinstance(v, dict))


def movie_node(next_data):
    """The CmsMovie/CmsEpisode object of a Netzkino details page, or None."""
    for node in _iter_dehydrated(next_data):
        if node.get('__typename') in ('CmsMovie', 'CmsEpisode'):
            return node
    return None


def is_drm(node):
    nodes = ((node or {}).get('licenses') or {}).get('nodes')
    for lic in nodes if isinstance(nodes, list) else []:
        props = (lic or {}).get('properties')
        values = props if isinstance(props, list) else [props]
        if any(isinstance(v, str) and 'DRM' in v.upper() for v in values):
            return True
    return False


def file_url(node):
    """Progressive MP4 address from videoSource.pmdUrl; HLS/DASH are not used."""
    raw = ((node or {}).get('videoSource') or {}).get('pmdUrl')
    if not isinstance(raw, str) or not raw.strip():
        return None
    url = urllib.parse.urljoin(PMD_BASE, raw.strip())
    p = urllib.parse.urlsplit(url)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or not p.path.lower().endswith('.mp4')):
        return None
    return url


def _extractor_class(ytdl):
    if 'ie' in _CACHE:
        return _CACHE['ie']
    from youtube_dl.extractor.common import InfoExtractor
    from youtube_dl.utils import ExtractorError

    class MediathekAtlasNetzkinoIE(InfoExtractor):
        IE_NAME = 'netzkino:mediathekatlas'
        _VALID_URL = r'https?://(?:www\.)?netzkino\.de/details/(?P<id>[^/?#]+)'
        _GEO_COUNTRIES = ['DE']

        def _real_extract(self, url):
            video_id = self._match_id(url)
            webpage = self._download_webpage(url, video_id)
            node = movie_node(self._search_nextjs_data(webpage, video_id))
            if node is None:
                raise ExtractorError('Netzkino-Seite enthält keine Filmdaten', expected=True)
            if is_drm(node):
                self.report_drm(video_id)
            media = file_url(node)
            if not media:
                raise ExtractorError('Keine direkte MP4-Datei veröffentlicht', expected=True)
            def number(key):
                try:
                    return int(node.get(key))
                except (TypeError, ValueError):
                    return None
            return {'id': video_id, 'url': media, 'ext': 'mp4',
                    'title': node.get('title') or node.get('originalTitle') or video_id,
                    'duration': number('runtimeInSeconds'),
                    'release_year': number('productionYear'),
                    'age_limit': number('fskRating')}

    _CACHE['ie'] = MediathekAtlasNetzkinoIE
    return MediathekAtlasNetzkinoIE


def _error(exc):
    text = str(getattr(exc, 'msg', '') or exc)
    original = (getattr(exc, 'exc_info', None) or (None, None))[1] or exc
    name = type(original).__name__
    if name == 'GeoRestrictedError' or 'geo' in text.lower() and 'restrict' in text.lower():
        return ResolveError('Netzkino liefert diesen Titel nur innerhalb Deutschlands aus')
    if 'DRM' in text:
        return ResolveError('Titel ist DRM-geschützt; Wiedergabe und Download sind nur beim Anbieter möglich')
    if 'HTTP Error 404' in text:
        return ResolveError('Titel ist bei Netzkino nicht mehr verfügbar (HTTP 404)')
    if 'HTTP Error' in text:
        return ResolveError('Netzkino antwortet mit ' + re.search(r'HTTP Error \d+', text).group(0))
    if 'Unable to download webpage' in text or name in ('URLError', 'timeout', 'TimeoutError'):
        return ResolveError('Netzkino ist nicht erreichbar (Netzwerk/Proxy prüfen)')
    if 'Keine direkte MP4-Datei' in text:
        return ResolveError('Netzkino veröffentlicht für diesen Titel keine direkte MP4-Datei')
    if 'keine Filmdaten' in text or 'next.js data' in text:
        return ResolveError('Netzkino-Seite wurde geändert; Filmdaten nicht gefunden (ytdl-nightly aktualisieren)')
    return ResolveError('Netzkino-Adresse konnte nicht aufgelöst werden')


def resolve(url, *, ytdl=None, quality='best'):
    """Return {'url','title','duration',...} for one Netzkino details page."""
    page = page_url(url)
    ytdl = ytdl or load()
    ie_class = _extractor_class(ytdl)

    class _Quiet:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    ydl = ytdl.YoutubeDL({'quiet': True, 'no_warnings': True, 'noplaylist': True,
                          'socket_timeout': 25, 'logger': _Quiet(), 'skip_download': True,
                          'geo_bypass': False, 'call_home': False}, auto_init=False)
    ie = ie_class()
    ydl.add_info_extractor(ie)
    try:
        info = ydl.extract_info(page, download=False, ie_key=ie.ie_key())
    except Exception as exc:  # youtube_dl wraps extractor errors in DownloadError
        raise _error(exc) from None
    media = info.get('url') or ((info.get('formats') or [{}])[-1]).get('url')
    if quality and quality != 'best':
        # 0.5.63: a resolution chosen before the download, when Netzkino publishes several MP4 files
        import download_quality
        chosen = download_quality.pick_format(info.get('formats'), quality)
        if chosen:
            media = chosen['url']
    if not isinstance(media, str) or not media.lower().split('?', 1)[0].endswith('.mp4'):
        raise ResolveError('Netzkino veröffentlicht für diesen Titel keine direkte MP4-Datei')
    return {'url': media, 'page_url': page, 'title': info.get('title') or '',
            'duration': info.get('duration'), 'year': info.get('release_year'),
            'fsk': info.get('age_limit'), 'extractor': ie.IE_NAME,
            'ytdl_version': (_CACHE.get('info') or {}).get('version')}
