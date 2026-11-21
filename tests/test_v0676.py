"""0.6.76: Mac-Prüfung 0.6.75 (21.11.2026) nicht bestanden.

- Gesichter & Geschichten (tt23626090, IMDb nur „Episode dated …“, ohne Laufzeit): 727 ganze ~19-min-Ausgaben,
  nach dem Aufmacher benannt, fielen unter den 20-min-Rückfall und wurden Beiträge. → Ohne bekannte Ausgabenlänge
  (IMDb-Laufzeit oder längstes Angebot ≥ 30 min) gilt die längere Grenze nicht.
- Eisenbahn-Romantik nur +18: „Wolken, Wolle, Wales“ ↔ IMDb „Wolken, Wolle, Wales - Auf der Cambrian Line nach
  Aberystwyth“; „Dampfwolken über Osteuropa - Teil 1“ ↔ „Dampfwolken über Osteuropa 1“.
- Kennzeichnung der neuen Regel (K5): meta.format_rule = 'imdb_dated_v0676'.
"""
import gzip
import json
import sqlite3
import threading
import unittest
from unittest import mock

import catalog
import catalog_service
import imdb_archive
import test_v0675 as base

EXTRA_BASICS = [
    'tt23626090\ttvSeries\tGesichter & Geschichten\tGesichter & Geschichten\t0\t2005\t\\N\t\\N\tTalk-Show',
    'tt0450923\ttvSeries\tLandesschau Baden-Württemberg\tLandesschau Baden-Württemberg\t0\t1957\t\\N\t\\N\tNews',
]
EXTRA_EPISODES = []
for i, day in enumerate(base.DAYS):
    for prefix, parent in (('tt23', 'tt23626090'), ('tt45', 'tt0450923')):
        EXTRA_BASICS.append('%s%05d\ttvEpisode\tEpisode dated %s\tEpisode dated %s\t0\t2026\t\\N\t\\N\tTalk-Show' % (prefix, i, day, day))
        EXTRA_EPISODES.append('%s%05d\t%s\t\\N\t\\N' % (prefix, i, parent))
EISENBAHN = [('Wolken, Wolle, Wales - Auf der Cambrian Line nach Aberystwyth', 1001),
             ('Dampfwolken über Osteuropa 1', 1002),
             ('Rund um den Bodensee - Teil 2', 1003),           # subtitle with part number: never shortened
             ('Alpenbahnen im Winter - Die Gotthardstrecke', 1004),
             ('Alpenbahnen im Winter - Die Arlbergbahn', 1005)]  # shared main part: ambiguous


BASE_ROWS = base.rows


def rows():
    data = BASE_ROWS()
    data['basics'] = data['basics'] + EXTRA_BASICS
    data['episode'] = data['episode'] + EXTRA_EPISODES
    for i, (title, ep) in enumerate(EISENBAHN):
        data['basics'].append('tt39%05d\ttvEpisode\t%s\t%s\t0\t2024\t\\N\t30\tDocumentary' % (i, title, title))
        data['episode'].append('tt39%05d\ttt0346255\t1\t%d' % (i, ep))
    return data


class Base(base.Base):
    def setUp(self):
        with mock.patch.object(base, 'rows', rows):
            super().setUp()


class EditionLength(Base):
    def svc(self):
        return catalog_service.Service.__new__(catalog_service.Service)

    def db(self, longest):
        c = sqlite3.connect(':memory:');c.row_factory = sqlite3.Row
        c.executescript(catalog.SCHEMA)
        catalog.ingest(c, [{'title': 'Ausgabe %d' % d, 'topic': 'Sendung', 'duration': d, 'channel': 'SRF',
                            'description': 'x' * 60 + str(d), 'url_video': 'https://example.org/%d.mp4' % d}
                           for d in (700, 1149, longest)])
        c.execute("UPDATE works SET show_key='sendung'")
        return c, 'sendung'

    def test_without_runtime_the_longest_offer_decides(self):
        svc = self.svc()
        with mock.patch.object(imdb_archive, 'ACTIVE', self.archive):
            c, key = self.db(1537)                              # Gesichter & Geschichten: whole editions ~19–25 min
            self.assertIsNone(svc.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt23626090'}, c, key))
            self.assertIsNone(svc.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt23626090'}))
            c, key = self.db(2700)                              # a 45-minute Landesschau edition in the catalogue
            svc2 = self.svc()
            self.assertEqual(svc2.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt0450923'}, c, key), 1200)
            self.assertEqual(svc2.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt0862592'}, c, key), 1200)  # IMDb 120 min

    def test_rule_marker(self):
        self.assertEqual(catalog.dated_rule('segment', {'duration': 964}, 1200), 'imdb_dated_v0676')
        self.assertIsNone(catalog.dated_rule('segment', {'duration': 400}, 1200))      # 0.6.41 bound alone
        self.assertIsNone(catalog.dated_rule('segment', {'duration': 964}, None))
        self.assertIsNone(catalog.dated_rule('edition', {'duration': 964}, 1200))
        c = sqlite3.connect(':memory:');c.row_factory = sqlite3.Row;c.executescript(catalog.SCHEMA)
        catalog.ingest(c, [{'title': 'Rezept: Torte', 'topic': 'Kaffee oder Tee?', 'duration': 964, 'channel': 'SWR',
                            'description': 'x' * 70, 'url_video': 'https://example.org/t.mp4'}])
        row = c.execute('SELECT * FROM works').fetchone()
        m = {**json.loads(row['meta']), 'kind': 'series', 'title': 'Kaffee oder Tee?'}
        c.execute("UPDATE works SET state='identified' WHERE id=?", (row['id'],))
        self.assertTrue(catalog.mark_recurring_edition(c, row, m, {'title': 'Rezept: Torte', 'duration': 964}, 'segment', 'imdb_dated_v0676'))
        self.assertEqual(json.loads(c.execute('SELECT meta FROM works').fetchone()[0])['format_rule'], 'imdb_dated_v0676')


class Eisenbahn(Base):
    def test_offer_without_subtitle_and_part_word(self):
        for title, ep in (('Wolken, Wolle, Wales', 1001), ('Dampfwolken über Osteuropa - Teil 1', 1002),
                          ('Wolken, Wolle, Wales - Auf der Cambrian Line nach Aberystwyth', 1001)):
            with self.subTest(title=title):
                chosen = self.match(title, 'Eisenbahn-Romantik', 'tt0346255')
                self.assertIsNotNone(chosen)
                self.assertEqual(chosen['episode'], ep)

    def test_guards(self):
        self.assertIsNone(self.match('Rund um den Bodensee', 'Eisenbahn-Romantik', 'tt0346255'))     # "- Teil 2"
        self.assertIsNone(self.match('Alpenbahnen im Winter', 'Eisenbahn-Romantik', 'tt0346255'))    # two episodes
        self.assertIsNone(self.match('Dampfwolken über Osteuropa - Teil 2', 'Eisenbahn-Romantik', 'tt0346255'))
        self.assertIsNone(self.match('Wolken', 'Eisenbahn-Romantik', 'tt0346255'))                   # too short
        self.assertIsNone(self.match('Wolken, Wolle, Wales', 'Eisenbahn-Romantik', 'tt0346255', duration=200))


if __name__ == '__main__':
    unittest.main()
