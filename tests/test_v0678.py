"""0.6.78: Mac-Prüfung 0.6.77 (21.11.2026).

- Björns Bestand lief schon mit 0.6.76: 727 ganze Ausgaben „Gesichter & Geschichten“ blieben Beitrag
  (imdb_dated_v0676), weil 0.6.77 nur neue Einordnungen änderte. → einmalige Prüfung und Rücknahme.
- Wikidata-Regel 0.6.77 ohne messbare Wirkung: UNKNOWN_RULES_REV war nicht erhöht, der Sammellauf wartete 6 h.
- Planet Schule: „<Folgentitel> · <Reihe>“ unter dem Thema „planet schule“.
"""
import json
import sqlite3
import threading
import unittest
from unittest import mock

import catalog
import catalog_service
import imdb_archive
import metadata

STAMP = 1782086400


def database():
    c = sqlite3.connect(':memory:', check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(catalog.SCHEMA)
    return c


def service(c):
    class Ctx:
        def __enter__(self_):return c
        def __exit__(self_, *a):c.commit()
    return catalog_service.Service(lambda: Ctx(), lambda: {}, threading.Event(), None)


class Archive:
    updated = True
    def __init__(self, runtime=None):self.runtime = runtime
    def dated_format(self, ref):return (ref in ('tt_gg', 'tt_kot'), self.runtime if ref == 'tt_kot' else None)


def add(c, n, topic, duration, ref, state, grouping=None, rule=None, provider='IMDb Offline', title=None):
    catalog.ingest(c, [{'title': (title or topic + ' Beitrag %d') % i, 'topic': topic, 'duration': duration, 'channel': 'ARD',
                        'description': 'x' * 60 + '%s%d%s' % (topic, i, state), 'url_video': 'https://example.org/%s%s%d%s.mp4' % (ref, state, i, rule),
                        'timestamp': STAMP} for i in range(n)])
    for row in c.execute("SELECT * FROM works WHERE show_key=''").fetchall():
        m = json.loads(row['meta'])
        m.update(kind='series', title=topic, provider=provider, reference_id=ref, episode_verified=False)
        if state == 'format':
            m.update(state='format', format_grouping=grouping, reason='Beitrag der Sendung „%s“; keine eigene Folge.' % topic)
            if rule:m['format_rule'] = rule
        c.execute("UPDATE works SET kind='series',title=?,show_key=?,state=?,meta=? WHERE id=?",
                  (topic, 'show_' + ref, state, json.dumps(m), row['id']))


class HealDatedSegments(unittest.TestCase):
    def setUp(self):
        self.c = database()
        # G&G: ~19-minute whole editions filed as contributions by 0.6.76; regular editions are ~19 min, too
        add(self.c, 6, 'Gesichter & Geschichten', 1150, 'tt_gg', 'format', 'segment', 'imdb_dated_v0676')
        add(self.c, 3, 'Gesichter & Geschichten', 1140, 'tt_gg', 'format', 'edition', title='Gesichter & Geschichten %d')
        # Kaffee oder Tee?: IMDb runtime 2 h, 12-minute contributions stay
        add(self.c, 4, 'Kaffee oder Tee?', 720, 'tt_kot', 'format', 'segment', 'imdb_dated_v0676')
        # 0.6.75 leftovers without a label: 15 minutes in the dated G&G, a 5-minute ordinary contribution
        add(self.c, 2, 'Gesichter & Geschichten', 900, 'tt_gg', 'format', 'segment', title='GG alt %d')
        add(self.c, 2, 'Gesichter & Geschichten', 300, 'tt_gg', 'format', 'segment', title='GG kurz %d')
        # an unlabelled 15-minute contribution of a Sendung that IMDb does not list as dated stays untouched
        add(self.c, 2, 'Andere Sendung', 900, 'tt_other', 'format', 'segment')
        self.svc = service(self.c)

    def run_heal(self, archive):
        with mock.patch.object(imdb_archive, 'ACTIVE', archive):
            self.svc.heal_dated_segments()

    def rows(self, like):
        return self.c.execute("""SELECT w.state,json_extract(w.meta,'$.format_grouping') g,json_extract(w.meta,'$.format_rule') r,
            json_extract(w.meta,'$.state') ms,(SELECT 1 FROM episode_queue q WHERE q.work_id=w.id) q
            FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title') LIKE ?""", (like,)).fetchall()

    def test_heals_real_catalogue(self):
        self.run_heal(Archive(runtime=7200))
        gg = self.rows('Gesichter & Geschichten Beitrag%')
        self.assertEqual(len(gg), 6)
        self.assertTrue(all(r['state'] == 'identified' and r['g'] is None and r['r'] is None and r['ms'] == 'identified' and r['q'] for r in gg))
        self.assertTrue(all(r['state'] == 'format' and r['r'] == 'imdb_dated_v0677' for r in self.rows('Kaffee oder Tee? Beitrag%')))
        self.assertTrue(all(r['state'] == 'identified' for r in self.rows('GG alt%')))
        self.assertTrue(all(r['state'] == 'format' and r['r'] is None for r in self.rows('GG kurz%')))
        self.assertTrue(all(r['state'] == 'format' for r in self.rows('Andere Sendung%')))
        self.assertTrue(all(r['g'] == 'edition' for r in self.rows('Gesichter & Geschichten _')))
        done = catalog.get_state(self.c, 'dated_segments_v0678', {})
        self.assertEqual((done['undone'], done['kept']), (8, 4))
        # undone works are not filed again by the 0.6.65 refile of reset editions
        self.assertEqual(catalog.reset_editions(self.c), [])
        # once only
        self.c.execute("UPDATE works SET state='format',meta=json_set(meta,'$.format_grouping','segment','$.format_rule','imdb_dated_v0676') WHERE state='identified'")
        self.run_heal(Archive(runtime=7200))
        self.assertTrue(all(r['state'] == 'format' for r in self.rows('Gesichter & Geschichten Beitrag%')))

    def test_waits_for_archive(self):
        self.svc.stop.set()
        self.run_heal(None)
        self.assertFalse(catalog.get_state(self.c, 'dated_segments_v0678', False))
        self.assertTrue(all(r['state'] == 'format' for r in self.rows('Gesichter & Geschichten Beitrag%')))

    def test_user_decision_stays(self):
        self.c.execute("UPDATE works SET meta=json_set(meta,'$.scan_requested',1)")
        self.run_heal(Archive(runtime=7200))
        self.assertTrue(all(r['state'] == 'format' for r in self.rows('Gesichter & Geschichten Beitrag%')))


class WikidataSweep(unittest.TestCase):
    def test_rules_rev_raised(self):
        # 0.6.77's rule only takes effect when the sweep runs at once after the update
        self.assertGreaterEqual(catalog.UNKNOWN_RULES_REV, 6)
        c = database();svc = service(c)
        catalog.set_state(c, 'unknown_sweep', {'rev': 5, 'finished': __import__('time').time()})
        with mock.patch.object(catalog, 'unknown_candidates', return_value=([], [])) as cand:
            svc.unknown_sweep()
        self.assertTrue(cand.called)
        self.assertEqual(catalog.get_state(c, 'unknown_sweep', {})['rev'], catalog.UNKNOWN_RULES_REV)

    def test_old_wikidata_counted(self):
        old = {'provider': 'Wikidata', 'kind': 'movie', 'title': 'Midge Ure', 'similarity': 1.0,
               'evidence_type': 'unknown_type', 'confidence': 'possible'}
        self.assertTrue(catalog.old_wikidata_suggestion(old))
        self.assertFalse(catalog.old_wikidata_suggestion(dict(old, wikidata_rev=2)))
        self.assertFalse(catalog.old_wikidata_suggestion(dict(old, confidence='high')))


class PlanetSchule(unittest.TestCase):
    def test_series_after_dot(self):
        m = catalog.seed({'title': 'Das schnelle Pendel · Achtung! Experiment', 'topic': 'planet schule', 'channel': 'SWR', 'duration': 900})
        self.assertEqual((m['kind'], m['title'], m['episode_title']), ('series', 'Achtung! Experiment', 'Das schnelle Pendel'))
        m = catalog.seed({'title': 'Parallelwelten ⋅ Gezeichnete Seelen', 'topic': 'Planet Schule', 'channel': 'SWR', 'duration': 165})
        self.assertEqual((m['kind'], m['title']), ('series', 'Gezeichnete Seelen'))
        # without a separator, or under another topic, nothing changes
        self.assertNotEqual(catalog.seed({'title': 'The Wheat We Eat', 'topic': 'planet schule'})['kind'], 'series')
        self.assertNotEqual(catalog.seed({'title': 'Kochen · Rezepte', 'topic': 'ARD Buffet'})['title'], 'Rezepte')
        self.assertTrue(metadata.generic_topic('planet schule'))

    def test_existing_works_reseeded(self):
        c = database()
        catalog.ingest(c, [{'title': 'Das schnelle Pendel · Achtung! Experiment', 'topic': 'planet schule', 'duration': 900, 'channel': 'SWR',
                            'description': 'x' * 70, 'url_video': 'https://example.org/p1.mp4', 'timestamp': STAMP},
                           {'title': 'The Wheat We Eat', 'topic': 'planet schule', 'duration': 898, 'channel': 'SWR',
                            'description': 'y' * 70, 'url_video': 'https://example.org/p2.mp4', 'timestamp': STAMP}])
        # as before 0.6.78: unknown, already checked once
        c.execute("UPDATE works SET kind='unknown',state='review',attempts=1,title=(SELECT json_extract(payload,'$.title') FROM offers WHERE work_id=works.id)")
        svc = service(c)
        svc.reseed_portal()
        rows = {r['title']: r for r in c.execute('SELECT * FROM works')}
        self.assertEqual(rows['Achtung! Experiment']['kind'], 'series')
        self.assertEqual(rows['Achtung! Experiment']['state'], 'pending')
        self.assertEqual(rows['The Wheat We Eat']['kind'], 'unknown')
        self.assertTrue(catalog.get_state(c, 'portal_reseed_v0684', False))


if __name__ == '__main__':
    unittest.main()
