"""0.6.117 (Vorbereitung auf 0.6.116): „Dein Song 2023/2024/2025“ erschienen als drei Kacheln. Jahrgänge einer Sendung
werden eine Reihe, das Jahr bleibt im Folgentitel – aber nie, wenn die Jahreszahl zum Namen gehört."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402

N = [0]


def filed(c, topic, n, channel='KiKA', title=None):
    rows = []
    for i in range(n):
        N[0] += 1
        rows.append({'title': '%s Folge %d' % (title or topic, i + 1), 'topic': topic, 'duration': 900, 'channel': channel,
                     'description': 'x', 'url_video': 'https://example.org/j%d.mp4' % N[0], 'timestamp': 1795100000})
    catalog.ingest(c, rows)
    for r in rows:
        wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?", (r['url_video'],)).fetchone()[0]
        row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
        catalog.file_under_sendung(c, row, json.loads(row['meta']), r, topic, 'contribution')


class YearEditions(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.db = database(tmp.name)
        with self.db() as c:catalog.initialize(c)
        self.svc = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(tmp.name))

    def shows(self, c):
        return {r[0]: r[1] for r in c.execute("SELECT title,COUNT(DISTINCT show_key) FROM works WHERE state='format' GROUP BY title")}

    def test_dein_song_years_become_one_reihe(self):
        with self.db() as c:
            for t in ('Dein Song 2023', 'Dein Song 2024', 'Dein Song 2025'):filed(c, t, 3)
        events = []
        with patch.object(diagnostics, 'event', lambda name, *a, **f: events.append((name, f))):
            self.assertEqual(self.svc.merge_year_editions(), 9)
            self.assertEqual(self.svc.merge_year_editions(), 0)              # idempotent
        with self.db() as c:
            self.assertEqual(self.shows(c), {'Dein Song': 1})
            eps = sorted(json.loads(r[0])['episode_title'] for r in c.execute("SELECT meta FROM works WHERE title='Dein Song'"))
        self.assertTrue(eps[0].startswith('Dein Song 2023'))                  # year stays visible
        self.assertEqual(events[0][1]['shows'], {'Dein Song': [2023, 2024, 2025]})

    def test_joins_an_existing_main_reihe(self):
        with self.db() as c:
            filed(c, 'Dein Song', 2);filed(c, 'Dein Song 2023', 2);filed(c, 'Dein Song 2024', 2)
            catalog.merge_year_editions(c)
            self.assertEqual(self.shows(c), {'Dein Song': 1})

    def test_year_belonging_to_the_name_is_kept(self):
        with self.db() as c:
            filed(c, 'Berlin 1945', 3)                                         # one year, outside 2000.., part of the name
            filed(c, 'Olympia 2024', 3, 'ZDF');filed(c, 'Olympia 2020', 3, 'ZDF')    # events
            filed(c, 'Bundestagswahl 2025', 3, 'ARD');filed(c, 'Bundestagswahl 2021', 3, 'ARD')
            filed(c, 'Fußball-EM 2024', 3, 'ARD');filed(c, 'Fußball-EM 2021', 3, 'ARD')
            filed(c, 'Abenteuer 2050', 3);filed(c, 'Abenteuer 2049', 3)          # future year: a name
            filed(c, 'Tagebuch 2022', 3)                                       # single year only
            filed(c, 'Kinderreporter 2023', 1);filed(c, 'Kinderreporter 2024', 1)   # single works, no Jahrgang
            filed(c, 'Sommerreise 2023', 3, 'KiKA');filed(c, 'Sommerreise 2024', 3, 'ARTE')  # different senders
            before = self.shows(c)
            self.assertEqual(catalog.merge_year_editions(c), (0, {}))
            self.assertEqual(self.shows(c), before)

    def test_year_edition_parse(self):
        self.assertEqual(catalog.year_edition('Dein Song 2023'), ('Dein Song', 2023))
        self.assertEqual(catalog.year_edition('KiKA Award – 2024'), ('KiKA Award', 2024))
        self.assertIsNone(catalog.year_edition('2024'))
        self.assertIsNone(catalog.year_edition('Doku 2024'))                   # generic stem


if __name__ == '__main__':
    unittest.main()
