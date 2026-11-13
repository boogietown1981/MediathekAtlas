"""0.5.94: Umwandeln fertiger Downloads in 1080p, 720p oder 480p (encoder.py)."""
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import encoder  # noqa: E402
from tests._wiring import wired  # noqa: E402

FFMPEG, FFPROBE = shutil.which('ffmpeg'), shutil.which('ffprobe')
INFO = {'height': 1080, 'width': 1920, 'duration': 600.0, 'video_codec': 'h264', 'audio': 2, 'subtitles': []}


def has_x264():
    if not FFMPEG or not FFPROBE:
        return False
    return b'libx264' in subprocess.run([FFMPEG, '-hide_banner', '-encoders'], capture_output=True).stdout


class PureTests(unittest.TestCase):
    def test_probe_facts(self):
        doc = {'format': {'duration': '5400.5'}, 'streams': [
            {'codec_type': 'video', 'codec_name': 'mjpeg', 'height': 600, 'width': 400, 'disposition': {'attached_pic': 1}},
            {'codec_type': 'video', 'codec_name': 'hevc', 'height': 2160, 'width': 3840}, {'codec_type': 'audio'}, {'codec_type': 'audio'},
            {'codec_type': 'subtitle', 'codec_name': 'subrip'}]}
        self.assertEqual(encoder.read_probe(doc), {'height': 2160, 'width': 3840, 'duration': 5400.5, 'video_codec': 'hevc', 'audio': 2, 'subtitles': ['subrip']})
        for bad in ({}, {'streams': [{'codec_type': 'audio'}]}, None):
            with self.assertRaises(ValueError):
                encoder.read_probe(bad)

    def test_never_larger_than_the_source(self):
        self.assertEqual(encoder.plan(INFO, '720')['height'], 720)
        for profile, message in (('1080', 'bereits 1080p'), ('2160', 'Unbekannte'), ('', 'Unbekannte')):
            with self.assertRaisesRegex(ValueError, message):
                encoder.plan(INFO, profile)
        with self.assertRaisesRegex(ValueError, 'bereits 480p'):
            encoder.plan(dict(INFO, height=480), '720')
        with self.assertRaisesRegex(ValueError, 'nicht lesbar'):
            encoder.plan(dict(INFO, duration=0), '480')

    def test_target_and_command(self):
        self.assertEqual(encoder.target_path('/dl/Film (1999).mp4', '720').name, 'Film (1999) [720p].mkv')
        self.assertEqual(encoder.target_path('/dl/Film (1999).mp4', '720', replace=True).name, 'Film (1999).mkv')
        args = encoder.command('ffmpeg', '/dl/a.mkv', '/dl/a [480p].mkv.partial', INFO, '480', 'balanced')
        text = ' '.join(args)
        for part in ('-map 0:v:0 -map 0:a? -map 0:s?', '-vf scale=-2:480', '-c:v libx264 -preset medium -crf 23', '-c:a copy', '-c:s copy', '-f matroska', '-progress pipe:1'):
            self.assertIn(part, text)
        self.assertEqual(args[-1], '/dl/a [480p].mkv.partial')
        self.assertIn('-c:s srt', ' '.join(encoder.command('ffmpeg', 'a.mp4', 'b', dict(INFO, subtitles=['mov_text']), '720')))
        self.assertIn('-preset veryfast', ' '.join(encoder.command('ffmpeg', 'a.mp4', 'b', INFO, '720')))

    def test_verify_and_progress(self):
        good = dict(INFO, height=720, duration=599.2)
        self.assertEqual(encoder.verify(INFO, good, '720'), '')
        self.assertIn('Laufzeit', encoder.verify(INFO, dict(good, duration=300), '720'))
        self.assertIn('statt 720p', encoder.verify(INFO, dict(good, height=1080), '720'))
        self.assertIn('Tonspuren', encoder.verify(INFO, dict(good, audio=1), '720'))
        self.assertEqual(encoder.progress_of('out_time_us=300000000\n', 600.0), 0.5)
        self.assertEqual(encoder.progress_of('out_time_us=900000000', 600.0), 1.0)
        for line in ('frame=10', 'out_time_us=N/A', 'progress=continue'):
            self.assertIsNone(encoder.progress_of(line, 600.0))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'Film.mp4'
        self.video.write_bytes(b'x' * 1000)
        self.tools = {'ffmpeg': '/bin/ffmpeg', 'ffprobe': '/bin/ffprobe'}
        patch = mock.patch.object(encoder, 'probe', lambda ffprobe, path: dict(INFO))
        patch.start()
        self.addCleanup(patch.stop)
        self.job = {'id': 'j1', 'path': str(self.video), 'metadata': {'title': 'Ein Film'}}

    def test_add_list_cancel_clear(self):
        made = encoder.add(self.root, self.job, '720', self.tools, now=1)
        self.assertEqual((made['target'], made['source_height']), ('Film [720p].mkv', 1080))
        listed = encoder.listing(self.root, self.tools)
        self.assertEqual((listed['active'], listed['available'], [p['id'] for p in listed['profiles']]), (1, True, ['1080', '720', '480']))
        row = listed['jobs'][0]
        self.assertEqual((row['title'], row['file'], row['target'], row['state'], row['replace'], row['label']), ('Ein Film', 'Film.mp4', 'Film [720p].mkv', 'queued', False, 'HD (720p)'))
        self.assertNotIn(str(self.root), str(listed))   # no local paths leave the server
        with self.assertRaisesRegex(ValueError, 'bereits umgewandelt'):
            encoder.add(self.root, self.job, '480', self.tools)
        encoder.cancel(self.root, row['id'])
        self.assertEqual(encoder.listing(self.root)['jobs'][0]['state'], 'cancelled')
        with self.assertRaisesRegex(ValueError, 'läuft nicht mehr'):
            encoder.cancel(self.root, row['id'])
        self.assertEqual(encoder.clear(self.root), {'removed': 1})
        self.assertEqual(encoder.listing(self.root)['available'], False)

    def test_refusals(self):
        for job, profile, tools, kwargs, message in (
                (self.job, '720', {}, {}, 'fehlen FFmpeg'),
                (self.job, '1080', self.tools, {}, 'bereits 1080p'),
                (self.job, '720', self.tools, {'speed': 'turbo'}, 'Tempo'),
                ({'id': 'x', 'path': str(self.root / 'weg.mp4')}, '720', self.tools, {}, 'nicht mehr am gespeicherten Ort'),
                ({'id': 'x', 'path': str(self.root)}, '720', self.tools, {}, 'nicht mehr am gespeicherten Ort')):
            with self.assertRaisesRegex(ValueError, message):
                encoder.add(self.root, job, profile, tools, **kwargs)
        # An unrelated file with the result's name is never overwritten, with or without "replace".
        (self.root / 'Film.mkv').write_bytes(b'anderer film')
        (self.root / 'Film [720p].mkv').write_bytes(b'schon da')
        for replace in (False, True):
            with self.assertRaisesRegex(ValueError, 'gibt es bereits'):
                encoder.add(self.root, self.job, '720', self.tools, replace=replace)
        with mock.patch.object(encoder.shutil, 'disk_usage', lambda p: mock.Mock(free=10)):
            with self.assertRaisesRegex(ValueError, 'Zu wenig freier Platz'):
                encoder.add(self.root, self.job, '480', self.tools)
        self.assertEqual(encoder.listing(self.root)['jobs'], [])

    def test_an_interrupted_conversion_starts_again(self):
        encoder.add(self.root, self.job, '720', self.tools)
        worker = encoder.Worker(self.root, lambda: self.tools)
        task = worker.claim()
        partial = Path(task['target'] + '.partial')
        partial.write_bytes(b'halb')
        worker._set(task['id'], progress=0.4)
        worker.recover()
        row = encoder.listing(self.root)['jobs'][0]
        self.assertEqual((row['state'], row['progress'], partial.exists(), self.video.exists()), ('queued', 0, False, True))


@unittest.skipUnless(has_x264(), 'ffmpeg with libx264 and ffprobe are needed')
class RealConversionTests(unittest.TestCase):
    """With the real ffmpeg: a two-second 720p clip with two sound tracks."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.tmp.name) / 'quelle.mp4'
        subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=1280x720:rate=25:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2',
                        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-shortest', str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(dir=self.tmp.name))
        self.tools = {'ffmpeg': FFMPEG, 'ffprobe': FFPROBE}
        self.replaced, self.events = [], []
        self.worker = encoder.Worker(self.dir, lambda: self.tools, lambda *a: self.replaced.append(a), lambda name, **kw: self.events.append((name, kw)))

    def video(self, name):
        target = self.dir / name
        shutil.copy(self.source, target)
        return target

    def test_copy_beside_the_original(self):
        video = self.video('Film.mp4')
        encoder.add(self.dir, {'id': 'j1', 'path': str(video)}, '480', self.tools)
        self.assertEqual(self.worker.run_one(), 'done')
        self.assertIsNone(self.worker.run_one())
        result = self.dir / 'Film [480p].mkv'
        info = encoder.probe(FFPROBE, result)
        self.assertEqual((info['height'], info['width'], info['audio'], info['video_codec']), (480, 854, 2, 'h264'))
        self.assertTrue(video.exists())
        self.assertFalse(Path(str(result) + '.partial').exists())
        self.assertEqual(self.replaced, [])
        row = encoder.listing(self.dir)['jobs'][0]
        self.assertEqual((row['state'], row['progress'], row['result_bytes']), ('done', 1.0, result.stat().st_size))
        self.assertEqual((self.events[0][0], self.events[0][1]['state'], self.events[0][1]['replaced']), ('encoder_finished', 'done', False))

    def test_replace_only_after_the_check(self):
        video = self.video('Film.mp4')
        encoder.add(self.dir, {'id': 'j1', 'path': str(video)}, '480', self.tools, replace=True)
        self.assertEqual(self.worker.run_one(), 'done')
        result = self.dir / 'Film.mkv'
        self.assertEqual((video.exists(), encoder.probe(FFPROBE, result)['height']), (False, 480))
        self.assertEqual(self.replaced, [('j1', str(video), str(result))])
        # An MKV original is replaced under its own name.
        mkv = self.dir / 'Zwei.mkv'
        subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-i', str(self.source), '-map', '0', '-c', 'copy', str(mkv)], check=True)
        encoder.add(self.dir, {'id': 'j2', 'path': str(mkv)}, '480', self.tools, replace=True)
        self.assertEqual(self.worker.run_one(), 'done')
        self.assertEqual((encoder.probe(FFPROBE, mkv)['height'], self.replaced[-1]), (480, ('j2', str(mkv), str(mkv))))

    def test_a_rejected_result_leaves_the_original(self):
        video = self.video('Film.mp4')
        encoder.add(self.dir, {'id': 'j1', 'path': str(video)}, '480', self.tools, replace=True)
        with mock.patch.object(encoder, 'verify', lambda *a: 'Laufzeit weicht ab'):
            self.assertEqual(self.worker.run_one(), 'error')
        row = encoder.listing(self.dir)['jobs'][0]
        self.assertEqual((row['state'], video.exists(), sorted(p.name for p in self.dir.glob('Film*'))), ('error', True, ['Film.mp4']))
        self.assertIn('verworfen', row['error'])
        self.assertEqual(self.replaced, [])
        # A broken source fails with a reason and the queue goes on.
        broken = self.dir / 'Kaputt.mp4'
        encoder.add(self.dir, {'id': 'j3', 'path': str(self.video('Gut.mp4'))}, '480', self.tools)
        with mock.patch.object(encoder, 'probe', lambda ffprobe, path: dict(INFO)):
            broken.write_bytes(b'kein video')
            encoder.add(self.dir, {'id': 'j2', 'path': str(broken)}, '480', self.tools)
        self.assertEqual([self.worker.run_one(), self.worker.run_one()], ['done', 'error'])
        self.assertTrue(broken.exists())

    def test_cancel_and_app_shutdown(self):
        video = self.video('Film.mp4')
        made = encoder.add(self.dir, {'id': 'j1', 'path': str(video)}, '480', self.tools)
        with mock.patch.object(self.worker, '_cancelled', lambda encode_id: True), mock.patch.object(encoder.time, 'time', side_effect=iter(range(0, 100000, 10))):
            state = self.worker.run_one()
        self.assertIn(state, ('cancelled', 'done'))       # a two-second clip may finish before the first progress line
        if state == 'cancelled':
            self.assertEqual(sorted(p.name for p in self.dir.glob('Film*')), ['Film.mp4'])
        self.assertTrue(made['id'])


class WiringTests(unittest.TestCase):
    def test_routes_and_package(self):
        for needle in ("'/api/encoder'", "'/api/encoder-add'", "'/api/encoder-cancel'", "'/api/encoder-clear'"):
            self.assertTrue(wired(needle), needle)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("name='encoder'", server)
        self.assertIn("Original ersetzen nur nach Bestätigung", server)
        self.assertIn("'encoder.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn("api('encoder-add'", (ROOT / 'web' / 'storage.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
