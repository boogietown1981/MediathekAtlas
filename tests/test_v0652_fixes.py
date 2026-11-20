"""0.6.52: corrections after the check of 0.6.48 on Björn's Mac (20.11.2026, real network).

* ServusTV: the 15 pages refused in every run are lists for Austria only: 403 with body {"err":"geo blocked"}
  (the same ids under /stv/de/at/ answer 200). Such a page is final at once, without retries, not a partial run,
  shown as "nur in Österreich"; nothing is fetched from the Austrian scope.
* Joyn: titles carried HTML entities ("Mensch, der Bulle is &#39;ne Frau").
DMAX/TLC/HGTV over the website API: tests/test_v0648_dmax.py."""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import joyn  # noqa: E402
import servustv  # noqa: E402
from test_v0601_servustv import Base as ServusBase, FakeServus, NOW  # noqa: E402
import test_v0648_joyn_episodes as J  # noqa: E402

GEO = '/collections/v5.3/stv/de/de/1d9e083e-5b80-4f57-96dd-24d1e7cc6e27'


class GeoServus(FakeServus):
    def __init__(self):
        super().__init__()
        self.geo = {GEO}
        self.geo_calls = 0

    def __call__(self, url, headers, limit=None):
        assert '/stv/de/at/' not in url, 'nothing from the Austrian scope'
        if any(g in url for g in self.geo):
            self.geo_calls += 1
            raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(b'{"err":"geo blocked"}'))
        return super().__call__(url, headers, limit)


class ServusGeoBlocked(ServusBase):
    def run_sync(self, fake, now, waits=(0, 0)):
        events = []
        with mock.patch.object(servustv, '_notify', lambda e, **d: events.append((e, d))):
            result = servustv.sync(self.root, opener=fake, now=now, waits=waits)
        return result, dict(events).get('servustv_sync_completed', {})

    def test_geo_blocked_list_is_final_at_once(self):
        fake = GeoServus()
        result, done = self.run_sync(fake, NOW, waits=(30, 30))      # long waits: a retry would show
        self.assertTrue(result['ok'])
        self.assertFalse(result['partial'])
        self.assertEqual(fake.geo_calls, 1)                           # no retries
        self.assertEqual((done['geo_blocked'], done['refused'], done['remembered']), (1, 0, 0))
        self.assertEqual(done['unavailable'], {})
        st = servustv.state(self.root)
        self.assertEqual(st['last_result'], 'complete')
        self.assertEqual(st['last_error'], '')
        self.assertIn('1 Liste nur in Österreich verfügbar (Geosperre)', st['note'])
        self.assertEqual(st['geo_blocked'], 1)
        # next run: no request for the known list; still complete and still named
        result, done = self.run_sync(fake, NOW + 86400)
        self.assertEqual(fake.geo_calls, 1)
        self.assertFalse(result['partial'])
        self.assertEqual(done['geo_blocked'], 1)
        # after GEO_RECHECK one try
        self.run_sync(fake, NOW + servustv.GEO_RECHECK + 10)
        self.assertEqual(fake.geo_calls, 2)

    def test_plain_403_keeps_its_retries(self):
        fake = FakeServus()
        fake.refuse = {'/products/v5.3/stv/de/de/AA-25RX849FN1W11': 1}
        result, done = self.run_sync(fake, NOW)
        self.assertEqual((done['recovered'], done['geo_blocked']), (1, 0))

    def test_page_remembered_as_refused_by_0645_becomes_geo(self):
        db = servustv._connect(self.root)
        with db:
            servustv._set(db, 'refused_pages', json.dumps({GEO + '?offset=0': NOW - servustv.REFUSED_RECHECK - 10}))
        db.close()
        fake = GeoServus()
        result, done = self.run_sync(fake, NOW)
        self.assertEqual((done['geo_blocked'], done['remembered']), (1, 0))
        db = servustv._connect(self.root)
        try:
            self.assertEqual(json.loads(servustv._get(db, 'refused_pages')), {})
            self.assertEqual(list(json.loads(servustv._get(db, 'geo_pages'))), [GEO + '?offset=0'])
        finally:
            db.close()


class JoynEntities(unittest.TestCase):
    def test_titles_are_unescaped(self):
        node = J.episode('b_x', 3, 1, 'Mensch, der Bulle is &#39;ne Frau')
        node['description'] = 'Tom &amp; Jerry &quot;live&quot;'
        row = joyn.episode_row(node, 's.a_stromberg', 0)
        self.assertEqual(row['title'], "Mensch, der Bulle is 'ne Frau")
        if 'summary' in row and row['summary']:
            self.assertEqual(row['summary'], 'Tom & Jerry "live"')


if __name__ == '__main__':
    unittest.main()
