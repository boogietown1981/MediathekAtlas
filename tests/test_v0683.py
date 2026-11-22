"""0.6.83: Mac-Abfrage Runde 4 (21.11.2026, Prüfkopie mit 0.6.80/0.6.81).

- Folgensuche: 99.533 Einträge „ohne Treffer“, davon nur 72 fällig – meist von älteren Versionen geparkt
  (logo! „vom Donnerstag, 4. Juni 2026“ ist heute eine Ausgabe). → einmal mit den heutigen Regeln fällig machen.
- „Hallo Niedersachsen“: 4.442 Beiträge von 1–4 Minuten ohne Treffer (kein Formatwort, keine IMDb-Folgenliste,
  keine Laufzeit zum Vergleich). → Sendung aus fast nur Kurzclips: Beitrag, nie bei Kinderprogrammen.
"""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import catalog
import catalog_service
import imdb_archive
from tests import test_v0624_episode_search as base


def offer(title, topic, tag, duration, channel='NDR', stamp=None):
    src = base.offer(title, topic, tag)
    src.update(duration=duration, channel=channel, timestamp=stamp or int(time.time()) - 86400)
    return src


class Worker(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name);self.path = self.root / 'catalog.db'
        self.archive = base.build_archive(self.root)
        self.addCleanup(self.close_archive)
        self.settings = lambda: {'auto_metadata': True, 'episode_workers': 2, 'metadata_workers': 2,
                                 'sender_direct_lookup': False, 'scan_priority': 'series_first', 'complete_series': False}
        with self.db() as c:c.executescript(catalog.SCHEMA)
        self.svc = catalog_service.Service(self.db, self.settings, threading.Event(), self.root)

    def close_archive(self):
        opened = getattr(self.archive._reader_local, 'opened', None)
        if opened:opened[1].close()

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=5);c.row_factory = sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def add(self, src, title, reference='278918', genres=None):
        with self.db() as c:
            catalog.ingest(c, [src])
            row = c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.url_video')=?",
                            (src['url_video'],)).fetchone()
            m = json.loads(row['meta'])
            m.update(kind='series', title=title, provider='TMDB', reference_id=reference, year=2001, episode_verified=False)
            if genres:m['genres'] = genres
            catalog.save_metadata(c, row['id'], m, 'identified')
            return row['id']

    def clips(self, series, n, duration=180, channel='NDR', genres=None, ref='278918'):
        return [self.add(offer('%s Bericht Nummer %s' % (series, chr(65 + i % 26) + chr(65 + i // 26)), series, '%s-%d' % (ref, i),
                               duration, channel), series, ref, genres) for i in range(n)]

    def work(self, wid):
        with self.db() as c:
            row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            return row['state'], json.loads(row['meta'])

    def only_due(self, wid):
        with self.db() as c:
            c.execute('UPDATE episode_queue SET next_try=?', (time.time() + 3600,))
            c.execute('UPDATE episode_queue SET next_try=0 WHERE work_id=?', (wid,))

    def run_once(self):
        with patch.object(imdb_archive, 'ACTIVE', self.archive):
            self.assertTrue(self.svc.metadata_once('episode'))


class ClipSendung(Worker):
    def test_clip_sendung_without_imdb_episodes_files_its_clips(self):
        ids = self.clips('Hallo Niedersachsen', 24)
        long = self.add(offer('Hallo Niedersachsen', 'Hallo Niedersachsen', 'hn-full', 1800), 'Hallo Niedersachsen')
        self.only_due(ids[0])
        self.run_once()
        state, m = self.work(ids[0])
        self.assertEqual((state, m['format_grouping'], m['format_rule']), ('format', 'segment', 'clip_sendung_v0683'))
        self.assertEqual((m['provider'], m['reference_id'], m['title']), ('TMDB', '278918', 'Hallo Niedersachsen'))
        self.assertFalse(m['episode_verified'])
        # the siblings follow in the same pass; the whole edition is no contribution
        self.assertEqual(sum(self.work(w)[0] == 'format' for w in ids), 24)
        self.assertEqual(self.work(long)[0], 'identified')
        self.assertGreaterEqual(self.svc.episode_segments, 24)

    def test_kids_programmes_and_mixed_sendungen_stay(self):
        kids = self.clips('Kleine Wolke', 24, channel='KiKA', ref='k1')
        genre = self.clips('Zeichenwelt', 24, genres=['Animation'], ref='k2')
        mixed = self.clips('Landesreport', 20, ref='m1') + [
            self.add(offer('Landesreport lang %d' % i, 'Landesreport', 'm1-long-%d' % i, 1800), 'Landesreport', 'm1') for i in range(5)]
        for wid in (kids[0], genre[0], mixed[0]):
            self.only_due(wid);self.run_once()
            self.assertEqual(self.work(wid)[0], 'identified')
        self.assertEqual(self.svc.episode_segments, 0)

    def test_numbered_clips_and_few_offers_never_qualify(self):
        with self.db() as c:
            self.assertFalse(catalog.clip_sendung_offer({'kind': 'series'}, {'title': 'Folge 3: Am Hafen', 'duration': 200}))
            self.assertFalse(catalog.clip_sendung_offer({'kind': 'series'}, {'title': 'Am Hafen', 'duration': 900}))
            self.assertFalse(catalog.clip_sendung_offer({'kind': 'series', 'episode': 4}, {'title': 'Am Hafen', 'duration': 200}))
            self.assertTrue(catalog.clip_sendung_offer({'kind': 'series'}, {'title': 'Am Hafen', 'topic': 'Hallo Niedersachsen', 'duration': 200}))
        few = self.clips('Kurzreport', 12, ref='f1')
        with self.db() as c:
            show = c.execute('SELECT show_key FROM works WHERE id=?', (few[0],)).fetchone()[0]
            self.assertFalse(catalog.clip_sendung_show(c, show))


class ParkedRequeue(Worker):
    def test_parked_entries_the_rules_now_file_are_due_again(self):
        stamp = int(time.mktime((2026, 6, 4, 19, 0, 0, 0, 0, -1)))
        logo = self.add(offer('logo! vom Donnerstag, 4. Juni 2026', 'logo!', 'logo1', 640, 'KiKA', stamp), 'logo!', 'logo-154')
        drama = self.add(offer('Das Erbe', 'Familie Sonnenfeld', 'fs1', 5400), 'Familie Sonnenfeld', '55')
        clips = self.clips('Hallo Niedersachsen', 22)
        self.add(offer('Hallo Niedersachsen', 'Hallo Niedersachsen', 'hn-full', 1800), 'Hallo Niedersachsen')  # 0.6.85: whole edition
        future = time.time() + 20 * 86400
        with self.db() as c:
            c.execute("UPDATE episode_queue SET last_outcome='unresolved',next_try=?", (future,))
        self.svc.requeue_parked()
        with self.db() as c:
            due = {r[0]: r[1] for r in c.execute('SELECT work_id,next_try FROM episode_queue')}
            self.assertTrue(catalog.get_state(c, 'parked_requeue_v0683', False))
        self.assertLess(due[logo], time.time() + 3601)
        self.assertTrue(all(due[w] < time.time() + 3601 for w in clips))
        self.assertEqual(due[drama], future)
        # once only
        with self.db() as c:c.execute('UPDATE episode_queue SET next_try=?', (future,))
        self.svc.requeue_parked()
        with self.db() as c:
            self.assertEqual(c.execute('SELECT MIN(next_try) FROM episode_queue').fetchone()[0], future)


if __name__ == '__main__':
    unittest.main()
