"""0.6.6: choice of audio track and subtitles in the player (tracks.py) and the OmU label.

Björn (14.11.2026): "das mit OmU scheint zwar mit dem Titel bei Plex zu klappen, jedoch war der
Stream dann deutsch mit Untertitel, die aber nicht abgespielt wurden bzw. auch nicht ausgewählt
werden konnten"."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import languages  # noqa: E402
import plex  # noqa: E402
import streaming  # noqa: E402
import tracks  # noqa: E402

MASTER = '\n'.join([
    '#EXTM3U',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="de",NAME="Deutsch",DEFAULT=YES',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",LANGUAGE="en",NAME="English"',
    '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="hi",LANGUAGE="en",NAME="English HQ"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="de",NAME="Deutsch",URI="subs/de.m3u8"',
    '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="de",NAME="Deutsch (forced)",FORCED=YES,URI="subs/f.m3u8"',
    '#EXT-X-STREAM-INF:BANDWIDTH=1000000,AUDIO="aac",SUBTITLES="subs"',
    '720.m3u8'])

MPD = '''<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><BaseURL>https://cdn.example/v/</BaseURL><Period>
 <AdaptationSet contentType="video"><Representation id="v1" mimeType="video/mp4"/></AdaptationSet>
 <AdaptationSet mimeType="audio/mp4" lang="de"><Representation id="a1"/><Representation id="a2"/></AdaptationSet>
 <AdaptationSet mimeType="audio/mp4" lang="en"><Role value="main"/><Representation id="a3"/></AdaptationSet>
 <AdaptationSet mimeType="application/ttml+xml" lang="de"><Representation id="t1"><BaseURL>sub_de.ttml</BaseURL></Representation></AdaptationSet>
 <AdaptationSet contentType="text" mimeType="text/vtt" lang="en"><SegmentTemplate media="x$Number$.vtt"/><Representation id="t2"/></AdaptationSet>
</Period></MPD>'''

TTML = b'''<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:frameRate="25"><body><div>
<p begin="00:00:01.500" end="00:00:03.000">Hallo <span>Welt</span></p>
<p begin="00:01:00:12" dur="2s">Zweite<br/>Zeile &amp; mehr</p>
<p begin="10000000t" end="20000000t">Ticks</p>
</div></body></tt>'''

SRT = '1\r\n00:00:02,000 --> 00:00:04,500\r\nErste Zeile\r\n\r\n2\r\n00:00:10,000 --> 00:00:12,000\r\n<i>Zweite</i>\r\n'


class ParseTests(unittest.TestCase):
    def test_hls_tracks(self):
        audio, subs = tracks.hls_tracks(MASTER, 'https://cdn.example/x/master.m3u8')
        self.assertEqual([a['lang'] for a in audio], ['de', 'en'], 'only the first audio group')
        self.assertEqual(subs[0]['url'], 'https://cdn.example/x/subs/de.m3u8')
        self.assertTrue(subs[1]['forced'])

    def test_dash_tracks(self):
        audio, subs = tracks.dash_tracks(MPD, 'https://cdn.example/manifest.mpd')
        self.assertEqual([(a['lang'], a['reps']) for a in audio], [('de', 2), ('en', 1)])
        self.assertEqual(len(subs), 1, 'segmented text tracks are not offered')
        self.assertEqual(subs[0]['url'], 'https://cdn.example/v/sub_de.ttml')
        self.assertEqual(subs[0]['format'], 'ttml')
        self.assertEqual(tracks.dash_tracks('<kaputt', 'x'), ([], []))

    def test_ttml_and_srt(self):
        cues = tracks.cues_from_ttml(TTML)
        self.assertEqual(cues[0], (1.5, 3.0, 'Hallo Welt'))
        self.assertAlmostEqual(cues[1][0], 60.48)
        self.assertEqual(cues[1][2], 'Zweite\nZeile &amp; mehr')
        self.assertEqual(cues[2][:2], (1.0, 2.0))
        srt = tracks.cues_from_vtt(SRT)
        self.assertEqual(srt[0], (2.0, 4.5, 'Erste Zeile'))
        self.assertEqual(srt[1][2], '<i>Zweite</i>')

    def test_vtt_offset(self):
        text = tracks.to_vtt([(2.0, 4.5, 'A'), (10.0, 12.0, 'B'), (0.5, 1.0, 'weg')], offset=3.0)
        self.assertTrue(text.startswith('WEBVTT'))
        self.assertIn('00:00:00.000 --> 00:00:01.500\nA', text)
        self.assertIn('00:00:07.000 --> 00:00:09.000\nB', text)
        self.assertNotIn('weg', text)


class SourceTests(unittest.TestCase):
    def setUp(self):
        tracks._CACHE.clear()

    def test_provider_subtitles_and_choice(self):
        source = {'kind': 'url', 'url': 'https://cdn.example/a.mp4', 'hls': False, 'provider': 'mediathek',
                  'subtitles': [{'url': 'https://cdn.example/a.xml', 'lang': 'de', 'origin': 'provider'}]}
        out = tracks.list_tracks(source)
        self.assertEqual(out['audio'], [])
        self.assertEqual(out['subtitles'][0]['id'], 's0')
        self.assertIn('Deutsch', out['subtitles'][0]['label'])
        with mock.patch.object(tracks, '_get', return_value=(TTML, 'https://cdn.example/a.xml')):
            vtt = tracks.subtitle_vtt(source, 's0', 0)
        self.assertIn('Hallo Welt', vtt)
        with self.assertRaises(ValueError):
            tracks.subtitle_vtt(source, 's5')
        with self.assertRaises(ValueError):
            tracks.subtitle_vtt(source, '../x')

    def test_dash_source_audio_index(self):
        source = {'kind': 'url', 'url': 'https://cdn.example/manifest.mpd', 'hls': False, 'dash': True, 'provider': 'plex'}
        with mock.patch.object(tracks, '_get', return_value=(MPD.encode(), 'https://cdn.example/manifest.mpd')):
            out = tracks.list_tracks(source)
            self.assertEqual([a['id'] for a in out['audio']], ['a0', 'a1'])
            self.assertEqual(tracks.audio_index(source, 'a1'), 2, 'ffmpeg counts every audio representation')
            self.assertIsNone(tracks.audio_index(source, 'x'))
            self.assertEqual(tracks.observed(source), {'audio': ['de', 'en'], 'subtitles': ['de']})

    def test_hls_source_has_no_audio_choice(self):
        source = {'kind': 'url', 'url': 'https://cdn.example/x/master.m3u8', 'hls': True}
        with mock.patch('hls_variants.load', return_value=(MASTER, 'https://cdn.example/x/master.m3u8')):
            out = tracks.list_tracks(source)
        self.assertEqual(out['audio'], [], 'the remuxed one-level playlist keeps no alternative audio')
        self.assertEqual(len(out['subtitles']), 2)
        self.assertIsNone(tracks.audio_index(source, 'a1'))

    def test_local_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            film = Path(tmp) / 'Film (2020).mkv'
            film.write_bytes(b'')
            (Path(tmp) / 'Film (2020).de.srt').write_text(SRT, encoding='utf-8')
            (Path(tmp) / 'Film (2020).ass').write_text('x', encoding='utf-8')
            source = {'kind': 'file', 'path': str(film)}
            with mock.patch.object(tracks, '_probe', return_value=[]):
                out = tracks.list_tracks(source)
                self.assertEqual(len(out['subtitles']), 1)
                self.assertIn('Erste Zeile', tracks.subtitle_vtt(source, 's0', 0))


class CommandTests(unittest.TestCase):
    def test_audio_map(self):
        with mock.patch.object(streaming, 'tool', return_value='/usr/bin/ffmpeg'):
            args = streaming.command({'kind': 'file', 'path': '/tmp/x.mkv'}, 0, True, audio_track=1)
            plain = streaming.command({'kind': 'file', 'path': '/tmp/x.mkv'}, 0, True)
        self.assertIn('0:a:1', args)
        self.assertNotIn('0:a:1', plain)


class PlexTests(unittest.TestCase):
    def test_subtitle_streams(self):
        answer = {'MediaContainer': {'Metadata': [{'Media': [{'Part': [{'Stream': [
            {'streamType': 2, 'languageTag': 'de'},
            {'streamType': 3, 'key': '/library/streams/77', 'codec': 'srt', 'languageTag': 'de', 'displayTitle': 'Deutsch (SRT)'},
            {'streamType': 3, 'key': '/library/streams/78', 'codec': 'pgs', 'languageTag': 'en'},
            {'streamType': 3, 'codec': 'srt', 'languageTag': 'fr'},
            {'streamType': 3, 'key': '/../etc', 'codec': 'srt'}]}]}]}]}}
        subs = plex.subtitle_streams(answer, 'cid', 'tok')
        self.assertEqual(len(subs), 1)
        self.assertTrue(subs[0]['url'].startswith(plex.VOD + '/library/streams/77?'))
        self.assertEqual((subs[0]['lang'], subs[0]['format']), ('de', 'srt'))


class OmuLabelTests(unittest.TestCase):
    def test_title_omu_contradicted_by_german_stream(self):
        m = languages.build('plex', observed={'stream': {'audio': ['de'], 'subtitles': ['de']}}, titles=['Film (OmU)'])
        self.assertFalse(m['original'])
        self.assertNotIn('OmU', m['short'])
        self.assertIn('der Ton ist aber Deutsch', ' '.join(e['label'] for e in m['evidence']))

    def test_title_omu_without_measurement_stays(self):
        self.assertEqual(languages.build('plex', titles=['Film (OmU)'])['short'], 'OmU')

    def test_title_omu_with_foreign_stream_stays(self):
        m = languages.build('plex', observed={'stream': {'audio': ['en'], 'subtitles': ['de']}}, titles=['Film (OmU)'])
        self.assertTrue(m['original'])
        self.assertEqual(m['short'], 'OmU')


if __name__ == '__main__':
    unittest.main()
