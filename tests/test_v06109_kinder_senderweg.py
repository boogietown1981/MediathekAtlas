"""0.6.109 (Mac-Prüfung 0.6.106, 23.11.2026): Kindersender je Folge, Livestreams nie in Filme/Serien, Altersgrenze für
alle Quellen.

Befunde: Reihe „Livestream“ (ARD/ZDF/PHOENIX/ORF … und ein „KiKA Livestream“) stand in der Kinderecke und spielte
„ARD Livestream“; „WUMMS“ (2 von 176 KiKA), „Sportschau“ (121 von 2.056 KiKA), „POV · Deine Geschichte zählt“ (27 KiKA,
61 WDR, Folge „Suizidgedanken“), „#Ukraine · Mein Land im Krieg“ (13 KiKA, 20 rbtv), „Young Crime“ (24 KiKA, 34 ZDF)
öffneten alle Folgen. Grenze FSK 6 ließ Netzkino-Filme mit FSK 12 stehen; Pluto-Familienserien kamen über den
Altersweg; Live-Sender „Eine schrecklich nette Familie“, „Eine himmlische Familie“ galten als Kindersender.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import categories, kids_catalog, kids_rules  # noqa: E402
from test_v0699_kinder_freigabe import Base  # noqa: E402
from test_v0646_kids_catalog import fake_page, portal  # noqa: E402


class Mixed(Base):
    def series(self, show, title, parts):
        """parts: [(Anzahl, Sender, Genres, Folgentitel-Muster)]"""
        n = 0
        for count, channel, genres, pattern in parts:
            for i in range(count):
                n += 1
                self.add('%s-%d' % (show, n), pattern % n, genres, kind='series', show=show, state='format', channel=channel,
                         topic=title, episode=n)
        with self.db() as c:
            c.execute("UPDATE works SET title=?, meta=json_set(meta,'$.title',?) WHERE show_key=?", (title, title, show))

    def data(self):
        kids_catalog.invalidate()
        import unified_index, catalog
        unified_index.invalidate(); catalog.invalidate_listings(drop=True)
        import time
        for _ in range(100):
            d = kids_catalog.build(self.root, self.db, modules={})
            if not d['pending']:
                return d
            time.sleep(0.1)
        self.fail('Katalog wurde nicht fertig')

    def episodes(self, d, show):
        with self.db() as c:
            try:
                return [(e['title'], e['channel']) for e in kids_catalog.episodes(self.root, c, d, 'mediatheken', show)['episodes']]
            except ValueError:
                return None


class ChannelPerEpisode(Mixed):
    def test_mixed_series_show_only_kids_channel_episodes(self):
        self.series('show:wumms', 'WUMMS', [(2, 'KiKA', ['Kinder'], 'KiKA-Folge %d'),
                                            (20, 'ARD', [], 'EM gucken mit Borussia Hodenhagen %d')])
        self.series('show:pov', 'POV · Deine Geschichte zählt', [(3, 'KiKA', [], 'Mut %d'), (6, 'WDR', [], 'Suizidgedanken %d')])
        self.series('show:ukraine', '#Ukraine · Mein Land im Krieg', [(2, 'KiKA', [], 'Tagebuch %d'), (3, 'rbtv', [], 'Front %d')])
        self.series('show:young', 'Young Crime', [(2, 'KiKA', [], 'Folge %d'), (3, 'ZDF', ['Krimi'], 'Tatort Schule %d')])
        d = self.data()
        shows = {t['series']['show']: t for t in d['series']}
        self.assertEqual(self.episodes(d, 'show:wumms'), [('KiKA-Folge 1', 'KiKA'), ('KiKA-Folge 2', 'KiKA')])
        self.assertEqual(self.episodes(d, 'show:pov'), [('Mut %d' % i, 'KiKA') for i in (1, 2, 3)])
        self.assertEqual({ch for _, ch in self.episodes(d, 'show:young')}, {'KiKA'})
        self.assertEqual(shows['show:wumms']['basis'], 'gemischt')
        # „#Ukraine · Mein Land im Krieg“ trägt ein Sperrwort; die Reihe bleibt nur über Kindersender-Folgen sichtbar
        eps = self.episodes(d, 'show:ukraine')
        self.assertTrue(eps is None or {ch for _, ch in eps} == {'KiKA'}, eps)

    def test_sports_name_stays_out_despite_kika(self):
        self.series('show:sport', 'Sportschau', [(3, 'KiKA', ['Kinder'], 'Sport für Kinder %d'), (20, 'ARD', [], 'Bundesliga %d')])
        self.assertNotIn('show:sport', [t['series']['show'] for t in self.data()['series']])

    def test_whole_kika_series_and_known_series_unchanged(self):
        self.series('show:kikalive', 'KiKA LIVE', [(4, 'KiKA', [], 'Ausgabe %d')])
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', [], 'Maus %d')])
        d = self.data()
        self.assertEqual(len(self.episodes(d, 'show:kikalive')), 4)
        self.assertEqual(len(self.episodes(d, 'show:maus')), 3)


class LiveStreams(Mixed):
    def live(self, wid, title, channel):
        import json
        with self.db() as c:
            c.execute("INSERT INTO works(id,title,kind,year,show_key,meta,state,attempts,topic) VALUES(?,?,?,NULL,?,?,?,0,?)",
                      (wid, 'Livestream', 'other', 'show:live', json.dumps({'title': 'Livestream', 'kind': 'other', 'live': True}),
                       'format', 'Livestream'))
            c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,1)",
                      ('o-' + wid, wid, json.dumps({'title': title, 'channel': channel, 'topic': 'Livestream', 'duration': 0,
                                                    'url_video': 'https://example.org/%s.m3u8' % wid})))

    def test_livestream_never_in_lists_or_playable(self):
        for wid, title, ch in (('ard', 'ARD Livestream', 'ARD'), ('zdfinfo', 'ZDF.info Livestream', 'ZDFinfo'),
                               ('kika', 'KiKA Livestream', 'KiKA')):
            self.live(wid, title, ch)
        d = self.data()
        self.assertEqual(d['movies'] + d['series'], [])
        kids_catalog._EPISODES_SEEN.update({('mediatheken', 'o-ard'), ('mediatheken', 'o-zdfinfo')})
        with self.db() as c:
            self.assertFalse(kids_catalog.allowed_ref(d, {'offer': 'o-ard'}, c))
            self.assertFalse(kids_catalog.allowed_ref(d, {'offer': 'o-zdfinfo'}, c))
            self.assertFalse(kids_catalog.offer_allowed(c, 'o-kika'))
            self.assertFalse(kids_catalog.work_allowed(c, 'kika'))

    def test_play_checks_per_work(self):
        self.series('show:wumms', 'WUMMS', [(1, 'KiKA', ['Kinder'], 'KiKA-Folge %d'), (5, 'ARD', [], 'Faking Katar %d')])
        d = self.data()
        with self.db() as c:
            self.assertTrue(kids_catalog.offer_allowed(c, 'o-show:wumms-1'))
            self.assertTrue(kids_catalog.work_allowed(c, 'show:wumms-1'))
            self.assertFalse(kids_catalog.work_allowed(c, 'show:wumms-3'))      # ARD-Folge der gemischten Reihe
            kids_catalog._EPISODES_SEEN.add(('mediatheken', 'o-show:wumms-3'))   # auch wenn einmal ausgeliefert
            self.assertFalse(kids_catalog.allowed_ref(d, {'offer': 'o-show:wumms-3'}, c))


class LiveStations(unittest.TestCase):
    def test_family_sitcom_channels_are_no_kids_stations(self):
        import live_tv
        for name in ('Eine schrecklich nette Familie', 'Eine himmlische Familie'):
            self.assertFalse(live_tv.KIDS_LIVE.search(name), name)
        for name in ('KiKA', 'Pluto TV Kids', 'Familienkino', 'Toggo plus', 'Nick Jr.'):
            self.assertTrue(live_tv.KIDS_LIVE.search(name), name)


class Platforms(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate()
        self.addCleanup(setattr, categories, 'KIDS_MAX_AGE', categories.KIDS_MAX_AGE)

    def build(self, entries):
        return kids_catalog.build('/r', None, page=fake_page(entries))

    def test_age_limit_applies_to_platform_catalogs(self):
        movies = [{'cats': ['Kinder'], 'offers': [portal('netzkino', 'a' * 32, 'Run The Race', fsk=12)]},
                  {'cats': ['Kinder'], 'offers': [portal('netzkino', 'b' * 32, 'Die Bockreiter 1', fsk=12)]},
                  {'cats': ['Kinder'], 'offers': [portal('plex', 'p12', 'The Adventures of Aladdin', content_rating='de/12')]},
                  {'cats': ['Kinder'], 'offers': [portal('netzkino', 'c' * 32, 'Rabe', fsk=0)]}]
        categories.KIDS_MAX_AGE = 6
        self.assertEqual([t['title'] for t in self.build({'movies': movies})['movies']], ['Rabe'])
        categories.KIDS_MAX_AGE = 12
        self.assertEqual(len(self.build({'movies': movies})['movies']), 4)

    def test_family_series_for_adults_not_via_age(self):
        series = [{'cats': ['Kinder'], 'offers': [portal('pluto', 'pl-%d' % i, t, kind='series', fsk=6, source_genres=g)]}
                  for i, (t, g) in enumerate((('Familie Dr. Kleist', ['Familie', 'Drama']),
                                              ('Eine himmlische Familie', ['Familie', 'Drama']),
                                              ('Ein Hauch von Himmel', ['Familie']),
                                              ('Moesha', ['Familie', 'Komödie']),
                                              ('Sabrina', ['Familie', 'Komödie']),
                                              ('Alle hassen Chris', ['Familie', 'Komödie']),
                                              ('Peppa Wutz', ['Kinder']),
                                              ('Die Biene Maja', ['Familie', 'Animation'])))]
        self.assertEqual(sorted(t['title'] for t in self.build({'series': series})['series']), ['Die Biene Maja', 'Peppa Wutz'])


if __name__ == '__main__':
    unittest.main()
