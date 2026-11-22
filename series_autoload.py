"""0.6.94: Angefangene Serien automatisch offline laden.

Björn (22.11.2026): „wenn ein Film bzw. eine Folge einer Serie komplett angeschaut wurde, dass diese Serie dann
komplett offline runtergeladen wird“.

Ablauf
* Signal: ``watch_state`` ``done`` (Player oder Kinderecke bis 45 s vor dem Ende bzw. bis zum Schluss), dasselbe
  Signal wie das YouTube-Archiv (0.6.89). Gelesen wird nur, was seit dem letzten Durchlauf neu zu Ende gesehen
  wurde (Merker ``series_autoload_cursor``); beim ersten Start die letzten 7 Tage.
* Eine zu Ende gesehene Folge (Schlüssel = Werk, ``offer:<id>`` oder ``job:<id>``) aktiviert ihre Serie
  (``works.show_key``). Ein zu Ende gesehener Film wird selbst dauerhaft offline gespeichert (Björn 22.11.: „da die
  Chance groß ist, dass meine Tochter sie noch mal sehen möchte“), aber nicht seine „Reihe“: die ist bei Filmen
  meist nur ein Sendeplatz („Sechs auf einen Streich“, „FilmMittwoch“), kein eindeutiger Zusammenhang.
  Mediathek-Downloads haben keine 30-Tage-Frist und zählen zu keinem Abo-Budget: der normale Downloadordner ist
  damit das dauerhafte „Archiv“; nur der freie Platz (Reserve) bremst.
* Geladen wird nur, was „Ganze Serie laden“ (``series_download.plan``) auch erlaubt: ARD, ZDF & Co. mit
  direkter Videodatei, bestätigter Staffel/Folge, verfügbar, noch nicht vorhanden. Kein DRM, keine Link-Anbieter.
* Speicherschutz: je Serie höchstens ``series_autoload_max`` ungesehene Folgen und ``series_autoload_gb`` GB
  gleichzeitig (gleitendes Fenster: jede gesehene Folge macht Platz für die nächste, so wird eine kurze Serie
  komplett, eine lange oder tägliche nicht blind); vorher die Abo-Reserve am Downloadordner
  (``youtube_abos.no_room``: freie Reserve und Platz für das nächste IMDb-Update) und, falls gesetzt, das
  Speicherbudget der Speicherverwaltung. Eine einmal eingereihte Folge wird nie automatisch neu eingereiht
  (abgebrochen bleibt abgebrochen).
* Folgen nach der gesehenen kommen zuerst, dann frühere, die noch nicht gesehen sind.

Keine KI, keine Anmeldung, kein Umgehen von Kopierschutz.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

GB = 1024 ** 3
MAX_CHOICES = (5, 10, 20, 40, 80)
MAX_DEFAULT = 20
GB_CHOICES = (5, 10, 20, 40, 80)
GB_DEFAULT = 20
FIRST_LOOKBACK = 7 * 86400
CHECK_EVERY = 30 * 60            # Nachschau je aktiver Serie (neue Folgen, gesehene Folgen machen Platz)
PER_RUN = max(MAX_CHOICES)        # 0.6.101: das Fenster füllt sich im ersten Lauf (vorher 10 je 30 min)
GB_PER_HOUR = 1.6                # Schätzung für die HD-Datei der Sender (720p ≈ 3,5 Mbit/s)
FALLBACK_BYTES = int(0.8 * GB)
ACTIVE_STATES = ('queued', 'downloading', 'tagging')

SCHEMA = """
CREATE TABLE IF NOT EXISTS series_autoload(
 show_key TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'active',
 created REAL NOT NULL, updated REAL NOT NULL, trigger_work TEXT NOT NULL DEFAULT '',
 last_season INTEGER, last_episode INTEGER, last_watched REAL NOT NULL DEFAULT 0,
 next_check REAL NOT NULL DEFAULT 0, queued_total INTEGER NOT NULL DEFAULT 0,
 eligible INTEGER NOT NULL DEFAULT 0, unconfirmed INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT 'series');
CREATE TABLE IF NOT EXISTS series_autoload_items(
 show_key TEXT NOT NULL, work_id TEXT NOT NULL, job_id TEXT NOT NULL, created REAL NOT NULL,
 estimate INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(show_key, work_id));
CREATE INDEX IF NOT EXISTS series_autoload_items_job ON series_autoload_items(job_id);
"""


def initialize(c):
    c.executescript(SCHEMA)


def config(s):
    """Schalter und Grenzen aus den Einstellungen (Standard: an, 20 Folgen, 20 GB je Serie)."""
    s = s or {}
    try:
        most = int(s.get('series_autoload_max', MAX_DEFAULT))
    except (TypeError, ValueError):
        most = MAX_DEFAULT
    try:
        gb = int(s.get('series_autoload_gb', GB_DEFAULT))
    except (TypeError, ValueError):
        gb = GB_DEFAULT
    return {'enabled': s.get('series_autoload', True) is not False,
            'films': s.get('film_autoload', True) is not False,
            'max': most if most in MAX_CHOICES else MAX_DEFAULT,
            'gb': gb if gb in GB_CHOICES else GB_DEFAULT,
            'max_choices': list(MAX_CHOICES), 'gb_choices': list(GB_CHOICES)}


def clean_settings(d, s):
    """Übernimmt Schalter und Grenzen in das Einstellungs-dict ``s`` (prüft die erlaubten Werte)."""
    if 'enabled' in d:
        s['series_autoload'] = bool(d['enabled'])
    if 'films' in d:
        s['film_autoload'] = bool(d['films'])
    if 'max' in d:
        try:
            value = int(d['max'])
        except (TypeError, ValueError):
            value = -1
        if value not in MAX_CHOICES:
            raise ValueError('Erlaubt sind %s Folgen je Serie' % ', '.join(map(str, MAX_CHOICES)))
        s['series_autoload_max'] = value
    if 'gb' in d:
        try:
            value = int(d['gb'])
        except (TypeError, ValueError):
            value = -1
        if value not in GB_CHOICES:
            raise ValueError('Erlaubt sind %s GB je Serie' % ', '.join(map(str, GB_CHOICES)))
        s['series_autoload_gb'] = value
    return s


def estimate(meta, source):
    """Geschätzte Größe einer Folge (Byte): Dauer × HD-Rate, sonst die Filmlisten-Größe × 2,5, sonst 0,8 GB."""
    try:
        duration = float((source or {}).get('duration') or (meta or {}).get('runtime') or 0)
    except (TypeError, ValueError):
        duration = 0
    if 60 <= duration <= 6 * 3600:
        return int(duration / 3600 * GB_PER_HOUR * GB)
    try:
        size = int((source or {}).get('size') or 0)
    except (TypeError, ValueError):
        size = 0
    return int(size * 2.5) if size > 0 else FALLBACK_BYTES


# ----------------------------------------------------------------- Signal: welche Serie wurde angefangen?
def _work(c, work_id):
    if not work_id:
        return None
    row = c.execute('SELECT id,kind,show_key,meta,state FROM works WHERE id=?', (work_id,)).fetchone()
    if row is None:
        alias = c.execute('SELECT new_id FROM work_aliases WHERE old_id=?', (work_id,)).fetchone()
        if alias:
            row = c.execute('SELECT id,kind,show_key,meta,state FROM works WHERE id=?', (alias[0],)).fetchone()
    return row


def _offer_work(c, offer_id):
    if not offer_id:
        return None
    found = c.execute('SELECT work_id FROM offers WHERE id=?', (offer_id,)).fetchone()
    return _work(c, found[0]) if found else None


def resolve(c, key, ref=None):
    """Werk zu einem Eintrag aus watch.sqlite3: Werk-ID, ``offer:<id>``, ``job:<id>`` oder Angebots-ID."""
    key = str(key or '')
    ref = ref if isinstance(ref, dict) else {}
    name, _, value = key.partition(':')
    if name not in ('offer', 'job') or not value:
        if name in watch_state_sources():
            return None                    # Pluto, ServusTV, Joyn …: keine Serien aus dem Senderkatalog
        return _work(c, key) or _offer_work(c, key) or _offer_work(c, ref.get('offer'))
    if name == 'offer':
        return _offer_work(c, value)
    if name == 'job':
        row = c.execute('SELECT payload FROM jobs WHERE id=?', (value,)).fetchone()
        if not row:
            return None
        try:
            job = json.loads(row[0])
        except ValueError:
            return None
        if job.get('youtube_abo') or job.get('origin'):
            return None                    # YouTube-Abos und Portal-Kopien haben eigene Regeln
        return _offer_work(c, (job.get('source') or {}).get('_id')) or _offer_work(c, job.get('offer_id'))
    return None


def watch_state_sources():
    import watch_state
    return set(watch_state.REF_KEYS) - {'offer', 'job'}


def activate(c, work, now, films=True):
    """Serie eines zu Ende gesehenen Werks einschalten (beendete Serien bleiben aus); ein Film wird einmal
    vorgemerkt (Schlüssel ``film:<Werk>``)."""
    if work is not None and work['kind'] == 'movie' and films:
        show = 'film:' + work['id']
        if c.execute('SELECT 1 FROM series_autoload WHERE show_key=?', (show,)).fetchone():
            return None
        try:
            title = str(json.loads(work['meta'] or '{}').get('title') or '')[:200]
        except ValueError:
            title = ''
        c.execute('''INSERT INTO series_autoload(show_key,title,state,created,updated,trigger_work,last_watched,next_check,kind)
                     VALUES(?,?,'active',?,?,?,?,0,'movie')''', (show, title, now, now, work['id'], now))
        return 'new'
    if work is None or work['kind'] != 'series' or not work['show_key']:
        return None
    try:
        meta = json.loads(work['meta'] or '{}')
    except ValueError:
        meta = {}
    season = meta.get('season') if isinstance(meta.get('season'), int) else None
    episode = meta.get('episode') if isinstance(meta.get('episode'), int) else None
    show = work['show_key']
    row = c.execute('SELECT state,last_season,last_episode FROM series_autoload WHERE show_key=?', (show,)).fetchone()
    if row is None:
        c.execute('''INSERT INTO series_autoload(show_key,title,state,created,updated,trigger_work,last_season,last_episode,
                     last_watched,next_check) VALUES(?,?,?,?,?,?,?,?,?,0)''',
                  (show, str(meta.get('title') or '')[:200], 'active', now, now, work['id'], season, episode, now))
        return 'new'
    if row['state'] == 'stopped':
        return None
    later = season is not None and episode is not None and (
        row['last_season'] is None or (season, episode) > (row['last_season'], row['last_episode'] or 0))
    c.execute('''UPDATE series_autoload SET updated=?,last_watched=?,next_check=0,
                 last_season=CASE WHEN ? THEN ? ELSE last_season END,
                 last_episode=CASE WHEN ? THEN ? ELSE last_episode END WHERE show_key=?''',
              (now, now, int(later), season, int(later), episode, show))
    return 'seen'


def collect(root, c, now, films=True):
    """Neu zu Ende Gesehenes einlesen und die Serien einschalten. Ergebnis: Zahl eingeschalteter Serien."""
    import catalog
    import watch_state
    cursor = catalog.get_state(c, 'series_autoload_cursor', None)
    if cursor is None:
        cursor = now - FIRST_LOOKBACK
    entries = watch_state.finished_since(root, cursor)
    started = 0
    for e in entries:
        if activate(c, resolve(c, e['key'], e['ref']), now, films) == 'new':
            started += 1
        cursor = max(cursor, e['watched_at'])
    if entries or catalog.get_state(c, 'series_autoload_cursor', None) is None:
        catalog.set_state(c, 'series_autoload_cursor', cursor)
    return started


# ----------------------------------------------------------------- Nachladen
def _watched_keys(root):
    import watch_state
    try:
        return {k for k, v in watch_state.states(root).items() if v.get('done')}
    except Exception:
        return set()


def _seen(done, work_id, offer_ids=(), job_id=''):
    keys = {work_id, *offer_ids, *('offer:' + o for o in offer_ids)}
    if job_id:
        keys.add('job:' + job_id)
    return bool(keys & done)


def _offers(c, work_id):
    return [r[0] for r in c.execute('SELECT id FROM offers WHERE work_id=? LIMIT 40', (work_id,))]


def held(c, show, done):
    """Automatisch geladene, noch nicht gesehene Folgen einer Serie: (Anzahl, geschätzte Byte, laufend, fertig)."""
    count = size = running = finished = 0
    for item in c.execute('''SELECT i.work_id,i.job_id,i.estimate,j.state,j.payload FROM series_autoload_items i
                             JOIN jobs j ON j.id=i.job_id WHERE i.show_key=?''', (show,)).fetchall():
        if item['state'] not in (*ACTIVE_STATES, 'done'):
            continue
        if _seen(done, item['work_id'], _offers(c, item['work_id']), item['job_id']):
            continue
        count += 1
        real = 0
        if item['state'] == 'done':
            finished += 1
            try:
                path = json.loads(item['payload']).get('path') or ''
                real = Path(path).stat().st_size if path else 0
            except (OSError, ValueError):
                real = 0
        else:
            running += 1
        size += real or item['estimate']
    return count, size, running, finished


def pending_bytes(c):
    """Geschätzte Byte aller noch nicht fertigen automatischen Aufträge (für die Platzreserve)."""
    row = c.execute('''SELECT SUM(i.estimate) FROM series_autoload_items i JOIN jobs j ON j.id=i.job_id
                       WHERE j.state IN ('queued','downloading','tagging')''').fetchone()
    return int(row[0] or 0)


def _budget_note(c, root, download_dir, extra):
    """Speicherbudget der Speicherverwaltung (falls gesetzt) überschritten → Hinweis, sonst ''."""
    import storage_policy
    budget = storage_policy.load(root).get('budget_gb') or 0
    if not budget:
        return ''
    try:
        import watch_state
        used = storage_policy.overview(c, root, download_dir, watch_state.states(root)).get('used_bytes') or 0
    except Exception:
        return ''
    if used + extra > budget * GB:
        return 'Speicherbudget der Downloads erreicht (%.0f von %.0f GB): wartet, bis Platz frei wird' % (used / GB, budget)
    return ''


def _space_note(c, root, download_dir, extra):
    import youtube_abos
    try:
        note = youtube_abos.no_room(root, download_dir, extra=extra)
    except Exception:
        note = ''
    if note:
        return note.replace('Abo-Downloads warten', 'Serien-Downloads warten').replace('am Abo-Speicherort', 'am Downloadordner')
    return _budget_note(c, root, download_dir, extra)


def topup(c, root, download_dir, show_row, cfg, done, now):
    """Bis zur Grenze je Serie planen (nur lesen). Ergebnis: (Aufträge, Werte für series_autoload, Hinweis)."""
    import series_download
    show = show_row['show_key']
    try:
        result = series_download.plan(c, show, download_dir)
    except ValueError as exc:
        return [], {}, str(exc)
    tried = {r[0] for r in c.execute('SELECT work_id FROM series_autoload_items WHERE show_key=?', (show,))}
    after, before = [], []
    last = (show_row['last_season'], show_row['last_episode'])
    for item in result['eligible']:
        found = c.execute('SELECT work_id FROM offers WHERE id=?', (item['id'],)).fetchone()
        work_id = found[0] if found else ''
        if not work_id or work_id in tried or _seen(done, work_id, _offers(c, work_id)):
            continue
        m = item['metadata']
        pos = (m.get('season'), m.get('episode'))
        (after if last[0] is None or pos > (last[0], last[1] or 0) else before).append((work_id, item))
    unconfirmed = sum(1 for s in result['skipped'] if 'nicht bestätigt' in s['reason'] or 'ungeprüft' in s['reason'])
    counts = {'eligible': len(after) + len(before), 'unconfirmed': unconfirmed}
    count, size, _running, _finished = held(c, show, done)
    jobs, note = [], ''
    pending = pending_bytes(c)
    for work_id, item in after + list(reversed(before)):
        if len(jobs) >= PER_RUN:
            break
        if count >= cfg['max']:
            note = 'Grenze erreicht: %d ungesehene Folgen liegen bereit; weitere folgen, sobald welche gesehen sind' % cfg['max']
            break
        size_guess = estimate(item['metadata'], item['source'])
        if size + size_guess > cfg['gb'] * GB and count:
            note = 'Grenze erreicht: %d GB je Serie; weitere Folgen folgen, sobald welche gesehen sind' % cfg['gb']
            break
        room = _space_note(c, root, download_dir, pending + size_guess)
        if room:
            note = room
            break
        job_id = secrets.token_hex(8)
        source = _with_offer(c, work_id, item, now)
        j = {**item, 'source': source, 'id': job_id, 'state': 'queued', 'received': 0, 'total': 0,
             'autoload_show': show, 'autoload_title': show_row['title'] or item['metadata'].get('title') or '',
             'autoload_at': now}
        jobs.append((work_id, j, size_guess))
        count += 1
        size += size_guess
        pending += size_guess
    counts['eligible'] = max(0, counts['eligible'] - len(jobs))     # noch nicht eingereiht
    # 0.6.101 (Mac-Prüfung: nach S01E09 kam S01E20): Lücke sichtbar machen statt sie stumm zu überspringen
    if after and last[0] is not None:
        nxt = (after[0][1]['metadata'].get('season'), after[0][1]['metadata'].get('episode'))
        if nxt[0] == last[0] and nxt[1] != (last[1] or 0) + 1:
            gap = ('Nach S%02dE%02d geht es mit S%02dE%02d weiter: die Folgen dazwischen sind beim Sender nicht als Datei '
                   'verfügbar oder ihre Folgennummer ist noch unbestätigt' % (last[0], last[1] or 0, nxt[0], nxt[1]))
            note = gap + (' · ' + note if note else '')
    if not note and not jobs and not (after or before):
        note = ('Keine weiteren Folgen mit bestätigter Folgennummer verfügbar' if not unconfirmed else
                '%d Folgen warten noch auf die Folgenerkennung (Staffel/Folge unbestätigt)' % unconfirmed)
    return jobs, counts, note


def _store(c, show, jobs, counts, note, now):
    """Aufträge und Stand einer Serie in einer kurzen Schreibtransaktion ablegen."""
    queued = 0
    if c.in_transaction:
        c.commit()
    c.execute('BEGIN IMMEDIATE')
    try:
        row = c.execute('SELECT state FROM series_autoload WHERE show_key=?', (show,)).fetchone()
        if not row or row[0] != 'active':
            jobs = []                      # inzwischen beendet oder entfernt
        for work_id, j, size_guess in jobs:
            if c.execute('INSERT OR IGNORE INTO series_autoload_items VALUES(?,?,?,?,?)',
                         (show, work_id, j['id'], now, size_guess)).rowcount:
                c.execute('INSERT INTO jobs(id,payload,state) VALUES(?,?,?)', (j['id'], json.dumps(j), 'queued'))
                queued += 1
        if show.startswith('film:') and (queued or note.startswith(('Liegt schon', 'Kein direkter', 'Beim Sender', 'Film nicht'))):
            c.execute("UPDATE series_autoload SET state='done' WHERE show_key=?", (show,))
        c.execute('UPDATE series_autoload SET next_check=?,queued_total=queued_total+?,note=?,updated=?,'
                  'eligible=COALESCE(?,eligible),unconfirmed=COALESCE(?,unconfirmed) WHERE show_key=?',
                  (now + CHECK_EVERY, queued, note, now, counts.get('eligible'), counts.get('unconfirmed'), show))
        c.commit()
    except Exception:
        c.rollback()
        raise
    return queued


def run(root, c, settings, now=None):
    """Ein Durchlauf (im Hintergrund jede Minute und gleich nach „zu Ende gesehen“). Ergebnis für die Diagnose.

    ``c`` ohne offene Transaktion: gelesen wird außerhalb, geschrieben je Serie kurz (USB-Laufwerke, 0.6.42)."""
    now = time.time() if now is None else now
    cfg = config(settings)
    if not cfg['enabled']:
        return {'enabled': False}
    started = collect(root, c, now, cfg['films'])
    c.commit()
    due = c.execute("SELECT * FROM series_autoload WHERE state='active' AND next_check<=? ORDER BY next_check LIMIT 10",
                    (now,)).fetchall()
    if not due:
        return {'enabled': True, 'started': started, 'queued': 0}
    done = _watched_keys(root)
    total = 0
    for row in due:
        try:
            if row['kind'] == 'movie':
                jobs, note = film_plan(c, root, settings['download_dir'], row, done)
                counts = {}
            else:
                jobs, counts, note = topup(c, root, settings['download_dir'], row, cfg, done, now)
        except Exception as exc:          # eine Serie darf die anderen nicht aufhalten
            jobs, counts, note = [], {}, 'Prüfung fehlgeschlagen (%s); neuer Versuch später' % type(exc).__name__
        total += _store(c, row['show_key'], jobs, counts, note, now)
    return {'enabled': True, 'started': started, 'queued': total}


def _version_penalty(row):
    """0.6.101 (Mac-Prüfung 22.11.: bei „Loulou“ kam die Originalversion mit Untertitel, obwohl es die deutsche Fassung
    gibt): kleiner ist besser. Deutsche Regelfassung vor OmU/OV/Fremdsprache, vor Hörfassung, Gebärdensprache,
    Klarer/Leichter Sprache. Gelesen aus Titel und Sendereihe des Angebots (languages.from_title) und dem Sender."""
    import languages
    info = languages.from_title(row.get('title'), row.get('topic'))
    penalty = 0
    if info.get('original') or [a for a in info.get('audio') or [] if a != 'de']:
        penalty += 4
    if info.get('accessibility'):
        penalty += 2
    channel = str(row.get('channel') or '').upper()
    if channel.startswith('ARTE.') and channel != 'ARTE.DE':
        penalty += 4
    return penalty


def preferred_offer(c, work_id, now=None):
    """Beste ladbare Fassung eines Werks für das automatische Laden: (Angebots-ID, Quelle, Adresse) oder None."""
    import catalog
    import subscriptions
    now = time.time() if now is None else now
    best = None
    for o in c.execute('SELECT id,payload,rank FROM offers WHERE work_id=? AND active=1 ORDER BY rank DESC,seen DESC LIMIT 40',
                       (work_id,)).fetchall():
        try:
            row = json.loads(o['payload'])
        except ValueError:
            continue
        row.update(catalog.offer_expiry(c, o['id']))
        if subscriptions.expired(row, now):
            continue
        links = [x for x in catalog.links(row) if x.get('supported') and x.get('url')]
        if not links:
            continue
        key = (_version_penalty(row), -(links[0].get('score') or 0), -(o['rank'] or 0))
        if best is None or key < best[0]:
            best = (key, o['id'], row, links[0]['url'])
    return best[1:] if best else None


def _with_offer(c, work_id, item, now):
    """Quelle des Auftrags auf die bevorzugte Fassung umstellen (sonst die vom Katalog gewählte)."""
    found = preferred_offer(c, work_id, now)
    if not found:
        return {**item['source'], '_id': item['id'], '_download_url': (item.get('best') or {}).get('url') or item['source'].get('_download_url')}
    offer_id, row, url = found
    return {**row, '_id': offer_id, '_download_url': url}


def film_plan(c, root, download_dir, row, done):
    """0.6.94 (Björn: „auch Filme, die einmal zu Ende geschaut wurden … herunterladen, da die Chance groß ist, dass
    meine Tochter sie noch mal sehen möchte“): eine dauerhafte Offline-Kopie des Films. Wie beim Einzeldownload: erkannt
    (matched/manual), verfügbar, direkte Videodatei, noch nicht vorhanden. Ergebnis: (Aufträge, Hinweis)."""
    import catalog
    import core
    work_id = row['trigger_work']
    w = _work(c, work_id)
    if w is None or w['kind'] != 'movie':
        return [], 'Film nicht mehr im Katalog'
    item = catalog.item(c, c.execute('SELECT * FROM works WHERE id=?', (w['id'],)).fetchone())
    if not item:
        return [], 'Film nicht mehr im Katalog'
    if item.get('downloaded'):
        return [], 'Liegt schon offline vor'
    if w['state'] not in ('matched', 'manual'):
        return [], 'Film noch nicht sicher erkannt: wird nach der Erkennung geladen'
    if not item['available']:
        return [], 'Beim Sender nicht mehr verfügbar'
    if not item['best'] or not item['best']['supported']:
        return [], 'Kein direkter Download beim Sender (nur Stream)'
    if c.execute('SELECT 1 FROM series_autoload_items WHERE show_key=?', (row['show_key'],)).fetchone():
        return [], 'Eingereiht'
    meta = item['metadata']
    try:
        target = str(core.target(download_dir, meta, item['id']))
    except (ValueError, TypeError) as exc:
        return [], str(exc)
    if core.existing_for(download_dir, meta, item['id']) or c.execute(
            "SELECT 1 FROM jobs WHERE state IN ('queued','downloading','tagging','done') AND json_extract(payload,'$.target')=? LIMIT 1",
            (target,)).fetchone():
        return [], 'Liegt schon offline vor oder ist eingereiht'
    size_guess = estimate(meta, item['source'])
    room = _space_note(c, root, download_dir, pending_bytes(c) + size_guess)
    if room:
        return [], room.replace('Serien-Downloads', 'Film-Downloads')
    j = {'id': secrets.token_hex(8), 'source': _with_offer(c, w['id'], item, time.time()),
         'metadata': meta, 'root': str(download_dir), 'quality': 'best', 'target': target, 'state': 'queued',
         'received': 0, 'total': 0, 'autoload_show': row['show_key'], 'autoload_title': row['title'] or meta.get('title') or '',
         'autoload_kind': 'movie', 'autoload_at': time.time()}
    return [(w['id'], j, size_guess)], ''


# ----------------------------------------------------------------- Oberfläche
def change(c, show, action, now=None):
    """stop: Automatik für die Serie beenden und wartende Aufträge abbrechen (fertige Dateien bleiben);
    resume: wieder einschalten; forget: aus der Liste nehmen (eine neu gesehene Folge schaltet sie wieder ein)."""
    now = time.time() if now is None else now
    if action not in ('stop', 'resume', 'forget'):
        raise ValueError('Unbekannte Aktion')
    if not c.execute('SELECT 1 FROM series_autoload WHERE show_key=?', (show,)).fetchone():
        raise ValueError('Serie nicht gefunden')
    cancelled = 0
    if action in ('stop', 'forget'):
        for (job_id,) in c.execute('SELECT job_id FROM series_autoload_items WHERE show_key=?', (show,)).fetchall():
            cancelled += c.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state IN ('queued','downloading','tagging')",
                                   (job_id,)).rowcount
    if action == 'stop':
        c.execute("UPDATE series_autoload SET state='stopped',note='Von Hand beendet',updated=? WHERE show_key=?", (now, show))
    elif action == 'resume':
        c.execute("UPDATE series_autoload SET state='active',note='',next_check=0,updated=? WHERE show_key=?", (now, show))
    else:
        c.execute('DELETE FROM series_autoload WHERE show_key=?', (show,))
    return {'ok': True, 'cancelled': cancelled}


def status(root, c, settings):
    cfg = config(settings)
    done = _watched_keys(root)
    rows = []
    for r in c.execute('SELECT * FROM series_autoload ORDER BY state, last_watched DESC LIMIT 100').fetchall():
        count, size, running, finished = held(c, r['show_key'], done)
        states = dict(c.execute('''SELECT j.state,COUNT(*) FROM series_autoload_items i JOIN jobs j ON j.id=i.job_id
                                   WHERE i.show_key=? GROUP BY j.state''', (r['show_key'],)).fetchall())
        rows.append({'show': r['show_key'], 'title': r['title'] or 'Serie', 'state': r['state'], 'note': r['note'], 'kind': r['kind'],
                     'ready': finished, 'waiting': running, 'unseen': count, 'bytes': size,
                     'loaded': states.get('done', 0), 'failed': states.get('error', 0) + states.get('cancelled', 0),
                     'more': r['eligible'], 'unconfirmed': r['unconfirmed'], 'last_watched': r['last_watched'],
                     'last': ('S%02dE%02d' % (r['last_season'], r['last_episode'] or 0)) if r['last_season'] is not None else ''})
    return {'settings': cfg, 'series': rows}


def summary(root, c, settings):
    """Für die Diagnose: Zahlen ohne Titel, dazu ob das Signal „zu Ende gesehen“ ankommt."""
    import watch_state
    cfg = config(settings)
    out = {'enabled': cfg['enabled'], 'max': cfg['max'], 'gb': cfg['gb']}
    for state, n in c.execute('SELECT state,COUNT(*) FROM series_autoload GROUP BY state'):
        out['series_' + state] = n
    out['jobs'] = dict(c.execute('''SELECT j.state,COUNT(*) FROM series_autoload_items i JOIN jobs j ON j.id=i.job_id
                                    GROUP BY j.state''').fetchall())
    out['pending_gb'] = round(pending_bytes(c) / GB, 1)
    import catalog
    cursor = catalog.get_state(c, 'series_autoload_cursor', None)
    out['cursor_age_h'] = round((time.time() - cursor) / 3600, 1) if cursor else None
    try:
        recent = watch_state.finished_since(root, time.time() - 7 * 86400, limit=500)
    except Exception:
        recent = []
    kinds = {}
    for e in recent:
        name = e['key'].partition(':')[0] if ':' in e['key'] else 'werk'
        kinds[name] = kinds.get(name, 0) + 1
    out['finished_7d'] = kinds
    return out
