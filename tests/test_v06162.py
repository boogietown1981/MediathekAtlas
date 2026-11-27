"""0.6.162 – Björn 27.11.2026 (Bild kinderecke-doppelte.png): „teilweise werden sie doppelt dargestellt, der Inhalt
ist aber unterschiedlich“ – „Animanimals“ zweimal unter Zeichentrick. Gleichnamige Reihen unter verschiedenen
Reihenschlüsseln (der gemeinsame Katalog führt zwei Angebote derselben Quelle nie zusammen) werden in der
Kinderecke EINE Kachel mit den Folgen aller; verschiedene Namen bleiben getrennt."""
import unittest
from pathlib import Path
from unittest import mock

import kids_catalog as kc

ROOT = Path(__file__).resolve().parents[1]


def show(key, title, poster='', **extra):
    return {'id': 'mediatheken:' + key, 'source': 'mediatheken', 'kind': 'series', 'title': title, 'poster': poster,
            'series': {'show': key}, 'group': 'zeichentrick', **extra}


def ep(source, ident, title, season=None, episode=None):
    ref = {'offer' if source == 'mediatheken' else source: ident}
    return kc._episode(source, ref, title, season, episode, '', 600)


class MergeTests(unittest.TestCase):
    def test_same_name_one_tile_different_names_stay(self):
        tiles = [show('animanimals', 'Animanimals'), show('anna-tiere', 'Anna und die wilden Tiere', 'p'),
                 show('animanimals-kika', 'AnimAnimals', 'bild', local=True),
                 show('anna-paula', 'Anna, Paula, Pia und die wilden Tiere', 'p'),
                 {'id': 'pluto:x', 'source': 'pluto', 'title': 'Animanimals', 'series': {'id': 'x'}, 'poster': ''},
                 {'id': 'netzkino:nummern-1', 'source': 'netzkino', 'title': 'Animanimals', 'series': {'id': 'nummern-1'}}]
        out = kc.merge_twin_series(tiles)
        titles = [t['title'] for t in out]
        self.assertEqual(titles.count('Anna und die wilden Tiere'), 1)
        self.assertIn('Anna, Paula, Pia und die wilden Tiere', titles)      # anderer Name: eigene Kachel
        merged = [t for t in out if kc._title_key(t['title']) == 'animanimals' and not t['series'].get('id', '').startswith('nummern-')]
        self.assertEqual(len(merged), 1)
        head = merged[0]
        self.assertEqual(head['series'], {'show': 'animanimals-kika'})     # Mediatheken mit Bild zuerst
        self.assertEqual({(t['source'], t['series'].get('show') or t['series'].get('id')) for t in head['twins']},
                         {('mediatheken', 'animanimals'), ('pluto', 'x')})
        self.assertTrue(head['local'])
        self.assertEqual(titles[0], head['title'])                         # Platz der ersten Kachel bleibt
        self.assertEqual(len([t for t in out if t['series'].get('id') == 'nummern-1']), 1)   # Nummern-Serie unberührt

    def test_episodes_of_all_twins_once(self):
        head = show('a1', 'Animanimals', 'b')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'a2'}}, {'source': 'pluto', 'series': {'id': 'px'}}]
        data = {'movies': [], 'series': [head]}
        parts = {'a1': [ep('mediatheken', 'o1', 'Der Elefant', 1, 2), ep('mediatheken', 'o2', 'Die Giraffe', 1, 1)],
                 'a2': [ep('mediatheken', 'o3', 'Die Giraffe', 1, 1), ep('mediatheken', 'o4', 'Das Zebra', 1, 3)],
                 'px': [ep('pluto', 'p1', 'Der Elefant', 1, 2), ep('pluto', 'p2', 'Der Hai', 2, 1)]}
        with mock.patch.object(kc, '_episodes_of', side_effect=lambda root, c, d, s, sid: [dict(e) for e in parts[sid]]):
            got = kc.episodes('/r', None, data, 'mediatheken', 'a1', {})
        self.assertEqual([e['title'] for e in got['episodes']], ['Die Giraffe', 'Der Elefant', 'Das Zebra', 'Der Hai'])
        # alle Folgen sind danach abspielbar (Liste der gesehenen Folgen)
        self.assertTrue(kc.allowed_ref(data, {'pluto': 'p2'}))
        self.assertTrue(kc.allowed_ref(data, {'offer': 'o4'}))
        # die Zwillingsreihe selbst ist keine eigene Kachel mehr
        with self.assertRaises(ValueError):
            kc.episodes('/r', None, data, 'mediatheken', 'a2', {})

    def test_failing_twin_keeps_main_episodes(self):
        head = show('a1', 'Animanimals')
        head['twins'] = [{'source': 'mediatheken', 'series': {'show': 'a2'}}]

        def parts(root, c, d, s, sid):
            if sid == 'a2':
                raise RuntimeError('kaputt')
            return [ep('mediatheken', 'o1', 'Eins', 1, 1)]
        with mock.patch.object(kc, '_episodes_of', side_effect=parts):
            got = kc.episodes('/r', None, {'movies': [], 'series': [head]}, 'mediatheken', 'a1', {})
        self.assertEqual([e['title'] for e in got['episodes']], ['Eins'])

    def test_wired_into_finish(self):
        src = (ROOT / 'kids_catalog.py').read_text(encoding='utf-8')
        self.assertLess(src.index("out['series'] = _parent_blocks(db, out['series'] + numbered)"),
                        src.index("out['series'] = merge_twin_series(out['series'])"))
        self.assertLess(src.index("out['series'] = merge_twin_series(out['series'])"), src.index('_mark_local(db, out)\n    _fold'))


if __name__ == '__main__':
    unittest.main()
