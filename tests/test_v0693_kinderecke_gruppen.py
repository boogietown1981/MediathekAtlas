"""0.6.93 (Björn, 22.11.2026): Gruppen in der Kinderecke – wenige feste Gruppen (kids_catalog.GROUPS), jeder Titel
in genau einer, kleine Gruppen gehen in „Noch mehr“, leere erscheinen nicht."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kids_catalog  # noqa: E402


def entry(title, cats=(), genre='', topic='', source='pluto', kind='movie', item_id=None):
    if source == 'mediatheken':
        item = {'id': item_id or 'o-' + title, 'available': True, 'categories': list(cats), 'series_parent': kind == 'series',
                'show_key': 'show:' + title, 'metadata': {'title': title, 'genres': [genre] if genre else []},
                'source': {'title': title, 'topic': topic}}
    else:
        item = {'id': item_id or ('id-%s' % abs(hash(title)))[:20], 'title': title, 'kind': kind, 'playable': 1,
                'categories': list(cats), 'genre': genre}
    return {'title': title, 'offers': [{'source': source, 'item': item}]}


class GroupTests(unittest.TestCase):
    def test_group_of(self):
        g = kids_catalog.group_of
        self.assertEqual(g(entry('Die Gänsemagd', ['Fantasy', 'Familie'], topic='Sechs auf einen Streich', source='mediatheken')), 'maerchen')
        self.assertEqual(g(entry('Rapunzel', ['Animation', 'Kinder'], genre='Märchen')), 'maerchen')      # Märchen vor Zeichentrick
        self.assertEqual(g(entry('Der kleine Drache', ['Animation', 'Kinder'])), 'trick')
        self.assertEqual(g(entry('Tierbabys', ['Kinder', 'Natur & Tiere'])), 'tiere')
        self.assertEqual(g(entry('Checker Tobi', ['Kinder'], topic='Checker Tobi', source='mediatheken')), 'wissen')
        self.assertEqual(g(entry('Piratenschatz', ['Kinder', 'Abenteuer'])), 'abenteuer')
        self.assertEqual(g(entry('Lachen mit Ole', ['Kinder', 'Komödie'])), 'lustig')
        self.assertEqual(g(entry('Ein Film', ['Kinder'])), 'mehr')

    def test_build_folds_small_groups_and_lists_used_groups(self):
        movies = [entry('Märchen %d' % i, ['Kinder'], genre='Märchen') for i in range(3)]
        movies += [entry('Trick %d' % i, ['Animation', 'Kinder']) for i in range(2)]          # zu klein → Noch mehr
        movies += [entry('Film %d' % i, ['Kinder']) for i in range(4)]
        series = [entry('Trickserie', ['Animation', 'Kinder'], genre='Kinder', kind='series')]                  # zählt mit: 3 Zeichentrick

        def page(root, db, kind='movies', offset=0, **kw):
            rows = movies if kind == 'movies' else series
            return {'items': rows[offset:offset + 48], 'total': len(rows), 'pending': []}
        data = kids_catalog.build('/r', None, page=page)
        groups = {t['title']: t['group'] for t in data['movies'] + data['series']}
        self.assertEqual(groups['Märchen 0'], 'maerchen')
        self.assertEqual(groups['Trick 0'], 'trick')
        self.assertEqual(groups['Trickserie'], 'trick')
        self.assertEqual(groups['Film 0'], 'mehr')
        self.assertEqual([g['id'] for g in data['groups']], ['maerchen', 'trick', 'mehr'])
        self.assertTrue(all(g['icon'] and g['name'] for g in data['groups']))
        out = kids_catalog.with_progress(data, {})
        self.assertEqual(out['groups'], data['groups'])

    def test_small_group_goes_to_more(self):
        movies = [entry('Tierfilm', ['Natur & Tiere', 'Kinder'])] + [entry('Film %d' % i, ['Kinder']) for i in range(3)]

        def page(root, db, kind='movies', offset=0, **kw):
            rows = movies if kind == 'movies' else []
            return {'items': rows[offset:offset + 48], 'total': len(rows), 'pending': []}
        data = kids_catalog.build('/r', None, page=page)
        self.assertEqual({t['group'] for t in data['movies']}, {'mehr'})
        self.assertEqual([g['id'] for g in data['groups']], ['mehr'])

    def test_ui_uses_theme_not_play_group(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn("theme: t.group || 'mehr', group: type", js)
        self.assertIn("chip('g:' + g.id", js)


if __name__ == '__main__':
    unittest.main()
