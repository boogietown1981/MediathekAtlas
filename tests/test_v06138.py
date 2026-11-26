"""0.6.138 (Mac-Prüfung 0.6.136, BEFUND-06136.txt): More than Honey blieb „prüfen“, weil IMDb-Offline-Filmkandidaten
keine IMDb-Laufzeit trugen; „DER TAG in Berlin & Brandenburg“ blieb Kultur, hessenschau ohne Genre."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import broadcaster  # noqa: E402
import catalog  # noqa: E402
import imdb_archive  # noqa: E402
import matching  # noqa: E402
import metadata  # noqa: E402


def archive(tmp):
    a = imdb_archive.Archive(Path(tmp), threading.Event())
    with sqlite3.connect(a.path) as c:
        c.executescript("""CREATE TABLE names(name TEXT,tconst TEXT);
CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,startYear INTEGER,runtimeMinutes INTEGER,genres TEXT);
CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);
CREATE TABLE title_episode(tconst TEXT,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER);""")
        c.execute('INSERT INTO names VALUES(?,?)', (imdb_archive.norm('More than Honey'), 'tt2113681'))
        c.execute("INSERT INTO title_basics VALUES('tt2113681','movie',2012,95,'Documentary')")
    a.updated = 1;a.version = 0
    return a


def close(a):
    cached = getattr(a._reader_local, 'opened', None)
    if cached:cached[1].close()


class MoreThanHoney(unittest.TestCase):
    ROW = {'title': 'More than Honey - Dokumentarfilm, Schweiz 2010', 'topic': 'Dokumentarfilm', 'channel': '3Sat',
           'duration': 5306}

    def test_imdb_candidate_carries_runtime_and_two_year_rule_accepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = archive(tmp)
            try:
                with patch.object(imdb_archive, 'ACTIVE', a):
                    found = a.candidates(self.ROW, {'kind': 'movie', 'title': 'More than Honey', 'year': 2010})
                    self.assertEqual(a.movie_runtime('tt2113681'), 5700)
            finally:close(a)
        film = [x for x in found if x['reference_id'] == 'tt2113681'][0]
        self.assertEqual(film['imdb_runtime_seconds'], 5700)
        self.assertNotIn('reference_runtime_seconds', film)   # bleibt Serienangabe (Kurzformat-Prüfung)
        self.assertTrue(film['runtime_agrees'])
        meta = {'kind': 'movie', 'title': 'More than Honey', 'year': 2010}
        self.assertEqual(matching.issues(meta, dict(film, source_duration_seconds=5306)), [])
        # Black Box bleibt abgelehnt: 115 min gegen 100 min
        self.assertTrue(matching.issues(meta, dict(film, imdb_runtime_seconds=6000, source_duration_seconds=6900)))

    def test_stored_suggestion_without_runtime_is_matched_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = sqlite3.connect(Path(tmp) / 'catalog.db');c.row_factory = sqlite3.Row
            catalog.initialize(c)
            catalog.ingest(c, [dict(self.ROW, description='Dokumentarfilm über das Bienensterben.',
                                    url_video='https://example.org/honey.mp4')])
            wid = c.execute('SELECT id FROM works').fetchone()[0]
            old = {'kind': 'movie', 'title': 'More than Honey', 'year': 2012, 'provider': 'IMDb Offline',
                   'reference_id': 'tt2113681', 'similarity': 1.0, 'runtime_agrees': True, 'runtime_mismatch': False,
                   'year_mismatch': True, 'confidence': 'high'}   # wie 0.6.136 gespeichert: ohne IMDb-Laufzeit
            m = json.loads(c.execute('SELECT meta FROM works').fetchone()[0])
            m.update(kind='movie', year=2010, suggestions=[old])
            c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(m), wid))
            self.assertEqual(catalog.rematch_movie_suggestions(c)[0], 0)   # ohne Archiv: bleibt prüfen
            a = archive(tmp + '/imdb')
            try:
                with patch.object(imdb_archive, 'ACTIVE', a):
                    self.assertEqual(catalog.rematch_movie_suggestions(c)[0], 1)
            finally:close(a)
            row = c.execute('SELECT state,meta FROM works').fetchone()
            self.assertEqual(row['state'], 'matched')
            self.assertEqual(json.loads(row['meta'])['reason'], catalog.YEAR_TWO_REASON)
            c.close()


class NewsNames(unittest.TestCase):
    def test_regional_news_name_is_nachrichten_not_kultur(self):
        out = broadcaster.genres('DER TAG in Berlin & Brandenburg', 'Politik, Wirtschaft, Kultur und Sport aus der Region',
                                 names=('DER TAG in Berlin & Brandenburg',))
        self.assertEqual(out[0], 'Nachrichten');self.assertNotIn('Kultur', out)
        self.assertEqual(broadcaster.genres('hessenschau', 'Die Nachrichten aus Hessen', names=('hessenschau',))[0], 'Nachrichten')
        # unverändert: BR24 Zeitreise, Kulturmagazine, Sport
        self.assertNotIn('Nachrichten', broadcaster.genres('#BR24 Zeitreise', 'Geschichte', names=('#BR24 Zeitreise',)))
        self.assertIn('Kultur', broadcaster.genres('ttt', 'Kultur am Sonntag', names=('titel thesen temperamente',)))
        self.assertEqual(broadcaster.genres('Sport-Clip', 'aktuell', names=('Sport-Clip',))[0], 'Sport')

    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)

    def add(self, title, topic, genres, n):
        catalog.ingest(self.c, [{'title': title, 'topic': topic, 'channel': 'rbb', 'duration': 1800,
                                 'description': 'Beitrag', 'url_video': 'https://example.org/%d.mp4' % n}])
        w = self.c.execute('SELECT id,meta FROM works WHERE title=?', (title,)).fetchone()
        m = json.loads(w['meta']);m.update(kind='series', title=topic, genres=genres)
        m['genre_source'] = 'Sender (abgeleitet)' if genres else 'Unbekannt'
        self.c.execute("UPDATE works SET kind='series',title=?,show_key=?,meta=?,state='identified' WHERE id=?",
                       (topic, catalog.showkey(m), json.dumps(m), w['id']))
        self.c.execute('DELETE FROM work_genres WHERE work_id=?', (w['id'],))
        for g in genres:self.c.execute('INSERT INTO work_genres VALUES(?,?)', (w['id'], g))
        return w['id']

    def genres(self, wid):
        return [r[0] for r in self.c.execute('SELECT genre FROM work_genres WHERE work_id=? ORDER BY genre', (wid,))]

    def test_heal_and_backfill(self):
        tag = self.add('Ausgabe 1', 'DER TAG in Berlin & Brandenburg', ['Kultur'], 1)
        ttt = self.add('Ausgabe 2', 'titel thesen temperamente', ['Kultur'], 2)
        hessen = self.add('Ausgabe 3', 'hessenschau', [], 3)
        changed, _, _ = catalog.heal_derived_genres(self.c)
        self.assertEqual(changed, 1)
        self.assertEqual(self.genres(tag), ['Nachrichten']);self.assertEqual(self.genres(ttt), ['Kultur'])
        n, _, _ = catalog.backfill_genres(self.c)
        self.assertEqual(n, 1);self.assertEqual(self.genres(hessen), ['Nachrichten'])
        self.assertEqual(catalog.heal_derived_genres(self.c)[0], 0)   # zweiter Lauf ändert nichts


if __name__ == '__main__':
    unittest.main()
