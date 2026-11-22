"""0.6.46 (Björn, 20.11.2026): Kinderfilme und Kinderserien aus dem Katalog in der Kinderecke (kids_catalog.py)
und Vollbild für Videos beim Anbieter (Chrome-Erweiterung)."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog, kids_catalog, unified_index  # noqa: E402
from _wiring import routed, SERVER  # noqa: E402


def text(name):
    return (ROOT / name).read_text(encoding='utf-8')


def fake_page(entries):
    """Ersatz für unified_index.page: liefert nur, was unter der verlangten Kategorie steht."""
    calls = []

    def page(root, db, kind='movies', genre='', offset=0, **kw):
        calls.append((kind, genre, offset))
        rows = [e for e in entries.get(kind, []) if genre in e.get('cats', ())]
        return {'items': rows[offset:offset + 2], 'total': len(rows), 'pending': []}
    page.calls = calls
    return page


def portal(source, item_id, title, kind='movie', playable=1, **extra):
    return {'source': source, 'item': {'id': item_id, 'title': title, 'kind': kind, 'playable': playable,
                                       'poster': 'https://img.example.org/p.jpg', 'year': 2019, 'duration': 5400, **extra}}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate()
        kids_catalog._EPISODES_SEEN.clear()

    def build(self, entries):
        page = fake_page(entries)
        return kids_catalog.build('/r', None, page=page), page

    def test_only_category_kinder_is_requested(self):
        data, page = self.build({'movies': [
            {'cats': ['Kinder'], 'offers': [portal('pluto', 'pluto-kind-1', 'Der kleine Rabe')]},
            {'cats': ['Familie'], 'offers': [portal('pluto', 'pluto-fam-1', 'Familienfilm ab 12')]},
            {'cats': ['Thriller'], 'offers': [portal('pluto', 'pluto-thr-1', 'Thriller')]}]})
        self.assertEqual({genre for _, genre, _ in page.calls}, {'Kinder'})
        self.assertEqual([t['title'] for t in data['movies']], ['Der kleine Rabe'])
        self.assertEqual(data['movies'][0]['ref'], {'pluto': 'pluto-kind-1'})
        self.assertEqual(data['movies'][0]['key'], 'pluto:pluto-kind-1')

    def test_protected_and_youtube_sources_stay_outside(self):
        data, _ = self.build({'movies': [
            {'cats': ['Kinder'], 'offers': [portal('joyn', 'j1', 'Joyn-Film')]},
            {'cats': ['Kinder'], 'offers': [portal('rtlplus', 'r1', 'RTL-Film')]},
            {'cats': ['Kinder'], 'offers': [portal('crunchyroll', 'c1', 'Anime')]},
            {'cats': ['Kinder'], 'offers': [portal('youtube', 'abcdefghijk', 'YouTube-Film')]},
            {'cats': ['Kinder'], 'offers': [portal('justwatch', 'tm9', 'Geschützt', playable=0)]},
            {'cats': ['Kinder'], 'offers': [portal('joyn', 'j2', 'Zweifach'), portal('toggo', 'tg-22', 'Zweifach')]}]})
        self.assertEqual([(t['source'], t['title']) for t in data['movies']], [('toggo', 'Zweifach')])

    def test_all_pages_and_series_tiles(self):
        movies = [{'cats': ['Kinder'], 'offers': [portal('plex', 'm.%d' % i, 'Film %d' % i)]} for i in range(5)]
        series = [{'cats': ['Kinder'], 'offers': [portal('toggo', 'serie-1', 'Paw', kind='series')]},
                  {'cats': ['Kinder'], 'offers': [{'source': 'netzkino', 'item': {'kind': 'series', 'series_key': 'series-' + 'a' * 24, 'title': 'Biene'}}]},
                  {'cats': ['Kinder'], 'offers': [{'source': 'mediatheken', 'item': {'series_parent': True, 'show_key': 'show:maus', 'metadata': {'title': 'Maus'}}}]}]
        data, page = self.build({'movies': movies, 'series': series})
        self.assertEqual(len(data['movies']), 5)
        self.assertEqual([(t['source'], t['series']) for t in data['series']],
                         [('toggo', {'id': 'serie-1'}), ('netzkino', {'id': 'series-' + 'a' * 24}), ('mediatheken', {'show': 'show:maus'})])
        self.assertNotIn('ref', data['series'][0])

    def test_poster_must_be_https_and_ids_safe(self):
        data, _ = self.build({'movies': [
            {'cats': ['Kinder'], 'offers': [portal('pluto', 'ok-123456', 'Bild', poster='http://img.example.org/p.jpg')]},
            {'cats': ['Kinder'], 'offers': [portal('pluto', 'x' * 300, 'Zu lang')]}]})
        self.assertEqual([t['title'] for t in data['movies']], ['Bild'])
        self.assertEqual(data['movies'][0]['poster'], '')

    def test_allowed_ref_only_for_listed_titles(self):
        data, _ = self.build({'movies': [{'cats': ['Kinder'], 'offers': [portal('pluto', 'pluto-kind-1', 'Rabe')]}]})
        self.assertTrue(kids_catalog.allowed_ref(data, {'pluto': 'pluto-kind-1'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'pluto': 'pluto-thr-1'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'pluto-kind-1'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'pluto': 'pluto-kind-1', 'offer': 'x'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {}))

    def test_progress_is_added_per_title(self):
        data, _ = self.build({'movies': [{'cats': ['Kinder'], 'offers': [portal('pluto', 'pluto-kind-1', 'Rabe')]}]})
        out = kids_catalog.with_progress(data, {'pluto:pluto-kind-1': {'pos': 2700}})
        self.assertEqual(out['movies'][0]['progress'], 0.5)
        self.assertNotIn('progress', data['movies'][0])       # die zwischengespeicherte Liste bleibt unverändert
        done = kids_catalog.with_progress(data, {'pluto:pluto-kind-1': {'pos': 5300, 'done': True}})
        self.assertTrue(done['movies'][0]['done'])
        self.assertEqual(done['movies'][0]['progress'], 0)

    def test_shelf_is_cached(self):
        page = fake_page({'movies': [{'cats': ['Kinder'], 'offers': [portal('pluto', 'pluto-kind-1', 'Rabe')]}]})
        kids_catalog.shelf('/r', None, page=page)
        n = len(page.calls)
        kids_catalog.shelf('/r', None, page=page)
        self.assertEqual(len(page.calls), n)
        kids_catalog.shelf('/r', None, page=page, fresh=True)
        self.assertGreater(len(page.calls), n)


class MediathekTests(unittest.TestCase):
    """Echter Werkkatalog (catalog.py) über unified_index, ohne Plattformen."""

    def setUp(self):
        kids_catalog.invalidate()
        kids_catalog._EPISODES_SEEN.clear()
        unified_index.invalidate()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'catalog.db'
        with self.db() as c:
            catalog.initialize(c)
        old = catalog.LISTING_DB
        catalog.LISTING_DB = self.db
        self.addCleanup(setattr, catalog, 'LISTING_DB', old)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add(self, wid, title, genres, kind='movie', show=None, state='matched', attempts=1, season=None, episode=None, active=1,
            channel='Das Erste', topic=''):
        # 0.6.91: Sender KiKA und Kinder-/Märchenreihen zählen selbst als Kinder-Signal; die Genre-Regeln hier
        # prüfen deshalb mit einem allgemeinen Sender.
        meta = {'title': title if kind == 'movie' else (show or title), 'kind': kind, 'genres': genres, 'poster': 'https://img.example.org/%s.jpg' % wid}
        if kind == 'series':
            meta.update(season=season, episode=episode, episode_title=title)
        with self.db() as c:
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,?)",
                      (wid, meta['title'], kind, 2015, show or wid, json.dumps(meta), state, attempts))
            c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,?)",
                      ('o-' + wid, wid, json.dumps({'title': title, 'channel': channel, 'topic': topic, 'duration': 1500, 'url_video': 'https://example.org/%s.mp4' % wid}), active))
            for g in genres:
                c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))

    def shelf(self):
        for _ in range(100):
            data = kids_catalog.build(self.root, self.db, modules={})
            if not data['pending']:
                return data
            time.sleep(0.1)
        self.fail('Katalog wurde nicht fertig')

    def test_films_only_with_clear_kids_signal(self):
        self.add('rabe', 'Der kleine Rabe Socke', ['Kinder'])
        self.add('pixar', 'Trickfilm', ['Familie', 'Animation'])
        self.add('familie', 'Familiendrama', ['Familie', 'Drama'])
        self.add('kidskrimi', 'Kinderkrimi', ['Kinder', 'Krimi'])
        self.add('grusel', 'Gruselkinder', ['Kinder', 'Horror'])
        self.add('offen', 'Noch nicht abgeglichen', ['Kinder'], state='new', attempts=0)
        self.add('weg', 'Nicht mehr online', ['Kinder'], active=0)
        data = self.shelf()
        self.assertEqual(sorted(t['title'] for t in data['movies']), ['Der kleine Rabe Socke', 'Trickfilm'])
        rabe = next(t for t in data['movies'] if t['title'].startswith('Der kleine'))
        self.assertEqual(rabe['ref'], {'offer': 'o-rabe'})
        self.assertEqual(rabe['key'], 'offer:o-rabe')
        self.assertTrue(kids_catalog.allowed_ref(data, {'offer': 'o-rabe'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'o-kidskrimi'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'o-offen'}))

    def test_series_episodes_are_checked_one_by_one(self):
        self.add('m1', 'Die Maus im Zoo', ['Kinder'], kind='series', show='show:maus', season=1, episode=1)
        self.add('m2', 'Die Maus am Meer', ['Kinder'], kind='series', show='show:maus', season=1, episode=2)
        self.add('m3', 'Sonderfolge Krimi', ['Kinder', 'Krimi'], kind='series', show='show:maus', season=1, episode=3)
        self.add('t1', 'Tatort', ['Krimi'], kind='series', show='show:tatort', season=1, episode=1)
        data = self.shelf()
        self.assertEqual([t['series'] for t in data['series']], [{'show': 'show:maus'}])
        with self.db() as c:
            eps = kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:maus', {'offer:o-m1': {'pos': 100, 'done': True}})
            self.assertEqual([(e['episode'], e['title'], e['done']) for e in eps['episodes']],
                             [(1, 'Die Maus im Zoo', True), (2, 'Die Maus am Meer', False)])
            with self.assertRaises(ValueError):
                kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:tatort')
            with self.assertRaises(ValueError):
                kids_catalog.episodes(self.root, c, data, 'joyn', 'show:maus')
        self.assertTrue(kids_catalog.allowed_ref(data, {'offer': 'o-m2'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'o-m3'}))
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'o-t1'}))


class WiringTests(unittest.TestCase):
    def test_routes_and_guard(self):
        self.assertTrue(routed('/api/kids-episodes', 'GET'))
        self.assertTrue(routed('/api/kids-play', 'GET'))
        body = SERVER[SERVER.index("@ROUTES.get('/api/kids-play')"):]
        body = body[:body.index('@ROUTES', 10)]
        self.assertIn('allowed_ref', body)
        self.assertIn("return get_play(self,path)", body)
        self.assertIn('kids_catalog.with_progress', SERVER)

    def test_page_plays_through_guarded_route_only(self):
        js = text('web/kids.js')
        self.assertIn("api('kids-play?'", js)
        self.assertNotIn("api('play?'", js)
        self.assertIn("'kids-episodes?'", js)
        self.assertNotIn('window.open', js)          # die Kinderecke öffnet keine Anbieterseiten
        self.assertNotIn('target=', js)

    def test_module_is_packaged(self):
        self.assertIn("'kids_catalog.py'", text('build_macos.py'))
        self.assertIn('./mediathekatlas/kids_catalog.py', text('qpkg-files.txt'))

    def test_no_protected_or_embed_sources(self):
        for name in ('joyn', 'rtlplus', 'crunchyroll', 'youtube'):
            self.assertNotIn(name, kids_catalog.SOURCES)
            self.assertNotIn(name, kids_catalog.REF_KEYS)


class ExtensionTests(unittest.TestCase):
    def test_fullscreen_pieces(self):
        auto = text('web/browser-extension/chrome/autostart.js')
        back = text('web/browser-extension/chrome/background.js')
        self.assertIn("tell('fullscreen')", auto)
        self.assertIn('requestFullscreen', auto)
        self.assertIn('e.isTrusted', auto)
        self.assertIn("state: 'fullscreen'", back)
        self.assertIn('chrome.tabs.onRemoved', back)
        manifest = json.loads(text('web/browser-extension/chrome/manifest.json'))
        self.assertEqual(sorted(manifest['permissions']), ['scripting', 'storage'])   # keine neue Berechtigung, sonst deaktiviert Chrome das Update
        popup = text('web/browser-extension/chrome/popup.html')
        self.assertIn('id="fullscreen"', popup)
        self.assertIn('id="fill"', popup)


if __name__ == '__main__':
    unittest.main()
