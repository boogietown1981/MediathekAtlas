"""ArchiveMedia cross-app regression: video-only discovery, families, bounded track probe."""
import sqlite3
import unittest
from unittest.mock import patch

import portal_sources as portals
from vendor.archive_portals import media_probe


def movie_manifest(extra_clips=0):
    files=[
        {'name':'film.mkv','format':'Matroska','size':'800000000','length':'01:40:00',
         'source':'original'},
        {'name':'film.mp4','format':'MPEG4','size':'600000000','length':'01:40:00',
         'source':'derivative','original':'film.mkv'},
        {'name':'film.ia.mp4','format':'MPEG4','size':'100000000','length':'01:40:00',
         'source':'derivative','original':'film.mkv'},
        {'name':'show.S01E02.GermanAudio.mkv','format':'Matroska',
         'size':'300000000','length':'25:00','source':'original'},
        {'name':'trailer.mp4','size':'1500000','length':'01:30','source':'original'},
        {'name':'BDMV/STREAM/00001.m2ts','size':'40000000','length':'20:00'},
        {'name':'film.mp3','size':'8000000','length':'20:00'},
        {'name':'film.pdf','size':'1000000'},
        {'name':'film.de.srt','size':'2500'},
        {'name':'cover.jpg','size':'50000'},
    ]
    for k in range(extra_clips):
        files.append({'name':'small_%05d.mp4'%k,'size':'500000',
                      'length':'00:15','source':'original'})
    return {'metadata':{'identifier':'movie_test','title':'A Movie',
                        'year':'1988','language':'English'},
            'files':files}


class ArchiveMediaVideoTests(unittest.TestCase):
    def test_keeps_movies_episode_families_and_language_hints(self):
        data=portals.archive_detail_document('movie_test',movie_manifest(700))
        self.assertEqual(data['files_in_manifest'],710)
        self.assertEqual(data['video_files_found'],706)
        self.assertEqual(data['hidden_short_clips'],700)
        self.assertEqual(data['hidden_technical_clips'],2)
        self.assertEqual(data['video_files_eligible'],4)
        self.assertEqual(data['video_families_found'],2)
        self.assertEqual(data['non_video_files_ignored'],3)
        self.assertEqual(len(data['video_variants']),4)
        self.assertTrue(all(v['filename'].endswith(('.mkv','.mp4')) for v in data['video_variants']))
        self.assertEqual(len({v['family_id'] for v in data['video_variants']}),2)
        episode=next(v for v in data['video_variants'] if v['kind']=='series')
        self.assertEqual((episode['season'],episode['episode']),(1,2))
        self.assertEqual(episode['audio_hint_languages'],['de'])
        self.assertFalse(episode['languages_verified'])
        self.assertEqual(data['content_format_hint'],'series_or_mixed_upload')
        self.assertFalse(data['download_allowed'])

    def test_short_episodes_not_wrongly_confirmed_as_trailers(self):
        fixture={'metadata':{'title':'Short anime','series':'Short anime'},'files':[
            {'name':'Short.anime.S01E01.mp4','size':'20000000','length':'02:00'},
            {'name':'Short.anime.S01E02.mp4','size':'30000000','length':'05:00'},
        ]}
        result=portals.archive_detail_document('short_anime_001',fixture)
        self.assertEqual(result['hidden_short_clips'],1)
        self.assertEqual(len(result['video_variants']),1)
        self.assertEqual(result['video_variants'][0]['episode'],2)
        self.assertEqual(result['video_variants'][0]['duration_seconds'],300)
        # A visibility filter is not proof the 2-minute anime is a trailer.
        self.assertEqual(result['content_format_hint'],'series_or_mixed_upload')

    def test_rejects_path_traversal_and_arbitrary_hosts(self):
        for name in ('../x.mp4','/tmp/x.mkv','x/../../y.mp4',
                     'https://evil.test/film.mp4','sub\\evil.mkv','x\x00.mp4'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                portals._archive_video_url('movie_test',name)
        good=portals._archive_video_url('movie_test','My film (German).mkv')
        self.assertEqual(good,'https://archive.org/download/movie_test/My%20film%20%28German%29.mkv')

    def test_saved_details_and_probes_persist_without_download_jobs(self):
        con=sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        portals.initialize(con)
        item=portals.entry('internet_archive','movie_test','A Movie',
                           'https://archive.org/details/movie_test')
        with con:portals.save(con,[item])
        manifest=portals.archive_detail_document('movie_test',movie_manifest())
        with con:portals.save_archive_detail(con,item['id'],manifest)
        saved=portals.archive_saved_detail(con,item['id'])
        self.assertEqual(saved['detail']['video_families_found'],2)
        self.assertEqual(saved['probes'],{})
        with self.assertRaisesRegex(ValueError,'Zugriffsberechtigung'):
            portals.probe_archive_variant(con,item['id'],'film.mkv',acknowledged=False)
        with patch('portal_sources.archive_probe.inspect',return_value={
                'state':'partial','bytes':1048576,'method':'Containerindex MP4',
                'detail':'Spurheader gelesen','tracks':[
                    {'type':'video','codec':'h264','language':None,'evidence':'container-index'},
                    {'type':'audio','codec':'aac','language':'deu','evidence':'container-index'},
                    {'type':'subtitle','codec':'subrip','language':'eng','evidence':'ffprobe-partial'}
                ]}) as probe:
            with con:
                result=portals.probe_archive_variant(
                    con,item['id'],'film.mkv',acknowledged=True)
        self.assertEqual(result['audio_languages_from_tracks'],['de'])
        self.assertEqual(result['subtitle_languages_from_tracks'],['en'])
        self.assertEqual(result['kind'],'bounded_http_range')
        self.assertTrue(result['track_metadata_partial'])
        self.assertFalse(result['download_allowed'])
        self.assertEqual(probe.call_count,1)
        kwargs=probe.call_args.kwargs
        self.assertLessEqual(kwargs['max_total_bytes'],8*1024*1024)
        self.assertEqual(probe.call_args.args[0],
                         'https://archive.org/download/movie_test/film.mkv')
        saved=portals.archive_saved_detail(con,item['id'])
        self.assertEqual(saved['probes']['film.mkv']['bytes_sampled'],1048576)
        self.assertFalse(any(name in {'jobs','offers'} for (name,) in
                         con.execute("SELECT name FROM sqlite_master WHERE type='table'")))

    def test_unlisted_clips_and_invalid_targets_cannot_be_probed(self):
        con=sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        portals.initialize(con)
        item=portals.entry('internet_archive','movie_test','A Movie',
                           'https://archive.org/details/movie_test')
        with con:portals.save(con,[item])
        with con:
            portals.save_archive_detail(con,item['id'],
                portals.archive_detail_document('movie_test',movie_manifest(200)))
        with patch('portal_sources.archive_probe.inspect',
                   side_effect=AssertionError('No HTTP should run')) as probe:
            for name in ('trailer.mp4','small_00001.mp4','film.pdf','../film.mkv'):
                with self.subTest(name=name),self.assertRaises(ValueError):
                    portals.probe_archive_variant(con,item['id'],name,acknowledged=True)
        probe.assert_not_called()

    def test_archive_media_range_refuses_full_file_and_wrong_host(self):
        with self.assertRaisesRegex(ValueError,'Only HTTPS Archive.org'):
            media_probe.fetch_range('https://evil.example/movie.mp4',0,100)
        with self.assertRaisesRegex(ValueError,'Invalid bounded range'):
            media_probe.fetch_range('https://archive.org/download/test/movie.mp4',
                                    0,3*1024*1024)


if __name__=='__main__':
    unittest.main()
