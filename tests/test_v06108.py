"""0.6.108: Mac-Prüfung der Erkennung 0.6.97 (an 0.6.98/0.6.105, 23.11.2026) teilweise bestanden.

- B3/B4: 730 3sat-Filme mit Titelzusatz eingereiht, keiner erkannt – der Arbeiter wählt nie Zustand 'review'
  (CatalogService.pick/choose), 0.6.97 setzte nur next_try. Jetzt: erster Durchgang (pending, 0 Versuche) mit dem
  ältesten next_try, vor ~5.000 anderen neuen Werken. 8 Mile über den ganzen Weg (Heilung → Arbeiter → IMDb-Archiv).
- B5: „Jahr ±1“ machte aus SRF-Clips „Sport“ (9 min) und „Moda“ (10 min) TMDB-Filme – nur noch ab 40 min; Heilung.
- B2: Sendungen ohne IMDb-Folgen waren im Protokoll nicht sichtbar – Regelstand 8 und Ereignis.
"""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import imdb_archive
import matching


def archive(root):
    a = imdb_archive.Archive(Path(root), threading.Event())
    with sqlite3.connect(a.path) as c:
        c.executescript("""CREATE TABLE names(name TEXT,tconst TEXT);
CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,startYear INTEGER,runtimeMinutes INTEGER,genres TEXT);
CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);
CREATE TABLE title_episode(tconst TEXT,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER);""")
        c.execute('INSERT INTO names VALUES(?,?)', (imdb_archive.norm('8 Mile'), 'tt0298203'))
        c.execute("INSERT INTO title_basics VALUES('tt0298203','movie',2002,110,'Drama,Music')")
    a.updated = 1;a.version = 0
    return a


def src(title, topic, channel, duration, n):
    return {'title': title, 'topic': topic, 'channel': channel, 'duration': duration, 'timestamp': 1795100000,
            'url_video': 'https://example.org/%d.mp4' % n}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.path = self.root / 'catalog.db'
        self.archive = archive(self.root)
        self.addCleanup(self.close_archive)
        self.settings = lambda: {'auto_metadata': True, 'metadata_workers': 1, 'sender_direct_lookup': False,
                                 'scan_priority': 'balanced', 'complete_series': False}
        with self.db() as c:
            c.executescript(catalog.SCHEMA)
            c.execute('CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
        self.svc = catalog_service.Service(self.db, self.settings, threading.Event(), self.root)

    def close_archive(self):
        opened = getattr(self.archive._reader_local, 'opened', None)
        if opened:opened[1].close()

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5);c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def work(self, url_n, c=None):
        if c is not None:
            return c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.url_video')=?",
                             ('https://example.org/%d.mp4' % url_n,)).fetchone()
        with self.db() as c:
            return c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.url_video')=?",
                             ('https://example.org/%d.mp4' % url_n,)).fetchone()


class FilmRuleWorkerTests(Base):
    def test_8_mile_through_the_worker_before_the_backlog(self):
        rows = [src('8 Mile - Spielfilm, USA 2002', 'Spielfilm', '3Sat', 6354, 1)]
        rows += [src('Neuer Film %d' % i, 'Filme', 'ARD', 5400, 100 + i) for i in range(5)]   # Rückstau neuer Werke
        with self.db() as c:
            catalog.ingest(c, rows)
            mile = self.work(1, c)['id']
            # Björns Bestand: „prüfen“, 8 Versuche, nächster Versuch erst am 20.12.
            c.execute("UPDATE works SET kind='movie',state='review',attempts=8,next_try=? WHERE id=?", (time.time() + 28 * 86400, mile))
            c.execute("UPDATE works SET kind='movie',state='pending',attempts=0,next_try=0 WHERE id!=?", (mile,))
        self.svc.film_heals()
        seen = []
        real = catalog_service.core.candidates
        def spy(row, meta, settings):
            seen.append(row['title']);return real(row, meta, settings)
        with patch.object(imdb_archive, 'ACTIVE', self.archive), patch.object(catalog_service.core, 'candidates', side_effect=spy):
            self.assertTrue(self.svc.metadata_once('identity'))
        self.assertEqual(seen, ['8 Mile - Spielfilm, USA 2002'])
        with self.db() as c:
            r = c.execute("SELECT * FROM works WHERE json_extract(meta,'$.reference_id')='tt0298203'").fetchone()
            self.assertIsNotNone(r)
            m = json.loads(r['meta'])
        self.assertEqual((r['state'], m['title'], m['year']), ('matched', '8 Mile', 2002))
        with self.db() as c:
            st = catalog.get_state(c, 'film_rules_v06108')
        self.assertEqual(st['suffix_requeued'], 1)


class YearCloseTests(Base):
    def test_only_feature_length(self):
        c = {'kind': 'movie', 'year': 1999, 'similarity': 1.0, 'runtime_agrees': True, 'year_mismatch': True}
        self.assertTrue(matching.issues({'kind': 'movie', 'year': 1998}, dict(c, source_duration_seconds=540)))
        self.assertTrue(matching.issues({'kind': 'movie', 'year': 1998}, c))                       # Laufzeit unbekannt
        self.assertEqual(matching.issues({'kind': 'movie', 'year': 1998}, dict(c, source_duration_seconds=5400)), [])

    def test_sport_and_moda_are_undone(self):
        with self.db() as c:
            catalog.ingest(c, [src('Sport', 'Dai, domanda!', 'SRF', 540, 1), src('Moda', 'Dai, domanda!', 'SRF', 600, 2),
                               src('Im Zweifel', 'Filme', 'ARD', 5189, 3)])
            for n, title, ref, year in ((1, 'Sport', '1519627', 1999), (2, 'Moda', '508514', 1996), (3, 'Im Zweifel', 'tt5420522', 2016)):
                w = self.work(n, c)
                m = {'kind': 'movie', 'title': title, 'year': year, 'provider': 'TMDB', 'reference_id': ref, 'state': 'auto_matched',
                     'reason': catalog.YEAR_CLOSE_REASON}
                c.execute("UPDATE works SET kind='movie',state='matched',meta=? WHERE id=?", (json.dumps(m), w['id']))
        self.svc.film_heals()
        for n in (1, 2):
            w = self.work(n);m = json.loads(w['meta'])
            self.assertEqual((w['state'], m.get('reference_id')), ('pending', None))
            self.assertTrue(m['year_close_undone_v06108'])
        self.assertEqual(self.work(3)['state'], 'matched')
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'film_rules_v06108')['clips_undone'], 2)

    def test_rematch_needs_length_from_the_offer(self):
        with self.db() as c:
            catalog.ingest(c, [src('Sport', 'Dai, domanda!', 'SRF', 540, 1), src('Im Zweifel', 'Filme', 'ARD', 5189, 2)])
            for n, title, year in ((1, 'Sport', 1998), (2, 'Im Zweifel', 2015)):
                w = self.work(n, c);m = json.loads(w['meta'])
                m.update(kind='movie', year=year, suggestions=[{'provider': 'TMDB', 'kind': 'movie', 'title': title, 'year': year + 1,
                         'reference_id': 'r%d' % n, 'similarity': 1.0, 'confidence': 'high', 'year_mismatch': True,
                         'runtime_agrees': True, 'runtime_mismatch': False}])
                c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(m), w['id']))
            done, _ = catalog.rematch_movie_suggestions(c)
        self.assertEqual(done, 1)
        self.assertEqual(self.work(1)['state'], 'review')


class ObservableTests(unittest.TestCase):
    def test_rules_revision_raised(self):
        self.assertGreaterEqual(catalog.UNKNOWN_RULES_REV, 8)

    def test_event_in_episode_path(self):
        import inspect
        self.assertIn("episode_sendung_without_episodes", inspect.getsource(catalog_service))


if __name__ == '__main__':
    unittest.main()
