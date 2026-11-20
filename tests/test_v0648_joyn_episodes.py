"""0.6.48: Joyn episode lists from the series page (RSC payload), free/Joyn+ per episode.

The synthetic page follows the shape found on Björn's Mac on 20.11.2026 (www.joyn.de/serien/<slug>,
``self.__next_f.push([1,"…"])`` chunks with Episode objects). If the saved real pages of that day are in
the project folder, they are checked as well (counts reported from the Mac)."""
import json
import os
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path

import joyn
import portal_title

SAMPLES = Path('/mnt/project-files/joyn_serienseiten_2026-11-20.zip')


def episode(ident, season, number, title, licence='AVOD', series='a_stromberg'):
    return {'id': ident, '__typename': 'Episode',
            'primaryImage': {'url': 'https://img.joyn.de/ingest/%s.jpg/profile:nextgen-web-livestill-503x283' % ident},
            'number': number, 'airdate': 1720994400, 'endsAt': 253402297199, 'title': title,
            'path': '/serien/stromberg/%d-%d-%s' % (season, number, title.lower().replace(' ', '-')),
            'genres': [{'name': 'Comedy', '__typename': 'Genre'}], 'season': {'id': 'c_s%d' % season, 'seasonNumber': season},
            'licenseTypes': [licence], 'series': {'id': series, 'title': 'Stromberg'},
            'video': {'id': 'v_' + ident, 'duration': 1500}, 'ageRating': {'minAge': 12}}


def rsc_page(nodes):
    """HTML with the payload split over two push chunks (the split runs through an object)."""
    text = '0:["$","div",null,{"children":' + json.dumps(nodes, separators=(',', ':')) + '}]\n'
    half = len(text) // 2
    chunks = [text[:half], text[half:]]
    return '<html><body>' + ''.join('<script>self.__next_f.push([1,%s])</script>' % json.dumps(c) for c in chunks) + '</body></html>'


PAGE = rsc_page([episode('b_e1', 1, 1, 'Der Neue'), episode('b_e2', 1, 2, 'Lebenslauf'),
                 episode('b_e3', 2, 1, 'Das Praktikum', licence='SVOD'),
                 episode('b_e1', 1, 1, 'Der Neue'),                                   # repeated on the page
                 episode('b_other', 1, 1, 'Andere Serie', series='a_other')])          # recommendation


class JoynEpisodesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        joyn._EPISODE_TIME.clear()
        db = joyn._connect(self.root)
        with db:
            joyn._store(db, [{'id': 's.a_stromberg', 'kind': 'series', 'title': 'Stromberg', 'path': '/serien/stromberg',
                              'series_id': '', 'season': None, 'episode': None, 'year': None, 'duration': None, 'rating': '',
                              'genre': 'Comedy', 'summary': '', 'poster': '', 'imdb_id': '', 'imdb_score': None,
                              'imdb_votes': None, 'number': None, 'category': joyn.FREE, 'brand': 'ProSieben', 'offer': 'free',
                              'seasons': 2, 'quality': '', 'playable': 0, 'drm': 1,
                              'web_url': 'https://www.joyn.de/serien/stromberg'}], 1794500000.0)
            joyn._set(db, 'last_success', 1794500000.0)
        db.close()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        return PAGE

    def test_parse_page(self):
        nodes = joyn.page_episodes(PAGE, 'a_stromberg')
        self.assertEqual(sorted(n['id'] for n in nodes), ['b_e1', 'b_e2', 'b_e3'])
        self.assertEqual(len(joyn.page_episodes(PAGE)), 4)

    def test_episodes_with_offer_per_episode(self):
        data = joyn.episodes(self.root, 's.a_stromberg', fetch=self.fetch, now=1794600000.0)
        self.assertEqual(self.calls, ['https://www.joyn.de/serien/stromberg'])
        items = data['items']
        self.assertEqual([(e['season'], e['episode'], e['badge']) for e in items],
                         [(1, 1, 'Kostenlos'), (1, 2, 'Kostenlos'), (2, 1, 'Joyn+')])
        self.assertEqual(data['counts'], {'episodes': 3, 'plus': 1, 'free': 2, 'seasons': 2})
        self.assertEqual(items[0]['web_url'], 'https://www.joyn.de/serien/stromberg/1-1-der-neue')
        self.assertEqual(items[0]['duration'], 1500)
        self.assertEqual(items[0]['rating'], 'FSK 12')
        self.assertEqual(items[0]['playable'], 0)
        # kept 12 hours: no new request when the page is opened again
        joyn.episodes(self.root, 's.a_stromberg', fetch=self.fetch, now=1794600000.0 + 3600)
        self.assertEqual(len(self.calls), 1)
        joyn.episodes(self.root, 's.a_stromberg', fetch=self.fetch, now=1794600000.0 + joyn.EPISODE_TTL + 1)
        self.assertEqual(len(self.calls), 2)

    def test_failed_read_keeps_the_stored_list(self):
        joyn.episodes(self.root, 's.a_stromberg', fetch=self.fetch, now=1794600000.0)

        def down(url):
            raise urllib.error.URLError('offline')
        data = joyn.episodes(self.root, 's.a_stromberg', fetch=down, now=1794600000.0 + joyn.EPISODE_TTL + 1)
        self.assertEqual(len(data['items']), 3)
        self.assertEqual(data['note'], '')

    def test_title_page_and_episode_detail(self):
        joyn.PAGE_FETCH = self.fetch
        try:
            m = portal_title.model(self.root, 'joyn', 's.a_stromberg')
        finally:
            joyn.PAGE_FETCH = None
        self.assertEqual([e['badge'] for e in m['episodes']], ['Kostenlos', 'Kostenlos', 'Joyn+'])
        self.assertTrue(all(not e['playable'] for e in m['episodes']))
        detail = joyn.item(self.root, 'e.b_e3')
        self.assertEqual(detail['item']['offer_label'], joyn.PLUS)
        self.assertEqual(detail['series']['id'], 's.a_stromberg')
        self.assertEqual(detail['item']['web_url'], 'https://www.joyn.de/serien/stromberg/2-1-das-praktikum')

    def test_only_series_pages_on_joyn(self):
        for bad in ('/filme/x', 'https://evil.example/serien/x', '/serien/../x', ''):
            with self.assertRaises(ValueError):
                joyn.series_page(bad, opener=self.fetch)

    @unittest.skipUnless(SAMPLES.exists(), 'gespeicherte Joyn-Seiten vom 20.11.2026 fehlen')
    def test_real_pages_of_20_11_2026(self):
        expected = {'navy-cis.html': (445, 23), 'dittsche-das-wirklich-wahre-leben.html': (184, 20),
                    'geordie-shore-dpg06lv0kptr.html': (212, 23)}
        with zipfile.ZipFile(SAMPLES) as z:
            for name, (count, seasons) in expected.items():
                html = z.read(name).decode('utf-8')
                nodes = joyn.page_episodes(html)
                series = {n['series']['id'] for n in nodes}
                main = max(series, key=lambda s: sum(1 for n in nodes if n['series']['id'] == s))
                rows = [joyn.episode_row(n, 's.' + main, 0) for n in joyn.page_episodes(html, main)]
                self.assertEqual((len(rows), len({r['season'] for r in rows})), (count, seasons), name)
                self.assertTrue(all(r and r['offer'] in ('free', 'plus') for r in rows), name)


if __name__ == '__main__':
    unittest.main()
