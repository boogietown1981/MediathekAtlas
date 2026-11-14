"""0.5.43: Björn's "#Roxy" (Netzkino 2018): six IMDb titles of the same name stayed 'review'.
The provider's year now picks the matching reference; also for Pluto TV / JustWatch TV
(same analyze()). Old 'review' reports are rechecked automatically."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import netzkino_enrichment as ne  # noqa: E402

ROXY = {'kind': 'movie', 'title': '#Roxy', 'year': 2018, 'season': None, 'episode': None}


def cand(ref, year, provider='IMDb Offline'):
    return {'provider': provider, 'reference_id': ref, 'title': '#Roxy', 'kind': 'movie', 'year': year,
            'similarity': 1, 'genres': ['Comedy', 'Romance']}


def run(meta, cands):
    return ne.analyze(meta, {'title': meta['title'], 'description': ''},
                      [{'candidates': cands, 'provider_checks': []}], match_issues=lambda m, c: [])


class YearTests(unittest.TestCase):
    def test_roxy_exact_year_wins(self):
        r = run(ROXY, [cand('tt12786268', None), cand('tt5646082', 2018), cand('tt18273362', 2022),
                       cand('tt2202527', 2012), cand('tt7223824', 2016), cand('tt0100911', 1990)])
        self.assertEqual(r['status'], 'candidate')
        chosen = [x for x in r['references'] if x['eligible']]
        self.assertEqual([x['reference_id'] for x in chosen], ['tt5646082'])
        self.assertEqual(r['analysis'], ne.ANALYSIS)

    def test_one_year_apart_is_no_contradiction(self):
        r = run(ROXY, [cand('tt5646082', 2018), cand('555', 2017, 'TMDB')])
        self.assertEqual(r['status'], 'candidate')

    def test_two_same_year_titles_stay_review(self):
        r = run(ROXY, [cand('tt1000001', 2018), cand('tt2000002', 2018)])
        self.assertEqual(r['status'], 'review')

    def test_near_year_beats_missing_year(self):
        r = run(ROXY, [cand('tt1000001', None), cand('tt2000002', 2019)])
        self.assertEqual(r['status'], 'candidate')
        self.assertEqual([x['reference_id'] for x in r['references'] if x['eligible']], ['tt2000002'])

    def test_without_provider_year_nothing_changes(self):
        r = run({**ROXY, 'year': None}, [cand('tt1000001', None), cand('tt2000002', 2018)])
        self.assertEqual(r['status'], 'review')

    def test_old_review_reports_are_rechecked(self):
        self.assertTrue(ne.stale_review({'status': 'review'}))
        self.assertTrue(ne.stale_review(json.dumps({'status': 'review', 'analysis': 1})))
        self.assertFalse(ne.stale_review({'status': 'review', 'analysis': ne.ANALYSIS}))
        self.assertFalse(ne.stale_review({'status': 'candidate'}))
        self.assertIn('ne.STALE_REVIEW'.split('.')[1], dir(ne))
        self.assertIn('shared.stale_review(prev)', (ROOT / 'portal_enrichment.py').read_text())

    def test_pending_picks_stale_review(self):
        import sqlite3, tempfile, time
        with tempfile.TemporaryDirectory() as tmp:
            db = ne._conn(Path(tmp))
            cols = [r[1] for r in db.execute('PRAGMA table_info(netzkino_catalog)')]
            db.close()
            self.assertIn('id', cols)
            c = sqlite3.connect(str(Path(tmp) / 'q.db'))
            c.execute('CREATE TABLE r(payload TEXT)')
            c.execute("INSERT INTO r VALUES(?)", (json.dumps({'status': 'review'}),))
            c.execute("INSERT INTO r VALUES(?)", (json.dumps({'status': 'review', 'analysis': ne.ANALYSIS}),))
            n = c.execute('SELECT COUNT(*) FROM r WHERE ' + ne.STALE_REVIEW).fetchone()[0]
            c.close()
            self.assertEqual(n, 1)


if __name__ == '__main__':
    unittest.main()
