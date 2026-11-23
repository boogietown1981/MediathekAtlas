"""Vorbereitung 0.6.113 (Mac-Prüfung 0.6.112, 23.11.2026, K4): Werk mit KiKA- und ZDF-Angebot war über den KiKA-Zwilling
zugelassen, die Kinderecke spielte aber das ZDF-Angebot. Jetzt: Kindersender-Angebot bevorzugt (Liste, Folgenliste,
Abspielen, Nachladen), Sender und Weg werden ausgewiesen; ohne aktiven Zwilling keine Zulassung über den Sender.
Dazu: Weg je Film (kids_rules.explain), leere Referenz trifft keine Altersangabe (K8), Folgenwege zwischengespeichert."""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog, kids_rules  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


class Twin(Mixed):
    def twin(self, wid, channel='KiKA', active=1):
        with self.db() as c:
            c.execute("INSERT INTO offers(id,work_id,payload,active) VALUES(?,?,?,?)",
                      ('k-' + wid, wid, json.dumps({'title': 'Zwilling', 'channel': channel, 'topic': '', 'duration': 1500,
                                                    'url_video': 'https://example.org/k-%s.mp4' % wid}), active))

    def test_episode_plays_kids_twin(self):
        self.series('show:young', 'Young Crime', [(2, 'ZDF', [], 'Folge %d')])
        self.twin('show:young-1')
        d = self.data()
        with self.db() as c:
            eps = kids_catalog.episodes(self.root, c, d, 'mediatheken', 'show:young')['episodes']
            self.assertEqual([(e['channel'], e['weg']) for e in eps], [('KiKA', 'sender')])
            self.assertEqual(eps[0]['ref'], {'offer': 'k-show:young-1'})
            self.assertTrue(kids_catalog.work_allowed(c, 'show:young-1'))
            self.assertTrue(kids_catalog.work_allowed(c, 'show:young-1', 'k-show:young-1'))
            self.assertFalse(kids_catalog.work_allowed(c, 'show:young-1', 'o-show:young-1'))   # ZDF-Angebot nie
            self.assertFalse(kids_catalog.offer_allowed(c, 'o-show:young-1'))
            self.assertFalse(kids_catalog.work_allowed(c, 'show:young-2'))

    def test_inactive_twin_loses_admission(self):
        self.series('show:young', 'Young Crime', [(1, 'ZDF', [], 'Folge %d')])
        self.twin('show:young-1', active=0)
        d = self.data()
        with self.db() as c:
            self.assertIsNone(kids_catalog.kids_offer(c, 'show:young-1'))
            self.assertFalse(kids_catalog.work_allowed(c, 'show:young-1'))
        self.assertEqual(d['series'], [])

    def test_film_tile_switches_to_twin(self):
        self.add('film', 'Ein Abenteuer', ['Abenteuer'], channel='ZDF')
        self.twin('film')
        d = self.data()
        tiles = [t for t in d['movies'] if t['title'] == 'Ein Abenteuer']
        self.assertEqual(len(tiles), 1, d['movies'])
        self.assertEqual((tiles[0]['ref'], tiles[0]['channel'], tiles[0]['weg']), ({'offer': 'k-film'}, 'KiKA', 'sender'))
        with self.db() as c:
            self.assertFalse(kids_catalog.offer_allowed(c, 'o-film'))
            self.assertTrue(kids_catalog.offer_allowed(c, 'k-film'))


class Explain(Mixed):
    def test_paths(self):
        self.add('kika', 'KiKA-Film', ['Abenteuer'], channel='KiKA')
        self.add('ref', 'Trickfilm', ['Kinder'])
        self.add('krimi', 'Krimi', ['Krimi'])
        with self.db() as c:
            self.assertEqual(kids_rules.explain(c, 'kika'), 'sender')
            self.assertEqual(kids_rules.explain(c, 'ref'), 'referenz')
            self.assertIsNone(kids_rules.explain(c, 'krimi'))

    def test_empty_reference_matches_no_age(self):
        # K8: Werk ohne Kennung darf keine Altersangabe zum leeren Schlüssel finden
        self.add('liebe', 'Wer hat eigentlich die Liebe erfunden?', ['Familie', 'Komödie'], ref='')
        with self.db() as c:
            c.execute("INSERT OR REPLACE INTO reference_ages(ref, age) VALUES('', 0)")
            self.assertIsNone(kids_rules.explain(c, 'liebe'))
        self.assertEqual(self.data()['movies'], [])


class PathCache(Mixed):
    def test_cache_follows_parent_choice(self):
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', [], 'Maus %d')])
        self.data()
        with self.db() as c:
            self.assertTrue(kids_catalog.work_allowed(c, 'show:maus-1'))
            t = time.perf_counter()
            for _ in range(200):
                kids_catalog.work_allowed(c, 'show:maus-2')
            self.assertLess(time.perf_counter() - t, 2.0)
            kids_rules.choose(c, 'work', 'show:maus-1', 'block')
            self.assertFalse(kids_catalog.work_allowed(c, 'show:maus-1'))


if __name__ == '__main__':
    unittest.main()
