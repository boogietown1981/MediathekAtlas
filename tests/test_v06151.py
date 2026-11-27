"""0.6.151 (Björn 26.11.2026: „erkennung bzw. einbindung von lokalen Filmarchiven auf Shares … wenn dort schon NFO-Dateien
sind, können diese gleich genutzt werden, wenn noch keine sind, werden sie eben gescannt und zugeordnet“).

Nur lesend auf der Freigabe, NFO zuerst, sonst Datei-/Ordnername; inkrementell; nicht erreichbare Freigabe = offline, nie
gelöscht; Wiedergabe nur innerhalb der eingetragenen Ordner."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lokal  # noqa: E402
import lokal_enrichment  # noqa: E402
import local_titles  # noqa: E402
import streaming  # noqa: E402
import unified_index  # noqa: E402
sys.path.insert(0, str(ROOT / 'tests'))
import test_v0555_dashboard_admin as base  # noqa: E402

MOVIE_NFO = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie><title>Das Boot</title><originaltitle>Das Boot</originaltitle><year>1981</year><plot>U-96 im Atlantik.</plot>
<genre>Drama</genre><genre>Krieg</genre><uniqueid type="imdb" default="true">tt0082096</uniqueid><uniqueid type="tmdb">387</uniqueid>
<thumb aspect="poster">https://img.example.org/boot.jpg</thumb><thumb aspect="poster">http://unsicher.example.org/x.jpg</thumb>
<fileinfo><streamdetails><video><durationinseconds>8940</durationinseconds></video></streamdetails></fileinfo></movie>'''
SHOW_NFO = '<tvshow><title>Babylon Berlin</title><year>2017</year><genre>Krimi</genre><uniqueid type="imdb">tt4378376</uniqueid></tvshow>'
EP_NFO = '<episodedetails><title>Folge eins</title><season>1</season><episode>1</episode><plot>Berlin 1929.</plot></episodedetails>'


class Names(unittest.TestCase):
    def test_movie_names(self):
        self.assertEqual(lokal.parse_name('/a/Das.Boot.1981.German.1080p.BluRay.x264.mkv'),
                         {'kind': 'movie', 'title': 'Das Boot', 'year': 1981})
        self.assertEqual(lokal.parse_name('/a/Der Name der Rose (1986)/movie.mkv'),
                         {'kind': 'movie', 'title': 'Der Name der Rose', 'year': 1986})
        self.assertEqual(lokal.parse_name('/a/2001 Odyssee im Weltraum.mkv')['title'], '2001 Odyssee im Weltraum')
        self.assertEqual(lokal.parse_name('/a/Lola rennt.mp4'), {'kind': 'movie', 'title': 'Lola rennt', 'year': None})

    def test_episode_names(self):
        ep = lokal.parse_name('/s/Babylon Berlin/Staffel 2/Babylon.Berlin.S02E03.German.720p.mkv')
        self.assertEqual((ep['kind'], ep['show'], ep['season'], ep['episode']), ('episode', 'Babylon Berlin', 2, 3))
        ep = lokal.parse_name('/s/Tatort/Season 01/S01E05 - Taxi nach Leipzig.mkv')
        self.assertEqual((ep['show'], ep['season'], ep['episode'], ep['title']), ('Tatort', 1, 5, 'Taxi nach Leipzig'))
        self.assertEqual(lokal.parse_name('/s/Dark (2017)/Dark 1x02.mkv')['show'], 'Dark')


class Nfo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, text):
        p = self.dir / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(text, encoding='utf-8');return p

    def test_movie_nfo_fields(self):
        info = lokal.read_nfo(self.write('boot.nfo', MOVIE_NFO))
        self.assertEqual((info['title'], info['year'], info['imdb_id'], info['tmdb_id'], info['seconds']),
                         ('Das Boot', 1981, 'tt0082096', '387', 8940))
        self.assertEqual(info['genres'], ['Drama', 'Krieg'])
        self.assertEqual(info['poster'], 'https://img.example.org/boot.jpg')     # nur https

    def test_url_only_and_hostile_files(self):
        self.assertEqual(lokal.read_nfo(self.write('a.nfo', 'https://www.imdb.com/title/tt0082096/\n')), {'imdb_id': 'tt0082096'})
        evil = '<?xml version="1.0"?><!DOCTYPE m [<!ENTITY x SYSTEM "file:///etc/passwd">]><movie><title>&x;</title></movie>'
        self.assertEqual(lokal.read_nfo(self.write('b.nfo', evil)), {})            # keine Entitäten auflösen
        self.assertEqual(lokal.read_nfo(self.write('c.nfo', '<movie><title>kaputt')), {})
        self.assertEqual(lokal.read_nfo(self.dir / 'fehlt.nfo'), {})

    def test_describe_prefers_nfo_then_name(self):
        video = self.dir / 'Boot' / 'U96.1980.mkv';video.parent.mkdir();video.write_bytes(b'')
        self.write('Boot/movie.nfo', MOVIE_NFO)
        info = lokal.describe(str(video), True)
        self.assertEqual((info['title'], info['year'], info['imdb_id'], info['nfo']), ('Das Boot', 1981, 'tt0082096', True))
        # movie.nfo gilt nur, wenn das Video allein im Ordner liegt
        self.assertEqual(lokal.describe(str(video), False)['title'], 'U96')
        ep = self.dir / 'Babylon Berlin' / 'Staffel 1' / 'Babylon.Berlin.S01E01.mkv';ep.parent.mkdir(parents=True);ep.write_bytes(b'')
        self.write('Babylon Berlin/tvshow.nfo', SHOW_NFO);self.write('Babylon Berlin/Staffel 1/Babylon.Berlin.S01E01.nfo', EP_NFO)
        info = lokal.describe(str(ep), False)
        self.assertEqual((info['kind'], info['show'], info['show_year'], info['show_imdb'], info['title'], info['episode']),
                         ('episode', 'Babylon Berlin', 2017, 'tt4378376', 'Folge eins', 1))


class Archive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'data';self.root.mkdir()
        self.share = Path(tmp.name) / 'share';self.share.mkdir()
        patch = mock.patch.object(lokal, 'MIN_SIZE', 4);patch.start();self.addCleanup(patch.stop)
        self.addCleanup(local_titles.invalidate)

    def video(self, rel, data=b'video'):
        p = self.share / rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(data);return p

    def nfo(self, rel, text):
        p = self.share / rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(text, encoding='utf-8')

    def fill(self):
        self.video('Filme/Das Boot (1981)/Das.Boot.1981.mkv');self.nfo('Filme/Das Boot (1981)/Das.Boot.1981.nfo', MOVIE_NFO)
        self.video('Filme/Lola.rennt.1998.1080p.mp4')
        self.video('Filme/Lola.rennt.1998-sample.mp4')                       # Beispiel: überspringen
        self.video('Filme/klein.mkv', b'x')                                    # zu klein
        self.video('Filme/.Trash/Alt.2001.mkv');self.video('Filme/@eaDir/x.2001.mkv')
        self.video('Serien/Babylon Berlin/Staffel 1/Babylon.Berlin.S01E01.mkv')
        self.video('Serien/Babylon Berlin/Staffel 1/Babylon.Berlin.S01E02.mkv')
        self.nfo('Serien/Babylon Berlin/tvshow.nfo', SHOW_NFO)
        self.nfo('Serien/Babylon Berlin/Staffel 1/Babylon.Berlin.S01E01.nfo', EP_NFO)
        lokal.set_dirs(str(self.root), str(self.share))

    def test_dirs_need_absolute_paths_and_no_drive_root(self):
        with self.assertRaises(ValueError):
            lokal.clean_dirs('Filme')
        with self.assertRaises(ValueError):
            lokal.clean_dirs('/')
        self.assertEqual(lokal.clean_dirs('/Volumes/Filme\n\n/Volumes/Filme\n/Volumes/Serien'), ['/Volumes/Filme', '/Volumes/Serien'])

    def test_scan_reads_nfo_names_and_series(self):
        self.fill()
        summary = lokal.scan(str(self.root), now=100.0)
        self.assertEqual((summary[0]['files'], summary[0]['new'], summary[0]['reachable']), (4, 4, True))
        movies = lokal.listing(str(self.root), 'movies')['items']
        self.assertEqual([(m['title'], m['year']) for m in movies], [('Das Boot', 1981), ('Lola rennt', 1998)])
        boot = movies[0]
        self.assertEqual((boot['imdb_id'], boot['nfo'], boot['duration'], boot['poster']), ('tt0082096', 1, 8940, 'https://img.example.org/boot.jpg'))
        self.assertTrue(boot['local']);self.assertEqual(boot['playable'], 1);self.assertNotIn('path', boot)
        self.assertIn('Drama', boot['categories'])                         # Genres der NFO mit IMDb-Nummer zählen
        self.assertNotIn('Drama', movies[1].get('categories') or [])
        series = lokal.listing(str(self.root), 'series')['items']
        self.assertEqual([(s['title'], s['year'], s['episode_count'], s['imdb_id']) for s in series], [('Babylon Berlin', 2017, 2, 'tt4378376')])
        eps = lokal.episodes(str(self.root), series[0]['id'])['items']
        self.assertEqual([(e['season'], e['episode'], e['title']) for e in eps], [(1, 1, 'Folge eins'), (1, 2, 'Folge 2')])
        st = lokal.state(str(self.root))
        self.assertEqual((st['movies'], st['series'], st['episodes'], st['with_nfo'], st['offline']), (2, 1, 2, 3, 0))   # Folge 2: tvshow.nfo
        self.assertEqual(st['last_result'], 'ok');self.assertGreater(st['next_attempt'], 100.0)
        self.assertFalse(lokal.should_sync(str(self.root), now=101.0))

    def test_incremental_scan_reads_only_changes(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        seen = []
        real = lokal.describe

        def spy(path, single):
            seen.append(Path(path).name);return real(path, single)
        summary = lokal.scan(str(self.root), now=200.0, describe_fn=spy)
        self.assertEqual(seen, []);self.assertEqual(summary[0]['new'] + summary[0]['changed'], 0)
        lola = self.share / 'Filme/Lola.rennt.1998.1080p.mp4';lola.write_bytes(b'neue fassung');os.utime(lola, (5000, 5000))
        self.video('Filme/Victoria.2015.mkv')
        summary = lokal.scan(str(self.root), now=300.0, describe_fn=spy)
        self.assertEqual(sorted(seen), ['Lola.rennt.1998.1080p.mp4', 'Victoria.2015.mkv'])
        self.assertEqual((summary[0]['new'], summary[0]['changed']), (1, 1))

    def test_removed_file_is_gone_offline_share_is_kept(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        (self.share / 'Filme/Lola.rennt.1998.1080p.mp4').unlink()
        summary = lokal.scan(str(self.root), now=200.0)
        self.assertEqual(summary[0]['gone'], 1)
        self.assertEqual([m['title'] for m in lokal.listing(str(self.root), 'movies')['items']], ['Das Boot'])
        # Freigabe abgemeldet: Ordner fehlt → nichts löschen, nur offline
        moved = self.share.with_name('weg');self.share.rename(moved)
        summary = lokal.scan(str(self.root), now=300.0)
        self.assertFalse(summary[0]['reachable'])
        items = lokal.listing(str(self.root), 'movies')['items']
        self.assertEqual([(m['title'], m['offline_share'], m['playable']) for m in items], [('Das Boot', True, 0)])
        self.assertEqual(lokal.state(str(self.root))['offline'], 3)
        with self.assertRaisesRegex(ValueError, 'nicht erreichbar'):
            lokal.play_source(str(self.root), items[0]['id'])
        moved.rename(self.share)
        lokal.scan(str(self.root), now=400.0)
        self.assertEqual(lokal.listing(str(self.root), 'movies')['items'][0]['playable'], 1)

    def test_empty_mount_point_counts_as_offline(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        hidden = self.share.with_name('versteckt');self.share.rename(hidden);self.share.mkdir()   # leerer Einhängepunkt
        summary = lokal.scan(str(self.root), now=200.0)
        self.assertFalse(summary[0]['reachable']);self.assertEqual(summary[0]['gone'], 0)
        self.assertEqual(lokal.state(str(self.root))['movies'], 2)

    def test_removed_folder_drops_its_titles_but_not_files(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        lokal.set_dirs(str(self.root), '')
        self.assertEqual(lokal.listing(str(self.root), 'movies')['total'], 0)
        self.assertTrue((self.share / 'Filme/Lola.rennt.1998.1080p.mp4').exists())

    def test_play_only_inside_registered_folders(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        boot = lokal.listing(str(self.root), 'movies')['items'][0]
        src = lokal.play_source(str(self.root), boot['id'])
        self.assertEqual((src['kind'], src['provider'], src['title']), ('file', 'lokal', 'Das Boot (1981)'))
        self.assertTrue(src['path'].endswith('Das.Boot.1981.mkv'))
        self.assertEqual(streaming.resolve(None, root=str(self.root), lokal=boot['id'])['path'], src['path'])
        plan = streaming.plan(src)
        self.assertEqual(plan['origin'], 'local')
        for bad in ('../etc', 'f' + 'z' * 20, ''):
            with self.assertRaises(ValueError):
                lokal.play_source(str(self.root), bad)
        # ein Eintrag, der auf eine Datei außerhalb zeigt (z. B. manipulierte Datenbank), wird abgelehnt
        outside = self.share.parent / 'geheim.mkv';outside.write_bytes(b'video')
        db = lokal._connect(str(self.root))
        with db:
            db.execute('UPDATE lokal_items SET path=? WHERE id=?', (str(outside), boot['id']))
        db.close()
        with self.assertRaisesRegex(ValueError, 'eingetragenen'):
            lokal.play_source(str(self.root), boot['id'])
        self.assertFalse(lokal.allowed(str(self.share / '..' / 'geheim.mkv'), [str(self.share)]))

    def test_details_and_reference_check_use_nfo_imdb_number(self):
        self.fill()
        lokal.scan(str(self.root), now=100.0)
        boot = lokal.listing(str(self.root), 'movies')['items'][0]
        details = lokal.item(str(self.root), boot['id'])
        self.assertEqual(details['item']['title'], 'Das Boot');self.assertEqual(details['reference']['status'], 'unchecked')
        self.assertIn(boot['id'], lokal_enrichment.pending(str(self.root), limit=10, now=200.0))
        hits = [{'provider': 'IMDb Offline', 'reference_id': 'tt0082096', 'title': 'Das Boot', 'kind': 'movie', 'year': 1981, 'similarity': 1.0},
                {'provider': 'IMDb Offline', 'reference_id': 'tt0120000', 'title': 'Das Boot', 'kind': 'movie', 'year': 1981, 'similarity': 1.0}]
        seen = []

        def lookup(row, meta, settings):
            seen.append(meta['title']);return {'candidates': [dict(h) for h in hits], 'provider_checks': []}
        with mock.patch('reference_share.wrap', side_effect=lambda root, fn, *a, **k: fn):
            report = lokal_enrichment.enrich(str(self.root), boot['id'], {}, lookup=lookup, now=200.0)
        self.assertEqual(seen, ['Das Boot'])
        self.assertEqual(report['status'], 'candidate', report)           # ohne NFO-Nummer wäre es „review“
        self.assertEqual([r['reference_id'] for r in report['references']], ['tt0082096'])
        # ohne Treffer der Suche kommt der Titel direkt über die IMDb-Nummer aus dem Archiv
        wrapped = lokal_enrichment.nfo_lookup(lambda *a: {'candidates': []}, 'tt0082096', '', {'title': 'Das Boot'},
                                              archive=lambda tconst, row: {'provider': 'IMDb Offline', 'reference_id': tconst})
        self.assertEqual(wrapped({}, {}, {})['candidates'], [{'provider': 'IMDb Offline', 'reference_id': 'tt0082096'}])
        plain = lambda *a: {'candidates': [1]}
        self.assertIs(lokal_enrichment.nfo_lookup(plain, '', '', {}), plain)

    def test_planner_and_background_run(self):
        self.assertFalse(lokal.should_sync(str(self.root), now=1.0))                 # ohne Ordner nichts zu tun
        self.fill()
        self.assertTrue(lokal.should_sync(str(self.root), now=1.0))
        with mock.patch.object(lokal, 'scan') as scan:
            self.assertTrue(lokal.start_sync(str(self.root)))
            for _ in range(100):
                if not lokal._ACTIVE:
                    break
                import time;time.sleep(0.02)
        scan.assert_called_once()


class Catalog(base.UnifiedPageTests):
    """Im gemeinsamen Katalog: eigener Anbieter „Lokales Archiv“, gleicher Titel = eine Kachel, gilt als geladen."""
    test_merged_sorted_page = test_filters_paging_and_cache = test_removed_work_is_skipped = None

    def setUp(self):
        super().setUp();local_titles.invalidate()
        import catalog
        patch = mock.patch.object(catalog, 'LISTING_DB', None);patch.start();self.addCleanup(patch.stop)
        self.addCleanup(local_titles.invalidate)
        self.modules['lokal'] = base.Portal([{'id': 'f' + '1' * 20, 'kind': 'movie', 'title': 'Zebra', 'year': 2001},
                                             {'id': 'f' + '2' * 20, 'kind': 'movie', 'title': 'Heimkino', 'year': 2010}])

    def test_local_archive_titles_merge_and_come_first(self):
        import time, catalog
        for _ in range(100):
            catalog.invalidate_listings(drop=True);unified_index.invalidate();local_titles.invalidate()
            page = unified_index.page(self.dir.name, self.db, modules=self.modules)
            if not page['pending']:
                break
            time.sleep(0.05)
        rows = [(i['title'], bool(i.get('local')), [o['source'] for o in i['offers']]) for i in page['items']]
        self.assertEqual(rows[:2], [('Heimkino', True, ['lokal']), ('Zebra', True, ['lokal', 'mediatheken'])], rows)
        only = unified_index.page(self.dir.name, self.db, modules=self.modules, only='lokal')
        self.assertEqual({i['title'] for i in only['items']}, {'Heimkino', 'Zebra'})


class Wiring(unittest.TestCase):
    def text(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_server_routes_and_play_keys(self):
        server = self.text('server.py')
        for route in ("'/api/lokal'", "'/api/lokal-dirs'", "'/api/lokal-scan'", "'/api/lokal-enrich'"):
            self.assertIn(route, server)
        self.assertIn("'dailyme','sender','lokal')", server)
        self.assertIn("lokal=q.get('lokal',[''])[0]", server)
        self.assertIn("planner.CatalogJob('lokal',lokal)", server)
        self.assertIn("'/lokal_archive.js'", server)
        self.assertIn("'lokal.py','lokal_enrichment.py'", self.text('build_macos.py'))

    def test_ui(self):
        html = self.text('web/index.html')
        for needle in ('id="lokal-archive-panel"', 'id="lokal-archive-dirs"', 'id="lokal-archive-save"', 'id="lokal-archive-scan"',
                       'data-catalog-source="lokal"', '<script src="/lokal_archive.js"></script>'):
            self.assertIn(needle, html)
        self.assertIn("window.playLokal=function", self.text('web/player.js'))
        uc = self.text('web/unified_catalog.js')
        self.assertIn("lokal:()=>window.playLokal", uc);self.assertIn("item.source!=='lokal'", uc)
        self.assertIn("'mediatheken','lokal',", uc)
        self.assertIn("lokal: {play: () => window.playLokal", self.text('web/portal_title.js'))
        js = self.text('web/lokal_archive.js')
        self.assertIn("api('lokal-dirs',{dirs:box.value})", js);self.assertIn("api('lokal-scan',{})", js)


if __name__ == '__main__':
    unittest.main()
