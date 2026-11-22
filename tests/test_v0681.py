"""0.6.81: Planet Schule unter dem Portalnamen, Ladezeiten Werkliste/Kinderecke (Nachtdiagnose 21.11.2026)."""
import json
import sqlite3
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import catalog
import catalog_service
import kids_catalog

ROOT = Path(__file__).resolve().parents[1]


class PortalMatched(unittest.TestCase):
    def test_matched_portal_identity_reseeded(self):
        c = sqlite3.connect(':memory:', check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.executescript(catalog.SCHEMA)
        catalog.ingest(c, [{'title': 'Der Fuchs · Das kleine 1x1 der Artenkunde', 'topic': 'planet schule', 'duration': 600,
                            'channel': 'SWR', 'description': 'x' * 70, 'url_video': 'https://example.org/a.mp4', 'timestamp': 1782086400},
                           {'title': 'Die Eule · Achtung! Experiment', 'topic': 'planet schule', 'duration': 600,
                            'channel': 'SWR', 'description': 'y' * 70, 'url_video': 'https://example.org/b.mp4', 'timestamp': 1782086400}])
        ids = [r[0] for r in c.execute('SELECT id FROM works ORDER BY id')]
        c.execute("UPDATE works SET kind='series',title='Planet Schule',state='matched' WHERE id=?", (ids[0],))
        c.execute("UPDATE works SET kind='series',title='Planet Schule',state='manual' WHERE id=?", (ids[1],))

        class Ctx:
            def __enter__(self_):return c
            def __exit__(self_, *a):c.commit()
        catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None).reseed_portal()
        rows = {r['id']: r for r in c.execute('SELECT * FROM works')}
        self.assertEqual((rows[ids[0]]['title'], rows[ids[0]]['state']), ('Das kleine 1x1 der Artenkunde', 'pending'))
        self.assertEqual((rows[ids[1]]['title'], rows[ids[1]]['state']), ('Planet Schule', 'manual'))   # user's choice stays


class KidsShelf(unittest.TestCase):
    def setUp(self):
        kids_catalog.invalidate()
        self.addCleanup(kids_catalog.invalidate)

    def test_stale_shelf_answers_at_once(self):
        calls = []
        def page(root, db, kind='movies', **kw):
            calls.append(kind)
            return {'items': [], 'total': 0}
        first = kids_catalog.shelf('/r', None, page=page)
        self.assertEqual(len(calls), 2)
        with kids_catalog._LOCK:
            kids_catalog._CACHE['/r'] = (time.monotonic() - kids_catalog.TTL - 1, first)
        slow = threading.Event()
        def slow_page(root, db, kind='movies', **kw):
            slow.wait(2)
            calls.append('slow')
            return {'items': [], 'total': 0}
        started = time.monotonic()
        again = kids_catalog.shelf('/r', None, page=slow_page)
        self.assertLess(time.monotonic() - started, 0.5)       # old list at once
        self.assertIs(again, first)
        slow.set()
        for _ in range(50):
            if not kids_catalog._BUILDING:break
            time.sleep(.05)
        self.assertIn('slow', calls)
        self.assertIsNot(kids_catalog.shelf('/r', None, page=page), first)   # renewed list


class Server(unittest.TestCase):
    def test_prewarm_and_timing(self):
        src = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("('series','hide')", src)
        self.assertIn('kids_shelf_prewarmed', src)
        self.assertIn("'catalog_slow_parts'", src)
        self.assertIn("'kids_slow_parts'", src)


if __name__ == '__main__':
    unittest.main()
