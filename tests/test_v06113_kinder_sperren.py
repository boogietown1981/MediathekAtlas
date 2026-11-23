"""Vorbereitung 0.6.113: sichtbare Titel der Kinderecke in der Elternansicht sperren (Film, ganze Serie, Plattform-Kachel)
und zurücknehmen. Ableitung aus Björns Regel „im Zweifel nicht, ich entscheide selbst“ (22.11.2026)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog, kids_rules  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402
from test_v0646_kids_catalog import fake_page, portal  # noqa: E402


class Block(Mixed):
    def test_film_and_series_block_and_undo(self):
        self.add('rabe', 'Der kleine Rabe Socke', ['Kinder'])
        self.series('show:maus', 'Die Sendung mit der Maus', [(2, 'Das Erste', [], 'Maus %d')])
        d = self.data()
        film = next(t for t in d['movies'] if t['title'] == 'Der kleine Rabe Socke')
        show = next(t for t in d['series'] if t['series']['show'] == 'show:maus')
        self.assertEqual(film['block'], {'kind': 'work', 'id': 'rabe'})
        self.assertEqual(show['block'], {'kind': 'show', 'id': 'show:maus'})
        with self.db() as c:
            kids_rules.choose(c, film['block']['kind'], film['block']['id'], 'block', film['title'])
            kids_rules.choose(c, show['block']['kind'], show['block']['id'], 'block', show['title'])
        d = self.data()
        self.assertEqual(d['movies'] + d['series'], [])
        with self.db() as c:
            self.assertFalse(kids_catalog.offer_allowed(c, 'o-rabe'))
            self.assertFalse(kids_catalog.work_allowed(c, 'show:maus-1'))      # Abspielen und Nachladen
            kids_rules.choose(c, 'work', 'rabe', '')
            kids_rules.choose(c, 'show', 'show:maus', '')
        d = self.data()
        self.assertEqual(len(d['movies']), 1)
        self.assertEqual(len(d['series']), 1)

    def test_platform_tile_block(self):
        movies = [{'cats': ['Kinder'], 'offers': [portal('netzkino', 'a' * 32, 'Rabe', fsk=0)]},
                  {'cats': ['Kinder'], 'offers': [portal('netzkino', 'b' * 32, 'Biene', fsk=0)]}]
        kids_catalog.invalidate()
        d = kids_catalog.build(self.root, self.db, page=fake_page({'movies': movies}))
        target = next(t['block'] for t in d['movies'] if t['title'] == 'Rabe')
        self.assertEqual(target['kind'], 'tile')
        with self.db() as c:
            kids_rules.choose(c, 'tile', target['id'], 'block', 'Rabe')
            self.assertIn('tile', [x['kind'] for x in kids_rules.choices(c)])
        kids_catalog.invalidate()
        d = kids_catalog.build(self.root, self.db, page=fake_page({'movies': movies}))
        self.assertEqual([t['title'] for t in d['movies']], ['Biene'])
        self.assertFalse(kids_catalog.allowed_ref(d, {'netzkino': 'a' * 32}))

    def test_unknown_kind_rejected(self):
        with self.db() as c:
            with self.assertRaises(ValueError):
                kids_rules.choose(c, 'alles', 'x', 'block')


class Wiring(unittest.TestCase):
    def test_parents_view_and_server(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        js = (ROOT / 'web' / 'kids_parents.js').read_text(encoding='utf-8')
        self.assertIn('id="kids-visible-filter"', html)
        self.assertIn('id="kids-visible"', html)
        self.assertIn('t.block', js)
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("kids_catalog._EPISODES_SEEN.clear()", src[src.index('def post_kids_rules('):])


if __name__ == '__main__':
    unittest.main()
