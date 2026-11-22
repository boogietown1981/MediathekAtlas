"""0.6.97: Mac-Prüfung 0.6.88 nicht bestanden (Sendungsvorschläge: 74 von 1.223 falsch) und Runde 6 (Filme 3sat/ARD).

- Wikidata-Q-Nummern einzelner Folgen fremder Serien, IMDb-Namensvettern ohne Jahr, Thema nur „3sat“ → nie
  automatisch; die schon so eingeordneten Werke (Björns Bestand seit 0.6.91) werden wieder offen.
- 3sat-Titel „Der Schut - Spielfilm, BRD/Frankreich/Italien 1964“: ohne Zusatz suchen, Jahr übernehmen.
- Filmjahr ein Jahr versetzt (Produktion/Erscheinen) mit passender Laufzeit ist derselbe Film („Im Zweifel“ 2015/2016).
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import matching  # noqa: E402
import metadata  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402
from test_v0649_unknown_rest import offer, series  # noqa: E402


def src(topic='Wahrheit oder Pflicht', channel='KiKA'):
    return {'duration': 1500, 'timestamp': 1795100000, 'title': 'Folge', 'topic': topic, 'channel': channel}


class RuleTests(unittest.TestCase):
    def test_wikidata_no_year_and_sender_topic_never_decide(self):
        wd = {'provider': 'Wikidata', 'kind': 'series', 'title': 'Wahrheit oder Pflicht', 'similarity': 1.0,
              'reference_id': 'Q50386201', 'year': 2009, 'confidence': 'high'}
        self.assertIsNone(catalog.sendung_suggestion({'suggestions': [wd]}, src(), 'Wahrheit oder Pflicht'))
        self.assertIsNone(catalog.sendung_suggestion({'suggestions': [series('Headhunter', ref='tt24510162', year=None)]},
                                                     src('Headhunter', 'SRF'), 'Headhunter'))
        self.assertIsNone(catalog.sendung_suggestion({'suggestions': [series('Entführt', ref='tt3625998', year=2014)]},
                                                     src('3sat', '3Sat'), 'Entführt'))
        good = series('Sportpanorama', ref='tt10366472', year=1977)
        self.assertEqual(catalog.sendung_suggestion({'suggestions': [good, dict(wd, title='Sportpanorama')]}, src('Sportpanorama', 'SRF'),
                                                    'Sportpanorama')['reference_id'], 'tt10366472')

    def test_film_title_suffix_of_3sat(self):
        self.assertEqual(metadata.query_title('Der Schut - Spielfilm, BRD/Frankreich/Italien 1964'), 'Der Schut')
        self.assertEqual(metadata.film_suffix_year('Helge Schneider - The Klimperclown - Dokumentarfilm von Helge Schneider, Deutschland 2025'), 2025)
        self.assertEqual(metadata.query_title('Danowski - Blutapfel - Fernsehfilm, Deutschland 2019'), 'Danowski - Blutapfel')
        self.assertIsNone(metadata.film_suffix_year('8 Mile'))
        self.assertEqual(metadata.query_title('8 Mile - Spielfilm, USA 2002'), '8 Mile')
        self.assertEqual(metadata.film_suffix_year('8 Mile - Spielfilm, USA 2002'), 2002)

    def test_8_mile_end_to_end_against_local_imdb(self):
        # Björns Bestand 22.11.: 3sat „8 Mile - Spielfilm, USA 2002“, 105,9 min, kein Jahr, 8 Versuche ohne Vorschlag.
        # IMDb-Archiv: tt0298203 „8 Mile“ 2002, 110 min.
        import sqlite3
        from unittest.mock import patch
        import imdb_archive
        with tempfile.TemporaryDirectory() as tmp:
            a = imdb_archive.Archive(Path(tmp), threading.Event())
            with sqlite3.connect(a.path) as c:
                c.executescript("""CREATE TABLE names(name TEXT,tconst TEXT);
CREATE TABLE title_basics(tconst TEXT PRIMARY KEY,titleType TEXT,startYear INTEGER,runtimeMinutes INTEGER,genres TEXT);
CREATE TABLE title_ratings(tconst TEXT PRIMARY KEY,averageRating REAL,numVotes INTEGER);
CREATE TABLE title_episode(tconst TEXT,parentTconst TEXT,seasonNumber INTEGER,episodeNumber INTEGER);""")
                c.execute('INSERT INTO names VALUES(?,?)', (imdb_archive.norm('8 Mile'), 'tt0298203'))
                c.execute("INSERT INTO title_basics VALUES('tt0298203','movie',2002,110,'Drama,Music')")
            a.updated = 1;a.version = 0
            row = {'title': '8 Mile - Spielfilm, USA 2002', 'topic': 'Spielfilm', 'channel': '3Sat', 'duration': 6354}
            meta = {'kind': 'movie', 'title': '8 Mile - Spielfilm, USA 2002'}
            try:
                with patch.object(imdb_archive, 'ACTIVE', a):
                    result = metadata.candidates(row, meta, {})
            finally:
                cached = getattr(a._reader_local, 'opened', None)
                if cached:cached[1].close()
        film = [x for x in result['candidates'] if x.get('reference_id') == 'tt0298203']
        self.assertEqual(len(film), 1)
        self.assertEqual((film[0]['title'], film[0]['year']), ('8 Mile', 2002))
        self.assertTrue(film[0]['runtime_agrees'])
        self.assertEqual(film[0]['plausibility_issues'], [])
        self.assertTrue(matching.verified({'kind': 'movie', 'title': '8 Mile', 'year': 2002}, film[0]))

    def test_one_year_apart_with_agreeing_runtime(self):
        c = {'kind': 'movie', 'year': 2016, 'similarity': 1.0, 'runtime_agrees': True, 'year_mismatch': True}
        self.assertEqual(matching.issues({'kind': 'movie', 'year': 2015}, c), [])
        self.assertTrue(matching.issues({'kind': 'movie', 'year': 2015}, dict(c, runtime_agrees=False)))
        self.assertTrue(matching.issues({'kind': 'movie', 'year': 2014}, c))


class HealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Mutprobe', 'Wahrheit oder Pflicht', channel='KiKA', n=1), offer('Sieg', 'Sportpanorama', n=2),
                offer('Im Zweifel', 'Filme in der ARD', channel='ARD', n=3, duration=5189),
                offer('Der Schut - Spielfilm, BRD/Frankreich/Italien 1964', 'Spielfilm', channel='3Sat', n=4, duration=6645),
                offer('8 Mile - Spielfilm, USA 2002', 'Spielfilm', channel='3Sat', n=5, duration=6354)]
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            ids = {json.loads(m)['title']: w for w, m in c.execute('SELECT id,meta FROM works')}
            self.ids = ids
            wrong = {'kind': 'series', 'title': 'Wahrheit oder Pflicht', 'provider': 'Wikidata', 'reference_id': 'Q50386201', 'year': 2009,
                     'episode_title': 'Mutprobe', 'episode_verified': False, 'sendung_suggestion_v0688': True,
                     'unknown_before': {'kind': 'unknown', 'title': 'Mutprobe', 'state': 'review', 'rev': 7,
                                        'suggestions': [{'provider': 'Wikidata', 'kind': 'series', 'title': 'Wahrheit oder Pflicht'}]}}
            right = dict(wrong, title='Sportpanorama', provider='IMDb Offline', reference_id='tt10366472', year=1977, episode_title='Sieg',
                         unknown_before={'kind': 'unknown', 'title': 'Sieg', 'rev': 7})
            catalog.save_metadata(c, ids['Mutprobe'], wrong, 'identified')
            catalog.save_metadata(c, ids['Sieg'], right, 'identified')
            film = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (ids['Im Zweifel'],)).fetchone()[0])
            film.update(kind='movie', year=2015, suggestions=[{'provider': 'IMDb Offline', 'kind': 'movie', 'title': 'Im Zweifel', 'year': 2016,
                        'reference_id': 'tt5420522', 'similarity': 1.0, 'confidence': 'high', 'year_mismatch': True,
                        'runtime_agrees': True, 'runtime_mismatch': False}])
            c.execute("UPDATE works SET kind='movie',state='review',meta=? WHERE id=?", (json.dumps(film), ids['Im Zweifel']))
            c.execute("UPDATE works SET kind='movie',state='review',next_try=? WHERE id=?", (time.time() + 9e6, ids['Der Schut - Spielfilm, BRD/Frankreich/Italien 1964']))
            # 8 Mile: 8 Versuche, nächster erst am 20.12. – die einmalige Anwendung holt ihn trotzdem vor.
            c.execute("UPDATE works SET kind='movie',state='review',attempts=8,next_try=? WHERE id=?", (time.time() + 28 * 86400, ids['8 Mile - Spielfilm, USA 2002']))
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def row(self, wid):
        with self.db() as c:
            r = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            return dict(r, meta=json.loads(r['meta'])) if r else None

    def test_wrong_filings_reopen_right_ones_stay(self):
        self.svc.heal_sendung_suggestions()
        wrong = self.row(self.ids['Mutprobe'])
        self.assertEqual((wrong['kind'], wrong['state'], wrong['title']), ('unknown', 'review', 'Mutprobe'))
        self.assertTrue(wrong['meta']['sendung_suggestion_undone_v0697'])
        self.assertNotIn('sendung_suggestion_v0688', wrong['meta'])
        right = self.row(self.ids['Sieg'])
        self.assertEqual((right['state'], right['meta']['reference_id']), ('identified', 'tt10366472'))
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'sendung_suggestion_fix_v0697')['works'], 1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue WHERE work_id=?', (self.ids['Mutprobe'],)).fetchone()[0], 0)

    def test_film_rules_once(self):
        self.svc.film_heals()
        with self.db() as c:
            matched = c.execute("SELECT COUNT(*) FROM works WHERE state='matched' AND json_extract(meta,'$.reference_id')='tt5420522'").fetchone()[0]
            schut = c.execute('SELECT next_try FROM works WHERE id=?', (self.ids['Der Schut - Spielfilm, BRD/Frankreich/Italien 1964'],)).fetchone()[0]
            mile = c.execute('SELECT next_try FROM works WHERE id=?', (self.ids['8 Mile - Spielfilm, USA 2002'],)).fetchone()[0]
            state = catalog.get_state(c, 'film_rules_v0697')
        self.assertEqual(matched, 1)
        self.assertLess(schut, time.time() + 7300)
        self.assertLess(mile, time.time() + 7300)
        self.assertEqual((state['suffix_requeued'], state['year_matched']), (2, 1))
        self.svc.film_heals()  # einmalig
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'film_rules_v0697')['suffix_requeued'], 2)


if __name__ == '__main__':
    unittest.main()
