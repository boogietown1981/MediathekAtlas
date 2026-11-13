"""0.5.80: Live-TV false alarm, cast photos, clips under their Sendung, recognition per media type,
Windows/Linux packages."""
import json, shutil, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import catalog, cast_photos, live_tv
from test_diagnosis_fixes import database


def offer(title, topic, channel='ZDF', duration=900, n=0, ts=None):
    o = {'title': title, 'topic': topic, 'description': '', 'duration': duration, 'channel': channel,
         'url_video': 'https://example.org/%s-%d.mp4' % (channel, n)}
    if ts:
        o['timestamp'] = ts
    return o


def overview(total, joyn=0):
    return {'total': total, 'providers': [{'key': 'mediathek', 'channels': 44, 'error': ''},
                                          {'key': 'pluto', 'channels': 199, 'error': ''},
                                          {'key': 'joyn', 'channels': joyn, 'error': ''}]}


class LiveTvProblemTests(unittest.TestCase):
    def test_provider_without_channels_is_no_problem(self):
        # Björn's diagnosis 0.5.72: the Joyn strip asked for provider=joyn before Joyn had channels.
        self.assertFalse(live_tv.overview_problem(overview(0), 0.01, provider='joyn'))

    def test_search_without_hits_is_no_problem(self):
        self.assertFalse(live_tv.overview_problem(overview(0), 0.01, query='xyz'))
        self.assertFalse(live_tv.overview_problem(overview(0), 0.01, group='Gone'))

    def test_real_problems_are_reported(self):
        self.assertTrue(live_tv.overview_problem(overview(0), 0.01))
        self.assertTrue(live_tv.overview_problem(overview(0), 0.01, provider='pluto'))
        self.assertTrue(live_tv.overview_problem(overview(5), 4.0))
        broken = overview(5)
        broken['providers'][1]['error'] = 'busy'
        self.assertTrue(live_tv.overview_problem(broken, 0.1))
        self.assertFalse(live_tv.overview_problem(overview(5), 0.1, provider='pluto'))


class FakeTmdb:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, path, params):
        self.calls.append(path)
        if path not in self.data:
            raise OSError('offline')
        return self.data[path]


class CastPhotoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_credits_of_the_title_give_photos_and_roles(self):
        tmdb = FakeTmdb({'find/tt0111161': {'movie_results': [{'id': 278}]},
                         'movie/278/credits': {'cast': [{'name': 'Tim Robbins', 'profile_path': '/abc.jpg', 'character': 'Andy'},
                                                        {'name': 'Morgan Freeman', 'profile_path': None}]}})
        out = cast_photos.lookup(self.root, 'k' * 32, [{'name': 'Tim Robbins'}, {'name': 'Morgan Freeman'}],
                                 {'kind': 'movie', 'title': 'Die Verurteilten', 'provider': 'IMDb Offline', 'reference_id': 'tt0111161'}, tmdb)
        self.assertEqual(out['photos'], {'Tim Robbins': 'https://image.tmdb.org/t/p/w185/abc.jpg'})
        self.assertEqual(out['roles'], {'Tim Robbins': 'Andy'})
        # Second opening comes from the cache, including the miss.
        tmdb.calls.clear()
        again = cast_photos.lookup(self.root, 'k' * 32, [{'name': 'Tim Robbins'}, {'name': 'Morgan Freeman'}],
                                   {'kind': 'movie', 'title': 'Die Verurteilten', 'provider': 'IMDb Offline', 'reference_id': 'tt0111161'}, tmdb)
        self.assertEqual(again['photos'], out['photos'])
        self.assertEqual(tmdb.calls, [])

    def test_exact_imdb_person_without_title_context(self):
        tmdb = FakeTmdb({'find/nm0000209': {'person_results': [{'profile_path': '/p.png'}]}})
        out = cast_photos.lookup(self.root, 'k' * 32, [{'name': 'Tim Robbins', 'imdb_id': 'nm0000209'}], {'title': 'X'}, tmdb)
        self.assertEqual(out['photos'], {'Tim Robbins': 'https://image.tmdb.org/t/p/w185/p.png'})

    def test_no_blind_name_search_and_no_key(self):
        tmdb = FakeTmdb({})
        out = cast_photos.lookup(self.root, 'k' * 32, [{'name': 'Peter Müller'}], {'title': 'Irgendwas'}, tmdb)
        self.assertEqual(out['photos'], {})
        self.assertFalse(any(c.startswith('search/person') for c in tmdb.calls))
        self.assertFalse(cast_photos.lookup(self.root, '', [{'name': 'A'}], {}, tmdb)['configured'])

    def test_search_needs_year_and_one_matching_hit(self):
        hits = {'results': [{'id': 1, 'title': 'Heat', 'release_date': '1995-12-15'},
                            {'id': 2, 'title': 'Heat', 'release_date': '1986-01-01'}]}
        tmdb = FakeTmdb({'search/movie': hits, 'movie/1/credits': {'cast': [{'name': 'Al Pacino', 'profile_path': '/a.jpg'}]}})
        out = cast_photos.lookup(self.root, 'k' * 32, ['Al Pacino'], {'kind': 'movie', 'title': 'Heat', 'year': 1995}, tmdb)
        self.assertIn('Al Pacino', out['photos'])
        self.assertEqual(cast_photos.resolve_title(tmdb, {'kind': 'movie', 'title': 'Heat'}), (None, 'movie'))

    def test_network_error_is_not_cached(self):
        tmdb = FakeTmdb({})
        out = cast_photos.lookup(self.root, 'k' * 32, ['A B'], {'provider': 'TMDB', 'reference_id': '5'}, tmdb)
        self.assertEqual(out.get('error'), 'OSError')
        tmdb.data['movie/5/credits'] = {'cast': [{'name': 'A B', 'profile_path': '/x.jpg'}]}
        self.assertIn('A B', cast_photos.lookup(self.root, 'k' * 32, ['A B'], {'provider': 'TMDB', 'reference_id': '5'}, tmdb)['photos'])

    def test_unsafe_profile_paths_are_dropped(self):
        self.assertEqual(cast_photos._photo('/../x.jpg'), '')
        self.assertEqual(cast_photos._photo('javascript:alert(1)'), '')


class ClipFormatTests(unittest.TestCase):
    def test_single_news_clip_joins_its_sendung(self):
        self.assertTrue(catalog.format_contribution({'kind': 'other'}, offer('Merz in Washington', 'Landesschau Magazin'), 1))
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, offer('Merz in Washington', 'Landesschau Magazin'), 1))

    def test_editions_named_like_the_sendung(self):
        self.assertTrue(catalog.format_contribution({'kind': 'other'}, offer('Hessenschau', 'Hessenschau'), 3))
        self.assertFalse(catalog.format_contribution({'kind': 'other'}, offer('Hessenschau', 'Hessenschau'), 1))
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, offer('Der Pate', 'Der Pate'), 5))

    def test_short_clips_of_any_sendung(self):
        self.assertTrue(catalog.format_contribution({'kind': 'other'}, offer('Clip', 'Brisant', duration=200), 2))
        self.assertFalse(catalog.format_contribution({'kind': 'other'}, offer('Trailer: Tatort', 'Brisant', duration=200), 9))
        self.assertFalse(catalog.format_contribution({'kind': 'other'}, offer('Clip', 'Filme im Ersten', duration=200), 9))

    def test_assign_formats_moves_clips_and_dates_editions(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = database(tmp.name)
        with db() as c:
            catalog.initialize(c)
            catalog.ingest(c, [offer('Hessenschau', 'Hessenschau', channel='HR', n=1, ts=1762000000),
                               offer('Hessenschau', 'Hessenschau', channel='HR', n=2, ts=1762086400),
                               offer('Wetter am Abend', 'Hessenschau', channel='HR', n=3, duration=120)])
            catalog.set_state(c, 'format_rev', 0)
            for _ in range(3):
                catalog.assign_formats(c)
            rows = c.execute('SELECT kind,state,title,meta FROM works').fetchall()
            self.assertTrue(rows)
            for kind, state, title, meta in rows:
                self.assertEqual((kind, state, title), ('series', 'format', 'Hessenschau'))
            editions = sorted(json.loads(r[3])['episode_title'] for r in rows)
            self.assertTrue(any('·' in e for e in editions), editions)
            rec = catalog.recognition(c)
            self.assertEqual(rec[0]['channel'], 'HR')
            self.assertEqual(rec[0]['kinds']['series']['format'], len(rows))
            totals = {k['kind']: k for k in catalog.recognition_totals(rec)}
            self.assertEqual(totals['series']['works'], len(rows))


class DesktopPackageTests(unittest.TestCase):
    def test_packages_build_and_contain_the_app(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest('Pillow fehlt')
        import build_desktop
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, True)
        build_desktop.build_tarball(out)
        build_desktop.build_windows(out)
        tgz = next(out.glob('*-Linux.tar.gz'))
        with tarfile.open(tgz) as tar:
            names = tar.getnames()
            install = next(m for m in tar.getmembers() if m.name.endswith('/install.sh'))
            self.assertEqual(install.mode & 0o755, 0o755)
        self.assertTrue(any(n.endswith('/app/server.py') for n in names))
        self.assertTrue(any(n.endswith('/app/cast_photos.py') for n in names))
        self.assertFalse(any(n.endswith('build_desktop.py') for n in names))
        with zipfile.ZipFile(next(out.glob('*-Windows.zip'))) as z:
            names = z.namelist()
            ps1 = z.read(next(n for n in names if n.endswith('start.ps1')))
        self.assertTrue(any(n.endswith('/app/web/index.html') for n in names))
        self.assertTrue(ps1.startswith(b'\xef\xbb\xbf'))   # PowerShell 5 reads UTF-8 only with BOM
        self.assertIn(b'\r\n', ps1)
        if shutil.which('makensis'):
            self.assertTrue(next(out.glob('*-Windows-Setup.exe')).read_bytes()[:2] == b'MZ')
        if shutil.which('dpkg-deb'):
            deb = build_desktop.build_deb(out)[0]
            self.assertTrue(deb.is_file())


if __name__ == '__main__':
    unittest.main()
