"""0.6.57: Besetzung bei Serien ohne Seriendaten, „Alle anzeigen“ aus den TMDB-Credits, Plex über die eigene IMDb-ID."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cast_photos, catalog   # noqa: E402

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 500


class FakeTmdb:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, path, params):
        self.calls.append(path)
        if path not in self.data:
            raise OSError('offline')
        return self.data[path]


CREDITS = {'find/tt1193138': {'movie_results': [{'id': 22947}]},
           'movie/22947/credits': {
               'cast': [{'name': 'George Clooney', 'character': 'Ryan Bingham', 'profile_path': '/gc.jpg'},
                        {'name': 'Vera Farmiga', 'character': 'Alex', 'profile_path': '/vf.jpg'}]
                       + [{'name': 'Darsteller %d' % i, 'character': 'Rolle %d' % i, 'profile_path': None} for i in range(50)],
               'crew': [{'name': 'Jason Reitman', 'job': 'Director', 'profile_path': '/jr.jpg'},
                        {'name': 'Kameramann', 'job': 'Director of Photography', 'profile_path': '/k.jpg'}]}}
CONTEXT = {'kind': 'movie', 'title': 'Up in the Air', 'year': 2009, 'imdb_id': 'tt1193138'}


class MoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cast_photos._FAILED.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_further_people_in_billing_order_without_the_listed_ones_and_without_other_crew(self):
        tmdb = FakeTmdb(CREDITS)
        out = cast_photos.lookup(self.root, 'k' * 32, ['George Clooney'], CONTEXT, tmdb, more=True)
        names = [p['name'] for p in out['more']]
        self.assertEqual(names[:3], ['Jason Reitman', 'Vera Farmiga', 'Darsteller 0'])
        self.assertNotIn('George Clooney', names)
        self.assertNotIn('Kameramann', names)
        self.assertEqual(len(names), cast_photos.MAX_MORE)
        self.assertEqual(out['more'][0], {'name': 'Jason Reitman', 'role': 'Regie', 'crew': True, 'file': 'jr.jpg'})
        self.assertEqual(out['more'][1]['role'], 'Alex')
        self.assertEqual(out['files'], {'George Clooney': 'gc.jpg'})
        # second opening: everything from people.sqlite, no TMDB call
        tmdb.calls.clear()
        again = cast_photos.lookup(self.root, 'k' * 32, ['George Clooney'], CONTEXT, tmdb, more=True)
        self.assertEqual(tmdb.calls, [])
        self.assertEqual(again['more'], out['more'])
        # photos of further people are loadable from the local store
        self.assertEqual(cast_photos.photo(self.root, 'vf.jpg', lambda url: JPEG)[0], JPEG)

    def test_page_without_own_cast_gets_the_whole_cast(self):
        out = cast_photos.lookup(self.root, 'k' * 32, [], CONTEXT, FakeTmdb(CREDITS), more=True)
        self.assertEqual(out['more'][0]['name'], 'Jason Reitman')
        self.assertEqual(out['more'][1]['name'], 'George Clooney')

    def test_without_more_nothing_changes_and_errors_are_not_cached(self):
        self.assertEqual(cast_photos.lookup(self.root, '', [], CONTEXT, FakeTmdb(CREDITS), more=True)['more'], [])
        failing = cast_photos.lookup(self.root, 'k' * 32, [], CONTEXT, FakeTmdb({}), more=True)
        self.assertEqual(failing.get('error'), 'OSError')
        self.assertNotIn('more', cast_photos.lookup(self.root, 'k' * 32, ['George Clooney'], CONTEXT, FakeTmdb(CREDITS)))
        # the title listing stored by the plain lookup serves the next "more" without TMDB
        self.assertEqual(cast_photos.lookup(self.root, 'k' * 32, [], CONTEXT, FakeTmdb({}), more=True)['more'][0]['name'], 'Jason Reitman')

    def test_unknown_title_is_remembered_as_miss(self):
        tmdb = FakeTmdb({'find/tt1193138': {'movie_results': []}, 'search/movie': {'results': []}})
        self.assertEqual(cast_photos.lookup(self.root, 'k' * 32, [], CONTEXT, tmdb, more=True)['more'], [])
        tmdb.calls.clear()
        cast_photos.lookup(self.root, 'k' * 32, [], CONTEXT, tmdb, more=True)
        self.assertEqual(tmdb.calls, [])


def ep(title):
    return {'title': title, 'topic': 'Der Pass', 'channel': 'ZDF', 'description': 'Folge ' + title, 'duration': 2700,
            'url_video': 'https://example.org/' + title.replace(' ', '_') + '.mp4'}


class SeriesFallbackTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:'); self.c.row_factory = sqlite3.Row; self.c.executescript(catalog.SCHEMA)

    def tearDown(self):
        self.c.close()

    def test_series_without_show_credits_uses_the_works(self):
        catalog.ingest(self.c, [ep('Eins S01E01'), ep('Zwei S01E02')])
        show = catalog.listing(self.c)['items'][0]['show_key']
        rows = self.c.execute('SELECT id,meta FROM works WHERE show_key=? ORDER BY id', (show,)).fetchall()
        casts = [[{'name': 'Gast', 'role': 'X'}, {'name': 'Julia Jentsch', 'role': 'Ellie Stocker', 'imdb_id': 'nm0421026'}],
                 [{'name': 'Julia Jentsch', 'role': 'Ellie Stocker'}, {'name': 'Nicholas Ofczarek', 'role': 'Gedeon Winter'}]]
        for r, cast in zip(rows, casts):
            m = json.loads(r['meta']); m.update(cast=cast, directors=['Cyrill Boss', 'Philipp Stennert'], show_credits={})
            self.c.execute("UPDATE works SET meta=?,state='matched' WHERE id=?", (json.dumps(m), r['id']))
        credits = catalog.show_detail(self.c, show)['show']['show_credits']
        self.assertEqual(credits['cast'][0]['name'], 'Julia Jentsch')   # in both works: first
        self.assertEqual(sorted(p['name'] for p in credits['cast'][1:]), ['Gast', 'Nicholas Ofczarek'])
        self.assertEqual(credits['cast'][0], {'name': 'Julia Jentsch', 'role': 'Ellie Stocker', 'imdb_id': 'nm0421026'})
        self.assertEqual(credits['directors'], ['Cyrill Boss', 'Philipp Stennert'])
        self.assertEqual(credits['source'], 'works')

    def test_existing_show_credits_win(self):
        catalog.ingest(self.c, [ep('Eins S01E01')])
        show = catalog.listing(self.c)['items'][0]['show_key']
        r = self.c.execute('SELECT id,meta FROM works WHERE show_key=?', (show,)).fetchone()
        m = json.loads(r['meta']); m.update(cast=[{'name': 'Gast'}], show_credits={'cast': [{'name': 'Hauptrolle'}]})
        self.c.execute("UPDATE works SET meta=?,state='matched' WHERE id=?", (json.dumps(m), r['id']))
        self.assertEqual(catalog.show_detail(self.c, show)['show']['show_credits'], {'cast': [{'name': 'Hauptrolle'}]})


class WiringTests(unittest.TestCase):
    def test_plex_imdb_id_and_more_switch(self):
        self.assertIn("m['cast_ref'] = {**ref, 'imdb_id': ref.get('imdb_id') or own}", (ROOT / 'portal_title.py').read_text(encoding='utf-8'))
        self.assertIn("more=bool(d.get('more'))", (ROOT / 'server.py').read_text(encoding='utf-8'))
        js = (ROOT / 'web' / 'titleview.js').read_text(encoding='utf-8')
        self.assertIn('more:true', js)
        self.assertIn("' anzeigen'", js)


if __name__ == '__main__':
    unittest.main()
