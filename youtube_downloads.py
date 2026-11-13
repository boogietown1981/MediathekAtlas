"""YouTube offline copies, only after an explicit opt-in (0.5.53).

Björn's decision (12.11.2026, decision card "Sollen YouTube-Filme auch 30 Tage offline gespeichert
werden können?"): "Offline als Schalter, Standard aus". YouTube's terms of service forbid
downloading content except through a download function YouTube itself offers (YouTube Premium in
YouTube's apps) or with prior written permission of YouTube and the rights holder. MediathekAtlas
therefore:

* ships the switch OFF; switching it on needs ``confirmed=True`` from a dialog that states the
  terms and that the user acts on their own responsibility; the time of consent is stored;
* never bypasses copy protection, age gates, sign-ins or region blocks (no cookies, no account,
  no geo bypass, no PO-token tricks); a video yt-dlp cannot fetch that way simply fails;
* keeps the same life cycle as every other portal: shared queue, folders and names (core.target),
  MKV with NFO, ``.partial`` staging, 30 days, hourly expiry (netzkino_downloads).

Fetching uses yt-dlp, the maintained successor of youtube-dl (the vendored ytdl-nightly has no
working YouTube extractor any more). Order: MEDIATHEKATLAS_YTDLP, a ``yt-dlp`` on PATH, then a copy
MediathekAtlas installed on request into <data>/tools/yt-dlp (official release zipapp from
github.com/yt-dlp/yt-dlp, checked against the release's SHA2-256SUMS). Video and audio are merged
by ffmpeg into one file; MediathekAtlas then tags it like every other download.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import netzkino_downloads as offline

OFFLINE_DAYS = 30
LICENSE = offline.PORTAL_LICENSES['youtube']
NAME = 'YouTube'
POLICY = ('YouTube erlaubt das Herunterladen laut Nutzungsbedingungen nur über eigene Funktionen oder mit '
          'Erlaubnis von YouTube und Rechteinhaber. Offline-Kopien sind in MediathekAtlas deshalb nur nach '
          'ausdrücklichem Einschalten möglich, auf eigene Verantwortung, %d Tage; danach entfernt '
          'MediathekAtlas die Datei automatisch.' % OFFLINE_DAYS)
CONSENT = ('Ich weiß, dass die YouTube-Nutzungsbedingungen das Herunterladen ohne Erlaubnis von YouTube und '
           'Rechteinhaber untersagen, und speichere YouTube-Filme auf eigene Verantwortung nur für den privaten '
           'Gebrauch für höchstens %d Tage.' % OFFLINE_DAYS)
FORMAT = ('bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=1080]+ba/b[height<=1080]/b')
RELEASE = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/'
TIMEOUT = 6 * 3600
_LOCK = threading.Lock()
_ENABLED = {'value': False}


# ------------------------------------------------------------ the switch

def enabled(root):
    import youtube
    db = youtube._connect(root)
    try:
        value = youtube._get(db, 'offline_enabled', '0') == '1'
    finally:
        db.close()
    _ENABLED['value'] = value
    return value


def enabled_cached():
    return _ENABLED['value']


def set_enabled(root, value, confirmed=False, now=None):
    import youtube
    if type(value) is not bool:
        raise ValueError('Schalter muss ausdrücklich ein- oder ausgeschaltet werden')
    if value and confirmed is not True:
        raise ValueError('Bitte den Hinweis zu den YouTube-Nutzungsbedingungen bestätigen')
    db = youtube._connect(root)
    try:
        with db:
            youtube._set(db, 'offline_enabled', int(value))
            if value:
                youtube._set(db, 'offline_consent', time.time() if now is None else float(now))
    finally:
        db.close()
    _ENABLED['value'] = value
    try:
        import diagnostics
        diagnostics.event('youtube_offline_switch', enabled=value)
    except (ImportError, OSError, RuntimeError):
        pass
    return status(root)


def status(root):
    import youtube
    db = youtube._connect(root)
    try:
        consent = float(youtube._get(db, 'offline_consent', '0') or 0)
    finally:
        db.close()
    tool = find_tool(root)
    return {'enabled': enabled(root), 'consent_at': consent, 'days': OFFLINE_DAYS, 'policy': POLICY,
            'consent_text': CONSENT, 'tool': bool(tool), 'tool_origin': tool[1] if tool else '',
            'tool_hint': '' if tool else 'yt-dlp fehlt. „yt-dlp einrichten“ lädt die offizielle Version von '
                                          'github.com/yt-dlp herunter (einmalig, ca. 3 MB).'}


# ------------------------------------------------------------ yt-dlp

def _managed(root):
    return Path(root) / 'tools' / 'yt-dlp'


def find_tool(root):
    """(argv prefix, origin) of a usable yt-dlp, or None."""
    override = os.environ.get('MEDIATHEKATLAS_YTDLP')
    if override and Path(override).is_file():
        return [override], 'MEDIATHEKATLAS_YTDLP'
    found = shutil.which('yt-dlp')
    if found:
        return [found], 'installiert (' + found + ')'
    managed = _managed(root)
    if managed.is_file():
        return [sys.executable, str(managed)], 'von MediathekAtlas eingerichtet'
    return None


def install_tool(root, fetch=None):
    """Download the official yt-dlp zipapp and verify it against the release checksums."""
    fetch = fetch or (lambda url: urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'MediathekAtlas'}), timeout=60).read(64 * 1024 * 1024))
    with _LOCK:
        sums = fetch(RELEASE + 'SHA2-256SUMS').decode('utf-8', 'replace')
        expected = next((line.split()[0] for line in sums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip('*') == 'yt-dlp'), '')
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Prüfsumme für yt-dlp nicht gefunden')
        data = fetch(RELEASE + 'yt-dlp')
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('yt-dlp-Download beschädigt (Prüfsumme stimmt nicht)')
        target = _managed(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix('.partial')
        tmp.write_bytes(data)
        os.chmod(tmp, 0o700)
        os.replace(tmp, target)
    return status(root)


def _progress(line):
    """(downloaded, total) from yt-dlp's --progress-template line 'MAP <d> <t>'."""
    m = re.match(r'MAP (\d+|NA) (\d+|NA)', line.strip())
    if not m:
        return None
    d, t = (int(x) if x.isdigit() else 0 for x in m.groups())
    return d, t


def _format(row):
    """0.5.63: the resolution chosen before the download ('best' = up to 1080p as before)."""
    wish = row.get('_quality')
    if not wish or wish == 'best':
        return FORMAT
    import download_quality
    return download_quality.youtube_format(wish)


def fetch(row, src, directory, update, cancelled, runner=None):
    """Download one video with yt-dlp into ``src`` (merged by ffmpeg). Returns the size."""
    import downloads, youtube
    root = row['_youtube_home']
    if not enabled(root):
        raise ValueError('YouTube-Offline-Speichern ist ausgeschaltet')
    tool = find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    video = str(row.get('_video_id') or '')
    if not youtube.VALID_VIDEO.fullmatch(video):
        raise ValueError('Ungültiges YouTube-Video')
    downloads.require_space(directory, 2 * 1024 ** 3)
    work = Path(tempfile.mkdtemp(prefix='.yt-', suffix='.partial', dir=str(Path(src).parent)))
    ffmpeg = downloads.tool('ffmpeg')
    args = [*tool[0], '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-cookies-from-browser',
            '--no-mtime', '--no-part', '--newline', '--no-warnings', '-f', _format(row),
            '--merge-output-format', 'mkv', '--progress-template', 'download:MAP %(progress.downloaded_bytes)s %(progress.total_bytes)s',
            '-o', str(work / 'video.%(ext)s')]
    if ffmpeg:
        args += ['--ffmpeg-location', str(ffmpeg)]
    args.append(youtube.video_url(video))
    update('downloading', 0, 0, speed=0, eta=None)
    log = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
    started, done_parts, part_total, received, last = time.monotonic(), 0, 0, 0, 0
    proc = (runner or subprocess.Popen)(args, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL, text=True,
                                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    stop = threading.Event()

    def watch():
        while not stop.wait(1):
            if cancelled() or time.monotonic() - started > TIMEOUT:
                proc.kill()
                return
    threading.Thread(target=watch, name='youtube-cancel', daemon=True).start()
    try:
        prev = 0
        for line in proc.stdout:
            got = _progress(line)
            if not got:
                continue
            d, t = got
            if d < prev:              # next stream (audio after video)
                done_parts += prev
            prev = d
            part_total = max(part_total, t)
            received = done_parts + d
            if time.monotonic() - last > .5:
                speed = received / max(.001, time.monotonic() - started)
                update('downloading', received, done_parts + part_total if part_total else 0, speed=speed,
                       eta=max(0, (part_total - d) / speed) if part_total and speed else None)
                last = time.monotonic()
        code = proc.wait()
        if cancelled():
            raise ValueError('Download abgebrochen')
        if code != 0:
            log.seek(0)
            raise ValueError(_reason(log.read()[-4000:]))
        files = [p for p in work.iterdir() if p.is_file() and p.name.startswith('video.') and p.stat().st_size]
        if not files:
            raise ValueError('yt-dlp lieferte keine Videodatei')
        os.replace(max(files, key=lambda p: p.stat().st_size), src)
        return Path(src).stat().st_size
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
        shutil.rmtree(work, ignore_errors=True)


def _reason(text):
    """yt-dlp error -> short German reason without URLs."""
    low = str(text or '').lower()
    if 'sign in to confirm your age' in low or 'age-restricted' in low or 'inappropriate for some users' in low:
        return 'Altersbeschränktes Video: ohne Anmeldung nicht ladbar (MediathekAtlas meldet sich nicht an)'
    if "sign in to confirm you're not a bot" in low or 'not a bot' in low:
        return 'YouTube verlangt eine Anmeldung („kein Bot“); MediathekAtlas umgeht das nicht. Später erneut versuchen'
    if 'not available in your country' in low or 'geo' in low and 'restrict' in low:
        return 'In Deutschland nicht verfügbar'
    if 'drm' in low:
        return 'Kopiergeschützt (DRM): nicht speicherbar'
    if 'private video' in low or 'video unavailable' in low or 'has been removed' in low:
        return 'Video nicht mehr verfügbar'
    if 'requested format is not available' in low:
        return 'Kein ladbares Format; yt-dlp aktualisieren („yt-dlp einrichten“) oder Deno/Node.js installieren'
    last = [l for l in str(text or '').splitlines() if l.strip()]
    detail = re.sub(r'https?://\S+', '', last[-1] if last else '')[:200]
    return 'yt-dlp meldet einen Fehler' + (': ' + detail.strip() if detail.strip() else '')


# ------------------------------------------------------------ direct playback

SOURCE_TTL = 20 * 60          # resolved stream addresses are reused this long (seeking, "Von vorn")
_SOURCES = {}
_SOURCES_LOCK = threading.Lock()
_GOOGLEVIDEO = re.compile(r'(?i)^https://[a-z0-9.-]+\.(?:googlevideo\.com|youtube\.com)/')


def play_source(root, item_id, quality='auto', runner=None, now=None):
    """0.5.78 (Björn, 13.11.2026: music videos refuse the embedded player, the download works):
    source for MediathekAtlas' own player. yt-dlp resolves the stream addresses of the video the
    same way as for an offline copy (no sign-in, no cookies, nothing copy protected), ffmpeg on the
    server joins picture and sound while playing. Same switch as offline saving: without the
    explicit opt-in nothing is resolved."""
    import youtube, streaming
    if not enabled(root):
        raise ValueError('Im eigenen Player lassen sich YouTube-Videos nur mit eingeschaltetem YouTube-Offline-Schalter abspielen')
    if not youtube.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger YouTube-Titel')
    db = youtube._connect(root)
    try:
        row = youtube._row(db, item_id)
    finally:
        db.close()
    if not row or row['kind'] in ('series', 'album'):
        raise ValueError('YouTube-Video nicht im Katalog; bitte Katalog neu laden')
    if row['reason'].startswith('Altersbeschränkt'):
        raise ValueError('Altersbeschränktes Video: ohne Anmeldung nicht abspielbar')
    limit = streaming.quality_limit(quality)
    now = time.time() if now is None else float(now)
    key = (str(root), item_id, limit)
    with _SOURCES_LOCK:
        hit = _SOURCES.get(key)
    if hit and hit[0] > now:
        return dict(hit[1])
    tool = find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    # H.264 + AAC so that the browser plays the stream without re-encoding; one file as fallback.
    fmt = ('bv*[height<={h}][vcodec^=avc1][protocol^=http]+ba[acodec^=mp4a][protocol^=http]/'
           'b[height<={h}][vcodec^=avc1]/b[vcodec^=avc1]/b').format(h=limit)
    args = [*tool[0], '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-cookies-from-browser',
            '--no-warnings', '-f', fmt, '-g', youtube.video_url(row['path'])]
    try:
        done = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    except subprocess.TimeoutExpired:
        raise ValueError('YouTube hat nicht rechtzeitig geantwortet; bitte erneut versuchen') from None
    except OSError:
        raise ValueError('yt-dlp konnte nicht gestartet werden') from None
    urls = [l.strip() for l in (done.stdout or '').splitlines() if _GOOGLEVIDEO.match(l.strip()) and len(l) < 8000]
    if done.returncode != 0 or not urls:
        raise ValueError(_reason(done.stderr))
    hls = '.m3u8' in urls[0] or '/manifest/hls' in urls[0]
    source = {'kind': 'url', 'url': urls[0], 'audio_url': urls[1] if len(urls) > 1 and not hls else '', 'hls': hls,
              'remux': True, 'provider': 'youtube', 'title': row['title'], 'duration': row['duration'] or 0,
              'quality': 'eigener Player, bis %dp' % limit}
    with _SOURCES_LOCK:
        if len(_SOURCES) > 200:
            _SOURCES.clear()
        _SOURCES[key] = (now + SOURCE_TTL, source)
    return dict(source)


# ------------------------------------------------------------ jobs

def metadata(row, series=None):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('YouTube-Titel ohne Namen')
    source = series or row
    genres = [g.strip() for g in str(source.get('genre') or '').split(',') if g.strip()][:12]
    meta = {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'),
            'season': None, 'episode': None, 'description': row.get('summary') or '',
            'genres': genres, 'poster': row.get('poster') or source.get('poster') or '', 'fanart': '',
            'provider': NAME, 'reference_id': None, 'state': 'manual',
            'reason': 'YouTube-Kanal %s; Offline-Kopie auf eigene Verantwortung, zeitlich begrenzt.' % (row.get('category') or '')}
    if row.get('kind') == 'episode':
        show = ' '.join(str((series or {}).get('title') or '').split())[:180]
        if show and row.get('season') is not None and row.get('episode'):
            meta.update(kind='series', title=show, season=int(row['season']), episode=int(row['episode']),
                        episode_title=title, year=None, show_description=(series or {}).get('summary') or '')
        elif show:
            meta['title'] = (show + ' - ' + title)[:180]
    return meta


MUSIC_FOLDER = 'Musikvideos'


def music_metadata(row, album=None):
    title = ' '.join(str(row.get('title') or '').split())[:180]
    if not title:
        raise ValueError('YouTube-Video ohne Namen')
    return {'kind': 'movie', 'title': title, 'episode_title': '', 'year': row.get('year'), 'season': None,
            'episode': None, 'description': row.get('summary') or '', 'genres': ['Musik'],
            'poster': row.get('poster') or (album or {}).get('poster') or '', 'fanart': '', 'provider': NAME,
            'reference_id': None, 'state': 'manual',
            'reason': 'YouTube-Musikvideo (%s); Offline-Kopie auf eigene Verantwortung, zeitlich begrenzt.'
                      % ((album or {}).get('title') or row.get('category') or NAME)}


def music_target(download_dir, row, album=None):
    from package_media import clean_path_part
    folder = clean_path_part((album or {}).get('title') or row.get('category') or 'Einzelne Videos') or 'YouTube'
    name = clean_path_part(row.get('title') or row.get('path') or 'Video') or 'Video'
    if album and row.get('number') is not None:
        name = '%03d - %s' % (int(row['number']) + 1, name)
    return Path(download_dir) / MUSIC_FOLDER / folder / (name + '.mkv')


def build_job(root, download_dir, item_id, now=None):
    import core, youtube, youtube_enrichment, portal_reference
    if not enabled(root):
        raise ValueError('YouTube-Offline-Speichern ist ausgeschaltet (im YouTube-Bereich einschaltbar)')
    if not youtube.VALID_ID.fullmatch(str(item_id or '')):
        raise ValueError('Ungültiger YouTube-Titel')
    db = youtube._connect(root)
    try:
        row = youtube._row(db, item_id)
        parent = youtube._row(db, row['series_id']) if row and row['series_id'] else None
    finally:
        db.close()
    if not row:
        raise ValueError('YouTube-Titel nicht im Katalog; bitte Katalog neu laden')
    if row['kind'] == 'series':
        raise ValueError('Bitte eine einzelne Folge auswählen; Serien werden folgenweise geladen')
    if row['kind'] == 'album':
        raise ValueError('Bitte „Ganze Playlist offline speichern“ verwenden')
    if row['reason'].startswith('Altersbeschränkt'):
        raise ValueError('Altersbeschränktes Video: ohne Anmeldung nicht ladbar')
    source_id = 'youtube:' + item_id
    if row['kind'] == 'track':
        # 0.5.71: music videos go to <Download>/Musikvideos/<Playlist or channel>/[NNN - ]<Titel>.mkv;
        # no film references (a song has no IMDb entry).
        meta = core.validate_meta(music_metadata(row, parent))
        target = str(music_target(download_dir, row, parent))
    else:
        try:
            report = youtube_enrichment.cached(root, item_id)
        except Exception:
            report = None
        meta = core.validate_meta(portal_reference.apply(metadata(row, parent), report, NAME, series_report=True))
        target = str(core.target(download_dir, meta, source_id))
    source = {'_id': source_id, '_resolver': 'youtube', '_youtube_id': item_id, '_youtube_home': str(root),
              '_video_id': row['path'], 'channel': row.get('category') or NAME, 'title': row['raw_title'] or row['title'],
              'duration': row['duration'], 'url': row['web_url']}
    return {'id': secrets.token_hex(8), 'source': source, 'metadata': meta,
            'root': str(download_dir), 'quality': 'best', 'target': target,
            'state': 'queued', 'received': 0, 'total': 0,
            'origin': 'youtube', 'youtube_id': item_id,
            'license': {'kind': LICENSE, 'days': OFFLINE_DAYS,
                        'granted': time.time() if now is None else float(now),
                        'note': 'YouTube: Offline-Kopie auf eigene Verantwortung (Schalter), %d Tage' % OFFLINE_DAYS}}


def enqueue(c, root, download_dir, item_id, now=None):
    job = build_job(root, download_dir, item_id, now)
    return offline.portal_duplicate(c, job) or offline.insert(c, job)


def enqueue_many(c, root, download_dir, item_ids, now=None):
    """0.5.71: one click for a whole playlist or a selection. Each video is its own job, so pause,
    retry and the 30-day limit work per video; videos already saved or queued are not added twice."""
    if not enabled(root):
        raise ValueError('YouTube-Offline-Speichern ist ausgeschaltet (im YouTube-Bereich einschaltbar)')
    out = {'created': 0, 'existing': 0, 'failed': 0, 'errors': [], 'jobs': []}
    for item_id in list(item_ids)[:500]:
        try:
            result = enqueue(c, root, download_dir, item_id, now)
        except FileExistsError:
            out['existing'] += 1       # already saved earlier: nothing to do
            continue
        except (ValueError, OSError) as exc:
            out['failed'] += 1
            if len(out['errors']) < 5:
                out['errors'].append(str(exc)[:200])
            continue
        out['created' if result.get('created') else 'existing'] += 1
        if result.get('created'):
            out['jobs'].append(result.get('id'))
    return out
