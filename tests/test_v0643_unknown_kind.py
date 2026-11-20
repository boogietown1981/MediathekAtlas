"""0.6.43: checked works of unknown kind get their kind (Sendung, Einzelsendung, Film).

Nachtdiagnose 20.11.2026 (0.6.40, MacBook Air): 38,727 open works stayed "Noch zuordnen", 95 % single
contributions of SRF, ARTE, ORF and 3Sat; the first pass was almost done (985 left), so they were not a
backlog but works no film database knows. The kind follows from the Sendung (topic) once providers found
nothing; never for unchecked works, works with suggestions, provider errors or a user request.
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402


def offer(title, topic, channel='SRF', duration=1500, n=0, description=''):
    return {'title': title, 'topic': topic, 'description': description, 'duration': duration,
            'channel': channel, 'url_video': 'https://example.org/%s-%d.mp4' % (channel, n),
            'timestamp': 1795100000}


class RoleTests(unittest.TestCase):
    def role(self, title, topic, count, duration=1500, description=''):
        return catalog.unknown_role(offer(title, topic, duration=duration, description=description), count)

    def test_recurring_sendung(self):
        self.assertEqual(self.role('Gefährliche Keime im Spital', 'Puls', 5), ('contribution', 'Puls'))
        self.assertEqual(self.role('Wie sicher sind E-Bikes?', 'Kassensturz', 4, duration=420), ('segment', 'Kassensturz'))
        self.assertEqual(self.role('Kulturplatz vom 19.11.2026', 'Kulturplatz', 2), ('edition', 'Kulturplatz'))
        self.assertEqual(self.role('Universum', 'Universum', 3), ('edition', 'Universum'))
        self.assertEqual(self.role('Der Germanwings-Absturz (2/3)', 'Der Germanwings-Absturz', 3), ('part', 'Der Germanwings-Absturz'))
        self.assertEqual(self.role('Folge 2: Popelproduktion', 'Ene Mene Bu', 2), ('part', 'Ene Mene Bu'))

    def test_single_programmes(self):
        # Only this one work under its topic, or the topic only repeats the title of two versions.
        self.assertEqual(self.role('Die Mafiamorde von Duisburg', 'Die Mafiamorde von Duisburg', 1, duration=2700), ('single', ''))
        self.assertEqual(self.role('Die Mafiamorde von Duisburg', 'Die Mafiamorde von Duisburg', 2, duration=2700), ('single', ''))
        self.assertEqual(self.role('Ein Tag am Meer', 'Wilde Küsten', 1), ('single', ''))
        # Collective rubrics name no Sendung.
        self.assertEqual(self.role('Pietro Mascagni: Iris', 'Dokumentation', 40, duration=5400), ('single', ''))
        self.assertEqual(self.role('Sport: Kennt der Körper keine Grenzen?', 'Kultur - Pop-Kultur', 40), ('single', ''))

    def test_explicit_film_evidence(self):
        self.assertEqual(self.role('Ein stiller Abend', 'Spielfilm', 30, duration=5400), ('movie', ''))
        self.assertEqual(self.role('Ein stiller Abend', 'Der Fernsehfilm der Woche', 12, duration=5400), ('movie', ''))
        self.assertEqual(self.role('Ein stiller Abend', 'Wilde Küsten', 1, duration=5400,
                                   description='Spielfilm, Deutschland 2024'), ('movie', ''))
        # Too short for a feature, a dated edition, or a film word without feature length.
        self.assertEqual(self.role('Ein stiller Abend', 'Spielfilm', 30, duration=1500), ('single', ''))
        self.assertEqual(self.role('Kino vom 19.11.2026', 'Kino-Magazin', 6, duration=4000), ('edition', 'Kino-Magazin'))

    def test_numbered_part_without_topic_names_its_series(self):
        self.assertEqual(self.role('Österreich - Die ganze Geschichte (7/10): Der Aufstieg', '', 1),
                         ('part', 'Österreich - Die ganze Geschichte'))


class OpenReasonTests(unittest.TestCase):
    def reason(self, attempts=1, state='review', **meta):
        return catalog.unknown_open_reason({'state': state, 'attempts': attempts}, meta)

    def test_only_checked_works_without_evidence_qualify(self):
        self.assertIsNone(self.reason())
        self.assertIsNone(self.reason(state='retry', deferred_providers=['ARD Mediathek', 'OMDb']))
        self.assertEqual(self.reason(attempts=0), 'unchecked')
        self.assertEqual(self.reason(suggestions=[{'provider': 'TMDB'}]), 'suggestions')
        self.assertEqual(self.reason(metadata_warnings=['TMDB: Zeitüberschreitung']), 'warnings')
        self.assertEqual(self.reason(deferred_providers=['TMDB']), 'deferred')
        self.assertEqual(self.reason(scan_requested=True), 'requested')
        self.assertEqual(self.reason(state='manual'), 'state')


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Gefährliche Keime im Spital', 'Puls', n=1),
                offer('Schlaflos in der Schweiz', 'Puls', n=2),
                offer('Wenn die Hüfte schmerzt', 'Puls', n=3),
                offer('Die Mafiamorde von Duisburg', 'Die Mafiamorde von Duisburg', channel='ARD', duration=2700, n=4),
                offer('Ein stiller Abend', 'Kino am Sonntag', channel='ZDF', duration=5400, n=5),
                offer('Neu im Katalog', 'Neue Sendung', channel='ORF', n=6),            # not yet checked
                offer('Mit Vorschlag', 'Puls', n=7),                                     # has a suggestion
                offer('Fehler beim Anbieter', 'Puls', n=8),                              # provider error
                offer('Bitte prüfen', 'Puls', n=9)]                                       # user request
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, rows)
            for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
                m = json.loads(meta)
                self.assertEqual(m['kind'], 'unknown', m['title'])
                attempts = 0 if m['title'] == 'Neu im Katalog' else 1
                if m['title'] == 'Mit Vorschlag':m['suggestions'] = [{'provider': 'TMDB'}]
                if m['title'] == 'Fehler beim Anbieter':m['metadata_warnings'] = ['TMDB: Zeitüberschreitung']
                if m['title'] == 'Bitte prüfen':m['scan_requested'] = True
                c.execute("UPDATE works SET state='review', attempts=?, meta=? WHERE id=?",
                          (attempts, json.dumps(m), wid))
        self.service = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def works(self):
        with self.db() as c:
            return {json.loads(r['meta']).get('episode_title') or r['title']: dict(r, meta=json.loads(r['meta']))
                    for r in c.execute('SELECT * FROM works')}

    def test_sweep_files_checked_works_and_leaves_the_rest(self):
        events = []
        with patch.object(diagnostics, 'event', lambda name, **kw: events.append((name, kw))):
            changed = self.service.unknown_sweep(force=True)
        self.assertEqual(changed, 5)
        w = self.works()
        for title in ('Gefährliche Keime im Spital', 'Schlaflos in der Schweiz', 'Wenn die Hüfte schmerzt'):
            self.assertEqual((w[title]['kind'], w[title]['state'], w[title]['title']), ('series', 'format', 'Puls'), title)
            self.assertEqual(w[title]['meta']['format_grouping'], 'contribution')
            self.assertEqual(w[title]['meta']['provider'], 'Sendung')
        single = w['Die Mafiamorde von Duisburg']
        self.assertEqual((single['kind'], single['state'], single['meta']['format_grouping']), ('other', 'format', 'single'))
        film = w['Ein stiller Abend']
        self.assertEqual((film['kind'], film['state']), ('movie', 'review'))
        for title in ('Neu im Katalog', 'Mit Vorschlag', 'Fehler beim Anbieter', 'Bitte prüfen'):
            self.assertEqual(w[title]['kind'], 'unknown', title)
        name, info = [e for e in events if e[0] == 'unknown_classified'][0]
        self.assertEqual(info['classified'], {'contribution': 3, 'single': 1, 'movie': 1})
        self.assertEqual(info['remaining'], {'suggestions': 1, 'warnings': 1, 'requested': 1})
        self.assertEqual(info['unknown_left'], 4)
        self.assertEqual(info['channels']['SRF'], {'contribution': 3})
        self.assertTrue(info['samples']['single'][0]['title'].startswith('Die Mafiamorde'))
        with self.db() as c:
            self.assertEqual(catalog.stats(c)['unknown_sweep']['changed'], 5)

    def test_sweep_waits_for_its_interval_and_is_idempotent(self):
        self.assertEqual(self.service.unknown_sweep(force=True), 5)
        self.assertIsNone(self.service.unknown_sweep())
        self.assertEqual(self.service.unknown_sweep(force=True), 0)

    def test_single_joins_its_sendung_once_more_editions_arrive(self):
        with self.db() as c:
            catalog.ingest(c, [offer('Wien bei Nacht', 'Stadtgeschichten', channel='ORF', n=20)])
            c.execute("UPDATE works SET state='review', attempts=1 WHERE title='Wien bei Nacht'")
        self.service.unknown_sweep(force=True)
        self.assertEqual(self.works()['Wien bei Nacht']['meta']['format_grouping'], 'single')
        with self.db() as c:
            catalog.ingest(c, [offer('Graz im Winter', 'Stadtgeschichten', channel='ORF', n=21)])
            c.execute("UPDATE works SET state='review', attempts=1 WHERE title='Graz im Winter'")
        self.service.unknown_sweep(force=True)
        w = self.works()
        for title in ('Wien bei Nacht', 'Graz im Winter'):
            self.assertEqual((w[title]['kind'], w[title]['title'], w[title]['meta']['format_grouping']),
                             ('series', 'Stadtgeschichten', 'contribution'), title)

    def test_user_decisions_are_never_touched(self):
        with self.db() as c:
            c.execute("UPDATE works SET state='manual' WHERE title='Schlaflos in der Schweiz'")
        self.service.unknown_sweep(force=True)
        self.assertEqual(self.works()['Schlaflos in der Schweiz']['state'], 'manual')

    def test_format_loop_runs_the_sweep(self):
        self.assertIn('self.unknown_sweep()', Path(catalog_service.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
