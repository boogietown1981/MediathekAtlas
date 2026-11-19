"""Einstellbare Speicherorte mit sicherem Umzug (0.6.20).

Björn (16.11.2026): In den Einstellungen sollen drei Speicherorte getrennt festgelegt werden
können: Downloads, Zwischenspeicher (YouTube-Abo-Videos) und System/Datenbank. Beim Ändern eines
Pfads sollen die vorhandenen Daten an den neuen Ort übernommen werden. Anlass: auf dem MacBook
Air waren nur noch 2,6 GB frei (Datenbanksicherung scheiterte, IMDb-Archiv 21,8 GB).

Ablauf eines Umzugs (alle drei Arten gleich):

1. Prüfen: Ziel absolut, nicht ineinander verschachtelt, Elternordner vorhanden (ein abgezogenes
   Laufwerk wird nie neu angelegt), Schreibprobe, freier Platz, Konflikte am Ziel.
2. Kopieren: Dateien über ``<name>.partial`` und erst danach umbenennen; SQLite-Dateien über die
   Backup-API (auch die offene Datenbank mit WAL bleibt konsistent). Bereits vollständig kopierte
   Dateien werden bei einer Wiederaufnahme übersprungen. Abbruch jederzeit.
3. Prüfen: jede Datei am Ziel vorhanden, gleiche Größe, kleine Dateien zusätzlich per SHA-256,
   Datenbanken per ``PRAGMA quick_check``.
4. Umschalten: Downloads/Zwischenspeicher sofort (Einstellung + Pfade in catalog.db), System und
   Datenbank beim nächsten Start: dann ist nichts mehr geöffnet, geänderte Dateien werden
   nachkopiert und erst danach zeigt ``storage.json`` auf den neuen Ort.
5. Der alte Ort bleibt unangetastet. Löschen nur auf ausdrücklichen Wunsch (Bestätigungstext);
   gelöscht wird nur, was am neuen Ort nachweislich gleich vorliegt.

``storage.json`` liegt immer im Startordner (``MEDIATHEKATLAS_HOME`` bzw. Standardort), dort
bleiben auch ``runtime/`` (Programmkopie), Startprotokoll und Instanzsperre. Ist der eingestellte
Datenordner beim Start nicht erreichbar (Laufwerk abgezogen), wartet der Start kurz und bricht
dann mit einer verständlichen Meldung ab, statt still an einem leeren Ort neu anzufangen.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

POINTER = 'storage.json'
PROBLEM_FILE = 'storage-problem.txt'
DATA_MARKER = '.mediathekatlas-daten'      # liegt in einem umgezogenen Datenordner
PLACE_MARKER = '.mediathekatlas-ort'       # liegt in Download-/Zwischenspeicherordnern nach einem Umzug
STAGING = '.mediathekatlas-umzug'          # Umzugsprotokoll am Ziel, solange der Umzug läuft
MARKERS = (DATA_MARKER, PLACE_MARKER, STAGING)
HOME_ONLY = frozenset({'runtime', 'instance.lock', 'instance.json', 'instance.json.tmp', 'startup.log',
                       POINTER, POINTER + '.tmp', PROBLEM_FILE})
SKIP_SUFFIXES = ('.partial', '.part', '.ytdl', '-wal', '-shm', '-journal')
SKIP_NAMES = frozenset({'.DS_Store', 'Thumbs.db', 'desktop.ini'})
RESERVE = 512 * 1024 * 1024
HASH_LIMIT = 16 * 1024 * 1024
CHUNK = 8 * 1024 * 1024
CONFIRM = 'ALTE DATEN LÖSCHEN'
ABO_FOLDER = 'YouTube-Abos'
UNAVAILABLE_EXIT = 3
KINDS = {'downloads': 'Downloads', 'cache': 'Zwischenspeicher (YouTube-Abos)', 'system': 'System und Datenbank',
         'imdb': 'IMDb-Archiv'}
SUBFOLDER = {'downloads': 'Downloads', 'cache': 'Zwischenspeicher', 'system': 'System', 'imdb': 'IMDb'}
IMDB_FOLDER = 'imdb'                       # Standard: Unterordner des Datenordners
IMDB_DB = 'imdb_archive.db'
IMDB_TRANSIENT = ('building.db', 'building.db-journal')   # Zwischenstand eines laufenden Neuaufbaus


class Unavailable(RuntimeError):
    """Der eingestellte Datenordner ist nicht erreichbar."""


# ------------------------------------------------------------------ Startordner und Zeiger

def default_home() -> Path:
    custom = os.environ.get('MEDIATHEKATLAS_HOME')
    if custom:
        return Path(custom)
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'MediathekAtlas'
    return Path.home() / '.mediathekatlas'


def read_pointer(home) -> dict:
    try:
        data = json.loads((Path(home) / POINTER).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_pointer(home, data):
    path = Path(home) / POINTER
    temp = path.with_name(POINTER + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def _norm(path) -> str:
    text = str(path or '').strip()
    if not text:
        return ''
    p = Path(text).expanduser()
    try:
        p = p.resolve()
    except (OSError, RuntimeError):
        p = Path(os.path.abspath(str(p)))
    return str(p)


def same(a, b) -> bool:
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def inside(child, parent) -> bool:
    """``child`` liegt in ``parent`` (oder ist gleich)."""
    a, b = _norm(child), _norm(parent)
    if not a or not b:
        return False
    try:
        return os.path.commonpath((a, b)) == b
    except ValueError:
        return False


def data_root(home=None, wait=0.0, log=None) -> Path:
    """Datenordner für den Start. Schließt einen vorbereiteten System-Umzug ab.

    ``wait``: so viele Sekunden auf ein noch nicht eingebundenes Laufwerk warten.
    Raises Unavailable, wenn der eingestellte Ordner fehlt (nie still neu anfangen).
    """
    home = Path(home or default_home())
    say = log or (lambda text: print(text, flush=True))
    cfg = read_pointer(home)
    pending = cfg.get('pending')
    if isinstance(pending, dict) and pending.get('kind') == 'system' and pending.get('state') == 'copied':
        try:
            finalize_system(home, cfg, pending, say)
        except Exception as exc:   # Umzug misslungen: alter Ort bleibt aktiv, Grund sichtbar
            cfg = read_pointer(home)
            pending = dict(cfg.get('pending') or pending, state='failed', error=str(exc)[:400], failed_at=time.time())
            cfg['pending'] = pending
            cfg['last'] = {'kind': 'system', 'phase': 'failed', 'error': pending['error'], 'at': time.time(),
                           'source': pending.get('source'), 'target': pending.get('target')}
            write_pointer(home, cfg)
            say('Umzug von System und Datenbank nicht abgeschlossen: %s – es bleibt beim bisherigen Ort.' % exc)
        cfg = read_pointer(home)
    data = cfg.get('data_dir')
    if not data:
        (home / PROBLEM_FILE).unlink(missing_ok=True)
        return home
    root = Path(data)
    deadline = time.monotonic() + max(0.0, float(wait))
    announced = False
    while not (root / DATA_MARKER).is_file():
        if time.monotonic() >= deadline:
            text = ('Der Speicherort für System und Datenbank ist nicht erreichbar:\n%s\n\n'
                    'Bitte das Laufwerk bzw. die Netzwerkfreigabe verbinden und MediathekAtlas erneut starten. '
                    'Es wurde nichts verändert und kein neuer, leerer Katalog angelegt.' % root)
            info = revert_info(home)
            if info:
                text += ('\n\nAlternativ „Bisherigen Ort verwenden“: startet mit dem Datenstand in\n%s\n(Stand %s). '
                         'Die Daten auf dem Laufwerk bleiben dabei unverändert.' % (info['path'], info['stand'] or 'unbekannt'))
            try:
                (home / PROBLEM_FILE).write_text(text + '\n', encoding='utf-8')
            except OSError:
                pass
            raise Unavailable(text)
        if not announced:
            say('Warte auf den Speicherort für System und Datenbank: %s' % root)
            announced = True
        time.sleep(1.0)
    (home / PROBLEM_FILE).unlink(missing_ok=True)
    return root


# ------------------------------------------------------------------ Sicherer Rückweg (0.6.25)

def _stand(path):
    try:
        return time.strftime('%d.%m.%Y %H:%M', time.localtime(Path(path).stat().st_mtime))
    except OSError:
        return ''


def revert_info(home) -> dict | None:
    """Bisheriger Datenordner, auf den sich gefahrlos zurückstellen lässt – nur den Zeiger, ohne Kopie.

    Björn (19.11.2026): Nach dem Abschluss des System-Umzugs fiel das Ziellaufwerk Sekunden später
    weg. Der bisherige Ort war vollständig und unverändert, aber der einzige Weg zurück
    („Zurück an den Standardort“) hätte die womöglich beschädigte Kopie darüber kopiert.
    Kandidaten: der vermerkte alte Ort des letzten System-Umzugs, sonst der Startordner – jeweils nur
    mit vorhandener ``catalog.db``. Am aktuellen Ort wird nichts verändert oder gelöscht.
    """
    home = Path(home)
    cfg = read_pointer(home)
    current = cfg.get('data_dir')
    if not current:
        return None
    prev = (cfg.get('previous') or {}).get('system') or {}
    candidates = [prev.get('source'), str(home)]
    for cand in candidates:
        if not cand or same(cand, current):
            continue
        folder = Path(cand)
        try:
            usable = (folder / 'catalog.db').is_file() and (same(folder, home) or (folder / DATA_MARKER).is_file())
        except OSError:
            usable = False
        if usable:
            return {'path': str(folder), 'current': str(current), 'stand': _stand(folder / 'catalog.db'),
                    'is_default': same(folder, home)}
    return None


def revert_system(home) -> dict:
    """Stellt System und Datenbank auf den bisherigen Ort zurück (wirksam beim nächsten Start)."""
    home = Path(home)
    info = revert_info(home)
    if not info:
        raise ValueError('Kein bisheriger Datenordner mit Katalog gefunden; es wurde nichts verändert.')
    cfg = read_pointer(home)
    if info['is_default']:
        cfg.pop('data_dir', None)
    else:
        cfg['data_dir'] = info['path']
    cfg.pop('pending', None)
    previous = dict(cfg.get('previous') or {})
    previous.pop('system', None)        # „Alte Daten löschen“ darf den jetzt aktiven Ort nie erreichen
    cfg['previous'] = previous
    cfg['abandoned'] = {'path': info['current'], 'at': time.time()}
    cfg['last'] = {'kind': 'system', 'phase': 'reverted', 'at': time.time(), 'source': info['current'],
                   'target': info['path']}
    write_pointer(home, cfg)
    (home / PROBLEM_FILE).unlink(missing_ok=True)
    return info


def lost_text(root, home):
    text = ('Der Speicherort für System und Datenbank ist nicht mehr erreichbar:\n%s\n\n'
            'MediathekAtlas wurde angehalten, damit nichts Halbes geschrieben wird. Bitte das Laufwerk bzw. '
            'die Netzwerkfreigabe wieder verbinden und erneut starten.' % root)
    info = revert_info(home)
    if info:
        text += ('\n\nAlternativ „Bisherigen Ort verwenden“: startet mit dem Datenstand in\n%s\n(Stand %s). '
                 'Die Daten auf dem Laufwerk bleiben dabei unverändert.' % (info['path'], info['stand'] or 'unbekannt'))
    return text


def watch_root(home, root, stop, on_lost, interval=10.0, misses=2):
    """Wächter (0.6.25): verschwindet der Datenordner im Betrieb (Laufwerk abgezogen, Ruhezustand),
    wird ``on_lost(text)`` aufgerufen, statt mit Fehlern wie „database disk image is malformed“
    weiterzulaufen. Nur für einen eingestellten Datenordner außerhalb des Startordners."""
    home, root = Path(home), Path(root)
    if same(home, root):
        return
    missing = 0
    while not stop.wait(interval):
        try:
            ok = (root / DATA_MARKER).is_file()
        except OSError:
            ok = False
        missing = 0 if ok else missing + 1
        if missing >= misses:
            text = lost_text(root, home)
            try:
                (home / PROBLEM_FILE).write_text(text + '\n', encoding='utf-8')
            except OSError:
                pass
            on_lost(text)
            return


# ------------------------------------------------------------------ IMDb-Archiv mit eigenem Ort (0.6.30)

def imdb_location(home, root, wait=0.0):
    """Ordner des IMDb-Archivs und ob er erreichbar ist.

    Björn (19.11.2026): Das IMDb-Archiv (21,8 GB) soll extern liegen können, während die
    Hauptdatenbank auf der internen SSD bleibt. Ohne Eintrag liegt es wie bisher in
    ``<Datenordner>/imdb``. Ein eingestellter externer Ort braucht die Ortsmarkierung; fehlt sie
    (Laufwerk nicht verbunden), startet die App trotzdem – nur ohne IMDb-Abgleich – und legt nie
    still ein neues, leeres Archiv an.
    """
    cfg = read_pointer(home)
    custom = cfg.get('imdb_dir')
    if not custom:
        return Path(root) / IMDB_FOLDER, True
    folder = Path(custom)
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        try:
            if (folder / PLACE_MARKER).is_file():
                return folder, True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return folder, False
        time.sleep(1.0)


_IMDB_HOLD = threading.Event()   # IMDb-Neuaufbau wartet während eines Archiv-Umzugs


def imdb_held():
    return _IMDB_HOLD.is_set()


# ------------------------------------------------------------------ Dateien, Datenbanken

def is_sqlite(path) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(16) == b'SQLite format 3\x00'
    except OSError:
        return False


def _skip_name(name) -> bool:
    return name in SKIP_NAMES or name in MARKERS or name.endswith(SKIP_SUFFIXES)


def walk(source, top_exclude=(), exclude=()):
    """Alle zu übernehmenden Dateien: (absoluter Pfad, relativer Pfad, os.stat_result).

    Übersprungen: Teil-/Sperrdateien (``.partial``, ``-wal`` …), Symlinks, Markierungen,
    Namen aus ``top_exclude`` direkt im Quellordner und Ordner aus ``exclude`` (andere
    Speicherorte, die im Quellordner liegen).
    """
    source = Path(source)
    excluded = [_norm(p) for p in exclude if p]
    top = set(top_exclude)
    for current, dirs, files in os.walk(source, followlinks=False):
        here = Path(current)
        rel_dir = here.relative_to(source)
        keep = []
        for name in sorted(dirs):
            full = here / name
            if (not rel_dir.parts and name in top) or name.endswith('.partial') or full.is_symlink():
                continue
            if any(_norm(full) == e for e in excluded):
                continue
            keep.append(name)
        dirs[:] = keep
        for name in sorted(files):
            if (not rel_dir.parts and name in top) or _skip_name(name):
                continue
            full = here / name
            try:
                st = full.lstat()
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            yield full, (rel_dir / name), st


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _fsync_dir(path):
    if os.name == 'nt':
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


_PACE = threading.local()   # im Umzug im laufenden Betrieb: Laufwerk für die Datenbank der App freihalten
PACE_RATIO = 0.5             # nach jedem Block halb so lange Pause, wie der Block gebraucht hat
FLUSH_EVERY = 64 * 1024 * 1024


def _low_io_priority():
    """0.6.25 (Björn, 19.11.2026: während des Downloadumzugs /api/state bis 579 s): der Umzug-Thread
    bekommt unter macOS die gedrosselte E/A-Klasse (``setiopolicy_np``, IOPOL_THROTTLE), damit die
    Datenbankzugriffe der App Vorrang haben. Anderswo genügt die Pause zwischen den Blöcken."""
    _PACE.on = True
    if sys.platform != 'darwin':
        return False
    try:
        import ctypes
        libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        return libc.setiopolicy_np(0, 1, 3) == 0   # IOPOL_TYPE_DISK, IOPOL_SCOPE_THREAD, IOPOL_THROTTLE
    except (OSError, AttributeError):
        return False


def _pace(started):
    if getattr(_PACE, 'on', False):
        time.sleep(min(2.0, max(0.0, time.monotonic() - started) * PACE_RATIO))


def copy_file(src, dst, on_bytes=None, cancelled=None):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + '.partial')
    written = flushed = 0
    try:
        with open(src, 'rb') as fin, open(part, 'wb') as fout:
            while True:
                if cancelled and cancelled():
                    raise InterruptedError('abgebrochen')
                started = time.monotonic()
                block = fin.read(CHUNK)
                if not block:
                    break
                fout.write(block)
                written += len(block)
                if getattr(_PACE, 'on', False) and written - flushed >= FLUSH_EVERY:
                    fout.flush()
                    os.fsync(fout.fileno())   # kleine Schübe statt eines großen Rückstaus vor dem fsync der Datenbank
                    flushed = written
                if on_bytes:
                    on_bytes(len(block))
                _pace(started)
            fout.flush()
            os.fsync(fout.fileno())
        shutil.copystat(src, part, follow_symlinks=False)
        os.replace(part, dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


QUICK_CHECK_LIMIT = 512 * 1024 * 1024   # größere Datenbanken: Strukturprüfung statt quick_check (0.6.22)
BACKUP_PAGES = 4096


def copy_sqlite(src, dst, on_bytes=None, cancelled=None, on_stage=None):
    """Konsistente Kopie einer (auch geöffneten) SQLite-Datei über die Backup-API.

    0.6.22 (Björn, 16.11.2026: Anzeige stand bei catalog.db 5,5 GB über 10 Minuten still): Die Quelle
    hält einen Lesestand fest (offene Lesetransaktion), damit die Kopie in Schritten laufen kann, ohne
    bei Schreibzugriffen der App neu zu beginnen. Jeder Schritt meldet Fortschritt und prüft den
    Abbruch. Danach statt ``quick_check`` über die ganze Datei (bei 5,5 GB auf USB-Laufwerken viele
    Minuten ohne Anzeige) bei großen Dateien eine Strukturprüfung: Kopf, Seitenzahl = Quelle,
    Dateigröße, Schema lesbar; kleine Dateien weiter mit ``quick_check``.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + '.partial')
    part.unlink(missing_ok=True)
    stage = on_stage or (lambda *a: None)
    seen = [0]
    try:
        source = sqlite3.connect(str(src), timeout=60, isolation_level=None)
        target = sqlite3.connect(str(part))
        try:
            source.execute('BEGIN')
            page_size = source.execute('PRAGMA page_size').fetchone()[0]
            pages = source.execute('PRAGMA page_count').fetchone()[0]   # Lesestand ab hier fest
            total = page_size * pages

            step = [time.monotonic()]

            def progress(_status, remaining, count):
                _pace(step[0])
                step[0] = time.monotonic()
                if cancelled and cancelled():
                    raise InterruptedError('abgebrochen')
                done = max(0, (count - remaining) * page_size)
                if on_bytes and done > seen[0]:
                    on_bytes(done - seen[0])
                    seen[0] = done
                stage('copy', done, total)
            stage('copy', 0, total)
            source.backup(target, pages=BACKUP_PAGES, progress=progress, sleep=0)
            source.execute('COMMIT')
            stage('check', 0, total)
            if total <= QUICK_CHECK_LIMIT:
                check = target.execute('PRAGMA quick_check').fetchone()[0]
                if check != 'ok':
                    raise ValueError('Datenbankkopie fehlerhaft (%s): %s' % (Path(src).name, str(check)[:160]))
            else:
                copied = target.execute('PRAGMA page_count').fetchone()[0]
                if copied != pages:
                    raise ValueError('Datenbankkopie unvollständig (%s): %d von %d Seiten' % (Path(src).name, copied, pages))
                target.execute('SELECT count(*) FROM sqlite_master').fetchone()
            target.commit()
            # 0.6.25: keine Umstellung des Journalmodus an der Kopie mehr; sollte die Prüfung dort ein
            # WAL angelegt haben, wird es zurückgeschrieben statt blind gelöscht.
            if str(target.execute('PRAGMA journal_mode').fetchone()[0]).lower() == 'wal':
                target.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            target.close()
            source.close()
        for suffix in ('-wal', '-shm'):
            extra = part.with_name(part.name + suffix)
            if extra.exists():
                if suffix == '-wal' and extra.stat().st_size:
                    raise ValueError('Datenbankkopie nicht vollständig zurückgeschrieben (%s)' % Path(src).name)
                extra.unlink(missing_ok=True)
        stage('sync', total, total)
        with open(part, 'rb') as f:
            os.fsync(f.fileno())
        with open(part, 'rb') as f:
            if f.read(16) != b'SQLite format 3\x00':
                raise ValueError('Datenbankkopie ohne gültigen Kopf (%s)' % Path(src).name)
        if total > QUICK_CHECK_LIMIT and part.stat().st_size < total:
            raise ValueError('Datenbankkopie zu klein (%s)' % Path(src).name)
        try:
            os.chmod(part, 0o600)
        except OSError:
            pass
        os.replace(part, dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    final = dst.stat().st_size
    if on_bytes and final > seen[0]:
        on_bytes(final - seen[0])


def _wal_stamp(path):
    wal = Path(str(path) + '-wal')
    try:
        st = wal.stat()
        return [st.st_size, st.st_mtime_ns] if st.st_size else None
    except OSError:
        return None


def _stamp(st, path, db):
    return {'size': st.st_size, 'mtime': st.st_mtime_ns, 'wal': _wal_stamp(path) if db else None, 'db': bool(db)}


def _unchanged(entry, st, path):
    return bool(entry) and entry.get('size') == st.st_size and entry.get('mtime') == st.st_mtime_ns and \
        entry.get('wal') == (_wal_stamp(path) if entry.get('db') else None)


def _present(dst, st):
    """Normale Datei schon vollständig am Ziel (Wiederaufnahme)."""
    try:
        d = dst.stat()
    except OSError:
        return False
    return d.st_size == st.st_size and abs(d.st_mtime - st.st_mtime) <= 2   # FAT/exFAT: 2 s Raster


# ------------------------------------------------------------------ Laufwerke

def disk(path):
    """Freier/gesamter Platz am nächsten vorhandenen Ordner von ``path``."""
    p = Path(path) if path else None
    while p is not None and not p.exists():
        if p.parent == p:
            p = None
            break
        p = p.parent
    if p is None:
        return {'free': 0, 'total': 0}
    try:
        usage = shutil.disk_usage(p)
        return {'free': usage.free, 'total': usage.total}
    except OSError:
        return {'free': 0, 'total': 0}


_SLOW = {}
_SLOW_LOCK = threading.Lock()


def _bounded(key, fn, ttl=60.0, wait=3.0, default=None):
    """0.6.25 (Björn, 19.11.2026: /api/storage-locations bis 433 s): Laufwerksabfragen (``mount``,
    Platz auf schlafenden USB-Laufwerken oder hängenden Netzwerkfreigaben) laufen im Hintergrund.
    Die Oberfläche wartet höchstens ``wait`` Sekunden und bekommt sonst den letzten bekannten Wert."""
    with _SLOW_LOCK:
        entry = _SLOW.setdefault(key, {})
        fresh = 'value' in entry and time.monotonic() - entry['at'] < ttl
        if fresh:
            return entry['value']
        thread = entry.get('thread')
        if thread is None or not thread.is_alive():
            def work():
                try:
                    value = fn()
                except Exception:   # noqa: BLE001 – Anzeigewert, nie den Aufrufer stören
                    value = default
                with _SLOW_LOCK:
                    entry.update(value=value, at=time.monotonic())
            thread = threading.Thread(target=work, daemon=True, name='storage_probe')
            entry['thread'] = thread
            thread.start()
    thread.join(wait)
    with _SLOW_LOCK:
        return entry.get('value', default)


def _mounts():
    return _bounded('mounts', _read_mounts, ttl=30.0, wait=6.0, default=[])


def _read_mounts():
    rows = []
    try:
        if sys.platform.startswith('linux'):
            for line in Path('/proc/self/mounts').read_text().splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    rows.append((parts[1].replace('\\040', ' '), parts[2]))
        elif sys.platform == 'darwin':
            out = subprocess.run(['/sbin/mount'], capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if ' on ' in line and ' (' in line:
                    point = line.split(' on ', 1)[1].rsplit(' (', 1)[0]
                    kind = line.rsplit(' (', 1)[1].split(',')[0].strip(' )')
                    rows.append((point, kind))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return rows


NETWORK_FS = ('smbfs', 'cifs', 'smb3', 'nfs', 'nfs4', 'afpfs', 'webdav', 'fuse.sshfs', 'davfs', '9p')


def filesystem(path):
    """Dateisystemtyp des Einhängepunkts (best effort, '' wenn unbekannt)."""
    target = _norm(path)
    best, kind = '', ''
    for point, fs in _mounts():
        if inside(target, point) and len(point) > len(best):
            best, kind = point, fs
    return kind


def volumes():
    """Vorschläge für die Oberfläche: eingebundene Laufwerke mit freiem Platz."""
    found = []
    if sys.platform == 'darwin':
        candidates = sorted(Path('/Volumes').glob('*'))
    elif os.name == 'nt':
        candidates = [Path('%s:\\' % c) for c in 'DEFGHIJKLMNOPQRSTUVWXYZ' if os.path.exists('%s:\\' % c)]
    else:
        user = os.environ.get('USER') or ''
        candidates = list(Path('/media').glob('*')) + list(Path('/mnt').glob('*')) + \
            list(Path('/').glob('volume[0-9]*')) + list(Path('/share').glob('CACHEDEV*_DATA'))
        if user:
            candidates += list(Path('/media', user).glob('*')) + list(Path('/run/media', user).glob('*'))
        candidates = sorted(candidates)
    seen = set()
    for p in candidates:
        try:
            if not p.is_dir() or p.is_symlink() or str(p) in seen:
                continue
            if sys.platform.startswith('linux') and p.parent == Path('/media') and user and p.name == user:
                continue
            seen.add(str(p))
            usage = shutil.disk_usage(p)
        except OSError:
            continue
        if usage.total <= 0:
            continue
        found.append({'path': str(p), 'name': p.name or str(p), 'free': usage.free, 'total': usage.total,
                      'network': filesystem(p) in NETWORK_FS})
    return found[:16]


# ------------------------------------------------------------------ Prüfung eines Ziels

def _existing_ancestor(p: Path):
    while not p.exists():
        if p.parent == p:
            return None
        p = p.parent
    return p if p.is_dir() else p


def _mount_container(p: Path) -> bool:
    """Ordner, in denen Laufwerke eingehängt werden: ein fehlender Unterordner heißt „nicht verbunden“.
    Darin wird nie etwas angelegt (sonst landen die Daten still auf der internen Platte)."""
    user = os.environ.get('USER') or ''
    containers = {'/Volumes', '/media', '/mnt', '/run/media', '/share', '/media/' + user, '/run/media/' + user}
    text = str(p)
    return p == Path(p.anchor) or text in containers


def _writable(target: Path):
    probe = target / ('.mediathekatlas-schreibprobe-%d' % os.getpid())
    try:
        with probe.open('wb') as f:
            f.write(b'MediathekAtlas')
            f.flush()
            os.fsync(f.fileno())
        return ''
    except OSError as exc:
        return str(exc)
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def inspect(kind, source, target, *, home=None, others=(), exclude=(), mode='copy', budget=40.0):
    """Prüft einen geplanten Umzug, ohne etwas zu verändern."""
    if kind not in KINDS:
        raise ValueError('Unbekannter Speicherort')
    text = str(target or '').strip()
    result = {'kind': kind, 'label': KINDS[kind], 'source': str(source or ''), 'target': text, 'mode': mode,
              'problems': [], 'warnings': [], 'files': 0, 'bytes_total': 0, 'bytes_present': 0, 'bytes_needed': 0,
              'free': 0, 'complete': True, 'conflicts': [], 'existing_data': False, 'network': False}
    problems, warnings = result['problems'], result['warnings']
    if not text:
        problems.append('Bitte einen Zielordner angeben.')
        return _finish(result)
    p = Path(text).expanduser()
    if not p.is_absolute():
        problems.append('Bitte einen absoluten Pfad angeben (z. B. /Volumes/Laufwerk/MediathekAtlas).')
        return _finish(result)
    if p == Path(p.anchor):
        problems.append('Bitte einen Unterordner wählen, nicht die oberste Ebene eines Laufwerks.')
        return _finish(result)
    target_n = _norm(p)
    result['target'] = target_n
    src = Path(source) if source else None
    if src is not None and same(src, target_n):
        problems.append('Das ist bereits der aktuelle Speicherort.')
        return _finish(result)
    if src is not None and (inside(target_n, src) or inside(src, target_n)):
        problems.append('Alter und neuer Ort dürfen nicht ineinander liegen.')
        return _finish(result)
    for label, other in others:
        if other and (inside(target_n, other) or inside(other, target_n)):
            problems.append('Der neue Ort überschneidet sich mit „%s“ (%s).' % (label, other))
    anchor = _existing_ancestor(p)
    if anchor is None or (anchor != p and _mount_container(anchor)):
        problems.append('Laufwerk bzw. Ordner nicht gefunden: %s – ist das Laufwerk verbunden?' % p)
        return _finish(result)
    if p.exists() and not p.is_dir():
        problems.append('Am Ziel liegt eine Datei, kein Ordner.')
        return _finish(result)
    probe_dir = anchor
    error = _writable(probe_dir)
    if error:
        problems.append('Keine Schreibrechte am Ziel: %s' % error[:160])
    fs = filesystem(probe_dir)
    result['network'] = fs in NETWORK_FS
    if kind == 'system' and result['network']:
        warnings.append('Das Ziel ist eine Netzwerkfreigabe (%s). SQLite-Datenbanken können dort langsam sein; '
                        'die App braucht die Freigabe dauerhaft und startet ohne sie nicht.' % fs)
    if fs in ('msdos', 'vfat', 'fat32'):
        warnings.append('Das Laufwerk ist mit FAT32 formatiert: Dateien über 4 GB passen nicht. Besser exFAT, APFS oder NTFS.')
    is_home = home is not None and same(target_n, home)
    staging = p / STAGING
    if p.is_dir():
        if kind == 'system':
            if (p / 'catalog.db').is_file() and (is_home or (p / DATA_MARKER).is_file()):
                result['existing_data'] = True
            entries = [x for x in p.iterdir() if x.name not in SKIP_NAMES]
            if entries and not is_home and not staging.is_file() and not result['existing_data']:
                problems.append('Der Zielordner ist nicht leer. Bitte einen leeren oder neuen Ordner wählen.')
        if kind == 'imdb' and is_sqlite(p / IMDB_DB):
            result['existing_data'] = True
            result['existing_stand'] = _stand(p / IMDB_DB)
        if staging.is_file():
            try:
                info = json.loads(staging.read_text(encoding='utf-8'))
                if info.get('source') and not same(info.get('source'), source):
                    problems.append('Im Zielordner liegt ein unterbrochener Umzug von einem anderen Ort (%s).' % info.get('source'))
                else:
                    warnings.append('Unterbrochener Umzug gefunden: bereits kopierte Dateien werden übernommen.')
            except (OSError, ValueError):
                pass
    if kind == 'system' and mode == 'copy' and is_home and result['existing_data'] and not staging.is_file():
        # 0.6.25: am Standardort liegt noch ein früherer Stand – nie überschreiben.
        problems.append('Am Standardort liegt noch ein früherer Datenstand (Katalog vom %s). Er wird nicht '
                        'überschrieben. „Vorhandene MediathekAtlas-Daten am Ziel verwenden“ kehrt zu diesem Stand '
                        'zurück; soll der aktuelle Stand umziehen, den früheren vorher löschen lassen oder im Finder '
                        'wegräumen.' % (_stand(p / 'catalog.db') or 'unbekannt'))
    if kind == 'imdb' and mode == 'copy' and result['existing_data'] and not staging.is_file():
        problems.append('Am Ziel liegt schon ein IMDb-Archiv (Stand %s). Es wird nicht überschrieben: „Vorhandenes '
                        'Archiv am Ziel verwenden“ übernimmt es ohne Kopieren, sonst einen leeren Ordner wählen.'
                        % (result.get('existing_stand') or 'unbekannt'))
    if kind == 'imdb' and result['network']:
        warnings.append('Das Ziel ist eine Netzwerkfreigabe (%s). Die Erkennung fragt das IMDb-Archiv bei fast jedem '
                        'Abgleich ab und wird dort deutlich langsamer.' % fs)
    if mode == 'adopt':
        if not result['existing_data']:
            problems.append('Am Ziel liegt kein IMDb-Archiv.' if kind == 'imdb' else 'Am Ziel liegen keine MediathekAtlas-Daten.')
        return _finish(result)
    if mode == 'switch' or src is None or not src.is_dir():
        if mode != 'switch' and (src is None or not src.is_dir()):
            warnings.append('Am bisherigen Ort liegen keine Daten; es wird nur umgestellt.')
            result['mode'] = 'switch'
        if kind == 'system' and result['mode'] == 'switch':
            problems.append('System und Datenbank lassen sich nur mit Übernahme der Daten umstellen.')
        if kind == 'imdb' and result['mode'] == 'switch' and mode == 'switch':
            problems.append('Das IMDb-Archiv lässt sich nur mit Übernahme umstellen (oder ein vorhandenes Archiv verwenden).')
        return _finish(result)
    started = time.monotonic()
    plan = _plan_parts(kind, source, home)
    manifest = _read_staging(p)
    for full, rel, st in walk(src, plan['top_exclude'], list(exclude)):
        result['files'] += 1
        result['bytes_total'] += st.st_size
        dst = p / rel
        if dst.exists():
            db = is_sqlite(full)
            if db and _unchanged(manifest.get(str(rel)), st, full):
                result['bytes_present'] += st.st_size
            elif not db and _present(dst, st):
                result['bytes_present'] += st.st_size
            elif kind != 'system' and not db and len(result['conflicts']) < 50:
                result['conflicts'].append(str(rel))
        if time.monotonic() - started > budget:
            result['complete'] = False
            warnings.append('Sehr viele Dateien: Größe noch nicht vollständig ermittelt; der Umzug prüft den Platz erneut.')
            break
    if result['conflicts'] and not is_home:
        problems.append('Am Ziel liegen schon %d gleichnamige, abweichende Dateien (z. B. %s). Nichts wird überschrieben – '
                        'bitte einen anderen Ordner wählen.' % (len(result['conflicts']), result['conflicts'][0]))
    result['bytes_needed'] = max(0, result['bytes_total'] - result['bytes_present'])
    result['free'] = disk(probe_dir)['free']
    if result['free'] and result['free'] < result['bytes_needed'] + RESERVE:
        problems.append('Zu wenig freier Platz am Ziel: %s frei, %s nötig.' % (_gb(result['free']), _gb(result['bytes_needed'] + RESERVE)))
    return _finish(result)


def _finish(result):
    result['ok'] = not result['problems']
    return result


def _gb(n):
    return ('%.1f GB' % (n / 1e9)).replace('.', ',')


def _plan_parts(kind, source, home):
    top = set()
    if kind == 'system':
        top = set(HOME_ONLY)
    if kind == 'imdb':
        top = set(IMDB_TRANSIENT)
    return {'top_exclude': sorted(top)}


def _read_staging(target):
    try:
        data = json.loads((Path(target) / STAGING).read_text(encoding='utf-8'))
        return data.get('files') or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _write_staging(target, info):
    path = Path(target) / STAGING
    temp = path.with_name(STAGING + '.tmp')
    temp.write_text(json.dumps(info, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def _write_marker(folder, name, kind):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / name).write_text(json.dumps({'kind': kind, 'created': time.time(), 'app': 'MediathekAtlas'}) + '\n',
                                     encoding='utf-8')


# ------------------------------------------------------------------ Kopieren und Prüfen

def sync_tree(source, target, *, top_exclude=(), exclude=(), progress=None, cancelled=None, manifest=None,
              staging_info=None):
    """Kopiert alle Dateien; überspringt bereits identische. Gibt das Manifest zurück."""
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest or {})
    info = dict(staging_info or {})
    files = list(walk(source, top_exclude, exclude))
    total = sum(st.st_size for _, _, st in files)
    state = {'files_total': len(files), 'files_done': 0, 'bytes_total': total, 'bytes_done': 0, 'current': ''}
    last_save = [time.monotonic()]

    def _stage(step, done, total):
        state.update(step=step, file_done=done, file_total=total)
        if progress:
            progress(dict(state))

    def tick(n=0, current=None):
        state['bytes_done'] += n
        if current is not None:
            state['current'] = current
            state.update(step='copy', file_done=0, file_total=0, file_started=time.time())
        if progress:
            progress(dict(state))
    tick()
    for full, rel, st in files:
        if cancelled and cancelled():
            raise InterruptedError('abgebrochen')
        dst = target / rel
        key = str(rel)
        db = is_sqlite(full)
        if dst.exists() and ((db and _unchanged(manifest.get(key), st, full)) or (not db and _present(dst, st))):
            if not db:
                manifest[key] = _stamp(st, full, False)   # auch übernommene Dateien gehören zur Prüfliste
            state['files_done'] += 1
            tick(st.st_size, key)
            continue
        tick(0, key)
        before = state['bytes_done']
        if db:
            stamp = _stamp(st, full, True)
            copy_sqlite(full, dst, on_bytes=lambda n: tick(n), cancelled=cancelled,
                        on_stage=lambda step, done, total: _stage(step, done, total))
        else:
            stamp = _stamp(st, full, False)
            state['file_total'] = st.st_size

            def counted(n):
                state['file_done'] = state.get('file_done', 0) + n
                tick(n)
            copy_file(full, dst, on_bytes=counted, cancelled=cancelled)
        state['bytes_done'] = before + st.st_size   # Datenbankkopie kann kleiner/größer sein als das Original
        state['files_done'] += 1
        manifest[key] = stamp
        tick(0)
        if staging_info is not None and time.monotonic() - last_save[0] > 5:
            info['files'] = manifest
            _write_staging(target, info)
            last_save[0] = time.monotonic()
    _fsync_dir(target)
    if staging_info is not None:
        info['files'] = manifest
        _write_staging(target, info)
    return manifest


def _live_files(source, manifest):
    """Prüfliste im laufenden Betrieb: nur die kopierten Dateien, deren Quelle seit der Kopie unverändert ist.

    0.6.23 (Björn, 16.11.2026): Die Prüfung las den Quellordner neu ein und meldete Dateien, die die
    laufende App seit der Kopie geschrieben hatte (diagnostic.jsonl, neue Verbund-Ereignisse
    verbund/nodes/…/events-*.jsonl), als Fehler – der ganze Umzug galt als fehlgeschlagen. Solche
    Dateien zieht beim System-Umzug der Abschluss beim Neustart nach (dann ohne laufende App und mit
    strenger Prüfung aller Dateien).
    """
    files, changed = [], 0
    for key, entry in sorted(manifest.items()):
        full = Path(source) / key
        try:
            st = full.stat()
        except OSError:
            changed += 1   # seit der Kopie gelöscht oder umbenannt (z. B. rotiertes Protokoll)
            continue
        if not _unchanged(entry, st, full):
            changed += 1
            continue
        files.append((full, Path(key), st))
    return files, changed


def verify_tree(source, target, *, top_exclude=(), exclude=(), progress=None, cancelled=None, manifest=None,
                live=False, report=None):
    """Jede Datei des Quellordners liegt gleich am Ziel. Gibt Liste der Abweichungen zurück.

    ``live``: App läuft weiter – nur Dateien aus dem Manifest prüfen, deren Quelle unverändert ist;
    die Zahl der seitdem geänderten Dateien steht danach in ``report['changed']``.
    """
    source, target = Path(source), Path(target)
    manifest = manifest or {}
    bad = []
    if live:
        files, changed = _live_files(source, manifest)
        if report is not None:
            report['changed'] = changed
    else:
        files = list(walk(source, top_exclude, exclude))
    for i, (full, rel, st) in enumerate(files):
        if cancelled and cancelled():
            raise InterruptedError('abgebrochen')
        if progress and (i % 50 == 0 or i == len(files) - 1):
            progress({'files_done': i + 1, 'files_total': len(files), 'current': str(rel)})
        dst = target / rel
        if not dst.is_file():
            bad.append('%s fehlt' % rel)
            continue
        if is_sqlite(full):
            entry = manifest.get(str(rel))
            if entry and entry.get('db'):
                continue   # direkt nach dem Kopieren mit quick_check geprüft
            try:
                c = sqlite3.connect(dst.as_uri() + '?mode=ro', uri=True, timeout=10)
                try:
                    ok = c.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                finally:
                    c.close()
            except sqlite3.Error:
                ok = False
            if not ok:
                bad.append('%s fehlerhaft' % rel)
            continue
        if dst.stat().st_size != st.st_size:
            bad.append('%s Größe weicht ab' % rel)
            continue
        if st.st_size <= HASH_LIMIT and _sha256(full) != _sha256(dst):
            bad.append('%s Inhalt weicht ab' % rel)
    return bad


def remove_verified(source, target, *, top_exclude=(), exclude=(), progress=None):
    """Löscht am alten Ort nur Dateien, die am neuen Ort gleich vorliegen. Leere Ordner danach."""
    source, target = Path(source), Path(target)
    removed = kept = freed = 0
    files = list(walk(source, top_exclude, exclude))
    for i, (full, rel, st) in enumerate(files):
        if progress and i % 50 == 0:
            progress({'files_done': i, 'files_total': len(files), 'current': str(rel)})
        dst = target / rel
        try:
            # gleich groß, oder am neuen Ort seither weitergeschrieben (z. B. Protokoll nach dem Umzug)
            good = dst.is_file() and (is_sqlite(full) or dst.stat().st_size == st.st_size or
                                      dst.stat().st_mtime > st.st_mtime + 2 and dst.stat().st_size >= st.st_size)
        except OSError:
            good = False
        if not good:
            kept += 1
            continue
        try:
            full.unlink()
            for extra in (Path(str(full) + '-wal'), Path(str(full) + '-shm')):
                if is_sqlite(dst):
                    extra.unlink(missing_ok=True)
            removed += 1
            freed += st.st_size
        except OSError:
            kept += 1
    # leere Ordner von unten nach oben entfernen (nie den Quellordner selbst bei System = Startordner)
    for current, dirs, _files in sorted(os.walk(source), key=lambda x: -len(x[0])):
        here = Path(current)
        if here == source:
            continue
        rel = here.relative_to(source)
        if rel.parts and rel.parts[0] in set(top_exclude):
            continue
        try:
            here.rmdir()
        except OSError:
            pass
    return {'removed': removed, 'kept': kept, 'freed': freed}


# ------------------------------------------------------------------ Pfade in der Datenbank

def _remove_replaced_archive(source, target):
    """0.6.30: altes IMDb-Archiv nach Übernahme eines anderen Archivs löschen – nur die bekannten
    Archivdateien und nur, wenn das aktive Archiv am neuen Ort lesbar ist."""
    active = Path(target) / IMDB_DB
    try:
        c = sqlite3.connect(active.as_uri() + '?mode=ro', uri=True)
        try:
            c.execute('SELECT updated FROM snapshot').fetchone()
        finally:
            c.close()
    except sqlite3.Error as exc:
        raise ValueError('Das aktive IMDb-Archiv in %s ist nicht lesbar; zur Sicherheit wird nichts gelöscht (%s).'
                         % (target, exc)) from None
    removed = freed = 0
    folder = Path(source)
    names = [IMDB_DB, IMDB_DB + '-journal', IMDB_DB + '-wal', IMDB_DB + '-shm', *IMDB_TRANSIENT]
    names += [p.name for p in folder.glob('*.tsv.gz')] + [p.name for p in folder.glob('*.tsv.gz.part')]
    for name in names:
        path = folder / name
        try:
            if path.is_file() and not path.is_symlink():
                size = path.stat().st_size
                path.unlink()
                removed += 1
                freed += size
        except OSError:
            pass
    kept = sum(1 for p in folder.rglob('*') if p.is_file()) if folder.is_dir() else 0
    return {'removed': removed, 'freed': freed, 'kept': kept}


def _swap(value, pairs):
    if not isinstance(value, str) or not value:
        return value
    for old, new in pairs:
        if value == old:
            return new
        for sep in {os.sep, '/'}:
            if value.startswith(old + sep):
                return new + value[len(old):]
    return value


def _swap_tree(value, pairs):
    if isinstance(value, dict):
        return {k: _swap_tree(v, pairs) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap_tree(v, pairs) for v in value]
    return _swap(value, pairs)


def _exists(value):
    try:
        return bool(value) and Path(value).is_file()
    except (OSError, ValueError):
        return False


def rewrite_paths(c, pairs, abo_root=None, only_existing=False):
    """Ersetzt alte Pfadanfänge in catalog.db (Aufträge, fertige Downloads, Verbund).

    ``only_existing`` (0.6.37, Übernehmen vorhandener Daten): nur dort, wo die Datei am neuen Ort liegt."""
    pairs = [(str(o).rstrip('/\\'), str(n).rstrip('/\\')) for o, n in pairs if o and n and str(o) != str(n)]
    if not pairs:
        return 0
    changed = 0
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'jobs' in tables:
        for job_id, payload in c.execute('SELECT id,payload FROM jobs').fetchall():
            try:
                data = json.loads(payload)
            except (TypeError, ValueError):
                continue
            new = _swap_tree(data, pairs)
            if only_existing and new != data and not _exists(new.get('path') or new.get('target')):
                continue
            if abo_root and isinstance(new, dict) and new.get('youtube_abo'):
                new['root'] = str(abo_root)
            if new != data:
                c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(new), job_id))
                changed += 1
    for table, key, column in (('downloaded_items', 'identity', 'path'), ('mesh_downloads', 'key', 'local')):
        if table not in tables:
            continue
        for ident, value in c.execute('SELECT %s,%s FROM %s' % (key, column, table)).fetchall():
            new = _swap(value, pairs)
            if only_existing and new != value and not _exists(new):
                continue
            if new != value:
                c.execute('UPDATE %s SET %s=? WHERE %s=?' % (table, column, key), (new, ident))
                changed += 1
    return changed


# ------------------------------------------------------------------ System-Umzug beim Start

def finalize_system(home, cfg, pending, say):
    source, target = Path(pending['source']), Path(pending['target'])
    home = Path(home)
    if not source.is_dir():
        raise Unavailable('Bisheriger Datenordner nicht erreichbar: %s' % source)
    if not target.is_dir() or not (target / STAGING).is_file():
        raise Unavailable('Neuer Datenordner nicht erreichbar oder unvollständig: %s' % target)
    say('Umzug von System und Datenbank wird abgeschlossen: %s → %s' % (source, target))
    info = json.loads((target / STAGING).read_text(encoding='utf-8'))
    top = info.get('top_exclude') or sorted(HOME_ONLY)
    last = [0.0]

    def progress(state):
        if time.monotonic() - last[0] > 5:
            last[0] = time.monotonic()
            say('Abgleich: %d/%d Dateien, %s' % (state.get('files_done', 0), state.get('files_total', 0), state.get('current', '')))
    exclude = info.get('exclude') or []   # 0.6.30: z. B. eigener Ort des IMDb-Archivs, Downloads im Datenordner
    manifest = sync_tree(source, target, top_exclude=top, exclude=exclude, progress=progress,
                         manifest=info.get('files') or {}, staging_info=info)
    bad = verify_tree(source, target, top_exclude=top, exclude=exclude, manifest=manifest)
    if bad:
        raise ValueError('Prüfung am Ziel fehlgeschlagen: ' + '; '.join(bad[:5]))
    db = target / 'catalog.db'
    if db.is_file():
        c = sqlite3.connect(str(db), timeout=30)
        try:
            with c:
                changed = rewrite_paths(c, [(str(source), str(target))])
        finally:
            c.close()
        say('Pfadangaben angepasst: %d' % changed)
    if not same(target, home):
        _write_marker(target, DATA_MARKER, 'system')
    (target / STAGING).unlink(missing_ok=True)
    cfg = read_pointer(home)
    if same(target, home):
        cfg.pop('data_dir', None)
    else:
        cfg['data_dir'] = str(target)
    cfg.pop('pending', None)
    previous = dict(cfg.get('previous') or {})
    previous['system'] = {'source': str(source), 'target': str(target), 'at': time.time(), 'top_exclude': top}
    cfg['previous'] = previous
    cfg['last'] = {'kind': 'system', 'phase': 'done', 'at': time.time(), 'source': str(source), 'target': str(target),
                   'files': len(manifest)}
    write_pointer(home, cfg)
    say('Umzug abgeschlossen. Datenordner: %s' % target)


# ------------------------------------------------------------------ Laufzeit: Umzüge im Hintergrund

_HOLD = threading.Event()   # Download-Warteschlange wartet während eines Download-/Zwischenspeicher-Umzugs


def downloads_held():
    return _HOLD.is_set()


def abo_base(settings):
    """Basisordner der YouTube-Abo-Videos: Zwischenspeicher oder Downloadordner."""
    return (settings or {}).get('cache_dir') or (settings or {}).get('download_dir') or ''


def location(settings, kind, root=None):
    s = settings or {}
    if kind == 'downloads':
        return s.get('download_dir') or ''
    if kind == 'cache':
        base = abo_base(s)
        return str(Path(base) / ABO_FOLDER) if base else ''
    return str(root or '')


def problems(settings):
    """Nicht erreichbare Download-/Zwischenspeicherorte (nur nach einem Umzug markiert)."""
    s = settings or {}
    marked = s.get('storage_markers') or {}
    found = []
    for kind, folder in (('downloads', s.get('download_dir')), ('cache', s.get('cache_dir'))):
        if folder and marked.get(kind) and not (Path(folder) / PLACE_MARKER).is_file():
            found.append({'kind': kind, 'path': folder,
                          'text': '%s nicht erreichbar: %s. Laufwerk bzw. Freigabe verbinden; Downloads warten so lange.'
                                  % (KINDS[kind].split(' (')[0], folder)})
    return found


def root_problem(job_root, settings):
    for item in problems(settings):
        if job_root and (same(job_root, item['path']) or inside(job_root, item['path'])):
            return item['text']
    return ''


class Mover:
    """Ein Umzug zur Zeit; Zustand für die Oberfläche."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.state = {'phase': 'idle'}

    def status(self):
        with self.lock:
            return dict(self.state)

    def running(self):
        return self.state.get('phase') in ('preparing', 'waiting', 'copying', 'verifying', 'switching', 'removing')

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def start(self, ctx, kind, target, mode='copy'):
        if self.running():
            raise ValueError('Es läuft bereits ein Umzug.')
        plan = ctx.plan(kind, target, mode)
        if not plan['check']['ok']:
            raise ValueError(' '.join(plan['check']['problems']))
        self.cancel.clear()
        self.state = {'phase': 'preparing', 'kind': kind, 'label': KINDS[kind], 'source': plan['source'],
                      'target': plan['target'], 'mode': plan['check']['mode'], 'started': time.time(), 'files_done': 0,
                      'files_total': 0, 'bytes_done': 0, 'bytes_total': plan['check']['bytes_total'], 'current': '',
                      'error': '', 'restart_needed': False}
        self.thread = threading.Thread(target=self._run, args=(ctx, plan), daemon=True, name='storage_move')
        self.thread.start()
        return self.status()

    def stop(self):
        if not self.running():
            raise ValueError('Kein Umzug aktiv.')
        self.cancel.set()
        return self.status()

    def _run(self, ctx, plan):
        kind = plan['kind']
        _low_io_priority()
        hold = kind in ('downloads', 'cache')
        try:
            if kind == 'imdb':
                _IMDB_HOLD.set()
                self._set(phase='waiting', current='Wartet, bis der laufende IMDb-Neuaufbau fertig ist')
                while ctx.imdb_busy():
                    if self.cancel.wait(2):
                        raise InterruptedError('abgebrochen')
            if hold:
                _HOLD.set()
                self._set(phase='waiting', current='Wartet, bis der laufende Download fertig ist')
                while ctx.active_downloads():
                    if self.cancel.wait(2):
                        raise InterruptedError('abgebrochen')
            mode = plan['check']['mode']
            manifest = {}
            if mode == 'copy':
                target = Path(plan['target'])
                target.mkdir(parents=True, exist_ok=True)
                info = {'kind': kind, 'source': plan['source'], 'target': plan['target'], 'started': time.time(),
                        'top_exclude': plan['top_exclude'], 'exclude': plan['exclude'], 'files': _read_staging(target)}
                _write_staging(target, info)
                self._set(phase='copying')
                manifest = sync_tree(plan['source'], target, top_exclude=plan['top_exclude'], exclude=plan['exclude'],
                                     progress=lambda s: self._set(**s), cancelled=self.cancel.is_set,
                                     manifest=info['files'], staging_info=info)
                self._set(phase='verifying', current='')
                report = {}
                bad = verify_tree(plan['source'], target, top_exclude=plan['top_exclude'], exclude=plan['exclude'],
                                  progress=lambda s: self._set(current=s.get('current', '')),
                                  cancelled=self.cancel.is_set, manifest=manifest, live=True, report=report)
                # Downloads/Zwischenspeicher haben keinen Abschluss beim Neustart: seit der Kopie geänderte
                # Dateien noch einmal abgleichen (System und Datenbank: beim Neustart, App dann geschlossen).
                passes = 1
                while kind != 'system' and not bad and report.get('changed') and passes < 3:
                    passes += 1
                    self._set(phase='copying', current='')
                    manifest = sync_tree(plan['source'], target, top_exclude=plan['top_exclude'], exclude=plan['exclude'],
                                         progress=lambda s: self._set(**s), cancelled=self.cancel.is_set,
                                         manifest=manifest, staging_info=info)
                    self._set(phase='verifying', current='')
                    report = {}
                    bad = verify_tree(plan['source'], target, top_exclude=plan['top_exclude'], exclude=plan['exclude'],
                                      cancelled=self.cancel.is_set, manifest=manifest, live=True, report=report)
                if kind != 'system' and report.get('changed'):
                    bad.append('%d Dateien ändern sich während des Umzugs noch' % report['changed'])
                self._set(changed_since_copy=report.get('changed', 0))
                if bad:
                    raise ValueError('Prüfung am Ziel fehlgeschlagen: ' + '; '.join(bad[:5]))
            self._set(phase='switching', current='')
            result = ctx.commit(plan, manifest)
            self._set(phase='ready' if kind == 'system' else 'done', finished=time.time(),
                      restart_needed=kind == 'system', result=result, current='')
            ctx.event('storage_move_done', kind=kind, mode=mode, files=len(manifest))
        except InterruptedError:
            self._set(phase='cancelled', finished=time.time(), current='',
                      error='Abgebrochen. Bereits kopierte Dateien bleiben am Ziel und werden beim nächsten Versuch übernommen; '
                            'der bisherige Ort ist unverändert in Gebrauch.')
            ctx.event('storage_move_cancelled', kind=kind)
        except Exception as exc:
            self._set(phase='failed', finished=time.time(), current='', error=str(exc)[:400])
            ctx.error('storage_move_failed', exc, kind=kind)
        finally:
            if hold:
                _HOLD.clear()
            if kind == 'imdb':
                _IMDB_HOLD.clear()
            ctx.remember(self.status())


MOVER = Mover()


class Context:
    """Bindung an den laufenden Server (Einstellungen, catalog.db, Protokoll)."""

    def __init__(self, home, root, settings, save_settings, db, event=None, error=None, imdb=None):
        self.home, self.root = Path(home), Path(root)
        self.imdb = imdb   # Objekt mit busy() und relocate(folder, available) (server: IMDb-Archiv)
        self.settings, self.save_settings, self.db = settings, save_settings, db
        self.event = event or (lambda *a, **k: None)
        self.error = error or (lambda *a, **k: None)

    # -- Hilfen
    def imdb_busy(self):
        return bool(self.imdb and self.imdb.busy())

    def imdb_dir(self):
        return str(imdb_location(self.home, self.root)[0])

    def active_downloads(self):
        with self.db() as c:
            return c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('downloading','tagging')").fetchone()[0]

    def others(self, kind):
        s = self.settings()
        spots = {'downloads': ('Downloads', s.get('download_dir')),
                 'cache': ('Zwischenspeicher', s.get('cache_dir') and str(Path(s['cache_dir']) / ABO_FOLDER)),
                 'system': ('System und Datenbank', str(self.root))}
        if read_pointer(self.home).get('imdb_dir'):
            spots['imdb'] = ('IMDb-Archiv', self.imdb_dir())
        out = [spots[k] for k in spots if k != kind and spots[k][1]]
        if kind == 'downloads' and not s.get('cache_dir'):
            out = [o for o in out if o[0] != 'Zwischenspeicher']
        return out

    def plan(self, kind, target, mode='copy'):
        s = self.settings()
        target = str(target or '').strip()
        if kind == 'cache':
            base = _norm(target) if target else ''
            dl = s.get('download_dir') or ''
            source = location(s, 'cache')
            dest = str(Path(base) / ABO_FOLDER) if base else ''
            others = [o for o in self.others('cache') if o[0] != 'Downloads' or not base or not same(base, dl)]
            # Abo-Ordner liegt (ohne eigenen Zwischenspeicher) im Downloadordner – das ist kein Konflikt.
            others = [o for o in others if not (o[0] == 'Downloads' and (inside(dest, o[1]) or inside(source, o[1])))]
            check = inspect('cache', source, dest, home=self.home, others=others, mode=mode)
            check['base'] = base
            return {'kind': kind, 'source': source, 'target': check['target'], 'base': base,
                    'top_exclude': [], 'exclude': [], 'check': check}
        if kind == 'downloads':
            source = s.get('download_dir') or ''
            others = self.others('downloads')
            # ohne eigenen Zwischenspeicher ziehen die Abo-Videos mit (Unterordner), sonst ausnehmen
            exclude = [o[1] for o in others if o[1] and inside(o[1], source)]
            check = inspect('downloads', source, target, home=self.home,
                            others=[o for o in others if not inside(o[1], source)], exclude=exclude, mode=mode)
            return {'kind': kind, 'source': source, 'target': check['target'], 'top_exclude': [], 'exclude': exclude,
                    'check': check}
        if kind == 'system':
            source = str(self.root)
            others = self.others('system')
            exclude = [o[1] for o in others if o[1] and inside(o[1], source)]
            if read_pointer(self.home).get('imdb_dir'):
                # 0.6.30: das IMDb-Archiv hat einen eigenen Ort; ein alter Stand im Datenordner zieht nicht mit.
                exclude.append(str(Path(source) / IMDB_FOLDER))
            check = inspect('system', source, target, home=self.home,
                            others=[o for o in others if not inside(o[1], source)], exclude=exclude, mode=mode)
            return {'kind': kind, 'source': source, 'target': check['target'], 'top_exclude': sorted(HOME_ONLY),
                    'exclude': exclude, 'check': check}
        if kind == 'imdb':
            source = self.imdb_dir()
            others = [o for o in self.others('imdb') if o[0] != 'System und Datenbank']
            default = Path(self.root) / IMDB_FOLDER
            # Zurück in den Datenordner ist erlaubt; sonst darf das Archiv nicht in einem anderen Ort liegen.
            if target and not same(target, default):
                others.append(('System und Datenbank', str(self.root)))
            check = inspect('imdb', source, target, home=self.home, others=others, mode=mode)
            return {'kind': kind, 'source': source, 'target': check['target'], 'top_exclude': sorted(IMDB_TRANSIENT),
                    'exclude': [], 'check': check}
        raise ValueError('Unbekannter Speicherort')

    def commit(self, plan, manifest):
        kind, source, target = plan['kind'], plan['source'], plan['target']
        mode = plan['check']['mode']
        if kind == 'imdb':
            return self._commit_imdb(plan, mode)
        if kind == 'system':
            if mode == 'adopt':
                cfg = read_pointer(self.home)
                if same(target, self.home):
                    cfg.pop('data_dir', None)
                else:
                    cfg['data_dir'] = target
                cfg['last'] = {'kind': 'system', 'phase': 'adopted', 'at': time.time(), 'target': target}
                write_pointer(self.home, cfg)
                return {'adopted': True}
            cfg = read_pointer(self.home)
            cfg['pending'] = {'kind': 'system', 'state': 'copied', 'source': source, 'target': target, 'at': time.time()}
            write_pointer(self.home, cfg)
            return {'pending': True}
        s = self.settings()
        markers = dict(s.get('storage_markers') or {})
        if kind == 'downloads':
            Path(target).mkdir(parents=True, exist_ok=True)
            _write_marker(target, PLACE_MARKER, 'downloads')
            s['download_dir'] = target
            s['library_dirs'] = [target if same(p, source) else p for p in (s.get('library_dirs') or [])
                                 if not same(p, target)]
            markers['downloads'] = True
            s['storage_markers'] = markers
            self.save_settings(s)
            # 0.6.37: auch beim Übernehmen vorhandener Daten am Ziel („adopt“) zeigen die Aufträge auf die neue Stelle,
            # dort aber nur, wo die Datei am Ziel wirklich liegt (sonst blieben sie am alten Ort verwaist).
            pairs = [(source, target)] if source else []
            abo_root = None
        else:
            base = plan['base']
            Path(target).mkdir(parents=True, exist_ok=True)
            use_downloads = same(base, s.get('download_dir'))
            if use_downloads:
                s['cache_dir'] = ''
                markers.pop('cache', None)
            else:
                _write_marker(base, PLACE_MARKER, 'cache')
                s['cache_dir'] = base
                markers['cache'] = True
            s['storage_markers'] = markers
            self.save_settings(s)
            pairs = [(source, target)] if source else []
            abo_root = base if mode == 'copy' else None
        changed = 0
        if pairs:
            with self.db() as c:
                changed = rewrite_paths(c, pairs, abo_root=abo_root, only_existing=mode != 'copy')
        if mode == 'copy':
            Path(target, STAGING).unlink(missing_ok=True)
            cfg = read_pointer(self.home)
            previous = dict(cfg.get('previous') or {})
            previous[kind] = {'source': source, 'target': target, 'at': time.time(), 'top_exclude': plan['top_exclude'],
                              'exclude': plan['exclude']}
            cfg['previous'] = previous
            write_pointer(self.home, cfg)
        return {'paths_changed': changed}

    def _commit_imdb(self, plan, mode):
        source, target = plan['source'], plan['target']
        folder = Path(target)
        folder.mkdir(parents=True, exist_ok=True)
        default = same(folder, Path(self.root) / IMDB_FOLDER)
        if not default:
            _write_marker(folder, PLACE_MARKER, 'imdb')
        (folder / STAGING).unlink(missing_ok=True)
        cfg = read_pointer(self.home)
        if default:
            cfg.pop('imdb_dir', None)
        else:
            cfg['imdb_dir'] = str(folder)
        if mode == 'copy' or (source and Path(source, IMDB_DB).is_file() and not same(source, folder)):
            # Beim Übernehmen eines vorhandenen Archivs ist das bisherige nur noch ein ersetzbarer Zwischenstand
            # (es lässt sich jederzeit neu von IMDb laden) und darf auf Wunsch gelöscht werden.
            previous = dict(cfg.get('previous') or {})
            previous['imdb'] = {'source': source, 'target': str(folder), 'at': time.time(),
                                'top_exclude': plan['top_exclude'], 'exclude': [], 'replaceable': mode == 'adopt'}
            cfg['previous'] = previous
        write_pointer(self.home, cfg)
        if self.imdb:
            self.imdb.relocate(folder, True)   # ab sofort liest die Erkennung am neuen Ort
        return {'adopted': mode == 'adopt', 'imdb_dir': str(folder)}

    def remember(self, state):
        cfg = read_pointer(self.home)
        cfg['last'] = {k: state.get(k) for k in ('kind', 'phase', 'source', 'target', 'error', 'finished', 'files_total')}
        write_pointer(self.home, cfg)

    # -- Altdaten
    def cleanup(self, kind, confirm):
        if confirm != CONFIRM:
            raise ValueError('Zum Löschen bitte „%s“ eingeben.' % CONFIRM)
        if MOVER.running():
            raise ValueError('Während eines Umzugs wird nichts gelöscht.')
        cfg = read_pointer(self.home)
        prev = (cfg.get('previous') or {}).get(kind)
        if not prev:
            raise ValueError('Kein alter Speicherort vermerkt.')
        source, target = prev['source'], prev['target']
        s = self.settings()
        current = {'downloads': s.get('download_dir'), 'cache': location(s, 'cache'), 'system': str(self.root),
                   'imdb': self.imdb_dir()}
        if not same(current[kind], target):
            raise ValueError('Der vermerkte neue Ort ist nicht mehr in Gebrauch; zur Sicherheit wird nichts gelöscht.')
        for label, path in current.items():
            if path and (same(source, path) or inside(path, source)):
                raise ValueError('Der alte Ort enthält einen aktiven Speicherort (%s); zur Sicherheit wird nichts gelöscht.'
                                 % KINDS[label])
        if not Path(source).is_dir():
            raise ValueError('Alter Ort nicht erreichbar: %s' % source)
        top = prev.get('top_exclude') or []
        exclude = prev.get('exclude') or []
        if kind == 'imdb' and prev.get('replaceable'):
            result = _remove_replaced_archive(source, target)
        else:
            result = remove_verified(source, target, top_exclude=top, exclude=exclude)
        if kind != 'system' or not same(source, self.home):
            try:
                if not any(Path(source).iterdir()):
                    Path(source).rmdir()
            except OSError:
                pass
        previous = dict(cfg.get('previous') or {})
        if result['kept'] == 0:
            previous.pop(kind, None)
        else:
            previous[kind] = dict(prev, left=result['kept'])
        cfg['previous'] = previous
        write_pointer(self.home, cfg)
        self.event('storage_old_removed', kind=kind, removed=result['removed'], kept=result['kept'], freed=result['freed'])
        return result

    def dismiss(self, kind):
        """Altdaten-Hinweis ausblenden (nichts wird gelöscht)."""
        cfg = read_pointer(self.home)
        previous = dict(cfg.get('previous') or {})
        previous.pop(kind, None)
        cfg['previous'] = previous
        if kind == 'system' and (cfg.get('pending') or {}).get('state') == 'failed':
            cfg.pop('pending', None)
        if kind == 'system':
            cfg.pop('abandoned', None)
        write_pointer(self.home, cfg)
        return {'ok': True}

    def revert(self):
        """„Bisherigen Ort verwenden“: nur den Zeiger zurückstellen, wirksam beim Neustart."""
        if MOVER.running():
            raise ValueError('Bitte zuerst den laufenden Umzug abbrechen.')
        info = revert_system(self.home)
        self.event('storage_reverted', target=info['path'], left=info['current'])
        return dict(info, restart_needed=True)

    def cancel_pending(self):
        """Vorbereiteten System-Umzug verwerfen (Kopie am Ziel bleibt liegen)."""
        cfg = read_pointer(self.home)
        cfg.pop('pending', None)
        write_pointer(self.home, cfg)
        if MOVER.status().get('phase') == 'ready':
            MOVER._set(phase='idle', restart_needed=False)
        return {'ok': True}

    # -- Überblick
    def overview(self):
        s = self.settings()
        cfg = read_pointer(self.home)
        rows = []
        defaults = {'downloads': '', 'cache': '', 'system': str(self.home), 'imdb': str(Path(self.root) / IMDB_FOLDER)}
        imdb_folder, imdb_ok = imdb_location(self.home, self.root)
        for kind in KINDS:
            path = str(imdb_folder) if kind == 'imdb' else location(s, kind, self.root)
            space = _bounded(('disk', path), lambda p=path: disk(p), ttl=20.0, wait=2.0,
                             default={'free': 0, 'total': 0}) or {'free': 0, 'total': 0}
            reachable = _bounded(('exists', path), lambda p=path: bool(p) and Path(p).exists(), ttl=10.0, wait=2.0,
                                 default=None)
            item = {'kind': kind, 'label': KINDS[kind], 'path': path, 'free': space['free'], 'total': space['total'],
                    'reachable': reachable, 'suggest': SUBFOLDER[kind]}
            if kind == 'cache':
                item['base'] = s.get('cache_dir') or ''
                item['shared_with_downloads'] = not s.get('cache_dir')
            if kind == 'system':
                item['default'] = defaults['system']
                item['is_default'] = same(self.root, self.home)
            if kind == 'imdb':
                item['default'] = defaults['imdb']
                item['is_default'] = not cfg.get('imdb_dir')
                if self.imdb and hasattr(self.imdb, 'timing'):
                    item['timing'] = self.imdb.timing()
                if not imdb_ok:
                    item['reachable'] = False
                    item['problem'] = ('IMDb-Archiv nicht erreichbar: %s. Laufwerk verbinden; bis dahin läuft die '
                                       'Erkennung ohne IMDb-Abgleich.' % path)
            rows.append(item)
        for problem in problems(s):
            for row in rows:
                if row['kind'] == problem['kind']:
                    row['problem'] = problem['text']
                    row['reachable'] = False
        return {'locations': rows, 'move': MOVER.status(), 'previous': cfg.get('previous') or {},
                'pending': cfg.get('pending'), 'last': cfg.get('last'), 'volumes': _bounded('volumes', volumes, ttl=60.0, wait=3.0, default=[]) or [],
                'revert': revert_info(self.home), 'abandoned': cfg.get('abandoned'),
                'restart_supported': os.name == 'posix', 'confirm': CONFIRM}


def main(argv=None):
    """Startskripte (0.6.25): ``--revert-info`` / ``--revert`` ohne laufenden Server."""
    import argparse
    parser = argparse.ArgumentParser(description='MediathekAtlas-Speicherorte')
    parser.add_argument('--home', default=None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--revert-info', action='store_true')
    group.add_argument('--revert', action='store_true')
    args = parser.parse_args(argv)
    home = Path(args.home) if args.home else default_home()
    if args.revert_info:
        info = revert_info(home)
        if not info:
            return 1
        print('%s (Stand %s)' % (info['path'], info['stand'] or 'unbekannt'))
        return 0
    try:
        info = revert_system(home)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print('Datenordner zurückgestellt auf %s; %s bleibt unverändert liegen.' % (info['path'], info['current']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
