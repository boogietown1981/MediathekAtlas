"""0.6.124 (Diagnose Air 0.6.120, 23.11.2026): 3sat-Filme mit Titelzusatz blieben „prüfen“ – der 24-h-Zwischenspeicher
lieferte das alte Suchergebnis (from_cache), und das lokale IMDb-Archiv kennt nur exakte Namen („The Pledge - Das
Versprechen“, „Jussi Adler-Olsen: Erlösung“). Kinderecke vorab erst nach Heilungen und erstem Formatdurchlauf."""
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog_service  # noqa: E402
import imdb_archive  # noqa: E402
import matching  # noqa: E402
import metadata  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Archive:
    updated = 1

    def __init__(self, films):
        self.films = films   # name -> (tconst, year, runtime minutes)
        self.asked = []

    def candidates(self, row, meta):
        self.asked.append(meta['title'])
        out = []
        if meta.get('kind') == 'series':
            return out
        for name, (tconst, year, minutes) in self.films.items():
            if metadata.norm(name) == metadata.norm(meta['title']):
                agrees = abs(minutes * 60 - row['duration']) <= max(300, minutes * 6)
                out.append({**meta, 'title': meta['title'], 'kind': 'movie', 'year': year, 'provider': 'IMDb Offline',
                            'reference_id': tconst, 'similarity': 1.0, 'confidence': 'high', 'genres': ['Drama'],
                            'year_mismatch': bool(meta.get('year') and meta['year'] != year), 'runtime_agrees': agrees,
                            'runtime_mismatch': not agrees})
        return out


class TitlePartTests(unittest.TestCase):
    def test_parts(self):
        self.assertEqual(metadata.film_title_parts('The Pledge - Das Versprechen'), ['The Pledge', 'Das Versprechen'])
        self.assertEqual(metadata.film_title_parts('Jussi Adler-Olsen: Erlösung'), ['Jussi Adler-Olsen', 'Erlösung'])
        self.assertEqual(metadata.film_title_parts('Auf eigenes Risiko'), [])

    def test_part_with_year_and_runtime_is_chosen(self):
        import catalog
        title = 'The Pledge - Das Versprechen - Spielfilm, USA 2001'
        row = {'title': title, 'topic': 'Spielfilm', 'duration': 7400, 'provider': '3sat'}
        archive = Archive({'The Pledge': ('tt0237572', 2001, 124), 'Das Versprechen': ('tt0999999', 1995, 100)})
        with patch.object(imdb_archive, 'ACTIVE', archive):
            result = metadata.candidates(row, {'title': title, 'kind': 'movie', 'year': None}, {})
        refs = [c['reference_id'] for c in result['candidates']]
        self.assertEqual(refs, ['tt0237572'])   # 1995 film is no candidate (year from the suffix)
        judged = catalog.match_meta({'title': title, 'kind': 'movie', 'year': None}, row)
        chosen = matching.choose(judged, result['candidates'])
        self.assertEqual(chosen['reference_id'], 'tt0237572')

    def test_part_without_agreeing_runtime_stays_a_suggestion(self):
        import catalog
        title = 'Jussi Adler-Olsen: Erlösung - Spielfilm, Dänemark/Deutschland 2016'
        row = {'title': title, 'topic': 'Spielfilm', 'duration': 3000, 'provider': '3sat'}
        archive = Archive({'Erlösung': ('tt1189', 2016, 112)})
        with patch.object(imdb_archive, 'ACTIVE', archive):
            result = metadata.candidates(row, {'title': title, 'kind': 'movie', 'year': None}, {})
        self.assertEqual([c['reference_id'] for c in result['candidates']], ['tt1189'])
        judged = catalog.match_meta({'title': title, 'kind': 'movie', 'year': None}, row)
        self.assertIsNone(matching.choose(judged, result['candidates']))

    def test_two_parts_naming_two_films_decide_nothing(self):
        import catalog
        title = 'Alpha - Beta - Spielfilm, USA 2001'
        row = {'title': title, 'topic': 'Spielfilm', 'duration': 6000, 'provider': '3sat'}
        archive = Archive({'Alpha': ('tt1', 2001, 100), 'Beta': ('tt2', 2001, 100)})
        with patch.object(imdb_archive, 'ACTIVE', archive):
            result = metadata.candidates(row, {'title': title, 'kind': 'movie', 'year': None}, {})
        judged = catalog.match_meta({'title': title, 'kind': 'movie', 'year': None}, row)
        self.assertIsNone(matching.choose(judged, result['candidates']))

    def test_exact_title_hit_needs_no_parts(self):
        title = 'Der Schut - Spielfilm, BRD/Frankreich/Italien 1964'
        row = {'title': title, 'topic': 'Spielfilm', 'duration': 6000, 'provider': '3sat'}
        archive = Archive({'Der Schut': ('tt5', 1964, 100)})
        with patch.object(imdb_archive, 'ACTIVE', archive):
            metadata.candidates(row, {'title': title, 'kind': 'movie', 'year': None}, {})
        self.assertEqual(archive.asked, ['Der Schut'])


class CacheKeyTests(unittest.TestCase):
    def test_cache_key_carries_search_revision_and_search_title(self):
        src = (ROOT / 'catalog_service.py').read_text(encoding='utf-8')
        self.assertIn("metadata.SEARCH_REV,metadata.query_title(m['title'])", src)
        self.assertTrue(metadata.SEARCH_REV >= 'v06124')   # raised with each search change
        self.assertIn("'film_rules_parts_v06124'", src)


class StartupSettledTests(unittest.TestCase):
    def test_waits_for_heals_and_first_format_pass(self):
        service = catalog_service.Service(lambda: None, lambda: {}, threading.Event(), Path('.'))
        self.assertFalse(service.startup_settled(timeout=0.2))   # start() not yet run
        service.heals_done = threading.Event();service.first_format_pass = threading.Event()
        service.heals_done.set()
        self.assertFalse(service.startup_settled(timeout=0.2))
        threading.Timer(0.3, service.first_format_pass.set).start()
        started = time.monotonic()
        self.assertTrue(service.startup_settled(timeout=5))
        self.assertLess(time.monotonic() - started, 3)

    def test_server_builds_kids_shelf_after_settling(self):
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        block = src[src.index('def prewarm_listing'):src.index("name='catalog_listing_prewarm'")]
        self.assertLess(block.index('SERVICE.startup_settled(stop=STOP)'), block.index('_kids_shelf()'))


if __name__ == '__main__':
    unittest.main()
