"""0.5.59: Rakuten-TV-Livesender – Anfrage wie die Website, Grund bei fehlendem Stream."""
import io
import json
import unittest
import urllib.error

import rakuten as rk

ROW = {'id': 'c.top-movies-rakuten-tv', 'path': 'top-movies-rakuten-tv'}
LONG = ('https://top-movies-rakuten-tv-de.fast.rakuten.tv/v1/master/abc/production-hls-aes128-rtv-5985-playout/'
        'master.m3u8?' + '&'.join('ads.k%d=v' % i for i in range(300)))


class LiveRequestTests(unittest.TestCase):
    def setUp(self):
        rk._SOURCES.clear()

    def test_query_and_body_like_website(self):
        calls = []

        def api(path, query=None, body=None):
            calls.append((path, query, body))
            return {'data': {'stream_infos': [{'player': rk.LIVE_PLAYER, 'url': LONG}]}}
        self.assertGreater(len(LONG), 2000)
        self.assertEqual(rk.live_stream(ROW, api, now=1.0), LONG)
        path, query, body = calls[0]
        self.assertEqual(path, 'avod/streamings')
        self.assertEqual(query['unique_session_id'], body['unique_session_id'])
        self.assertEqual((query['device_stream_video_quality'], query['disable_dash_legacy_packages']), ('FHD', 'false'))
        self.assertEqual((body['content_type'], body['player'], body['app_bundle']),
                         ('live_channels', 'web:HLS-NONE:NONE', 'com.rakutentv.web'))

    def test_other_cdn_host_accepted(self):
        url = 'https://abc.mediatailor.eu-west-1.amazonaws.com/v1/master/x/y/master.m3u8'
        self.assertEqual(rk.stream_info({'data': {'stream_infos': [{'url': url}]}})[0], url)

    def test_reason_when_no_stream(self):
        cases = (({'data': {'type': 'streamings', 'heartbeat': {}}}, 'ohne Streamliste'),
                 ({'data': {'stream_infos': [{'player': 'web:HLS-NONE:NONE'}]}}, 'ohne Adresse'),
                 ({'data': {'stream_infos': []}, 'errors': [{'code': 'error.geo'}]}, 'error.geo'),
                 ({'data': {'stream_infos': [{'url': 'http://x.rakuten.tv/a'}]}}, 'Adresse abgelehnt'))
        for answer, needle in cases:
            rk._SOURCES.clear()
            with self.assertRaisesRegex(ValueError, 'keinen Stream.*' + needle):
                rk.live_stream(ROW, lambda *a, **k: answer, now=1.0)

    def test_http_error_carries_rakuten_message(self):
        body = io.BytesIO(json.dumps({'errors': [{'code': 'x', 'message': 'Inhalt nicht verfügbar'}]}).encode())
        exc = urllib.error.HTTPError('https://gizmo.rakuten.tv/v3/avod/streamings', 422, 'x', {}, body)
        self.assertEqual(rk._http_detail(exc), 'Rakuten TV antwortet mit HTTP 422: Inhalt nicht verfügbar')


if __name__ == '__main__':
    unittest.main()
