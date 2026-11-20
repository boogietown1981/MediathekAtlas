"""0.6.53: recognition results are shared between devices instead of being recalculated.

Björn runs MediathekAtlas on several Macs with separate catalogues (MacBook Pro M3, MacBook Air,
MacBook Pro M4 Pro). Every Mac recognised the same catalogue on its own; the Verbund was off
because two desktop apps cannot connect directly (both listen on this computer only).
Covered here:
- one-click Verbund over a cloud folder (iCloud Drive & Co.) with staged open segments,
- gap-safe reading (a later segment synced before an earlier one, evicted iCloud files),
- confirmed episodes and "no episode found" shared by the episode search,
- a local manual assignment is never replaced; a differing one becomes a visible conflict,
- a copied data folder gets its own node ID,
- older nodes (without episode sharing) keep working.
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import imdb_archive
import meshjournal
from tests import test_v0624_episode_search as episodes


def event_data(work='ab12'):
    return {'work': work, 'outcome': 'matched', 'meta': {'title': 'Film', 'kind': 'movie'}, 'providers': ['TMDB']}


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'iCloud' / 'MediathekAtlas-Verbund'; self.root.mkdir(parents=True)
        meshjournal.check_folder(self.root, create=True)

    def test_open_segment_stays_in_local_staging_until_published(self):
        staging = self.base / 'data' / 'verbund-staging' / 'x'
        a = meshjournal.Journal(self.root, 'a' * 32, staging=staging)
        a.append('match.result', event_data('01'))
        self.assertEqual([p.name for p in a.dir.iterdir()], [])
        self.assertEqual([p.name for p in staging.iterdir()], ['events-000001.jsonl.partial'])
        a.flush(force=True)
        self.assertEqual(sorted(p.name for p in a.dir.iterdir()), ['events-000001.jsonl'])
        self.assertEqual(list(staging.iterdir()), [])
        a.append('match.result', event_data('02'))
        again = meshjournal.Journal(self.root, 'a' * 32, staging=staging)
        self.assertEqual((again.seq, again.segment), (2, 2))
        again.flush(force=True)
        events, _, _ = meshjournal.Journal(self.root, 'b' * 32).read({})
        self.assertEqual([e['data']['work'] for e in events], ['01', '02'])

    def test_crash_after_publish_and_folder_change_keep_numbering(self):
        staging = self.base / 'staging'
        a = meshjournal.Journal(self.root, 'a' * 32, staging=staging)
        a.append('match.result', event_data('01')); a.flush(force=True)
        # Crash between publishing and removing the staged copy.
        (staging / 'events-000001.jsonl.partial').write_bytes((a.dir / 'events-000001.jsonl').read_bytes())
        again = meshjournal.Journal(self.root, 'a' * 32, staging=staging)
        self.assertEqual(again.segment, 2); self.assertFalse((staging / 'events-000001.jsonl.partial').exists())
        # A staged segment of the old folder continues the new folder's numbering (no gap for readers).
        again.append('match.result', event_data('02'))
        other = self.base / 'other'; other.mkdir(); meshjournal.check_folder(other, create=True)
        moved = meshjournal.Journal(other, 'a' * 32, staging=staging)
        self.assertEqual(moved.segment, 1); moved.flush(force=True)
        self.assertEqual([p.name for p in moved.dir.iterdir()], ['events-000001.jsonl'])

    def test_later_segment_waits_for_earlier_one(self):
        a = meshjournal.Journal(self.root, 'a' * 32)
        for work in ('01', '02', '03'):
            a.append('match.result', event_data(work)); a.flush(force=True)
        hidden = a.dir / 'events-000002.jsonl'; kept = hidden.read_bytes(); hidden.unlink()
        b = meshjournal.Journal(self.root, 'b' * 32)
        events, cursors, _ = b.read({}, now=1000)
        self.assertEqual([e['data']['work'] for e in events], ['01'])
        self.assertEqual(b.waiting, {'a' * 32: 2})
        hidden.write_bytes(kept)
        events, cursors, _ = b.read(cursors, now=1010)
        self.assertEqual([e['data']['work'] for e in events], ['02', '03']); self.assertEqual(b.waiting, {})

    def test_missing_segment_is_given_up_after_waiting(self):
        a = meshjournal.Journal(self.root, 'a' * 32)
        for work in ('01', '02'):
            a.append('match.result', event_data(work)); a.flush(force=True)
        (a.dir / 'events-000001.jsonl').unlink()
        b = meshjournal.Journal(self.root, 'b' * 32)
        self.assertEqual(b.read({}, now=1000)[0], [])
        events, _, _ = b.read({}, now=1000 + meshjournal.GAP_WAIT + 1)
        self.assertEqual([e['data']['work'] for e in events], ['02'])

    def test_evicted_icloud_segment_is_requested_and_awaited(self):
        a = meshjournal.Journal(self.root, 'a' * 32)
        for work in ('01', '02'):
            a.append('match.result', event_data(work)); a.flush(force=True)
        os.replace(a.dir / 'events-000001.jsonl', a.dir / '.events-000001.jsonl.icloud')
        b = meshjournal.Journal(self.root, 'b' * 32)
        with patch.object(meshjournal, 'request_download') as fetch:
            events, cursors, _ = b.read({}, now=1000)
        self.assertEqual(events, []); self.assertEqual(b.waiting, {'a' * 32: 1})
        fetch.assert_called_once()
        os.replace(a.dir / '.events-000001.jsonl.icloud', a.dir / 'events-000001.jsonl')
        self.assertEqual([e['data']['work'] for e in b.read(cursors, now=1001)[0]], ['01', '02'])

    def test_episode_event_validation(self):
        good = {'works': ['ab'], 'dest': 'ab', 'outcome': 'unresolved', 'until': 5, 'archive': 4, 'sender': False}
        self.assertTrue(meshjournal.valid_episode(good))
        for bad in ({**good, 'works': []}, {**good, 'outcome': 'matched'}, {**good, 'until': True}, {**good, 'sender': 'ja'}, {**good, 'works': ['x' * 65]}):
            self.assertFalse(meshjournal.valid_episode(bad))

    def test_cloud_folders_are_found_without_creating_anything(self):
        home = self.base / 'home'
        (home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs').mkdir(parents=True)
        (home / 'Library' / 'CloudStorage' / 'GoogleDrive-x@y' / 'Meine Ablage').mkdir(parents=True)
        (home / 'Library' / 'CloudStorage' / 'OneDrive-Persönlich').mkdir(parents=True)
        found = meshjournal.cloud_folders(home)
        self.assertEqual([f['label'] for f in found], ['iCloud Drive', 'Google Drive', 'OneDrive'])
        self.assertTrue(all(f['path'].endswith('/MediathekAtlas-Verbund') and not f['exists'] for f in found))
        self.assertFalse((home / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs' / 'MediathekAtlas-Verbund').exists())
        self.assertEqual(meshjournal.cloud_folders(self.base / 'empty'), [])


class Node:
    def __init__(self, root, shared, archive=None, **config):
        self.root = Path(root); self.root.mkdir(exist_ok=True)
        self.config = {'auto_metadata': True, 'mesh_dir': str(shared), 'episode_workers': 2, 'metadata_workers': 2,
                       'sender_direct_lookup': False, 'scan_priority': 'series_first', 'complete_series': False, **config}
        with self.db() as c: c.executescript(catalog.SCHEMA)
        self.service = catalog_service.Service(self.db, lambda: self.config, threading.Event(), self.root)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.root / 'c.db', timeout=20); c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()

    def sync(self):
        self.service.mesh_beat = 0
        if self.service.mesh: self.service.mesh.flush(force=True)
        self.service.mesh_tick()

    def series(self, title, topic, tag):
        src = episodes.offer(title, topic, tag)
        with self.db() as c:
            catalog.ingest(c, [src])
            row = c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.url_video')=?", (src['url_video'],)).fetchone()
            m = json.loads(row['meta']); m.update(kind='series', title=topic, provider='TMDB', reference_id='77', year=2017, episode_verified=False)
            catalog.save_metadata(c, row['id'], m, 'identified')
            return row['id']

    def work(self, wid):
        with self.db() as c:
            row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            return row['state'], json.loads(row['meta'])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name); self.shared = self.base / 'cloud' / 'MediathekAtlas-Verbund'; self.shared.mkdir(parents=True)
        meshjournal.check_folder(self.shared, create=True)
        self.a = Node(self.base / 'a', self.shared); self.b = Node(self.base / 'b', self.shared)

    def join(self):
        for _ in range(2):
            for n in (self.a, self.b): n.sync()

    def archive(self):
        arch = episodes.build_archive(self.base)
        self.addCleanup(lambda: getattr(arch._reader_local, 'opened', None) and arch._reader_local.opened[1].close())
        return arch

    def test_cloud_folder_uses_local_staging(self):
        self.join()
        self.assertTrue(self.a.service.mesh_status['staged'])
        self.assertTrue((self.base / 'a' / 'verbund-staging').is_dir())
        self.assertEqual(self.a.service.mesh_status['episode_partitions'] + self.b.service.mesh_status['episode_partitions'], 256)

    def test_confirmed_episode_is_taken_over_without_search(self):
        arch = self.archive()
        wa = self.a.series('Folge 12: Das Vorsprechen', 'Find me in Paris', 'x1')
        wb = self.b.series('Folge 12: Das Vorsprechen', 'Find me in Paris', 'x1')
        self.assertEqual(wa, wb)
        self.join()
        with patch.object(imdb_archive, 'ACTIVE', arch):
            self.a.service.mesh_episode_filter = None
            self.assertTrue(self.a.service.metadata_once('episode'))
        self.assertEqual(self.matched(self.a)[0][0], 'matched')
        self.a.sync(); self.b.sync()
        rows = self.matched(self.b)
        self.assertEqual(len(rows), 1)
        state, meta = rows[0]
        self.assertEqual((state, meta['season'], meta['episode']), ('matched', 1, 12))
        self.assertEqual(self.b.service.mesh_saved['episodes'], 1)
        with self.b.db() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 0)

    def matched(self, node):
        with node.db() as c: return [(r['state'], json.loads(r['meta'])) for r in c.execute("SELECT * FROM works WHERE state='matched'")]

    def _ids(self, node):
        with node.db() as c: return [r[0] for r in c.execute('SELECT id FROM works')]

    def test_no_episode_found_is_not_searched_again(self):
        arch = self.archive()
        wa = self.a.series('Ein ganz anderer Titel', 'Find me in Paris', 'x2')
        wb = self.b.series('Ein ganz anderer Titel', 'Find me in Paris', 'x2')
        self.join()
        with patch.object(imdb_archive, 'ACTIVE', arch):
            self.a.service.mesh_episode_filter = None
            self.assertTrue(self.a.service.metadata_once('episode'))
        with self.a.db() as c: self.assertEqual(c.execute('SELECT last_outcome FROM episode_queue WHERE work_id=?', (wa,)).fetchone()[0], 'unresolved')
        self.a.sync(); self.b.sync()
        with patch.object(imdb_archive, 'ACTIVE', arch), patch.object(arch, 'episode_evidence', side_effect=AssertionError('searched twice')):
            self.b.service.mesh_episode_filter = None
            self.assertTrue(self.b.service._episode_once_claimed(wb))
        with self.b.db() as c:
            q = c.execute('SELECT * FROM episode_queue WHERE work_id=?', (wb,)).fetchone()
        self.assertEqual(q['last_outcome'], 'unresolved_remote'); self.assertGreater(q['next_try'], time.time() + 86400)
        self.assertEqual(self.b.service.mesh_saved['episodes_skipped'], 1)
        # A newer IMDb archive here, or the sender lookup only switched on here, searches anyway.
        with self.b.db() as c:
            c.execute('UPDATE episode_queue SET next_try=0')
            row = c.execute('SELECT * FROM works WHERE id=?', (wb,)).fetchone()
            self.assertFalse(self.b.service.mesh_episode_skip(c, row, arch.updated + 10, False))
            self.assertFalse(self.b.service.mesh_episode_skip(c, row, arch.updated, True))
            self.assertTrue(self.b.service.mesh_episode_skip(c, row, arch.updated, False))

    def test_older_node_keeps_episode_search_here(self):
        self.join()
        # An older version announces no shares: works are split, episodes stay complete here.
        node = self.b.service.mesh.dir / 'node.json'
        info = json.loads(node.read_text()); info.pop('shares'); node.write_text(json.dumps(info))
        self.a.sync()
        self.assertLess(self.a.service.mesh_status['partitions'], 256)
        self.assertIsNone(self.a.service.mesh_episode_filter)
        self.assertEqual(self.a.service.mesh_status['episode_partitions'], 256)

    def test_local_manual_assignment_is_never_replaced(self):
        src = {'title': 'Spielfilm', 'channel': 'ARD', 'topic': 'Spielfilm', 'description': 'Spielfilm Deutschland, lange Beschreibung', 'duration': 5400, 'url_video': 'https://example.org/f.mp4'}
        for n in (self.a, self.b):
            with n.db() as c: catalog.ingest(c, [src])
        self.join()
        wid = self._ids(self.a)[0]
        with self.a.db() as c: catalog.save_metadata(c, wid, {'title': 'Mein Film', 'kind': 'movie', 'year': 2001, 'state': 'user_confirmed'})
        with self.b.db() as c:
            theirs = {'title': 'Anderer Film', 'kind': 'movie', 'year': 1999, 'provider': 'TMDB', 'reference_id': '42', 'state': 'user_confirmed'}
            self.b.service.mesh_manual(c, wid, catalog.save_metadata(c, wid, theirs) or wid, theirs)
        self.b.sync(); self.a.sync()
        with self.a.db() as c:
            row = c.execute("SELECT * FROM works WHERE state='manual'").fetchone()
        self.assertEqual(json.loads(row['meta'])['title'], 'Mein Film')
        conflicts = self.a.service.mesh_conflicts()
        self.assertEqual(len(conflicts), 1); self.assertEqual(self.a.service.mesh_status['conflicts'], 1)
        self.assertEqual((conflicts[0]['mine']['title'], conflicts[0]['theirs']['title']), ('Mein Film', 'Anderer Film'))
        # Keep: nothing changes. Adopt (second round): the other system's assignment is used.
        self.a.service.mesh_resolve(conflicts[0]['work'], 'keep')
        self.assertEqual(self.a.service.mesh_conflicts(), [])
        with self.a.db() as c:
            event = json.loads(c.execute('SELECT payload FROM mesh_results').fetchone()[0])
            self.assertTrue(self.a.service.mesh_conflict(c, c.execute("SELECT * FROM works WHERE state='manual'").fetchone(), event))
        dest = self.a.service.mesh_resolve(conflicts[0]['work'], 'adopt')
        self.assertEqual(self.a.work(dest), ('manual', self.a.work(dest)[1])); self.assertEqual(self.a.work(dest)[1]['title'], 'Anderer Film')

    def test_same_manual_assignment_is_no_conflict(self):
        src = {'title': 'Spielfilm', 'channel': 'ARD', 'topic': 'Spielfilm', 'description': 'Spielfilm Deutschland, lange Beschreibung', 'duration': 5400, 'url_video': 'https://example.org/g.mp4'}
        for n in (self.a, self.b):
            with n.db() as c: catalog.ingest(c, [src])
        self.join(); wid = self._ids(self.a)[0]
        meta = {'title': 'Gleich', 'kind': 'movie', 'year': 2001, 'state': 'user_confirmed'}
        with self.a.db() as c: catalog.save_metadata(c, wid, meta)
        with self.b.db() as c: self.b.service.mesh_manual(c, wid, catalog.save_metadata(c, wid, meta) or wid, meta)
        self.b.sync(); self.a.sync()
        self.assertEqual(self.a.service.mesh_conflicts(), [])

    def test_copied_data_folder_gets_its_own_node(self):
        self.join(); node = self.a.service.mesh.node
        with self.a.db() as c: catalog.set_state(c, 'mesh_node_host', 'another-computer')
        self.a.service.mesh_off(); self.a.sync()
        self.assertNotEqual(self.a.service.mesh.node, node)
        # Upgrade case: no host stored yet, but a fresh heartbeat of another computer under this ID.
        node = self.a.service.mesh.node
        info = json.loads((self.a.service.mesh.dir / 'node.json').read_text()); info.update(host='0' * 16, time=int(time.time()))
        (self.a.service.mesh.dir / 'node.json').write_text(json.dumps(info))
        with self.a.db() as c: c.execute("DELETE FROM catalog_state WHERE key='mesh_node_host'")
        self.a.service.mesh_off(); self.a.sync()
        self.assertNotEqual(self.a.service.mesh.node, node)
        # Same computer again: the ID stays.
        node = self.a.service.mesh.node; self.a.service.mesh_off(); self.a.sync()
        self.assertEqual(self.a.service.mesh.node, node)


if __name__ == '__main__':
    unittest.main()


class SlimJournalTests(unittest.TestCase):
    """0.6.53 after the Mac check (20.11.2026): 6.4 KB per result, segments up to 13 MB, 1.6 GB per device."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name); self.root = self.base / 'shared'; self.root.mkdir()
        meshjournal.check_folder(self.root, create=True)

    def big_meta(self):
        sugg = {'provider': 'TMDB', 'reference_id': '1', 'kind': 'series', 'title': 'Tatort', 'year': 1970, 'similarity': .9,
                'description': 'x' * 2000, 'show_credits': {'cast': ['Name %d' % i for i in range(60)]}}
        return {'title': 'Tatort', 'kind': 'series', 'year': 1970, 'provider': 'TMDB', 'reference_id': '13', 'imdb_id': 'tt0806910',
                'season': 3, 'episode': 4, 'episode_title': 'Folge', 'genres': ['Krimi', 'Drama'], 'state': 'auto_matched',
                'description': 'Beschreibung ' * 200, 'show_description': 'Serie ' * 300, 'show_credits': {'cast': ['Person %d' % i for i in range(80)]},
                'poster': 'https://image.example/' + 'p' * 80, 'ratings': [{'source': 'IMDb', 'value': '7.1'}] * 5,
                'suggestions': [sugg] * 10, 'metadata_warnings': ['x']}

    def test_result_event_is_a_few_hundred_bytes(self):
        j = meshjournal.Journal(self.root, 'a' * 32)
        event = j.append('match.result', {'work': 'w' * 28, 'dest': 'd' * 28, 'outcome': 'matched',
                                          'meta': meshjournal.share_meta(self.big_meta(), 'matched'), 'providers': ['TMDB']})
        size = len(json.dumps(event, ensure_ascii=False, separators=(',', ':')))
        self.assertLess(size, 700, size)
        for gone in ('description', 'show_description', 'show_credits', 'poster', 'ratings', 'suggestions', 'metadata_warnings'):
            self.assertNotIn(gone, event['data']['meta'])
        self.assertIsNotNone(meshjournal.clean_meta(event['data']['meta']))   # older receivers accept it too
        review = meshjournal.share_meta(self.big_meta(), 'review')
        self.assertEqual(len(review['suggestions']), 3)
        self.assertNotIn('description', review['suggestions'][0])
        self.assertLess(len(json.dumps(review)), 900)

    def test_segment_limit_holds_within_a_round(self):
        j = meshjournal.Journal(self.root, 'a' * 32)
        with patch.object(meshjournal, 'SEGMENT_BYTES', 2000):
            for i in range(40): j.append('match.result', event_data('%02d' % i))
        files = sorted(j.dir.glob('events-*.jsonl'))
        self.assertGreater(len(files), 3)
        self.assertTrue(all(f.stat().st_size <= 2000 for f in files), [f.stat().st_size for f in files])
        j.flush(force=True)
        events, _, _ = meshjournal.Journal(self.root, 'b' * 32).read({})
        self.assertEqual([e['data']['work'] for e in events], ['%02d' % i for i in range(40)])

    def test_compressed_segments_are_read_and_mirrored(self):
        a = meshjournal.Journal(self.root, 'a' * 32); a.compress = True
        a.append('match.result', event_data('01')); a.flush(force=True)
        a.compress = False
        a.append('match.result', event_data('02')); a.flush(force=True)
        self.assertEqual(sorted(p.name for p in a.dir.iterdir()), ['events-000001.jsonl.gz', 'events-000002.jsonl'])
        events, _, _ = meshjournal.Journal(self.root, 'b' * 32).read({})
        self.assertEqual([e['data']['work'] for e in events], ['01', '02'])
        again = meshjournal.Journal(self.root, 'a' * 32); self.assertEqual((again.seq, again.segment), (2, 3))
        import meshpeer
        self.assertTrue(meshpeer.safe_path('nodes/%s/events-000001.jsonl.gz' % ('a' * 32)))
        self.assertEqual(a.usage()['files'], 2)

    def test_default_name_has_no_computer_name(self):
        with patch('platform.node', return_value='ITSO-adms-MacBook-Pro.local'):
            name = meshjournal.default_name('salt'); fp = meshjournal.host_id('salt')
        self.assertNotIn('ITSO', name); self.assertNotIn('adms', name)
        with patch('platform.node', return_value='ITSO-adms-MacBook-Pro.local'):
            self.assertNotEqual(meshjournal.host_id('other'), fp)


class SlimServiceTests(ServiceTests):
    def test_receiver_keeps_its_own_offer_data(self):
        src = {'title': 'Spielfilm', 'channel': 'ARD', 'topic': 'Spielfilm', 'description': 'Eigene Senderbeschreibung, lang genug', 'duration': 5400, 'url_video': 'https://example.org/k.mp4'}
        for n in (self.a, self.b):
            with n.db() as c: catalog.ingest(c, [src])
        self.join(); wid = self._ids(self.a)[0]
        with self.a.db() as c:
            meta = {'title': 'Der Film', 'kind': 'movie', 'year': 2001, 'provider': 'TMDB', 'reference_id': '9', 'description': 'TMDB-Text ' * 100, 'state': 'auto_matched'}
            dest = catalog.save_metadata(c, wid, meta, 'matched') or wid
            self.a.service.mesh_publish(c, 'match.result', wid, dest, 'matched', meta, ['TMDB'])
        self.a.sync(); self.b.sync()
        with self.b.db() as c:
            row = c.execute("SELECT * FROM works WHERE state='matched'").fetchone()
        m = json.loads(row['meta'])
        self.assertEqual((m['title'], m['reference_id']), ('Der Film', '9'))
        self.assertEqual(m['description'], 'Eigene Senderbeschreibung, lang genug')

    def test_compression_only_when_every_system_reads_it(self):
        self.join()
        self.assertTrue(self.a.service.mesh.compress)
        node = self.b.service.mesh.dir / 'node.json'
        info = json.loads(node.read_text()); info['shares'] = ['episodes']; node.write_text(json.dumps(info))
        self.a.sync(); self.assertFalse(self.a.service.mesh.compress)

    def test_backfill_pauses_at_the_size_limit(self):
        self.join()
        self.a.service.MESH_BACKFILL_PAUSE = 0
        self.a.service.mesh_usage = {'own': 400 * 1024 * 1024, 'total': 1, 'files': 1, 'at': time.monotonic()}
        self.assertEqual(self.a.service.mesh_backfill(self.a.service.mesh), 0)
        self.assertEqual(self.a.service.mesh_backlog['paused'], 'size')
        self.a.config['mesh_journal_mb'] = 1000
        self.a.service.mesh_backfill(self.a.service.mesh)
        self.assertFalse(self.a.service.mesh_backlog.get('paused'))
