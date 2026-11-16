"""0.6.14 Abo-Videos pro Stunde (Björn, 16.11.2026: „lieber nur wenige Videos die Stunde laden“, damit die
Bot-Sperre gar nicht erst auslöst). Abo-Aufträge starten gleichmäßig verteilt, Klicks von Hand sofort."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import download_retry as dr, youtube_abos as ab  # noqa: E402
from _wiring import SERVER  # noqa: E402


class PacingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_default_four_per_hour_evenly_spaced(self):
        self.assertEqual(ab.per_hour(self.root), 4)
        first, second = {'youtube_abo': 1}, {'youtube_abo': 2}
        self.assertFalse(ab.pace(self.root, first, now=10_000))          # erster startet sofort
        self.assertTrue(ab.pace(self.root, second, now=10_060))          # zweiter wartet 15 Minuten
        self.assertEqual(second['not_before'], 10_000 + 900)
        self.assertIn('Höchstens 4 Abo-Videos pro Stunde', second['note'])
        self.assertEqual(ab.next_slot(self.root, now=10_060), 10_900)
        self.assertFalse(ab.pace(self.root, second, now=10_900))         # dann ist er dran
        self.assertEqual(ab.next_slot(self.root, now=10_901), 11_800)

    def test_manual_jobs_and_force(self):
        self.assertFalse(ab.pace(self.root, {'youtube_abo': 1}, now=10_000))
        self.assertFalse(ab.pace(self.root, {'origin': 'youtube'}, now=10_001))      # „Offline speichern“ von Hand
        forced = {'youtube_abo': 3}
        self.assertFalse(ab.pace(self.root, forced, now=10_002, force=True))         # „Jetzt versuchen“
        self.assertNotIn('not_before', forced)
        self.assertEqual(ab.next_slot(self.root, now=10_003), 10_002 + 900)          # zählt aber mit

    def test_setting(self):
        self.assertEqual(ab.set_per_hour(self.root, '2'), 2)
        self.assertFalse(ab.pace(self.root, {'youtube_abo': 1}, now=0 + 5000))
        job = {'youtube_abo': 1}
        self.assertTrue(ab.pace(self.root, job, now=5001))
        self.assertEqual(job['not_before'], 5000 + 1800)
        for bad in (0, 5, 'viel', None):
            with self.assertRaises(ValueError):
                ab.set_per_hour(self.root, bad)
        data = ab.overview(self.root)
        self.assertEqual((data['per_hour'], data['per_hour_choices'][0]), (2, 1))

    def test_clock_set_back_does_not_block(self):
        ab.pace(self.root, {'youtube_abo': 1}, now=99_999_999)
        self.assertFalse(ab.pace(self.root, {'youtube_abo': 1}, now=1000))


class BlockBackoffTests(unittest.TestCase):
    def test_bot_block_starts_at_one_hour(self):
        # Diagnose 16.11.2026: Sperre hielt mindestens 80 Minuten; 15 Minuten wären verschenkte Versuche.
        self.addCleanup(dr.clear)
        job = {'id': 'j', 'source': {'_resolver': 'youtube'}}
        dr.reschedule(job, dr.RetryLater('kein Bot', block=True), now=0, rand=lambda: .5)
        self.assertEqual(job['not_before'], 3600)
        other = {'id': 'k', 'source': {'_resolver': 'youtube'}}
        dr.reschedule(other, dr.RetryLater('Netz weg'), now=0, rand=lambda: .5)
        self.assertEqual(other['not_before'], 3600)        # wartet trotzdem bis zum Ende der Sperre


class WiringTests(unittest.TestCase):
    def test_worker_and_route(self):
        self.assertIn('youtube_abos.pace(ROOT,j,force=forced)', SERVER)
        self.assertIn("elif action=='pace':youtube_abos.set_per_hour(ROOT,d.get('per_hour'))", SERVER)

    def test_ui(self):
        self.assertIn('id="youtube-abos-pace"', (ROOT / 'web/index.html').read_text(encoding='utf-8'))
        js = (ROOT / 'web/youtube_abos.js').read_text(encoding='utf-8')
        self.assertIn("act({action: 'pace', per_hour: Number(pick.value)}", js)
        self.assertIn('Offline speichern“ von Hand startet sofort', js)


if __name__ == '__main__':
    unittest.main()
