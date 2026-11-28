"""0.6.164 – Mac-Prüfung 0.6.162 (BEFUND-06162.txt): zusammengeführte Kinderreihen
A: die 400-Folgen-Grenze schnitt die zweite Reihe ab (Schloss Einstein 608 → 400) – jetzt je Teil 400, höchstens 1600;
B: dieselbe Folge aus der Zwillingsreihe ohne/mit anderen Nummern doppelt (Checkpoint 0 → 13) – gleicher Titel = dieselbe
   Folge, außer verschiedene Folgennummern oder deutlich andere Dauer;
Sperre: Sperren/Freigeben der Kachel gilt für alle Teile, Zurücknehmen auch;
Bild: TheTVDB-Platzhalter …/images/missing/series.jpg zählt nicht als Bild."""
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import kids_catalog as kc
import kids_rules

ROOT = Path(__file__).resolve().parents[1]


def show(key, title, poster='', **extra):
    return {'id': 'mediatheken:' + key, 'source': 'mediatheken', 'kind': 'series', 'title': title, 'poster': poster,
            'series': {'show': key}, 'group': 'zeichentrick', **extra}


def ep(source, ident, title, season=None, episode=None, duration=600):
    ref = {'offer' if source == 'mediatheken' else source: ident}
    return kc._episode(source, ref, title, season, episode, '', duration)


def run(head, parts):
    data = {'movies': [], 'series': [head]}
    with mock.patch.object(kc, '_episodes_of', side_effect=lambda root, c, d, s, sid: [dict(e) for e in parts[sid]]):
        return kc.episodes('/r', None, data, 'mediatheken', head['series']['show'], {})['episodes']


class CapTests(unittest.TestCase):
    def test_merged_tile_keeps_episodes_of_both_parts(self):
        head = show('se', 'Schloss Einstein')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'se2'}}]
        parts = {'se': [ep('mediatheken', 'a%d' % n, 'Folge %d' % n, 1, n) for n in range(1, 401)],
                 'se2': [ep('mediatheken', 'b%d' % n, 'Folge %d' % n, 2, n) for n in range(1, 216)]}
        self.assertEqual(len(run(head, parts)), 615)

    def test_single_tile_cap_unchanged(self):
        head = show('x', 'X')
        got = run(head, {'x': [ep('mediatheken', 'a%d' % n, 'F %d' % n, 1, n) for n in range(1, 450)]})
        self.assertEqual(len(got), kc.MAX_EPISODES)


class DuplicateTests(unittest.TestCase):
    def test_same_title_from_twin_without_numbers_once(self):
        head = show('cp', 'Checkpoint')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'cp-wdr'}}]
        parts = {'cp': [ep('mediatheken', 'k1', 'Wie stark ist ein Ei?', 3, 4, 1500)],
                 'cp-wdr': [ep('mediatheken', 'w1', 'Wie stark ist ein Ei?', None, None, 1520),
                            ep('mediatheken', 'w2', 'Neue Folge', None, None, 1500)]}
        self.assertEqual([e['title'] for e in run(head, parts)], ['Wie stark ist ein Ei?', 'Neue Folge'])

    def test_same_title_different_numbers_or_length_stay(self):
        head = show('c', 'Conni')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'c2'}}]
        parts = {'c': [ep('mediatheken', 'k1', 'Conni', 1, 1, 600)],
                 'c2': [ep('mediatheken', 'w1', 'Conni', 1, 2, 600), ep('mediatheken', 'w2', 'Conni', None, None, 1400)]}
        self.assertEqual(len(run(head, parts)), 3)


class BlockTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        kids_rules.ensure(self.c)
        head = show('heidi', 'Heidi')
        head['block'] = kc.block_target(head)
        twin = show('heidi-zdf', 'Heidi')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'heidi-zdf'}, 'block': kc.block_target(twin)}]
        kc._CACHE['/r'] = (0, {'movies': [], 'series': [head]})
        self.addCleanup(kc._CACHE.pop, '/r', None)

    def keys(self):
        return {r[0] for r in self.c.execute("SELECT key FROM kids_choices WHERE choice='block'")}

    def test_block_and_undo_cover_all_parts(self):
        self.assertEqual(kc.apply_to_twins(self.c, '/r', 'show', 'heidi', 'block', 'Heidi'), 1)
        kids_rules.choose(self.c, 'show', 'heidi', 'block', 'Heidi')
        self.assertEqual(self.keys(), {'show:heidi', 'show:heidi-zdf'})
        kc._CACHE['/r'] = (0, {'movies': [], 'series': []})      # gesperrt: Kachel und Teile nicht mehr in der Liste
        self.assertEqual(kc.apply_to_twins(self.c, '/r', 'show', 'heidi', '', 'Heidi'), 1)
        kids_rules.choose(self.c, 'show', 'heidi', '', 'Heidi')
        self.assertEqual(self.keys(), set())

    def test_merge_carries_block_targets_and_server_uses_them(self):
        a, b = show('a', 'Heidi', 'p'), show('b', 'heidi')
        for t in (a, b):
            t['block'] = kc.block_target(t)
        head = kc.merge_twin_series([a, b])[0]
        self.assertEqual(head['twins'][0]['block'], {'kind': 'show', 'id': 'b'})
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('kids_catalog.apply_to_twins(c,ROOT,kind,value', src)


class PictureTests(unittest.TestCase):
    def test_tvdb_placeholder_is_no_picture(self):
        self.assertEqual(kc._https('https://artworks.thetvdb.com/images/missing/series.jpg'), '')
        self.assertEqual(kc._https('https://artworks.thetvdb.com/banners/posters/1.jpg'),
                         'https://artworks.thetvdb.com/banners/posters/1.jpg')
        tile = kc._tile('mediatheken', 'series', 'X', 2020, 'https://thetvdb.com/images/missing/series.jpg', series={'show': 'x'})
        self.assertEqual(tile['poster'], '')


if __name__ == '__main__':
    unittest.main()
