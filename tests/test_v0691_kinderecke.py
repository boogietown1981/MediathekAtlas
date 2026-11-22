"""0.6.91 (Björn, 22.11.2026): Kinderecke zeigte erkannte Märchen nicht, Serien waren leer, Reihen ließen sich
nicht weiter nach rechts blättern.

Ursachen:
* Erkannte Filme tragen nur die Referenz-Genres; IMDb kennt kein „Kinder“ (Märchenfilm = „Family, Fantasy“).
  Sender (KiKA) und Kinder-/Märchenreihen des Angebots zählen jetzt als eindeutiges Signal.
* Jede Serienfolge musste selbst unter „Kinder“ stehen; Folgen ohne eigenen Abgleich fielen heraus.
* Die Liste endete nach 240 Titeln je Art (nach Titel sortiert, Märchen mit „D…“/„S…“ kamen nie an).
* Reihen hatten keine Pfeilknöpfe und endeten nach 40 Kacheln ohne Weg zur ganzen Liste.
"""
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
import catalog, categories, kids_catalog, unified_index  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate()
        kids_catalog._EPISODES_SEEN.clear()
        unified_index.invalidate()
        getattr(catalog, "kids_signal_invalidate", lambda: None)()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'catalog.db'
        with self.db() as c:
            catalog.initialize(c)
        old = catalog.LISTING_DB
        catalog.LISTING_DB = self.db
        self.addCleanup(setattr, catalog, 'LISTING_DB', old)
        self.addCleanup(getattr(catalog, "kids_signal_invalidate", lambda: None))

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add(self, wid, title, genres, kind='movie', show=None, state='matched', attempts=1, season=None, episode=None,
            channel='Das Erste', topic='', work_topic=None):
        meta = {'title': title if kind == 'movie' else (show or title), 'kind': kind, 'genres': genres}
        if kind == 'series':
            meta.update(season=season, episode=episode, episode_title=title)
        with self.db() as c:
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts,topic) VALUES(?,?,?,?,?,?,?,?,?)",
                      (wid, meta['title'], kind, 2015, show or wid, json.dumps(meta), state, attempts,
                       topic if work_topic is None else work_topic))
            c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)",
                      ('o-' + wid, wid, json.dumps({'title': title, 'channel': channel, 'topic': topic, 'duration': 1500,
                                                    'url_video': 'https://example.org/%s.mp4' % wid})))
            for g in genres:
                c.execute('INSERT INTO work_genres VALUES(?,?)', (wid, g))

    def shelf(self):
        for _ in range(100):
            data = kids_catalog.build(self.root, self.db, modules={})
            if not data['pending']:
                return data
            time.sleep(0.1)
        self.fail('Katalog wurde nicht fertig')


class MaerchenTests(Base):
    def test_recognized_fairy_tales_and_kika_films_are_kids(self):
        # „Sechs auf einen Streich“: erkannt als IMDb „Family, Fantasy“; Werk nach Zusammenführung ohne works.topic
        self.add('gaensemagd', 'Die Gänsemagd', ['Familie', 'Fantasy'], topic='Sechs auf einen Streich', work_topic='')
        self.add('topicquelle', 'Anderer Film der Reihe', ['Familie'], topic='Sechs auf einen Streich')
        self.add('perle', 'Schneewittchen', ['Fantasy'], channel='ZDF', topic='Märchenperlen')
        self.add('kika', 'Ein KiKA-Film', ['Abenteuer'], channel='KiKA', topic='Filme')
        self.add('label', 'Wikidata-Märchen', ['Märchenfilm'])
        self.add('harry', 'Zauberschüler', ['Familie', 'Fantasy', 'Abenteuer'])        # kein Kinder-Signal
        self.add('kikakrimi', 'Krimi auf KiKA', ['Krimi'], channel='KiKA')             # 0.6.99: KiKA immer (Björn)
        self.add('doku', 'Märchenhafte Landschaften', ['Dokumentation'], topic='Märchenhafte Landschaften')
        self.add('offen', 'Ungeprüfter Märchenfilm', [], state='pending', attempts=0, topic='Sechs auf einen Streich')
        data = self.shelf()
        self.assertEqual(sorted(t['title'] for t in data['movies']),
                         ['Anderer Film der Reihe', 'Die Gänsemagd', 'Ein KiKA-Film', 'Krimi auf KiKA', 'Schneewittchen', 'Wikidata-Märchen'])

    def test_category_label_and_topic_rule(self):
        self.assertIn('Kinder', categories.of_label('Märchenfilm'))
        self.assertNotIn('Kinder', categories.of_label('Märchen'))
        for topic in ('Sechs auf einen Streich', 'Märchenperlen', 'Kinderfilme', 'Filme für Kinder', 'Unser Sandmännchen'):
            self.assertTrue(catalog.KIDS_TOPIC.search(topic), topic)
        for topic in ('Kinder der Utopie', 'Kinderärzte im Einsatz', 'Märchenhafte Landschaften', 'Tatort'):
            self.assertFalse(catalog.KIDS_TOPIC.search(topic), topic)


class SeriesTests(Base):
    def test_unchecked_episodes_of_a_kids_series_are_listed(self):
        self.add('e1', 'Folge mit Referenz', ['Familie', 'Animation'], kind='series', show='show:hase', season=1, episode=1)
        self.add('e2', 'Folge ohne Abgleich', [], kind='series', show='show:hase', season=1, episode=2, state='pending', attempts=0)
        self.add('e3', 'Folge nur Animation', ['Animation'], kind='series', show='show:hase', season=1, episode=3, state='identified')
        self.add('e4', 'Folge mit Krimi', ['Krimi'], kind='series', show='show:hase', season=1, episode=4)
        # 0.6.98: die Reihe muss selbst Kinderprogramm sein (≥ 80 % der eingeordneten Folgen)
        for n in (5, 6, 7):
            self.add('e%d' % n, 'Weitere Folge %d' % n, ['Kinder'], kind='series', show='show:hase', season=1, episode=n)
        self.add('k1', 'KiKA-Folge', [], kind='series', show='show:kika', channel='KiKA', state='identified')
        # 0.6.99 (Björn: „nicht identifiziert → im Zweifel nicht“, aber „alles von KiKA oder TOGGO freigeben“):
        # nicht erkannte KiKA-Serie kommt hinein, nicht erkannte Serie aus einer Kinderreihe wartet auf Freigabe
        self.add('k2', 'Unerkannte KiKA-Folge', [], kind='series', show='show:kika2', channel='KiKA', state='retry', attempts=2)
        self.add('r1', 'Unerkannte Reihenfolge', [], kind='series', show='show:reihe', topic='Kinderserien', state='retry', attempts=2)
        data = self.shelf()
        self.assertEqual(sorted(t['series']['show'] for t in data['series']), ['show:hase', 'show:kika', 'show:kika2'])
        with self.db() as c:
            eps = kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:hase')
            self.assertEqual([e['episode'] for e in eps['episodes']], [1, 2, 3, 5, 6, 7])
            self.assertEqual(len(kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:kika')['episodes']), 1)
        self.assertFalse(kids_catalog.allowed_ref(data, {'offer': 'o-e4'}))
        self.assertTrue(kids_catalog.allowed_ref(data, {'offer': 'o-e2'}))


class LimitTests(unittest.TestCase):
    def test_list_is_not_cut_after_240_titles(self):
        entries = [{'offers': [{'source': 'pluto', 'item': {'id': 'pluto-%04d' % i, 'title': 'Film %04d' % i, 'kind': 'movie',
                                                              'playable': 1}}]} for i in range(700)]

        def page(root, db, kind='movies', genre='', offset=0, **kw):
            rows = entries if kind == 'movies' else []
            return {'items': rows[offset:offset + 48], 'total': len(rows), 'pending': []}
        data = kids_catalog.build('/r', None, page=page)
        self.assertEqual(len(data['movies']), 700)
        self.assertGreaterEqual(kids_catalog.MAX_TITLES, 1000)


class UiTests(unittest.TestCase):
    def test_rows_have_arrows_and_show_all_tile(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        css = (ROOT / 'web' / 'kids.css').read_text(encoding='utf-8')
        self.assertIn("function scroller(", js)
        self.assertIn("kids-arrow", css)
        self.assertIn("moreTile(", js)
        self.assertIn("scroller(host, 'kids-chips-scroller')", js)


if __name__ == '__main__':
    unittest.main()
