"""0.6.149 (Björn 26.11.2026): Kinderecke – neu abonnierte Kanäle stehen in der Gesamtansicht und der Kanalfilter zeigt
ihre Videos (Abo-Kennung war eine Zahl, der Filter warf einen Fehler); Fortschritt bzw. „schon geschaut“ wie bei YouTube
auch auf Katalogkarten, Kinderecke übernimmt Stände des großen Players."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kids_catalog  # noqa: E402
import watch_state  # noqa: E402


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


class KidsChannels(unittest.TestCase):
    def test_channel_ids_are_text_and_rows_before_groups(self):
        js = text('web/kids.js')
        self.assertIn("abo: String(v.abo)", js);self.assertIn("id: String(c.id)", js)
        self.assertIn("String(state.filter).startsWith('g:')", js)
        self.assertNotIn("state.filter.startsWith(", js.replace("String(state.filter).startsWith(", ''))
        all_view = js[js.index("const cut = (n, filter, name)"):]
        self.assertLess(all_view.index('for (const c of state.channels)'), all_view.index("grouped(main, byTitle("))


class Progress(unittest.TestCase):
    def test_overview_progress_carries_duration(self):
        with tempfile.TemporaryDirectory() as d:
            watch_state.progress(d, 'offer:o1', pos=600, duration=1200, info={'title': 'Film'})
            watch_state.progress(d, 'w2', pos=100, duration=100, done=True, info={'title': 'Fertig'})
            p = watch_state.overview(d)['progress']
        self.assertEqual((p['offer:o1']['pos'], p['offer:o1']['duration'], p['offer:o1']['done']), (600, 1200, False))
        self.assertTrue(p['w2']['done'])

    def test_kids_film_uses_position_of_the_big_player(self):
        data = {'movies': [{'id': 'mediatheken:o1', 'source': 'mediatheken', 'key': 'offer:o1', 'work': 'w1', 'duration': 1000,
                            'title': 'Film'}], 'series': []}
        out = kids_catalog.with_progress(data, {'w1': {'pos': 250}})['movies'][0]
        self.assertEqual((out['pos'], out['progress']), (250, 0.25))
        own = kids_catalog.with_progress(data, {'offer:o1': {'pos': 500}, 'w1': {'pos': 250}})['movies'][0]
        self.assertEqual(own['pos'], 500)                     # eigener Stand der Kinderecke geht vor
        seen = kids_catalog.with_progress(data, {'w1': {'done': True}})['movies'][0]
        self.assertTrue(seen['done']);self.assertEqual(seen['progress'], 0)

    def test_catalog_cards_show_progress_and_seen(self):
        wl, uc, css = text('web/watchlist.js'), text('web/unified_catalog.js'), text('web/style.css')
        self.assertIn('function progressNode(item)', wl);self.assertIn("'✓ Gesehen'", wl);self.assertIn('repaintProgress()', wl)
        self.assertIn('W?.progressNode?.(seen||main)', uc)
        self.assertIn('.atlas-progress-bar i{', css)


if __name__ == '__main__':
    unittest.main()
