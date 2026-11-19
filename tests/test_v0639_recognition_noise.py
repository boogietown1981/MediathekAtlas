"""0.6.39 (Björn, 19.11.2026: "bei ARD, ZDF etc. 2.390 nicht erkannte Filme und 2.817 unbekannte Serien").

Diagnosis 16:12, 1,086 failed checks in the fast window: 41 % ARTE language versions (FR/ES/IT/PL/EN),
22 % titles with episode counters or labels ("(12)", "(2/6)", "Season 1", "- Audiodeskription", "NEU"),
8 % dated magazine editions ("ttt vom 2. Februar 2025"). Search titles are cleaned; dated editions and
foreign versions of a recurring Sendung join it instead of being queried as films."""
import json, sys, tempfile, unittest, unittest.mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog, metadata  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402


def offer(title, topic, channel='ZDF', duration=1800, n=0):
    return {'title': title, 'topic': topic, 'description': '', 'duration': duration, 'channel': channel,
            'url_video': 'https://example.org/%s-%d.mp4' % (channel, n)}


class QueryTitleTests(unittest.TestCase):
    def test_counters_and_labels_leave_the_search_title(self):
        for title, query in [('Donna Leon (12) – Das Gesetz der Lagune', 'Donna Leon – Das Gesetz der Lagune'),
                             ('Gladbeck (2/2) - Audiodeskription', 'Gladbeck'),
                             ('Küssen verboten (5) · NEU', 'Küssen verboten'),
                             ('NEU · Bis auf den Knochen. Ein Krimi aus Passau (9)', 'Bis auf den Knochen. Ein Krimi aus Passau'),
                             ('Hungry - Season 1 (2/6)', 'Hungry'), ('Catastrophe (6/6) - Temporada 2', 'Catastrophe'),
                             ('Der Kroatien-Krimi: Tod einer Legende - Audiodeskription', 'Der Kroatien-Krimi: Tod einer Legende'),
                             ('Der Pate (Originalversion mit Untertitel)', 'Der Pate')]:
            self.assertEqual(metadata.query_title(title), query, title)

    def test_real_titles_stay(self):
        for title in ('2001', 'Staffel 3', 'Die Neue', 'Neue Welt', 'Nosferatu (1922)', 'Ocean’s 11', 'M - Eine Stadt sucht einen Mörder'):
            self.assertEqual(metadata.query_title(title), catalog.cleaned(title), title)

    def test_numbered_part_asks_for_the_series(self):
        self.assertEqual(metadata.part_series('Die Rosenheim-Cops (13/20): Leben vergeht, Geld besteht'), 'Die Rosenheim-Cops')
        self.assertEqual(metadata.part_series('Der Fall Barschel (1)'), '')
        seen = []

        def fake(row, meta, key, kind, title):
            seen.append((kind, title))
            return []
        with unittest.mock.patch.object(metadata, 'tmdb_candidates', fake), \
                unittest.mock.patch('imdb_archive.ACTIVE', None), \
                unittest.mock.patch.object(metadata, 'negative_cache') as neg:
            neg.contains.return_value = False
            metadata.candidates({'title': 'Österreich - Die ganze Geschichte (2/10): Der Spinner aus England', 'topic': ''},
                                {'kind': 'unknown', 'title': 'Österreich - Die ganze Geschichte (2/10): Der Spinner aus England'},
                                {'tmdb': 'k' * 32})
        self.assertEqual(seen[0], ('series', 'Österreich - Die ganze Geschichte'))
        self.assertEqual(seen[1], ('movie', 'Österreich - Die ganze Geschichte: Der Spinner aus England'))


class FormatRuleTests(unittest.TestCase):
    def test_dated_editions(self):
        for title in ('28 minutes - COP31, boycott de CNews (13/11/2026)', 'ttt vom 2. Februar 2025', 'Studio 2 vom 16.11.2026',
                      'Hier und heute | 12.08.2025', 'Ausgabe 2.3.2024.'):
            self.assertTrue(catalog.format_contribution({'kind': 'unknown'}, offer(title, 'Magazin X'), 2), title)
            self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, offer(title, 'Magazin X'), 1), title)
        for title in ('Der 20. Juli 1944', 'Gladbeck (2/2)', '1.000 Jahre', 'Version 1.2.2023x', 'Tatort: 12.12.12'):
            self.assertFalse(catalog.DATED.search(title), title)
        self.assertFalse(catalog.format_contribution({'kind': 'movie'}, offer('ttt vom 2. Februar 2025', 'ttt'), 5))

    def test_foreign_arte_versions_of_a_recurring_sendung(self):
        src = offer('Le dessous des images - Mbappé', 'Le dessous des images', channel='ARTE.FR', duration=720)
        self.assertTrue(catalog.format_contribution({'kind': 'unknown'}, src, 3))
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, src, 2))
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, {**src, 'duration': 5400}, 9))   # feature length
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, {**src, 'channel': 'ARTE.DE'}, 9))
        self.assertFalse(catalog.format_contribution({'kind': 'unknown'}, {**src, '_foreign_only': False}, 9))


class AssignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)

    def test_checked_without_hit_joins_its_sendung_once_rules_match(self):
        rows = [offer('ttt vom 2. Februar 2025', 'ttt - titel, thesen, temperamente', channel='ARD', n=1),
                offer('ttt vom 9. Februar 2025', 'ttt - titel, thesen, temperamente', channel='ARD', n=2),
                offer('Green, ma non troppo - Libro o reader?', 'Green, ma non troppo', channel='ARTE.IT', duration=600, n=3),
                offer('Green, ma non troppo - Auto elettrica?', 'Green, ma non troppo', channel='ARTE.IT', duration=600, n=4),
                offer('Green, ma non troppo - Vestiti nuovi?', 'Green, ma non troppo', channel='ARTE.IT', duration=600, n=5),
                offer('Ein stiller Abend', 'Fernsehfilme', channel='ZDF', duration=5400, n=6)]
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, rows)
            # every work was checked without a hit; one has a candidate to look at
            for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
                m = json.loads(meta)
                if 'Vestiti' in m.get('title', '') + m.get('episode_title', ''):
                    m['suggestions'] = [{'provider': 'TMDB'}]
                c.execute("UPDATE works SET state='review', meta=? WHERE id=?",
                          (json.dumps(m), wid))
            catalog.assign_formats(c)
            states = {r['title'] + '|' + (json.loads(r['meta']).get('episode_title') or ''): r['state'] for r in c.execute('SELECT * FROM works')}
        formats = [k for k, v in states.items() if v == 'format']
        self.assertEqual(len(formats), 4, states)
        self.assertFalse(any('Vestiti' in k or 'stiller' in k for k in formats))

    def test_rev_bump_restarts_the_format_pass(self):
        self.assertGreaterEqual(catalog.FORMAT_REV, 5)


if __name__ == '__main__':
    unittest.main()
