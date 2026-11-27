"""0.6.145 (Pro-Diagnose 26.11.2026, 0.6.139): filmfriend verlor nach einem einzigen Seitenfehler 37 % des Katalogs
(107 statt 173 Seiten, 2.275 statt 3.629 Filme) und wertete den Lauf trotzdem als vollständig. Dazu: die
Senderstatistik in der Diagnose war 37 h alt."""
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT));sys.path.insert(0, str(ROOT / 'tests'))
import filmfriend  # noqa: E402
import test_v0652_filmfriend as base  # noqa: E402

NOW = base.NOW


class Flaky(base.FakeFilmfriend):
    """Beantwortet die zweite Seite der Suche „Alle“ ``fails``-mal mit HTTP 502."""

    def __init__(self, fails):
        super().__init__();self.fails = fails

    def __call__(self, url, headers):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if url.split('?')[0].endswith('/search') and q.get('skip') == ['24'] and q.get('categoryIds') != [base.CAT_KIDS] and self.fails:
            self.fails -= 1
            raise urllib.error.HTTPError(url, 502, 'Bad Gateway', {}, None)
        return super().__call__(url, headers)


class FilmfriendPages(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def sync(self, fake, now=NOW):
        return filmfriend.sync(self.root, opener=fake, now=now)

    def test_failed_page_is_asked_again_and_the_run_stays_complete(self):
        result = self.sync(Flaky(1))
        self.assertFalse(result['partial'])
        self.assertEqual(filmfriend.listing(self.root, limit=100)['total'], 26)

    def test_page_missing_after_retry_makes_the_run_partial_and_keeps_old_titles(self):
        self.assertFalse(self.sync(base.FakeFilmfriend())['partial'])
        result = self.sync(Flaky(2), now=NOW + 86400)
        self.assertTrue(result['partial'])
        st = filmfriend.state(self.root)
        self.assertEqual(st['last_result'], 'partial')
        self.assertEqual(filmfriend.listing(self.root, limit=100)['total'], 26)      # alte Titel bleiben sichtbar

    def test_search_goes_on_after_a_missing_page(self):
        crawl = filmfriend.Crawl(Flaky(2), 0)
        with mock.patch.object(base.FakeFilmfriend, '__call__', base.FakeFilmfriend.__call__):
            crawl.collect()
        self.assertEqual(crawl.missed_pages, 1)
        # Seite 1 (24) und die Kinder-Suche sind da; Seite 3 gibt es nicht – kein Abbruch der weiteren Suchen
        self.assertGreaterEqual(len(crawl.entries), 24)

    def test_clearly_fewer_titles_is_partial_until_three_clean_runs_agree(self):
        self.sync(base.FakeFilmfriend())
        saved = list(base.ALL)
        try:
            del base.ALL[10:]
            results = [self.sync(base.FakeFilmfriend(), now=NOW + 86400 * d)['partial'] for d in (1, 2, 3)]
        finally:
            base.ALL[:] = saved
        self.assertEqual(results, [True, True, False])


class RecognitionExport(unittest.TestCase):
    def test_waits_for_a_fresh_count_when_only_an_old_one_is_there(self):
        import server
        old = {'channels': [{'channel': 'ARD'}], 'loading': True, 'computed_at': time.time() - 37 * 3600}
        fresh = {'channels': [{'channel': 'ARD'}], 'loading': False, 'computed_at': time.time()}
        answers = [old, old, fresh]
        with mock.patch.object(server, 'recognition', side_effect=lambda: answers.pop(0) if len(answers) > 1 else answers[0]), \
             mock.patch.object(server.time, 'sleep'):
            result = server.recognition_for_export(5)
        self.assertFalse(result['loading']);self.assertLess(result['age_hours'], 1)


if __name__ == '__main__':
    unittest.main()
