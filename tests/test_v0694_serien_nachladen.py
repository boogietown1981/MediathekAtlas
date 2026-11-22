"""0.6.94: Angefangene Serien automatisch offline laden (series_autoload)."""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import series_autoload
import watch_state


def source(title, show='Bibi und Tina', minutes=25):
    return {'title': title, 'topic': show, 'description': show + ' – ' + title, 'channel': 'ZDF', 'duration': minutes * 60,
            'url_video': 'https://example.org/' + title.replace(' ', '_') + '.mp4'}


class SerienNachladen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.downloads = self.root / 'Downloads'
        self.c = sqlite3.connect(self.root / 'catalog.db')
        self.c.row_factory = sqlite3.Row
        catalog.initialize(self.c)
        self.c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        series_autoload.initialize(self.c)
        self.c.commit()
        self.settings = {'download_dir': str(self.downloads)}
        self.now = time.time()
        self.room = patch('youtube_abos.no_room', return_value='')
        self.room.start()

    def tearDown(self):
        self.room.stop()
        self.c.close()
        self.tmp.cleanup()

    def episode(self, ep, state='matched', show='Bibi und Tina', season=1, minutes=25):
        title = 'Abenteuer Nummer %s %d' % (show, ep)
        catalog.ingest(self.c, [source(title, show, minutes)])
        w = self.c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title')=?",
                           (title,)).fetchone()
        m = json.loads(w['meta'])
        m.update(title=show, kind='series', year=2004, season=season, episode=ep, episode_title=title,
                 episode_verified=state == 'matched', provider='TMDB', reference_id='1')
        new_id = catalog.save_metadata(self.c, w['id'], m, state) or w['id']
        self.c.commit()
        return new_id

    def watch(self, key, at=None):
        watch_state.progress(self.root, key, 1500, 1500, True, now=at or self.now)

    def run_once(self, offset=0, settings=None):
        return series_autoload.run(self.root, self.c, {**self.settings, **(settings or {})}, now=self.now + offset)

    def jobs(self):
        return [json.loads(r[0]) for r in self.c.execute("SELECT payload FROM jobs WHERE state='queued' ORDER BY rowid")]

    def test_zu_ende_gesehene_folge_laedt_die_uebrigen_folgen_der_serie(self):
        ids = [self.episode(n) for n in range(1, 6)]
        self.watch(ids[1])                                  # Folge 2 im großen Player (Schlüssel = Werk)
        result = self.run_once()
        self.assertEqual(result['started'], 1)
        jobs = self.jobs()
        self.assertEqual([j['metadata']['episode'] for j in jobs], [3, 4, 5, 1])   # danach zuerst, dann frühere
        for j in jobs:
            self.assertTrue(j['autoload_show'])
            self.assertEqual(j['autoload_title'], 'Bibi und Tina')
            self.assertTrue(j['source']['_id'])                                      # catalog.mark_downloaded braucht die Angebots-ID
            self.assertTrue(j['source']['_download_url'].startswith('https://'))
        row = series_autoload.status(self.root, self.c, self.settings)['series'][0]
        self.assertEqual((row['state'], row['waiting'], row['last']), ('active', 4, 'S01E02'))
        # zweiter Lauf: nichts doppelt
        self.assertEqual(self.run_once(offset=series_autoload.CHECK_EVERY + 1)['queued'], 0)

    def test_0_6_101_deutsche_fassung_vor_omu_und_hoerfassung(self):
        ids = [self.episode(n) for n in range(1, 3)]
        german = self.c.execute('SELECT id FROM offers WHERE work_id=?', (ids[1],)).fetchone()[0]
        for oid, title, rank in (('omu1', 'Abenteuer 2 (Originalversion mit Untertitel)', 10 ** 9),
                                 ('ad1', 'Abenteuer 2 (Audiodeskription)', 10 ** 9 - 1)):
            row = {'title': title, 'topic': 'Bibi und Tina', 'channel': 'ARTE.DE', 'duration': 1500,
                   'url_video_hd': 'https://example.org/%s_1080p.mp4' % oid}
            self.c.execute('INSERT INTO offers VALUES(?,?,?,?,?,?,1)', (oid, ids[1], json.dumps(row), '', rank, self.now))
        self.c.commit()
        self.watch(ids[0])
        self.run_once()
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['source']['_id'], german)
        self.assertNotIn('omu1', jobs[0]['source']['_download_url'])

    def test_0_6_101_luecke_wird_benannt_und_fenster_fuellt_sich_sofort(self):
        ids = [self.episode(n) for n in (1, 2, 9)] + [self.episode(n) for n in range(20, 60)]
        self.watch(ids[1])
        self.run_once()
        self.assertEqual(len(self.jobs()), 20)                       # Standardgrenze im ersten Lauf
        self.assertEqual(self.jobs()[0]['metadata']['episode'], 9)
        self.assertIn('Nach S01E02 geht es mit S01E09 weiter', self.c.execute('SELECT note FROM series_autoload').fetchone()[0])

    def test_grenze_je_serie_gleitet_mit_gesehenen_folgen(self):
        ids = [self.episode(n) for n in range(1, 9)]
        self.watch(ids[0])
        self.run_once(settings={'series_autoload_max': 5})
        jobs = self.jobs()
        self.assertEqual(len(jobs), 5)
        note = self.c.execute('SELECT note FROM series_autoload').fetchone()[0]
        self.assertIn('Grenze erreicht', note)
        # zwei automatisch geladene Folgen in der Kinderecke zu Ende gesehen (Schlüssel job:<id>)
        self.watch('job:' + jobs[0]['id'], at=self.now + 10)
        self.watch('offer:' + jobs[1]['source']['_id'], at=self.now + 11)
        self.run_once(offset=20, settings={'series_autoload_max': 5})
        self.assertEqual(len(self.jobs()), 7)

    def test_gb_grenze_und_speicherreserve(self):
        ids = [self.episode(n, minutes=90) for n in range(1, 6)]   # je ~2,4 GB geschätzt
        self.watch(ids[0])
        self.run_once(settings={'series_autoload_gb': 5})
        self.assertEqual(len(self.jobs()), 2)
        self.assertIn('5 GB je Serie', self.c.execute('SELECT note FROM series_autoload').fetchone()[0])
        # andere Serie, aber der Downloadordner ist knapp: nichts wird eingereiht, Hinweis bleibt sichtbar
        other = [self.episode(n, show='Löwenzahn') for n in range(1, 3)]
        with patch('youtube_abos.no_room', return_value='Weniger als 5 GB frei am Abo-Speicherort (2.0 GB frei): Abo-Downloads warten, bis wieder Platz ist'):
            self.watch(other[0], at=self.now + 5)
            self.run_once(offset=10)
        note = self.c.execute("SELECT note FROM series_autoload WHERE title='Löwenzahn'").fetchone()[0]
        self.assertIn('Serien-Downloads warten', note)
        self.assertEqual(len(self.jobs()), 2)

    def test_abgebrochene_folge_kommt_nicht_wieder_und_beenden_bricht_wartende_ab(self):
        ids = [self.episode(n) for n in range(1, 5)]
        self.watch(ids[0])
        self.run_once()
        first = self.jobs()[0]
        self.c.execute("UPDATE jobs SET state='cancelled' WHERE id=?", (first['id'],))
        self.c.commit()
        self.run_once(offset=series_autoload.CHECK_EVERY + 1)
        self.assertNotIn(first['metadata']['episode'], [j['metadata']['episode'] for j in self.jobs()])
        show = first['autoload_show']
        result = series_autoload.change(self.c, show, 'stop')
        self.c.commit()
        self.assertEqual(result['cancelled'], 2)
        self.assertEqual(self.jobs(), [])
        self.watch(ids[1], at=self.now + 100)                     # beendete Serie bleibt aus
        self.assertEqual(self.run_once(offset=series_autoload.CHECK_EVERY * 3)['queued'], 0)
        self.assertEqual(self.c.execute('SELECT state FROM series_autoload').fetchone()[0], 'stopped')

    def film(self, title='Das tapfere Schneiderlein', state='matched'):
        catalog.ingest(self.c, [{'title': title, 'topic': 'Sechs auf einen Streich', 'channel': 'ARD', 'description': 'Märchenfilm',
                                 'duration': 3600, 'url_video': 'https://example.org/' + title.replace(' ', '_') + '.mp4'}])
        w = self.c.execute("SELECT w.* FROM works w JOIN offers o ON o.work_id=w.id WHERE json_extract(o.payload,'$.title')=?",
                           (title,)).fetchone()
        m = json.loads(w['meta'])
        m.update(title=title, kind='movie', year=2008, provider='TMDB', reference_id='77' + str(len(title)))
        new_id = catalog.save_metadata(self.c, w['id'], m, state) or w['id']
        self.c.commit()
        return new_id

    def test_zu_ende_gesehener_film_wird_dauerhaft_offline_gespeichert(self):
        film = self.film()
        self.film('Frau Holle')                                    # gleiche Sendereihe: wird nicht mitgeladen
        self.watch('offer:' + self.c.execute('SELECT id FROM offers WHERE work_id=?', (film,)).fetchone()[0])  # Kinderecke
        self.run_once()
        jobs = self.jobs()
        self.assertEqual([(j['metadata']['title'], j['autoload_kind']) for j in jobs], [('Das tapfere Schneiderlein', 'movie')])
        self.assertNotIn('offline_until', jobs[0])                  # keine 30-Tage-Frist
        self.assertEqual(self.c.execute("SELECT state FROM series_autoload WHERE kind='movie'").fetchone()[0], 'done')
        self.watch(film, at=self.now + 50)                          # nochmal gesehen: kein zweiter Auftrag
        self.run_once(offset=60)
        self.assertEqual(len(self.jobs()), 1)

    def test_anbieterkopien_und_ausgeschaltet_loesen_nichts_aus(self):
        film = self.film()
        ids = [self.episode(n) for n in range(1, 3)]
        self.watch('servustv:abc')
        self.watch('pluto:xyz')
        self.run_once()
        self.assertEqual(self.jobs(), [])
        self.watch(film, at=self.now + 1)
        self.run_once(offset=2, settings={'film_autoload': False})
        self.assertEqual(self.jobs(), [])
        self.watch(ids[0], at=self.now + 3)
        self.assertEqual(self.run_once(offset=4, settings={'series_autoload': False}), {'enabled': False})
        self.assertEqual(self.jobs(), [])

    def test_unsicher_erkannter_film_wartet(self):
        film = self.film(state='review')
        self.watch(film)
        self.run_once()
        self.assertEqual(self.jobs(), [])
        self.assertIn('nicht sicher erkannt', self.c.execute('SELECT note FROM series_autoload').fetchone()[0])

    def test_unbestaetigte_folgen_werden_nicht_geraten(self):
        ids = [self.episode(1), self.episode(2, state='identified'), self.episode(3, state='identified')]
        self.watch(ids[0])
        self.run_once()
        self.assertEqual(self.jobs(), [])
        row = series_autoload.status(self.root, self.c, self.settings)['series'][0]
        self.assertEqual(row['unconfirmed'], 2)
        self.assertIn('Folgenerkennung', row['note'])

    def test_erster_start_liest_nur_die_letzten_7_tage(self):
        ids = [self.episode(n) for n in range(1, 3)]
        self.watch(ids[0], at=self.now - 8 * 86400)
        self.assertEqual(self.run_once()['started'], 0)
        self.assertEqual(self.jobs(), [])

    def test_einstellungen_pruefen_erlaubte_werte(self):
        s = series_autoload.clean_settings({'enabled': False, 'max': 10, 'gb': 40}, {})
        self.assertEqual(series_autoload.config(s)['enabled'], False)
        self.assertEqual((s['series_autoload_max'], s['series_autoload_gb']), (10, 40))
        with self.assertRaises(ValueError):
            series_autoload.clean_settings({'max': 1000}, {})
        self.assertTrue(series_autoload.config({})['enabled'])            # Standard an

    def test_diagnose_zaehlt_ohne_titel(self):
        ids = [self.episode(n) for n in range(1, 3)]
        self.watch(ids[0])
        self.run_once()
        out = series_autoload.summary(self.root, self.c, self.settings)
        self.assertEqual(out['series_active'], 1)
        self.assertEqual(out['jobs'], {'queued': 1})
        self.assertEqual(out['finished_7d'], {'werk': 1})
        self.assertNotIn('Bibi', json.dumps(out))


if __name__ == '__main__':
    unittest.main()
