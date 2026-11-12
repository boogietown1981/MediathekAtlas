"""0.5.60: stored platform views, subtitle duplicates, quiet title pages, visible daily refresh."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import portal_snapshot  # noqa: E402
import unified_index  # noqa: E402


def offer(source, title, year=None, **item):
    return {'source': source, 'title': title, 'year': year, 'item': item}


def titles(entries):
    return [(e['title'], sorted(e['sources'])) for e in entries]


class SubtitleMergeTests(unittest.TestCase):
    """Björn (12.11.2026): "Ab ins Meer" (YouTube) next to "Ab ins Meer: Auf der Suche …" (Netzkino)."""

    LONG = 'Ab ins Meer: Auf der Suche nach der verlorenen Perle'

    def test_upload_title_is_compared_with_its_full_original_title(self):
        raw = 'Ab ins Meer - Auf der Suche nach der verlorenen Perle (Ganzer Film Deutsch)'
        for order in (0, 1):
            offers = [offer('youtube', 'Ab ins Meer', 2021, raw_title=raw), offer('netzkino', self.LONG, 2012)]
            entries = unified_index.merge(offers[::-1] if order else offers)
            self.assertEqual(titles(entries), [(self.LONG, ['netzkino', 'youtube'])])

    def test_short_and_long_title_join_with_the_same_reference(self):
        entries = unified_index.merge([
            offer('pluto', 'Ab ins Meer', 2012, reference={'provider': 'IMDb Offline', 'id': 'tt1'}),
            offer('netzkino', self.LONG, 2013, imdb_id='tt1')])
        self.assertEqual(len(entries), 1)

    def test_short_and_long_title_join_with_the_same_running_time(self):
        entries = unified_index.merge([offer('pluto', 'Ab ins Meer', 2012, duration=5000),
                                       offer('netzkino', self.LONG, 2012, duration=5090)])
        self.assertEqual(len(entries), 1)

    def test_without_proof_they_stay_apart(self):
        self.assertEqual(len(unified_index.merge([offer('youtube', 'Ab ins Meer', 2021), offer('netzkino', self.LONG, 2012)])), 2)
        self.assertEqual(len(unified_index.merge([offer('pluto', 'Alien', 1979, duration=7020),
                                                  offer('netzkino', 'Alien: Covenant', 2017, duration=7320)])), 2)
        # same database, different works
        self.assertEqual(len(unified_index.merge([
            offer('pluto', 'Ab ins Meer', 2012, duration=5000, reference={'provider': 'TMDB', 'id': '5'}),
            offer('netzkino', self.LONG, 2012, duration=5000, reference={'provider': 'TMDB', 'id': '6'})])), 2)
        # short films: running time proves nothing (0.5.63: the year of an upload does not either)
        self.assertEqual(len(unified_index.merge([offer('youtube', 'Ab ins Meer', 2012, duration=600),
                                                  offer('netzkino', self.LONG, 2012, duration=600)])), 2)

    def test_series_are_not_joined_by_subtitle(self):
        offers = [offer('pluto', 'Star Trek', 1966, duration=3000), offer('netzkino', 'Star Trek: Voyager', 1966, duration=3000)]
        self.assertEqual(len(unified_index.merge(offers, subtitles=False)), 2)
        self.assertIn("subtitles=view == 'movies'", (ROOT / 'unified_index.py').read_text(encoding='utf-8'))

    def test_earlier_rules_still_hold(self):
        entries = unified_index.merge([offer('youtube', '#Roxy (ROMANTISCHE KOMÖDIE mit …', 2020), offer('netzkino', '#Roxy', 2018),
                                       offer('pluto', '#Roxy', 2018), offer('pluto', '#Roxy', 2018), offer('rakuten', '#Roxy', 1990)])
        self.assertEqual(sorted(len(e['offers']) for e in entries), [1, 1, 3])
        self.assertEqual(len(unified_index.merge([offer('netzkino', 'A'), offer('pluto', 'A')], enabled=False)), 2)


class SnapshotTests(unittest.TestCase):
    """Björn (12.11.2026): after a scan the platform view can stay stored until the next scan."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        portal_snapshot.configure(Path(self.dir.name) / 'snapshots')
        self.ttl = portal_snapshot.TTL
        self.calls = 0
        self.rows = [{'id': 'a%03d' % i, 'title': 'Film %03d' % i} for i in range(130)]

    def tearDown(self):
        portal_snapshot.TTL = self.ttl
        portal_snapshot.configure(None)
        self.dir.cleanup()

    def loader(self):
        self.calls += 1
        return {'items': list(self.rows), 'total': len(self.rows), 'offset': 0, 'view': 'movies', 'genre_counts': [{'genre': 'Drama', 'n': 3}]}

    def wait_calls(self, n):
        deadline = time.time() + 5
        while time.time() < deadline and self.calls < n:
            time.sleep(0.02)
        time.sleep(0.05)

    def test_pages_come_from_one_stored_list(self):
        first = portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', limit=48)
        second = portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', offset=96, limit=48)
        self.assertEqual((len(first['items']), first['total'], first['offset']), (48, 130, 0))
        self.assertEqual([r['id'] for r in second['items']][:1], ['a096'])
        self.assertEqual(len(second['items']), 34)
        self.assertEqual(second['genre_counts'], [{'genre': 'Drama', 'n': 3}])
        self.assertEqual(self.calls, 1)
        self.assertEqual(len(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', limit='all')['items']), 130)
        capped = portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', limit='9999', offset='x')
        self.assertEqual((len(capped['items']), capped['offset']), (130, 0))
        self.assertEqual(len(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', limit='nix')['items']), 60)

    def test_view_survives_a_restart_and_is_renewed_in_the_background(self):
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')
        self.assertTrue((Path(self.dir.name) / 'snapshots' / 'pluto-movies-title.json').exists())
        portal_snapshot.configure(Path(self.dir.name) / 'snapshots')      # restart
        self.rows.append({'id': 'new', 'title': 'Neu'})
        gate = threading.Event()
        real = self.loader

        def slow():
            gate.wait(5)
            return real()
        shown = portal_snapshot.page('pluto', 'movies', slow, stamp='1')
        self.assertEqual(shown['total'], 130)                               # at once, from the file
        gate.set()
        self.wait_calls(2)
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')['total'], 131)

    def test_filtered_views_stay_in_memory_only(self):
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', query='abc')
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', genre='Drama')
        self.assertFalse((Path(self.dir.name) / 'snapshots').exists())
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1', query='ABC ')
        self.assertEqual(self.calls, 2)

    def test_new_catalogue_run_and_user_change_rebuild_before_showing(self):
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')
        self.rows.append({'id': 'new', 'title': 'Neu'})
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')['total'], 130)
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='2')['total'], 131)
        self.rows.append({'id': 'new2', 'title': 'Neu 2'})
        portal_snapshot.invalidate('pluto')
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='2')['total'], 132)
        portal_snapshot.invalidate('rakuten')                               # another platform: no rebuild
        calls = self.calls
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='2')
        self.assertEqual(self.calls, calls)

    def test_busy_database_shows_the_stored_view_and_last_status(self):
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')

        def locked():
            raise OSError('database is locked')
        self.assertEqual(portal_snapshot.page('pluto', 'movies', locked, stamp='2')['total'], 130)
        with self.assertRaises(OSError):
            portal_snapshot.page('rakuten', 'movies', locked, stamp='1')    # nothing stored: the error is real
        with self.assertRaises(OSError):
            portal_snapshot.status('pluto', locked)
        self.assertEqual(portal_snapshot.status('pluto', lambda: {'auto': True}), {'auto': True})
        self.assertEqual(portal_snapshot.status('pluto', locked), {'auto': True})

    def test_outdated_view_is_served_while_it_is_renewed(self):
        portal_snapshot.TTL = 0.0
        portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')
        self.rows.append({'id': 'new', 'title': 'Neu'})
        time.sleep(0.01)
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')['total'], 130)
        self.wait_calls(2)
        portal_snapshot.TTL = 60.0
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')['total'], 131)

    def test_broken_file_is_ignored(self):
        folder = Path(self.dir.name) / 'snapshots'
        folder.mkdir()
        (folder / 'pluto-movies-title.json').write_text('{"version":1,"key":["x"],"data":{}}', encoding='utf-8')
        self.assertEqual(portal_snapshot.page('pluto', 'movies', self.loader, stamp='1')['total'], 130)
        self.assertEqual(json.loads((folder / 'pluto-movies-title.json').read_text(encoding='utf-8'))['key'][0], 'pluto')


class InterfaceTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_platform_routes_use_the_stored_views(self):
        server = self.read('server.py')
        for name in ('pluto', 'justwatch', 'rakuten', 'youtube'):
            self.assertIn("portal_page('%s',%s,q)" % (name, name), server)
        self.assertIn("portal_snapshot.page('netzkino',view,", server)
        self.assertIn('modules=_UNIFIED_SOURCES', server)
        self.assertIn("portal_snapshot.invalidate(source)", server)
        self.assertIn("'portal_snapshot.py'", self.read('build_macos.py'))

    def test_daily_refresh_switch_is_not_undone_and_is_visible(self):
        panel, netzkino, admin = self.read('web/portal_panel.js'), self.read('web/netzkino.js'), self.read('web/admin.js')
        self.assertIn("if (Date.now() > autoHold) $(P + '-auto').checked = !!st.auto;", panel)
        self.assertIn('box.checked = !wanted', panel)
        self.assertIn("if (Date.now() > autoHold) $('netzkino-auto').checked", netzkino)
        self.assertIn("'Automatische Aktualisierung alle 24 Stunden: '", admin)
        self.assertIn('section.prepend(brief)', admin)

    def test_title_pages_do_not_show_verification_wording(self):
        portal, title, app = self.read('web/portal_title.js'), self.read('web/titleview.js'), self.read('web/app.js')
        self.assertNotIn("'passt'", portal)
        self.assertNotIn('Werkzuordnung · IMDb / TVDB', portal)
        self.assertNotIn("['Zuordnung', REF[", portal)
        self.assertIn('Technische Angaben · Abgleich und Anbieterdaten', portal)
        self.assertIn('referenceSection(m, expert)', portal)
        self.assertIn('providerSection(m, expert)', portal)
        self.assertIn("p === 'IMDb Offline' ? 'IMDb'", portal)
        # one offline button: the real control in the header, the section only lists copies
        self.assertIn('const save = window.AtlasOffline?.control(m.source, m.id, m.title', portal)
        self.assertNotIn('sec.append(note, add, list)', portal)
        self.assertIn('sec.hidden = !jobs.length', portal)
        self.assertIn("function providerLabel(p){return p==='IMDb Offline'?'IMDb'", title)
        self.assertNotIn("['Zuordnung',stateLabel(s.state)+(s.provider", title)
        self.assertNotIn("['IMDb Offline',imdbReady", app)


if __name__ == '__main__':
    unittest.main()
