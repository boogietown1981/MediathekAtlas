"""0.6.71 (Mac-Prüfung 0.6.70, 21.11.2026): Sturm der Liebe nur +770 statt ≥ 1.200.

934 offene Folgen mit Nummer ≤ 4.678 heißen „Episode N“ (Wiederholungen auf ONE 2025/26, IMDb-Jahr 2007–2010,
z. B. „Episode 1140“ ↔ tt8374782 #1.1140). Ursache: die Nummer wurde nur aus „Folge N“ gelesen – nicht die
Datumsprüfung, die gilt nur für ein Datum, das im Titel steht; das Sendedatum des Angebots zählt nicht.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imdb_archive  # noqa: E402
from test_v0670 import Soaps, build  # noqa: E402


class EpisodeTitles(Soaps):
    def test_repeat_titled_episode_n_is_matched_despite_a_recent_broadcast(self):
        for title in ('Episode 150', 'Episode 150 (Audiodeskription)'):
            with self.subTest(title=title):
                src_stamp = 1773014400                         # 09.03.2026, IMDb year of #1.150 is 2006
                chosen = self.match(title, 'Sturm der Liebe', 'tt0479846', timestamp=src_stamp)
                self.assertIsNotNone(chosen)
                self.assertEqual((chosen['season'], chosen['episode'], chosen['episode_reference_id']), (1, 150, 'tt8000150'))
                self.assertEqual(chosen['episode_title'], 'Folge 150')

    def test_episode_n_keeps_the_guards(self):
        self.assertIsNone(self.match('Episode 4999', 'Sturm der Liebe', 'tt0479846'))           # unknown number
        self.assertIsNone(self.match('Episode 3', 'Krimi mit Staffeln', 'tt7000000'))           # several seasons
        self.assertIsNone(self.match('Episode 150', 'Sturm der Liebe', 'tt0479846', duration=200))  # short clip
        self.assertIsNone(self.match('Episode 150 · 17.08.15 | x', 'Sturm der Liebe', 'tt0479846'))  # title date 2015 ≠ 2006
        self.assertIsNone(imdb_archive.absolute_episode({'title': 'Episode 2/6'}, {}))


class TrimEvent(unittest.TestCase):
    def test_event_names_the_planned_size(self):
        import youtube_abos as ab
        sent = []
        with mock.patch.object(ab, '_notify', lambda name, **kw: sent.append((name, kw))), \
                mock.patch.object(ab, 'held', lambda c, db, abo: (0, 30 * ab.GB)), \
                mock.patch.object(ab, '_job_states', lambda c, ids: {i: ('queued', None) for i in ids}), \
                mock.patch.object(ab, 'abo_rate', lambda *a: None), \
                mock.patch.object(ab, 'sized', lambda *a: 6 * ab.GB):
            class DB:
                def __init__(self):
                    self.rows = [{'abo_id': 'a', 'video': 'v%d' % i, 'job_id': 'j%d' % i, 'published': '2026-11-%02d' % (i + 1), 'position': i, 'state': 'queued'} for i in range(5)]

                def execute(self, sql, params=()):
                    class R(list):
                        rowcount = 1
                    return R(self.rows) if sql.startswith('SELECT') else R()

                def commit(self):
                    pass
            released = ab.trim_queued(DB(), DB(), {'id': 'a', 'kind': 'channel', 'quality': '720', 'budget_gb': 10}, 10 * ab.GB)
        self.assertEqual(released, 4)
        self.assertEqual(sent[0][1]['used_gb'], 0.0)
        self.assertEqual(sent[0][1]['planned_gb'], 30.0)


if __name__ == '__main__':
    unittest.main()
