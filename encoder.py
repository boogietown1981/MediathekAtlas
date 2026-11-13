"""Umwandeln fertiger Downloads in 1080p, 720p oder 480p (0.5.94).

The function the Jellyfin Encoder ("Media Manager") has, built into MediathekAtlas with the ffmpeg
that is already required for downloads: a finished download is re-encoded to a smaller picture
(H.264 in an MKV file, every sound track and subtitle kept as it is) to save space or to suit a
weaker player.

Rules:
* Never larger than the source: a file that already has the wished height or less is refused.
* One conversion at a time, with lowered priority, so the app stays usable on an old Mac mini or NAS.
* The result is written next to the source as ``<name>.partial`` and only becomes a real file after
  it was checked (readable, same running time, the wished height).
* Default: the result is stored beside the original (``Titel [720p].mkv``). Only when the user asked
  for it and confirmed, the original is replaced - after the check, never before.
* A conversion that was interrupted (app closed, power cut) starts again; its partial file is removed.

``plan``, ``command`` and ``verify`` are pure; ``Worker`` runs the queue (``encoder.sqlite3``).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

DB_NAME = 'encoder.sqlite3'
SCHEMA = """
CREATE TABLE IF NOT EXISTS encode_jobs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 job_id TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL,
 target TEXT NOT NULL,
 profile TEXT NOT NULL,
 speed TEXT NOT NULL DEFAULT 'fast',
 replace_original INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'queued',
 progress REAL NOT NULL DEFAULT 0,
 source_bytes INTEGER NOT NULL DEFAULT 0,
 result_bytes INTEGER NOT NULL DEFAULT 0,
 source_height INTEGER NOT NULL DEFAULT 0,
 duration REAL NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '',
 cancel INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL,
 started REAL,
 finished REAL);
CREATE INDEX IF NOT EXISTS encode_jobs_state ON encode_jobs(state,id);
"""
# height, quality (x264 CRF; lower = better and larger) and a label
PROFILES = {'1080': {'height': 1080, 'crf': 21, 'label': 'Full HD (1080p)'},
            '720': {'height': 720, 'crf': 22, 'label': 'HD (720p)'},
            '480': {'height': 480, 'crf': 23, 'label': 'SD (480p)'}}
SPEEDS = {'fast': {'preset': 'veryfast', 'label': 'Schnell (größere Datei)'},
          'balanced': {'preset': 'medium', 'label': 'Ausgewogen (kleinere Datei, deutlich langsamer)'}}
VIDEO_EXT = ('.mkv', '.mp4', '.m4v', '.mov', '.avi', '.webm', '.ts', '.mpg', '.mpeg', '.ogv', '.wmv', '.flv')
TEXT_SUBTITLES_MP4 = ('mov_text', 'tx3g')        # cannot be copied into MKV; written as SubRip instead
MAX_QUEUE = 200
KEEP_FINISHED = 100
DURATION_TOLERANCE = 0.02                        # 2 % or 2 seconds, whichever is more
_LOCK = threading.Lock()


def connect(root):
    db = sqlite3.connect(Path(root) / DB_NAME, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


# ---- pure parts ---------------------------------------------------------------------------

def read_probe(document):
    """Facts of an ffprobe JSON answer that the conversion needs."""
    streams = document.get('streams') if isinstance(document, dict) else None
    if not isinstance(streams, list):
        raise ValueError('Die Datei ließ sich nicht lesen')
    video = next((s for s in streams if s.get('codec_type') == 'video' and (s.get('disposition') or {}).get('attached_pic') != 1), None)
    if not video:
        raise ValueError('Die Datei enthält kein Videobild')

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    duration = number((document.get('format') or {}).get('duration')) or number(video.get('duration'))
    return {'height': int(number(video.get('height'))), 'width': int(number(video.get('width'))), 'duration': duration,
            'video_codec': str(video.get('codec_name') or ''),
            'audio': sum(1 for s in streams if s.get('codec_type') == 'audio'),
            'subtitles': [str(s.get('codec_name') or '') for s in streams if s.get('codec_type') == 'subtitle']}


def plan(info, profile):
    """Check a wish against the source. Returns the profile; refuses anything that would not make the picture smaller."""
    if profile not in PROFILES:
        raise ValueError('Unbekannte Zielauflösung')
    wanted = PROFILES[profile]
    if info['height'] <= 0 or info['duration'] <= 0:
        raise ValueError('Auflösung oder Laufzeit der Datei sind nicht lesbar')
    if info['height'] <= wanted['height']:
        raise ValueError('Die Datei hat bereits %dp; umgewandelt wird nur in eine kleinere Auflösung' % info['height'])
    return wanted


def target_path(source, profile, replace=False):
    """Where the result goes: beside the source, or (replace) under the source's own name as MKV."""
    source = Path(source)
    return source.with_suffix('.mkv') if replace else source.with_name('%s [%sp].mkv' % (source.stem, PROFILES[profile]['height']))


def command(ffmpeg, source, output, info, profile, speed='fast'):
    """The ffmpeg call. Picture: H.264 at the wished height, never upscaled, width kept even. Sound and subtitles are copied."""
    wanted, pace = PROFILES[profile], SPEEDS[speed]
    args = [str(ffmpeg), '-hide_banner', '-nostdin', '-y', '-i', str(source), '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?',
            '-vf', 'scale=-2:%d' % wanted['height'], '-c:v', 'libx264', '-preset', pace['preset'], '-crf', str(wanted['crf']),
            '-pix_fmt', 'yuv420p', '-c:a', 'copy']
    if any(codec in TEXT_SUBTITLES_MP4 for codec in info.get('subtitles') or []):
        args += ['-c:s', 'srt']
    else:
        args += ['-c:s', 'copy']
    return args + ['-map_metadata', '0', '-map_chapters', '0', '-max_muxing_queue_size', '2048', '-f', 'matroska',
                   '-progress', 'pipe:1', '-nostats', str(output)]


def verify(source_info, result_info, profile):
    """A result counts only when it has the wished height and (nearly) the source's running time. Returns '' or the reason."""
    wanted = PROFILES[profile]['height']
    if result_info['height'] != wanted:
        return 'Ergebnis hat %dp statt %dp' % (result_info['height'], wanted)
    allowed = max(2.0, source_info['duration'] * DURATION_TOLERANCE)
    if abs(result_info['duration'] - source_info['duration']) > allowed:
        return 'Laufzeit weicht ab (%.0f s statt %.0f s)' % (result_info['duration'], source_info['duration'])
    if result_info['audio'] != source_info['audio']:
        return 'Tonspuren fehlen (%d statt %d)' % (result_info['audio'], source_info['audio'])
    return ''


def progress_of(line, duration):
    """0..1 from one line of ffmpeg's -progress output, or None."""
    key, _, value = line.partition('=')
    if key.strip() not in ('out_time_us', 'out_time_ms') or duration <= 0:
        return None
    try:
        return max(0.0, min(1.0, int(value) / 1_000_000 / duration))
    except ValueError:
        return None


# ---- the queue ----------------------------------------------------------------------------

def probe(ffprobe, path):
    done = subprocess.run([str(ffprobe), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)],
                          capture_output=True, timeout=120)
    if done.returncode:
        raise ValueError('Die Datei ließ sich nicht lesen')
    try:
        return read_probe(json.loads(done.stdout))
    except json.JSONDecodeError:
        raise ValueError('Die Datei ließ sich nicht lesen') from None


def add(root, job, profile, tools, speed='fast', replace=False, now=None):
    """Queue one finished download. ``job`` is its record from the download list; ``tools`` names ffmpeg and ffprobe."""
    if not tools.get('ffmpeg') or not tools.get('ffprobe'):
        raise ValueError('Zum Umwandeln fehlen FFmpeg und ffprobe')
    if speed not in SPEEDS:
        raise ValueError('Unbekanntes Tempo')
    source = Path(str(job.get('path') or job.get('target') or ''))
    if not source.is_file() or source.suffix.lower() not in VIDEO_EXT:
        raise ValueError('Die Videodatei dieses Downloads liegt nicht mehr am gespeicherten Ort')
    info = probe(tools['ffprobe'], source)
    plan(info, profile)
    target = target_path(source, profile, replace)
    if target.exists() and target != source:
        # Also when replacing: 'Film.mp4' must never overwrite an unrelated 'Film.mkv'.
        raise ValueError('„%s“ gibt es bereits' % target.name)
    size = source.stat().st_size
    free = shutil.disk_usage(source.parent).free
    if free < size:
        raise ValueError('Zu wenig freier Platz: für die Umwandlung müssen mindestens %.1f GB frei sein' % (size / 1024 ** 3))
    meta = job.get('metadata') or {}
    title = str(meta.get('title') or source.stem)[:200]
    with _LOCK:
        db = connect(root)
        try:
            with db:
                if db.execute("SELECT 1 FROM encode_jobs WHERE source=? AND state IN ('queued','running')", (str(source),)).fetchone():
                    raise ValueError('Diese Datei wird bereits umgewandelt oder wartet darauf')
                if db.execute("SELECT COUNT(*) FROM encode_jobs WHERE state IN ('queued','running')").fetchone()[0] >= MAX_QUEUE:
                    raise ValueError('Die Warteschlange ist voll (%d Aufträge)' % MAX_QUEUE)
                cursor = db.execute("""INSERT INTO encode_jobs(job_id,title,source,target,profile,speed,replace_original,source_bytes,source_height,duration,created)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (str(job.get('id') or ''), title, str(source), str(target), profile, speed, int(bool(replace)), size,
                                                         info['height'], info['duration'], time.time() if now is None else now))
                return {'id': cursor.lastrowid, 'target': target.name, 'source_height': info['height']}
        finally:
            db.close()


def _public(row):
    out = {k: row[k] for k in ('id', 'job_id', 'title', 'profile', 'speed', 'state', 'progress', 'source_bytes', 'result_bytes',
                               'source_height', 'duration', 'error', 'created', 'started', 'finished')}
    out['file'] = Path(row['source']).name
    out['target'] = Path(row['target']).name
    out['replace'] = bool(row['replace_original'])
    out['label'] = PROFILES.get(row['profile'], {}).get('label', row['profile'])
    return out


def listing(root, tools=None):
    db = connect(root)
    try:
        rows = [_public(r) for r in db.execute("""SELECT * FROM encode_jobs ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END,
            CASE WHEN state IN ('running','queued') THEN id ELSE -id END LIMIT 300""")]
    finally:
        db.close()
    tools = tools or {}
    return {'jobs': rows, 'active': sum(1 for r in rows if r['state'] in ('queued', 'running')),
            'available': bool(tools.get('ffmpeg') and tools.get('ffprobe')),
            'profiles': [{'id': key, 'label': value['label']} for key, value in PROFILES.items()],
            'speeds': [{'id': key, 'label': value['label']} for key, value in SPEEDS.items()],
            'note': 'Es läuft immer nur eine Umwandlung, mit gesenkter Priorität. Ton und Untertitel bleiben unverändert.'}


def cancel(root, encode_id):
    """Stop a waiting or running conversion. The source is never touched by a cancel."""
    db = connect(root)
    try:
        with db:
            row = db.execute('SELECT state FROM encode_jobs WHERE id=?', (int(encode_id),)).fetchone()
            if not row:
                raise ValueError('Auftrag nicht gefunden')
            if row['state'] == 'queued':
                db.execute("UPDATE encode_jobs SET state='cancelled',finished=? WHERE id=?", (time.time(), int(encode_id)))
            elif row['state'] == 'running':
                db.execute('UPDATE encode_jobs SET cancel=1 WHERE id=?', (int(encode_id),))
            else:
                raise ValueError('Dieser Auftrag läuft nicht mehr')
    finally:
        db.close()
    return {'ok': True}


def clear(root):
    """Forget finished, failed and cancelled conversions (the list only; no file is touched)."""
    db = connect(root)
    try:
        with db:
            removed = db.execute("DELETE FROM encode_jobs WHERE state IN ('done','error','cancelled')").rowcount
    finally:
        db.close()
    return {'removed': removed}


def _lower_priority():
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


class Worker:
    """Runs the queue, one conversion at a time."""

    def __init__(self, root, tools, replaced=None, event=None, error=None):
        self.root, self.tools = Path(root), tools            # tools: () -> {'ffmpeg': path, 'ffprobe': path}
        self.replaced = replaced or (lambda job_id, old, new: None)   # the download list learns the new file
        self.event = event or (lambda name, **kw: None)
        self.error = error or (lambda name, exc: None)

    def recover(self):
        """After a restart: what was running starts again; its partial file is removed."""
        db = connect(self.root)
        try:
            with db:
                for row in db.execute("SELECT id,target FROM encode_jobs WHERE state='running'").fetchall():
                    Path(row['target'] + '.partial').unlink(missing_ok=True)
                    db.execute("UPDATE encode_jobs SET state='queued',progress=0,cancel=0,started=NULL WHERE id=?", (row['id'],))
                db.execute("""DELETE FROM encode_jobs WHERE state IN ('done','error','cancelled') AND id NOT IN
                    (SELECT id FROM encode_jobs WHERE state IN ('done','error','cancelled') ORDER BY id DESC LIMIT ?)""", (KEEP_FINISHED,))
        finally:
            db.close()

    def _set(self, encode_id, **values):
        db = connect(self.root)
        try:
            with db:
                db.execute('UPDATE encode_jobs SET %s WHERE id=?' % ','.join(k + '=?' for k in values), (*values.values(), encode_id))
        finally:
            db.close()

    def _cancelled(self, encode_id):
        db = connect(self.root)
        try:
            return bool(db.execute('SELECT cancel FROM encode_jobs WHERE id=?', (encode_id,)).fetchone()[0])
        finally:
            db.close()

    def claim(self):
        with _LOCK:
            db = connect(self.root)
            try:
                with db:
                    row = db.execute("SELECT * FROM encode_jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
                    if not row:
                        return None
                    task = dict(row, started=time.time())
                    db.execute("UPDATE encode_jobs SET state='running',started=?,progress=0,error='' WHERE id=?", (task['started'], row['id']))
                return task
            finally:
                db.close()

    def run_one(self, stop=None):
        """Convert the next waiting file. Returns its final state, or None when nothing waits."""
        task = self.claim()
        if not task:
            return None
        encode_id, source, target = task['id'], Path(task['source']), Path(task['target'])
        partial = Path(str(target) + '.partial')
        state, message, result_bytes = 'error', '', 0
        try:
            tools = self.tools()
            if not tools.get('ffmpeg') or not tools.get('ffprobe'):
                raise ValueError('FFmpeg oder ffprobe fehlen')
            if not source.is_file():
                raise ValueError('Die Quelldatei ist nicht mehr da')
            info = probe(tools['ffprobe'], source)
            plan(info, task['profile'])
            partial.unlink(missing_ok=True)
            process = subprocess.Popen(command(tools['ffmpeg'], source, partial, info, task['profile'], task['speed']),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace',
                                       preexec_fn=_lower_priority if os.name == 'posix' else None)
            tail = []
            reader = threading.Thread(target=lambda: tail.extend(process.stderr.read().splitlines()[-12:]), daemon=True)
            reader.start()
            last, stopped = 0.0, False
            for line in process.stdout:
                done = progress_of(line, info['duration'])
                if done is None or time.time() - last < 1.5:
                    continue
                last = time.time()
                self._set(encode_id, progress=round(done, 4))
                if (stop is not None and stop.is_set()) or self._cancelled(encode_id):
                    stopped = True
                    process.terminate()
                    break
            try:
                code = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
            reader.join(5)
            if stopped:
                if stop is not None and stop.is_set():
                    # The app is closing: the conversion starts again next time.
                    partial.unlink(missing_ok=True)
                    self._set(encode_id, state='queued', progress=0, started=None)
                    return 'queued'
                state, message = 'cancelled', ''
            elif code:
                raise ValueError('FFmpeg brach ab: ' + (' | '.join(t.strip() for t in tail[-3:] if t.strip()) or 'Code %s' % code)[:400])
            else:
                problem = verify(info, probe(tools['ffprobe'], partial), task['profile'])
                if problem:
                    raise ValueError('Ergebnis verworfen: ' + problem)
                if target.exists() and target != source:
                    raise ValueError('„%s“ gibt es inzwischen; nichts überschrieben' % target.name)
                result_bytes = partial.stat().st_size
                os.replace(partial, target)                 # same name as an MKV original: replaced in one step
                if task['replace_original']:
                    self.replaced(task['job_id'], str(source), str(target))
                    if source != target:
                        source.unlink(missing_ok=True)
                state = 'done'
        except Exception as error:                           # one failed file must not stop the queue
            message = str(error)[:500] if isinstance(error, ValueError) else type(error).__name__ + ': ' + str(error)[:400]
            self.error('encoder_failed', error)
        finally:
            if state != 'done':
                partial.unlink(missing_ok=True)
        self._set(encode_id, state=state, error=message, result_bytes=result_bytes, finished=time.time(),
                  progress=1.0 if state == 'done' else 0.0, cancel=0)
        self.event('encoder_finished', state=state, profile=task['profile'], replaced=bool(task['replace_original']) and state == 'done',
                   source_mb=round(task['source_bytes'] / 1048576), result_mb=round(result_bytes / 1048576),
                   seconds=round(time.time() - (task.get('started') or time.time())))
        return state

    def loop(self, stop, idle=5.0):
        try:
            self.recover()
        except Exception as error:
            self.error('encoder_recover_failed', error)
        while not stop.wait(idle):
            try:
                while not stop.is_set() and self.run_one(stop) not in (None, 'queued'):
                    pass
            except Exception as error:
                self.error('encoder_loop_failed', error)
