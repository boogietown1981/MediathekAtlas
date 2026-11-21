"""0.6.77: Nachtdiagnose 21.11.2026 (M3, 0.6.56) und Mac-Abfrage Runde 3.

- „BR Retro“/„Wir in Bayern“: 1.438 vollständige Archivclips (1–9 min) als „vielleicht nur Kurzformat“ gegen die
  Senderlaufzeit von 28 min markiert. → Sendung aus Kurzclips: Beitrag, Markierung einmalig zurücknehmen.
- Wikidata-Vorschläge von vor 0.6.58 („Malik Harris“ als Film) blockierten 6.121 Werke ohne Art.
- KiKA „stark!“ (514 Werke) hing an IMDb „Stark“, einer 3-teiligen Miniserie von 1993.
"""
import json
import sqlite3
import threading
import time
import unittest
from unittest import mock

import catalog
import catalog_service
import imdb_archive
import matching
import test_v0675 as base
import video_causality

STAMP_2026 = 1782086400


def database():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(catalog.SCHEMA)
    return c


def add(c, show, durations, topic='BR Retro', kind='series'):
    catalog.ingest(c, [{'title': '%s Clip %d' % (topic, i), 'topic': topic, 'duration': d, 'channel': 'BR',
                        'description': 'x' * 60 + '%s%d' % (topic, i), 'url_video': 'https://example.org/%s%d.mp4' % (show, i),
                        'timestamp': STAMP_2026} for i, d in enumerate(durations)])
    c.execute("UPDATE works SET show_key=?,kind=? WHERE show_key=''", (show, kind))


class ClipShow(unittest.TestCase):
    def test_sendung_of_short_clips(self):
        c = database()
        add(c, 'retro', [60 * m for m in (1, 2, 3, 4, 5, 6, 7, 8, 9, 3, 2, 4)])
        self.assertTrue(video_causality.clip_show(c, 'retro', 1680))
        # an ordinary 28-minute series with a few short extras stays a series
        add(c, 'serie', [1680] * 9 + [120, 180, 240], topic='Serie')
        self.assertIsNone(video_causality.clip_show(c, 'serie', 1680))
        # too few offers
        add(c, 'klein', [120, 180, 240], topic='Klein')
        self.assertIsNone(video_causality.clip_show(c, 'klein', 1680))
        self.assertIsNone(video_causality.clip_show(c, 'retro', None))

    def test_flagged_clips_are_filed_once(self):
        path_db = database()
        add(path_db, 'retro', [60 * m for m in (1, 2, 3, 4, 5, 6, 7, 8, 9, 3, 2, 4)])
        add(path_db, 'serie', [1680] * 9 + [120, 180, 240], topic='Serie')
        for row in path_db.execute('SELECT * FROM works').fetchall():
            m = json.loads(row['meta'])
            m.update(kind='series', title=row['topic'] or 'x', provider='ARD Mediathek', reference_id='crid', video_role='short_excerpt_suspected',
                     video_role_needs_review=True, expected_runtime_seconds=1680,
                     expected_runtime_source='ARD Mediathek · Serienlaufzeit', episode_verified=False)
            path_db.execute("UPDATE works SET state='identified',meta=? WHERE id=?", (json.dumps(m), row['id']))

        class Ctx:
            def __enter__(self_):return path_db
            def __exit__(self_, *a):path_db.commit()
        svc = catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None)
        svc.refile_clip_shows()
        rows = path_db.execute("SELECT show_key,state,json_extract(meta,'$.format_rule') r,json_extract(meta,'$.video_role_needs_review') f FROM works").fetchall()
        retro = [r for r in rows if r['show_key'] == 'retro']
        self.assertTrue(retro and all(r['state'] == 'format' and r['r'] == 'clip_show_v0677' and not r['f'] for r in retro))
        self.assertTrue(all(r['state'] == 'identified' for r in rows if r['show_key'] == 'serie'))
        self.assertTrue(catalog.get_state(path_db, 'clip_shows_v0677', False))


class OldWikidata(unittest.TestCase):
    def test_unstamped_unknown_type_is_weak(self):
        old = {'provider': 'Wikidata', 'kind': 'movie', 'title': 'Malik Harris', 'similarity': 1.0,
               'evidence_type': 'unknown_type', 'confidence': 'possible'}
        src = {'title': 'Malik Harris', 'duration': 3600}
        self.assertTrue(catalog.suggestion_weak(old, src, 'Musik'))
        self.assertFalse(catalog.suggestion_weak({**old, 'wikidata_rev': 2}, src, 'Musik'))     # filtered since 0.6.58
        self.assertFalse(catalog.suggestion_weak({**old, 'evidence_type': 'correct_type'}, src, 'Musik'))


class OldMiniseries(base.Base):
    def setUp(self):
        extra = ['tt0108215\ttvMiniSeries\tStark\tStark\t0\t1993\t1993\t50\tDrama',
                 'tt0108216\ttvEpisode\tTeil 1\tTeil 1\t0\t1993\t\\N\t50\tDrama']
        original = base.rows
        def rows():
            data = original()
            data['basics'] = data['basics'] + extra
            data['episode'] = data['episode'] + ['tt0108216\ttt0108215\t1\t1']
            return data
        with mock.patch.object(base, 'rows', rows):
            super().setUp()

    def test_title_alone_does_not_take_an_old_miniseries(self):
        src = {'title': 'Nathan - Klima schützen mit Zahlen', 'topic': 'stark!', 'duration': 896, 'timestamp': STAMP_2026}
        meta = {**catalog.seed(src), 'kind': 'series', 'title': 'stark!'}
        cands = [x for x in self.archive.candidates(src, meta) if x['reference_id'] == 'tt0108215']
        self.assertEqual(len(cands), 1)
        self.assertTrue(cands[0]['identity_contradicted'])
        self.assertIsNone(matching.choose(meta, cands, work_only=True))
        self.assertTrue(self.archive.old_miniseries('tt0108215', year=2026))
        self.assertFalse(self.archive.old_miniseries('tt0108215', year=2000))
        self.assertFalse(self.archive.old_miniseries('tt0862592', year=2026))     # a series, not a miniseries

    def test_existing_identities_are_reset_once(self):
        c = database()
        add(c, 'stark', [896] * 3, topic='stark!')
        for row in c.execute('SELECT * FROM works').fetchall():
            m = json.loads(row['meta'])
            m.update(kind='series', title='stark!', provider='IMDb Offline', reference_id='tt0108215', year=1993, episode_verified=False)
            c.execute("UPDATE works SET state='identified',meta=? WHERE id=?", (json.dumps(m), row['id']))

        class Ctx:
            def __enter__(self_):return c
            def __exit__(self_, *a):c.commit()
        svc = catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None)
        with mock.patch.object(imdb_archive, 'ACTIVE', self.archive):
            svc.reset_old_miniseries()
        rows = c.execute("SELECT state,json_extract(meta,'$.reference_id') ref FROM works").fetchall()
        self.assertTrue(rows and all(r['state'] == 'pending' and r['ref'] != 'tt0108215' for r in rows))
        self.assertTrue(catalog.get_state(c, 'imdb_miniseries_v0677', False))


if __name__ == '__main__':
    unittest.main()
