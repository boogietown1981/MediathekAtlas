"""0.6.127 (Björn 23.11.2026): „#BR24 Zeitreise“ und „#BR24Zeitreise“ als zwei Reihen."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402


def offer(title, topic, channel, n):
    return {'title': title, 'topic': topic, 'channel': channel, 'duration': 600, 'description': 'Folge',
            'url_video': 'https://example.org/%s-%d.mp4' % (channel, n)}


class SpacingVariants(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)

    def series(self, rows):
        catalog.ingest(self.c, rows)
        for w in self.c.execute('SELECT id,meta,topic FROM works').fetchall():
            m = json.loads(w['meta']);m.update(kind='series', title=w['topic'], year=None)
            self.c.execute("UPDATE works SET kind='series',title=?,year=NULL,show_key=?,meta=?,state='identified' WHERE id=?",
                           (w['topic'], catalog.showkey(m), json.dumps(m), w['id']))

    def shows(self):
        return {(r['title'], r['show_key']): r['n'] for r in self.c.execute('SELECT title,show_key,COUNT(*) n FROM works GROUP BY title,show_key')}

    def test_same_sender_spacing_variants_become_one(self):
        self.series([offer('A%d' % i, '#BR24 Zeitreise', 'BR', i) for i in range(3)] +
                    [offer('B%d' % i, '#BR24Zeitreise', 'BR', 10 + i) for i in range(2)])
        out = catalog.merge_spacing_variants(self.c)
        self.assertEqual(out, {'#BR24Zeitreise': '#BR24 Zeitreise'})
        self.assertEqual(list(self.shows().values()), [5])
        self.assertEqual(catalog.merge_spacing_variants(self.c), {})

    def test_other_sender_or_other_identity_stays(self):
        self.series([offer('A%d' % i, 'Wo ist das', 'BR', i) for i in range(3)] + [offer('B1', 'Woist das', 'NDR', 20)])
        self.assertEqual(catalog.merge_spacing_variants(self.c), {})
        self.assertEqual(len(self.shows()), 2)

    def test_different_database_identities_stay(self):
        self.series([offer('A1', 'Night Shift', 'ARD', 1), offer('B1', 'Nightshift', 'ARD', 2)])
        for i, (w, ref) in enumerate(zip(self.c.execute('SELECT id,meta FROM works ORDER BY title').fetchall(), ('tt1', 'tt2'))):
            m = json.loads(w['meta']);m.update(provider='IMDb Offline', reference_id=ref)
            self.c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), w['id']))
        self.assertEqual(catalog.merge_spacing_variants(self.c), {})


if __name__ == '__main__':
    unittest.main()
