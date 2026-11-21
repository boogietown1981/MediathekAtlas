"""0.6.85: Mac-Prüfung 0.6.84 (21.11.2026).

- Planet Schule, Rest: Werke mit der Portal-Identität unter anderem oder leerem Thema („Sarah Baatout … · Women of
  Science“ TVDB 461332 matched, „Rafik Schami · Der Erzähler“ ARD „Planet Schule“).
- clip_sendung_v0683 traf Kurzserien: JoNaLu-Minis (Vorschul-Zeichentrick, Sender „ZDF“, ohne Genre), ARTE
  „Alte Schachteln aus Belgien“ (Rubrik „Kurz und witzig“), „Erklär’s mir“ (Planet Schule). Ein Beitrag gehört zu
  einer Sendung mit ganzen Ausgaben; schon abgelegte Fälle werden zurückgenommen.
"""
import json
import sqlite3
import threading
import time
import unittest

import catalog
import catalog_service
from tests.test_v0683 import Worker, offer


class ShortSeries(Worker):
    def test_short_series_without_whole_editions_stay_series(self):
        jonalu = self.clips('JoNaLu-Minis', 24, channel='ZDF', ref='jn')
        self.only_due(jonalu[0]);self.run_once()
        self.assertEqual(self.work(jonalu[0])[0], 'identified')
        self.assertEqual(self.svc.episode_segments, 0)

    def test_fiction_rubric_never_qualifies(self):
        src = {'title': 'Die Erbschaft', 'topic': 'Fernsehfilme und Serien - Kurz und witzig', 'duration': 180, 'channel': 'ARTE.DE'}
        self.assertFalse(catalog.clip_sendung_offer({'kind': 'series'}, src))
        self.assertFalse(catalog.clip_sendung_offer({'kind': 'series'}, dict(src, topic='planet schule')))
        self.assertTrue(catalog.clip_sendung_offer({'kind': 'series'}, dict(src, topic='Hallo Niedersachsen')))

    def file_as_clip(self, ids):
        with self.db() as c:
            for wid in ids:
                row = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
                src = json.loads(c.execute('SELECT payload FROM offers WHERE work_id=?', (wid,)).fetchone()[0])
                self.assertTrue(catalog.mark_recurring_edition(c, row, json.loads(row['meta']), src, 'segment', 'clip_sendung_v0683'))

    def test_filed_short_series_are_taken_back_magazine_clips_stay(self):
        jonalu = self.clips('JoNaLu-Minis', 22, channel='ZDF', ref='jn')
        hn = self.clips('Hallo Niedersachsen', 22)
        self.add(offer('Hallo Niedersachsen', 'Hallo Niedersachsen', 'hn-full', 1800), 'Hallo Niedersachsen')
        self.file_as_clip(jonalu + hn)
        self.svc.undo_clip_sendung()
        states = lambda ids: {self.work(w)[0] for w in ids}
        self.assertEqual(states(jonalu), {'identified'})
        self.assertEqual(states(hn), {'format'})
        m = self.work(jonalu[0])[1]
        self.assertNotIn('format_rule', m);self.assertEqual(m['format_undone'], 'v0685')
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'clip_sendung_undo_v0685')['works'], 22)
            # back in the episode queue, and not filed again by the „Sendung with editions“ rule
            self.assertIsNotNone(c.execute('SELECT 1 FROM episode_queue WHERE work_id=?', (jonalu[0],)).fetchone())
        self.only_due(jonalu[0]);self.run_once()
        self.assertEqual(self.work(jonalu[0])[0], 'identified')


class PortalOtherTopic(unittest.TestCase):
    def test_portal_identity_under_other_or_empty_topic(self):
        c = sqlite3.connect(':memory:', check_same_thread=False);c.row_factory = sqlite3.Row;c.executescript(catalog.SCHEMA)
        rows = [('Sarah Baatout, leitende Radiobiologin aus Belgien · Women of Science', '', 'matched',
                 {'provider': 'TVDB', 'reference_id': '461332', 'episode_verified': True, 'title': 'Planet Schule'}),
                ('Rafik Schami · Der Erzähler', 'Deutsch', 'identified', {'provider': 'ARD Mediathek', 'title': 'Planet Schule'}),
                ('Féminin ou masculin?', '', 'identified', {'provider': 'ARD Mediathek', 'title': 'Planet Schule'}),
                ('Zecken · im Garten', 'Servicezeit', 'identified', {'provider': 'ARD Mediathek', 'title': 'Servicezeit'})]
        catalog.ingest(c, [{'title': t, 'topic': topic, 'duration': 900, 'channel': 'SWR', 'description': 'x' * 60 + t,
                            'url_video': 'https://example.org/%d.mp4' % i, 'timestamp': 1782086400} for i, (t, topic, _, _) in enumerate(rows)])
        for t, _, state, extra in rows:
            wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')=?", (t,)).fetchone()[0]
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0]);m.update(kind='series', **extra)
            c.execute('UPDATE works SET kind=?,title=?,state=?,meta=? WHERE id=?', ('series', extra['title'], state, json.dumps(m), wid))

        class Ctx:
            def __enter__(self_):return c
            def __exit__(self_, *a):c.commit()
        catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None).reseed_portal()
        out = {r['t']: (r['title'], r['state']) for r in c.execute(
            "SELECT w.title,w.state,json_extract(o.payload,'$.title') t FROM works w JOIN offers o ON o.work_id=w.id")}
        self.assertEqual(out[rows[0][0]], ('Women of Science', 'pending'))
        self.assertEqual(out[rows[1][0]], ('Der Erzähler', 'pending'))
        self.assertEqual(out[rows[2][0]], ('Planet Schule', 'identified'))      # no series in the title
        self.assertEqual(out[rows[3][0]], ('Servicezeit', 'identified'))        # not a portal
        self.assertTrue(catalog.get_state(c, 'portal_reseed_v0685', False))


if __name__ == '__main__':
    unittest.main()
