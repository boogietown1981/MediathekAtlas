"""0.5.81: Merkliste/Weiterschauen on the server (watch_state) and the storage overview (storage_policy)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import netzkino_downloads
import storage_policy
import watch_state
from storage_policy import StoredFile, cleanup_plan, protection

DAY = 86400
NOW = 2_000_000_000.0


class WatchStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_progress_appears_under_continue_and_is_handed_to_the_player(self):
        watch_state.progress(self.root, 'pluto:abc', 600, 5400, info={'title': 'Film A', 'source': 'pluto', 'ref': {'pluto': 'abc'}}, now=NOW)
        data = watch_state.overview(self.root)
        self.assertEqual([e['key'] for e in data['continue']], ['pluto:abc'])
        self.assertEqual(data['continue'][0]['ref'], {'pluto': 'abc'})
        self.assertEqual(data['progress']['pluto:abc'], {'pos': 600.0, 'done': False, 'at': int(NOW * 1000)})

    def test_a_few_seconds_do_not_count_as_started(self):
        self.assertFalse(watch_state.progress(self.root, 'pluto:abc', 12, 5400)['stored'])
        self.assertEqual(watch_state.overview(self.root)['continue'], [])

    def test_the_last_45_seconds_finish_a_title(self):
        watch_state.progress(self.root, 'netzkino:' + 'a' * 32, 600, 5400, info={'title': 'B'}, now=NOW)
        result = watch_state.progress(self.root, 'netzkino:' + 'a' * 32, 5370, 5400, now=NOW + 5)
        self.assertTrue(result['done'])
        data = watch_state.overview(self.root)
        self.assertEqual(data['continue'], [])
        self.assertTrue(data['progress']['netzkino:' + 'a' * 32]['done'])
        self.assertTrue(watch_state.states(self.root)['netzkino:' + 'a' * 32]['done'])

    def test_later_report_without_title_keeps_the_known_title(self):
        watch_state.progress(self.root, 'youtube:t.xyz_-1', 100, 900, info={'title': 'Lied', 'poster': 'https://i.ytimg.com/vi/x/hq.jpg'}, now=NOW)
        watch_state.progress(self.root, 'youtube:t.xyz_-1', 200, 900, info={}, now=NOW + 10)
        entry = watch_state.overview(self.root)['continue'][0]
        self.assertEqual((entry['title'], entry['pos'], entry['poster']), ('Lied', 200.0, 'https://i.ytimg.com/vi/x/hq.jpg'))

    def test_mark_and_unmark(self):
        info = {'title': 'Serie C', 'source': 'mediatheken', 'kind': 'series', 'year': 2021,
                'open': {'id': 'abc123', 'show_key': 'serie c', 'series_parent': True, 'evil': '<script>'}}
        self.assertEqual(watch_state.mark(self.root, 'abc123', favorite=True, info=info, now=NOW)['favorite'], True)
        data = watch_state.overview(self.root)
        self.assertEqual(data['marks'], {'abc123': {'favorite': True, 'pinned': False}})
        self.assertEqual(data['marked'][0]['open'], {'id': 'abc123', 'show_key': 'serie c', 'series_parent': True})
        watch_state.mark(self.root, 'abc123', favorite=False)
        data = watch_state.overview(self.root)
        self.assertEqual((data['marked'], data['marks']), ([], {}))
        self.assertEqual(watch_state.summary(self.root)['entries'], 0)   # nothing left: the row is gone

    def test_forget_keeps_the_mark(self):
        watch_state.progress(self.root, 'pluto:abc', 600, 5400, now=NOW)
        watch_state.mark(self.root, 'pluto:abc', pinned=True)
        watch_state.forget(self.root, 'pluto:abc')
        data = watch_state.overview(self.root)
        self.assertEqual(data['continue'], [])
        self.assertEqual(data['marks']['pluto:abc'], {'favorite': False, 'pinned': True})

    def test_invalid_keys_and_values_are_refused_or_dropped(self):
        for key in ('', 'a b', '../x', 'live:offer:1', 'x' * 201, None):
            with self.assertRaises(ValueError):
                watch_state.progress(self.root, key, 100, 200)
        watch_state.progress(self.root, 'pluto:abc', float('nan'), 'viel', done=True,
                             info={'title': 'T', 'poster': 'javascript:alert(1)', 'year': 'x', 'source': 'boese',
                                   'ref': {'pluto': 'abc', 'url': 'https://example.org', 'job': {'a': 1}}})
        watch_state.mark(self.root, 'pluto:abc', favorite=True)
        entry = watch_state.overview(self.root)['marked'][0]
        self.assertEqual((entry['poster'], entry['year'], entry['source'], entry['ref']), ('', None, '', {'pluto': 'abc'}))


class StorageRuleTests(unittest.TestCase):
    def test_protection_reasons(self):
        old = NOW - 200 * DAY
        self.assertEqual(protection(StoredFile('a', 1, old, pinned=True), NOW), 'pinned')
        self.assertEqual(protection(StoredFile('a', 1, old, favorite=True), NOW), 'favorite')
        self.assertEqual(protection(StoredFile('a', 1, old, last_watched=NOW - 10 * DAY), NOW), 'watched')
        self.assertEqual(protection(StoredFile('a', 1, NOW - 10 * DAY), NOW), 'new')
        self.assertEqual(protection(StoredFile('a', 1, old), NOW), '')
        self.assertEqual(protection(StoredFile('a', 1, old, last_watched=NOW - 100 * DAY), NOW), '')
        # watched to the end long ago although loaded recently: may go
        self.assertEqual(protection(StoredFile('a', 1, NOW - 10 * DAY, watched_done=True, last_watched=NOW - 95 * DAY), NOW), '')

    def test_no_budget_or_within_budget_suggests_nothing(self):
        files = [StoredFile('a', 50, NOW - 200 * DAY), StoredFile('b', 50, NOW - 300 * DAY)]
        self.assertEqual(cleanup_plan(files, 0, NOW)['candidates'], [])
        self.assertEqual(cleanup_plan(files, 100, NOW)['candidates'], [])

    def test_only_as_many_as_needed_finished_first_then_oldest(self):
        files = [StoredFile('recent', 40, NOW - 120 * DAY), StoredFile('oldest', 40, NOW - 400 * DAY),
                 StoredFile('seen', 40, NOW - 150 * DAY, watched_done=True, last_watched=NOW - 100 * DAY),
                 StoredFile('pinned', 40, NOW - 500 * DAY, pinned=True)]
        plan = cleanup_plan(files, 90, NOW)
        self.assertEqual(plan['candidates'], ['seen', 'oldest'])
        self.assertEqual((plan['over_budget_bytes'], plan['blocked']), (70, False))

    def test_blocked_when_everything_else_is_protected(self):
        files = [StoredFile('a', 60, NOW - 400 * DAY, favorite=True), StoredFile('b', 60, NOW - DAY)]
        plan = cleanup_plan(files, 50, NOW)
        self.assertEqual((plan['candidates'], plan['blocked']), ([], True))

    def test_negative_budget_is_an_error(self):
        with self.assertRaises(ValueError):
            cleanup_plan([], -1, NOW)


class StorageOverviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'data'
        self.downloads = Path(self.tmp.name) / 'Filme'
        self.root.mkdir()
        self.c = sqlite3.connect(':memory:')
        self.c.executescript('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT);'
                             'CREATE TABLE offers(id TEXT PRIMARY KEY,work_id TEXT);'
                             'CREATE TABLE downloaded_items(identity TEXT PRIMARY KEY,path TEXT,at REAL);')

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def job(self, job_id, title, size, age_days, origin='', state='done', **extra):
        folder = self.downloads / ('%s (2020)' % title)
        folder.mkdir(parents=True)
        video = folder / ('%s - (2020) - 1080p.mkv' % title)
        video.write_bytes(b'x' * size)
        video.with_suffix('.nfo').write_text('<movie/>')
        os.utime(video, (NOW - age_days * DAY, NOW - age_days * DAY))
        job = {'id': job_id, 'state': state, 'path': str(video), 'root': str(self.downloads), 'origin': origin,
               'metadata': {'title': title, 'year': 2020, 'kind': 'movie'}, 'source': {'_id': 'offer-' + job_id}, **extra}
        self.c.execute('INSERT INTO jobs VALUES(?,?,?)', (job_id, json.dumps(job), state))
        return video

    def test_overview_groups_by_source_and_marks_the_suggestion(self):
        self.job('j1', 'Alt', 3000, 400)
        self.job('j2', 'Neu', 2000, 3)
        self.job('j3', 'Pluto', 1000, 200, origin='pluto', pluto_id='p9', offline_until=NOW + 5 * DAY)
        self.job('j4', 'Wartet', 500, 1, state='queued')
        self.c.execute("INSERT INTO offers VALUES('offer-j1','work-1')")
        storage_policy.save(self.root, {'budget_gb': 0})
        data = storage_policy.overview(self.c, self.root, self.downloads, now=NOW)
        self.assertEqual((data['files'], data['used_bytes'], data['suggested']), (3, 6000, 0))
        self.assertEqual([(g['source'], g['bytes']) for g in data['sources']], [('ARD, ZDF & Co.', 5000), ('Pluto TV', 1000)])
        self.assertEqual({r['id']: r['protection'] for r in data['items']}, {'j1': '', 'j2': 'new', 'j3': ''})
        self.assertEqual(next(r for r in data['items'] if r['id'] == 'j1')['watch_key'], 'work-1')
        self.assertEqual(next(r for r in data['items'] if r['id'] == 'j3')['watch_key'], 'pluto:p9')
        self.assertFalse(data['rules']['automatic_deletion'])
        self.assertGreater(data['disk']['total_bytes'], 0)

    def test_budget_marks_candidates_and_watch_state_protects(self):
        self.job('j1', 'Alt', 3000, 400)
        self.job('j3', 'Pluto', 1000, 200, origin='pluto', pluto_id='p9')
        self.c.execute("INSERT INTO offers VALUES('offer-j1','work-1')")
        with unittest.mock.patch.object(storage_policy, 'GIB', 1000):
            storage_policy.save(self.root, {'budget_gb': 2})
            data = storage_policy.overview(self.c, self.root, self.downloads, now=NOW)
            self.assertEqual([r['id'] for r in data['items'] if r['suggested']], ['j1'])
            self.assertEqual(data['items'][0]['id'], 'j1')   # suggestions first
            watch = {'work-1': {'favorite': True, 'pinned': False, 'done': False, 'watched_at': 0}}
            data = storage_policy.overview(self.c, self.root, self.downloads, watch=watch, now=NOW)
            self.assertEqual([r['id'] for r in data['items'] if r['suggested']], ['j3'])
            self.assertTrue(data['blocked'])   # 3000 protected, budget 2000

    def test_settings_are_validated(self):
        self.assertEqual(storage_policy.load(self.root), {'budget_gb': 0.0, 'protect_days': 90})
        self.assertEqual(storage_policy.save(self.root, {'budget_gb': '250.55', 'protect_days': 30}), {'budget_gb': 250.55, 'protect_days': 30})
        for bad in ({'budget_gb': -1}, {'budget_gb': 'viel'}, {'budget_gb': float('nan')}, {'protect_days': 1}, {'protect_days': None}):
            with self.assertRaises(ValueError):
                storage_policy.save(self.root, bad)
        self.assertEqual(storage_policy.load(self.root)['budget_gb'], 250.55)   # a refused change leaves the file alone

    def test_delete_removes_exactly_this_download(self):
        video = self.job('j1', 'Alt', 3000, 400)
        other = self.job('j2', 'Bleibt', 2000, 400)
        self.c.execute('INSERT INTO downloaded_items VALUES(?,?,?)', ('work-1', str(video), NOW))
        result = storage_policy.delete(self.c, 'j1', {}, netzkino_downloads.remove_files)
        self.assertEqual(result['freed_bytes'], 3000)
        self.assertFalse(video.exists())
        self.assertFalse(video.parent.exists())      # NFO and the emptied film folder are gone as well
        self.assertTrue(other.exists())
        self.assertEqual(self.c.execute("SELECT state FROM jobs WHERE id='j1'").fetchone()[0], 'removed')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM downloaded_items').fetchone()[0], 0)
        with self.assertRaises(ValueError):          # not a finished download any more
            storage_policy.delete(self.c, 'j1', {}, netzkino_downloads.remove_files)

    def test_pinned_download_is_not_deleted(self):
        video = self.job('j1', 'Alt', 3000, 400)
        with self.assertRaises(ValueError):
            storage_policy.delete(self.c, 'j1', {'job:j1': {'pinned': True}}, netzkino_downloads.remove_files)
        self.assertTrue(video.exists())

    def test_file_outside_the_job_folder_is_never_deleted(self):
        video = self.job('j1', 'Alt', 3000, 400)
        job = json.loads(self.c.execute("SELECT payload FROM jobs WHERE id='j1'").fetchone()[0])
        job['root'] = str(Path(self.tmp.name) / 'woanders')
        self.c.execute("UPDATE jobs SET payload=? WHERE id='j1'", (json.dumps(job),))
        with self.assertRaises(ValueError):
            storage_policy.delete(self.c, 'j1', {}, netzkino_downloads.remove_files)
        self.assertTrue(video.exists())
        self.assertEqual(self.c.execute("SELECT state FROM jobs WHERE id='j1'").fetchone()[0], 'done')


if __name__ == '__main__':
    import unittest.mock
    unittest.main()
