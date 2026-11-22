"""0.6.106: Reihennamen, wie Kinder sie kennen (Mac-Abfrage Kinderreihen 22.11.2026, Bestand 0.6.99).

- TMDB nennt die Reihe „KIKA LIVE“, KiKA „KiKA LIVE“: angezeigt wird die Schreibweise des Senders.
- KiKA-Ableger („KiKA LIVE fordert heraus“, „KiKA LIVE #ZuHauseUmDieWelt“ …) liefen als 11 eigene Mini-Reihen neben der
  Hauptreihe (641 Werke); sie gehören unter die Hauptreihe, der Ableger bleibt im Folgentitel.
- BR/ARD-Kinderreihen ohne Kindersender und ohne Genre „Kinder“ („Anna, Nina, Pia und die wilden Tiere“, „Checker Can,
  Checker Tobi und Checker Julian“) zählen über ihren Namen als Kinderprogramm.
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402
from test_v0649_unknown_rest import offer  # noqa: E402


class RuleTests(unittest.TestCase):
    def test_broadcaster_spelling(self):
        self.assertEqual(catalog.broadcaster_spelling('KIKA LIVE', 'KiKA LIVE'), 'KiKA LIVE')
        self.assertIsNone(catalog.broadcaster_spelling('KiKA LIVE', 'KiKA LIVE'))
        self.assertIsNone(catalog.broadcaster_spelling('KIKA LIVE', 'KiKA LIVE fordert heraus'))
        self.assertIsNone(catalog.broadcaster_spelling('Tatort', ''))

    def test_kids_names(self):
        for t in ('Anna, Nina, Pia und die wilden Tiere', 'Paula, Anna und die wilden Tiere', 'Anna und die wilden Tiere',
                  'Anna, Paula, Pia und die wilden Tiere / wilde Natur', 'Checker Can, Checker Tobi und Checker Julian',
                  'Checker Tobi'):
            self.assertTrue(catalog.KIDS_TOPIC.search(t), t)
        for t in ('Der Doktor und die wilden Tiere', 'Faktenchecker', 'Erlebnisreisen', 'Tatort'):
            self.assertFalse(catalog.KIDS_TOPIC.search(t), t)


class HealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Folge %d' % i, 'KiKA LIVE', channel='KiKA', n=i) for i in range(25)]
        rows += [offer('Becher Pong', 'KiKA LIVE fordert heraus', channel='KiKA', n=100),
                 offer('Reise 1', 'KiKA LIVE #ZuHauseUmDieWelt', channel='KiKA', n=101),
                 offer('Usedom 1', 'Tatort Usedom', channel='ARD', n=102)]
        for i in range(25):
            rows.append(offer('Fall %d' % i, 'Tatort', channel='ARD', n=200 + i))
        with self.db() as c:
            catalog.initialize(c);catalog.ingest(c, rows)
            self.ids = {}
            for w, m in c.execute('SELECT id,meta FROM works'):
                m = json.loads(m);self.ids[m.get('episode_title') or m['title']] = w
            for i in range(25):
                wid = self.ids['Folge %d' % i]
                m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
                m.update(kind='series', title='KIKA LIVE', provider='TMDB', reference_id='90485', year=2005, episode_title='Folge %d' % i)
                c.execute("UPDATE works SET kind='series',title='KIKA LIVE',show_key=?,meta=?,state='identified',topic='KiKA LIVE' WHERE id=?",
                          (catalog.showkey(m), json.dumps(m), wid))
                tid = self.ids['Fall %d' % i]
                c.execute("UPDATE works SET kind='series',title='Tatort',show_key='tatort',state='identified',topic='Tatort' WHERE id=?", (tid,))
            # the spin-offs as 0.6.105 filed them (own Sendung)
            for title, topic, ch in (('Becher Pong', 'KiKA LIVE fordert heraus', 'KiKA'), ('Reise 1', 'KiKA LIVE #ZuHauseUmDieWelt', 'KiKA'),
                                     ('Usedom 1', 'Tatort Usedom', 'ARD')):
                wid = self.ids[title]
                row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
                m = json.loads(row['meta'])
                m.update(kind='series', title=topic, episode_title=title, provider='Sendung')
                c.execute("UPDATE works SET kind='series',title=?,show_key=?,meta=?,state='format',topic=? WHERE id=?",
                          (topic, catalog.showkey(m), json.dumps(m), topic, wid))
            self.main = c.execute("SELECT show_key FROM works WHERE id=?", (self.ids['Folge 0'],)).fetchone()[0]
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def row(self, wid):
        with self.db() as c:
            r = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            return dict(r, meta=json.loads(r['meta']))

    def test_heal_once(self):
        self.svc.heal_series_names()
        main = self.row(self.ids['Folge 3'])
        self.assertEqual((main['title'], main['meta']['title'], main['show_key']), ('KiKA LIVE', 'KiKA LIVE', self.main))
        pong = self.row(self.ids['Becher Pong'])
        self.assertEqual((pong['title'], pong['show_key']), ('KiKA LIVE', self.main))
        self.assertEqual(pong['meta']['episode_title'], 'KiKA LIVE fordert heraus: Becher Pong')
        self.assertEqual(pong['meta']['sendung_name'], 'KiKA LIVE fordert heraus')
        self.assertEqual(self.row(self.ids['Reise 1'])['show_key'], self.main)
        usedom = self.row(self.ids['Usedom 1'])             # not a kids channel: stays its own Sendung
        self.assertEqual(usedom['title'], 'Tatort Usedom')
        self.assertNotEqual(usedom['show_key'], 'tatort')
        with self.db() as c:
            state = catalog.get_state(c, 'series_names_v06106')
            self.assertEqual((state['spelled'], state['moved']), (25, 2))
            c.execute("UPDATE works SET title='KIKA LIVE' WHERE id=?", (self.ids['Folge 1'],))
        self.svc.heal_series_names()                          # once
        self.assertEqual(self.row(self.ids['Folge 1'])['title'], 'KIKA LIVE')

    def test_new_filing_goes_under_main_reihe(self):
        self.svc.heal_series_names()
        with self.db() as c:
            catalog.ingest(c, [offer('Minipferde', 'KiKA LIVE Minipferde-Challenge', channel='KiKA', n=300)])
            wid = next(w for w, m in c.execute('SELECT id,meta FROM works') if json.loads(m).get('episode_title') == 'Minipferde'
                       or json.loads(m).get('title') == 'Minipferde')
            row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            src = offer('Minipferde', 'KiKA LIVE Minipferde-Challenge', channel='KiKA', n=300)
            m = catalog.file_under_sendung(c, row, json.loads(row['meta']), src, 'KiKA LIVE Minipferde-Challenge')
        r = self.row(wid)
        self.assertEqual((r['title'], r['show_key'], m['episode_title']), ('KiKA LIVE', self.main, 'KiKA LIVE Minipferde-Challenge: Minipferde'))

    def test_identification_takes_broadcaster_spelling(self):
        with self.db() as c:
            wid = self.ids['Folge 5']
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
            m['title'] = 'KIKA LIVE'
            catalog.save_metadata(c, wid, m, 'identified')
            self.assertEqual(c.execute('SELECT title FROM works WHERE id=?', (wid,)).fetchone()[0], 'KiKA LIVE')


if __name__ == '__main__':
    unittest.main()
