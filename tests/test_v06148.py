"""0.6.148 (Björn 26.11.2026, Kinderecke „Abenteuer“: „die verwegene sollten als serie zusammengefasst werden“):
Filme mit vorangestellter Folgennummer und gemeinsamem Reihennamen werden zu einer Serie, Folgen nach Nummer."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kids_catalog  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import local_titles  # noqa: E402
import unified_index  # noqa: E402
sys.path.insert(0, str(ROOT / 'tests'))
import test_v0555_dashboard_admin as base  # noqa: E402

NUMBERS = (10, 11, 13, 17, 2, 5, 6)
TITLES = {10: 'Die verwegenen Vier auf heisser Spur', 11: 'Die verwegenen Vier und der Schatz', 13: 'Die verwegenen Vier auf Geisterjagd',
          17: 'Die verwegenen Vier halten zusammen', 2: 'Die verwegenen Vier reissen aus', 5: 'Die verwegenen Vier bewähren sich',
          6: 'Die verwegenen Vier in Gefahr'}


def page_of(movies):
    def page(root, db, kind='movies', genre='', offset=0, **kw):
        rows = movies if kind == 'movies' else []
        return {'items': rows[offset:offset + 50], 'total': len(rows), 'pending': []}
    return page


def film(item_id, title, source='netzkino', poster='https://img.example.org/v.jpg'):
    return {'offers': [{'source': source, 'item': {'id': item_id, 'title': title, 'kind': 'movie', 'playable': 1,
                                                   'poster': poster, 'year': 1991, 'duration': 1560,
                                                   'genres': ['Abenteuer']}}]}


def nid(n):
    return ('%032x' % n)


class NumberedSeries(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate();kids_catalog._EPISODES_SEEN.clear()

    def build(self, movies):
        return kids_catalog.build('/r', None, page=page_of(movies))

    def test_blyton_episodes_become_one_series_sorted_by_number(self):
        movies = [film(nid(n), '%d. %s' % (n, TITLES[n])) for n in NUMBERS]
        movies += [film(nid(99), 'Der kleine Rabe Socke'), film(nid(98), '3. Mann im Mond')]
        data = self.build(movies)
        self.assertEqual(sorted(t['title'] for t in data['movies']), ['3. Mann im Mond', 'Der kleine Rabe Socke'])
        self.assertEqual(len(data['series']), 1)
        show = data['series'][0]
        self.assertEqual((show['title'], show['kind'], show['source'], show['group']),
                         ('Die verwegenen Vier', 'series', 'netzkino', 'abenteuer'))
        self.assertTrue(show['series']['id'].startswith('nummern-'))
        eps = kids_catalog.episodes('/r', None, data, 'netzkino', show['series']['id'],
                                    {'netzkino:' + nid(5): {'pos': 780}})['episodes']
        self.assertEqual([e['episode'] for e in eps], sorted(NUMBERS))
        self.assertEqual(eps[0]['title'], 'Die verwegenen Vier reissen aus')
        self.assertEqual(eps[0]['ref'], {'netzkino': nid(2)})
        self.assertEqual(eps[1]['progress'], 0.5)                      # Weiterschauen je Film bleibt erhalten
        # jeder Film bleibt abspielbar, fremde nicht
        self.assertTrue(kids_catalog.allowed_ref(data, {'netzkino': nid(17)}))
        kids_catalog._EPISODES_SEEN.clear()
        self.assertTrue(kids_catalog.allowed_ref(data, {'netzkino': nid(13)}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'netzkino': nid(77)}))
        # die Kachelliste an die Kinderecke trägt die Folgen nicht mit
        self.assertNotIn('films', kids_catalog.with_progress(data, {})['series'][0])

    def test_needs_three_numbers_common_start_and_same_source(self):
        movies = [film(nid(1), '1. Die verwegenen Vier reissen aus'), film(nid(2), '2. Die verwegenen Vier in Gefahr'),
                  film('p-3', '3. Die verwegenen Vier auf Geisterjagd', source='pluto'),
                  film(nid(4), '1. Die Biene Maja'), film(nid(5), '2. Die Bienen'), film(nid(6), '3. Die Bienenkönigin')]
        data = self.build(movies)
        self.assertEqual(data['series'], [])
        self.assertEqual(len(data['movies']), 6)

    def test_unknown_series_id_is_refused(self):
        data = self.build([film(nid(n), '%d. %s' % (n, TITLES[n])) for n in NUMBERS])
        with self.assertRaises(ValueError):
            kids_catalog.episodes('/r', None, data, 'netzkino', 'nummern-0000000000000000')
        with self.assertRaises(ValueError):
            kids_catalog.episodes('/r', None, data, 'pluto', data['series'][0]['series']['id'])

    def test_parents_can_block_the_series_tile(self):
        data = self.build([film(nid(n), '%d. %s' % (n, TITLES[n])) for n in NUMBERS])
        show = data['series'][0]
        self.assertEqual(show['block'], {'kind': 'tile', 'id': show['id']})


class LocalFirst(base.UnifiedPageTests):
    """Björn 26.11.2026: geladene Filme und Serien zuerst – Katalog (gemeinsamer Index) und Kinderecke."""
    test_merged_sorted_page = test_filters_paging_and_cache = test_removed_work_is_skipped = None

    def setUp(self):
        super().setUp();local_titles.invalidate()
        import catalog
        from unittest import mock
        # ein früherer Server-Test der Suite setzt catalog.LISTING_DB (Hintergrund-Aufbau auf SEINER Datenbank)
        patch = mock.patch.object(catalog, 'LISTING_DB', None);patch.start();self.addCleanup(patch.stop)
        self.addCleanup(local_titles.invalidate)

    def titles(self, **kw):
        import time
        for _ in range(100):      # nach einem Start gruppiert der Katalog im Hintergrund (ListingPending)
            import catalog     # Listen-Zwischenspeicher ist nicht je Datenbank (andere Tests derselben Suite)
            catalog.invalidate_listings(drop=True);unified_index.invalidate();local_titles.invalidate()
            page = unified_index.page(self.dir.name, self.db, modules=self.modules, **kw)
            if not page['pending']:
                break
            time.sleep(0.05)
        self.last = (page['counts'], page['errors'], page['pending'])
        return [(i['title'], bool(i.get('local'))) for i in page['items']]

    def test_without_downloads_order_is_unchanged(self):
        self.assertEqual(self.titles(), [('Alpha', False), ('Ärger im Paradies', False), ('#Roxy', False), ('Zebra', False)], self.last)

    def test_downloaded_work_and_portal_copy_come_first(self):
        film = Path(self.dir.name) / 'zebra.mkv';film.write_bytes(b'x')
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT, state TEXT)')
            c.execute('INSERT INTO downloaded_items VALUES(?,?,?)', ('w0', str(film), 1.0))
            c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j1', json.dumps({'origin': 'pluto', 'pluto_id': 'p2', 'path': str(film)}), 'done'))
            c.execute('INSERT INTO jobs VALUES(?,?,?)', ('j2', json.dumps({'origin': 'pluto', 'pluto_id': 'p1', 'path': '/weg/datei.mkv'}), 'done'))
        self.assertEqual(self.titles(), [('Alpha', True), ('Zebra', True), ('Ärger im Paradies', False), ('#Roxy', False)])
        self.assertEqual([t for t, _ in self.titles(sort='year')], ['Zebra', 'Alpha', '#Roxy', 'Ärger im Paradies'])

    def test_series_counts_when_one_episode_is_downloaded(self):
        with self.db() as c:
            for wid, ep in (('s1', 1), ('s2', 2)):
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          (wid, 'Die Maus', 'series', 2020, 'maus', json.dumps({'title': 'Die Maus', 'kind': 'series', 'episode': ep}), 'matched', 1.0))
                c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                          ('o' + wid, wid, json.dumps({'title': 'Die Maus', 'channel': 'KiKA', 'url_video': 'https://example.org/m.mp4'}), '', 1, 1.0))
            c.execute('INSERT INTO downloaded_items VALUES(?,?,?)', ('s2', '/x/s2.mkv', 1.0))
        self.assertEqual(self.titles(kind='series')[0], ('Die Maus', True))
        with self.db() as c:
            self.assertLessEqual({'s1', 's2'}, local_titles.local_works(c, series=True))
            self.assertEqual(local_titles.local_works(c), {'s2'})

    def test_kids_tiles_carry_local_and_ui_sorts_it_first(self):
        movies = [film(nid(1), 'Anton'), film(nid(2), 'Zora')]
        movies[1]['local'] = True
        data = kids_catalog.build('/r', None, page=page_of(movies))
        self.assertEqual({t['title']: bool(t.get('local')) for t in data['movies']}, {'Anton': False, 'Zora': True})
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn("(!a.local - !b.local)", js);self.assertIn("kids-local", js)
        self.assertIn("if (x.local && x.type !== 'abo') score += 1", js)
        self.assertIn("atlas-uc-local", (ROOT / 'web' / 'unified_catalog.js').read_text(encoding='utf-8'))

    def test_numbered_series_is_local_when_a_film_is(self):
        movies = [film(nid(n), '%d. %s' % (n, TITLES[n])) for n in NUMBERS]
        movies[3]['local'] = True
        data = kids_catalog.build('/r', None, page=page_of(movies))
        self.assertTrue(data['series'][0].get('local'))


if __name__ == '__main__':
    unittest.main()
