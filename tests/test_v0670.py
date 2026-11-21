"""0.6.70 (Mac-Testkopie 21.11.2026): Daily Soaps in der Folgensuche.

IMDb nummeriert Sturm der Liebe (tt0479846, Staffel 1 = Folgen 1–4.678) und Dahoam is Dahoam (tt1111847,
Staffel 1 = 1–3.833) absolut. In der Warteschlange: Sturm der Liebe 1.710 von 1.824 ohne Treffer, Dahoam is
Dahoam 2.471 von 2.545. Mediathek-Titel (echte Beispiele): „Menu à la Française · 17.08.15 | Folge 1562“,
„(K)oa Chance · 12.11.26 | Folge 3829 (Audiodeskription)“, „Folge 4556“, „Folge (4612)“, „Sturm der Liebe (4602)“.
"""
import gzip
import tempfile
import threading
import unittest
from pathlib import Path

import catalog
import imdb_archive
import matching

ROWS = {
    'basics': [
        'tt1111847\ttvSeries\tDahoam is Dahoam\tDahoam is Dahoam\t0\t2007\t\\N\t25\tComedy',
        'tt9001562\ttvEpisode\tMenu à la Française\tMenu à la Française\t0\t2015\t\\N\t25\tComedy',
        'tt9003829\ttvEpisode\t(K)oa Chance\t(K)oa Chance\t0\t2026\t\\N\t25\tComedy',
        'tt9000100\ttvEpisode\tErste Hundert\tErste Hundert\t0\t2008\t\\N\t25\tComedy',
        'tt0479846\ttvSeries\tStorm of Love\tSturm der Liebe\t0\t2005\t\\N\t50\tDrama',
        'tt8004556\ttvEpisode\tEpisode #1.4556\tEpisode #1.4556\t0\t2025\t\\N\t50\tDrama',
        'tt8004612\ttvEpisode\tEpisode #1.4612\tEpisode #1.4612\t0\t2026\t\\N\t50\tDrama',
        'tt8000150\ttvEpisode\tEpisode #1.150\tEpisode #1.150\t0\t2006\t\\N\t50\tDrama',
        'tt7000000\ttvSeries\tKrimi mit Staffeln\tKrimi mit Staffeln\t0\t2010\t\\N\t45\tCrime',
        'tt7000001\ttvEpisode\tEins\tEins\t0\t2010\t\\N\t45\tCrime',
        'tt7000002\ttvEpisode\tZwei\tZwei\t0\t2011\t\\N\t45\tCrime',
    ],
    'ratings': ['tt0479846\t6.0\t100'],
    'episode': ['tt9001562\ttt1111847\t1\t1562', 'tt9003829\ttt1111847\t1\t3829', 'tt9000100\ttt1111847\t1\t100',
                'tt8004556\ttt0479846\t1\t4556', 'tt8004612\ttt0479846\t1\t4612', 'tt8000150\ttt0479846\t1\t150',
                'tt7000001\ttt7000000\t1\t3', 'tt7000002\ttt7000000\t2\t3'],
    'akas': ['tt0479846\t1\tSturm der Liebe\tDE\tde\t\\N\t\\N\t0'],
    'crew': ['tt8004556\t\\N\t\\N'], 'principals': ['tt8004556\t1\tnm1\tactress\t\\N\t["Lena"]'],
    'people': ['nm1\tJemand\t\\N\t\\N\tactress\ttt0479846'],
}


def build(root):
    files = {}
    for kind, rows in ROWS.items():
        path = root / (kind + '.gz')
        path.write_bytes(gzip.compress(('\t'.join(imdb_archive.HEADERS[kind]) + '\n' + '\n'.join(rows) + ('\n' if rows else '')).encode()))
        files[kind] = path
    archive = imdb_archive.Archive(root, threading.Event())
    imdb_archive.build(archive.path, files)
    return imdb_archive.Archive(root, threading.Event())


class Soaps(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.archive = build(Path(tmp.name))

    def tearDown(self):
        opened = getattr(self.archive._reader_local, 'opened', None)
        if opened:
            opened[1].close()

    def match(self, title, topic, ref, duration=None, timestamp=None, **kw):
        src = {'title': title, 'topic': topic, 'duration': duration or (2900 if topic == 'Sturm der Liebe' else 1700)}
        if timestamp:
            src['timestamp'] = timestamp
        m = {**catalog.seed(src), 'kind': 'series', 'title': topic, 'provider': 'IMDb Offline', 'reference_id': ref,
             'episode_verified': False, 'season': None, 'episode': None, **kw}
        ev = self.archive.episode_evidence(src, m)
        return matching.choose(m, ev['candidates'])

    def test_dahoam_titles_with_air_date_and_number(self):
        for title, ep, ref in (('Menu à la Française · 17.08.15 | Folge 1562', 1562, 'tt9001562'),
                               ('(K)oa Chance · 12.11.26 | Folge 3829 (Audiodeskription)', 3829, 'tt9003829'),
                               ('(K)oa Chance · 12.11.26 | Folge 3829', 3829, 'tt9003829')):
            with self.subTest(title=title):
                chosen = self.match(title, 'Dahoam is Dahoam', 'tt1111847')
                self.assertIsNotNone(chosen)
                self.assertEqual((chosen['season'], chosen['episode'], chosen['episode_reference_id']), (1, ep, ref))
                self.assertTrue(chosen['episode_verified'])

    def test_sturm_der_liebe_absolute_numbers(self):
        for title, ep in (('Folge 4556', 4556), ('Folge (4612)', 4612), ('Sturm der Liebe (4612)', 4612)):
            with self.subTest(title=title):
                chosen = self.match(title, 'Sturm der Liebe', 'tt0479846')
                self.assertIsNotNone(chosen)
                self.assertEqual((chosen['season'], chosen['episode']), (1, ep))
                self.assertEqual(chosen['episode_title'], 'Folge %d' % ep)      # not IMDb's "Episode #1.4556"

    def test_no_match_without_safe_evidence(self):
        # number unknown in IMDb
        self.assertIsNone(self.match('Folge 4999', 'Sturm der Liebe', 'tt0479846'))
        # air date contradicts IMDb's year for that number (2015 vs 2008)
        self.assertIsNone(self.match('Anderer Name · 17.08.15 | Folge 100', 'Dahoam is Dahoam', 'tt1111847'))
        # the broadcaster names the episode differently than IMDb: contradiction, no match
        self.assertIsNone(self.match('Ganz anderer Titel · 17.08.15 | Folge 1562', 'Dahoam is Dahoam', 'tt1111847'))
        # a series with several IMDb seasons: an absolute number names nothing
        self.assertIsNone(self.match('Folge 3', 'Krimi mit Staffeln', 'tt7000000'))
        # parts of a multi-part film are no absolute episode numbers
        self.assertIsNone(self.match('Folge 2/3', 'Sturm der Liebe', 'tt0479846'))
        self.assertIsNone(imdb_archive.absolute_episode({'title': 'Teil 2 (2/6)'}, {}))

    def test_runtime_still_decides(self):
        # a 3-minute clip titled with the episode number is no full episode
        chosen = self.match('Folge 4556', 'Sturm der Liebe', 'tt0479846', duration=180)
        self.assertIsNone(chosen)

    def test_given_numbers_stay_authoritative(self):
        # a stored season/episode that disagrees is never overridden by the absolute number
        self.assertIsNone(self.match('Folge 4556', 'Sturm der Liebe', 'tt0479846', season=2, episode=7))


if __name__ == '__main__':
    unittest.main()


import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v0658 import Fixture  # noqa: E402


class WaitingSoapsComeBack(Fixture):
    def test_numbered_soap_episodes_are_due_again_others_wait(self):
        now = time.time()
        with self.db() as c:
            rows = c.execute('SELECT id,meta FROM works ORDER BY id').fetchall()
            for i, row in enumerate(rows):
                m = json.loads(row['meta'])
                if i < 3:
                    m.update(title='Sturm der Liebe', reference_id='tt0479846')
                    c.execute('UPDATE offers SET payload=? WHERE work_id=?',
                              (json.dumps({'title': 'Folge %d' % (4556 + i), 'topic': 'Sturm der Liebe', 'duration': 2900}), row['id']))
                    c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), row['id']))
                c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=? WHERE work_id=?", (now + 7 * 86400, row['id']))
        self.svc.refile_loop()
        with self.db() as c:
            due = c.execute('SELECT COUNT(*) FROM episode_queue WHERE next_try<=?', (time.time(),)).fetchone()[0]
        self.assertEqual(due, 3)
