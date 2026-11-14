"""0.5.88: Staffel- und Folgenauswahl für Archive.org-Uploads und vorgemerkte Uploader (aus Archive Media)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_selection as selection  # noqa: E402
import archive_uploaders as uploaders  # noqa: E402
import portal_sources  # noqa: E402
from tests._wiring import wired  # noqa: E402


def variant(name, season=1, episode=1, **extra):
    base = {'filename': name, 'title': 'Folge %s' % episode, 'kind': 'series', 'season': season, 'episode': episode,
            'family_id': name.rsplit('.', 1)[0], 'technical_role': 'primary_video', 'size_bytes': 1000, 'source': 'original',
            'audio_hint_languages': [], 'subtitle_hint_languages': [], 'sidecar_subtitles': [], 'height': 720}
    base.update(extra)
    return base


def detail(*variants):
    return {'source': 'internet_archive', 'video_variants': list(variants), 'inventory_complete': True, 'display_complete': True}


class CriteriaTests(unittest.TestCase):
    def test_defaults_and_refusals(self):
        c = selection.criteria(None)
        self.assertEqual((c['audio'], c['resolution_mode'], c['height'], c['format'], c['verified'], c['season']), ([], 'any', 0, '', False, None))
        self.assertEqual(selection.criteria({'audio': ['DE', 'de', 'x', 'en; DROP']})['audio'], ['de'])
        for bad in ({'resolution_mode': 'best'}, {'height': 999}, {'height': 'hoch'}, {'resolution_mode': 'exact'}, {'format': '.exe'},
                    {'audio_match': 'some'}, {'audio': 'de'}):
            with self.assertRaises(ValueError, msg=bad):
                selection.criteria(bad)

    def test_quality_bucket(self):
        self.assertEqual([selection.quality_bucket(h) for h in (None, 'x', 360, 576, 720, 1080, 1088, 1440, 2160)],
                         [0, 0, 480, 480, 720, 1080, 1080, 1440, 2160])


class MatrixTests(unittest.TestCase):
    def test_one_file_per_episode_the_best_that_fits(self):
        d = detail(variant('S01E01.720.mkv'), variant('S01E01.1080.mkv', height=1080, size_bytes=3000),
                   variant('S01E01.derived.mp4', height=480, source='derivative'), variant('S01E02.mkv', episode=2),
                   variant('S02E01.mkv', season=2), variant('lose.mkv', season=None, episode=None))
        result = selection.matrix(d)
        self.assertEqual([(r['season'], r['episode'], r['filename']) for r in result['rows']],
                         [(1, 1, 'S01E01.1080.mkv'), (1, 2, 'S01E02.mkv'), (2, 1, 'S02E01.mkv')])
        self.assertEqual((result['kind'], result['matched'], result['missing'], result['unassigned_files'], result['seasons'], result['estimated_bytes'], result['complete']),
                         ('series', 3, 0, 1, [1, 2], 5000, True))
        self.assertEqual((result['rows'][0]['options'], result['rows'][0]['matching'], result['rows'][0]['quality']), (3, 3, 1080))
        # A wish for 720p takes the closest file, a season wish hides the others.
        self.assertEqual(selection.matrix(d, wishes={'height': 720})['rows'][0]['filename'], 'S01E01.720.mkv')
        self.assertEqual([r['season'] for r in selection.matrix(d, wishes={'season': 2})['rows']], [2])

    def test_reasons_when_nothing_fits(self):
        d = detail(variant('a.mkv', audio_hint_languages=['en']), variant('b.avi', episode=2, audio_hint_languages=['de'], height=None),
                   variant('c.mkv', episode=3, audio_hint_languages=['de'], identity_warning='unklar'))
        result = selection.matrix(d, wishes={'audio': ['de'], 'resolution_mode': 'at_least', 'height': 720})
        self.assertEqual([r['status'] for r in result['rows']], ['missing', 'missing', 'missing'])
        self.assertEqual([list(r['reasons']) for r in result['rows']],
                         [['Gewünschte Tonsprache nicht angegeben'], ['Auflösung unbekannt'], ['Folge nicht eindeutig zugeordnet']])
        self.assertEqual((result['matched'], result['missing'], result['estimated_bytes']), (0, 3, 0))
        self.assertEqual(selection.matrix(d, wishes={'format': '.avi'})['rows'][0]['reasons'], {'Dateiformat passt nicht': 1})
        self.assertEqual(selection.matrix(detail(variant('x.mp4', source='derivative')), wishes={'originals': True})['rows'][0]['reasons'],
                         {'Von Archive.org umgerechnete Fassung': 1})

    def test_a_proven_language_beats_a_file_name(self):
        d = detail(variant('gross.de.mkv', audio_hint_languages=['de'], size_bytes=9000, height=1080),
                   variant('klein.mkv', size_bytes=100))
        probes = {'klein.mkv': {'audio_languages_from_tracks': ['de', 'en'], 'subtitle_languages_from_tracks': []}}
        self.assertEqual(selection.matrix(d, probes, {'audio': ['de']})['rows'][0]['filename'], 'klein.mkv')
        verified = selection.matrix(d, None, {'audio': ['de'], 'verified': True})
        self.assertEqual(verified['rows'][0]['status'], 'missing')
        self.assertIn('Tonspur', next(iter(verified['rows'][0]['reasons'])))
        both = selection.matrix(d, probes, {'audio': ['de', 'fr'], 'audio_match': 'any', 'verified': True})['rows'][0]
        self.assertEqual((both['filename'], both['audio'], both['audio_proven']), ('klein.mkv', ['de', 'en'], True))
        self.assertEqual(selection.matrix(d, probes, {'audio': ['de', 'fr']})['matched'], 0)

    def test_films_are_one_row_per_family(self):
        d = detail(variant('Film A.mkv', kind='movie', season=None, episode=None, family_id='a', title='Film A'),
                   variant('Film A.mp4', kind='movie', season=None, episode=None, family_id='a', source='derivative', height=480),
                   variant('Film B.mkv', kind='movie', season=None, episode=None, family_id='b', title='Film B'))
        result = selection.matrix(d)
        self.assertEqual((result['kind'], [r['filename'] for r in result['rows']], result['seasons']), ('movie', ['Film A.mkv', 'Film B.mkv'], []))


class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.detail = detail(variant('e1.mkv'), variant('e2.mkv', episode=2), variant('e3.mkv', episode=3, identity_warning='unklar'))
        patch = mock.patch.object(portal_sources, 'archive_saved_detail', lambda c, item_id: {'detail': self.detail if item_id == 'ok' else None, 'probes': {}})
        patch.start()
        self.addCleanup(patch.stop)

    def test_only_winners_are_queued(self):
        queued = []

        def queue(c, folder, item_id, name):
            queued.append((folder, item_id, name))
            if name == 'e2.mkv':
                return {'created': False, 'state': 'done'}
            return {'created': True}
        result = selection.enqueue('c', '/dl', 'ok', None, None, queue)
        self.assertEqual((result['created'], result['existing'], result['failed'], result['files'], result['estimated_bytes']), (1, 1, [], 2, 2000))
        self.assertEqual(queued, [('/dl', 'ok', 'e1.mkv'), ('/dl', 'ok', 'e2.mkv')])
        # A ticked file that is no winner (or not in the upload at all) is never queued.
        del queued[:]
        selection.enqueue('c', '/dl', 'ok', None, ['e1.mkv', 'e3.mkv', '../../etc/passwd'], queue)
        self.assertEqual([q[2] for q in queued], ['e1.mkv'])

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'Dateibestand'):
            selection.enqueue('c', '/dl', 'fehlt')
        with self.assertRaisesRegex(ValueError, 'Keine passende'):
            selection.enqueue('c', '/dl', 'ok', {'format': '.avi'})
        with self.assertRaisesRegex(ValueError, 'Auswahl'):
            selection.enqueue('c', '/dl', 'ok', None, 'e1.mkv')

        def broken(c, folder, item_id, name):
            raise ValueError('Datei nicht mehr im Upload')
        result = selection.enqueue('c', '/dl', 'ok', None, None, broken)
        self.assertEqual((result['created'], len(result['failed'])), (0, 2))
        many = detail(*[variant('f%d.mkv' % n, episode=n) for n in range(selection.MAX_FILES + 1)])
        with self.assertRaisesRegex(ValueError, 'Höchstens'):
            selection.choose(selection.matrix(many))


class ManifestTests(unittest.TestCase):
    def test_height_and_public_account_from_the_manifest(self):
        doc = {'metadata': {'identifier': 'show', 'title': 'Show', 'mediatype': 'movies', '_uploader_useritem': '@film_fan', 'uploader': 'someone@example.org'},
               'files': [{'name': 'Show S01E01.mkv', 'source': 'original', 'format': 'Matroska', 'size': '700000000', 'length': '1500', 'height': '1080', 'width': '1920'},
                         {'name': 'Show S01E02.mkv', 'source': 'original', 'format': 'Matroska', 'size': '700000000', 'length': '1500', 'height': 'n/a'}]}
        d = portal_sources.archive_detail_document('show', doc)
        self.assertEqual({v['filename']: (v['height'], v['width']) for v in d['video_variants']},
                         {'Show S01E01.mkv': (1080, 1920), 'Show S01E02.mkv': (None, None)})
        self.assertEqual(d['uploader_account'], '@film_fan')
        self.assertNotIn('example.org', json.dumps(d))
        self.assertEqual([portal_sources.uploader_account(v) for v in ('@a_b.c-1', ['@only'], ['@a', '@b'], 'someone@example.org', 'name', '@x', None)],
                         ['@a_b.c-1', '@only', '', '', '', '', ''])
        self.assertIn('_uploader_useritem', portal_sources.archive_query('nosferatu'))
        rows = portal_sources.archive_document({'response': {'docs': [{'identifier': 'abc', 'title': 'Ein Film', '_uploader_useritem': '@kino'}]}})
        self.assertEqual(rows[0]['uploader_account'], '@kino')


class UploaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = sqlite3.connect(Path(self.tmp.name) / 'main.sqlite3')
        self.addCleanup(self.c.close)
        import portal_control
        portal_sources.initialize(self.c)
        portal_control.initialize(self.c)
        self.works = [('aw1', 'Nosferatu', ['i1', 'i2']), ('aw2', 'Metropolis', ['i3']), ('aw3', 'Ohne Konto', ['i4'])]
        patch = mock.patch.object(uploaders, 'recognised', lambda root: self.works)
        patch.start()
        self.addCleanup(patch.stop)
        for item_id, account in (('i1', '@kino'), ('i2', '@Kino'), ('i3', '@stummfilm'), ('i4', 'someone@example.org')):
            self.c.execute("INSERT INTO portal_items(id,source,external_id,title,title_key,year,page_url,metadata,discovered,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (item_id, 'internet_archive', item_id, 'T ' + item_id, 't', None, 'https://archive.org/details/' + item_id,
                            json.dumps({'uploader_account': portal_sources.uploader_account(account)}), 1, 1))

    def scopes(self):
        return [tuple(r) for r in self.c.execute("SELECT scope,state,label FROM portal_scopes WHERE kind='uploader' ORDER BY scope")]

    def test_accounts_are_noted_once_and_paused(self):
        result = uploaders.follow(Path(self.tmp.name), self.c, now=100)
        self.assertEqual((result['works'], result['new'], result['accounts'], result['without_account']), (3, 2, ['@kino', '@stummfilm'], 1))
        self.assertEqual(self.scopes(), [('@kino', 'paused', 'Uploader von „Nosferatu“'), ('@stummfilm', 'paused', 'Uploader von „Metropolis“')])
        self.assertEqual(uploaders.follow(Path(self.tmp.name), self.c)['new'], 0)
        # Removed by the user: it stays away.
        self.c.execute("DELETE FROM portal_scopes WHERE scope='@kino'")
        self.assertEqual(uploaders.follow(Path(self.tmp.name), self.c)['new'], 0)
        self.assertEqual([s[0] for s in self.scopes()], ['@stummfilm'])
        listed = uploaders.listing(self.c)['items']
        self.assertEqual(sorted((r['account'], r['removed'], r['title']) for r in listed), [('@kino', True, 'Nosferatu'), ('@stummfilm', False, 'Metropolis')])

    def test_an_own_source_keeps_its_settings_and_the_run_is_bounded(self):
        import portal_control
        scope_id = portal_control.add_scope(self.c, 'uploader', '@kino', priority=3, page_budget=20)
        self.c.execute("UPDATE portal_scopes SET state='queued',enabled=1 WHERE id=?", (scope_id,))
        result = uploaders.follow(Path(self.tmp.name), self.c, limit=1)
        self.assertEqual((result['accounts'], result['pending']), (['@stummfilm'], 0))
        self.assertEqual(tuple(self.c.execute("SELECT priority,page_budget,state,label FROM portal_scopes WHERE id=?", (scope_id,)).fetchone()), (3, 20, 'queued', '@kino'))

    def test_background_run_is_throttled(self):
        uploaders._last['at'] = 0.0
        self.assertEqual(uploaders.background(Path(self.tmp.name), self.c, now=5000)['new'], 2)
        self.assertIsNone(uploaders.background(Path(self.tmp.name), self.c, now=5100))
        self.assertIsNotNone(uploaders.background(Path(self.tmp.name), self.c, now=5000 + uploaders.EVERY))


class WiringTests(unittest.TestCase):
    def test_routes_scripts_and_package(self):
        for needle in ("'/api/archive-selection'", "'/api/archive-selection-download'", "'/api/archive-uploaders'", "'/api/archive-uploaders-follow'"):
            self.assertTrue(wired(needle), needle)
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        self.assertIn("'archive_selection.py'", build)
        self.assertIn("'archive_uploaders.py'", build)
        app = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn("api('archive-selection'", app)
        self.assertIn("api('archive-selection-download'", app)
        self.assertIn('archive_uploaders.background', (ROOT / 'archive_recognition.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
