"""0.6.152: Korrekturen aus der Mac-Prüfung 0.6.147 (26.11.2026, Prüfvermerk PRUEFVERMERK-06147.txt).

(a) Maus über „Mehr davon“ hielt den Countdown nicht an; (b) „Mehr davon“ zeigte die eigene Reihe (Löwenzahn);
(c) Kinderecke-Bilder: Pro „asked 1, found 0“ (Stundenlimit von der Erkennung verbraucht), KiKA-Reihen ohne Bild;
(d) erster Diagnose-Export mit altem Stand ohne Senderstatistik (Übersicht wartete 30 s bei 20 s Frist);
(e) Serienliste nach 10 min einmal 7,1 s (gealterte schnelle Liste wurde im Aufruf neu gebaut)."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import broadcaster  # noqa: E402
import catalog  # noqa: E402
import kids_catalog  # noqa: E402
import youtube  # noqa: E402
from test_v06146 import SenderPictures  # noqa: E402

ARD_ROW = {'url_website': 'https://www.ardmediathek.de/video/x/y/br/Y3JpZDovL2JyLmRlL3ZpZGVvLzEyMzQ1Njc4OQ'}


class SuggestionsUi(unittest.TestCase):
    def test_hover_holds_countdown_and_own_show_is_skipped(self):
        js = (ROOT / 'web' / 'kids.js').read_text(encoding='utf-8')
        self.assertIn("$('kids-suggest').onpointerover = hover; $('kids-suggest').onpointermove = hover;", js)
        self.assertIn("if (e.pointerType === 'mouse') hold();", js)
        self.assertIn("((x.id && x.id === show.id) || sameShow(x.title, show.title))", js)
        self.assertIn("a.startsWith(b + ' ') || b.startsWith(a + ' ')", js)


class PictureBudget(unittest.TestCase):
    def setUp(self):
        broadcaster._AUTOMATED_BUDGET.clear();broadcaster._PICTURE_DEMAND.clear();broadcaster._CACHE.clear()
        self.addCleanup(broadcaster._AUTOMATED_BUDGET.clear);self.addCleanup(broadcaster._PICTURE_DEMAND.clear)

    def test_pictures_keep_a_reserve_total_stays_120(self):
        with mock.patch.object(broadcaster, 'lookup', return_value={}):
            for _ in range(100):
                broadcaster.lookup_limited(ARD_ROW)
            broadcaster.lookup_limited(ARD_ROW, purpose='pictures')        # Kinderecke fragt: Rücklage gilt ab jetzt
            with self.assertRaises(broadcaster.BudgetExhausted):
                broadcaster.lookup_limited(ARD_ROW)                        # Erkennung: 101 > 100
            for _ in range(19):
                broadcaster.lookup_limited(ARD_ROW, purpose='pictures')
            with self.assertRaises(broadcaster.BudgetExhausted):
                broadcaster.lookup_limited(ARD_ROW, purpose='pictures')    # 120 insgesamt
        self.assertEqual(broadcaster._AUTOMATED_BUDGET['ARD Mediathek'][1], 120)

    def test_without_picture_demand_recognition_gets_all_120(self):
        with mock.patch.object(broadcaster, 'lookup', return_value={}):
            for _ in range(120):
                broadcaster.lookup_limited(ARD_ROW)
            with self.assertRaises(broadcaster.BudgetExhausted):
                broadcaster.lookup_limited(ARD_ROW)


class YoutubePictures(SenderPictures):
    test_series_without_picture_gets_the_sender_picture = test_paused_sender_stores_nothing_and_kika_only_is_counted = None
    test_without_sender_page_no_request_and_retry_after_a_week = test_same_title_across_films_and_series = None

    def seed_youtube(self, abo_titles=(), item_titles=()):
        ydb = youtube._connect(self.root)
        import youtube_abos
        youtube_abos._connect(self.root).close()
        with ydb:
            for i, title in enumerate(abo_titles):
                ydb.execute("INSERT INTO youtube_abo_videos(abo_id,video,title,poster,found) VALUES(1,?,?,?,?)",
                            ('v%010d' % i, title, 'https://i.ytimg.com/vi/v%010d/hqdefault.jpg' % i, float(i)))
            for i, title in enumerate(item_titles):
                ydb.execute("INSERT INTO youtube_items(id,kind,title,poster,seen,updated) VALUES(?,?,?,?,?,?)",
                            ('y%d' % i, 'movie', title, 'https://i.ytimg.com/vi/y%d/hqdefault.jpg' % i, float(i), 1.0))
        ydb.close()

    def test_phrase_match_only(self):
        self.seed_youtube(abo_titles=['Mein Checker-Tag – Checker Reportagen spezial', 'Checker Tobi im Zoo'],
                          item_titles=['Carolin testet Schuhe'])
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Checker Reportagen'), 'https://i.ytimg.com/vi/v0000000000/hqdefault.jpg')
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Carolin testet'), 'https://i.ytimg.com/vi/y0/hqdefault.jpg')
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Checker Can'), '')          # nur „Checker Tobi“ da
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Anna'), '')                 # zu kurz/allgemein
        self.assertEqual(kids_catalog.youtube_picture(self.root, 'Reportage'), '')            # ein Wort, < 10 Zeichen

    def test_show_without_sender_page_takes_youtube_picture_and_old_failures_retry(self):
        self.prepare(url=False)
        self.shelf()
        now = time.time()
        with self.db() as c:   # Fehlschlag aus 0.6.147 (ohne 'v'): wird trotz Wochenfrist erneut versucht
            catalog.set_state(c, kids_catalog.PICTURES_KEY, {'show:checker': {'url': '', 'at': now - 60}})
        self.seed_youtube(abo_titles=['Checker Reportagen: Wie kommt der Strom in die Steckdose?'])
        calls = []
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, now=now, lookup=calls.append), (1, 0, 1))
        self.assertEqual(calls, [])
        self.assertTrue(self.tile(self.shelf())['poster'].startswith('https://i.ytimg.com/vi/'))

    def test_budget_stop_is_reported_for_early_retry(self):
        self.prepare()
        self.shelf()

        def full(row):
            raise broadcaster.BudgetExhausted('ARD Mediathek: automatisches Stundenlimit erreicht')
        self.assertEqual(kids_catalog.fetch_missing_pictures(self.root, self.db, lookup=full), (0, 1, 0))
        self.assertTrue(kids_catalog.LAST_FETCH['stopped'])
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("STOP.wait(600 if kids_catalog.LAST_FETCH.get('stopped') else 3600)", server)


class ExportWait(unittest.TestCase):
    def test_overview_waits_less_than_the_part_budget(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("'recognition':recognition_for_export(EXPORT_RECOGNITION_WAIT)", server)
        self.assertIn('EXPORT_RECOGNITION_WAIT=15.0', server)
        self.assertIn('def _bounded_parts(parts,budget=20.0):', server)


class AgedListing(unittest.TestCase):
    def setUp(self):
        catalog.invalidate_listings(drop=True)
        patch = mock.patch.object(catalog, 'LISTING_DB', 'egal');patch.start();self.addCleanup(patch.stop)
        self.addCleanup(catalog.invalidate_listings, drop=True)
        self.key = ('w', (), 'g', 'o')

    def store(self, built):
        catalog._LISTING[self.key] = {'rows': ['alt'], 'built': built, 'busy': False, 'used': 0, 'seconds': 0.2, 'search': False}

    def test_aged_quick_listing_answers_from_memory_and_renews(self):
        self.store(time.monotonic() - catalog.LISTING_TTL - 5)
        started = threading.Event()
        with mock.patch.object(catalog, '_listing_refresh', side_effect=lambda *a, **k: started.set()), \
             mock.patch.object(catalog, '_listing_build', side_effect=AssertionError('kein Neubau im Aufruf')):
            self.assertEqual(catalog._listing_groups(None, 'w', [], 'g', 'o'), ['alt'])
            self.assertTrue(started.wait(2))

    def test_after_a_change_a_quick_listing_is_rebuilt_at_once(self):
        self.store(float('-inf'))
        with mock.patch.object(catalog, '_listing_build', return_value=(['neu'], 0.1)):
            self.assertEqual(catalog._listing_groups(None, 'w', [], 'g', 'o'), ['neu'])


if __name__ == '__main__':
    unittest.main()
