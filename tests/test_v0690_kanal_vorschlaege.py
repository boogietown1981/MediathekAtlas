"""0.6.90 (Björn 22.11.2026): neue YouTube-Kanäle aus dem eigenen Sehverhalten vorschlagen, ansehen
(validieren) und dann für die Kinderecke freigeben. Ohne Konto, ohne KI; synthetische Antworten."""
import json
import sys
import urllib.parse
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
        # Auflösen (Name/Videotitel je Vorschlag) prüft die Klasse ResolveAndRank; hier ohne Netz
        mock.patch.object(disc, 'resolve', return_value={}).start()

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

    def test_loose_handles_and_search_terms(self):
        self.assertEqual(disc.mentions('Kamera: @TechTim\nInstagram: @nurinsta\nmail@example.org\nMit @Gast_Kanal.'),
                         ['@techtim', '@gast_kanal'])
        db = disc._connect(self.root)
        with db:
            for v, tags in ((vid(1), ['Experimente', 'Kinderkanal', 'Wasser']), (vid(2), ['experimente', 'Vulkan']),
                            (vid(3), ['Wasser', '2026', 'Experimente'])):
                db.execute('INSERT INTO youtube_tagged(video,tags,at) VALUES(?,?,0)', (v, json.dumps(tags)))
        self.assertEqual(disc.search_terms(db, [vid(1), vid(2), vid(3)], ['Kinderkanal']), ['Experimente', 'Wasser'])
        with db:
            for v, tags in ((vid(4), ['Tobi Krell', 'Video für Kinder', 'Instagram', 'Heißluftballon']),
                            (vid(5), ['Tobi Krell', 'Video für Kinder', 'Instagram', 'Heißluftballon'])):
                db.execute('INSERT INTO youtube_tagged(video,tags,at) VALUES(?,?,0)', (v, json.dumps(tags)))
        self.assertEqual(disc.search_terms(db, [vid(4), vid(5)], []), ['Heißluftballon'])
        self.assertEqual([disc.kids_signal(t) for t in ('ARD Kinder und Familie', 'CHECKER WELT', 'Like Nastya DE', 'Mamaleen')],
                         [1, 1, -1, 0])
        db.close()

    def test_search_source_from_watched_tags(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 1}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        j = self.jobs()[0]
        self.set_job(j['id'], 'done', path=j['target'])
        watch_state.progress(self.root, 'job:' + j['id'], pos=400, duration=428, done=True, now=NOW)
        with self.db() as c:
            db = ab._connect(self.root); ab.sync_states(c, db); db.close()
        db = disc._connect(self.root)
        with db:
            db.execute('INSERT INTO youtube_tagged(video,tags,at) VALUES(?,?,0)', (j['source']['_video_id'], json.dumps(['Experimente'])))
            db.execute('INSERT INTO youtube_described(video,at) VALUES(?,0)', (j['source']['_video_id'],))
        db.close()

        def runner(args, **kw):
            url = args[-1]
            if url.startswith('ytsearch'):
                self.assertEqual(url, 'ytsearch20:Experimente für Kinder')
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'entries': [
                    {'id': vid(70), 'channel_id': FEATURED, 'channel': 'Forscherkanal'},
                    {'id': vid(71), 'channel_id': FEATURED, 'channel': 'Forscherkanal'},
                    {'id': vid(73), 'channel_id': 'UC' + 't' * 22, 'channel': 'Diana and Roma DE'},
                    {'id': vid(72), 'channel_id': OWN, 'channel': 'Kinderkanal'}]}))
            return types.SimpleNamespace(returncode=0, stderr='', stdout='{}')
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')), \
                mock.patch.object(yd, 'js_args', return_value=[]), \
                mock.patch.object(ab, '_request_for_key', return_value=None):
            disc.discover(self.root, now=NOW + 10, runner=runner, seen=watch_state.states(self.root))
        d = disc.overview(self.root)
        self.assertEqual([s['ref'] for s in d['suggestions']], [FEATURED, 'UC' + 't' * 22])
        self.assertTrue(any('Suche nach „Experimente“' in w for w in d['suggestions'][0]['why']))
        self.assertIn('Spielzeug', d['suggestions'][1]['why'][0])
        self.assertEqual(d['suggestions'][0]['title'], 'Forscherkanal')

    def test_companions_only_real_sidecars(self):
        folder = self.root / 'k'; folder.mkdir()
        video = folder / '2026 - Titel [abc].mp4'
        names = ['2026 - Titel [abc]-poster.jpg', '2026 - Titel [abc].nfo', '2026 - Titel [abc].metadata.json',
                 '2026 - Titel [abc].de.vtt', '2026 - Titel [abc] Zugabe.mp4', '2026 - Titel [abc].mp4.partial']
        for n in [video.name, *names]:
            (folder / n).write_text('x')
        got = sorted(p.name for p in ab._companions(video))
        self.assertEqual(got, sorted([video.name, *names[:4]]))


class ResolveAndRank(Fixture):
    """Nachbesserung nach Mac-Prüfung 0.6.106 (23.11.2026): nur Handles ohne Namen, eine als Handle gelesene Kanal-
    Kennung, vorn englische Kanäle aus den Beschreibungen eines einzigen Abos, Suche ohne gesehene Videos leer."""
    ID = 'UCAbcdefghijklmnopqrstuv'

    def setUp(self):
        super().setUp()
        mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')).start()
        mock.patch.object(yd, 'js_args', return_value=[]).start()
        mock.patch.object(ab, '_request_for_key', return_value=None).start()

    def subscribed(self, profile='kinder', enabled=True):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2, 'profile': profile}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        for j in self.jobs():
            self.set_job(j['id'], 'done', path=j['target'])
        with self.db() as c:
            db = ab._connect(self.root); ab.sync_states(c, db); db.close()
        db = ab._connect(self.root)
        with db:
            db.execute('UPDATE youtube_abos SET channel_id=?,enabled=?', (OWN, int(enabled)))
        db.close()
        return abo

    @staticmethod
    def listing(channel, cid, titles):
        return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(
            {'channel': channel, 'channel_id': cid, 'thumbnails': [{'id': 'avatar_uncropped', 'url': 'https://yt3.ggpht.com/a.jpg'}],
             'entries': [{'id': vid(80 + n), 'title': t} for n, t in enumerate(titles)]}))

    def test_channel_id_written_as_handle(self):
        self.assertEqual(disc.norm('@' + self.ID), self.ID)
        self.assertEqual(disc.mentions('Schaut bei https://www.youtube.com/@%s vorbei' % self.ID), [self.ID])
        self.assertTrue(disc._LOST_ID.fullmatch('@' + self.ID.lower()))

    def test_resolve_names_language_kids_signal_and_single_abo(self):
        self.subscribed()
        refs = ['@EnglishKid', '@Lernkanal', '@Weg', '@Doppel', '@' + self.ID, '@Eins', '@Zwei', '@Drei']
        disc.record_mentions(self.root, vid(38), ' '.join(refs))
        db = disc._connect(self.root)
        with db:                                   # alter Stand: kleingeschriebene Kennung aus 0.6.100
            db.execute('INSERT INTO youtube_mentions(video,ref) VALUES(?,?)', (vid(37), '@' + self.ID.lower()))
        db.close()
        calls = []

        def runner(args, **kw):
            url = args[-1]
            calls.append(url)
            if '--skip-download' in args or url.endswith('/playlists') or url.startswith('ytsearch'):
                return types.SimpleNamespace(returncode=0, stderr='', stdout='{}')
            if '/@englishkid/' in url:
                return self.listing('Fun Kid Show', 'UC' + 'e' * 22, ['How we build the tallest tower', 'What is the moon? Learn with us',
                                                                       'The big truck song for you'])
            if '/@lernkanal/' in url:
                return self.listing('Lernkanal', 'UC' + 'l' * 22, ['Wie funktioniert ein Vulkan? Für Kinder erklärt',
                                                                   'Was ist der Mond? Kinderwissen', 'Das Wetter für Kinder'])
            if '/@weg/' in url:
                return types.SimpleNamespace(returncode=1, stdout='', stderr='ERROR: [youtube:tab] @weg: This channel does not exist.')
            if '/@doppel/' in url or '/channel/%s/' % self.ID in url:
                return self.listing('Doppelkanal', self.ID, ['Wir basteln eine Laterne', 'Ein Bild malen mit Wasserfarben'])
            if '/@eins/' in url:
                return self.listing('Kinderkanal Zweitname', OWN, ['x'])     # schon abonniert (gleiche Kanal-ID)
            name = url.split('/@')[1].split('/')[0]
            return self.listing('Irgendwer ' + name, 'UC' + (name * 22)[:22], ['Vlog', 'Mein Tag'])
        with mock.patch.object(disc, 'MENTIONS_PER_ABO', 10):
            disc.discover(self.root, now=NOW + 10, runner=runner, seen=watch_state.states(self.root))
        d = disc.overview(self.root)
        got = {s['ref']: s for s in d['suggestions']}
        self.assertIn('@zwei', got)
        self.assertNotIn('@weg', got)                                   # gibt es nicht
        self.assertNotIn('@eins', got)                                  # derselbe Kanal wie das Abo
        self.assertNotIn('@' + self.ID.lower(), got)                    # verlorene Kennung nie als Handle
        self.assertEqual(len([r for r in got if r in ('@doppel', self.ID)]), 1)   # Handle und Kennung zusammengelegt
        self.assertEqual(got['@lernkanal']['title'], 'Lernkanal')
        self.assertEqual(got['@lernkanal']['avatar'], 'https://yt3.ggpht.com/a.jpg')
        self.assertIn('Kindersignal', got['@lernkanal']['why'][0])
        self.assertEqual(got['@englishkid']['title'], 'Fun Kid Show')
        self.assertEqual(got['@englishkid']['why'][0], 'englischsprachig')
        order = [s['ref'] for s in d['suggestions']]
        self.assertLess(order.index('@lernkanal'), order.index('@englishkid'))
        self.assertFalse(got['@lernkanal']['checked'])                  # Auflösen ersetzt nicht das Ansehen vor der Freigabe
        # zweiter Lauf: Angaben aus dem Speicher (vier Wochen), kein neuer Listenabruf
        before = len([c for c in calls if '/videos' in c])
        with mock.patch.object(disc, 'MENTIONS_PER_ABO', 10):
            disc.discover(self.root, now=NOW + 3600, runner=runner, seen=watch_state.states(self.root))
        self.assertEqual(len([c for c in calls if '/videos' in c]), before)
        # Standard: aus den Beschreibungen eines Abos zählen höchstens 5 Kanäle
        disc.discover(self.root, now=NOW + 7200, runner=runner, seen=watch_state.states(self.root))
        self.assertLessEqual(len(disc.overview(self.root)['suggestions']), 5)

    def test_search_fallback_without_watched_and_probe_with_paused_abo(self):
        self.subscribed(enabled=False)
        db = disc._connect(self.root)
        with db:
            for j in self.jobs():
                db.execute('INSERT INTO youtube_tagged(video,tags,at) VALUES(?,?,0)', (j['source']['_video_id'], json.dumps(['Experimente'])))
                db.execute('INSERT INTO youtube_described(video,at) VALUES(?,0)', (j['source']['_video_id'],))
        db.close()
        urls = []

        def runner(args, **kw):
            url = args[-1]
            urls.append(url)
            if url.startswith('ytsearch'):
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'entries': [
                    {'id': vid(70), 'channel_id': FEATURED, 'channel': 'Forscherkanal'}]}))
            if url.endswith('/playlists'):
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'entries': []}))
            return self.listing('Forscherkanal', FEATURED, ['Experimente für Kinder', 'Kinderwissen: Wasser'])
        disc.discover(self.root, now=NOW + 10, runner=runner, seen=watch_state.states(self.root))
        self.assertIn('ytsearch20:Experimente für Kinder', urls)          # ohne gesehene Videos: Themen der Abo-Videos
        self.assertFalse([u for u in urls if u.endswith('/playlists')])  # pausiertes Abo: keine Playlists
        s = disc.overview(self.root)['suggestions'][0]
        self.assertTrue(any('Thema der Abo-Videos' in w for w in s['why']))
        self.assertEqual(disc.summary(self.root)['sources']['search_fallback'], 1)
        # Prüflauf: auch pausierte Abos, ohne Wochenspeicher
        urls.clear()
        disc.discover(self.root, now=NOW + 20, runner=runner, seen=watch_state.states(self.root), probe=True)
        self.assertTrue([u for u in urls if u.endswith('/playlists')])
        self.assertTrue([u for u in urls if u.startswith('ytsearch')])

    def test_empty_archive_has_bytes(self):
        self.assertEqual(ab.archive_summary(self.root, None).get('bytes'), 0)


class WithApiKey(Fixture):
    """Mac-Prüfung 0.6.112 (23.11.2026): mit API-Schlüssel scheiterten Empfehlungen (channelSections) und Suche
    (search) an der Endpunktliste von youtube._request („Ungültige YouTube-Anfrage“) und verbrauchten das Budget;
    der Lauf dauerte 8 Minuten. Hier läuft alles über den echten youtube._request mit nachgebildeter Antwort."""
    SEARCHED = 'UC' + 's' * 22

    def setUp(self):
        super().setUp()
        mock.patch.object(yd, 'find_tool', return_value=None).start()     # ohne yt-dlp: nur der API-Weg
        self.calls = []
        self.quota = False
        mock.patch.object(yt.urllib.request, 'urlopen', side_effect=self.urlopen).start()

    def answer(self, endpoint, q):
        if endpoint == 'channelSections':
            return {'items': [{'snippet': {'type': 'multipleChannels'}, 'contentDetails': {'channels': [FEATURED]}}]}
        if endpoint == 'search':
            if self.quota:
                raise yt.urllib.error.HTTPError('https://x', 403, 'quotaExceeded', {}, __import__('io').BytesIO(b'{}'))
            return {'items': [{'snippet': {'channelId': self.SEARCHED, 'channelTitle': 'Forscherkanal'}}]}
        if endpoint == 'channels':
            ids = (q.get('id') or 'UC' + 'h' * 22).split(',')
            return {'items': [{'id': i, 'snippet': {'title': {FEATURED: 'Tierkanal', self.SEARCHED: 'Forscherkanal'}.get(i, 'Kanal'),
                                                     'thumbnails': {'high': {'url': 'https://yt3.ggpht.com/%s.jpg' % i}}},
                               'contentDetails': {'relatedPlaylists': {'uploads': 'UU' + i[2:]}}} for i in ids]}
        if endpoint == 'playlists':
            return {'items': []}
        if endpoint == 'playlistItems':
            return {'items': [{'snippet': {'resourceId': {'videoId': vid(90 + n)}}, 'contentDetails': {'videoId': vid(90 + n)}}
                              for n in range(3)]}
        if endpoint == 'videos':
            return {'items': [{'id': i, 'snippet': {'title': 'Experimente für Kinder %s' % i[-2:], 'description': 'Mehr bei youtube.com/@Gastkanal',
                                                    'tags': ['Experimente', 'Wasser']},
                               'contentDetails': {'duration': 'PT5M'}, 'status': {'embeddable': True}} for i in q['id'].split(',')]}
        raise AssertionError(endpoint)

    def urlopen(self, req, timeout=None):
        url = req.full_url
        endpoint = url.split('/youtube/v3/')[1].split('?')[0]
        q = dict(urllib.parse.parse_qsl(url.split('?', 1)[1]))
        self.calls.append(endpoint)
        body = json.dumps(self.answer(endpoint, q)).encode()
        return __import__('io').BytesIO(body)

    def prepare(self):
        abo = ab.add(self.root, {'url': '@Kinderkanal', 'mode': 'new', 'start_count': 2}, now=NOW)
        ab.check(self.root, abo, now=NOW, request=self.api)
        for j in self.jobs():
            self.set_job(j['id'], 'done', path=j['target'])
        with self.db() as c:
            db = ab._connect(self.root); ab.sync_states(c, db); db.close()
        db = ab._connect(self.root)
        with db:
            db.execute('UPDATE youtube_abos SET channel_id=?', (OWN,))
        db.close()

    def run_discover(self):
        request = lambda endpoint, query: yt._request(endpoint, query, 'SCHLUESSEL')  # noqa: E731
        disc._RUNNING['last_error'] = ''
        return disc.discover(self.root, now=NOW + 10, request=request, seen=watch_state.states(self.root))

    def test_endpoints_allowed(self):
        for endpoint in ('channelSections', 'search', 'channels', 'playlists', 'playlistItems', 'videos'):
            self.assertIn(endpoint, yt.ENDPOINTS)

    def test_featured_search_and_tags_over_api(self):
        self.prepare()
        self.run_discover()
        self.assertNotIn('Ungültige', disc._RUNNING['last_error'])
        self.assertIn('channelSections', self.calls)
        self.assertIn('search', self.calls)                   # Suche mit eigenem Budget, Schlagwörter kamen aus videos.list
        src = disc.summary(self.root)['sources']
        self.assertGreaterEqual(src['featured'], 1)
        self.assertGreaterEqual(src['search_fallback'], 1)
        got = {s['ref']: s for s in disc.overview(self.root)['suggestions']}
        self.assertEqual(got[FEATURED]['title'], 'Tierkanal')
        self.assertEqual(got[self.SEARCHED]['title'], 'Forscherkanal')
        self.assertTrue(got[self.SEARCHED]['avatar'].startswith('https://yt3.ggpht.com/'))
        self.assertIn('@gastkanal', got)                      # Beschreibung aus videos.list

    def test_search_quota_falls_back_to_ytdlp(self):
        self.prepare()
        self.quota = True
        urls = []

        def runner(args, **kw):
            urls.append(args[-1])
            if args[-1].startswith('ytsearch'):
                return types.SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({'entries': [
                    {'id': vid(70), 'channel_id': self.SEARCHED, 'channel': 'Forscherkanal'}]}))
            return types.SimpleNamespace(returncode=0, stderr='', stdout='{}')
        with mock.patch.object(yd, 'find_tool', return_value=(['yt-dlp'], 'test')), mock.patch.object(yd, 'js_args', return_value=[]):
            request = lambda endpoint, query: yt._request(endpoint, query, 'SCHLUESSEL')  # noqa: E731
            disc.discover(self.root, now=NOW + 10, request=request, runner=runner, seen=watch_state.states(self.root))
        self.assertTrue([u for u in urls if u.startswith('ytsearch20:Experimente')])
        self.assertIn(self.SEARCHED, {s['ref'] for s in disc.overview(self.root)['suggestions']})


if __name__ == '__main__':
    unittest.main()
