"""0.6.44 (Björn, 20.11.2026, Diagnose 0.6.43 vom M3 MacBook Pro):
- Episodensuche: aufgebrauchtes Stundenkontingent des Senderabrufs stellt Werke nicht mehr endlos zurück.
- Ausgaben: „Teil 1 vom 15.04.2026“, „vom Montag, 16. Februar 2026“, „26. Jänner 2025“.
- Protokoll: keine zwei Ereignisse je Werk mehr.
- YouTube-Abos: Prüfungen zeitlich versetzt.
- Dateinamen ohne Emojis, Hashtags und Sonderzeichen; alte Downloads werden weiter gefunden.
- Plattformseiten: „… verwalten“ oben."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))

import broadcaster, catalog, catalog_service, core, imdb_archive, metadata  # noqa: E402
import youtube_abos as ab  # noqa: E402
import test_v0530  # noqa: E402


class EditionDates(unittest.TestCase):
    def role(self, title, series, sendung=True):
        return catalog.recurring_edition({'kind': 'series', 'title': series}, {'title': title, 'topic': series, 'duration': 1700}, sendung)

    def test_new_date_forms_are_editions(self):
        self.assertEqual(self.role('hallo hessen – Teil 1 vom 15.04.2026', 'hallo hessen'), 'edition')
        self.assertEqual(self.role('logo! vom Montag, 16. Februar 2026', 'logo!'), 'edition')
        self.assertEqual(self.role('erLesen - Sendung vom  26. Jänner 2025', 'Erlesen'), 'edition')

    def test_numbered_episodes_stay_episodes(self):
        self.assertIsNone(self.role('Der Fall (Teil 2)', 'Tatort'))
        self.assertIsNone(self.role('Folge 12', 'hallo hessen'))
        self.assertIsNone(self.role('Teil 3', 'hallo hessen'))

    def test_title_date_reads_weekday_and_austrian_month(self):
        self.assertEqual(imdb_archive.title_date('logo! vom Montag, 16. Februar 2026')[1:], (2026, 2, 16))
        self.assertEqual(imdb_archive.title_date('erLesen vom 26. Jänner 2025')[1:], (2025, 1, 26))
        self.assertEqual(imdb_archive.title_date('Wien heute vom 3. Feber 2025')[1:], (2025, 2, 3))


class SenderBudget(test_v0530.EpisodeWorkerTests):
    def test_exhausted_budget_lets_imdb_decide(self):
        self.direct = True
        archive = type('Offline', (), {'updated': 1, 'episode_evidence': lambda self, *a: {'candidates': [], 'series_with_episodes': 1}})()
        with patch('broadcaster.lookup_limited', side_effect=broadcaster.BudgetExhausted('Stundenlimit')), patch.object(imdb_archive, 'ACTIVE', archive):
            self.assertTrue(self.svc.metadata_once('episode'))
        _, _, q = self.data()
        self.assertEqual(q['last_outcome'], 'unresolved')
        self.assertGreater(q['next_try'], time.time() + 6 * 86400)
        self.assertLess(q['next_try'], time.time() + 8 * 86400)
        self.assertEqual(self.svc.episode_sender_budget, 1)
        self.assertEqual(self.svc.episode_sender_deferred, 0)
        self.assertEqual(self.svc.episode_retried, 0)

    def test_budget_error_is_raised_by_the_limit(self):
        broadcaster._CACHE.clear(); broadcaster._PAUSED.clear(); broadcaster._AUTOMATED_BUDGET.clear()
        row = {'url_website': 'https://www.ardmediathek.de/video/x/Y3JpZDovL2FiYy8xMjM0'}
        with patch.object(broadcaster, 'AUTOMATED_HOURLY_LIMIT', 0):
            with self.assertRaises(broadcaster.BudgetExhausted):
                broadcaster.lookup_limited(row)


class ProtocolVolume(unittest.TestCase):
    def test_metadata_status_is_sampled(self):
        svc = catalog_service.Service(lambda: None, lambda: {}, __import__('threading').Event(), Path('.'))
        with patch('diagnostics.event') as log:
            svc.checked = 7
            svc.metadata_state(phase='checking', title='A')
            svc.metadata_state(phase='result', title='A', outcome='identified')
            svc.metadata_state(phase='result', title='B', outcome='review')
            svc.metadata_state(phase='result', title='C', outcome='retry')
            svc.checked = 100
            svc.metadata_state(phase='result', title='D', outcome='identified')
        self.assertEqual([c.kwargs['title'] for c in log.call_args_list], ['C', 'D'])
        self.assertEqual(svc.metadata_status['title'], 'D')

    def test_slow_provider_answer_is_logged(self):
        with patch('diagnostics.event') as log:
            metadata.provider_complete(time.monotonic() - 3, provider='TMDB', title='X', candidates=0)
            metadata.provider_complete(time.monotonic(), provider='TMDB', title='Y', candidates=0)
        self.assertEqual([c.kwargs['title'] for c in log.call_args_list], ['X'])


class AboStagger(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = ab._connect(self.root)
        self.addCleanup(self.db.close)
        with self.db:
            for n in range(1, 4):
                self.db.execute("INSERT INTO youtube_abos(ref,kind,added,next_check,enabled) VALUES(?,?,?,?,1)",
                                ('@k%d' % n, 'channel', 1000, 5000))

    def test_next_check_keeps_distance(self):
        when = ab._staggered(self.db, 1, 5000)
        self.assertGreaterEqual(when - 5000, ab.STAGGER)
        self.assertEqual(ab._staggered(self.db, 1, 5000 + 3 * ab.STAGGER), 5000 + 3 * ab.STAGGER)

    def test_run_due_checks_one_abo_and_spreads_the_rest(self):
        seen = []
        with patch.object(ab, 'check', side_effect=lambda root, i, now=None: seen.append(i) or {'ok': True}):
            ab.run_due(self.root, now=6000)
        self.assertEqual(len(seen), 1)
        rest = sorted(r[0] for r in self.db.execute('SELECT next_check FROM youtube_abos WHERE id!=?', (seen[0],)))
        self.assertEqual(rest, [6000 + ab.STAGGER, 6000 + 2 * ab.STAGGER])


class FileNames(unittest.TestCase):
    def test_tidy_name(self):
        cases = {'Bluey ｜ Ganze Folge 🐶 #kinder #bluey': 'Bluey - Ganze Folge',
                 'Peppa Wutz ⧸ Die Pfütze!!! 💦': 'Peppa Wutz - Die Pfütze!',
                 '„Tatort“: Der Fall – Teil 2': 'Tatort - Der Fall - Teil 2',
                 'Löwenzahn: Die Ölpest': 'Löwenzahn - Die Ölpest',
                 'Paw Patrol #1 Folge': 'Paw Patrol #1 Folge',
                 'Was ist das?': 'Was ist das',
                 '🎉': 'Unbekannt'}
        for raw, want in cases.items():
            self.assertEqual(core.tidy_name(raw), want, raw)

    def test_umlauts_are_nfc(self):
        import unicodedata
        self.assertEqual(core.tidy_name(unicodedata.normalize('NFD', 'Ölpest')), 'Ölpest')

    def test_target_is_tidy_and_old_file_is_still_found(self):
        meta = {'kind': 'movie', 'title': 'Bluey ｜ Spezial 🐶', 'year': 2024, 'season': None, 'episode': None}
        with tempfile.TemporaryDirectory() as tmp:
            new = core.target(tmp, meta, 'x:1')
            self.assertIn('Bluey - Spezial - (2024)', new.name)
            self.assertIsNone(core.existing_for(tmp, meta, 'x:1'))
            old = core.legacy_target(tmp, meta, 'x:1')
            self.assertNotEqual(old, new)
            old.parent.mkdir(parents=True)
            (old.parent / (old.stem + ' - 1080p - H264 AAC.mkv')).write_bytes(b'x')
            self.assertTrue(core.existing_for(tmp, meta, 'x:1'))

    def test_abo_job_name_and_existing_channel_folder(self):
        abo = {'id': 1, 'title': 'Kinder ｜ Kanal 🐻', 'kids': 1, 'quality': '720'}
        video = {'video': 'abcdefghijk', 'title': 'Bluey ｜ Ganze Folge 🐶 #kinder', 'published': '2026-11-20T08:00:00Z'}
        with tempfile.TemporaryDirectory() as tmp:
            job = ab.build_job(tmp, tmp, abo, video, now=1)
            self.assertEqual(Path(job['target']).parent.name, 'Kinder - Kanal')
            self.assertEqual(Path(job['target']).name, '2026-11-20 - Bluey - Ganze Folge [abcdefghijk].mp4')
            (Path(tmp) / ab.FOLDER / 'Kinder ｜ Kanal 🐻').mkdir(parents=True)
            job = ab.build_job(tmp, tmp, abo, video, now=1)
            self.assertEqual(Path(job['target']).parent.name, 'Kinder ｜ Kanal 🐻')


class PlatformAdminOnTop(unittest.TestCase):
    def test_admin_block_follows_status_line(self):
        js = (ROOT / 'web' / 'admin.js').read_text()
        self.assertIn('brief.after(admin)', js)
        self.assertNotIn('section.append(admin)', js)


if __name__ == '__main__':
    unittest.main()
