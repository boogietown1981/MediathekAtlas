"""0.6.68 (Mac-Gegenprüfung 0.6.65, Daten der Testkopie vom 21.11.2026): Trefferquote der Folgensuche.

* Ausgaben mit Tag ohne Jahr („buten un binnen vom 23. Oktober“) sind Ausgaben, wenn der Tag der Sendetag ist.
* Gesprächssendungen nach Gast („THADEUSZ lang & breit - Gast: …“, 39 von 39 Stichproben ohne Treffer).
* Schon geprüfte Werke, die diese Regeln jetzt abdecken, werden sofort wieder fällig statt in 7–31 Tagen.
* Die 18 BR24-Beiträge mit Kurzvideo-Hinweis werden ebenfalls wieder abgelegt.
* „wartet auf das IMDb-Offline-Archiv“ steht auch ohne laufende Prüfung im Protokoll.
"""
import calendar
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import catalog, imdb_archive  # noqa: E402
from test_v0658 import Fixture  # noqa: E402

SERIES = {'kind': 'series', 'title': 'buten un binnen | regionalmagazin', 'reference_id': 'crid1', 'provider': 'ARD Mediathek'}
TALK = {'kind': 'series', 'title': 'THADEUSZ lang & breit', 'reference_id': 'crid2', 'provider': 'ARD Mediathek'}


def offer(title, topic, day, duration=1700):
    return {'title': title, 'topic': topic, 'duration': duration,
            'timestamp': calendar.timegm(time.strptime(day, '%Y-%m-%d')) + 18 * 3600}


class EditionRules(unittest.TestCase):
    def test_day_without_year_is_an_edition_on_its_broadcast_day(self):
        topic = SERIES['title']
        for title, day in (('buten un binnen vom 23. Oktober', '2026-10-23'),
                           ('buten un binnen mit Sportblitz vom 25. Oktober', '2026-10-25'),
                           ('buten un binnen vom 23.10.', '2026-10-23'),
                           ('buten un binnen vom Freitag, 31. Dezember', '2027-01-02')):
            self.assertEqual(catalog.recurring_edition(SERIES, offer(title, topic, day)), 'edition', title)

    def test_day_without_year_needs_the_broadcast_day_and_the_sendung(self):
        topic = SERIES['title']
        self.assertIsNone(catalog.recurring_edition(SERIES, offer('buten un binnen vom 23. Oktober', topic, '2026-11-20')))
        drama = {'kind': 'series', 'title': 'Weissensee', 'reference_id': 'tt1', 'provider': 'IMDb Offline'}
        # A scripted episode named after a day, even if shown on that day, is no edition
        self.assertIsNone(catalog.recurring_edition(drama, offer('Die Nacht vom 9. November', 'Weissensee', '2026-11-09', 2900)))
        self.assertIsNone(catalog.recurring_edition(SERIES, offer('buten un binnen vom 23. Oktober (Folge 3)', topic, '2026-10-23')))

    def test_talk_show_guest_titles_are_editions(self):
        topic = TALK['title']
        for title in ('THADEUSZ lang & breit - Gast: Dr. Emily Haber',
                      'THADEUSZ lang & breit – Zu Gast: Serap Güler (Staatsministerin im Auswärtigen Amt)',
                      'THADEUSZ lang & breit - Zu  Gast: Christiane Hoffmann (ehemalige Journalistin)',
                      'THADEUSZ lang & breit: Britische Autorin Jacinta Nandi ist zu Gast'):
            self.assertEqual(catalog.recurring_edition(TALK, offer(title, topic, '2026-05-19', 3400)), 'edition', title)

    def test_guest_rule_needs_the_own_sendung_name(self):
        drama = {'kind': 'series', 'title': 'Der Gast', 'reference_id': 'tt2', 'provider': 'IMDb Offline'}
        self.assertIsNone(catalog.recurring_edition(drama, offer('Folge 2: Der Gast', 'Der Gast', '2026-05-19', 2900)))
        other = {'kind': 'series', 'title': 'Tatort', 'reference_id': 'tt3', 'provider': 'IMDb Offline'}
        self.assertIsNone(catalog.recurring_edition(other, offer('Sonntagsgast - Gast: Max', 'Tatort', '2026-05-19', 5400)))
        self.assertIsNone(catalog.recurring_edition(other, offer('Der ungebetene Gast', 'Tatort', '2026-05-19', 5400)))


class Requeue(Fixture):
    def test_checked_guest_editions_become_due_and_br24_clips_are_refiled(self):
        now = time.time()
        with self.db() as c:
            rows = c.execute('SELECT id,meta FROM works ORDER BY id').fetchall()
            for i, row in enumerate(rows):
                m = json.loads(row['meta'])
                if i < 4:     # talk show, checked before: waits 7 days
                    m.update(title='THADEUSZ lang & breit')
                    payload = {'title': 'THADEUSZ lang & breit - Gast: Person %d' % i, 'topic': 'THADEUSZ lang & breit',
                               'duration': 3400, 'timestamp': int(now)}
                    c.execute('UPDATE offers SET payload=? WHERE work_id=?', (json.dumps(payload), row['id']))
                    c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), row['id']))
                    c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=? WHERE work_id=?", (now + 7 * 86400, row['id']))
                elif i < 6:   # BR24 contributions: filed, set back, flagged as short clip -> out of the queue
                    m.update(state='format', format_grouping='segment', video_role_needs_review=True)
                    c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), row['id']))
                else:         # an ordinary episode that waits stays waiting
                    c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=? WHERE work_id=?", (now + 7 * 86400, row['id']))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue').fetchone()[0], 10)
        self.svc.refile_loop()
        with self.db() as c:
            due = c.execute('SELECT COUNT(*) FROM episode_queue WHERE next_try<=?', (time.time(),)).fetchone()[0]
            filed = c.execute("SELECT COUNT(*) FROM works WHERE state='format'").fetchone()[0]
            flags = [json.loads(r[0]).get('video_role_needs_review') for r in c.execute("SELECT meta FROM works WHERE state='format'")]
            self.assertTrue(catalog.get_state(c, 'refile_reset_v0668', False))
        self.assertEqual(due, 4)
        self.assertEqual(filed, 2)
        self.assertEqual(flags, [False, False])
        self.assertIn('episode_new_edition_rules_requeued', [e[0] for e in self.events])


class ArchiveWaitEvent(Fixture):
    def test_named_without_a_running_check(self):
        with patch.object(imdb_archive, 'ACTIVE', None):
            self.svc.note_archive_wait()
            self.svc.note_archive_wait()                   # once per hour
        self.assertEqual([e for e in self.events if e[0] == 'episode_waiting_for_imdb_archive'],
                         [('episode_waiting_for_imdb_archive', {'level': 'WARNING', 'archive': 'missing'})])


if __name__ == '__main__':
    unittest.main()
