"""0.6.146 (Björn 26.11.2026, zwei Bildschirmfotos der Kinderecke): YouTube-Kanalreihen mit halb leeren, viel zu
hohen Kacheln; Reihen wie „Checker Reportagen“, „Carolin testet“ weiter nur mit Anfangsbuchstaben."""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import broadcaster  # noqa: E402
import catalog  # noqa: E402
import kids_catalog  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402

ARD = 'https://www.ardmediathek.de/video/checker-reportagen/folge-%d/br/Y3JpZDovL2JyLmRlL3ZpZGVvLzEyMzQ1Njc4OQ%d'
PICTURE = 'https://api.ardmediathek.de/image-service/images/urn:ard:image:checker?w=1280'


class MoreTileShape(unittest.TestCase):
    def test_more_tile_follows_the_row(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn("function moreTile(n, filter, name, tall)", js)
        self.assertIn("'kids-tile kids-more' + (tall ? ' is-poster' : '')", js)
        self.assertIn("moreTile(more.n, more.filter, more.name, box.classList.contains('is-posters'))", js)
        self.assertNotIn("'kids-tile kids-more is-poster'", js)


class SenderPictures(Mixed):
    def shelf(self):
        kids_catalog.invalidate()
        import unified_index
        unified_index.invalidate();catalog.invalidate_listings(drop=True)
        for _ in range(100):
            d = kids_catalog._build_store(self.root, self.db, {}, True, None)
            if not d['pending']:
                return d
            time.sleep(0.1)
        self.fail('Katalog wurde nicht fertig')

    def prepare(self, url=True):
        self.series('show:checker', 'Checker Reportagen', [(3, 'KiKA', [], 'Reportage %d')])
        with self.db() as c:
            c.execute("UPDATE works SET meta=json_remove(meta,'$.poster') WHERE show_key='show:checker'")
            if url:
                for i, (oid, payload) in enumerate(c.execute("SELECT o.id,o.payload FROM offers o JOIN works w ON w.id=o.work_id "
                                                             "WHERE w.show_key='show:checker'").fetchall()):
                    p = json.loads(payload);p['url_website'] = ARD % (i, i)
                    c.execute('UPDATE offers SET payload=? WHERE id=?', (json.dumps(p), oid))

    def tile(self, d):
        return next(t for t in d['series'] if t['series']['show'] == 'show:checker')

    def test_series_without_picture_gets_the_sender_picture(self):
        self.prepare()
        self.assertEqual(self.tile(self.shelf())['poster'], '')
        asked = []

        def lookup(row):
            asked.append(row['url_website']);return {'series_image': PICTURE, 'image': ''}
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=lookup), (1, 1, 0))
        self.assertEqual(self.tile(self.shelf())['poster'], PICTURE)
        # einmal gefunden: keine weitere Abfrage
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=lookup), (0, 0, 0))
        self.assertEqual(len(asked), 1)

    def test_paused_sender_stores_nothing_and_kika_only_is_counted(self):
        self.prepare()
        self.shelf()

        def paused(row):
            raise broadcaster.Unavailable('ARD Mediathek pausiert')
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=paused), (0, 1, 0))
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, kids_catalog.PICTURES_KEY, {}), {})

    def test_without_sender_page_no_request_and_retry_after_a_week(self):
        self.prepare(url=False)
        self.shelf()
        calls = []
        now = time.time()
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, now=now, lookup=calls.append), (0, 0, 1))
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, now=now + 3600, lookup=calls.append), (0, 0, 0))
        self.assertEqual(calls, [])

    def test_same_title_across_films_and_series(self):
        out = {'movies': [{'title': 'Die wilde Natur', 'poster': 'https://img.example.org/natur.jpg'}],
               'series': [{'title': 'Die wilde Natur', 'poster': '', 'source': 'pluto'}]}
        kids_catalog._fill_pictures(None, out)
        self.assertEqual(out['series'][0]['poster'], 'https://img.example.org/natur.jpg')


if __name__ == '__main__':
    unittest.main()
