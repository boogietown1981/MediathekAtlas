"""0.6.7 (Björn, 14.11.2026): YouTube-Kanäle abonnieren; je Abo einstellbar, was automatisch offline
geladen wird (nur neue, alle, eine Reihe), neue Videos als „neu“ markiert, Kinderecke mit Vollbild.
Synthetische Data-API- und yt-dlp-Antworten im dokumentierten Format."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube as yt, youtube_downloads as yd, youtube_abos as ab, downloads, watch_state  # noqa: E402
import netzkino_downloads as nd  # noqa: E402
from _wiring import routed, SERVER  # noqa: E402
from test_v0553_youtube import video, vid  # noqa: E402

NOW = 1_800_000_000
UPLOADS = 'UU' + 'k' * 22
KIDS = {n: video(n, 'Bluey Folge %d' % n if n % 2 else 'Lustige Tiere %d' % n, 420 + n, channel='Kinderkanal') for n in range(30, 40)}
KIDS[39] = video(39, 'Kurz #shorts', 40, channel='Kinderkanal')
for n, v in KIDS.items():                      # neuere Videos haben spätere Daten
    v['snippet']['publishedAt'] = '2026-11-%02dT08:00:00Z' % (n - 29)


class KidsApi:
    def __init__(self):
        self.order = list(range(38, 29, -1))      # Uploads-Playlist: neueste zuerst
        self.calls = []

    def __call__(self, endpoint, query):
        self.calls.append(endpoint)
        if endpoint == 'channels':
            return {'items': [{'id': 'UC' + 'k' * 22, 'snippet': {'title': 'Kinderkanal', 'thumbnails': {
                'high': {'url': 'https://yt3.ggpht.com/avatar=s240'}}},
                'contentDetails': {'relatedPlaylists': {'uploads': UPLOADS}}}]}
        if endpoint == 'playlistItems':
            return {'items': [{'snippet': {'position': i}, 'contentDetails': {'videoId': vid(n)}} for i, n in enumerate(self.order)]}
        if endpoint == 'videos':
            wanted = query['id'].split(',')
            return {'items': [v for v in KIDS.values() if v['id'] in wanted]}
        raise AssertionError(endpoint)


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.downloads = self.root / 'Downloads'
        self.downloads.mkdir()
        self.catalog = self.root / 'catalog.db'
        with self.db() as c:
            c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        ab.configure(db=self.db, settings=lambda: {'download_dir': str(self.downloads)})
        self.addCleanup(ab.configure, None, lambda: {})
        self.addCleanup(setattr, ab, '_DB', None)
        yd.set_enabled(self.root, True, confirmed=True)
        self.addCleanup(yd._ENABLED.update, value=False)
        self.api = KidsApi()
        mock.patch.object(ab, '_cache_avatar', lambda root, abo, fetch=None: False).start()
        self.addCleanup(mock.patch.stopall)

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.catalog)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def jobs(self):
        with self.db() as c:
            return [dict(json.loads(r[0]), _state=r[1]) for r in c.execute('SELECT payload,state FROM jobs')]

    def videos(self, abo_id):
        db = ab._connect(self.root)
        try:
            return {r['video']: dict(r) for r in db.execute('SELECT * FROM youtube_abo_videos WHERE abo_id=?', (abo_id,))}
        finally:
            db.close()

    def set_job(self, job_id, state, **extra):
        with self.db() as c:
            payload = json.loads(c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()[0])
            payload.update(state=state, **extra)
            c.execute('UPDATE jobs SET payload=?,state=? WHERE id=?', (json.dumps(payload), state, job_id))


class ParseTests(unittest.TestCase):
    def test_channel_playlist_and_no_single_video(self):
        self.assertEqual(ab.parse('https://www.youtube.com/@Kinderkanal/videos'), ('@Kinderkanal', 'channel'))
        self.assertEqual(ab.parse('youtube.com/playlist?list=PLabcdefghijkl'), ('PLabcdefghijkl', 'playlist'))
        with self.assertRaises(ValueError):
            ab.parse('https://youtu.be/' + vid(31))
        with self.assertRaises(ValueError):
            ab.parse('https://example.org/@x')

    def test_settings_are_bounded(self):
        clean = ab._clean({'mode': 'all', 'keep': 9999, 'interval_hours': 5, 'quality': '720', 'include': 'Bluey; Folge'})
        self.assertEqual((clean['keep'], clean['interval_hours'], clean['include']), (500, 6, 'bluey, folge'))
        with self.assertRaises(ValueError):
            ab._clean({'mode': 'alles'})
        with self.assertRaises(ValueError):
            ab._clean({'quality': '4320'})


class CheckTests(Fixture):
    def test_new_only_takes_newest_start_count_then_only_new_uploads(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 3}, now=NOW)
        result = ab.check(self.root, abo, now=NOW, request=self.api)
        self.assertTrue(result['ok'], result)
        states = self.videos(abo)
        wanted = {v for v, r in states.items() if r['state'] in ('queued', 'done')}
        self.assertEqual(wanted, {vid(38), vid(37), vid(36)})                  # die 3 neuesten
        self.assertEqual(sum(1 for r in states.values() if r['state'] == 'old'), 6)
        jobs = self.jobs()
        self.assertEqual(len(jobs), 3)
        job = jobs[0]
        self.assertEqual(job['origin'], 'youtube')
        self.assertEqual(job['youtube_abo'], abo)
        self.assertEqual(job['quality'], '720')
        self.assertEqual(job['source']['_container'], 'mp4')
        self.assertTrue(job['source']['_target'].startswith(str(self.downloads / 'YouTube-Abos' / 'Kinderkanal')))
        self.assertTrue(job['target'].endswith('[%s].mp4' % job['source']['_video_id']))
        self.assertIn('Kinder', job['metadata']['genres'])
        self.assertEqual(job['license']['days'], yd.OFFLINE_DAYS)
        # Ein neues Video erscheint: nur dieses kommt dazu, als „neu“ gezählt.
        KIDS[40] = video(40, 'Bluey Folge 40', 500, channel='Kinderkanal')
        KIDS[40]['snippet']['publishedAt'] = '2026-11-20T08:00:00Z'
        self.addCleanup(KIDS.pop, 40)
        self.api.order.insert(0, 40)
        result = ab.check(self.root, abo, now=NOW + 3 * 3600, request=self.api)
        self.assertEqual((result['new'], result['queued']), (1, 1))
        self.assertEqual(len(self.jobs()), 4)
        self.assertEqual(self.videos(abo)[vid(30)]['state'], 'old')

    def test_all_mode_series_filter_and_shorts(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all', 'include': 'Bluey'}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        states = self.videos(abo)
        loaded = {v for v, r in states.items() if r['state'] == 'queued'}
        self.assertEqual(loaded, {vid(n) for n in (37, 35, 33, 31)})          # ungerade = „Bluey Folge“
        self.assertEqual(states[vid(36)]['reason'], 'passt nicht zur Reihe')
        # Filter entfernen: Ausgelassene werden neu bewertet.
        ab.change(self.root, abo, {'include': ''})
        ab.check(self.root, abo, now=NOW + 60, request=self.api)
        self.assertEqual(sum(1 for r in self.videos(abo).values() if r['state'] == 'queued'), 9)  # alle 9 (4 + 5 nachgeholt)

    def test_shorts_are_skipped(self):
        self.api.order.insert(0, 39)
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all'}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        self.assertEqual(self.videos(abo)[vid(39)]['state'], 'skipped')
        self.assertIn('kürzer', self.videos(abo)[vid(39)]['reason'])

    def test_switch_off_queues_nothing_and_says_so(self):
        yd._ENABLED['value'] = False
        with mock.patch.object(yd, 'enabled', return_value=False):
            abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2}, now=NOW)
            result = ab.check(self.root, abo, now=NOW, request=self.api)
        self.assertEqual(result['queued'], 0)
        self.assertIn('ausgeschaltet', result['note'])
        self.assertEqual(self.jobs(), [])
        self.assertEqual(sum(1 for r in self.videos(abo).values() if r['state'] == 'wanted'), 2)

    def test_expired_videos_are_never_loaded_again(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        job = self.jobs()[0]
        self.set_job(job['id'], 'done', path=str(self.downloads / 'x.mp4'))
        with self.db() as c:
            db = ab._connect(self.root)
            ab.sync_states(c, db, abo)
            db.close()
        self.assertEqual(self.videos(abo)[vid(38)]['state'], 'done')
        self.set_job(job['id'], 'expired')
        ab.check(self.root, abo, now=NOW + 99999, request=self.api)
        self.assertEqual(self.videos(abo)[vid(38)]['state'], 'expired')
        self.assertEqual(len(self.jobs()), 1)

    def test_keep_limit_removes_oldest_watched_only(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'keep': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = {j['source']['_video_id']: j for j in self.jobs()}
        for v, j in jobs.items():
            path = self.downloads / ('%s.mp4' % v)
            path.write_bytes(b'x')
            self.set_job(j['id'], 'done', path=str(path), offline_until=NOW + 86400)
        KIDS[41] = video(41, 'Bluey Folge 41', 500, channel='Kinderkanal')
        KIDS[41]['snippet']['publishedAt'] = '2026-11-21T08:00:00Z'
        self.addCleanup(KIDS.pop, 41)
        self.api.order.insert(0, 41)
        # Nichts gesehen: das neue wartet, nichts wird gelöscht.
        ab.check(self.root, abo, now=NOW + 3600, request=self.api)
        self.assertEqual(self.videos(abo)[vid(41)]['state'], 'wanted')
        # Das ältere ist gesehen: es macht Platz.
        watch_state.progress(self.root, 'job:' + jobs[vid(37)]['id'], pos=400, duration=427, done=True)
        ab.check(self.root, abo, now=NOW + 7200, request=self.api)
        states = self.videos(abo)
        self.assertEqual(states[vid(41)]['state'], 'queued')
        self.assertEqual(states[vid(37)]['state'], 'expired')
        self.assertEqual(states[vid(38)]['state'], 'done')
        self.assertFalse((self.downloads / ('%s.mp4' % vid(37))).exists())

    def test_list_failure_is_kept_on_the_abo(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal'}, now=NOW)
        broken = mock.Mock(side_effect=ValueError('Kanal nicht gefunden'))
        result = ab.check(self.root, abo, now=NOW, request=broken)
        self.assertFalse(result['ok'])
        row = ab.overview(self.root)['abos'][0]
        self.assertEqual(row['last_error'], 'Kanal nicht gefunden')
        self.assertEqual(row['next_check'], NOW + 3600)


class YtDlpListTests(Fixture):
    def test_listing_without_api_key(self):
        payload = {'channel': 'Kinderkanal', 'channel_id': 'UC' + 'k' * 22,
                   'thumbnails': [{'url': 'https://yt3.googleusercontent.com/banner', 'width': 1060, 'height': 175},
                                  {'url': 'https://yt3.googleusercontent.com/avatar', 'id': 'avatar_uncropped'}],
                   'entries': [{'id': vid(33), 'title': 'Bluey Folge 33', 'duration': 433.0, 'timestamp': 1_790_000_000},
                               {'id': vid(32), 'title': 'Live jetzt', 'live_status': 'is_live'},
                               {'id': 'kaputt', 'title': 'x'},
                               {'id': vid(31), 'title': 'Bluey Folge 31', 'duration': 431, 'upload_date': '20261101'}]}
        calls = []

        def runner(args, **kw):
            calls.append(args)
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')):
            info, videos = ab.list_with_ytdlp({'ref': '@Kinderkanal', 'kind': 'channel'}, 50, runner=runner, root=self.root)
        self.assertIn('https://www.youtube.com/@Kinderkanal/videos', calls[0])
        self.assertIn('--flat-playlist', calls[0])
        self.assertNotIn('--cookies', ' '.join(calls[0]))
        self.assertEqual(info['avatar'], 'https://yt3.googleusercontent.com/avatar')
        self.assertEqual([v['video'] for v in videos], [vid(33), vid(31)])
        self.assertEqual(videos[1]['published'], '2026-11-01T00:00:00Z')
        self.assertEqual(videos[0]['poster'], 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % vid(33))

    def test_check_uses_ytdlp_without_key(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'all'}, now=NOW)
        out = json.dumps({'channel': 'Kinderkanal', 'entries': [{'id': vid(33), 'title': 'Bluey 33', 'duration': 433}]})
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')):
            result = ab.check(self.root, abo, now=NOW, runner=lambda a, **k: types.SimpleNamespace(returncode=0, stdout=out, stderr=''))
        self.assertTrue(result['ok'], result)
        self.assertEqual(ab.overview(self.root)['abos'][0]['via'], 'yt-dlp')
        self.assertEqual(len(self.jobs()), 1)

    def test_no_tool_no_key_explains(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal'}, now=NOW)
        with mock.patch.object(yd, 'find_tool', return_value=None):
            result = ab.check(self.root, abo, now=NOW)
        self.assertIn('yt-dlp', result['error'])


class KidsViewTests(Fixture):
    def test_kids_lists_finished_videos_new_first(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'label': 'Lieblingskanal'}, now=NOW)
        hidden = ab.add(self.root, {'url': 'PLabcdefghijkl', 'mode': 'all', 'kids': False}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = self.jobs()
        for j in jobs:
            self.set_job(j['id'], 'done', path=str(self.downloads / 'a.mp4'))
        watch_state.progress(self.root, 'job:' + jobs[0]['id'], pos=100, duration=400)
        with self.db() as c:
            data = ab.kids(self.root, c)
        self.assertEqual([ch['name'] for ch in data['channels']], ['Lieblingskanal'])
        self.assertNotIn(hidden, [ch['id'] for ch in data['channels']])
        self.assertEqual(len(data['videos']), 2)
        self.assertEqual(data['videos'][0]['video'], vid(38))                 # neuestes zuerst
        started = next(v for v in data['videos'] if v['job'] == jobs[0]['id'])
        self.assertFalse(started['new'])
        self.assertGreater(started['progress'], 0)
        self.assertEqual(data['channels'][0]['new'], 1)

    def test_poster_and_avatar_files(self):
        film = self.downloads / 'Bluey - 720p - H264 AAC.mp4'
        film.write_bytes(b'x')
        (self.downloads / 'Bluey - 720p - H264 AAC-poster.jpg').write_bytes(b'\xff\xd8\xff')
        self.assertEqual(ab.poster_file({'path': str(film)}).name, 'Bluey - 720p - H264 AAC-poster.jpg')
        self.assertIsNone(ab.poster_file({}))
        self.assertTrue(ab._cache_avatar.__module__)        # gepatcht in setUp
        mock.patch.stopall()
        self.assertTrue(ab._cache_avatar(self.root, {'id': 4, 'avatar': 'https://yt3.ggpht.com/a'}, fetch=lambda u: b'\xff\xd8\xff' + b'0' * 10))
        self.assertTrue(ab.avatar_file(self.root, 4))
        self.assertFalse(ab._cache_avatar(self.root, {'id': 5, 'avatar': 'https://example.org/a.jpg'}, fetch=lambda u: b'\xff\xd8\xff'))


class DownloadTargetTests(unittest.TestCase):
    def test_abo_target_must_stay_inside_download_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = {'kind': 'movie', 'title': 'X'}
            inside = str(Path(tmp) / 'YouTube-Abos' / 'K' / 'a [x].mp4')
            self.assertEqual(downloads.planned_target(tmp, meta, {'_target': inside, '_container': 'mp4', '_id': 'y'}), Path(inside).resolve())
            for bad in (str(Path(tmp).parent / 'a.mp4'), str(Path(tmp) / '..' / 'b.mp4'), str(Path(tmp) / 'c.exe')):
                with self.assertRaises(ValueError):
                    downloads.planned_target(tmp, meta, {'_target': bad, '_container': 'mp4', '_id': 'y'})
            with self.assertRaises(ValueError):          # .mkv-Ziel passt nicht zu MP4
                downloads.planned_target(tmp, meta, {'_target': str(Path(tmp) / 'd.mkv'), '_container': 'mp4', '_id': 'y'})

    def test_remux_to_mp4_keeps_picture_and_sound_only(self):
        seen = []

        def run(args, **kw):
            seen.append(args)
            return types.SimpleNamespace(returncode=0, stderr=b'')
        with mock.patch.object(downloads, 'tool', return_value='ffmpeg'), mock.patch.object(downloads.subprocess, 'run', run), \
                mock.patch.object(downloads, 'probe', return_value={'format': {'duration': '10'}}):
            downloads.remux('in', 'out', {'kind': 'movie', 'title': 'T'}, container='mp4')
            downloads.remux('in', 'out', {'kind': 'movie', 'title': 'T'})
        mp4, mkv = seen
        self.assertEqual(mp4[mp4.index('-f') + 1], 'mp4')
        self.assertIn('+faststart', mp4)
        self.assertNotIn('0:s?', mp4)
        self.assertEqual(mkv[mkv.index('-f') + 1], 'matroska')
        self.assertIn('0:s?', mkv)


class WiringTests(unittest.TestCase):
    def test_routes_planner_and_pages(self):
        self.assertTrue(routed('/api/youtube-abos', 'GET'))
        self.assertTrue(routed('/api/youtube-abos', 'POST'))
        self.assertTrue(routed('/kinder', 'GET', 'signed'))
        self.assertTrue(routed('/api/kids', 'GET', 'api'))
        self.assertTrue(routed('/api/kids-image', 'GET', 'signed'))
        self.assertIn("planner.CatalogJob('youtube_abos',youtube_abos)", SERVER)
        self.assertIn("'/youtube_abos.js'", SERVER)
        index = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="youtube-abo-form"', index)
        self.assertIn('href="/kinder"', index)
        kids = (ROOT / 'web' / 'kids.html').read_text(encoding='utf-8')
        for needle in ('__TOKEN__', 'id="kids-video"', 'id="kids-close"', 'src="/kids.js"'):
            self.assertIn(needle, kids)
        script = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn('requestFullscreen', script)
        self.assertIn('webkitEnterFullscreen', script)
        self.assertIn("'watch-progress'", script)

    def test_planner_interface(self):
        self.assertFalse(ab.should_sync(Path(tempfile.gettempdir()) / 'nie-da'))   # ohne Warteschlange nichts
        for name in ('should_sync', 'start_sync', 'tick'):
            self.assertTrue(callable(getattr(ab, name)))


if __name__ == '__main__':
    unittest.main()
