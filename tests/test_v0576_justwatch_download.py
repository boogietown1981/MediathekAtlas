"""0.5.76: the live answer of JustWatch decides between "download now" and "tonight", not the stored
catalogue flag or a fixed hour (Björn, 12.11.2026: youth-protection films played at once, the
download did not work). The signed address is asked again at every start, never remembered."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import justwatch  # noqa: E402
import justwatch_downloads  # noqa: E402

COLS = 'id,kind,title,path,series_id,season,episode,year,duration,rating,genre,summary,poster,imdb_id,imdb_score,imdb_votes,playable,web_url,seen,updated,night'


class LiveAnswerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        db = justwatch._connect(self.root)
        with db:
            for item_id, playable, night in (('tm1', 0, 1), ('tm2', 1, 1), ('tm3', 1, 0), ('tm4', 0, 0)):
                db.execute('INSERT INTO justwatch_items(%s) VALUES(%s)' % (COLS, ','.join('?' * 21)),
                           (item_id, 'movie', 'Film ' + item_id, '/de/Film/' + item_id, '', None, None, 2009, 7200, '16', 'Drama', '', '', '',
                            None, None, playable, 'https://www.justwatch.com/de/Film/x', 1, 1, night))
        db.close()

    def tearDown(self):
        self.tmp.cleanup()
        justwatch._SOURCES.clear()

    def job(self, item_id, live):
        return justwatch_downloads.build_job(self.root, self.root / 'media', item_id, 1000, released=lambda row: live)

    def test_night_title_released_right_now_starts_at_once(self):
        # catalogue read by day (playable 0), clicked at 23:30: JustWatch releases it already
        job = self.job('tm1', True)
        self.assertNotIn('not_before', job); self.assertNotIn('night', job)

    def test_night_title_not_released_waits_even_with_an_old_flag(self):
        for item_id in ('tm1', 'tm2'):   # tm2: catalogue read inside the window, clicked by day
            job = self.job(item_id, False)
            self.assertTrue(job['night']); self.assertGreaterEqual(job['not_before'], 1000)

    def test_titles_without_window_are_not_asked(self):
        asked = []
        job = justwatch_downloads.build_job(self.root, self.root / 'media', 'tm3', 1000, released=lambda row: asked.append(1) or False)
        self.assertNotIn('night', job)
        with self.assertRaisesRegex(ValueError, 'kopiergeschützten Player'):
            self.job('tm4', True)

    def test_released_now_asks_justwatch_and_never_raises(self):
        offer = {'standardWebURL': 'https://www.justwatch.com/de/Film/x', 'package': {'shortName': 'jwt'},
                 'streamUrlExternalPlayer': 'https://apis.justwatch.com/jwtv/manifest/external/abcdefghij.SiGnAtUrE_123.m3u8'}
        row = justwatch.item(self.root, 'tm1')['item']
        yes = lambda q, v: {'data': {'urlV2': {'node': {'watchNowOffer': offer, 'offers': []}}}}
        no = lambda q, v: {'data': {'urlV2': {'node': {'watchNowOffer': None, 'offers': []}}}}

        def down(q, v):
            raise OSError('offline')
        self.assertFalse(justwatch.released_now(self.root, row, post=no, now=10))
        self.assertFalse(justwatch.released_now(self.root, row, post=down, now=10))
        self.assertTrue(justwatch.released_now(self.root, row, post=yes, now=10))

    def test_worker_asks_before_it_postpones(self):
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn('later>time.time() and not justwatch_downloads.released(j)', server)
        self.assertFalse(justwatch_downloads.released({'source': {}}))

    def test_download_never_uses_a_remembered_address(self):
        justwatch._SOURCES['tm1'] = (10 ** 12, 'https://apis.justwatch.com/jwtv/manifest/alt/alt')
        seen = {}
        original = justwatch.play_source
        justwatch.play_source = lambda root, item_id: seen.update(cached='tm1' in justwatch._SOURCES) or {'url': 'u'}
        try:
            justwatch_downloads.resolve({'_justwatch_home': str(self.root), '_justwatch_id': 'tm1'})
        finally:
            justwatch.play_source = original
        self.assertEqual(seen, {'cached': False})


if __name__ == '__main__':
    unittest.main()
