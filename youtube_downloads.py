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
import json
import os
import platform
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
# 0.6.160 (Mac-Prüfung B1, 27.11.2026): yt-dlp 2026.10.26/2026.11.06 with its bundled challenge solver
# (yt-dlp-ejs 0.8.0) failed on YouTube's current player ("n challenge solving failed", Deno: "TypeError:
# a.addOnDisposeCallback is not a function"); kids videos only have the web/web_embedded way and then
# end in "This video is not available". When the newest stable release is not newer, the official
# nightly build (same assets and checksum file) is used until a newer stable one follows.
NIGHTLY = 'https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/'
CHALLENGE = ('n challenge solving failed', 'error solving n challenge', 'sig function', 'challenge solving failed')
REFRESH_GAP = 12 * 3600        # at most one automatic yt-dlp update per half day
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
    js = find_js_runtime(root)
    old = bool(tool) and not _js_ok(tool)
    hint = ('' if tool else 'yt-dlp fehlt. „yt-dlp einrichten“ lädt die offizielle Version von '
                            'github.com/yt-dlp herunter (einmalig, ca. 3 MB).')
    if tool and not js:
        hint = ('Deno fehlt: Ohne JavaScript-Laufzeit kann yt-dlp Kindervideos („Made for Kids“) und manche '
                'Formate nicht laden. „Deno einrichten“ lädt die offizielle Version von github.com/denoland '
                '(einmalig, ca. 40 MB).')
    elif old:
        hint = ('yt-dlp ist zu alt für Kindervideos („Made for Kids“). „yt-dlp einrichten“ lädt eine aktuelle '
                'Version in MediathekAtlas (ein über Homebrew installiertes yt-dlp: „brew upgrade yt-dlp“).')
    return {'enabled': enabled(root), 'consent_at': consent, 'days': OFFLINE_DAYS, 'policy': POLICY,
            'consent_text': CONSENT, 'tool': bool(tool), 'tool_origin': tool[1] if tool else '',
            'js_runtime': ('%s (%s)' % js) if js else '', 'tool_current': bool(tool) and not old,
            'tool_hint': hint}


# ------------------------------------------------------------ yt-dlp

def _managed(root):
    return Path(root) / 'tools' / 'yt-dlp'


# 0.6.36 (Björn, 19.11.2026): "Anna und die wilden Tiere" (BR, Kinderkanal) scheiterte immer mit
# "This video is not available". yt-dlp ohne JavaScript-Laufzeit fragt YouTube nur über den Client
# "visionos" an, und der liefert keine "Made for Kids"-Videos; der Ausweg über "web_embedded" braucht
# eine JS-Laufzeit (yt-dlp: Deno von Haus aus, Node/Bun mit --js-runtimes).
JS_RUNTIMES = ('deno', 'node', 'bun')
JS_DIRS = ('/opt/homebrew/bin', '/usr/local/bin', '~/.deno/bin', '~/.bun/bin', '/usr/bin')
DENO_RELEASE = 'https://github.com/denoland/deno/releases/latest/download/'


def _deno_managed(root):
    return Path(root) / 'tools' / 'deno' / ('deno.exe' if os.name == 'nt' else 'deno')


def find_js_runtime(root):
    """(name, path) of a JavaScript runtime yt-dlp can use, or None. The app's own Deno first."""
    managed = _deno_managed(root) if root is not None else None
    if managed is not None and managed.is_file():
        return 'deno', str(managed)
    for name in JS_RUNTIMES:
        found = shutil.which(name)
        if not found:
            # Started from Finder, the app has no Homebrew PATH.
            found = next((str(Path(d).expanduser() / name) for d in JS_DIRS
                          if os.access(str(Path(d).expanduser() / name), os.X_OK)), None)
        if found:
            return name, found
    return None


def js_args(root, tool=None):
    """--js-runtimes for yt-dlp, only if the yt-dlp in use knows the option (else it would stop at once)."""
    js = find_js_runtime(root)
    tool = tool or find_tool(root)
    # --remote-components: if this yt-dlp lacks its bundled solver scripts (yt-dlp-ejs, e.g. a pip install),
    # it may fetch them from yt-dlp's GitHub releases; with the scripts present it uses its own.
    return ['--js-runtimes', '%s:%s' % js, '--remote-components', 'ejs:github'] if js and tool and _js_ok(tool) else []


def _deno_asset():
    machine = platform.machine().lower()
    arch = 'aarch64' if machine in ('arm64', 'aarch64') else 'x86_64' if machine in ('x86_64', 'amd64') else ''
    system = {'darwin': 'apple-darwin', 'linux': 'unknown-linux-gnu', 'windows': 'pc-windows-msvc'}.get(platform.system().lower(), '')
    if not arch or not system or (system == 'pc-windows-msvc' and arch != 'x86_64'):
        return ''
    return 'deno-%s-%s.zip' % (arch, system)


def install_js_runtime(root, fetch=None):
    """Download the official Deno build and verify it against its published SHA-256."""
    import zipfile, io
    asset = _deno_asset()
    if not asset:
        raise ValueError('Für dieses System gibt es keine offizielle Deno-Version; bitte Node.js installieren')
    fetch = fetch or (lambda url: urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'MediathekAtlas'}), timeout=120).read(160 * 1024 * 1024))
    with _LOCK:
        line = fetch(DENO_RELEASE + asset + '.sha256sum').decode('utf-8', 'replace').split()
        expected = line[0].lower() if line else ''
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Prüfsumme für Deno nicht gefunden')
        data = fetch(DENO_RELEASE + asset)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Deno-Download beschädigt (Prüfsumme stimmt nicht)')
        target = _deno_managed(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist() if Path(n).name == target.name), None)
            if not name:
                raise ValueError('Deno-Archiv ohne Programmdatei')
            tmp = target.with_name(target.name + '.partial')
            tmp.write_bytes(z.read(name))
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)
    return status(root)


JS_MIN_VERSION = (2025, 11, 12)   # first yt-dlp with --js-runtimes (EJS)
_VERSIONS = {}


def tool_version(argv):
    """yt-dlp's version as a tuple (cached per program file and its change time), () if unknown."""
    path = argv[-1]
    try:
        key = (path, os.stat(path).st_mtime)
    except OSError:
        return ()
    if key not in _VERSIONS:
        try:
            out = subprocess.run([*argv, '--version'], capture_output=True, text=True, timeout=30,
                                 stdin=subprocess.DEVNULL).stdout
            _VERSIONS[key] = tuple(int(x) for x in re.findall(r'\d+', out.strip().split()[0])[:3]) if out.strip() else ()
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            _VERSIONS[key] = ()
    return _VERSIONS[key]


def find_tool(root):
    """(argv prefix, origin) of a usable yt-dlp, or None.

    0.6.36: an installed yt-dlp older than JS_MIN_VERSION cannot use a JavaScript runtime; the app's own,
    newer copy (if set up) is preferred then."""
    override = os.environ.get('MEDIATHEKATLAS_YTDLP')
    if override and Path(override).is_file():
        return [override], 'MEDIATHEKATLAS_YTDLP'
    managed = _managed(root)
    own = ([sys.executable, str(managed)], 'von MediathekAtlas eingerichtet') if managed.is_file() else None
    found = shutil.which('yt-dlp')
    if found:
        system = ([found], 'installiert (' + found + ')')
        version = tool_version(system[0])
        # 0.6.160: the app's own copy also wins when it is newer (set up after a challenge failure)
        if own and version and (version < JS_MIN_VERSION or (tool_version(own[0]) or ()) > version):
            return own
        return system
    return own


def _js_ok(tool):
    version = tool_version(tool[0])
    return bool(version) and version >= JS_MIN_VERSION


def install_tool(root, fetch=None, js_fetch=None):
    """yt-dlp (official zipapp, checksum verified) and, if no JavaScript runtime is there, Deno.

    The button stays one: "yt-dlp einrichten" also renews the app's own yt-dlp (YouTube changes often)."""
    tool = find_tool(root)
    if not tool or tool[1] == 'von MediathekAtlas eingerichtet' or not _js_ok(tool):
        _install_ytdlp(root, fetch)
    if not find_js_runtime(root):
        try:
            install_js_runtime(root, js_fetch)
        except (OSError, ValueError) as e:
            # yt-dlp itself is set up; Deno is reported, not fatal (most videos load without it).
            return {**status(root), 'js_error': 'Deno konnte nicht eingerichtet werden: ' + str(e)[:200]}
    return status(root)


def _refresh_state(root):
    try:
        return json.loads((Path(root) / 'tools' / 'yt-dlp-refresh.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_refresh_state(root, state):
    path = Path(root) / 'tools' / 'yt-dlp-refresh.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.partial')
    tmp.write_text(json.dumps(state), encoding='utf-8')
    os.replace(tmp, path)


def challenge_failed(text):
    """yt-dlp could not solve YouTube's player challenge (solver script older than the player)."""
    low = str(text or '').lower()
    return any(x in low for x in CHALLENGE)


def refresh_for_challenge(root, tool=None, fetch=None, now=None, force=False):
    """0.6.160: after a challenge failure update the app's own yt-dlp (stable, else nightly), at most every
    REFRESH_GAP. Returns the new version as text, '' if nothing was done or nothing newer was found."""
    now = time.time() if now is None else float(now)
    state = _refresh_state(root)
    if not force and 'at' in state and now - float(state.get('at') or 0) < REFRESH_GAP:
        return ''
    before = tool_version(tool[0]) if tool else ()
    state['at'] = now                    # recorded first: a failing download never loops into updates
    _save_refresh_state(root, state)
    own = [sys.executable, str(_managed(root))]
    channel = state.get('channel') or 'stable'
    try:
        if channel == 'stable':
            _install_ytdlp(root, fetch)
            if (tool_version(own) or ()) <= before:
                channel = 'nightly'
        if channel == 'nightly':
            _install_ytdlp(root, fetch, release=NIGHTLY)
    except (OSError, ValueError) as e:
        try:
            import diagnostics
            diagnostics.event('youtube_ytdlp_refresh_failed', 'WARNING', channel=channel, error=str(e)[:200])
        except Exception:
            pass
        return ''
    after = tool_version(own) or ()
    if after <= before:
        return ''
    state.update(channel=channel, version='.'.join(map(str, after)))
    _save_refresh_state(root, state)
    _REFRESHED['version'] = state['version']
    try:
        import diagnostics
        diagnostics.event('youtube_ytdlp_refreshed', channel=channel, before='.'.join(map(str, before)), after=state['version'])
    except Exception:
        pass
    return state['version']


_REFRESHED = {'version': ''}
# 0.6.163 (Air-Diagnose 27.11.: 8 Abo-Videos, 17 Meldungen, 0 Erfolge): "not available" for several different
# videos in a row is one systemic failure (old yt-dlp, address refused), not one per video. After STREAK_VIDEOS
# different videos without a success in between, the whole source pauses (download_retry block) with one message.
_STREAK = {'videos': set(), 'at': 0.0}
STREAK_VIDEOS = 2
STREAK_WINDOW = 6 * 3600


def _not_available_streak(video, now=None):
    """Record a "not available" failure; True once STREAK_VIDEOS different videos failed in a row."""
    now = time.time() if now is None else float(now)
    with _LOCK:
        if now - _STREAK['at'] > STREAK_WINDOW:
            _STREAK['videos'] = set()
        _STREAK['videos'].add(str(video))
        _STREAK['at'] = now
        return len(_STREAK['videos']) >= STREAK_VIDEOS


def _streak_reset():
    with _LOCK:
        _STREAK['videos'], _STREAK['at'] = set(), 0.0


def _video_of(text):
    """Video id from a bare id or any YouTube video address ('' if none)."""
    import youtube
    value = str(text or '').strip()
    if youtube.VALID_VIDEO.fullmatch(value):
        return value
    try:
        ref = youtube.parse_ref(value)
    except ValueError:
        return ''
    return ref[2:] if ref.startswith('v:') else ''


def _simulate(root, tool, video, runner=None):
    """yt-dlp -s (no download) for one video: (returncode, challenge failed, clients, last ERROR line)."""
    import youtube
    args = [*tool[0], '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-cookies-from-browser', '-s',
            *js_args(root, tool), youtube.video_url(video)]
    try:
        done = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    except subprocess.TimeoutExpired:
        return None, False, [], 'YouTube hat nicht rechtzeitig geantwortet'
    out, err = str(done.stdout or ''), str(done.stderr or '')
    clients = []
    for line in (out + '\n' + err).splitlines():
        c = _client(line)
        if c and c not in clients:
            clients.append(c)
    errors = [URL.sub('<url>', l.strip())[:240] for l in err.splitlines() if l.startswith('ERROR:')]
    return done.returncode, challenge_failed(err), clients, errors[-1] if errors else ''


def check_access(root, video, fetch=None, runner=None):
    """0.6.161 ("YouTube-Zugang prüfen", Mac-Prüfung 0.6.160): simulate one video with the yt-dlp in use;
    if YouTube's player challenge fails, renew yt-dlp at once (button = explicit, no 12-hour pause) and
    simulate again. Downloads nothing. The caller re-queues "not available" jobs when it ends well."""
    video = _video_of(video)
    if not video:
        raise ValueError('Bitte eine YouTube-Video-ID oder Videoadresse angeben')
    tool = find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    js = find_js_runtime(root)
    before = '.'.join(map(str, tool_version(tool[0])))
    code, challenge, clients, error = _simulate(root, tool, video, runner)
    result = {'video': video, 'tool_version': before, 'js_runtime': js[0] if js else '', 'js_args': bool(js_args(root, tool)),
              'challenge_failed': challenge, 'clients': clients, 'ok': code == 0, 'error': error, 'refreshed': ''}
    if challenge and result['js_args']:
        result['refreshed'] = refresh_for_challenge(root, tool, fetch=fetch, force=True)
        if result['refreshed']:
            tool = find_tool(root)
            code, challenge, clients, error = _simulate(root, tool, video, runner)
            result.update(tool_version='.'.join(map(str, tool_version(tool[0]))), challenge_failed=challenge,
                          clients=clients, ok=code == 0, error=error)
    if result['ok']:
        # 0.6.163: access proven – lift the pause a series of "not available" failures had set
        _streak_reset()
        import download_retry
        download_retry.clear('youtube')
        result['message'] = 'YouTube liefert das Video mit yt-dlp %s%s' % (result['tool_version'],
                             ' (eben aktualisiert von %s)' % before if result['refreshed'] else '')
    elif not js:
        result['message'] = 'Deno fehlt: im YouTube-Bereich „Deno einrichten“ (%s)' % (error or 'kein Ergebnis')
    elif result['challenge_failed']:
        result['message'] = ('yt-dlp %s kann YouTubes Player noch nicht entschlüsseln; es gibt noch keine neuere '
                             'Ausgabe, MediathekAtlas versucht es automatisch wieder' % result['tool_version'])
    else:
        result['message'] = 'YouTube liefert das Video nicht: ' + (_reason(error) if error else 'kein Ergebnis')
    try:
        import diagnostics
        diagnostics.event('youtube_access_check', **{k: v for k, v in result.items() if k != 'message'})
    except Exception:
        pass
    return result


def take_refreshed():
    """Version set up by refresh_for_challenge since the last call ('' if none), for re-queueing jobs."""
    version, _REFRESHED['version'] = _REFRESHED['version'], ''
    return version


def _install_ytdlp(root, fetch=None, release=None):
    """Download the official yt-dlp zipapp and verify it against the release checksums.

    0.6.160: ``release`` – NIGHTLY once the stable release could not solve YouTube's challenge; the
    button then stays on that channel (see _refresh_state)."""
    release = release or (NIGHTLY if _refresh_state(root).get('channel') == 'nightly' else RELEASE)
    fetch = fetch or (lambda url: urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'MediathekAtlas'}), timeout=60).read(64 * 1024 * 1024))
    with _LOCK:
        sums = fetch(release + 'SHA2-256SUMS').decode('utf-8', 'replace')
        expected = next((line.split()[0] for line in sums.splitlines()
                         if len(line.split()) == 2 and line.split()[1].lstrip('*') == 'yt-dlp'), '')
        if not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Prüfsumme für yt-dlp nicht gefunden')
        data = fetch(release + 'yt-dlp')
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
    import download_retry
    work = Path(tempfile.mkdtemp(prefix='.yt-', suffix='.partial', dir=str(Path(src).parent)))
    ffmpeg = downloads.tool('ffmpeg')
    # 0.6.159 (Air-Diagnose 27.11., B1): yt-dlp's warnings are kept (they go to the error log, never to the
    # screen) – they say which YouTube client answered and why a video was refused; "--no-warnings" hid that.
    jsargs = js_args(root, tool)
    args = [*tool[0], '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-cookies-from-browser',
            '--no-mtime', '--no-part', '--newline', '-f', _format(row),
            '--merge-output-format', 'mkv', '--progress-template', 'download:MAP %(progress.downloaded_bytes)s %(progress.total_bytes)s',
            '-o', str(work / 'video.%(ext)s'), *jsargs]
    if row.get('_container') == 'mp4' or row.get('_abo'):
        # 0.6.13: subscription videos come in batches; short pauses between YouTube's requests make the
        # bot check ("Sign in to confirm you're not a bot") less likely. A single click stays immediate.
        args += ['--sleep-requests', str(SLEEP_REQUESTS), '--sleep-interval', str(SLEEP_MIN), '--max-sleep-interval', str(SLEEP_MAX)]
    if row.get('_abo'):
        # 0.6.90: the description (one small text file, no extra request) names related channels (youtube_discover)
        args.append('--write-description')
    if ffmpeg:
        args += ['--ffmpeg-location', str(ffmpeg)]
    args.append(youtube.video_url(video))
    update('downloading', 0, 0, speed=0, eta=None, note=PHASES[0][1])
    log = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
    started, done_parts, part_total, received, last = time.monotonic(), 0, 0, 0, 0
    proc = (runner or subprocess.Popen)(args, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL, text=True,
                                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    stop = threading.Event()
    # 0.6.13 (Björn, 16.11.2026: "0.0 MiB · Geschwindigkeit wird ermittelt" for good): the watcher also
    # ends a download that receives nothing. Before the first byte yt-dlp may take a while (video page,
    # player, pauses), so that limit is longer than the one for a stalled transfer.
    state = {'bytes': 0, 'moved': time.monotonic(), 'phase': PHASES[0][1], 'stalled': '', 'told': time.monotonic(), 'clients': []}

    def watch():
        while not stop.wait(1):
            now = time.monotonic()
            if cancelled() or now - started > TIMEOUT:
                proc.kill()
                return
            quiet = now - state['moved']
            limit = STALL_START if not state['bytes'] else STALL
            if quiet > limit:
                state['stalled'] = ('YouTube liefert seit %d Minuten keine Daten' % round(quiet / 60)) if state['bytes'] else \
                    ('YouTube hat nach %d Minuten noch keine Daten geschickt (%s)' % (round(quiet / 60), state['phase']))
                proc.kill()
                return
            if not state['bytes'] and quiet > 60 and now - state['told'] >= 30:
                state['told'] = now
                update('downloading', 0, 0, speed=0, eta=None,
                       note='%s · wartet seit %d Min.; nach %d Min. ohne Daten neuer Versuch später'
                            % (state['phase'], quiet // 60, STALL_START // 60))
    threading.Thread(target=watch, name='youtube-cancel', daemon=True).start()
    try:
        prev = 0
        for line in proc.stdout:
            got = _progress(line)
            if not got:
                client = _client(line)
                if client and client not in state['clients']:
                    state['clients'].append(client)
                phase = _phase(line)
                if phase and phase != state['phase']:
                    state['phase'] = phase
                    update('downloading', received, done_parts + part_total if part_total else 0, speed=0, eta=None, note=phase)
                continue
            d, t = got
            if d < prev:              # next stream (audio after video)
                done_parts += prev
            prev = d
            part_total = max(part_total, t)
            received = done_parts + d
            if received > state['bytes']:
                state['bytes'], state['moved'] = received, time.monotonic()
            if time.monotonic() - last > .5:
                speed = received / max(.001, time.monotonic() - started)
                update('downloading', received, done_parts + part_total if part_total else 0, speed=speed,
                       eta=max(0, (part_total - d) / speed) if part_total and speed else None, note='')
                last = time.monotonic()
        code = proc.wait()
        if cancelled():
            raise ValueError('Download abgebrochen')
        if state['stalled']:
            # 0.6.165 (Air-Diagnose 27.11. abends, Y5): YouTube drosselt auf fast null, wenn yt-dlp die n-challenge
            # nicht löst; der Stillstand-Wächter brach ab, bevor das Protokoll ausgewertet wurde. Jetzt auch hier
            # erkennen und yt-dlp erneuern (wie beim Fehler-Ende).
            message = state['stalled']
            try:
                log.seek(0)
                text = log.read()[-4000:]
                if jsargs and challenge_failed(text):
                    newer = refresh_for_challenge(root, tool)
                    message += (' – yt-dlp konnte YouTubes Player nicht entschlüsseln („n challenge“); ' +
                                ('yt-dlp %s eingerichtet, neuer Versuch in Kürze' % newer if newer else
                                 'eine neuere yt-dlp-Version wird automatisch geholt, sobald es eine gibt'))
                    _report_failure(row, video, tool, find_js_runtime(root), jsargs, state['clients'], text, True, True)
            except Exception:                # the stall itself stays the reported failure
                pass
            raise download_retry.RetryLater(message)
        if code != 0:
            log.seek(0)
            text = log.read()[-4000:]
            js = find_js_runtime(root)
            # warnings are kept for the diagnosis only: the reason comes from yt-dlp's ERROR lines, so a warning
            # mentioning e.g. a timeout or a geo note cannot change how the failure is judged
            errors = '\n'.join(line for line in text.splitlines() if line.startswith('ERROR:')) or text
            message, retry, block = _failure(errors, js_runtime=bool(js), js_used=bool(jsargs))
            challenge = bool(jsargs) and challenge_failed(text)
            if challenge:
                newer = refresh_for_challenge(root, tool)
                message = ('yt-dlp konnte YouTubes aktuellen Player nicht entschlüsseln („n challenge“); ' +
                           ('MediathekAtlas hat yt-dlp %s eingerichtet, neuer Versuch in Kürze' % newer if newer else
                            'eine neuere yt-dlp-Version wird automatisch geholt, sobald es eine gibt') +
                           ' (YouTube: „%s“)' % ('This video is not available' if 'this video is not available'
                                                 in errors.lower() else _reason(errors)[:80]))
                retry, block = True, False
            if retry and not block and not challenge and 'this video is not available' in errors.lower() \
                    and _not_available_streak(video):   # n-challenge: yt-dlp is renewed instead (0.6.160)
                block = True
                message = ('YouTube gibt seit mehreren Videos nichts heraus („This video is not available“); '
                           'YouTube-Downloads pausieren, statt jedes Video einzeln zu versuchen – im YouTube-Bereich '
                           'lässt sich mit „YouTube-Zugang prüfen“ sofort nachsehen')
            _report_failure(row, video, tool, js, jsargs, state['clients'], text, retry, challenge)
            if retry:
                raise download_retry.RetryLater(message, block=block)
            raise ValueError(message)
        described = work / 'video.description'
        if row.get('_abo') and described.is_file():
            try:
                import youtube_discover
                youtube_discover.record_mentions(root, video, described.read_text(encoding='utf-8', errors='replace')[:20000])
            except Exception:                    # never fail a finished download because of suggestions
                pass
        files = [p for p in work.iterdir() if p.is_file() and p.name.startswith('video.') and p.suffix != '.description' and p.stat().st_size]
        if not files:
            raise ValueError('yt-dlp lieferte keine Videodatei')
        os.replace(max(files, key=lambda p: p.stat().st_size), src)
        _streak_reset()
        return Path(src).stat().st_size
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log.close()
        shutil.rmtree(work, ignore_errors=True)


STALL_START = 10 * 60        # bis zum ersten Byte
STALL = 5 * 60               # danach ohne Zuwachs
SLEEP_REQUESTS = 1           # Sekunden zwischen den Anfragen eines Abo-Downloads
SLEEP_MIN, SLEEP_MAX = 5, 20 # Sekunden vor jedem Abo-Download (gestreut)
PHASES = (
    ('', 'Verbindung zu YouTube wird aufgebaut'),
    ('downloading webpage', 'Videoseite wird abgerufen'),
    ('player api json', 'Videodaten werden abgefragt'),
    ('downloading player', 'YouTube-Player wird ausgewertet'),
    ('n challenge', 'YouTube-Player wird ausgewertet'),
    ('downloading m3u8', 'Formate werden abgefragt'),
    ('sleeping', 'Kurze Pause zur Schonung (YouTube bremst sonst)'),
    ('downloading 1 format', 'Download startet'),
    ('[merger]', 'Bild und Ton werden zusammengeführt'),
)


def _phase(line):
    """Readable step from a yt-dlp status line (shown while no bytes arrive)."""
    low = str(line or '').lower()
    for needle, text in PHASES[1:]:
        if needle in low:
            return text
    return ''


CLIENT_LINE = re.compile(r'downloading ([a-z0-9_ ]+?) (?:client config|player api json|tv client config)', re.I)
URL = re.compile(r'https?://\S+')


def _client(line):
    """YouTube client yt-dlp asked ("Downloading tv client config", "… web safari player API JSON")."""
    m = CLIENT_LINE.search(str(line or ''))
    return m.group(1).strip().lower().replace(' ', '_')[:30] if m else ''


def _report_failure(row, video, tool, js, jsargs, clients, text, retry, challenge=False):
    """0.6.159 (B1): one diagnostic event per failed YouTube download with everything needed to tell a
    refused kids video from a bot block or an unused JavaScript runtime. No addresses (they carry tokens)."""
    try:
        import diagnostics
        lines = [URL.sub('<url>', line.strip())[:240] for line in str(text or '').splitlines()
                 if line.startswith(('WARNING:', 'ERROR:'))][-6:]
        diagnostics.event('youtube_download_failed', 'WARNING', video=video, abo=row.get('_abo') or None,
                          retry=bool(retry), js_runtime=js[0] if js else '', js_args=bool(jsargs),
                          tool_origin=str(tool[1])[:80], tool_version='.'.join(map(str, tool_version(tool[0]))),
                          clients=clients[:8], challenge_failed=bool(challenge), messages=lines)
    except Exception:                    # diagnostics must never turn into a second failure
        pass


def _failure(text, js_runtime=None, js_used=None):
    """(reason, temporary, provider-wide pause) for yt-dlp's error output (0.6.13).

    0.6.159: ``js_runtime``/``js_used`` – whether a JavaScript runtime exists and was handed to yt-dlp;
    the "Deno einrichten" advice is only given when it can help (None = unknown, the old wording)."""
    low = str(text or '').lower()
    reason = _reason(text)
    if "not a bot" in low or 'http error 429' in low or 'too many requests' in low:
        if 'not a bot' not in low:
            reason = 'YouTube bremst gerade (zu viele Anfragen)'
        return reason, True, True
    if any(x in low for x in TEMPORARY):
        return reason, True, False
    if 'this video is not available' in low:
        # 0.6.19 (Björns Diagnose 0.6.18): after the bot check every one of 18 videos failed with this text
        # within minutes, none succeeded – YouTube's answer to a flagged address, not a removed video
        # (that says "Video unavailable"/"Private video"). Retried with growing gaps; given up after the series.
        # 0.6.36: also every "Made for Kids" video when yt-dlp has no JavaScript runtime (see JS_RUNTIMES).
        # 0.6.159 (Air 27.11., B1): Deno was set up, yet the advice still sent Björn to "Deno einrichten".
        if js_runtime is False:
            return ('YouTube gibt das Video gerade nicht heraus („This video is not available“: meist ein Kindervideo, '
                    'das ohne Deno nicht lädt; im YouTube-Bereich „Deno einrichten“)'), True, False
        if js_runtime and js_used is False:
            return ('YouTube gibt das Video gerade nicht heraus („This video is not available“); yt-dlp ist zu alt, '
                    'um Deno zu nutzen: im YouTube-Bereich „yt-dlp einrichten“'), True, False
        if js_runtime and js_used:
            # 0.6.163 (Björn 27.11.: „viele Botwarnungen, obwohl wir kaum laden“): this text is no bot check –
            # a real one says "confirm you're not a bot" and is handled above. No "Bot" in the wording.
            return ('YouTube gibt das Video gerade nicht heraus („This video is not available“: Kindervideo, regional '
                    'gesperrt oder vorübergehend verweigert; Deno ist eingerichtet, neuer Versuch später)'), True, False
        return ('YouTube gibt das Video gerade nicht heraus („This video is not available“: Kindervideo, regional '
                'gesperrt oder vorübergehend verweigert; ohne Deno laden Kindervideos nicht)'), True, False
    return reason, False, False


TEMPORARY = ('timed out', 'timeout', 'connection reset', 'connection aborted', 'connection refused',
             'temporary failure in name resolution', 'name or service not known', 'network is unreachable',
             'remote end closed', 'incompleteread', 'http error 500', 'http error 502', 'http error 503',
             'http error 504', 'unable to download video data', 'giving up after', 'read operation timed out')


def _reason(text):
    """yt-dlp error -> short German reason without URLs."""
    low = str(text or '').lower()
    if 'sign in to confirm your age' in low or 'age-restricted' in low or 'inappropriate for some users' in low:
        return 'Altersbeschränktes Video: ohne Anmeldung nicht ladbar (MediathekAtlas meldet sich nicht an)'
    if "sign in to confirm you're not a bot" in low or 'not a bot' in low:
        return 'YouTube verlangt eine Anmeldung („kein Bot“); MediathekAtlas meldet sich nicht an'
    if 'http error 429' in low or 'too many requests' in low:
        return 'YouTube bremst gerade (zu viele Anfragen)'
    if 'timed out' in low or 'timeout' in low:
        return 'YouTube antwortet nicht rechtzeitig (Netz oder YouTube langsam)'
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
    if row.get('drm'):
        raise ValueError('Kopiergeschützter YouTube-Film: läuft nur bei YouTube')
    if row['reason'].startswith('Altersbeschränkt'):
        raise ValueError('Altersbeschränktes Video: ohne Anmeldung nicht abspielbar')
    # 0.5.89 (Björn, 13.11.2026: smooth now, but only 480p): since 0.5.86 the pieces arrive at full
    # speed, so "Automatisch" goes up to 1080p like youtube.com instead of the general 720p.
    wish = str(quality or 'auto').strip().lower()
    limit = AUTO_HEIGHT if wish in ('', 'auto') else MAX_HEIGHT if wish == 'max' else streaming.quality_limit(quality)
    now = time.time() if now is None else float(now)
    key = (str(root), item_id, limit)
    with _SOURCES_LOCK:
        hit = _SOURCES.get(key)
    if hit and hit[0] > now:
        return dict(hit[1])
    tool = find_tool(root)
    if not tool:
        raise ValueError('yt-dlp fehlt; im YouTube-Bereich „yt-dlp einrichten“ wählen')
    args = [*tool[0], '--ignore-config', '--no-playlist', '--no-cache-dir', '--no-cookies-from-browser',
            '-f', FORMAT.format(h=limit), '-S', SORT.format(h=limit), *js_args(root, tool), '-j', youtube.video_url(row['path'])]
    try:
        done = (runner or subprocess.run)(args, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    except subprocess.TimeoutExpired:
        raise ValueError('YouTube hat nicht rechtzeitig geantwortet; bitte erneut versuchen') from None
    except OSError:
        raise ValueError('yt-dlp konnte nicht gestartet werden') from None
    urls, headers, height = _stream_urls(done.stdout)
    if done.returncode != 0 or not urls:
        # 0.6.160: warnings are no longer suppressed (stderr only); the reason comes from the ERROR lines
        errors = '\n'.join(l for l in str(done.stderr or '').splitlines() if l.startswith('ERROR:')) or done.stderr
        if challenge_failed(done.stderr) and refresh_for_challenge(root, tool):
            raise ValueError('yt-dlp wurde für YouTubes neuen Player aktualisiert; bitte noch einmal abspielen')
        raise ValueError(_reason(errors))
    hls = '.m3u8' in urls[0] or '/manifest/hls' in urls[0]
    # 0.5.86 (Björn, 13.11.2026: stutters, picture and sound out of step; diagnosis: 1.8 Mbit/s, first
    # data after 8 s): YouTube serves one open-ended request only at about playback speed. 'ranged'
    # sends both addresses through range_relay, which loads them in 4 MB pieces like youtube.com.
    # 'server_only': the addresses are bound to the server's IP and never go to the browser (also HLS).
    # 'files': heights YouTube offers, for the player's "Qualität" menu (0.5.89).
    source = {'kind': 'url', 'url': urls[0], 'audio_url': urls[1] if len(urls) > 1 and not hls else '', 'hls': hls,
              'remux': True, 'server_only': True, 'ranged': not hls, 'headers': headers, 'provider': 'youtube',
              'title': row['title'], 'duration': row['duration'] or 0, 'files': _heights(done.stdout), 'auto_height': AUTO_HEIGHT,
              'quality': 'eigener Player, %s' % ('%dp' % height if height else 'bis %dp' % limit)}
    with _SOURCES_LOCK:
        if len(_SOURCES) > 200:
            _SOURCES.clear()
        _SOURCES[key] = (now + SOURCE_TTL, source)
    return dict(source)


_HEADER_NAMES = {'user-agent', 'accept', 'accept-language', 'origin', 'referer'}

# 0.5.89 (Björn, 13.11.2026: "Take My Breath Away" smooth, but only 480p). Until 0.5.88 the first
# alternative demanded H.264 as separate HTTPS file. Without a sign-in YouTube often offers those
# files only up to 480p; the higher levels exist as HLS (H.264 with sound in one stream) or as VP9.
# yt-dlp took the first alternative that matched at all (480p) instead of the highest picture.
# Now: picture H.264 or VP9 (the browser plays both from MP4, ffmpeg only copies), sound AAC; the
# order (-S) is resolution up to the limit first, then H.264 before VP9 (Safari is surest with
# H.264), then HTTPS before HLS.
AUTO_HEIGHT = 1080
MAX_HEIGHT = 2160
VIDEO_CODECS = r"^(avc1|vp0?9)"
FORMAT = ("bv*[height<={h}][vcodec~='" + VIDEO_CODECS + "']+ba[acodec^=mp4a]/"
          "b[height<={h}][vcodec^=avc1]/bv*[vcodec~='" + VIDEO_CODECS + "']+ba[acodec^=mp4a]/b")
SORT = 'res:{h},vcodec:h264,proto,acodec:aac'


def _heights(stdout):
    """Picture heights (>=240) of the formats the own player can play, highest first."""
    try:
        info = json.loads(str(stdout or '').strip().splitlines()[0])
    except (ValueError, IndexError):
        return []
    found = set()
    for f in info.get('formats') or []:
        h, codec = f.get('height'), str(f.get('vcodec') or '')
        if isinstance(h, (int, float)) and 240 <= h <= MAX_HEIGHT and re.match(VIDEO_CODECS, codec) and str(f.get('protocol') or '').startswith(('http', 'm3u8')):
            found.add(int(h))
    return sorted(found, reverse=True)


def _stream_urls(stdout):
    """(addresses, request headers, picture height) from yt-dlp. 0.5.86: -j (JSON) instead of -g, so the
    headers yt-dlp would send with the addresses come along (some YouTube clients require their own
    User-Agent). Lines with bare addresses (older output) are still understood."""
    text = str(stdout or '').strip()
    if text.startswith('{'):
        try:
            info = json.loads(text.splitlines()[0])
        except ValueError:
            info = {}
        formats = info.get('requested_formats') or [info]
        urls = [str(f.get('url') or '') for f in formats]
        urls = [u for u in urls if _GOOGLEVIDEO.match(u) and len(u) < 8000]
        raw = (formats[0].get('http_headers') if formats else None) or info.get('http_headers') or {}
        headers = {str(k): str(v)[:400] for k, v in raw.items() if str(k).lower() in _HEADER_NAMES}
        height = next((int(f.get('height')) for f in formats if isinstance(f.get('height'), (int, float)) and f.get('height')), 0)
        return urls, headers, height
    urls = [l.strip() for l in text.splitlines() if _GOOGLEVIDEO.match(l.strip()) and len(l) < 8000]
    return urls, {}, 0


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
    import core
    from package_media import clean_path_part
    # 0.6.44: tidy names (core.tidy_name); an existing playlist folder keeps its old name.
    label = (album or {}).get('title') or row.get('category') or 'Einzelne Videos'
    folder = clean_path_part(label) or 'YouTube'
    if not (Path(download_dir) / MUSIC_FOLDER / folder).is_dir():
        folder = clean_path_part(core.tidy_name(label)) or 'YouTube'
    name = clean_path_part(core.tidy_name(row.get('title') or row.get('path') or 'Video')) or 'Video'
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
    if row.get('drm'):
        raise ValueError('Kopiergeschützter YouTube-Film: kein Offline-Speichern, läuft nur bei YouTube')
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
