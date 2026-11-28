"""0.6.167 – Mac-Prüfung 0.6.165/0.6.166: Reihenprüfung der Kinderecke (kids_shows) 6,7 s von 13,7 s Aufbau.
* Reihen mit Kinder-Thema einmal je Aufbau lesen statt je Reihe eine Abfrage mit bis zu 5.000 Themen.
* Werk-Fakten einer Reihe einmal je Aufbau (show_basis-Stichprobe und _has_episode nutzen dieselben).
* kids_undo_result prüft nach Kachel-Schlüssel (der gleichnamige Netzkino-Film zählt nicht)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog as kc  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


class MemoTests(Mixed):
    def test_same_result_with_and_without_memo(self):
        self.series('show:maus', 'Die Sendung mit der Maus', [(3, 'Das Erste', ['Kinder'], 'Maus %d')])
        self.series('show:kika', 'Bluey', [(2, 'KiKA', [], 'Bluey %d')])
        self.series('show:news', 'Tagesschau', [(2, 'ARD', [], 'Nachrichten %d')])
        with self.db() as c:
            plain = {s: (kc.show_basis(c, s), kc._work_facts(c, s)) for s in ('show:maus', 'show:kika', 'show:news')}
            query = kc._work_query(c)
            memo = {s: (kc.show_basis(c, s, query=query), kc._work_facts(c, s, None, query)) for s in plain}
            self.assertEqual(plain, memo)
            self.assertEqual(kc._work_facts(c, 'show:maus', 2, query), plain['show:maus'][1][:2])
            for s in plain:
                self.assertEqual(kc._curated_topic(c, s), kc._curated_topic(c, s, query[2]))

    def test_curated_topics_read_once_per_build(self):
        self.series('show:a', 'A', [(1, 'ARD', [], 'A %d')])
        with self.db() as c, mock.patch('catalog.kids_topics', return_value=['Die Sendung mit der Maus'] * 3000):
            memo, calls = {}, []
            real = c.execute
            proxy = mock.MagicMock(wraps=c)
            proxy.execute.side_effect = lambda *a: calls.append(a[0]) or real(*a)
            for _ in range(5):
                kc._curated_topic(proxy, 'show:a', memo)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
