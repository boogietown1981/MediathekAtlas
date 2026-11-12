"""0.5.34: Netzkino films play in the in-app player like Mediathek videos."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import streaming, ytdl_bridge  # noqa: E402
from test_v0532_netzkino_offline import ITEM, MOVIE, QueueFixture, next_page  # noqa: E402

MP4 = 'https://pmd.netzkino-seite.netzkino.de/hin-und-weg.mp4'


class PlaybackTests(QueueFixture):
    def setUp(self):
        super().setUp()
        streaming._NK_CACHE.clear()
        self.calls = []

    def resolver(self, url):
        self.calls.append(url)
        return {'url': MP4, 'duration': 5700}

    def test_online_mp4_is_played_directly_by_the_browser(self):
        source = streaming.resolve(self.c, netzkino=ITEM, root=self.state, resolver=self.resolver)
        self.assertEqual(self.calls, ['https://www.netzkino.de/details/hin-und-weg'])
        info = streaming.plan(source)
        self.assertEqual((info['mode'], info['origin'], info['url'], info['provider']),
                         ('direct', 'online', MP4, 'netzkino'))
        self.assertEqual(info['title'], 'Hin und Weg (2014)')
        self.assertEqual(info['duration'], 5700)

    def test_resolution_is_cached_for_seeking_in_remuxed_streams(self):
        for _ in range(3):
            streaming.resolve(self.c, netzkino=ITEM, root=self.state, resolver=self.resolver)
        self.assertEqual(len(self.calls), 1)
        streaming._NK_CACHE[ITEM] = (0, streaming._NK_CACHE[ITEM][1])  # expired
        streaming.resolve(self.c, netzkino=ITEM, root=self.state, resolver=self.resolver)
        self.assertEqual(len(self.calls), 2)

    def test_offline_copy_wins_over_the_online_stream(self):
        _, job = self.job()
        target = self.publish(job)
        source = streaming.resolve(self.c, netzkino=ITEM, root=self.state, resolver=self.resolver)
        self.assertEqual(source['kind'], 'file')
        self.assertEqual(source['path'], str(target))
        self.assertEqual(self.calls, [])
        target.unlink()  # deleted or expired copy: back to the online stream
        self.assertEqual(streaming.resolve(self.c, netzkino=ITEM, root=self.state,
                                           resolver=self.resolver)['kind'], 'url')

    def test_unknown_or_invalid_ids_are_refused(self):
        for bad in ('ef' * 16, '../etc', 'x'):
            with self.assertRaises(ValueError):
                streaming.resolve(self.c, netzkino=bad, root=self.state, resolver=self.resolver)
        self.assertEqual(self.calls, [])

    def test_ytdl_errors_become_readable_value_errors(self):
        ie_class = ytdl_bridge._extractor_class(ytdl_bridge.load())
        drm = {**MOVIE, 'licenses': {'nodes': [{'properties': 'DRM'}]}}
        with mock.patch.object(ie_class, '_download_webpage', return_value=next_page(drm)):
            with self.assertRaisesRegex(ValueError, 'DRM-geschützt; Wiedergabe'):
                streaming.resolve(self.c, netzkino=ITEM, root=self.state)
        self.assertNotIn(ITEM, streaming._NK_CACHE)

    def test_end_to_end_with_vendored_ytdl(self):
        ie_class = ytdl_bridge._extractor_class(ytdl_bridge.load())
        with mock.patch.object(ie_class, '_download_webpage', return_value=next_page(MOVIE)):
            info = streaming.plan(streaming.resolve(self.c, netzkino=ITEM, root=self.state))
        self.assertEqual(info['url'], MP4)

    def test_remux_command_reads_the_resolved_url(self):
        source = streaming.resolve(self.c, netzkino=ITEM, root=self.state, resolver=self.resolver)
        with mock.patch.object(streaming, 'tool', return_value='/usr/bin/ffmpeg'):
            args = streaming.command(source, 60, streaming.audio_copy(source))
        self.assertIn(MP4, args)


class WiringTests(unittest.TestCase):
    def test_ui_uses_the_in_app_player_not_the_webkit_helper(self):
        detail = (ROOT / 'web' / 'netzkino_detail.js').read_text('utf-8')
        self.assertIn('window.playNetzkino(id, label)', detail)
        self.assertNotIn("'netzkino-watch'", detail)
        player = (ROOT / 'web' / 'player.js').read_text('utf-8')
        self.assertIn('window.playNetzkino=function', player)
        server = (ROOT / 'server.py').read_text('utf-8')
        self.assertIn("for k in ('offer','job','netzkino')", server)
        self.assertIn("netzkino=q.get('netzkino',[''])[0],root=ROOT", server)


if __name__ == '__main__':
    unittest.main()
