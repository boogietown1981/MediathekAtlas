"""0.5.71 (Björn, 12.11.2026): YouTube music videos next to films and series. Playlists, channels or
single videos, no minimum length and no promo filter; online in the embedded player (playlist plays
video after video), offline per video, the whole playlist or a selection in one click (still only
with the opt-in switch). Synthetic Data API answers in the documented shape."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube as yt, youtube_downloads as yd  # noqa: E402
from test_v0553_youtube import Api, VIDEOS, video, vid, NOW, UPLOADS  # noqa: E402

MUSIC_PL = 'PLmusik1234567890'
MUSIC = {
    20: video(20, 'Künstler A - Lied Eins (Official Video)', 215, channel='Label Musik'),
    21: video(21, 'Künstler B - Lied Zwei [Official Music Video]', 190, channel='Label Musik'),
    22: video(22, 'Künstler C - Lied Drei (Lyric Video)', 240, channel='Label Musik', age=True),
    23: video(23, 'Gesperrt', 200, region={'blocked': ['DE']}),
    24: video(24, 'Single - Einzelnes Video (Official Audio)', 180, channel='Einzelkanal'),
}


class MusicApi(Api):
    def __call__(self, endpoint, query):
        if endpoint == 'playlistItems' and query['playlistId'] == MUSIC_PL:
            self.calls.append((endpoint, dict(query)))
            return {'items': [{'snippet': {'position': i}, 'contentDetails': {'videoId': vid(n)}}
                              for i, n in enumerate((20, 21, 22, 23))]}
        if endpoint == 'playlists':
            self.calls.append((endpoint, dict(query)))
            return {'items': [{'id': query['id'], 'snippet': {'title': 'Hits 2024', 'channelId': 'UC' + 'm' * 22}}]}
        if endpoint == 'videos':
            self.calls.append((endpoint, dict(query)))
            wanted = query['id'].split(',')
            return {'items': [v for v in list(VIDEOS.values()) + list(MUSIC.values()) if v['id'] in wanted]}
        return super().__call__(endpoint, query)


class MusicTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        db = yt._connect(self.root)
        with db:
            db.execute('DELETE FROM youtube_sources')
        db.close()
        yt.add_source(self.root, 'https://www.youtube.com/@ParamountVault')
        yt.add_source(self.root, 'https://music.youtube.com/playlist?list=' + MUSIC_PL, kind='music')
        yt.add_source(self.root, 'https://youtu.be/' + vid(24) + '?si=abc', kind='music')
        self.result = yt.sync(self.root, request=MusicApi(), now=NOW, gap=0)
        self.assertTrue(self.result['ok'], self.result)
        self.c = sqlite3.connect(':memory:')
        self.addCleanup(self.c.close)
        self.c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        self.media = self.root / 'media'
        self.media.mkdir()

    def test_references(self):
        for text in ('https://www.youtube.com/watch?v=%s' % vid(1), 'youtu.be/%s' % vid(1),
                     'https://www.youtube.com/shorts/%s' % vid(1), 'https://music.youtube.com/watch?v=%s' % vid(1)):
            self.assertEqual(yt.parse_ref(text), 'v:' + vid(1), text)
        # a playlist link wins over the video it was opened on
        self.assertEqual(yt.parse_ref('https://www.youtube.com/watch?v=%s&list=%s' % (vid(1), MUSIC_PL)), MUSIC_PL)
        with self.assertRaisesRegex(ValueError, 'Playlist'):
            yt.add_source(self.root, 'youtu.be/' + vid(1), kind='series')
        src = [s for s in yt.sources(self.root) if s['kind'] == 'music']
        self.assertEqual([s['min_minutes'] for s in src], [1, 1])

    def test_no_length_or_promo_filter_and_films_untouched(self):
        music = yt.listing(self.root, 'music')
        self.assertEqual(sorted((i['kind'], i['title']) for i in music['items']),
                         [('album', 'Hits 2024'), ('track', 'Single - Einzelnes Video')])
        album = next(i for i in music['items'] if i['kind'] == 'album')
        self.assertEqual((album['number'], album['category'], album['duration']), (3, 'Label Musik', 215 + 190 + 240))
        tracks = yt.tracks(self.root, album['id'])['items']
        self.assertEqual([(t['number'], t['title']) for t in tracks],
                         [(0, 'Künstler A - Lied Eins'), (1, 'Künstler B - Lied Zwei'), (2, 'Künstler C - Lied Drei (Lyric Video)')])
        # films keep their filters, music does not appear among films or series
        self.assertNotIn('track', {i['kind'] for i in yt.listing(self.root, 'movies')['items']})
        self.assertEqual(yt.listing(self.root, 'series')['items'], [])
        st = yt.state(self.root)
        self.assertEqual((st['music'], st['tracks'], st['movies']), (2, 4, self.result['movies']))
        skipped = json.loads(next(s for s in yt.sources(self.root) if s['ref'] == MUSIC_PL)['skipped'])
        self.assertEqual(skipped, {'nicht verfügbar (gesperrt, privat, live)': 1})
        # search finds the playlist by one of its songs
        self.assertEqual([i['id'] for i in yt.listing(self.root, 'music', query='Lied Zwei')['items']], [album['id']])

    def test_playback(self):
        info = yt.play_info(self.root, 't.' + vid(20))
        self.assertEqual((info['mode'], info['embed']), ('embed', yt.EMBED + vid(20)))
        with self.assertRaisesRegex(ValueError, 'Video der Playlist'):
            yt.play_info(self.root, 'm.' + MUSIC_PL)

    def test_offline_whole_playlist_and_selection(self):
        album = 'm.' + MUSIC_PL
        self.assertEqual(yt.album_track_ids(self.root, album), [])          # switch off: nothing storable
        with self.assertRaisesRegex(ValueError, 'ausgeschaltet'):
            yd.enqueue_many(self.c, self.root, self.media, ['t.' + vid(20)])
        yd.set_enabled(self.root, True, confirmed=True)
        ids = yt.album_track_ids(self.root, album)
        self.assertEqual(ids, ['t.' + vid(20), 't.' + vid(21)])            # age restricted video left out
        self.assertEqual(yt.album_track_ids(self.root, album, ['t.' + vid(21), 't.' + vid(1)]), ['t.' + vid(21)])
        first = yd.enqueue_many(self.c, self.root, self.media, ['t.' + vid(21)])
        self.assertEqual((first['created'], first['existing'], first['failed']), (1, 0, 0))
        result = yd.enqueue_many(self.c, self.root, self.media, ids)
        self.assertEqual((result['created'], result['existing'], result['failed']), (1, 1, 0))
        jobs = [json.loads(p) for (p,) in self.c.execute('SELECT payload FROM jobs')]
        targets = sorted(Path(j['target']).relative_to(self.media.resolve()).as_posix() for j in jobs)
        self.assertEqual(targets, ['Musikvideos/Hits 2024/001 - Künstler A - Lied Eins.mkv',
                                   'Musikvideos/Hits 2024/002 - Künstler B - Lied Zwei.mkv'])
        self.assertEqual({(j['origin'], j['license']['kind'], j['metadata']['genres'][0]) for j in jobs},
                         {('youtube', 'youtube_offline', 'Musik')})
        single = yd.enqueue(self.c, self.root, self.media, 't.' + vid(24))
        target = json.loads(self.c.execute('SELECT payload FROM jobs WHERE id=?', (single['id'],)).fetchone()[0])['target']
        self.assertTrue(target.endswith('Musikvideos/Einzelkanal/Single - Einzelnes Video.mkv'), target)
        with self.assertRaisesRegex(ValueError, 'Ganze Playlist'):
            yd.enqueue(self.c, self.root, self.media, album)

    def test_player_way_out_and_catalogue_entry(self):
        # 0.5.76: the player learns whether "load and play here" is possible
        self.assertEqual(yt.play_info(self.root, 't.' + vid(20))['offline'], 0)
        self.assertIn('Offline-Schalter', yt.play_info(self.root, 't.' + vid(20))['offline_hint'])
        yd.set_enabled(self.root, True, confirmed=True)
        info = yt.play_info(self.root, 't.' + vid(20))
        self.assertEqual((info['offline'], info['offline_hint'], info['web_url']), (1, '', yt.video_url(vid(20))))
        player = (ROOT / 'web/player.js').read_text(encoding='utf-8')
        for part in ("d.event==='onError'", 'embedRefused', 'https://www.youtube.com', 'Kurz laden und hier abspielen', 'Auf YouTube ansehen'):
            self.assertIn(part, player)
        self.assertIn('data-cross-kind="music"', (ROOT / 'web/index.html').read_text(encoding='utf-8'))
        catalogue = (ROOT / 'web/unified_catalog.js').read_text(encoding='utf-8')
        self.assertIn("view:'music'", catalogue)
        self.assertIn('openAlbum', catalogue)
        self.assertIn('openAlbum', (ROOT / 'web/portal_panel.js').read_text(encoding='utf-8'))
        subprocess.run(['node', '--check', str(ROOT / 'web/unified_catalog.js')], check=True)

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("youtube.tracks(ROOT", server)
        self.assertIn('enqueue_many', server)
        html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        for node in ('youtube-view-music', 'youtube-music-play', 'youtube-music-all', 'youtube-music-pick', 'value="music"'):
            self.assertIn(node, html)
        for name in ('portal_panel.js', 'player.js', 'youtube.js'):
            subprocess.run(['node', '--check', str(ROOT / 'web' / name)], check=True)
        self.assertIn('playYouTubeList', (ROOT / 'web/player.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
