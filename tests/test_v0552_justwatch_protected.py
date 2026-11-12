"""0.5.52: night reservation only with a real youth-protection window; other JustWatch titles without
a stream for external players are copy protected (Björn: "Andromeda", FSK 12, was shown as night-only)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import justwatch  # noqa: E402
import justwatch_downloads  # noqa: E402


def node(item_id, kind, title, path, age, hours=None, details=True, stream=None):
    content = {'title': title, 'fullPath': path, 'originalReleaseYear': 2000, 'ageCertification': age}
    if details:
        content['ageCertificationDetails'] = {'ageValue': int(age), 'availableHours': hours or []}
    return {'id': item_id, 'objectType': kind, 'content': content,
            'watchNowOffer': {'standardWebURL': 'https://www.justwatch.com' + path, 'streamUrlExternalPlayer': stream,
                              'package': {'shortName': 'jwt'}}}


NIGHT = [{'fromMinute': 0, 'toMinute': 360}, {'fromMinute': 1320, 'toMinute': 1440}]


class TimeWindowTests(unittest.TestCase):
    def test_window_comes_from_justwatch(self):
        show = justwatch.item_from(node('ts10316', 'SHOW', 'Andromeda', '/de/Serie/Andromeda', '12'))
        film = justwatch.item_from(node('tm1', 'MOVIE', 'Bad Lieutenant', '/de/Film/Bad-Lieutenant', '16', NIGHT))
        self.assertEqual((show['night'], show['playable']), (0, 0))
        self.assertEqual(film['night'], 1)
        # FSK 16 without a window in the answer is not night-only.
        self.assertEqual(justwatch.item_from(node('tm2', 'MOVIE', 'X', '/de/Film/X', '16'))['night'], 0)

    def test_age_rating_decides_without_the_field(self):
        self.assertEqual(justwatch.item_from(node('tm3', 'MOVIE', 'Y', '/de/Film/Y', '18', details=False))['night'], 1)
        self.assertEqual(justwatch.item_from(node('tm4', 'MOVIE', 'Z', '/de/Film/Z', '12', details=False))['night'], 0)

    def test_episodes_follow_their_series(self):
        data = {'urlV2': {'node': {'seasons': [{'content': {'seasonNumber': 5}, 'episodes': [
            {'id': 'tse166157', 'content': {'title': 'Das Herz der Reise', 'episodeNumber': 22, 'seasonNumber': 5},
             'offers': [{'standardWebURL': 'https://www.justwatch.com', 'streamUrlExternalPlayer': None,
                         'package': {'shortName': 'jwt'}}]}]}]}}}
        rows, streams = justwatch.parse_seasons(data, {'id': 'ts10316', 'path': '/de/Serie/Andromeda', 'night': 0})
        self.assertEqual((rows[0]['night'], rows[0]['playable'], streams), (0, 0, {}))
        rows, _ = justwatch.parse_seasons(data, {'id': 'ts10316', 'path': '/de/Serie/Andromeda', 'night': 1})
        self.assertEqual(rows[0]['night'], 1)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, nodes):
        return {'data': {'popularTitles': {'edges': [{'node': n} for n in nodes],
                                           'pageInfo': {'endCursor': '', 'hasNextPage': False}, 'totalCount': len(nodes)}}}

    def test_refused_field_falls_back_to_the_basic_query(self):
        asked = []

        def post(query, variables):
            asked.append('ageCertificationDetails' in query)
            if asked[-1]:
                raise ValueError('JustWatch lehnte die Abfrage ab: Cannot query field')
            return self.page([node('tm1', 'MOVIE', 'Bad Lieutenant', '/de/Film/Bad-Lieutenant', '16', details=False),
                              node('ts10316', 'SHOW', 'Andromeda', '/de/Serie/Andromeda', '12', details=False)])
        result = justwatch.sync(self.root, post=post, now=1000)
        self.assertTrue(result['ok']); self.assertEqual(asked, [True, False])
        self.assertEqual((result['night_only'], result['protected']), (1, 0))
        self.assertEqual(justwatch.item(self.root, 'tm1')['item']['night'], 1)
        self.assertEqual(justwatch.item(self.root, 'ts10316')['item']['night'], 0)

    def test_network_failure_is_not_retried_with_another_query(self):
        calls = []

        def post(query, variables):
            calls.append(1)
            raise OSError('offline')
        self.assertFalse(justwatch.sync(self.root, post=post, now=1000)['ok'])
        self.assertEqual(len(calls), 1)

    def test_old_stock_gets_the_column(self):
        import sqlite3
        db = sqlite3.connect(str(self.root / 'justwatch.sqlite3'))
        db.executescript(justwatch.SCHEMA.replace(",\n  night INTEGER NOT NULL DEFAULT 0", ''))
        cols = 'id,kind,title,series_id,rating,seen,updated'
        db.executemany('INSERT INTO justwatch_items(%s) VALUES(?,?,?,?,?,1,1)' % cols, [
            ('ts1', 'series', 'Hart', '', '16'), ('tse1', 'episode', 'Folge', 'ts1', ''),
            ('ts2', 'series', 'Andromeda', '', '12'), ('tse2', 'episode', 'Folge', 'ts2', '')])
        db.commit(); db.close()
        db = justwatch._connect(self.root)
        got = dict(db.execute('SELECT id, night FROM justwatch_items'))
        db.close()
        self.assertEqual(got, {'ts1': 1, 'tse1': 1, 'ts2': 0, 'tse2': 0})


class ProtectedTitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        justwatch.sync(self.root, now=1000, post=lambda q, v: {'data': {'popularTitles': {'edges': [
            {'node': node('ts10316', 'SHOW', 'Andromeda', '/de/Serie/Andromeda', '12')},
            {'node': node('tm9', 'MOVIE', 'Geschützt', '/de/Film/Geschuetzt', '12')},
            {'node': node('tm1', 'MOVIE', 'Bad Lieutenant', '/de/Film/Bad-Lieutenant', '16', NIGHT)}],
            'pageInfo': {'endCursor': '', 'hasNextPage': False}, 'totalCount': 3}}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_protected_title_is_not_queued(self):
        with self.assertRaisesRegex(ValueError, 'kopiergeschützten Player'):
            justwatch_downloads.build_job(self.root, self.root / 'media', 'tm9', 1000)
        self.assertTrue(justwatch_downloads.build_job(self.root, self.root / 'media', 'tm1', 1000)['night'])

    def test_title_page_says_protected_instead_of_night(self):
        import portal_title
        m = portal_title.model(self.root, 'justwatch', 'tm9')
        self.assertTrue(m['protected']); self.assertFalse(m['offline']['allowed']); self.assertFalse(m['offline']['night'])
        self.assertTrue(any('kopiergeschützten' in f[1] for f in m['provider_facts']))
        n = portal_title.model(self.root, 'justwatch', 'tm1')
        self.assertFalse(n['protected']); self.assertTrue(n['offline']['night'])
        ep = portal_title._episode('justwatch', {'id': 'tse1', 'playable': 0, 'night': 0})
        self.assertEqual((ep['offline'], ep['night'], ep['protected']), (False, False, True))

    def test_night_title_without_stream_at_night_names_the_reason(self):
        api = lambda q, v: {'data': {'urlV2': {'node': {'watchNowOffer': None, 'offers': []}}}}
        row = justwatch.item(self.root, 'tm1')['item']
        with self.assertRaisesRegex(ValueError, 'auch im Jugendschutz-Zeitfenster'):
            justwatch.fresh_stream(self.root, row, post=api, now=5000)


class WiringTests(unittest.TestCase):
    def test_tiles_show_the_protection_note(self):
        web = ROOT / 'web'
        self.assertIn('protectedNote', (web / 'offline_button.js').read_text(encoding='utf-8'))
        self.assertIn('item.night ?', (web / 'portal_panel.js').read_text(encoding='utf-8'))
        self.assertIn('!item.playable&&!!item.night', (web / 'unified_catalog.js').read_text(encoding='utf-8'))
        self.assertIn('e.protected', (web / 'portal_title.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
