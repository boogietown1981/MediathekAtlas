"""0.6.49: the works 0.6.43 left without a kind.

Diagnose 20.11.2026 abends (0.6.43, MacBook Pro M3): 21,189 works stayed "Art unbekannt"; 14,270 only because of
film database suggestions, 4,756 because of an old provider error. Weak suggestions (a feature film of the same
name with another running time, a fuzzy title, the Sendung itself listed several times) no longer block filing
a contribution under its Sendung; they are kept and "Erneut prüfen" restores them. ARTE's foreign sections are no
Sendungen; works named after a section are checked again under their own title. TVDB search hits whose record is
gone are no provider error. The recognition per channel survives a restart and lists why works stay open.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog  # noqa: E402
import catalog_service  # noqa: E402
import diagnostics  # noqa: E402
import metadata  # noqa: E402
from test_diagnosis_fixes import database  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def offer(title, topic, channel='SRF', duration=1500, n=0, description=''):
    return {'title': title, 'topic': topic, 'description': description, 'duration': duration,
            'channel': channel, 'url_video': 'https://example.org/%s-%d.mp4' % (channel, n),
            'timestamp': 1795100000}


def movie(title, similarity=1.0, **extra):
    return {'provider': 'IMDb Offline', 'kind': 'movie', 'title': title, 'similarity': similarity, **extra}


def series(title, similarity=1.0, ref='tt1', year=None, **extra):
    return {'provider': 'IMDb Offline', 'kind': 'series', 'title': title, 'similarity': similarity, 'reference_id': ref,
            'year': year, 'confidence': 'high', **extra}


class WeakSuggestionTests(unittest.TestCase):
    def weak(self, s, duration=1500, sendung='DOK'):
        return catalog.suggestion_weak(s, {'duration': duration, 'timestamp': 1795100000}, sendung)

    def test_no_evidence_against_the_sendung(self):
        self.assertTrue(self.weak(series('DOK', year=1954)))                      # an old namesake (Top Secret 1954)
        self.assertTrue(self.weak(series('Arena', year=1975), sendung='Arena'))
        self.assertTrue(self.weak(series('Arena', year='1975'), sendung='Arena'))         # year as text (Wikidata)
        # Third Gegenprobe (Rohdaten 4a2e9ad): fuzzy namesake and Wikidata concepts are no evidence.
        self.assertTrue(self.weak({'provider': 'TMDB', 'kind': 'series', 'title': '3 von oben', 'year': 2018,
                                   'similarity': 0.889}, sendung='...von oben'))
        self.assertTrue(self.weak({'provider': 'Wikidata', 'kind': 'series', 'title': 'Reise', 'similarity': 1.0,
                                   'confidence': 'possible', 'reference_id': 'Q36875808'}, sendung='Reise'))
        # Second Gegenprobe: a film named like the Sendung is no episode of it ("Top Secret!" 1984).
        src = {'duration': 1500, 'timestamp': 1795100000}
        self.assertTrue(catalog.suggestion_weak(movie('Top Secret'), src, 'Top Secret', 'Der Maulwurf im Ministerium'))
        self.assertFalse(catalog.suggestion_weak(movie('Top Secret'), src, 'Top Secret', 'Top Secret'))
        self.assertTrue(self.weak(series('Dok Leipzig', similarity=.8)))          # fuzzy series name
        self.assertTrue(self.weak(movie('Heimweh', runtime_mismatch=True)))       # 90-min film vs. 25-min clip
        self.assertTrue(self.weak(movie('Heimweh', year_mismatch=True)))
        self.assertTrue(self.weak(movie('Heimweh!', similarity=.9)))              # fuzzy title, clip length

    def test_suggestions_that_could_be_right(self):
        self.assertFalse(self.weak(series('Heimweh')))                            # another series of exactly this title
        # Gegenprobe 20.11.2026: the Sendung's own series is evidence for the work (NACHTCAFÉ, 1 gegen 100).
        self.assertFalse(self.weak(series('Nachtcafé', year=1987), sendung='NACHTCAFÉ'))
        self.assertFalse(self.weak(series('DOK')))                                # year unknown: in doubt open
        self.assertFalse(self.weak(series('Arena', year=1993), sendung='Arena'))  # several namesakes, one fits
        self.assertFalse(self.weak({'provider': 'Wikidata', 'kind': 'series', 'title': 'Hau Ruck', 'year': 2005,
                                    'similarity': 1.0, 'confidence': 'possible'}, sendung='Hau Ruck'))
        self.assertFalse(self.weak(series('Sag die Wahrheit', year=2016, episode_verified=True), sendung='Sag die Wahrheit'))
        self.assertFalse(self.weak(series('Sag die Wahrheit', year=1954, season=3, episode=4), sendung='Sag die Wahrheit'))
        self.assertFalse(self.weak(movie('Heimweh')))                             # same title, running time unknown/agrees
        self.assertFalse(self.weak(movie('Die Frau im Mond', similarity=.9), duration=5400))  # fuzzy, but film length


class RubricTests(unittest.TestCase):
    def test_foreign_arte_sections_are_no_sendung(self):
        for topic in ('Serie e fiction - Serie', 'Séries et fictions - Séries', 'Series y ficciones - Webseries',
                      'Scienze - In pillole', 'Historia - Civilizaciones', 'Ciencias - Al grano', 'Seriale i fikcja - Seriale'):
            self.assertTrue(metadata.generic_topic(topic), topic)
        for topic in ('Puls', 'Kulturplatz', 'Kino am Sonntag', 'DOK - Auf und davon', 'Historia'):
            self.assertFalse(metadata.generic_topic(topic), topic)

    def test_series_section_without_series_name_stays_open(self):
        self.assertEqual(catalog.unknown_role(offer('Die Erbschaft - Episodio 3', 'Serie e fiction - Serie', channel='ARTE.IT'), 240),
                         ('series_rubric', ''))
        self.assertEqual(catalog.unknown_role(offer('Die Erbschaft (3/10)', 'Serie e fiction - Serie', channel='ARTE.IT'), 240),
                         ('part', 'Die Erbschaft'))
        self.assertEqual(catalog.unknown_role(offer('Leonardo', 'Scienze - In pillole', channel='ARTE.IT'), 40), ('single', ''))

    def test_seed_keeps_the_section_out_of_the_series_title(self):
        m = catalog.seed(offer('Tschugger (2/5)', 'Fernsehfilme und Serien - Serien'))
        self.assertEqual((m['kind'], m['title']), ('series', 'Tschugger'))
        m = catalog.seed(offer('Der Bestatter - Die Frau im Moor', 'Fernsehfilme und Serien - Serien'))
        self.assertEqual((m['kind'], m['title']), ('unknown', 'Der Bestatter - Die Frau im Moor'))
        m = catalog.seed(offer('Folge 1', 'Hotel Heidelberg - Serie'))       # a real series name stays the title
        self.assertEqual((m['kind'], m['title']), ('series', 'Hotel Heidelberg - Serie'))


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)
        rows = [offer('Auf und davon', 'DOK', n=1),
                offer('Heimweh', 'DOK', n=2),
                offer('Die Bergbauern', 'DOK', n=3),
                offer('Grenzgänger', 'DOK', n=4, duration=5400),
                offer('Fehler alt', 'DOK', n=5),
                offer('Fehler neu', 'DOK', n=6),
                offer('Allein im Wald', 'Allein im Wald', channel='ARTE.DE', duration=3000, n=7),
                offer('Zwei', 'Kleine Sendung', channel='ORF', n=8),
                offer('Drei', 'Kleine Sendung', channel='ORF', n=9)]
        setup = {
            'Auf und davon': dict(suggestions=[series('DOK', ref='tt1', year=1954), series('DOK', ref='tt2', year=1963)]),
            'Heimweh': dict(suggestions=[movie('Heimweh', runtime_mismatch=True)]),
            'Die Bergbauern': dict(suggestions=[movie('Die Bergbauern')]),                 # could be right
            'Grenzgänger': dict(suggestions=[movie('Grenzgänger!', similarity=.9)]),       # feature length
            'Fehler alt': dict(metadata_warnings=['TVDB: Zeitüberschreitung'], attempts=3),
            'Fehler neu': dict(metadata_warnings=['TVDB: Zeitüberschreitung'], attempts=1),
            'Allein im Wald': dict(suggestions=[movie('Allein im Wald', runtime_mismatch=True)]),
            'Zwei': dict(suggestions=[movie('Zwei', runtime_mismatch=True)]),
        }
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, rows)
            for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
                m = json.loads(meta)
                extra = dict(setup.get(m['title'], {}))
                attempts = extra.pop('attempts', 2)
                m.update(extra)
                c.execute("UPDATE works SET state='review', attempts=?, meta=? WHERE id=?", (attempts, json.dumps(m), wid))
        self.service = catalog_service.Service(self.db, lambda: {}, threading.Event(), Path(self.tmp.name))

    def works(self):
        with self.db() as c:
            out = {}
            for r in c.execute('SELECT * FROM works'):
                m = json.loads(r['meta'])
                out[(m.get('unknown_before') or {}).get('title') or m.get('episode_title') or r['title']] = dict(r, meta=m)
            return out

    def sweep(self):
        events = []
        with patch.object(diagnostics, 'event', lambda name, **kw: events.append((name, kw))):
            self.service.unknown_sweep(force=True)
        return [kw for name, kw in events if name == 'unknown_classified'][0]

    def test_weak_suggestions_and_old_errors_no_longer_block(self):
        info = self.sweep()
        w = self.works()
        for title in ('Auf und davon', 'Heimweh', 'Fehler alt'):
            self.assertEqual((w[title]['kind'], w[title]['state'], w[title]['title']), ('series', 'format', 'DOK'), title)
            self.assertEqual(w[title]['meta']['unknown_before']['kind'], 'unknown')
        self.assertEqual(len(w['Auf und davon']['meta']['unknown_before']['suggestions']), 2)
        self.assertIn('passten nicht', w['Heimweh']['meta']['reason'])
        self.assertNotIn('suggestions', w['Heimweh']['meta'])
        # Could be right, Einzelsendung, Sendung with only three works, recent provider error: stay open.
        for title in ('Die Bergbauern', 'Grenzgänger', 'Fehler neu', 'Allein im Wald', 'Zwei'):
            self.assertEqual(w[title]['kind'], 'unknown', title)
        self.assertEqual(w['Drei']['meta']['format_grouping'], 'contribution')     # no suggestion, 2 works suffice
        self.assertEqual(info['remaining'], {'suggestions': 2, 'warnings': 1, 'suggestions_no_sendung': 1,
                                             'suggestions_small_sendung': 1})
        self.assertEqual(info['set_aside'], {'suggestions': 2, 'warnings': 1})
        blocking = {b['title']: b for b in info['blocking_samples']}
        self.assertEqual(blocking['Die Bergbauern']['suggestion'], {'provider': 'IMDb Offline', 'kind': 'movie', 'title': 'Die Bergbauern', 'similarity': 1.0})
        self.assertEqual(info['remaining_channels']['SRF'], {'suggestions': 2, 'warnings': 1})
        self.assertEqual(info['remaining_topics'][0], {'channel': 'SRF', 'topic': 'DOK', 'reason': 'suggestions', 'works': 2})
        self.assertEqual(info['unknown_left'], 5)
        self.assertEqual(info['unknown_by_state'], {'review': 5})
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'unknown_sweep', {})['rev'], catalog.UNKNOWN_RULES_REV)

    def test_recheck_restores_the_open_work_and_its_suggestions(self):
        self.sweep()
        wid = self.works()['Auf und davon']['id']
        with self.db() as c:
            c.execute("INSERT OR IGNORE INTO episode_queue(work_id,next_try) VALUES(?,0)", (wid,))
            self.assertEqual(catalog.prioritize(c, [wid]), 1)
            r = c.execute('SELECT * FROM works WHERE id=?', (wid,)).fetchone()
            m = json.loads(r['meta'])
            self.assertEqual((r['kind'], r['title'], r['state'], r['show_key']), ('unknown', 'Auf und davon', 'pending', ''))
            self.assertEqual(len(m['suggestions']), 2)
            self.assertTrue(m['scan_requested'])
            self.assertNotIn('unknown_before', m)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM episode_queue WHERE work_id=?', (wid,)).fetchone()[0], 0)
            c.execute("UPDATE works SET state='review' WHERE id=?", (wid,))
        self.sweep()
        self.assertEqual(self.works()['Auf und davon']['kind'], 'unknown')       # the user's request wins

    def test_first_049_decisions_against_good_suggestions_are_undone(self):
        with self.db() as c:
            row = c.execute("SELECT * FROM works WHERE title='Die Bergbauern'").fetchone()
            m = json.loads(row['meta'])
            m['suggestions'] = [series('DOK', year=2005)]                           # the Sendung's own series
            m['unknown_before'] = {'title': row['title'], 'kind': 'unknown', 'rev': 2, 'suggestions': m['suggestions']}
            catalog.file_under_sendung(c, row, m, catalog.best_source(c, row['id']), 'DOK', 'contribution')
            old = c.execute("SELECT * FROM works WHERE title='Grenzgänger'").fetchone()
            m2 = json.loads(old['meta'])
            m2['unknown_before'] = {'title': old['title'], 'kind': 'unknown', 'rev': 2, 'suggestions': [series('DOK', year=1954)]}
            catalog.file_under_sendung(c, old, m2, catalog.best_source(c, old['id']), 'DOK', 'contribution')
            self.assertEqual(catalog.unknown_recheck_set_aside(c), 1)
            self.assertEqual(catalog.unknown_recheck_set_aside(c), 0)                 # once
        w = self.works()
        self.assertEqual((w['Die Bergbauern']['kind'], w['Die Bergbauern']['state'], w['Die Bergbauern']['title']),
                         ('unknown', 'review', 'Die Bergbauern'))
        self.assertEqual(w['Die Bergbauern']['meta']['suggestions'][0]['year'], 2005)
        self.assertEqual(w['Grenzgänger']['state'], 'format')                       # weak namesake: stays filed
        info = self.sweep()
        # 0.6.88: the Sendung's own series is no reason to wait any more – the work becomes its Folge (identified,
        # episode search), instead of staying without a kind (before: 'unknown').
        r = self.works()['Die Bergbauern']
        self.assertEqual((r['kind'], r['state'], r['title'], r['meta']['year']), ('series', 'identified', 'DOK', 2005))

    def test_new_rules_run_right_after_the_update(self):
        with self.db() as c:
            catalog.set_state(c, 'unknown_sweep', {'finished': time.time(), 'changed': 26969})      # 0.6.43 summary, no rev
        self.assertIsNotNone(self.service.unknown_sweep())
        self.assertIsNone(self.service.unknown_sweep())                                          # then every 6 h again


class SingleUnderRubricTests(unittest.TestCase):
    """Analyse der Datenbankkopie: 4,684 works only with Wikidata concepts, ZDF "Politik" with fuzzy series names."""
    def check(self, suggestions):
        row = {'attempts': 2, 'state': 'review'}
        return catalog.unknown_soft_check(row, {'suggestions': suggestions}, offer('Fernweh - In den Alpen 5v7', 'Reise', duration=2695), 'single', '', 1)

    def test_series_hits_on_the_rubric_do_not_block_an_einzelsendung(self):
        self.assertIsNone(self.check([{'provider': 'Wikidata', 'kind': 'series', 'title': 'Reise', 'reference_id': 'Q36875808',
                                        'similarity': 1.0, 'confidence': 'possible'}]))
        self.assertIsNone(self.check([{'provider': 'TVDB', 'kind': 'series', 'title': 'POLITI', 'year': 2023, 'similarity': .923},
                                      {'provider': 'TMDB', 'kind': 'series', 'title': 'Politika', 'similarity': .933}]))

    def test_a_film_or_an_exact_series_keeps_it_open(self):
        self.assertEqual(self.check([movie('Fernweh - In den Alpen', similarity=.9)]), 'suggestions_no_sendung')
        self.assertEqual(self.check([series('Mapping the World', year=2017)]), 'suggestions_no_sendung')


class RubricFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = database(self.tmp.name)

    def test_works_under_a_section_are_checked_again(self):
        rows = [offer('Die Erbschaft - Episodio %d' % n, 'Serie e fiction - Serie', channel='ARTE.IT', n=n) for n in range(3)]
        rows += [offer('Il ponte', 'Scienze - In pillole', channel='ARTE.IT', n=10),
                 offer('Echte Folge', 'Puls', n=11), offer('Zweite Folge', 'Puls', n=12)]
        with self.db() as c:
            catalog.initialize(c)
            catalog.ingest(c, rows)
            for r in c.execute('SELECT * FROM works').fetchall():
                m = json.loads(r['meta'])
                src = catalog.best_source(c, r['id'])
                if src['topic'] == 'Serie e fiction - Serie' and src['title'].endswith('0'):
                    # pre-0.6.49 seed: a series named after the section
                    m.update(kind='series', title='Serie e fiction - Serie', episode_title=src['title'])
                    c.execute("UPDATE works SET kind='series',title=?,state='review',attempts=4,meta=? WHERE id=?",
                              ('Serie e fiction - Serie', json.dumps(m), r['id']))
                else:
                    c.execute("UPDATE works SET state='review',attempts=2 WHERE id=?", (r['id'],))
                    r = c.execute('SELECT * FROM works WHERE id=?', (r['id'],)).fetchone()
                    if src['topic'] != 'Scienze - In pillole':
                        # how 0.6.43 filed them: under the section/Sendung as "Folge"
                        catalog.file_under_sendung(c, r, json.loads(r['meta']), src, catalog.cleaned(src['topic']), 'contribution')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM works WHERE kind='series' AND state='format' AND title='Serie e fiction - Serie'").fetchone()[0], 2)
            reopened = catalog.unknown_rubric_fix(c)
            self.assertEqual(reopened, 3)
            rows = {r['title']: r for r in c.execute('SELECT * FROM works')}
            for n in range(3):
                r = rows['Die Erbschaft - Episodio %d' % n]
                self.assertEqual((r['kind'], r['state'], r['attempts'], r['show_key']), ('unknown', 'pending', 0, ''))
            self.assertEqual(rows['Puls']['state'], 'format')                    # real Sendungen stay
            self.assertEqual(catalog.unknown_rubric_fix(c), 0)                   # once


class TvdbStaleHitTests(unittest.TestCase):
    def test_removed_series_is_skipped_not_an_error(self):
        import tvdb

        def request(path, key, pin='', params=None):
            if path == 'search':
                return {'data': [{'tvdb_id': '111', 'name': 'DOK'}, {'tvdb_id': '222', 'name': 'DOK'}]}
            if path == 'series/111/extended':
                raise tvdb.TVDBError(404, 'http')
            return {'data': {'name': 'DOK', 'firstAired': '2001-01-01'}}
        with patch.object(tvdb, 'request', request), patch.object(diagnostics, 'event', lambda *a, **k: None):
            out = metadata.tvdb_candidates({'title': 'Heimweh', 'duration': 1500}, {'title': 'DOK', 'kind': 'series'},
                                           ('k', ''), 'series', 'DOK')
        self.assertEqual([c['reference_id'] for c in out], ['222'])
        self.assertIn('nicht gefunden', str(tvdb.TVDBError(404, 'http')))
        self.assertNotIn('Netzwerk', str(tvdb.TVDBError(404, 'http')))


class RecognitionPanelTests(unittest.TestCase):
    def test_last_result_survives_and_lists_open_reasons(self):
        import server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = database(tmp.name)
        rows = [{'channel': 'SRF', 'works': 10, 'matched': 1, 'identified': 2, 'format': 3, 'open': 4, 'review': 0, 'clips': 0, 'kinds': {}}]
        with db() as c:
            catalog.initialize(c)
            catalog.set_state(c, 'recognition_last', {'at': 1795190000.0, 'rows': rows})
            catalog.set_state(c, 'unknown_sweep', {'finished': 1795190000.0, 'changed': 7, 'remaining_channels': {'SRF': {'suggestions': 4}},
                                                    'remaining_topics': [{'channel': 'SRF', 'topic': 'DOK', 'reason': 'suggestions', 'works': 4}]})
        state = dict(server._RECOGNITION)
        self.addCleanup(lambda: server._RECOGNITION.update(state))
        server._RECOGNITION.update(at=time.monotonic(), rows=[], busy=False, error='', computed=0.0, restored=False)
        with patch.object(server, 'db', db):
            d = server.recognition()
        self.assertEqual(d['channels'], rows)
        self.assertEqual(d['computed_at'], 1795190000.0)
        self.assertEqual(d['unknown']['remaining_channels'], {'SRF': {'suggestions': 4}})
        self.assertEqual(d['unknown']['remaining_topics'][0]['topic'], 'DOK')

    def test_page_shows_the_open_column_and_reasons(self):
        html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8')
        js = (ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
        for part in ('>Art offen</th>', 'id="unknown-reasons"', 'id="unknown-reasons-channels"', 'id="unknown-reasons-topics"'):
            self.assertIn(part, html)
        for part in ('function renderUnknownReasons(u)', 'renderUnknownReasons(d.unknown||{})', "suggestions:'Vorschlag könnte passen'"):
            self.assertIn(part, js)


if __name__ == '__main__':
    unittest.main()
