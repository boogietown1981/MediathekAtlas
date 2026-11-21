"""0.6.75: Mac-Abfrage Runde 3 (21.11.2026, Kopie nach 0.6.74).

- Kaffee oder Tee? (tt0862592, 1.848 offen), Landesschau Baden-Württemberg (tt0450923, 1.475), DER TAG in Berlin &
  Brandenburg (tt30028600, 800): IMDb führt jede Folge als „Episode dated …“ ohne Staffel/Nummer; die Mediathek
  bietet 8–17-minütige Beiträge mit Thementitel („Rezept: Kürbis-Motivtorte“, 964 s). → Beitrag der Sendung.
- Eisenbahn-Romantik (tt0346255, 428 offen): IMDb-Titel „1092. Mit dem Schienenbus an den Bodensee - …“ bzw.
  „1090 Mit der Nordlandsbahn …“, Mediathek ohne die laufende Nummer. → exakter Abgleich ohne Nummer.
"""
import gzip
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import catalog
import catalog_service
import imdb_archive
import matching

DAYS = ['%d %s 2026' % (d, m) for m in ('January', 'February', 'March') for d in range(1, 21)]


def rows():
    basics = ['tt0862592\ttvSeries\tKaffee oder Tee?\tKaffee oder Tee?\t0\t2000\t\\N\t120\tTalk-Show',
              'tt0346255\ttvSeries\tEisenbahn-Romantik\tEisenbahn-Romantik\t0\t1991\t\\N\t30\tDocumentary',
              'tt5000000\ttvSeries\tKrimi am Abend\tKrimi am Abend\t0\t2010\t\\N\t45\tCrime',
              'tt5100000\ttvSeries\tFußball-Chronik\tFußball-Chronik\t0\t2010\t\\N\t30\tSport']
    episode = []
    for i, day in enumerate(DAYS):
        basics.append('tt86%05d\ttvEpisode\tEpisode dated %s\tEpisode dated %s\t0\t2026\t\\N\t\\N\tTalk-Show' % (i, day, day))
        episode.append('tt86%05d\ttt0862592\t\\N\t\\N' % i)
    names = ['Mit dem Schienenbus an den Bodensee - Der Rote Flitzer auf großer Fahrt', 'Mit der Nordlandsbahn über den Polarkreis',
             'Die Pilatusbahn', 'Die Pilatusbahn']                       # the last name twice: ambiguous, never chosen
    for i in range(1, 30):
        name = names[i - 1] if i <= len(names) else 'Strecke Nummer %d' % i
        title = ('%d. %s' if i % 2 else '%d %s') % (1060 + i, name)
        basics.append('tt34%05d\ttvEpisode\t%s\t%s\t0\t2025\t\\N\t30\tDocumentary' % (i, title, title))
        episode.append('tt34%05d\ttt0346255\t1\t%d' % (i, 1060 + i))
    for i in range(1, 61):                                              # a scripted series with named episodes
        basics.append('tt50%05d\ttvEpisode\tFall %d\tFall %d\t0\t2012\t\\N\t45\tCrime' % (i, i, i))
        episode.append('tt50%05d\ttt5000000\t%d\t%d' % (i, 1 + i // 20, 1 + i % 20))
    # only one running-numbered title: "1. FC Köln" is no numbering convention
    basics.append('tt5100001\ttvEpisode\t1. FC Köln\t1. FC Köln\t0\t2012\t\\N\t30\tSport')
    episode.append('tt5100001\ttt5100000\t1\t1')
    return {'basics': basics, 'ratings': ['tt0862592\t6.0\t10'], 'episode': episode, 'akas': ['tt0862592\t1\tKaffee oder Tee?\tDE\tde\t\\N\t\\N\t0'],
            'crew': ['tt0862592\t\\N\t\\N'], 'principals': ['tt0862592\t1\tnm1\tself\t\\N\t\\N'],
            'people': ['nm1\tJemand\t\\N\t\\N\tself\ttt0862592']}


def build(root):
    files = {}
    for kind, data in rows().items():
        path = root / (kind + '.gz')
        path.write_bytes(gzip.compress(('\t'.join(imdb_archive.HEADERS[kind]) + '\n' + '\n'.join(data) + '\n').encode()))
        files[kind] = path
    archive = imdb_archive.Archive(root, threading.Event())
    imdb_archive.build(archive.path, files)
    return imdb_archive.Archive(root, threading.Event())


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.archive = build(self.root)

    def tearDown(self):
        opened = getattr(self.archive._reader_local, 'opened', None)
        if opened:
            opened[1].close()

    def match(self, title, topic, ref, duration=1790, **kw):
        src = {'title': title, 'topic': topic, 'duration': duration, 'timestamp': 1782086400}
        m = {**catalog.seed(src), 'kind': 'series', 'title': topic, 'provider': 'IMDb Offline', 'reference_id': ref,
             'episode_verified': False, 'season': None, 'episode': None, **kw}
        return matching.choose(m, self.archive.episode_evidence(src, m)['candidates'])


class RunningNumbers(Base):
    def test_title_without_running_number_is_matched(self):
        for title, ep in (('Mit dem Schienenbus an den Bodensee - Der Rote Flitzer auf großer Fahrt', 1061),
                          ('Mit der Nordlandsbahn über den Polarkreis', 1062),
                          ('Eisenbahn-Romantik: Mit der Nordlandsbahn über den Polarkreis', 1062)):
            with self.subTest(title=title):
                chosen = self.match(title, 'Eisenbahn-Romantik', 'tt0346255')
                self.assertIsNotNone(chosen)
                self.assertEqual((chosen['season'], chosen['episode']), (1, ep))

    def test_guards(self):
        self.assertIsNone(self.match('Die Pilatusbahn', 'Eisenbahn-Romantik', 'tt0346255'))            # two episodes
        self.assertIsNone(self.match('Eisenbahn-Romantik', 'Eisenbahn-Romantik', 'tt0346255'))         # series name
        self.assertIsNone(self.match('Mit der Nordlandsbahn', 'Eisenbahn-Romantik', 'tt0346255'))      # not exact
        self.assertIsNone(self.match('Mit der Nordlandsbahn über den Polarkreis', 'Eisenbahn-Romantik', 'tt0346255',
                                     duration=200))                                                    # short clip
        self.assertIsNone(self.match('FC Köln', 'Fußball-Chronik', 'tt5100000'))                       # no convention
        self.assertEqual(imdb_archive.running_free('1914 - 1950'), '')
        self.assertEqual(imdb_archive.running_free('1090 Mit der Nordlandsbahn'), 'Mit der Nordlandsbahn')

    def test_series_flags(self):
        self.assertTrue(self.archive.running_numbered_series('tt0346255'))
        self.assertFalse(self.archive.running_numbered_series('tt5100000'))
        self.assertEqual(self.archive.dated_format('tt0862592'), (True, 7200))
        self.assertFalse(self.archive.dated_format('tt5000000')[0])     # scripted series with 60 named episodes
        self.assertFalse(self.archive.dated_format('tt0346255')[0])


class DatedSendung(Base):
    def service(self):
        svc = catalog_service.Service.__new__(catalog_service.Service)
        return svc

    def test_clip_limit_only_for_dated_imdb_sendung(self):
        svc = self.service()
        with mock.patch.object(imdb_archive, 'ACTIVE', self.archive):
            self.assertEqual(svc.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt0862592'}), 1200)
            self.assertIsNone(svc.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt5000000'}))
            self.assertIsNone(svc.dated_clip_limit({'provider': 'TMDB', 'reference_id': '278918'}))
        with mock.patch.object(imdb_archive, 'ACTIVE', None):
            self.assertIsNone(svc.dated_clip_limit({'provider': 'IMDb Offline', 'reference_id': 'tt0862592'}))

    def role(self, title, duration, clip=1200, sendung=True, **meta):
        return catalog.recurring_edition({'kind': 'series', 'title': 'Kaffee oder Tee?', **meta},
                                         {'title': title, 'topic': 'Kaffee oder Tee?', 'duration': duration,
                                          'timestamp': 1782086400}, sendung, clip)

    def test_contributions_and_editions(self):
        self.assertEqual(self.role('Rezept: Kürbis-Motivtorte', 964), 'segment')
        self.assertEqual(self.role('Nikoläuse und Tannenbäume aus Lebkuchen', 555), 'segment')
        self.assertEqual(self.role('Kaffee oder Tee?', 6900), 'edition')
        self.assertIsNone(self.role('Ein langes Gespräch über das Leben', 3600))         # whole length: no claim
        self.assertIsNone(self.role('Rezept: Kürbis-Motivtorte (S2026/E12)', 964))       # numbered: never
        self.assertIsNone(self.role('Rezept: Kürbis-Motivtorte', 964, episode_verified=True))
        self.assertIsNone(self.role('Rezept: Kürbis-Motivtorte', 964, scan_requested=True))
        # without the IMDb evidence the 10-minute bound of 0.6.41 stays
        self.assertIsNone(self.role('Rezept: Kürbis-Motivtorte', 964, clip=600))

    def test_waiting_entries_of_covered_series_are_due_again(self):
        path = self.root / 'catalog.db'
        def db():
            c = sqlite3.connect(path, timeout=30)
            c.row_factory = sqlite3.Row
            return c
        with db() as c:
            c.executescript(catalog.SCHEMA)
            catalog.ingest(c, [{'title': t, 'topic': topic, 'duration': 900, 'channel': 'SWR', 'description': 'x' * 60 + t,
                                'url_video': 'https://example.org/%d.mp4' % i, 'timestamp': 1782086400}
                               for i, (t, topic) in enumerate((('Rezept: Torte', 'Kaffee oder Tee?'),
                                                               ('Die Pilatusbahn', 'Eisenbahn-Romantik'),
                                                               ('Fall 3', 'Krimi am Abend')))])
            refs = {'Kaffee oder Tee?': 'tt0862592', 'Eisenbahn-Romantik': 'tt0346255', 'Krimi am Abend': 'tt5000000'}
            for row in c.execute('SELECT * FROM works').fetchall():
                m = json.loads(row['meta']);topic = json.loads(c.execute('SELECT payload FROM offers WHERE work_id=?', (row['id'],)).fetchone()[0])['topic']
                m.update(kind='series', title=topic, provider='IMDb Offline', reference_id=refs[topic], episode_verified=False)
                c.execute("UPDATE works SET kind='series',state='identified',title=?,meta=? WHERE id=?", (topic, json.dumps(m), row['id']))
            c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=?", (time.time() + 7 * 86400,))
            catalog.set_state(c, 'refile_reset_v0673', True)        # update from 0.6.73/0.6.74
        stop = threading.Event();self.addCleanup(stop.set)
        svc = catalog_service.Service(db, lambda: {}, stop, self.root)
        with mock.patch.object(imdb_archive, 'ACTIVE', self.archive):
            svc.refile_loop()
        with db() as c:
            due = {r[0] for r in c.execute("""SELECT json_extract(w.meta,'$.title') FROM episode_queue q JOIN works w ON w.id=q.work_id
                                               WHERE q.next_try=0""")}
            self.assertEqual(due, {'Kaffee oder Tee?', 'Eisenbahn-Romantik'})
            self.assertTrue(catalog.get_state(c, 'refile_reset_v0675', False))

    def test_no_marker_without_archive(self):
        path = self.root / 'c2.db'
        def db():
            c = sqlite3.connect(path, timeout=30);c.row_factory = sqlite3.Row;return c
        with db() as c:c.executescript(catalog.SCHEMA)
        stop = threading.Event();self.addCleanup(stop.set)
        svc = catalog_service.Service(db, lambda: {}, stop, self.root)
        with mock.patch.object(imdb_archive, 'ACTIVE', None):
            svc.refile_loop()
        with db() as c:self.assertFalse(catalog.get_state(c, 'refile_reset_v0675', False))


if __name__ == '__main__':
    unittest.main()
