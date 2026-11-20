"""0.6.60 (Björns Diagnose 20.11.2026 nachts): YouTube-Abo belegte 18,7 GB bei 10 GB Budget.

* Aufträge, die schon in der Warteschlange stehen (aus der Zeit vor dem Budget, 0.6.43), wurden vom Budget nicht
  erfasst. Liegt ein Abo über dem Budget, gehen noch nicht gestartete Aufträge zurück auf „gewünscht“.
* Auch beim Start eines Downloads gilt das Budget (pace mit Verbindung zur Warteschlange).
* Die Größe wartender Videos wird aus den fertigen Dateien des Abos gelernt (feste 250 kB/s waren zu wenig).
* Die Verwaltung zeigt „Über dem Speicherbudget“.
"""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube_abos as ab  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW  # noqa: E402

MB = 1000 ** 2


class HardBudget(Fixture):
    def _conn(self):
        c = sqlite3.connect(self.catalog)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def finish(self, job, size):
        path = self.downloads / ('%s.mp4' % job['source']['_video_id'])
        with open(path, 'wb') as f:
            f.truncate(size)                                  # sparse: no real disk use
        self.set_job(job['id'], 'done', path=str(path), offline_until=NOW + 86400)

    def queued_without_budget(self, count):
        """Like 0.6.43: an abo without budget queues videos; then the budget arrives (0.6.45 default 10 GB)."""
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': count, 'budget_gb': 0}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        return abo

    def test_queued_jobs_over_budget_go_back_to_wanted(self):
        abo = self.queued_without_budget(6)
        jobs = sorted(self.jobs(), key=lambda j: j['source']['_video_id'])
        self.assertEqual(len(jobs), 6)
        for job in jobs[:2]:
            self.finish(job, 600 * MB)                        # 1.2 GB on disk already
        ab.change(self.root, abo, {'budget_gb': 1})
        ab.check(self.root, abo, now=NOW + 3600, request=self.api)
        states = [v['state'] for v in self.videos(abo).values() if v['state'] != 'old']
        self.assertEqual(states.count('done'), 2)
        self.assertEqual(states.count('queued'), 0)            # nothing more starts above the budget
        self.assertEqual(len([j for j in self.jobs() if j['_state'] == 'queued']), 0)
        waiting = [v for v in self.videos(abo).values() if v['state'] == 'wanted']
        self.assertTrue(waiting)
        self.assertTrue(all(v['reason'] == ab.BUDGET_REASON for v in waiting if v['job_id'] == ''))
        over = ab.overview(self.root, self._conn())['abos'][0]
        self.assertTrue(over['over_budget'])
        self.assertTrue(over['budget_full'])
        self.assertGreater(ab.summary(self.root)['waiting_for_budget'], 0)

    def test_started_download_is_held_by_budget(self):
        abo = self.queued_without_budget(3)
        jobs = sorted(self.jobs(), key=lambda j: j['source']['_video_id'])
        self.finish(jobs[0], 1200 * MB)
        ab.change(self.root, abo, {'budget_gb': 1})
        job = jobs[1]
        conn = self._conn()
        self.assertTrue(ab.pace(self.root, job, now=NOW, c=conn))
        self.assertIn('Speicherbudget des Abos erreicht (1.2 von 1 GB)', job['note'])
        self.assertEqual(job['not_before'], NOW + ab.RESERVE_RECHECK)
        self.assertFalse(ab.pace(self.root, dict(jobs[2]), now=NOW, force=True, c=conn))   # „Jetzt versuchen“

    def test_budget_without_files_lets_the_first_video_start(self):
        abo = self.queued_without_budget(1)
        ab.change(self.root, abo, {'budget_gb': 0.1})
        job = self.jobs()[0]
        with mock.patch.object(ab, 'per_hour', lambda root: 1000):
            self.assertFalse(ab.pace(self.root, job, now=NOW, c=self._conn()))

    def test_learned_rate_is_used_for_waiting_videos(self):
        self.assertIsNone(ab._learned_rate([]))
        self.assertIsNone(ab._learned_rate([(10 * MB, 30)]))   # under a minute: no evidence
        rate = ab._learned_rate([(600 * MB, 600), (300 * MB, 300)])
        self.assertEqual(rate, 1 * MB)
        fixed = ab.estimate({'duration': 600}, '720')
        self.assertEqual(ab.sized({'duration': 600}, '720', None), fixed)
        self.assertEqual(ab.sized({'duration': 600}, '720', 1 * MB), 4 * fixed)        # capped at 4×
        self.assertEqual(ab.sized({'duration': 600}, '720', 100), fixed)                # never below the fixed rate

    def test_admin_page_names_over_budget(self):
        js = (ROOT / 'web' / 'youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn('a.over_budget', js)
        self.assertIn('Über dem Speicherbudget', js)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('youtube_abos.pace(ROOT,j,force=forced,c=c)', server)


if __name__ == '__main__':
    unittest.main()
