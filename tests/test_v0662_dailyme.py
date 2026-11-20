"""0.6.62: dailyme TV as a catalogue with links.

The pages below follow what dailyme.de sent on 20.11.2026 (read from outside the build environment, which cannot
reach the site): server-rendered HTML under a JavaScript app ("You need to enable JavaScript to run this app."),
programmes as /content/show/<id>-<slug>/, episodes as /content/show/<id>-<slug>/<id>-<slug>, film page title
"… – ganzer Film kostenlos ansehen | dailyme TV" with "Kompletter Film · 2015", "FSK 12", "Abspielen 1:44:54",
series episodes "… kostenlos streamen | dailyme 24:12 Staffel 1, Folge N: …", robots.txt with
``Disallow: /content/player/`` and sitemaps under /fast/. Titles and ids are partly made up. Playback never
happens here: every title opens on dailyme.de."""
import tempfile
import unittest
import urllib.error

import dailyme
import dailyme_enrichment
import platform_registry
import portal_title
import unified_index
import streaming

NOW = 1795132800
JS = '<noscript>You need to enable JavaScript to run this app.</noscript>'

ROBOTS = """# Kommentare zu den Sitemaps
User-agent: *
Allow: /
Disallow: /microsites_static/
Disallow: /content/player/
Sitemap: https://www.dailyme.de/fast/inhalte-sitemap.xml
Sitemap: https://www.dailyme.de/fast/news-sitemap.xml
Sitemap: https://www.dailyme.de/fast/video-sitemap.xml
"""

VIDEO_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:video="http://www.google.com/schemas/sitemap-video/1.1">
<url><loc>https://www.dailyme.de/content/show/21534-tierwelt-live-weite-welt/4499038-abenteuer-kongo</loc>
 <video:video><video:thumbnail_loc>https://i.selocon.com/clips/feed_58181/15966123_4499206.raw.jpg</video:thumbnail_loc>
 <video:title><![CDATA[Abenteuer Kongo]]></video:title><video:description>Expedition &amp; Natur am Kongo.</video:description>
 <video:player_loc>https://www.dailyme.de/content/player/21534-tierwelt-live-weite-welt/4499038-abenteuer-kongo</video:player_loc>
 <video:duration>2659</video:duration><video:publication_date>2024-03-01T10:00:00+01:00</video:publication_date></video:video></url>
<url><loc>https://www.dailyme.de/content/show/21534-tierwelt-live-weite-welt/4499039-hawaii</loc>
 <video:video><video:title>Hawaii</video:title><video:duration>2666</video:duration></video:video></url>
<url><loc>https://example.org/content/show/1-fremd/2-fremd</loc></url>
</urlset>"""

INHALTE_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.dailyme.de/fast/inhalte-1.xml</loc></sitemap></sitemapindex>"""
INHALTE_1 = """<?xml version="1.0"?><urlset><url><loc>https://www.dailyme.de/content/impressum</loc></url>
<url><loc>https://www.dailyme.de/content/show/24829-heidi/</loc></url>
<url><loc>https://www.dailyme.de/content/show/21534-tierwelt-live-weite-welt/</loc></url>
<url><loc>https://www.dailyme.de/content/show/21534-tierwelt-live-weite-welt/4499039-hawaii</loc></url>
<url><loc>https://www.dailyme.de/content/show/20410-verbotene-liebe-folge-401-bis-500/</loc></url>
<url><loc>https://www.dailyme.de/content/ddr/polizeiruf-110</loc></url></urlset>"""

# Shape of the programme page recorded on Björn's Mac (20.11.2026): episode links without slug, title only "Folge N"
VL_EPISODE = ('<article><a class="jss52" href="/content/show/20410-verbotene-liebe-folge-401-bis-500/%d"><div><img '
              'src="https://i.selocon.com/clips/feed_57381/rsz/400/30/x_%d.raw.jpg" alt=" kostenlos streamen | dailyme">'
              '<div><time>24:17</time></div></div><div><h3>Folge %d</h3><p></p></div></a></article>')
VERBOTENE = ('<html><head><title>Verbotene Liebe (Folge 401 bis 500) – alle Folgen | dailyme</title>'
             '<script type="application/ld+json" data-react-helmet="true">{"@context":"https://schema.org","@type":"TVSeries",'
             '"name":"Verbotene Liebe (Folge 401 bis 500)","description":"Liebesgeschichten und Intrigen.",'
             '"thumbnailUrl":"https://i.selocon.com/resources/slotPreview/previewBig20410_164890048e5.jpg"}</script>'
             '<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,'
             '"name":"Serien","item":"https://www.dailyme.de/content/theme/serien-shows-magazine"},{"@type":"ListItem","position":2,'
             '"name":"Daily Soaps","item":"https://www.dailyme.de/content/kategorie/daily-soaps"}]}</script></head><body>'
             '<nav><a href="/content/theme/filme">FILME</a><span>NEWS · KIDS</span></nav>'
             '<h1>Verbotene Liebe (Folge 401 bis 500)</h1><div><span>100 Folgen</span></div>' +
             ''.join(VL_EPISODE % (3809502 + i, 3809502 + i, 401 + i) for i in range(3)) +
             '<h2>Ähnliche Filme</h2>' + '<a href="/content/show/24329-der-amerikanische-buergerkrieg/"><span>HORROR • 1980</span></a>'
             '</body></html>')


def card(sid, slug, title, badge='', runtime='', img=True):
    picture = '<img src="https://www.dailyme.de/fast/cover/c%s.jpg" alt="%s">' % (sid, title) if img else ''
    return ('<a href="/content/show/%s-%s/">%s<span>%s</span><span>%s</span><span>%s</span></a>'
            % (sid, slug, picture, title, badge, runtime))


HOME = '<html><head><title>Serien und Filme kostenlos streamen – ohne Anmeldung | dailyme TV</title></head><body>' + JS + \
    card('23013', 'ip-man-3', 'Ip Man 3', 'ACTION · 2015 · FSK 12') + \
    card('21745', 'to-love-ru-trouble', 'To Love-Ru Trouble') + \
    '<a href="/content/theme/filme">Filme</a><a href="/content/theme/family-kids">KIDS</a>' \
    '<a href="/content/channel/anime-serien">Anime</a><a href="/content/agb">AGB</a>' \
    '<a href="https://www.dailyme.de/live-tv/netzkino-live/">Netzkino Live</a></body></html>'

FILME = '<html><body>' + JS + card('23013', 'ip-man-3', 'Ip Man 3') + \
    card('23047', 'the-good-girl', 'The Good Girl', 'Drama · 2002 · 93 Min. · FSK 12') + \
    '<a href="/content/channel/actionfilme">mehr &gt;</a><a href="/content/kategorie/familienfilme">mehr</a></body></html>'

KIDS = '<html><body>' + JS + card('24829', 'heidi', 'Heidi', 'FAMILIE · 2015 · FSK 0') + \
    card('24412', 'die-abenteuer-von-pepper-und-paula', 'Die Abenteuer von Pepper und Paula', 'KINDER/JUGEND · FSK 0') + \
    '<a href="/content/channel/filme-und-serien-fuer-vorschul-kids">mehr</a></body></html>'

ANIME = '<html><body>' + JS + card('21745', 'to-love-ru-trouble', 'To Love-Ru Trouble', '', '24:12') + '</body></html>'

IPMAN = ('<html><head><title>Ip Man 3 – ganzer Film kostenlos ansehen | dailyme TV</title>'
         '<meta name="description" content="Donnie Yen als Wing-Chun-Meister Ip Man. Kostenlos ansehen.">'
         '<meta property="og:title" content="Ip Man 3"><meta property="og:type" content="article">'
         '<meta property="og:image" content="https://i.selocon.com/resources/slotPreview/previewBig23013_18c8c63d544.jpg">'
         '<meta property="og:description" content="Donnie Yen als Wing-Chun-Meister Ip Man gegen einen Bauspekulanten.">'
         '</head><body>' + JS + '<h1>Ip Man 3</h1><div>Kompletter Film · 2015</div><div>FSK 12</div>'
         '<div>Actiongeladen · Mitreißend · Wing Chun</div><button>Abspielen</button><span>1:44:54</span>'
         '<h2>Ähnliche Filme</h2>' + card('22874', 'dog-eat-dog', 'Dog Eat Dog', '', '1:33:00') + '</body></html>')


def episode_link(n, eid, slug, title, runtime='24:12'):
    return ('<a href="https://www.dailyme.de/content/show/21745-to-love-ru-trouble/%s-%s">'
            '<img src="https://i.selocon.com/clips/x/%s.raw.jpg"><span>%s kostenlos streamen | dailyme</span>'
            '<span>%s Staffel 1, Folge %d: Was in Folge %d geschieht, ausführlich.</span></a>'
            % (eid, slug, eid, title, runtime, n, n))


LOVERU = ('<html><head><title>To Love-Ru Trouble – Anime-Serie kostenlos auf Deutsch | dailyme TV</title>'
          '<meta property="og:title" content="To Love-Ru: Trouble">'
          '<meta property="og:description" content="Rito und das Mädchen aus dem All.">'
          '<meta property="og:image" content="https://i.selocon.com/resources/slotPreview/previewBig21745_1773e9256f1.jpg">'
          '</head><body>' + JS + '<h1>To Love-Ru: Trouble</h1><div>26 Folgen</div><div>Abspielen 24:12</div>' +
          episode_link(2, '3664897', 'vom-umtausch-ausgeschlossen', 'Vom Umtausch ausgeschlossen') +
          episode_link(1, '3664896', 'das-maedchen-das-vom-himmel-fiel', 'Das Mädchen, das vom Himmel fiel') +
          episode_link(26, '3664921', 'alles-oder-nichts', 'Alles oder nichts', '23:42') +
          '<a href="/content/show/99999-andere-serie/1234567-fremde-folge">Andere Serie</a></body></html>')

TIERWELT = ('<html><head><title>TIERWELT Live - Weite Welt | dailyme TV</title>'
            '<meta property="og:title" content="TIERWELT Live - Weite Welt"></head><body>' + JS +
            '<h1>TIERWELT Live - Weite Welt</h1>'
            '<a href="/content/show/21534-tierwelt-live-weite-welt/4499038-abenteuer-kongo"><span>Abenteuer Kongo</span><span>44:19</span></a>'
            '</body></html>')

PEPPER = ('<html><head><title>Die Abenteuer von Pepper und Paula | dailyme</title>'
          '<script type="application/ld+json">{"@context":"https://schema.org","@type":"TVSeries","name":"Die Abenteuer von Pepper und Paula",'
          '"description":"Zwei Freundinnen erleben Abenteuer.","contentRating":"FSK 0","genre":["Kinder","Animation"],'
          '"episode":[{"@type":"TVEpisode","name":"Der Drache","url":"https://www.dailyme.de/content/show/24412-die-abenteuer-von-pepper-und-paula/5000001-der-drache",'
          '"episodeNumber":1,"partOfSeason":{"@type":"TVSeason","seasonNumber":1},"duration":"PT11M30S"}]}</script>'
          '</head><body>' + JS + '</body></html>')

STUB = '<html><head><title>dailyme: Kostenlose TV Serien und Shows ansehen</title></head><body>' + JS + '</body></html>'


class Site:
    """Fake dailyme.de: path -> page; records every request."""

    def __init__(self, pages=None, robots=ROBOTS):
        self.pages = {'/robots.txt': robots, '/': HOME, '/content/theme/filme': FILME, '/content/theme/family-kids': KIDS,
                      '/content/channel/anime-serien': ANIME, '/fast/video-sitemap.xml': VIDEO_SITEMAP,
                      '/fast/inhalte-sitemap.xml': INHALTE_INDEX, '/fast/inhalte-1.xml': INHALTE_1,
                      '/content/show/23013-ip-man-3/': IPMAN, '/content/show/21745-to-love-ru-trouble/': LOVERU,
                      '/content/show/21534-tierwelt-live-weite-welt/': TIERWELT,
                      '/content/show/24412-die-abenteuer-von-pepper-und-paula/': PEPPER,
                      '/content/show/24829-heidi/': STUB, '/content/show/23047-the-good-girl/': STUB,
                      '/content/show/20410-verbotene-liebe-folge-401-bis-500/': VERBOTENE,
                      '/content/kategorie/familienfilme': '<html><body>' + card('24829', 'heidi', 'Heidi') + '</body></html>'}
        if pages:
            self.pages.update(pages)
        self.calls = []

    def __call__(self, url, headers, **kw):
        assert url.startswith('https://www.dailyme.de/'), url
        assert 'MediathekAtlas' in headers['User-Agent']
        path = url[len('https://www.dailyme.de'):]
        self.calls.append(path)
        if path not in self.pages or self.pages[path] is None:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        value = self.pages[path]
        if isinstance(value, Exception):
            raise value
        return value


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self, site=None, now=NOW):
        self.site = site or Site()
        return dailyme.sync(self.root, opener=self.site, now=now)


class ParsingTests(unittest.TestCase):
    def test_robots(self):
        rules = dailyme.robots_rules(ROBOTS)
        self.assertTrue(dailyme.robots_allows(rules, '/content/show/23013-ip-man-3/'))
        self.assertTrue(dailyme.robots_allows(rules, '/fast/video-sitemap.xml'))
        self.assertFalse(dailyme.robots_allows(rules, '/content/player/21534-x/4499038-y'))
        other = dailyme.robots_rules('User-agent: Googlebot\nDisallow:\n\nUser-agent: *\nDisallow: /content/\n')
        self.assertFalse(dailyme.robots_allows(other, '/content/theme/filme'))
        self.assertTrue(dailyme.robots_allows(other, '/'))
        self.assertTrue(dailyme.robots_allows(dailyme.robots_rules(''), '/content/x'))

    def test_list_page(self):
        shows, lists = dailyme.list_page(FILME)
        self.assertEqual(set(shows), {'23013', '23047'})
        good = shows['23047']
        self.assertEqual((good['title'], good['year'], good['fsk'], good['duration']), ('The Good Girl', 2002, 12, 93 * 60))
        self.assertEqual(good['genres'], [])          # "Drama" in mixed case is not a badge genre
        self.assertEqual(good['poster'], 'https://www.dailyme.de/fast/cover/c23047.jpg')
        self.assertEqual(lists, ['/content/channel/actionfilme', '/content/kategorie/familienfilme'])
        shows, lists = dailyme.list_page(HOME)
        self.assertNotIn('/content/agb', lists)
        self.assertEqual(shows['23013']['genres'], ['Action'])

    def test_titles(self):
        self.assertEqual(dailyme.clean_title('Ip Man 3 – ganzer Film kostenlos ansehen | dailyme TV'), 'Ip Man 3')
        self.assertEqual(dailyme.clean_title('Das Mädchen kostenlos streamen | dailyme 24:12 Staffel 1, Folge 1: Text'), 'Das Mädchen')
        self.assertEqual(dailyme.clean_title('To Love-Ru Trouble – Anime-Serie kostenlos auf Deutsch | dailyme TV'),
                         'To Love-Ru Trouble – Anime-Serie kostenlos auf Deutsch')

    def test_film_page(self):
        facts, episodes, stub = dailyme.show_page(IPMAN, '23013', 'ip-man-3')
        self.assertFalse(stub)
        self.assertEqual(facts['type'], 'movie')
        self.assertEqual((facts['title'], facts['year'], facts['fsk']), ('Ip Man 3', 2015, 12))
        self.assertEqual(facts['duration'], 3600 + 44 * 60 + 54)
        self.assertTrue(facts['poster'].startswith('https://i.selocon.com/'))
        self.assertIn('Bauspekulanten', facts['summary'])
        self.assertEqual(episodes, [])               # "Ähnliche Filme" are other programmes

    def test_series_page(self):
        facts, episodes, stub = dailyme.show_page(LOVERU, '21745', 'to-love-ru-trouble')
        self.assertEqual(facts['title'], 'To Love-Ru: Trouble')
        self.assertEqual(facts['type'], '')
        by_id = {e['id']: e for e in episodes}
        self.assertEqual(set(by_id), {'3664896', '3664897', '3664921'})
        first = by_id['3664896']
        self.assertEqual((first['title'], first['season'], first['episode'], first['duration']),
                         ('Das Mädchen, das vom Himmel fiel', 1, 1, 24 * 60 + 12))
        self.assertIn('Was in Folge 1 geschieht', first['summary'])
        self.assertEqual(by_id['3664921']['duration'], 23 * 60 + 42)

    def test_json_ld(self):
        facts, episodes, _ = dailyme.show_page(PEPPER, '24412', 'die-abenteuer-von-pepper-und-paula')
        self.assertEqual((facts['type'], facts['fsk'], facts['genres']), ('series', 0, ['Kinder', 'Animation']))
        self.assertEqual([(e['id'], e['season'], e['episode'], e['duration']) for e in episodes], [('5000001', 1, 1, 690)])

    def test_stub(self):
        facts, episodes, stub = dailyme.show_page(STUB, '24829', 'heidi')
        self.assertTrue(stub)
        self.assertEqual(episodes, [])

    def test_sitemaps(self):
        kind, entries = dailyme.sitemap_entries(VIDEO_SITEMAP)
        self.assertEqual(kind, 'urls')
        self.assertEqual(len(entries), 2)            # the foreign host is left out
        self.assertEqual((entries[0]['title'], entries[0]['duration'], entries[0]['year']), ('Abenteuer Kongo', 2659, 2024))
        self.assertEqual(entries[0]['summary'], 'Expedition & Natur am Kongo.')
        self.assertEqual(dailyme.sitemap_entries(INHALTE_INDEX), ('index', ['/fast/inhalte-1.xml']))

    def test_images_only_from_known_hosts(self):
        self.assertEqual(dailyme._image('/fast/cover/b1.jpg'), 'https://www.dailyme.de/fast/cover/b1.jpg')
        self.assertEqual(dailyme._image('https://evil.example/x.jpg'), '')
        self.assertEqual(dailyme._image('http://www.dailyme.de/x.jpg'), '')


class SyncTests(Fixture):
    def test_catalogue(self):
        result = self.sync()
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['movies'], result['series']), (3, 4))   # Ip Man 3, The Good Girl, Heidi; 4 series
        calls = self.site.calls
        self.assertEqual(calls[0], '/robots.txt')
        self.assertFalse([c for c in calls if c.startswith('/content/player/')])
        self.assertNotIn('/content/agb', calls)
        self.assertNotIn('/fast/video-sitemap.xml', calls)            # news clips only (Mac, 20.11.2026)
        self.assertIn('/content/kategorie/familienfilme', calls)      # the sitemap named few programmes: lists are followed
        movies = dailyme.listing(self.root, 'movies')['items']
        ip = next(r for r in movies if r['id'] == 'm.23013')
        self.assertEqual((ip['title'], ip['year'], ip['rating'], ip['duration'], ip['playable']), ('Ip Man 3', 2015, 'FSK 12', 6294, 0))
        self.assertEqual(ip['web_url'], 'https://www.dailyme.de/content/show/23013-ip-man-3/')
        self.assertEqual(ip['badge'], 'Kostenlos mit Werbung')
        heidi = next(r for r in movies if r['id'] == 'm.24829')       # bare page: kind from the list "Familienfilme"
        self.assertEqual((heidi['rating'], heidi['title']), ('FSK 0', 'Heidi'))
        self.assertIn('Familie', heidi['genre'])
        series = {r['id']: r for r in dailyme.listing(self.root, 'series')['items']}
        self.assertEqual(series['s.21745']['episodes'], 3)
        self.assertIn('Anime', series['s.21745']['genre'])
        self.assertEqual(series['s.21534']['episodes'], 2)            # one from the page, one only in the sitemap
        vl = dailyme.episodes(self.root, 's.20410')['items']
        self.assertEqual([(e['title'], e['episode'], e['duration']) for e in vl][:2], [('Folge 401', 401, 1457), ('Folge 402', 402, 1457)])
        self.assertEqual(vl[0]['web_url'], 'https://www.dailyme.de/content/show/20410-verbotene-liebe-folge-401-bis-500/3809502')
        self.assertIn('Daily Soaps', series['s.20410']['genre'])
        self.assertNotIn('Horror', series['s.20410']['genre'])
        eps = dailyme.episodes(self.root, 's.21745')['items']
        self.assertEqual([e['episode'] for e in eps], [1, 2, 26])
        self.assertTrue(all(e['playable'] == 0 and e['web_url'].startswith('https://www.dailyme.de/content/show/21745-') for e in eps))
        kongo = {e['id']: e for e in dailyme.episodes(self.root, 's.21534')['items']}
        self.assertEqual(kongo['e.4499038']['duration'], 44 * 60 + 19)
        self.assertEqual(kongo['e.4499039']['web_url'], 'https://www.dailyme.de/content/show/21534-tierwelt-live-weite-welt/4499039-hawaii')
        pepper = dailyme.item(self.root, 's.24412')['item']
        self.assertEqual(pepper['rating'], 'FSK 0')
        state = dailyme.state(self.root)
        self.assertEqual(state['last_result'], 'complete')
        self.assertEqual(state['stubs'], 2)
        self.assertIn('dailyme-App', state['note'])

    def test_second_run_keeps_programmes_read_this_week(self):
        self.assertTrue(self.sync()['ok'])
        site = Site()
        self.assertTrue(self.sync(site, now=NOW + 3600)['ok'])
        self.assertNotIn('/content/show/21745-to-love-ru-trouble/', site.calls)
        self.assertEqual(len(dailyme.episodes(self.root, 's.21745')['items']), 3)
        self.assertEqual(len(dailyme.listing(self.root, 'movies')['items']), 3)
        site = Site()
        self.assertTrue(self.sync(site, now=NOW + 8 * 86400)['ok'])
        self.assertIn('/content/show/21745-to-love-ru-trouble/', site.calls)

    def test_lists_not_followed_when_the_sitemap_names_enough(self):
        old = dailyme.SITEMAP_ENOUGH
        dailyme.SITEMAP_ENOUGH = 2
        try:
            self.assertTrue(self.sync()['ok'])
        finally:
            dailyme.SITEMAP_ENOUGH = old
        self.assertNotIn('/content/kategorie/familienfilme', self.site.calls)
        self.assertIn('/content/theme/family-kids', self.site.calls)

    def test_interrupted_run_keeps_what_was_read_and_resumes(self):
        class Stop(Exception):
            pass
        site = Site({'/content/show/23047-the-good-girl/': Stop()})
        old = dailyme.FLUSH_EVERY
        dailyme.FLUSH_EVERY = 1
        try:
            crawl = dailyme.Crawl(site, 0, now=NOW)
            written = []
            crawl.sink = written.extend
            crawl.robots(); crawl.sitemaps(); crawl.collect()
            crawl.read_shows({})
        finally:
            dailyme.FLUSH_EVERY = old
        self.assertTrue(written)                                       # rows were handed out while reading
        self.assertGreaterEqual(len({r['id'] for r in written}), 5)
        # a second run skips programmes read within the week and reads the rest
        self.assertTrue(self.sync()['ok'])
        later = Site()
        result = self.sync(later, now=NOW + 60)
        self.assertTrue(result['ok'])
        self.assertFalse([c for c in later.calls if c.startswith('/content/show/')])

    def test_robots_disallowing_everything(self):
        result = self.sync(Site(robots='User-agent: *\nDisallow: /\n'))
        self.assertFalse(result['ok'])
        self.assertIn('robots.txt', result['error'])
        self.assertEqual(self.site.calls, ['/robots.txt'])

    def test_javascript_only(self):
        pages = {p: STUB for p in ('/', '/content/theme/filme', '/content/theme/family-kids', '/content/channel/anime-serien')}
        pages.update({'/fast/video-sitemap.xml': None, '/fast/inhalte-sitemap.xml': None})
        result = self.sync(Site(pages))
        self.assertFalse(result['ok'])
        self.assertIn('JavaScript', result['error'])

    def test_network_failure(self):
        result = self.sync(Site({'/robots.txt': urllib.error.URLError('down')}))
        self.assertFalse(result['ok'])
        self.assertIn('nicht erreichbar', result['error'])
        self.assertEqual(dailyme.state(self.root)['last_result'], 'failed')

    def test_never_a_player_source(self):
        self.assertTrue(self.sync()['ok'])
        with self.assertRaises(ValueError) as ctx:
            dailyme.play_source(self.root, 'm.23013')
        self.assertIn('Bei dailyme ansehen', str(ctx.exception))
        with self.assertRaises(ValueError):
            streaming.resolve(None, root=self.root, dailyme='e.3664896')
        with self.assertRaises(ValueError):
            dailyme.item(self.root, '../x')


class WiringTests(unittest.TestCase):
    def test_wiring(self):
        self.assertIn('dailyme', platform_registry.BY_KEY)
        self.assertIsNone(platform_registry.BY_KEY['dailyme'].offline)
        self.assertIn('dailyme', portal_title.PROVIDER_PLAYER_ONLY)
        self.assertIn('dailyme', unified_index.SOURCES)
        self.assertEqual(dailyme_enrichment.SPEC.items, 'dailyme_items')
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for name in ('build_macos.py', 'qpkg-files.txt'):
            self.assertIn('dailyme_enrichment.py', (root / name).read_text('utf-8'))
        html = (root / 'web' / 'index.html').read_text('utf-8')
        for needle in ('data-platform="dailyme"', 'id="dailyme-items"', 'src="/dailyme.js"', 'data-catalog-source="dailyme"'):
            self.assertIn(needle, html)
        self.assertIn("'/dailyme.js'", (root / 'server.py').read_text('utf-8'))


if __name__ == '__main__':
    unittest.main()


SAMPLES = __import__('pathlib').Path('/mnt/project-files/dailyme_samples.zip')


@unittest.skipUnless(SAMPLES.exists(), 'Mitschnitte vom Mac fehlen')
class RecordedAnswers(unittest.TestCase):
    """Answers recorded on Björn's Mac on 20.11.2026 with the app's user agent (dailyme_samples.zip)."""

    @classmethod
    def setUpClass(cls):
        import zipfile
        with zipfile.ZipFile(SAMPLES) as archive:
            cls.files = {name.rsplit('/', 1)[-1]: archive.read(name).decode('utf-8', 'replace')
                         for name in archive.namelist() if not name.endswith('/')}

    def test_robots_and_sitemaps(self):
        rules = dailyme.robots_rules(self.files['01_robots.txt'])
        self.assertFalse(dailyme.robots_allows(rules, '/content/player/19357-x/3567462-y'))
        self.assertTrue(dailyme.robots_allows(rules, '/content/show/24275-ploetzlich-vater/'))
        self.assertEqual(dailyme.sitemap_entries(self.files['02_sitemap_inhalte-sitemap.xml']), ('index', ['/fast/inhalte-sitemap-1.xml']))
        kind, entries = dailyme.sitemap_entries(self.files['05_inhalte-sitemap-1.xml'])
        shows = {dailyme.SHOW_PATH.fullmatch(e['path']).group(1) for e in entries if dailyme.SHOW_PATH.fullmatch(e['path'])}
        episodes = [e for e in entries if dailyme.EPISODE_PATH.fullmatch(e['path'])]
        self.assertGreater(len(shows), 1000)
        self.assertGreater(len(episodes), 4000)
        self.assertEqual(dailyme.sitemap_entries(self.files['04_sitemap_video-sitemap.xml'])[1], [])   # news clips only

    def test_start_page(self):
        shows, lists = dailyme.list_page(self.files['06_start.html'])
        self.assertGreater(len(shows), 100)
        self.assertIn('/content/theme/filme', lists + list(dailyme.START_LISTS))
        titled = [t for t in shows.values() if t['title']]
        self.assertGreater(len(titled), 0.9 * len(shows))

    def test_film(self):
        facts, episodes, stub = dailyme.show_page(self.files['07_sendung_ploetzlich-vater.html'], '24275', 'ploetzlich-vater')
        self.assertFalse(stub)
        self.assertEqual((facts['type'], facts['title'], facts['year'], facts['fsk']), ('movie', 'Plötzlich Vater', 2013, 6))
        self.assertEqual(facts['genres'], ['Comedy', 'Drama'])
        self.assertIn('Fabella', facts['crumbs'])
        self.assertGreater(facts['duration'], 3600)
        self.assertEqual(episodes, [])

    def test_series(self):
        facts, episodes, stub = dailyme.show_page(self.files['08_sendung_verbotene-liebe.html'], '20410',
                                                  'verbotene-liebe-folge-401-bis-500')
        self.assertEqual((facts['type'], facts['title']), ('series', 'Verbotene Liebe (Folge 401 bis 500)'))
        self.assertEqual(len(episodes), 100)
        numbers = sorted(e['episode'] for e in episodes)
        self.assertEqual((numbers[0], numbers[-1]), (401, 500))
        self.assertTrue(all(e['duration'] and 60 < e['duration'] < 3600 for e in episodes))
        self.assertFalse([g for g in facts['genres'] if g.upper() in ('NEWS', 'KIDS', 'AGB', 'IMPRESSUM')])
