"""ArchiveMedia preservation and differentiated, source-aware metadata proof."""
import json
import pathlib
import unittest
import urllib.error

import archive_companion
import portal_metadata_policy as policy
from vendor.archive_portals import reference_pipeline
import core


class MetadataEvidenceTests(unittest.TestCase):
    def test_archive_sources_independent_and_wikimedia_not_twice(self):
        result=policy.assess_references([
            {'provider':'Wikidata','confidence':'high','candidate_kind':'movie',
             'candidate_id':'Q1','candidate_year':1999},
            {'provider':'Wikipedia','confidence':'high','candidate_kind':'movie',
             'candidate_id':'movie-page','candidate_year':1999}
        ],'movie',1999)
        self.assertEqual(result['independent_sources'],['Wikimedia'])
        self.assertFalse(result['verified_video'])

    def test_specialized_source_cannot_alone_certify_a_work(self):
        # A reliable provider ID can support a WORK, not a video or episode.
        for provider,identifier in (('Wikidata','Q12'),
                                    ('AniList','anilist-12'),
                                    ('TVmaze','show-12')):
            with self.subTest(provider=provider):
                result=policy.assess_references([{
                    'provider':provider,'confidence':'high',
                    'candidate_kind':'series','candidate_id':identifier
                }],'series')
                self.assertFalse(result['identity_supported'])
                self.assertFalse(result['verified_episode'])
                self.assertFalse(result['verified_video'])
        result=policy.assess_references([{
            'provider':'IMDb Offline','confidence':'high',
            'candidate_kind':'movie','candidate_id':'tt98765'
        }],'movie')
        self.assertTrue(result['identity_supported'])
        self.assertEqual(result['primary_references'],['IMDb'])
        self.assertFalse(result['verified_video'])

    def test_untestable_high_confidence_title_is_not_an_identifier(self):
        result=policy.assess_references([{
            'provider':'TMDB','confidence':'high',
            'candidate_kind':'movie','candidate_title':'Popular Film'
        }],'movie')
        self.assertFalse(result['identity_supported'])
        self.assertEqual(result['strong_references'],0)

    def test_conflicting_year_and_imdb_ids_block_automatic_reference(self):
        refs=[
            {'provider':'IMDb Offline','confidence':'high','candidate_kind':'movie',
             'candidate_year':1997,'imdb_id':'tt11111'},
            {'provider':'TMDB','confidence':'high','candidate_kind':'movie',
             'candidate_year':2015,'imdb_id':'tt22222'}]
        result=policy.assess_references(refs,'movie',1997)
        self.assertFalse(result['identity_supported'])
        self.assertTrue(any('IMDb' in x for x in result['conflicts']))
        self.assertTrue(any('Erscheinungsjahr' in x for x in result['conflicts']))

    def test_series_metadata_does_not_certify_two_minute_video(self):
        data={'kind':'series','title':'Anime','normalized_title':'Anime','year':2020,
              'reference_id':'tv123','match_provider':'TMDB',
              'expected_runtime_seconds':1200,
              'video_variants':[{
                 'filename':'Anime.S01E02.mkv','technical_role':'primary_video',
                 'duration_seconds':120,'expected_runtime_seconds':1200,
                 'season':1,'episode':2,'identity_origin':'filename'
              }]}
        report=policy.assess_archive(data)
        self.assertNotEqual(report['stage'],'content_supported')
        self.assertEqual(report['strong_files'],0)
        self.assertFalse(report['video_content_verified'])

    def test_runtime_consistent_film_needs_independent_reference(self):
        data={'kind':'movie','title':'My Film','year':1998,
              'video_variants':[{'filename':'My.Film.mkv',
                 'technical_role':'primary_video','duration_seconds':5400,
                 'expected_runtime_seconds':5400,'identity_origin':'archive-title'}]}
        report=policy.assess_archive(data)
        self.assertEqual(report['stage'],'unresolved')
        data['reference_id']='tt77777'
        data['match_provider']='IMDb Offline'
        report=policy.assess_archive(data)
        self.assertEqual(report['stage'],'content_supported')
        self.assertFalse(report['video_content_verified'])

    def test_source_specific_priorities(self):
        self.assertEqual(policy.source_policy('internet_archive')['canonical'],'ArchiveMedia')
        self.assertEqual(policy.source_policy('mediathekview')['canonical'],'MediathekAtlas')
        self.assertFalse(policy.source_policy('netzkino')['supports_technical_tracks'])
        self.assertEqual(policy.PRIORITY,reference_pipeline.PRIORITY)
        with self.assertRaises(ValueError):policy.source_policy('madeup')

    def test_reference_pipeline_preserves_offline_first(self):
        calls=[]
        def provider(label,rows):
            def run():
                calls.append(label)
                return rows
            return run
        result=reference_pipeline.validate(
            offline=provider('IMDb',[{'confidence':'high','imdb_id':'tt999'}]),
            tvdb=provider('TVDB',[]),
            tmdb=provider('TMDB',[]),
            omdb=provider('OMDb',[]))
        self.assertEqual(calls,['IMDb'])
        self.assertEqual(result['primary']['imdb_id'],'tt999')
        self.assertEqual(result['trail'][1]['state'],'skipped_sufficient')

    def test_archive_ui_reports_evidence_separately_from_spoken_language(self):
        app=(pathlib.Path(__file__).resolve().parents[1]/'web'/'app.js').read_text(encoding='utf-8')
        self.assertIn("manifest.work_assessment",app)
        self.assertIn("Werk-/Dateibeleg:",app)
        self.assertIn("Video-Inhalt nicht bestätigt",app)
        self.assertIn("Sprachhinweise sind keine bestätigten Tonspuren",app)
        self.assertIn("Tonspuren (Containerangaben)",app)

    def test_filename_plan_uses_existing_single_engine(self):
        self.assertIn('canonical_target',policy.filename_rules()['engine'])
        self.assertFalse(policy.filename_rules()['guesses_used_as_verified_languages'])
        code=pathlib.Path(core.__file__).read_text(encoding='utf-8')
        self.assertIn('canonical_target',code)


class CompanionTests(unittest.TestCase):
    def test_companion_read_only_status(self):
        class Response:
            url=archive_companion.HEALTH
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,size):
                return json.dumps({'version':'0.10.53','ready':True,
                                   'phase':'Bereit','ok':True}).encode()
        received=[]
        def opener(req,timeout):
            received.append((req.full_url,req.get_method(),timeout))
            return Response()
        result=archive_companion.read_status(opener)
        self.assertTrue(result['connected'])
        self.assertTrue(result['compatible'])
        self.assertEqual(result['ui_url'],'http://127.0.0.1:8789/')
        self.assertFalse(result['write_access'])
        self.assertEqual(received[0][1],'GET')
        self.assertEqual(len(received),1)

    def test_companion_does_not_follow_unsafe_redirect(self):
        class Response:
            url='http://example.org/unsafe'
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,size):raise AssertionError('Never read redirected data')
        result=archive_companion.read_status(lambda *args,**kwargs:Response())
        self.assertFalse(result['connected'])
        self.assertIsNone(result['ui_url'])

    def test_companion_absent_is_not_an_automatic_install(self):
        result=archive_companion.read_status(
            lambda *args,**kwargs:(_ for _ in ()).throw(urllib.error.URLError('offline')))
        self.assertFalse(result['connected'])
        self.assertFalse(result['write_access'])

    def test_outdated_companion_is_not_offered_as_compatible(self):
        class Response:
            url=archive_companion.HEALTH
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return b'{"version":"0.9.0","ready":true}'
        result=archive_companion.read_status(lambda *_a,**_k:Response())
        self.assertTrue(result['connected'])
        self.assertFalse(result['compatible'])
        self.assertIsNone(result['ui_url'])


class FeaturePreservationTests(unittest.TestCase):
    def test_archive_full_mode_and_isolated_scoped_mode_are_distinct(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        html=(root/'web'/'index.html').read_text(encoding='utf-8')
        js=(root/'web'/'app.js').read_text(encoding='utf-8')
        server=(root/'server.py').read_text(encoding='utf-8')
        build=(root/'build_macos.py').read_text(encoding='utf-8')
        for needle in ('archive-full-mode','archive-companion-status',
                       'archive-full-open','archive-scanner-enabled',
                       'archive-scope-add','portal-language'):
            self.assertIn('id="'+needle+'"',html)
        for endpoint in ('/api/archive-companion','/api/portal-policy',
                         '/api/portal-controls','/api/portal-scope-add'):
            self.assertIn(endpoint,server)
        self.assertIn('function displayPortalControls',js)
        for module in ('archive_companion.py','portal_metadata_policy.py',
                       'portal_control.py','portal_sources.py'):
            self.assertIn("'"+module+"'",build)


if __name__=='__main__':unittest.main()
