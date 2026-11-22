"""0.6.90 (Björn 22.11.2026): neue YouTube-Kanäle aus dem eigenen Sehverhalten vorschlagen, ansehen
(validieren) und dann für die Kinderecke freigeben. Ohne Konto, ohne KI; synthetische Antworten."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import youtube as yt, youtube_abos as ab, youtube_discover as disc, youtube_downloads as yd, watch_state  # noqa: E402
from test_v0607_youtube_abos import Fixture, NOW  # noqa: E402
from test_v0553_youtube import vid  # noqa: E402

FEATURED = 'UC' + 'f' * 22
OWN = 'UC' + 'k' * 22


class Discover(Fixture):
    def request(self, endpoint, query):
        if endpoint == 'channelSections':
            self.assertEqual(query['channelId'], OWN)
            return {'items': [{'snippet': {'type': 'multipleChannels'}, 'contentDetails': {'channels': [FEATURED, OWN]}},
                              {'snippet': {'type': 'singlePlaylist'}, 'contentDetails': {'playlists': ['PLx']}}]}
        if endpoint == 'channels' and query.get('id') == FEATURED:
            return {'items': [{'id': FEATURED, 'snippet': {'title': 'Tierkanal'}}]}
        if endpoint == 'playlists':
            return {'items': []}
        return self.api(endpoint, query)

    def setUp(self):
        super().setUp()
        mock.patch.object(yd, 'find_tool', return_value=None).start()

    def prepare(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        jobs = {}
        for j in self.jobs():
            path = Path(j['target']); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'v')
            self.set_job(j['id'], 'done', path=str(path))
            jobs[j['source']['_video_id']] = j['id']
        with self.db() as c:
            db = ab._connect(self.root); ab.sync_states(c, db); db.close()
        watch_state.progress(self.root, 'job:' + jobs[vid(38)], pos=400, duration=428, done=True, now=NOW)
        disc.record_mentions(self.root, vid(38), 'Mehr bei https://www.youtube.com/@MalKanal und youtube.com/@Kinderkanal\n'
                                                 'Instagram: @nichtyoutube')
        disc.record_mentions(self.root, vid(37), 'Schaut auch https://youtube.com/@Andere')
        return abo

    def run_discover(self):
        return disc.discover(self.root, now=NOW + 10, request=self.request, seen=watch_state.states(self.root))

    def test_mentions_only_youtube_links(self):
        self.assertEqual(disc.mentions('x https://www.youtube.com/@Abc_1 y youtube.com/channel/%s @insta '
                                       'https://www.youtube.com/user/Alt z' % FEATURED),
                         ['@abc_1', FEATURED, 'user:alt'])

    def test_suggestions_weighted_by_watching_and_never_subscribed(self):
        self.prepare()
        self.assertEqual(self.run_discover(), 3)
        d = disc.overview(self.root)
        refs = [s['ref'] for s in d['suggestions']]
        self.assertEqual(refs, [FEATURED, '@malkanal', '@andere'])     # empfohlen > gesehen erwähnt > ungesehen erwähnt
        self.assertNotIn('@kinderkanal', refs)
        top = d['suggestions'][0]
        self.assertEqual((top['title'], top['profile']), ('Tierkanal', 'kinder'))
        self.assertIn('empfohlen', top['why'][0])
        self.assertIn('einem gesehenen Video', d['suggestions'][1]['why'][0])
        # Empfehlungen werden je Abo höchstens wöchentlich gelesen
        with mock.patch.object(disc, 'featured_with_api', side_effect=AssertionError('nicht erneut')):
            disc.discover(self.root, now=NOW + 3600, request=self.request, seen=watch_state.states(self.root))

    def test_preview_then_approve_for_kids_and_reject(self):
        self.prepare()
        self.run_discover()
        out = json.dumps({'channel': 'Malkanal', 'channel_id': 'UC' + 'm' * 22,
                          'entries': [{'id': vid(51), 'title': 'Malen 1', 'duration': 300, 'upload_date': '20261101'},
                                      {'id': vid(52), 'title': 'Kurz', 'duration': 30, 'upload_date': '20261102'}]})
        runner = lambda a, **k: types.SimpleNamespace(returncode=0, stdout=out, stderr='')
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')):
            p = disc.preview(self.root, '@MalKanal', now=NOW + 20, runner=runner)
        self.assertEqual(p['title'], 'Malkanal')
        self.assertEqual([v['video'] for v in p['videos']], [vid(52), vid(51)])
        self.assertTrue(p['videos'][0]['short'])
        self.assertTrue(p['checked'])
        result = disc.decide(self.root, '@malkanal', 'kids', now=NOW + 30)
        abos = {a['id']: a for a in ab.overview(self.root)['abos']}
        self.assertEqual(abos[result['abo']]['profile'], 'kinder')
        self.assertEqual(abos[result['abo']]['start_count'], disc.START_COUNT)
        self.assertEqual(abos[result['abo']]['ref'], 'UC' + 'm' * 22)
        disc.decide(self.root, '@andere', 'reject', now=NOW + 40)
        self.run_discover()
        d = disc.overview(self.root)
        self.assertEqual([s['ref'] for s in d['suggestions']], [FEATURED])
        self.assertEqual({s['ref']: s['state'] for s in d['decided']}, {'@malkanal': 'approved', '@andere': 'rejected'})

    def test_ytdlp_featured_channels(self):
        payload = {'channel_id': OWN, 'entries': [
            {'id': FEATURED, 'title': 'Tierkanal', 'url': 'https://www.youtube.com/channel/' + FEATURED},
            {'id': 'x', 'url': 'https://www.youtube.com/@Zweiter', 'title': 'Zweiter'},
            {'id': OWN, 'title': 'selbst'}]}
        calls = []

        def runner(args, **kw):
            calls.append(args)
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')):
            refs = disc.featured_with_ytdlp(self.root, '@Kinderkanal', runner=runner)
        self.assertIn('https://www.youtube.com/@Kinderkanal/channels', calls[0])
        self.assertNotIn('--cookies', ' '.join(calls[0]))
        self.assertEqual(refs, [(FEATURED, 'Tierkanal'), ('@zweiter', 'Zweiter')])

    def test_preview_player_for_unknown_video(self):
        info = yt.play_info(self.root, 'v.' + vid(51), preview=True)
        self.assertEqual((info['mode'], info['video_id']), ('embed', vid(51)))
        with self.assertRaises(ValueError):
            yt.play_info(self.root, 'v.' + vid(51))

    def test_wiring(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("@ROUTES.get('/api/youtube-discover')", server)
        self.assertIn("'/youtube_discover.js'", server)
        self.assertIn("preview=q.get('preview'", server)
        self.assertIn('youtube-discover-search', (ROOT / 'web' / 'index.html').read_text(encoding='utf-8'))
        self.assertIn("'youtube_discover.py'", (ROOT / 'build_macos.py').read_text(encoding='utf-8'))
        self.assertIn("'--write-description'", (ROOT / 'youtube_downloads.py').read_text(encoding='utf-8'))
        kids = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertNotIn('discover', kids)                               # Kinderecke zeigt nie Vorschläge


class SourcesWithoutChannelsTab(Discover):
    """0.6.98 (Mac-Prüfung 0.6.90): YouTube liefert keinen Reiter „Kanäle“ mehr; Vorschläge kommen aus Playlists
    und aus nachgeholten Beschreibungen."""

    def test_playlists_and_backfilled_descriptions_without_key(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        for j in self.jobs():
            self.set_job(j['id'], 'done', path=j['target'])
            if j['source']['_video_id'] == vid(38):
                watch_state.progress(self.root, 'job:' + j['id'], pos=400, duration=428, done=True, now=NOW)
        with self.db() as c:
            db = ab._connect(self.root); ab.sync_states(c, db); db.close()
        db = ab._connect(self.root)
        with db:
            db.execute("UPDATE youtube_abos SET channel_id=?", (OWN,))
        db.close()
        calls = []

        def runner(args, **kw):
            calls.append(args)
            url = args[-1]
            if '--skip-download' in args:
                self.assertEqual(args[-2:], ['https://www.youtube.com/watch?v=' + vid(38), 'https://www.youtube.com/watch?v=' + vid(37)])
                out = '%s\t%s\n%s\t%s\n' % (vid(38), json.dumps('Mit https://www.youtube.com/@Gastkanal gedreht'),
                                              vid(37), json.dumps('ohne Link'))
                return types.SimpleNamespace(returncode=0, stdout=out, stderr='')
            if url.endswith('/playlists'):
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(
                    {'channel_id': OWN, 'entries': [{'id': 'PL' + 'a' * 30, 'title': 'Lieblingslieder'}]}))
            if 'list=PL' in url:
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'entries': [
                    {'id': vid(60), 'channel_id': FEATURED, 'channel': 'Tierkanal'},
                    {'id': vid(61), 'channel_id': FEATURED, 'channel': 'Tierkanal'},
                    {'id': vid(62), 'channel_id': OWN, 'channel': 'Kinderkanal'}]}))
            if url.endswith('/channels'):
                raise AssertionError('Reiter „Kanäle“ gibt es nicht mehr')
            raise AssertionError(url)
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')), \
                mock.patch.object(yd, 'js_args', return_value=[]), \
                mock.patch.object(ab, '_request_for_key', return_value=None):
            count = disc.discover(self.root, now=NOW + 10, runner=runner, seen=watch_state.states(self.root))
            self.assertEqual(count, 2)
            d = disc.overview(self.root)
            refs = {s['ref']: s for s in d['suggestions']}
            self.assertEqual(set(refs), {FEATURED, '@gastkanal'})
            self.assertIn('Playlist „Lieblingslieder“', refs[FEATURED]['why'][0])
            self.assertIn('einem gesehenen Video', refs['@gastkanal']['why'][0])
            # zweiter Lauf: Beschreibungen und Playlists kommen aus dem Speicher
            before = len(calls)
            disc.discover(self.root, now=NOW + 3600, runner=runner, seen=watch_state.states(self.root))
            self.assertEqual(len(calls), before)

    def test_companions_only_real_sidecars(self):
        folder = self.root / 'k'; folder.mkdir()
        video = folder / '2026 - Titel [abc].mp4'
        names = ['2026 - Titel [abc]-poster.jpg', '2026 - Titel [abc].nfo', '2026 - Titel [abc].metadata.json',
                 '2026 - Titel [abc].de.vtt', '2026 - Titel [abc] Zugabe.mp4', '2026 - Titel [abc].mp4.partial']
        for n in [video.name, *names]:
            (folder / n).write_text('x')
        got = sorted(p.name for p in ab._companions(video))
        self.assertEqual(got, sorted([video.name, *names[:4]]))


if __name__ == '__main__':
    unittest.main()
