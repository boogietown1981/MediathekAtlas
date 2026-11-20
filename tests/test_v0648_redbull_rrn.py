"""0.6.48: Red Bull TV with the resource names found on Björn's Mac (live network, 20.11.2026).

0.6.47 dropped every Red Bull TV card ("Red Bull TV lieferte keine Videos"): the ids are resource names
("page:rrn:content:films:<uuid>", "rrn:content:shows:<uuid>"), collections "playlists::<uuid>" and
"rrn:content:collections:<uuid>". The uuids below are made up, the shapes are the recorded ones."""
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import redbulltv
import servustv
from test_v0647_redbull_news import http_error

U = '%08x-1d4c-4d15-b379-26bc0c919234'
FILM_ID = 'rrn:content:films:' + U % 1
SHOW_ID = 'rrn:content:shows:' + U % 2
EP_IDS = ['rrn:content:episodes:' + U % (10 + n) for n in (1, 2)]
EVENT_ID = 'rrn:content:event-profiles:' + U % 3
FILMS_COLL, SERIES_COLL, EVENTS_COLL = 'playlists::' + U % 20, U % 21, 'rrn:content:collections:' + U % 22
SHOW_COLL = U % 23


def card(ident, title, ctype, **extra):
    raw = ident.split(':', 1)[1] if ident.startswith('page:') else ident
    base = {'id': ident, 'title': title, 'type': 'page' if ident.startswith('page:') or ctype == 'show' else 'video',
            'content_type': ctype, 'duration': 3120000, 'long_description': 'Über ' + title,
            'share_url': 'https://www.redbull.tv/de/video/%s/%s' % (raw, title.lower().replace(' ', '-'))}
    base.update(extra)
    return base


PRODUCTS = {'discover': {'id': 'discover', 'type': 'page', 'collections': [
                {'id': FILMS_COLL}, {'id': SERIES_COLL}, {'id': EVENTS_COLL}]},
            SHOW_ID: {'id': SHOW_ID, 'content_type': 'show', 'title': 'Frontiers', 'collections': [{'id': SHOW_COLL}]}}
COLLECTIONS = {FILMS_COLL: [card('page:' + FILM_ID, 'Into the Wild Line', 'film')],
               SERIES_COLL: [card(SHOW_ID, 'Frontiers', 'show')],
               EVENTS_COLL: [card(EVENT_ID, 'Red Bull Rampage', 'event_profile')],
               SHOW_COLL: [card(i, 'Folge %d' % n, 'episode', season_number=1, episode_number=n) for n, i in enumerate(EP_IDS, 1)]}


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, limit=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((parts.path, q))
        if parts.hostname == 'tv-api.redbull.com':
            kind, ident = parts.path.split('/rbtv/de/int/')
            if kind == '/products/v5.3':
                data = PRODUCTS.get(ident)
            else:
                cards = COLLECTIONS.get(ident)
                data = {'cards': cards, 'meta': {'total': len(cards)}} if cards is not None else None
            if data is None:
                raise http_error(url, 404)
            return json.dumps(data).encode()
        if parts.hostname == 'api-player.redbull.com':
            if q['tenant'] != 'rbtv':
                raise http_error(url, 404)
            return json.dumps({'videoUrl': 'https://play.redbull.com/main/v1/rbtv/de/de/personal_computer/http/%s.m3u8'
                                           '?device_group=group_5' % q['videoId'], 'playabilityErrors': []}).encode()
        raise AssertionError(url)


class RedBullRrnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        servustv._SOURCES.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalogue_with_resource_names(self):
        result = redbulltv.sync(self.root, opener=Fake(), now=1794556800)
        self.assertTrue(result['ok'], result)
        films = redbulltv.listing(self.root, view='movies')['items']
        self.assertEqual([(f['id'], f['title']) for f in films], [('v.' + FILM_ID, 'Into the Wild Line')])
        self.assertEqual(films[0]['web_url'], 'https://www.redbull.tv/de/video/%s/into-the-wild-line' % FILM_ID)
        series = redbulltv.listing(self.root, view='series')['items']
        self.assertEqual([s['id'] for s in series], ['s.' + SHOW_ID])
        eps = redbulltv.episodes(self.root, 's.' + SHOW_ID)['items']
        self.assertEqual([e['id'] for e in eps], ['v.' + i for i in EP_IDS])

    def test_playback_with_rbtv_tenant(self):
        redbulltv.sync(self.root, opener=Fake(), now=1794556800)
        src = redbulltv.play_source(self.root, 'v.' + FILM_ID, opener=Fake(), check=lambda url: None, now=1794556800)
        self.assertTrue(src['url'].startswith('https://play.redbull.com/main/v1/rbtv/de/de/personal_computer/http/'))

    def test_servustv_ids_unchanged(self):
        for ok in ('v.AA-1Q6XCDTAN1W11', 's.AA-25RX849FN1W11', 'c.PN0B1EC15B2FE10', 's.n-bergwelten', 'v.' + FILM_ID):
            self.assertTrue(servustv.VALID_ID.fullmatch(ok), ok)
        for bad in ('v.rrn:content:films:../x', 'v.page:' + FILM_ID, 'v.rrn:content:films:1234', 's.aa'):
            self.assertFalse(servustv.VALID_ID.fullmatch(bad), bad)


if __name__ == '__main__':
    unittest.main()
