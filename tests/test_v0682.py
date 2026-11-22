"""0.6.82: Mac-Prüfung 0.6.81 – die ARD-Mediathek-Erkennung überschrieb die Reihe aus dem Titel wieder mit dem
Portal „planet schule“ (256 Werke); ein TVDB-Werk „Planet Schule“ mit „bestätigter“ Folge blieb stehen."""
import json
import sqlite3
import threading
import unittest

import broadcaster
import catalog
import catalog_service
import matching
from test_broadcaster import ard_page


def database():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(catalog.SCHEMA)
    return c


class ArdPortal(unittest.TestCase):
    def test_portal_is_no_series(self):
        row = {'title': 'Wasserinsekten · Natur nah', 'topic': 'planet schule', 'duration': 900}
        meta = catalog.seed(dict(row, channel='SWR'))
        self.assertEqual(meta['title'], 'Natur nah')
        info = broadcaster.parse_ard(ard_page(series='planet schule', title='Wasserinsekten · Natur nah', seconds=900))
        self.assertIsNone(broadcaster.candidate(row, meta, info))
        # an ordinary Sendereihe still identifies its offers
        servicezeit = broadcaster.candidate({'title': 'Zecken im Garten', 'topic': 'Servicezeit', 'duration': 1770},
                                            {'kind': 'series', 'title': 'Servicezeit'}, broadcaster.parse_ard(ard_page()))
        self.assertEqual(servicezeit['title'], 'Servicezeit')


class Heal(unittest.TestCase):
    def test_portal_identities_reseeded(self):
        c = database()
        rows = [('Wasserinsekten · Natur nah', 'identified', {'provider': 'ARD Mediathek'}),
                ('Schwingen bis der Strom fließt · Achtung! Experiment', 'format',
                 {'provider': 'ARD Mediathek', 'state': 'format', 'format_grouping': 'segment'}),
                ('Der Fuchs · Das kleine 1x1 der Artenkunde', 'matched',
                 {'provider': 'TVDB', 'reference_id': '461332', 'episode_verified': True}),
                ('Die Eule · Eugens Welt', 'manual', {'provider': 'TVDB'})]
        catalog.ingest(c, [{'title': t, 'topic': 'planet schule', 'duration': 600, 'channel': 'SWR', 'description': 'x' * 60 + t,
                            'url_video': 'https://example.org/%d.mp4' % i, 'timestamp': 1782086400} for i, (t, _, _) in enumerate(rows)])
        for title, state, extra in rows:
            wid = c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.title')=?", (title,)).fetchone()[0]
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
            m.update(kind='series', title='planet schule', **extra)
            c.execute('UPDATE works SET kind=?,title=?,state=?,meta=? WHERE id=?', ('series', 'planet schule', state, json.dumps(m), wid))

        class Ctx:
            def __enter__(self_):return c
            def __exit__(self_, *a):c.commit()
        catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None).reseed_portal()
        out = {r['t']: (r['title'], r['state']) for r in c.execute(
            "SELECT w.title,w.state,json_extract(o.payload,'$.title') t FROM works w JOIN offers o ON o.work_id=w.id")}
        self.assertEqual(out['Wasserinsekten · Natur nah'], ('Natur nah', 'pending'))
        self.assertEqual(out['Schwingen bis der Strom fließt · Achtung! Experiment'], ('Achtung! Experiment', 'pending'))
        self.assertEqual(out['Der Fuchs · Das kleine 1x1 der Artenkunde'], ('Das kleine 1x1 der Artenkunde', 'pending'))
        self.assertEqual(out['Die Eule · Eugens Welt'], ('planet schule', 'manual'))
        self.assertTrue(catalog.get_state(c, 'portal_reseed_v0686', False))


if __name__ == '__main__':
    unittest.main()
