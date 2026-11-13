"""0.5.82: works on top of Archive.org uploads (from Archive Media: work_title_queries, series_merge,
year_repair, anime_match). Uploads stay as they are; a work gets the same reference check as every
other platform."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_recognition as ar  # noqa: E402
import portal_sources  # noqa: E402

FILMS = {'night of the living dead': ('tt0063350', 1968), 'nosferatu': ('tt0013442', 1922),
         'the lone ranger': ('tt0041038', 1949), 'lone ranger': ('tt0041038', 1949)}


def lookup(row, meta, settings):
    hit = FILMS.get(ar.title_key(meta['title']))
    if not hit:
        return {'candidates': [], 'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 0}]}
    return {'candidates': [{'provider': 'IMDb Offline', 'reference_id': hit[0], 'title': meta['title'].title(), 'kind': meta['kind'],
                            'year': hit[1], 'similarity': 1.0, 'genres': ['Horror'], 'rating': 7.8, 'votes': 1000}],
            'provider_checks': [{'provider': 'IMDb Offline', 'status': 'checked', 'count': 1}]}


def upload(ident, title, year=None, description=''):
    return {'id': ident, 'source': 'internet_archive', 'title': title, 'year': year, 'description': description}


class ParseTests(unittest.TestCase):
    def test_release_noise_and_counters_are_removed(self):
        self.assertEqual(ar.parse('[BDMV] Night of the Living Dead (1968) 1080p')['title'], 'Night of the Living Dead')
        self.assertEqual(ar.parse('00012 - Nosferatu')['title'], 'Nosferatu')
        self.assertEqual(ar.parse('Night_of_the_Living_Dead')['title'], 'Night of the Living Dead')

    def test_year_in_title_beats_item_year(self):
        p = ar.parse('Night of the Living Dead (1968)', 2011)
        self.assertEqual((p['title'], p['year'], p['kind']), ('Night of the Living Dead', 1968, 'movie'))
        self.assertEqual(ar.parse('Nosferatu', 2009)['year'], 2009)

    def test_legitimate_names_stay(self):
        for title in ('2001: A Space Odyssey', '1984', '007 Dr. No', 'Blade Runner 2049', 'Se7en'):
            self.assertEqual(ar.parse(title)['title'], title)
        self.assertEqual(ar.parse('1984 (1956)')['year'], 1956)

    def test_episode_marks_make_a_series(self):
        p = ar.parse('The Lone Ranger S02E05 - Gold Train')
        self.assertEqual((p['kind'], p['title'], p['season'], p['episode'], p['year']), ('series', 'The Lone Ranger', 2, 5, None))
        p = ar.parse('The Lone Ranger - Season 3')
        self.assertEqual((p['kind'], p['title'], p['season'], p['episode']), ('series', 'The Lone Ranger', 3, None))
        p = ar.parse('Lone Ranger Folge 12')
        self.assertEqual((p['kind'], p['episode']), ('series', 12))
        # An episode label without a name in front is no series title.
        self.assertEqual(ar.parse('Episode 3')['kind'], 'movie')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = time.time()

    def build(self, uploads):
        return ar.rebuild(self.root, uploads, self.now)

    def check_all(self, **kw):
        for wid in ar.pending(self.root, limit=50, now=self.now):
            ar.enrich(self.root, wid, {}, lookup=lookup, now=self.now, **kw)


class WorkTests(Fixture):
    def test_uploads_of_one_film_are_one_work(self):
        result = self.build([upload('a', 'Night of the Living Dead (1968)'), upload('b', '[DVD] Night of the Living Dead', 1968),
                             upload('c', 'Nosferatu', 1922)])
        self.assertEqual(result, {'uploads': 3, 'works': 2, 'removed': 0})
        items = ar.annotate(self.root, [upload('a', 'Night of the Living Dead (1968)'), upload('c', 'Nosferatu', 1922)])
        self.assertEqual(items[0]['work']['uploads'], 2)
        self.assertEqual(items[0]['work']['status'], 'unchecked')
        self.assertEqual(items[1]['work']['uploads'], 1)

    def test_reference_check_and_listing(self):
        self.build([upload('a', 'Night of the Living Dead (1968)')])
        self.check_all()
        work = ar.annotate(self.root, [upload('a', 'x')])[0]['work']
        self.assertEqual(work['reference'], {'provider': 'IMDb Offline', 'id': 'tt0063350'})
        self.assertEqual((work['status'], work['year'], work['rating']), ('candidate', 1968, 7.8))
        self.assertEqual(ar.pending(self.root, now=self.now), [])
        self.assertEqual(ar.summary(self.root)['recognised'], 1)

    def test_year_repair_when_upload_year_is_the_upload_date(self):
        self.build([upload('a', 'Nosferatu', 2009)])
        self.check_all()
        work = ar.annotate(self.root, [upload('a', 'x')])[0]['work']
        self.assertEqual(work['reference']['id'], 'tt0013442')
        self.assertEqual((work['year'], work['year_source'], work['year_upload']), (1922, 'reference', 2009))
        self.assertEqual(ar.summary(self.root)['year_repaired'], 1)
        # A rebuild with the same uploads keeps the repaired state and the report.
        self.build([upload('a', 'Nosferatu', 2009)])
        self.assertEqual(ar.pending(self.root, now=self.now), [])
        self.assertEqual(ar.annotate(self.root, [upload('a', 'x')])[0]['work']['year'], 1922)

    def test_year_stays_when_nothing_is_found_without_it(self):
        self.build([upload('a', 'Ein unbekannter Heimatfilm', 1957)])
        self.check_all()
        work = ar.annotate(self.root, [upload('a', 'x')])[0]['work']
        self.assertEqual((work['reference'], work['year'], work['year_source']), (None, 1957, 'upload'))
        self.assertEqual(ar.summary(self.root)['year_repaired'], 0)
        self.assertEqual(ar.pending(self.root, now=self.now), [])

    def test_series_from_several_uploads_merge_by_title_and_reference(self):
        self.build([upload('e1', 'The Lone Ranger S01E01'), upload('e2', 'The Lone Ranger S01E02 Gold'),
                    upload('s2', 'Lone Ranger - Season 2'), upload('f', 'Nosferatu (1922)')])
        self.assertEqual(ar.summary(self.root)['works'], 3)      # two spellings of the series, one film
        self.check_all()
        self.assertEqual(ar.summary(self.root)['works'], 2)      # same IMDb id -> one work
        items = ar.annotate(self.root, [upload('e2', 'x'), upload('s2', 'x')])
        self.assertEqual(items[0]['work']['group'], items[1]['work']['group'])
        self.assertEqual((items[0]['work']['uploads'], items[0]['work']['season'], items[0]['work']['episode']), (3, 1, 2))
        self.assertEqual(ar.members_of(self.root, items[0]['work']['group']), ['e1', 'e2', 's2'])
        over = ar.overview(self.root)
        self.assertEqual((over['total'], over['recognised'], over['items'][0]['uploads']), (2, 2, 3))
        self.assertEqual(ar.overview(self.root, query='nosferatu')['total'], 1)

    def test_removed_uploads_remove_their_work(self):
        self.build([upload('a', 'Nosferatu (1922)'), upload('b', 'Night of the Living Dead (1968)')])
        self.check_all()
        self.assertEqual(self.build([upload('b', 'Night of the Living Dead (1968)')])['removed'], 1)
        self.assertEqual(ar.summary(self.root), {**ar.summary(self.root), 'uploads': 1, 'works': 1, 'checked': 1})
        with self.assertRaises(ValueError):
            ar.members_of(self.root, 'nonsense')


class AnimeTests(Fixture):
    MEDIA = {'id': 4711, 'title': {'romaji': 'Hakujaden', 'english': 'The White Snake Enchantress', 'native': '白蛇伝'},
             'synonyms': [], 'seasonYear': 1958, 'format': 'MOVIE', 'episodes': 1}

    def test_anime_without_reference_is_asked_at_anilist(self):
        asked = []

        def anime(title, year=None):
            asked.append(title)
            return ar.anime_match.choose(title, year, [self.MEDIA, {'id': 9, 'title': {'romaji': 'Something else'}}])
        self.build([upload('a', 'Hakujaden', None, 'Classic anime film'), upload('b', 'Nosferatu (1922)', None, 'Anime? no, but tagged anime')])
        for wid in ar.pending(self.root, limit=10, now=self.now):
            ar.enrich(self.root, wid, {}, lookup=lookup, now=self.now, anime_lookup=anime)
        self.assertEqual(asked, ['Hakujaden'])          # the film with a reference is not asked
        work = ar.annotate(self.root, [upload('a', 'x')])[0]['work']
        self.assertEqual((work['anilist']['id'], work['year'], work['year_source']), (4711, 1958, 'anilist'))
        self.assertEqual(ar.summary(self.root)['anilist'], 1)
        # Stored: no second question within the period.
        ar.enrich(self.root, work['id'], {}, lookup=lookup, now=self.now + 60, anime_lookup=anime)
        self.assertEqual(asked, ['Hakujaden'])

    def test_no_anime_hint_no_question_and_failure_is_not_stored(self):
        def broken(title, year=None):
            raise OSError('offline')
        self.build([upload('a', 'Ein unbekannter Heimatfilm', 1957), upload('b', 'Hakujaden', None, 'anime')])
        for wid in ar.pending(self.root, limit=10, now=self.now):
            ar.enrich(self.root, wid, {}, lookup=lookup, now=self.now, anime_lookup=broken)
        self.assertEqual(ar.summary(self.root)['anilist'], 0)
        db = ar.connect(self.root)
        self.addCleanup(db.close)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM archive_anime').fetchone()[0], 0)

    def test_ambiguous_anilist_answer_is_no_hit(self):
        twin = {**self.MEDIA, 'id': 4712}
        self.assertIsNone(ar.anime_match.choose('Hakujaden', None, [self.MEDIA, twin]))


class SyncTests(Fixture):
    def test_sync_reads_main_database_only_when_it_changed(self):
        c = sqlite3.connect(self.root / 'main.sqlite3')
        self.addCleanup(c.close)
        c.row_factory = sqlite3.Row
        portal_sources.initialize(c)
        row = portal_sources.entry('internet_archive', 'nosferatu_1922', 'Nosferatu (1922)', 'https://archive.org/details/nosferatu_1922')
        portal_sources.save(c, [row])
        self.assertEqual(ar.sync(self.root, c, self.now)['works'], 1)
        self.assertIsNone(ar.sync(self.root, c, self.now))
        listing = ar.annotate(self.root, portal_sources.listing(c, source='internet_archive')['items'])
        self.assertEqual(listing[0]['work']['query_title'], 'Nosferatu')
        self.assertEqual(json.loads(c.execute('SELECT metadata FROM portal_items').fetchone()[0])['title'], 'Nosferatu (1922)')
        # Netzkino links are not touched.
        self.assertNotIn('work', ar.annotate(self.root, [{'id': 'n', 'source': 'netzkino', 'title': 'x'}])[0])


class WiringTests(unittest.TestCase):
    def test_server_ui_and_bundle(self):
        s = (ROOT / 'server.py').read_text()
        for needle in ('archive_recognition.loop', "'/api/archive-works'", 'archive_recognition.annotate', "'/api/archive-work-check'"):
            self.assertIn(needle, s)
        self.assertIn("'archive_recognition.py'", (ROOT / 'build_macos.py').read_text())
        self.assertIn('portalWorkLine', (ROOT / 'web' / 'app.js').read_text())
        import task_control
        self.assertIn('enrich:archive', task_control.TASKS)


if __name__ == '__main__':
    unittest.main()
