"""0.6.118 (Mac-Prüfung 0.6.117): E1 Themenwort-Regel traf echte Reihen (Tell-Star, Formel 1, Sonntagsmärchen, Cinema Strikes
Back) und ließ 1.045 „Schwimmen“-Werke unter anderem Thema stehen; E4 „Dein Song 2022“–„2026“ blieben getrennt; E6
„KiKANiNCHEN“/„Kikaninchen“ unter einem show_key; „database is locked“ im Filmlisten-Import."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402
import catalog_service  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        @contextmanager
        def db():
            c = sqlite3.connect(self.root / 'catalog.db');c.row_factory = sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.db = db
        with db() as c:catalog.initialize(c)
        self.svc = catalog_service.Service(db, lambda: {}, threading.Event(), self.root)
        self.n = 0

    def add(self, c, topic, title, channel='ZDF', duration=900):
        self.n += 1
        row = {'title': title, 'topic': topic, 'description': 'x', 'duration': duration, 'channel': channel,
               'url_video': 'https://example.org/%d.mp4' % self.n}
        catalog.ingest(c, [row])
        return c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?", (row['url_video'],)).fetchone()[0]

    def identify(self, c, wid, title, **ident):
        m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
        m.update(kind='series', title=title, episode_title=m.get('title'), **ident)
        catalog.save_metadata(c, wid, m, 'identified')


class RealSeriesStay(Base):
    """E1: echte Reihen bleiben, Themenwörter unter jedem Thema werden neu erkannt."""
    def test_real_series_are_never_reset_sport_word_under_other_topic_is(self):
        with self.db() as c:
            ids = {}
            for i in range(25):ids.setdefault('tell', []).append(self.add(c, 'Tell-Star', 'Tell-Star vom %d. März' % (i + 1), 'SRF'))
            for i in range(25):ids.setdefault('csb', []).append(self.add(c, 'Cinema Strikes Back', 'Film %d im Blick' % i, 'ARTE'))
            for i in range(20):ids.setdefault('sonntag', []).append(self.add(c, 'Sonntagsmärchen', 'Märchen %d' % i, 'KiKA'))
            for i in range(12):ids.setdefault('f1', []).append(self.add(c, 'Formel 1', 'Großer Preis %d' % i, 'RTL'))
            for i in range(6):ids.setdefault('swim', []).append(self.add(c, 'Fußball', 'Bundesliga Spieltag %d' % i))
            for i in range(4):ids.setdefault('swim', []).append(self.add(c, 'Ski alpin', 'Abfahrt %d' % i))
            for w in ids['tell']:self.identify(c, w, 'Tell-Star', provider='Wikidata', reference_id='Q1')
            for w in ids['csb']:self.identify(c, w, 'Cinema Strikes Back', provider='Wikidata', reference_id='Q2')
            for w in ids['sonntag']:self.identify(c, w, 'Sonntagsmärchen', provider='Wikidata', reference_id='Q3')
            for w in ids['f1']:self.identify(c, w, 'Formel 1', provider='TVDB', reference_id='387219')
            for w in ids['swim']:self.identify(c, w, 'Schwimmen', provider='ZDF Mediathek', reference_id='schwimmen-livestreams-ergebnisse-uebertragung-100')
        self.svc.reset_generic_identities()
        with self.db() as c:
            left = {r[0]: r[1] for r in c.execute("SELECT title,COUNT(*) FROM works WHERE state='identified' AND kind='series' GROUP BY title")}
            state = catalog.get_state(c, 'generic_templates_v06118')
        self.assertEqual((left.get('Tell-Star'), left.get('Cinema Strikes Back'), left.get('Sonntagsmärchen'), left.get('Formel 1')),
                         (25, 25, 20, 12))
        self.assertNotIn('Schwimmen', left)
        self.assertEqual(state['works'], 10)

    def test_generic_identity_is_never_a_candidate_unless_imdb_or_tvdb_know_it(self):
        self.assertTrue(catalog.portal_identity({'kind': 'series', 'title': 'Schwimmen', 'provider': 'ZDF Mediathek'}, 'Fußball'))
        self.assertTrue(catalog.portal_identity({'kind': 'series', 'title': 'Sport', 'provider': 'Wikidata'}, ''))
        self.assertFalse(catalog.portal_identity({'kind': 'series', 'title': 'Formel 1', 'provider': 'TVDB', 'reference_id': '387219'}, 'Formel 1'))
        self.assertFalse(catalog.portal_identity({'kind': 'series', 'title': 'Tell-Star', 'provider': 'Wikidata'}, 'Tell-Star'))
        self.assertFalse(catalog.portal_identity({'kind': 'series', 'title': 'Cinema Strikes Back', 'provider': 'Wikidata'}, 'Cinema Strikes Back'))

    def test_undo_of_the_0617_reset_on_test_copies(self):
        with self.db() as c:
            tell = [self.add(c, 'Tell-Star', 'Tell-Star %d' % i, 'SRF') for i in range(5)]
            swim = [self.add(c, 'Fußball', 'Spieltag %d' % i) for i in range(2)]
            for w in tell + swim:
                name = 'Tell-Star' if w in tell else 'Schwimmen'
                m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (w,)).fetchone()[0])
                m['reason'] = catalog.UNDO_GENERIC_REASON % name
                c.execute("UPDATE works SET state='retry',attempts=4,next_try=9e9,meta=? WHERE id=?", (json.dumps(m), w))
            c.execute("UPDATE works SET state='format',kind='other' WHERE id=?", (tell[0],))
            c.execute("UPDATE works SET state='manual' WHERE id=?", (tell[1],))
            catalog.set_state(c, 'generic_templates_v06117', {'works': 7, 'shows': {'Tell-Star': 5, 'Schwimmen': 2}})
        self.svc.reset_generic_identities()
        with self.db() as c:
            st = {r['id']: (r['state'], r['attempts'], r['next_try']) for r in c.execute('SELECT id,state,attempts,next_try FROM works')}
            state = catalog.get_state(c, 'generic_templates_v06118')
        for w in (tell[0], tell[2], tell[3], tell[4]):self.assertEqual(st[w], ('pending', 0, 0))
        self.assertEqual(st[tell[1]][0], 'manual')
        for w in swim:self.assertEqual(st[w][0], 'retry')                   # subject word: no undo
        self.assertEqual(state['undone_v06117'], 4)

    def test_heal_runs_without_0617_state_on_bjoerns_devices(self):
        self.svc.reset_generic_identities()
        with self.db() as c:
            self.assertEqual(catalog.get_state(c, 'generic_templates_v06118')['undone_v06117'], 0)


class YearEditions(Base):
    """E4: „Dein Song 2022“–„2026“ mit 1–6 Werken je Jahr, ZDF und KiKA."""
    def file(self, c, title, channel, n):
        for i in range(n):
            w = self.add(c, title, 'Beitrag %d' % i, channel)
            m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (w,)).fetchone()[0])
            m.update(kind='series', title=title, provider='Sendung')
            c.execute("UPDATE works SET kind='series',state='format',title=?,show_key=?,meta=? WHERE id=?",
                      (title, catalog.showkey({'kind': 'series', 'title': title}), json.dumps(m), w))

    def test_dein_song_years_become_one_reihe(self):
        with self.db() as c:
            for year, ch, n in ((2022, 'KiKA', 1), (2023, 'ZDF', 6), (2024, 'KiKA', 2), (2025, 'ZDF', 1), (2026, 'KiKA', 3)):
                self.file(c, 'Dein Song %d' % year, ch, n)
            moved, merged = catalog.merge_year_editions(c)
            shows = c.execute("SELECT DISTINCT show_key,title FROM works WHERE kind='series'").fetchall()
        self.assertEqual(moved, 13);self.assertEqual(merged, {'Dein Song': [2022, 2023, 2024, 2025, 2026]})
        self.assertEqual([r['title'] for r in shows], ['Dein Song'])

    def test_single_work_of_two_years_is_not_enough(self):
        with self.db() as c:
            self.file(c, 'Sommerfest 2024', 'ZDF', 1);self.file(c, 'Sommerfest 2025', 'ZDF', 1)
            self.assertEqual(catalog.merge_year_editions(c)[0], 0)

    def test_two_years_of_different_senders_stay_apart(self):
        with self.db() as c:
            self.file(c, 'Hafenfest 2024', 'NDR', 3);self.file(c, 'Hafenfest 2025', 'MDR', 3)
            self.assertEqual(catalog.merge_year_editions(c)[0], 0)


class ShowSpelling(Base):
    """E6: eine Schreibweise je Reihe."""
    def test_kikaninchen_takes_the_broadcaster_spelling(self):
        key = catalog.showkey({'kind': 'series', 'title': 'KiKANiNCHEN'})
        with self.db() as c:
            for i in range(5):
                w = self.add(c, 'KiKANiNCHEN', 'Folge %d' % i, 'KiKA')
                title = 'Kikaninchen' if i < 4 else 'KiKANiNCHEN'
                m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (w,)).fetchone()[0])
                m.update(kind='series', title=title, provider='IMDb Offline', reason='Folge von „%s“' % title)
                c.execute("UPDATE works SET kind='series',state='identified',title=?,show_key=?,meta=? WHERE id=?", (title, key, json.dumps(m), w))
            changed = catalog.unify_show_spelling(c)
            rows = c.execute('SELECT title,meta FROM works').fetchall()
        self.assertEqual(changed, {'Kikaninchen': 'KiKANiNCHEN'})
        self.assertEqual({r['title'] for r in rows}, {'KiKANiNCHEN'})
        self.assertTrue(all('„KiKANiNCHEN“' in json.loads(r['meta'])['reason'] for r in rows))

    def test_all_caps_topic_never_wins(self):
        key = catalog.showkey({'kind': 'series', 'title': 'Presseclub'})
        with self.db() as c:
            for i, title in enumerate(('Presseclub', 'Presseclub', 'PRESSECLUB')):
                w = self.add(c, 'PRESSECLUB', 'Ausgabe %d' % i, 'ARD')
                c.execute("UPDATE works SET kind='series',state='format',title=?,show_key=? WHERE id=?", (title, key, w))
            self.assertEqual(catalog.unify_show_spelling(c), {})   # 0.6.119: no brand spelling, nothing changes


class SyncBusy(Base):
    """Sprungtest 0.6.85→0.6.117: „database is locked“ in ingest/set_state/status."""
    def test_import_retries_a_busy_batch_without_double_counting(self):
        path = self.root / 'liste'
        rows = [{'title': 'T%d' % i, 'topic': 'X', 'description': 'x', 'duration': 900, 'channel': 'ZDF',
                 'url_video': 'https://example.org/s%d.mp4' % i} for i in range(3)]
        real = catalog.ingest_incremental;calls = {'n': 0}
        def flaky(c, batch, started, changes):
            calls['n'] += 1
            if calls['n'] == 1:
                changes['added'] += 99
                raise sqlite3.OperationalError('database is locked')
            return real(c, batch, started, changes)
        with patch('filmlist.read_rows', return_value=iter(rows)), patch.object(catalog, 'ingest_incremental', flaky), \
                patch.object(self.svc.stop, 'wait', return_value=False):
            count = self.svc.import_snapshot(path, 0, lambda: False)
        self.assertEqual(count, 3);self.assertGreaterEqual(self.svc.sqlite_busy_by_label.get('sync_ingest'), 1)
        with self.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM offers WHERE active=1').fetchone()[0], 3)

    def test_busy_progress_record_does_not_abort(self):
        @contextmanager
        def busy_db():
            raise sqlite3.OperationalError('database is locked');yield
        self.svc.db = busy_db
        self.svc.status(phase='downloading', received=1)
        self.assertEqual(self.svc.sqlite_busy_by_label.get('sync_status'), 1)


if __name__ == '__main__':
    unittest.main()
