"""0.6.5: audio and subtitle languages per title (languages.py) for every source.

Björn (14.11.2026): "was mir bisher auch fehlt sind die Sprachen, in denen der Film oder die Serie
verfügbar ist". Evidence: stream (HLS playlist), provider fields, title marks, assumption for
German-language offers; nothing else is guessed."""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402
import languages  # noqa: E402
import unified_index  # noqa: E402

MASTER = '\n'.join([
    '#EXTM3U',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="deu",NAME="Deutsch",DEFAULT=YES',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="en",NAME="English"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="de",NAME="Deutsch (Audiodeskription)",CHARACTERISTICS="public.accessibility.describes-video"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="de",NAME="Deutsch",URI="de.m3u8"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="und",NAME="Unknown",URI="x.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720,AUDIO="aac",SUBTITLES="subs"',
    'https://cdn.example/720.m3u8'])


class CodeTests(unittest.TestCase):
    def test_codes_and_labels(self):
        for value, want in (('de-DE', 'de'), ('DEU', 'de'), ('ger', 'de'), ('German', 'de'), ('Deutsch', 'de'),
                            ('en_US', 'en'), ('ENG', 'en'), ('Französisch', 'fr'), ('ja-JP', 'ja'),
                            ({'id': 'ITA', 'name': 'Italienisch'}, 'it'), ('und', ''), ('MIS', ''), ('zxx', ''),
                            ('Klingonisch', ''), ('', ''), (None, '')):
            self.assertEqual(languages.code(value), want, value)
        self.assertEqual(languages.label('fr'), 'Französisch')

    def test_title_marks(self):
        t = languages.from_title
        self.assertEqual(t('Der Pate (OmU)'), {'audio': [], 'subtitles': ['de'], 'original': True, 'accessibility': []})
        self.assertTrue(t('Mord im Orient-Express (Originalversion mit Untertitel)')['original'])
        self.assertEqual(t('Film (Englisch)')['audio'], ['en'])
        self.assertEqual(t('The Crown – English version')['audio'], ['en'])
        self.assertEqual(t('Doku (mit Untertitel)')['subtitles'], ['de'])
        self.assertEqual(t('Tatort: Spur (Audiodeskription)')['accessibility'], ['Audiodeskription'])
        self.assertEqual(t('Nachrichten in Gebärdensprache')['accessibility'], ['Gebärdensprache'])
        self.assertEqual(t('Ganzer Film Deutsch')['audio'], ['de'])
        # ordinary words are not language marks
        self.assertEqual(t('Der Engländer, der auf einen Hügel stieg'), {'audio': [], 'subtitles': [], 'original': False, 'accessibility': []})
        self.assertEqual(t('Originale Rezepte aus Italien')['original'], False)


class EvidenceTests(unittest.TestCase):
    def test_hls_master(self):
        self.assertEqual(languages.parse_hls(MASTER), {'audio': ['de', 'en'], 'subtitles': ['de'], 'accessibility': ['Audiodeskription']})
        # muxed audio without EXT-X-MEDIA says nothing (unknown, not "none")
        self.assertEqual(languages.parse_hls('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhttps://a/b.m3u8'), {})

    def test_player_tracks(self):
        found = languages.tracks_from_player([{'lang': 'de', 'name': 'Deutsch'}, {'lang': '', 'name': 'English'}, 'x'],
                                             [{'lang': 'fra', 'name': 'Français'}])
        self.assertEqual(found, {'audio': ['de', 'en'], 'subtitles': ['fr']})

    def test_provider_fields(self):
        # Rakuten-like stream list, Plex Media/Part/Stream, Joyn 'languages', Crunchyroll locales
        rakuten = {'view_options': {'private': {'streams': [{'audio_languages': [{'id': 'ENG', 'abbr': 'en'}, {'id': 'DEU'}],
                                                             'subtitle_languages': [{'id': 'DEU'}]}]}}}
        self.assertEqual(languages.harvest(rakuten), {'audio': ['en', 'de'], 'subtitles': ['de']})
        plex = {'Media': [{'Part': [{'Stream': [{'streamType': 1}, {'streamType': 2, 'languageCode': 'eng'},
                                                {'streamType': 3, 'languageTag': 'de'}]}]}]}
        self.assertEqual(languages.harvest(plex), {'audio': ['en'], 'subtitles': ['de']})
        self.assertEqual(languages.harvest({'languages': [{'code': 'de'}, {'code': 'en'}]}, extra_audio=('languages',)),
                         {'audio': ['de', 'en']})
        self.assertEqual(languages.harvest({'languages': []}, extra_audio=('languages',)), {})
        self.assertEqual(languages.harvest({'title': 'x', 'genres': [{'name': 'Drama'}]}), {})
        self.assertEqual(languages.provider_row('crunchyroll', {'languages': 'dub,sub'}), {'audio': ['de'], 'subtitles': ['de']})
        self.assertEqual(languages.provider_row('youtube', {'language': 'Englisch'}), {'audio': ['en'], 'subtitles': []})


class ModelTests(unittest.TestCase):
    def test_unknown_is_unknown(self):
        m = languages.for_portal(None, 'pluto', {'id': 'p', 'title': 'Arrival'}, observed={}, name='Pluto TV')
        self.assertFalse(m['known'])
        self.assertEqual(m['short'], '')
        self.assertEqual(m['text'], 'unbekannt')
        self.assertEqual(m['rows'][0], ['Tonspuren', 'unbekannt'])

    def test_assumed_german_is_marked(self):
        m = languages.for_portal(None, 'joyn', {'id': 'j', 'title': 'Krimi'}, observed={}, name='Joyn')
        self.assertTrue(m['assumed'])
        self.assertEqual(m['short'], '')                      # no tile chip for a plain assumption
        self.assertIn(['Tonspuren', 'Deutsch (vermutlich)'], m['rows'])
        self.assertIn('nicht geprüft', m['rows'][-1][1])
        self.assertTrue(languages.matches(m, 'de'))

    def test_stream_wins_over_assumption(self):
        seen = {'stream': {'audio': ['en', 'de'], 'subtitles': ['de'], 'accessibility': [], 'checked': 1.7e9}}
        m = languages.for_portal(None, 'joyn', {'id': 'j', 'title': 'Krimi'}, observed=seen, name='Joyn')
        self.assertFalse(m['assumed'])
        self.assertEqual(m['short'], 'EN · DE · UT DE')
        self.assertTrue(m['rows'][-1][1].startswith('im Stream geprüft am '))
        self.assertTrue(languages.matches(m, 'en') and languages.matches(m, 'ut'))
        self.assertFalse(languages.matches(m, 'fr'))

    def test_mediathek_versions(self):
        rows = [{'channel': 'ARD', 'title': 'Der Film', 'url_subtitle': 'https://ard.example/ut.vtt'},
                {'channel': 'ARD', 'title': 'Der Film (OmU)'},
                {'channel': 'ARD', 'title': 'Der Film (Audiodeskription)'}]
        m = languages.for_mediathek(None, list(enumerate(rows)), {}, observed={})
        self.assertEqual([a['code'] for a in m['audio']], ['de', 'orig'])
        self.assertEqual([s['code'] for s in m['subtitles']], ['de'])
        self.assertTrue(m['original'])
        self.assertEqual(m['accessibility'], ['Audiodeskription'])
        self.assertEqual(languages.keys(m), {'de', 'orig', 'ov', 'ut'})
        # the original language named by the reference replaces "Originalton"
        m = languages.for_mediathek(None, list(enumerate(rows)), {'original_language': 'en'}, observed={})
        self.assertEqual([a['code'] for a in m['audio']], ['de', 'en'])
        fr = languages.for_mediathek(None, [('x', {'channel': 'ARTE.FR', 'title': 'Le Film'})], {}, observed={})
        self.assertEqual(fr['short'], 'FR')
        self.assertFalse(languages.matches(fr, 'de'))

    def test_series_union(self):
        a = languages.for_mediathek(None, [('a', {'channel': 'ZDF', 'title': 'Folge 1'})], {}, observed={})
        b = languages.for_mediathek(None, [('b', {'channel': 'ZDF', 'title': 'Folge 2 (OmU)'})], {}, observed={})
        s = languages.combine([a, b])
        self.assertEqual([x['code'] for x in s['audio']], ['de', 'orig'])
        self.assertIsNone(languages.combine([]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_remember_and_lookup(self):
        self.assertTrue(languages.remember(self.root, 'pluto', 'p1', {'audio': ['de', 'en']}))
        self.assertFalse(languages.remember(self.root, 'pluto', 'p2', {}))            # nothing named: nothing stored
        self.assertFalse(languages.remember(self.root, 'evil', 'p1', {'audio': ['de']}))
        self.assertFalse(languages.remember(self.root, 'pluto', 'x' * 500, {'audio': ['de']}))
        self.assertEqual(languages.lookup(self.root, 'pluto', ['p1', 'p2'])['p1']['stream']['audio'], ['de', 'en'])
        m = languages.for_portal(self.root, 'pluto', {'id': 'p1', 'title': 'Arrival'}, name='Pluto TV')
        self.assertEqual(m['short'], 'DE · EN')
        # a series page sees the episodes that were played
        s = languages.for_portal(self.root, 'pluto', {'id': 'series1', 'title': 'Serie'}, extra_ids=('p1',), name='Pluto TV')
        self.assertEqual([a['code'] for a in s['audio']], ['de', 'en'])

    def test_platform_store_hook(self):
        db = sqlite3.connect(str(self.root / 'plex.sqlite3'))
        try:
            self.assertEqual(languages.remember_from_db(db, 'plex', [{'id': 'm.1', 'languages': {'audio': ['en']}},
                                                                     {'id': 'm.2', 'languages': {}}]), 1)
            self.assertEqual(languages.remember_from_db(db, 'plex', [{'id': 'm.3'}]), 0)
        finally:
            db.close()
        self.assertEqual(languages.lookup(self.root, 'plex', ['m.1'])['m.1']['provider']['audio'], ['en'])

    def test_observe_hls_from_cache(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return MASTER, url
        found = languages.observe_hls(self.root, {'servustv': 'aa-123'}, 'https://cdn.example/lang-test.m3u8', fetch)
        self.assertEqual(found['audio'], ['de', 'en'])
        self.assertEqual(languages.lookup(self.root, 'servustv', ['aa-123'])['aa-123']['stream']['subtitles'], ['de'])
        self.assertEqual(languages.ref_key({'offer': 'o1'}), ('mediathek', 'o1'))
        self.assertIsNone(languages.ref_key({'job': '7'}))

    def test_real_platform_store(self):
        import pluto
        node = {'_id': '5f1a2b3c4d5e6f7a8b9c0d1e', 'name': 'Arrival', 'slug': 'arrival', 'type': 'movie',
                'audioLanguages': ['de', 'en']}
        item = pluto.item_from(node, 'movie')
        if item is None:
            self.skipTest('pluto.item_from erwartet andere Felder')
        self.assertEqual(item['languages'], {'audio': ['de', 'en']})


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        path = Path(self.dir.name) / 'catalog.db'

        @contextmanager
        def db():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    yield c
            finally:
                c.close()
        self.db = db
        self.old_root = languages.DEFAULT_ROOT
        languages.DEFAULT_ROOT = self.dir.name
        catalog.invalidate_listings(drop=True)
        self.saved = (catalog.LISTING_DB, catalog.LISTING_FILE)
        catalog.LISTING_DB, catalog.LISTING_FILE = None, None
        with db() as c:
            catalog.initialize(c)
            works = (('w0', 'Zebra', [('o0', {'title': 'Zebra', 'channel': 'ARD'})]),
                     ('w1', 'Le Mépris', [('o1', {'title': 'Le Mépris', 'channel': 'ARTE.FR'})]),
                     ('w2', 'Der Pate', [('o2', {'title': 'Der Pate', 'channel': 'ZDF', 'url_subtitle': 'https://z.example/ut.xml'}),
                                         ('o3', {'title': 'Der Pate (OmU)', 'channel': 'ZDF'})]))
            for wid, title, offers in works:
                c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,updated) VALUES(?,?,?,?,?,?,?,?)",
                          (wid, title, 'movie', 1972, '', json.dumps({'title': title, 'kind': 'movie', 'year': 1972}), 'matched', 1.0))
                for oid, payload in offers:
                    payload['url_video'] = 'https://example.org/%s.mp4' % oid
                    c.execute("INSERT INTO offers(id,work_id,payload,special,rank,seen,active) VALUES(?,?,?,?,?,?,1)",
                              (oid, wid, json.dumps(payload), '', 1, 1.0))
        unified_index.invalidate()

    def tearDown(self):
        languages.DEFAULT_ROOT = self.old_root
        catalog.LISTING_DB, catalog.LISTING_FILE = self.saved
        catalog.invalidate_listings(drop=True)
        unified_index.invalidate()
        self.dir.cleanup()

    def test_item_carries_languages(self):
        with self.db() as c:
            item = catalog.item(c, c.execute("SELECT * FROM works WHERE id='w2'").fetchone())
        self.assertEqual(item['languages']['short'], 'DE · OV · UT DE')
        self.assertIn(['Untertitel', 'Deutsch'], item['languages']['rows'])

    def test_unified_filter_and_chip(self):
        modules = {'pluto': _Portal([{'id': 'p1', 'kind': 'movie', 'title': 'Alpha', 'year': 1999},
                                     {'id': 'p2', 'kind': 'movie', 'title': 'Beta (OmU)', 'year': 2001}])}
        languages.remember(self.dir.name, 'pluto', 'p1', {'audio': ['en']})
        page = unified_index.page(self.dir.name, self.db, modules=modules)
        self.assertEqual(page['total'], 5)
        chips = {i['title']: [o['item'].get('lang') for o in i['offers']] for i in page['items']}
        self.assertEqual(chips['Alpha'], ['EN'])
        self.assertEqual(chips['Le Mépris'], ['FR'])
        self.assertEqual(chips['Zebra'], [''])                      # assumed German: no chip
        titles = lambda lang, only='': [i['title'] for i in unified_index.page(self.dir.name, self.db, modules=modules, language=lang, only=only)['items']]
        self.assertEqual(titles('de'), ['Der Pate', 'Zebra'])
        self.assertEqual(titles('fr'), ['Le Mépris'])
        self.assertEqual(titles('en'), ['Alpha'])
        self.assertEqual(titles('ov'), ['Beta (OmU)', 'Der Pate'])
        self.assertEqual(titles('ut'), ['Beta (OmU)', 'Der Pate'])
        self.assertEqual(titles('ov', only='pluto'), ['Beta (OmU)'])
        self.assertEqual(titles('drop table'), titles(''))          # unknown filter = no filter


class _Portal:
    def __init__(self, rows):
        self.rows = rows

    def listing(self, root, view='movies', query='', offset=0, limit=60, genre='', sort='title', collection=''):
        kind = 'series' if view == 'series' else 'movie'
        rows = [dict(r) for r in self.rows if r['kind'] == kind]
        return {'items': rows, 'total': len(rows), 'genre_counts': []}


class WiringTests(unittest.TestCase):
    def test_page_and_server(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("@ROUTES.post('/api/language-observe')", server)
        self.assertIn('languages.observe_hls(ROOT', server)
        self.assertIn('languages.DEFAULT_ROOT=ROOT', server)
        self.assertIn("api('language-observe'", (ROOT / 'web' / 'player.js').read_text(encoding='utf-8'))
        self.assertIn('AtlasLanguages.rows(item.languages)', (ROOT / 'web' / 'titleview.js').read_text(encoding='utf-8'))
        self.assertIn('AtlasLanguages.rows(m.languages)', (ROOT / 'web' / 'portal_title.js').read_text(encoding='utf-8'))
        self.assertIn('id="atlas-cross-lang"', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn("'languages.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        for mod in ('pluto', 'rakuten', 'joyn', 'toggo', 'plex', 'rtlplus'):
            text = (ROOT / (mod + '.py')).read_text(encoding='utf-8')
            self.assertIn('languages.harvest(', text, mod)
            self.assertIn("languages.remember_from_db(db, '%s'" % mod, text, mod)


if __name__ == '__main__':
    unittest.main()
