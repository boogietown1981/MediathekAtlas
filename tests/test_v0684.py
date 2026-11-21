"""0.6.84: Mac-Prüfung 0.6.82 (21.11.2026) – Planet Schule unverändert.

portal_reseed lief (257 Werke), aber 3 s später standen die Werke wieder unter „planet schule“ (ARD Mediathek):
die Serienvorlage (series_templates) für das Thema „planet schule“ gab jedem neu zu erkennenden Werk die
Portal-Identität (series_template_candidate), propagate_series trug sie auf alle Werke der Reihe („Natur nah“,
Begründung „Reihe aus dem Titel …“ blieb stehen), die Folgensuche legte 145 als „Beitrag der Sendung „planet schule““
ab. Dieser Test schickt Werke mit ARD-Sendereihe „planet schule“ durch den ganzen Weg: Heilung, Erkennung mit
Vorlage, ARD-Seite und TVDB-Portaltreffer, Weitergabe an die Reihe, Folgensuche und Neuimport.
"""
import json
import time
import unittest
from unittest.mock import patch

import broadcaster
import catalog
import catalog_service
import core
import imdb_archive
from test_broadcaster import ard_page
from tests.test_v0683 import Worker

ARD = {'kind': 'series', 'title': 'planet schule', 'provider': 'ARD Mediathek', 'reference_id': 'Y3JpZDovL3N3ci5kZS8yNTgyNzUw',
       'year': None, 'genres': [], 'genre_source': 'Sender (abgeleitet)', 'poster': '', 'episode_verified': False}
PORTAL_TVDB = {'kind': 'series', 'title': 'Planet Schule', 'provider': 'TVDB', 'reference_id': '461332', 'year': 2009,
               'similarity': 1.0, 'confidence': 'high', 'year_mismatch': False, 'episode_verified': False,
               'season': None, 'episode': None, 'genres': [], 'poster': ''}
STAMP = 1782086400


def ard_info(title, seconds=900):
    return broadcaster.parse_ard(ard_page(series='planet schule', title=title, seconds=seconds))


class PlanetSchuleEndToEnd(Worker):
    def setUp(self):
        super().setUp()
        self.ids = {}
        titles = ['%s · Natur nah' % t for t in ('Wasserinsekten', 'Der Bach der Nasen', 'Die Rückkehr der bedrohten Vögel',
                                                 'Wildbienen', 'Am Teich')] + ['Vulkane · total phänomenal', 'Die Gurke · Feldküche']
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS metadata_cache(id TEXT PRIMARY KEY,payload TEXT,checked REAL)')
            # 0.6.81 learned the portal as template of the topic (state before 0.6.82)
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', ('planet schule', ARD['provider'], ARD['reference_id'], json.dumps(ARD)))
            catalog.ingest(c, [{'title': t, 'topic': 'planet schule', 'duration': 900, 'channel': 'SWR', 'description': 'x' * 60 + t,
                                'url_video': 'https://example.org/ps%d.mp4' % i, 'timestamp': STAMP,
                                'url_website': 'https://www.ardmediathek.de/video/planet-schule/x/swr/Y3JpZDovL3N3ci5kZS9wczEyMzQ%d' % i}
                               for i, t in enumerate(titles)])
            for i, t in enumerate(titles):
                wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')=?", (t,)).fetchone()[0]
                self.ids[t] = wid
                m = dict(ARD, reason='Sendereihe laut ARD Mediathek; Angaben zu genau diesem Angebot.')
                state = 'identified'
                if i == 1:
                    m.update(state='format', format_grouping='segment', reason='Beitrag der Sendung „planet schule“; keine eigene Folge.');state = 'format'
                c.execute('UPDATE works SET kind=?,title=?,state=?,show_key=?,meta=? WHERE id=?',
                          ('series', 'planet schule', state, catalog.showkey(ARD), json.dumps(m), wid))

    def candidates(self, row, meta, settings):
        # real ARD provider code (page parse + candidate) plus a TVDB hit for the portal and, for the Reihe, TMDB
        out = []
        c = broadcaster.candidate(row, meta, ard_info(row['title']))
        if c:out.append(c)
        out.append(dict(PORTAL_TVDB))
        if meta.get('title') == 'Natur nah':
            out.append({**PORTAL_TVDB, 'title': 'Natur nah', 'provider': 'TMDB', 'reference_id': '4711', 'year': None})
        return {'candidates': out, 'warnings': [], 'deferred_providers': [], 'provider_checks': []}

    def titles(self):
        with self.db() as c:
            return {t: (r['title'], r['state'], json.loads(r['meta']).get('provider'), json.loads(r['meta']).get('format_grouping'))
                    for t, wid in self.ids.items() for r in [c.execute('SELECT * FROM works WHERE id=(SELECT work_id FROM offers WHERE json_extract(payload,"$.title")=?)', (t,)).fetchone()]}

    def test_reihe_survives_recognition_propagation_episode_search_and_import(self):
        self.svc.reseed_portal()
        with self.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM series_templates WHERE topic='planet schule'").fetchone()[0], 0)
        with patch.object(core, 'candidates', side_effect=self.candidates), \
             patch.object(broadcaster, 'lookup_limited', side_effect=lambda row: ard_info(row.get('title'))), \
             patch.object(imdb_archive, 'ACTIVE', self.archive):
            for _ in range(20):
                if not self.svc.metadata_once('identity'):break
            with self.db() as c:c.execute('UPDATE episode_queue SET next_try=0')
            for _ in range(20):
                if not self.svc.metadata_once('episode'):break
        out = self.titles()
        for t, (title, state, provider, grouping) in out.items():
            self.assertNotEqual(catalog.key(title), 'planet schule', (t, out[t]))
            self.assertNotEqual(provider, 'ARD Mediathek', (t, out[t]))
            self.assertNotEqual(provider, 'TVDB', (t, out[t]))
        self.assertEqual(out['Wasserinsekten · Natur nah'][:3], ('Natur nah', 'identified', 'TMDB'))
        self.assertEqual(out['Der Bach der Nasen · Natur nah'][0], 'Natur nah')
        self.assertEqual(out['Vulkane · total phänomenal'][0], 'total phänomenal')
        with self.db() as c:
            # no new template for the portal; a later import of a portal offer seeds its own Reihe
            self.assertEqual(c.execute("SELECT COUNT(*) FROM series_templates WHERE topic='planet schule'").fetchone()[0], 0)
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', ('planet schule', ARD['provider'], ARD['reference_id'], json.dumps(ARD)))
            catalog.ingest(c, [{'title': 'Libellen · Natur nah', 'topic': 'planet schule', 'duration': 900, 'channel': 'SWR',
                                'description': 'y' * 80, 'url_video': 'https://example.org/new.mp4', 'timestamp': STAMP}])
            row = c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title')='Libellen · Natur nah'").fetchone()
            self.assertEqual((row['title'], row['state']), ('Natur nah', 'pending'))
            src = json.loads(c.execute('SELECT payload FROM offers WHERE work_id=?', (row['id'],)).fetchone()[0])
            self.assertIsNone(catalog.series_template_candidate(c, row, src))

    def test_ordinary_topic_template_still_works(self):
        with self.db() as c:
            known = {'kind': 'series', 'title': 'Servicezeit', 'provider': 'ARD Mediathek', 'reference_id': 'abc', 'year': None}
            c.execute('INSERT INTO series_templates VALUES(?,?,?,?)', ('servicezeit', 'ARD Mediathek', 'abc', json.dumps(known)))
            catalog.ingest(c, [{'title': 'Zecken im Garten', 'topic': 'Servicezeit', 'duration': 1770, 'channel': 'WDR',
                                'description': 'z' * 80, 'url_video': 'https://example.org/sz.mp4', 'timestamp': STAMP}])
            row = c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title')='Zecken im Garten'").fetchone()
            self.assertEqual((row['title'], row['state']), ('Servicezeit', 'identified'))
        self.assertTrue(catalog.portal_identity(PORTAL_TVDB))
        self.assertFalse(catalog.portal_identity(known))


if __name__ == '__main__':
    unittest.main()
