"""0.6.99 (Björn, 22.11.2026): Kinderecke nach Altersfreigabe, Grenze einstellbar, „im Zweifel nicht“, Freigabe durch
die Eltern (kids_rules.py)."""
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog, categories, kids_catalog, kids_rules, unified_index  # noqa: E402
from _wiring import routed, SERVER  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate(); kids_catalog._EPISODES_SEEN.clear(); unified_index.invalidate()
        catalog.kids_signal_invalidate(); catalog.invalidate_listings(drop=True)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); self.path = self.root / 'catalog.db'
        with self.db() as c:
            catalog.initialize(c); kids_rules.ensure(c)
        old = catalog.LISTING_DB; catalog.LISTING_DB = self.db
        self.addCleanup(setattr, catalog, 'LISTING_DB', old)
        self.addCleanup(setattr, categories, 'KIDS_MAX_AGE', categories.KIDS_MAX_AGE)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add(self, wid, title, genres, kind='movie', show=None, state='matched', ref=None, channel='Das Erste', topic='', episode=None):
        meta = {'title': title if kind == 'movie' else (show or title), 'kind': kind, 'genres': genres}
        if ref:
            meta['reference_id'] = ref
        if kind == 'series':
            meta.update(season=1, episode=episode, episode_title=title)
        with self.db() as c:
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts) VALUES(?,?,?,?,?,?,?,1)",
                      (wid, meta['title'], kind, 2015, show or wid, json.dumps(meta), state))
            c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)",
                      ('o-' + wid, wid, json.dumps({'title': title, 'channel': channel, 'topic': topic, 'duration': 1500,
                                                    'url_video': 'https://example.org/%s.mp4' % wid})))
            for g in genres:
                c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))

    def ages(self, **refs):
        with self.db() as c:
            kids_rules.store(c, list(refs), {k: v for k, v in refs.items() if v is not None})

    def titles(self):
        kids_catalog.invalidate(); unified_index.invalidate(); catalog.invalidate_listings(drop=True)
        for _ in range(100):
            d = kids_catalog.build(self.root, self.db, modules={})
            if not d['pending']:
                return sorted(t['title'] for t in d['movies'] + d['series'])
            time.sleep(0.1)
        self.fail('Katalog wurde nicht fertig')


class RuleTests(Base):
    def test_rule(self):
        self.add('bibi', 'Bibi & Tina', ['Familie', 'Komödie'], ref='tt1000001')          # FSK 0 → hinein (IMDb Family)
        self.add('zwoelf', 'Das Märchen von den zwölf Monaten', ['Familie', 'Fantasy'], ref='tt1000002')  # FSK 6 → hinein
        self.add('ohne', 'Fantasyfilm ohne FSK', ['Familie', 'Fantasy'], ref='tt1000003')              # keine FSK → wartet
        self.add('zwoelfer', 'Abenteuer ab 12', ['Familie', 'Abenteuer'], ref='tt1000004')   # FSK 12 → nein (Grenze 6)
        self.add('pilcher', 'Liebe in Cornwall', ['Romantik', 'Drama'], ref='tt1000005')     # FSK 0, Romantik → nein
        self.add('krimi', 'Krimi FSK 6', ['Krimi'], ref='tt1000006')                          # Sicherheitsnetz
        self.add('kika', 'KiKA-Film', ['Abenteuer'], channel='KiKA', ref='tt1000007')        # KiKA → immer
        self.add('kika12', 'KiKA-Film ab 12', ['Abenteuer'], channel='KiKA', ref='tt1000008') # KiKA, aber FSK über Grenze → nein
        self.add('arrival', 'Arrival', ['Drama', 'Science-Fiction'], ref='tt1000009')           # FSK 12, kein Kinder-Hinweis → nein
        self.add('kikakrimi', 'Pfefferkörner', ['Krimi'], channel='KiKA', state='retry')     # KiKA: auch ohne Erkennung, ohne Genre-Netz
        self.add('reihe', 'Unerkannter Märchenfilm', [], topic='Sechs auf einen Streich', state='retry')   # Reihe, nicht erkannt → wartet
        self.ages(tt1000001=0, tt1000002=6, tt1000003=None, tt1000004=12, tt1000005=0, tt1000006=6, tt1000008=12, tt1000009=0)
        with self.db() as c:
            self.assertEqual(kids_rules.max_age(c), 12)                                     # Björns Standard
        self.assertEqual(self.titles(), ['Abenteuer ab 12', 'Bibi & Tina', 'Das Märchen von den zwölf Monaten', 'KiKA-Film', 'KiKA-Film ab 12', 'Pfefferkörner'])
        with self.db() as c:
            kids_rules.set_max_age(c, 6)
        self.assertEqual(self.titles(), ['Bibi & Tina', 'Das Märchen von den zwölf Monaten', 'KiKA-Film', 'Pfefferkörner'])
        with self.db() as c:
            kids_rules.set_max_age(c, 0)
        self.assertEqual(self.titles(), ['Bibi & Tina', 'KiKA-Film', 'Pfefferkörner'])
        with self.assertRaises(ValueError):
            with self.db() as c:
                kids_rules.set_max_age(c, 16)

    def test_parents_allow_and_block(self):
        self.add('unerkannt', 'Unerkannter Kinderfilm', [], topic='Kinderfilme', state='retry')
        self.add('bibi', 'Bibi & Tina', ['Familie', 'Fantasy'], ref='tt1000001')
        self.add('e1', 'Folge 1', [], kind='series', show='show:x', state='retry', topic='Kinderserien', episode=1)
        self.add('e2', 'Folge 2', [], kind='series', show='show:x', state='retry', topic='Kinderserien', episode=2)
        self.ages(tt1000001=0)
        with self.db() as c:
            waiting = kids_rules.waiting(c)
        self.assertEqual({(w['kind'], w['id'], w['reason']) for w in waiting},
                         {('work', 'unerkannt', 'Nicht erkannt'), ('show', 'show:x', 'Nicht erkannt')})
        with self.db() as c:
            kids_rules.choose(c, 'work', 'unerkannt', 'allow', 'Unerkannter Kinderfilm')
            kids_rules.choose(c, 'show', 'show:x', 'allow', 'Serie X')
            kids_rules.choose(c, 'work', 'bibi', 'block', 'Bibi & Tina')
            self.assertEqual(kids_rules.waiting(c), [])
        self.assertEqual(self.titles(), ['Unerkannter Kinderfilm', 'show:x'])
        data = kids_catalog.build(self.root, self.db, modules={})
        with self.db() as c:
            self.assertEqual(len(kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:x')['episodes']), 2)
            kids_rules.choose(c, 'work', 'e2', 'block')
            self.assertEqual(len(kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:x')['episodes']), 1)
            kids_rules.choose(c, 'work', 'bibi', '')
            self.assertEqual([x['id'] for x in kids_rules.choices(c)], ['e2', 'show:x', 'unerkannt'])
        self.assertIn('Bibi & Tina', self.titles())
        with self.assertRaises(ValueError):
            with self.db() as c:
                kids_rules.choose(c, 'other', 'x', 'allow')

    def test_waiting_reasons(self):
        self.add('ohne', 'Fantasy ohne FSK', ['Fantasy'], ref='tt1000003')
        self.add('hoch', 'Abenteuer ab 12', ['Abenteuer'], ref='tt1000004')
        self.add('neu', 'Familienfilm noch nicht gesucht', ['Familie'], ref='tt1000009')
        self.add('krimi', 'Familienkrimi', ['Familie', 'Krimi'], ref='tt1000010')   # Sicherheitsnetz: gar nicht anbieten
        self.add('fanta', 'Fantasy ab 6', ['Fantasy', 'Abenteuer'], ref='tt1000011')  # 0.6.105: FSK passt, kein Familiensignal
        self.ages(tt1000003=None, tt1000004=12, tt1000011=6)
        with self.db() as c:
            kids_rules.set_max_age(c, 6)
            reasons = {w['title']: w['reason'] for w in kids_rules.waiting(c)}
        self.assertEqual(reasons, {'Fantasy ohne FSK': 'Keine Altersfreigabe bekannt', 'Abenteuer ab 12': 'FSK 12 (über der Grenze)',
                                   'Familienfilm noch nicht gesucht': 'Altersfreigabe wird noch gesucht',
                                   'Fantasy ab 6': 'FSK 6, aber kein Familien- oder Kinderhinweis'})


class FetchTests(Base):
    def test_fetch_round_batches_and_stores(self):
        for i in range(5):
            self.add('m%d' % i, 'Film %d' % i, ['Familie'] if i < 2 else ['Drama'], ref='tt200000%d' % i)
        self.add('x', 'Ohne Kennung', ['Familie'])
        self.add('offen', 'Nicht erkannt', ['Familie'], state='retry', ref='tt2999999')
        asked = []

        def query(refs, version):
            asked.append(list(refs))
            return {'tt2000000': 6, 'tt2000000#label': 'FSK 6', 'tt2000003': 16}
        old = kids_rules.BATCH; kids_rules.BATCH = 2; self.addCleanup(setattr, kids_rules, 'BATCH', old)
        kids_rules._PAUSE[0] = 0
        n = kids_rules.fetch_round(self.db, query=query, gap=0)
        self.assertEqual(n, 5)
        self.assertEqual(asked[0], ['tt2000000', 'tt2000001'])          # Kinder-Hinweis zuerst
        self.assertNotIn('tt2999999', sum(asked, []))
        with self.db() as c:
            rows = dict(c.execute('SELECT ref,age FROM reference_ages').fetchall())
            self.assertEqual(rows['tt2000000'], 6); self.assertEqual(rows['tt2000003'], 16); self.assertIsNone(rows['tt2000001'])
            self.assertEqual(kids_rules.summary(c)['with_age'], 2)
        self.assertEqual(kids_rules.fetch_round(self.db, query=query, gap=0), 0)   # frisch geprüft: nichts mehr

    def test_error_pauses(self):
        self.add('m', 'Film', ['Familie'], ref='tt3000000')
        kids_rules._PAUSE[0] = 0
        self.addCleanup(lambda: kids_rules._PAUSE.__setitem__(0, 0))

        def boom(refs, version):
            raise OSError('HTTP 429')
        self.assertEqual(kids_rules.fetch_round(self.db, query=boom, gap=0), 0)
        self.assertGreater(kids_rules._PAUSE[0], time.time())
        self.assertEqual(kids_rules.fetch_round(self.db, query=lambda r, v: {}, gap=0), 0)


class PortalTests(unittest.TestCase):
    def test_portal_age_counts_for_all_categories(self):
        old = categories.KIDS_MAX_AGE
        self.addCleanup(setattr, categories, 'KIDS_MAX_AGE', old)
        categories.KIDS_MAX_AGE = 6
        self.assertIn('Kinder', categories.classify(['Familie', 'Fantasy'], [], True, age='FSK 6'))
        self.assertNotIn('Kinder', categories.classify(['Fantasy'], [], True, age='FSK 6'))   # 0.6.105: Familie nötig
        # FSK allein reicht nicht: Drama/Science-Fiction/Komödie ab 0 oder 12 (Arrival) bleibt draußen
        self.assertNotIn('Kinder', categories.classify(['Komödie'], [], True, age=0))
        self.assertNotIn('Kinder', categories.classify(['Drama', 'Science-Fiction'], [], True, age=0))
        self.assertNotIn('Kinder', categories.classify(['Familie', 'Fantasy'], [], True, age='FSK 12'))
        self.assertNotIn('Kinder', categories.classify(['Romantik'], [], True, age=0))
        self.assertNotIn('Kinder', categories.classify(['Krimi'], [], True, age=0))
        self.assertEqual(categories.classify(['Fantasy'], [], False, age=0), [categories.UNCLASSIFIED])
        categories.KIDS_MAX_AGE = 12
        self.assertIn('Kinder', categories.classify(['Familie', 'Fantasy'], [], True, age='FSK 12'))


class LiveTests(unittest.TestCase):
    def test_only_kids_stations_with_own_playback(self):
        import live_tv
        stations = [
            {'key': 'kika', 'name': 'KiKA', 'group': 'Öffentlich-rechtlich', 'logo': 'https://x/kika.png', 'summary': '',
             'sources': [{'provider_name': 'ARD, ZDF & Co.', 'title': 'KiKA Livestream', 'play': {'offer': 'o-kika'}}]},
            {'key': 'plutokids', 'name': 'Pluto TV Kids', 'group': 'Kinder & Familie', 'logo': '', 'summary': '',
             'sources': [{'provider_name': 'Pluto TV', 'title': 'Pluto TV Kids', 'play': {'pluto': 'abc123456'}}]},
            {'key': 'familienkino', 'name': 'Familienkino', 'group': 'Filme', 'logo': '', 'summary': '',
             'sources': [{'provider_name': 'Samsung TV Plus', 'title': 'Familienkino', 'play': {'samsung': 'DE1'}}]},
            {'key': 'animetv', 'name': 'Anime Kids TV', 'group': 'Kids', 'logo': '', 'summary': '',
             'sources': [{'provider_name': 'Pluto TV', 'title': 'Anime', 'play': {'pluto': 'anime12345'}}]},
            {'key': 'joynkids', 'name': 'Joyn Kids', 'group': 'Kids', 'logo': '', 'summary': '',
             'sources': [{'provider_name': 'Joyn', 'title': 'Kids', 'play': None, 'link': 'https://joyn.de/x'}]},
            {'key': 'zdf', 'name': 'ZDF', 'group': 'Öffentlich-rechtlich', 'logo': '', 'summary': '',
             'sources': [{'provider_name': 'ARD, ZDF & Co.', 'title': 'ZDF Livestream', 'play': {'offer': 'o-zdf'}}]}]
        old = live_tv.overview
        live_tv.overview = lambda c, root, **kw: {'stations': [dict(s, sources=[dict(x) for x in s['sources']]) for s in stations]}
        self.addCleanup(setattr, live_tv, 'overview', old)
        got = kids_catalog.live(None, '/r')
        self.assertEqual([s['title'] for s in got], ['KiKA', 'Pluto TV Kids', 'Familienkino'])
        self.assertEqual(got[0]['ref'], {'offer': 'o-kika'})
        self.assertTrue(kids_catalog.allowed_ref({'movies': [], 'series': []}, {'pluto': 'abc123456'}))
        self.assertTrue(kids_catalog.allowed_ref({'movies': [], 'series': []}, {'samsung': 'DE1'}))
        self.assertFalse(kids_catalog.allowed_ref({'movies': [], 'series': []}, {'offer': 'o-zdf'}))
        self.assertFalse(kids_catalog.allowed_ref({'movies': [], 'series': []}, {'pluto': 'anime12345'}))


class WiringTests(unittest.TestCase):
    def test_routes_and_ui(self):
        self.assertTrue(routed('/api/kids-rules', 'GET'))
        self.assertTrue(routed('/api/kids-rules', 'POST'))
        self.assertTrue(routed('/api/kids-live', 'GET'))
        self.assertIn('id="kids-live-toggle"', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn("'/kids_parents.js'", SERVER)
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="kids-parents-panel"', html)
        self.assertIn('id="kids-max-age"', html)


if __name__ == '__main__':
    unittest.main()


class SeriesRuleTests(unittest.TestCase):
    """0.6.99 auf 0.6.98: KiKA-Krimiserie bleibt (KiKA immer), Elternfreigabe öffnet auch eine sonst gesperrte Reihe."""
    def test_kika_and_parent_allowed_series(self):
        from test_v0691_kinderecke import Base

        class T(Base):
            def runTest(self):
                pass
        t = T()
        t.setUp()
        try:
            for i in range(4):
                t.add('pf%d' % i, 'Pfefferkörner %d' % i, ['Krimi'], kind='series', show='show:pf', channel='KiKA', state='identified', episode=i + 1)
                t.add('nw%d' % i, 'Kinderreporter %d' % i, ['Nachrichten'], kind='series', show='show:news', episode=i + 1)
            with t.db() as c:
                c.execute("UPDATE works SET meta=json_set(meta,'$.title','Nachrichten für alle') WHERE show_key='show:news'")
            self.assertEqual(sorted(x['series']['show'] for x in t.shelf()['series']), ['show:pf'])
            with t.db() as c:
                kids_rules.choose(c, 'show', 'show:news', 'allow', 'Nachrichten für alle')
            catalog.invalidate_listings(drop=True); unified_index.invalidate(); kids_catalog.invalidate()
            data = t.shelf()
            self.assertEqual(sorted(x['series']['show'] for x in data['series']), ['show:news', 'show:pf'])
            with t.db() as c:
                self.assertEqual(len(kids_catalog.episodes(t.root, c, data, 'mediatheken', 'show:pf')['episodes']), 4)
                self.assertEqual(len(kids_catalog.episodes(t.root, c, data, 'mediatheken', 'show:news')['episodes']), 4)
        finally:
            t.doCleanups()
