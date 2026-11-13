"""0.5.90: every Joyn live channel opens its own player page.

Björn (13.11.2026): "joyn zeigt immer noch auf arte bei den tv sendern". Catalogues up to 0.5.89
linked the brand page (/channels/…) or, for 114 of the 128 channels of his recording, the bare
https://www.joyn.de/play/live-tv, which plays Joyn's default channel. The website itself links
/play/live-tv?channel_id=<Brand.id>. The nodes below have the shape of Björn's recording."""
import tempfile
import unittest
from pathlib import Path

import joyn
import live_tv


def node(brand_id, title, live_id, path=None, groups=('PUBLIC_VALUE',), markings=(), radio=False):
    return {'id': brand_id, 'title': title, '__typename': 'Brand', 'path': path, 'isRadio': radio,
            'logo': {'type': 'BRAND_LOGO', 'url': 'https://img.joyn.de/cms/%s.png' % live_id},
            'livestream': {'id': live_id, 'title': title, 'quality': 'HD', 'liveStreamGroups': list(groups),
                           'markings': list(markings)}, 'audioStreams': []}


LIVE = [node('165', 'Das Erste', 'daserste-de-hd', '/channels/das-erste'),
        node('1043', 'Sat.1 Bayern', 'sat1-bayern-de-sd'),
        node('2', 'SAT.1', 'sat1-de', '/mediatheken/sat1'),
        node('1007', 'Arte', 'arte-de-hd', '/channels/arte'),
        node('1104', 'Naruto', 'naruto-hd', groups=()),
        node('bbc-earth', 'BBC Earth', 'bbc-earth-hd', groups=()),
        node('1000', 'ProSieben FUN', 'prosiebenfun-de-hd', markings=('PLUS',))]
NAVIGATION = {'data': {'navigation': [], 'mediatheken': {'blocks': []}, 'liveTv': LIVE,
                       'movieGenre': {'blocks': [{'assets': [{'__typename': 'GenreItem', 'path': '/filme/genre/horror'}]}]},
                       'seriesGenre': {'blocks': []}}}
FILM = {'__typename': 'Movie', 'id': 'b_film', 'title': 'Film', 'path': '/filme/film', 'licenseTypes': ['AVOD'],
        'markings': [], 'genres': [], 'brands': [], 'description': '', 'images': []}


class Api:
    def __init__(self):
        self.calls = []

    def __call__(self, operation, variables=None):
        self.calls.append(operation)
        if operation == 'Navigation':
            return NAVIGATION
        if operation == 'GenresPaths':
            return {'data': {}}
        if variables.get('offset'):
            return {'data': {'page': {'blocks': [{'assets': []}]}}}
        return {'data': {'page': {'blocks': [{'assets': [FILM]}]}}}


class JoynLiveLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return joyn.sync(self.root, request=Api(), now=1794500000.0, gap=0)

    def test_each_channel_links_its_own_player_page(self):
        links = {joyn.channel_from(n)['title']: joyn.channel_from(n)['web_url'] for n in LIVE}
        self.assertEqual(links['Arte'], 'https://www.joyn.de/play/live-tv?channel_id=1007')
        self.assertEqual(links['Naruto'], 'https://www.joyn.de/play/live-tv?channel_id=1104')
        self.assertEqual(links['Sat.1 Bayern'], 'https://www.joyn.de/play/live-tv?channel_id=1043')
        self.assertEqual(links['BBC Earth'], 'https://www.joyn.de/play/live-tv?channel_id=bbc-earth')
        # No channel shares its link with another one, and none is the bare live page.
        self.assertEqual(len(set(links.values())), len(LIVE))
        self.assertNotIn('https://www.joyn.de/play/live-tv', links.values())

    def test_unusable_brand_id_gives_no_link(self):
        for bad in ('', None, '../x', '1&from=evil', 'a b', 'x' * 90):
            self.assertEqual(joyn.live_url(bad), '', bad)
        self.assertFalse(joyn.live_link_current('https://www.joyn.de/play/live-tv'))
        self.assertFalse(joyn.live_link_current('https://www.joyn.de/channels/arte'))
        self.assertTrue(joyn.live_link_current(joyn.live_url('1007')))

    def test_live_tab_never_offers_a_wrong_channel(self):
        self.load()
        found = {c['station']: c for c in live_tv.joyn_channels(self.root)}
        self.assertEqual(found['arte']['key'], 'arte')     # merged with ARD/ZDF & Co.'s arte
        self.assertEqual(found['arte']['link'], 'https://www.joyn.de/play/live-tv?channel_id=1007')
        self.assertEqual(found['Naruto']['link'], 'https://www.joyn.de/play/live-tv?channel_id=1104')
        self.assertEqual(len({c['link'] for c in found.values()}), len(found))

    def _age_links(self):
        """Store the links as 0.5.65–0.5.89 did."""
        db = joyn._connect(self.root)
        with db:
            db.execute("UPDATE joyn_items SET web_url='https://www.joyn.de/play/live-tv' WHERE kind='channel' AND id<>'c.arte-de-hd'")
            db.execute("UPDATE joyn_items SET web_url='https://www.joyn.de/channels/arte' WHERE id='c.arte-de-hd'")
        db.close()

    def test_old_catalogue_hides_wrong_links_and_is_repaired_with_one_request(self):
        self.load()
        self._age_links()
        self.assertEqual(joyn.live_links_outdated(self.root), len(LIVE))
        found = live_tv.joyn_channels(self.root)
        self.assertTrue(all(c['link'] == '' for c in found))
        self.assertTrue(all('Direktlink folgt' in c['quality'] for c in found))
        listed = joyn.listing(self.root, 'live')['items']
        self.assertTrue(all(c['web_url'] == '' for c in listed))
        self.assertEqual(joyn.item(self.root, 'c.arte-de-hd')['item']['web_url'], '')
        self.assertTrue(joyn._links_due(self.root, joyn.state(self.root), now=1794500100.0))

        api = Api()
        result = joyn.refresh_live_links(self.root, request=api, now=1794500100.0)
        self.assertEqual((result['ok'], result['updated']), (True, len(LIVE)))
        self.assertEqual(api.calls, ['Navigation'])
        self.assertEqual(joyn.live_links_outdated(self.root), 0)
        found = {c['station']: c for c in live_tv.joyn_channels(self.root)}
        self.assertEqual(found['arte']['link'], 'https://www.joyn.de/play/live-tv?channel_id=1007')
        self.assertIn('bei Joyn ansehen', found['arte']['quality'])
        # Films and series are not touched by the link refresh.
        self.assertEqual(joyn.listing(self.root, 'movies')['items'][0]['web_url'], 'https://www.joyn.de/filme/film')
        self.assertFalse(joyn._links_due(self.root, joyn.state(self.root), now=1794500200.0))

    def test_failed_refresh_waits_an_hour(self):
        self.load()
        self._age_links()

        def broken(operation, variables=None):
            raise OSError('timeout')
        result = joyn.refresh_live_links(self.root, request=broken, now=1794500100.0)
        self.assertFalse(result['ok'])
        self.assertFalse(joyn._links_due(self.root, joyn.state(self.root), now=1794500100.0 + 60))
        self.assertTrue(joyn._links_due(self.root, joyn.state(self.root), now=1794500100.0 + joyn.LINK_RETRY))


if __name__ == '__main__':
    unittest.main()
