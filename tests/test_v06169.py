"""0.6.169 – Mac-Messung 0.6.168 (BEFUND-06168): kids_shows 4,3 s, davon facts 3,43 s für 40.184 Werke (logo! 3.631).
* show_basis liest nur seine Stichprobe (SHOW_SAMPLE), nicht die ganze Reihe.
* _has_episode bewertet die neuesten Folgen stückweise (100, 400, …) bis eine passt – gleiche Antwort."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import kids_catalog as kc  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402


def full_answer(c, show, basis):
    """Antwort wie bis 0.6.168: alle Folgen bewerten."""
    paths = kc._episode_paths(c, show, basis)
    if any(p in ('freigabe', 'sender') and kc._active(c, w) for w, p in paths.items()):
        return True
    ok = [w for w, p in paths.items() if p]
    for _, otitle, ch in c.execute(
            "SELECT w.id, json_extract(o.payload,'$.title'), lower(trim(json_extract(o.payload,'$.channel'))) FROM works w "
            "JOIN offers o ON o.work_id=w.id AND o.active=1 WHERE w.id IN (%s)" % ','.join('?' * len(ok)), ok):
        if ch in kc._kids_channels() or not kc.word_blocked(otitle):
            return True
    return False


class ChunkTests(Mixed):
    def test_old_episode_found_in_later_chunk(self):
        self.series('show:alt', 'WUMMS', [(1, 'KiKA', ['Kinder'], 'Alt %d'), (250, 'ARD', ['Krimi'], 'Neu %d')])
        self.series('show:nichts', 'Nachtkrimi', [(1, 'ARD', ['Kinder'], 'Alt %d'), (250, 'ARD', ['Krimi'], 'Neu %d')])
        with self.db() as c:
            query = kc._work_query(c)
            before = kc.HAS_EPISODE_CHUNK_GROWTH[0]
            for show in ('show:alt', 'show:nichts'):
                for basis in ('gemischt', 'jugend', 'anteil'):
                    self.assertEqual(kc._has_episode(c, show, basis, query), full_answer(c, show, basis), (show, basis))
            self.assertTrue(kc._has_episode(c, 'show:alt', 'gemischt', kc._work_query(c)))
            self.assertGreater(kc.HAS_EPISODE_CHUNK_GROWTH[0], before)       # wirklich über das erste Stück hinaus

    def test_sample_reads_only_sample(self):
        self.series('show:gross', 'Die Sendung mit der Maus', [(300, 'Das Erste', ['Kinder'], 'Maus %d')])
        with self.db() as c:
            query = kc._work_query(c)
            self.assertEqual(kc.show_basis(c, 'show:gross', query=query), 'reihe')
            kc._work_rows(c, 'show:gross', kc.SHOW_SAMPLE, query)
            self.assertNotIn(('facts', 'show:gross'), query[2])
            self.assertTrue(kc._has_episode(c, 'show:gross', 'reihe', query))
            self.assertLessEqual(query[2].get(('read', 'show:gross'), 0), kc.SHOW_SAMPLE)

    def test_blocked_or_no_basis(self):
        self.series('show:b', 'Bluey', [(2, 'KiKA', [], 'Bluey %d')])
        with self.db() as c:
            self.assertFalse(kc._has_episode(c, 'show:b', None, kc._work_query(c)))
            self.assertTrue(kc._has_episode(c, 'show:b', 'gemischt', kc._work_query(c)))
            import kids_rules
            kids_rules.ensure(c)
            c.execute("INSERT OR REPLACE INTO kids_choices(key, choice) VALUES ('show:show:b', 'block')")
            self.assertFalse(kc._has_episode(c, 'show:b', 'gemischt', kc._work_query(c)))


if __name__ == '__main__':
    unittest.main()
