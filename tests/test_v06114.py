"""0.6.114: Mac-Prüfung 0.6.113 (23.11.2026, 77 min, IMDb-Klon).

- E3: catalog_sendung_suggestions_refiled kam nie – im Format-Thread hatte das IMDb-Archiv noch keinen Leser, _lookup
  warf AttributeError ('queries'), sendung_has_episodes las das als „Archiv nicht bereit“; nächster Versuch erst nach
  einer Stunde, still. Jetzt: Leser je Thread, Fehler im Protokoll, Wartegrund als Ereignis, neuer Versuch nach 2 min.
- Start: „database is locked“ in assign_formats startete den ganzen Worker neu – jetzt nur der Stapel später.
- E5: recognition_idle mit selectable 49 – ein Anspruch, der an einer belegten Datenbank scheiterte, galt als leere
  Warteschlange. Jetzt kein „waiting“ dafür, und das Ereignis nur, wenn die Auswahl im selben Lesestand nichts findet.
"""
import json
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
import imdb_archive  # noqa: E402
from tests.test_v0683 import Worker  # noqa: E402
from tests.test_v06113 import src, suggested, wid_of  # noqa: E402


class RefileWithRealArchive(Worker):
    def setUp(self):
        super().setUp()
        with self.db() as c:
            catalog.ingest(c, [src('Ausgabe %d' % i, 'Euromaxx', i) for i in range(3)] + [src('Folge %d' % i, 'Serie Hundert', 10 + i) for i in range(2)])
            for i in range(3):suggested(c, wid_of(c, i), 'Euromaxx', 'tt2620362', 'Ausgabe %d' % i)
            for i in range(2):suggested(c, wid_of(c, 10 + i), 'Serie Hundert', 'tt100', 'Folge %d' % i)

    def in_fresh_thread(self, fn):
        out = []
        t = threading.Thread(target=lambda: out.append(fn()));t.start();t.join()
        return out[0]

    def test_refile_from_a_thread_without_archive_reader(self):
        events = []
        with patch.object(imdb_archive, 'ACTIVE', self.archive), \
                patch.object(diagnostics, 'event', lambda name, *a, **f: events.append((name, f))):
            self.assertEqual(self.in_fresh_thread(self.svc.refile_suggested_sendungen), 3)
        with self.db() as c:
            states = {r['title']: r['state'] for r in c.execute('SELECT title,state FROM works')}
            done = catalog.get_state(c, 'sendung_refile_v06113')
        self.assertEqual(states['Euromaxx'], 'format')
        self.assertEqual(states['Serie Hundert'], 'identified')       # IMDb lists episodes: kept
        self.assertEqual((done['refiled'], done['kept']), (3, 1))
        self.assertTrue(any(n == 'catalog_sendung_suggestions_refiled' for n, _ in events))

    def test_series_has_episodes_in_a_new_thread(self):
        self.assertIs(self.in_fresh_thread(lambda: self.archive.series_has_episodes({'provider': 'IMDb Offline', 'reference_id': 'tt100'})), True)
        self.assertIs(self.in_fresh_thread(lambda: self.archive.series_has_episodes({'provider': 'IMDb Offline', 'reference_id': 'tt2620362'})), False)

    def test_waiting_is_reported_and_retried_soon(self):
        events = [];waits = []
        def sweep():
            self.svc.stop.set()
        with patch.object(imdb_archive, 'ACTIVE', None), patch.object(self.svc, 'unknown_sweep', sweep), \
                patch.object(self.svc.format_wake, 'wait', lambda t: waits.append(t)), \
                patch.object(diagnostics, 'event', lambda name, *a, **f: events.append((name, f))):
            self.svc.format_loop()
        self.assertEqual(waits, [catalog_service.REFILE_RETRY])
        self.assertEqual([f['reason'] for n, f in events if n == 'catalog_sendung_refile_waiting'], ['archive_missing'])

    def test_lookup_failure_is_logged_not_silent(self):
        broken = type('A', (), {'updated': 1, 'series_has_episodes': lambda self, m: (_ for _ in ()).throw(AttributeError('queries'))})()
        errors = []
        catalog._HAS_EPISODES_LOGGED = 0
        with patch.object(imdb_archive, 'ACTIVE', broken), patch.object(diagnostics, 'error', lambda name, exc, **f: errors.append(name)), \
                patch.object(diagnostics, 'event', lambda *a, **f: None):
            self.assertEqual(self.svc.refile_suggested_sendungen(), 'waiting')
        self.assertEqual(errors, ['sendung_has_episodes_failed'])


class FormatBusy(Worker):
    def test_busy_batch_is_postponed_not_fatal(self):
        calls = []
        real = catalog.assign_formats
        def flaky(c, limit=500):
            calls.append(1)
            if len(calls) == 1:raise sqlite3.OperationalError('database is locked')
            return real(c, limit)
        def sweep():
            self.svc.stop.set()
        with patch.object(catalog, 'assign_formats', flaky), patch.object(self.svc, 'unknown_sweep', sweep), \
                patch.object(self.svc, 'refile_suggested_sendungen', lambda: None), \
                patch.object(self.svc.stop, 'wait', lambda t: False), patch.object(self.svc.format_wake, 'wait', lambda t: True):
            self.svc.format_loop()
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(self.svc.sqlite_busy_count, 1)


class IdleHonest(Worker):
    def test_busy_claim_is_not_waiting(self):
        events = []
        self.svc.metadata_state(phase='result')
        with patch.object(self.svc, 'lease_work', lambda *a: catalog_service.LEASE_BUSY), \
                patch.object(diagnostics, 'event', lambda name, *a, **f: events.append(name)):
            self.assertFalse(self.svc.metadata_once())
        self.assertNotEqual(self.svc.metadata_status.get('phase'), 'waiting')
        self.assertNotIn('recognition_idle', events)

    def test_no_idle_event_while_the_selection_finds_work(self):
        with self.db() as c:
            catalog.ingest(c, [src('Clip', 'Irgendwas', 1, 2400)])
            c.execute("UPDATE works SET kind='unknown',state='retry',attempts=1,next_try=0")
        events = []
        with patch.object(diagnostics, 'event', lambda name, *a, **f: events.append((name, f))):
            self.assertIsNone(self.svc.report_idle())
        self.assertEqual(events, [])
        self.assertEqual(getattr(self.svc, 'idle_reported_at', 0), 0)


class ProgrammeExtra(Worker):
    def test_clip_of_a_film_is_its_extra_news_clip_joins_its_sendung(self):
        with self.db() as c:
            catalog.ingest(c, [src('Es geht um Luis', 'Es geht um Luis', 1, 5400, 'ARD'),
                               src('Extra: Interview mit Lucia Chiarla', 'Es geht um Luis', 2, 300, 'ARD'),
                               src('Wetter am Abend', 'Hessenschau', 3, 120, 'HR'), src('Hessenschau vom 1.12.', 'Hessenschau', 4, 1800, 'HR')])
            film, extra, news, edition = (wid_of(c, n) for n in (1, 2, 3, 4))
            c.execute("UPDATE works SET kind='movie',state='matched',meta=json_set(meta,'$.provider','TMDB') WHERE id=?", (film,))
            c.execute("UPDATE works SET kind='series',state='matched',meta=json_set(meta,'$.provider','TMDB') WHERE id=?", (edition,))
            c.execute("UPDATE works SET kind='other',state='pending',attempts=0 WHERE id IN (?,?)", (extra, news))
            catalog.set_state(c, 'format_rev', 5)
            while catalog.assign_formats(c)[0]:pass
            r = c.execute('SELECT kind,state,meta FROM works WHERE id=?', (extra,)).fetchone()
            self.assertEqual((r['kind'], r['state']), ('other', 'format'))
            self.assertEqual(json.loads(r['meta'])['related_series_title'], 'Es geht um Luis')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE kind='series' AND title='Es geht um Luis'").fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT kind,state FROM works WHERE id=?', (news,)).fetchone()[:], ('series', 'format'))


if __name__ == '__main__':
    unittest.main()
