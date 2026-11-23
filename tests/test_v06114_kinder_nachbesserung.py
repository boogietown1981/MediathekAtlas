"""Vorbereitung 0.6.114 (Mac-Prüfung Kinderecke 0.6.113, 23.11.2026):
* Altersweg: „Amore mio – Niemand ist wie Du“ (ARD, Drama/Familie/TV-Film, FSK 6), „Trauung mit Hindernissen“,
  „Oma wider Willen“ (3sat), „Wintertochter“ (RBB) kamen über Familie + FSK. Drama/Fernsehfilm braucht ein eigenes
  Kindersignal (Animation, Märchen, bekannte Kinderreihe), sonst Warteliste. Bibi & Tina und Märchenfilme bleiben.
* K3: „The Beverly Hillbillies“ (JustWatch) öffnete leer.
* Leistung: Neuberechnung 27–32 s statt 7 s (explain je Film las die Genre-Etiketten neu)."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog, kids_catalog, kids_rules  # noqa: E402
from test_v06109_kinder_senderweg import Mixed  # noqa: E402
from test_v0646_kids_catalog import fake_page, portal  # noqa: E402


class AgePath(Mixed):
    def test_adult_family_tv_films_wait_kids_films_stay(self):
        films = (('amore', 'Amore mio – Niemand ist wie Du', ['Drama', 'Familie', 'TV-Film'], 'ARD', ''),
                 ('trauung', 'Trauung mit Hindernissen', ['Komödie', 'Familie', 'TV-Film'], '3sat', ''),
                 ('oma', 'Oma wider Willen', ['Komödie', 'Familie', 'TV Movie'], '3sat', ''),
                 ('winter', 'Wintertochter', ['Drama', 'Familie'], 'RBB', ''),
                 ('liebe', 'Wer hat eigentlich die Liebe erfunden?', ['Drama', 'Familie'], 'ARD', ''),
                 ('bibi', 'Bibi & Tina', ['Familie', 'Komödie'], 'ZDF', ''),
                 ('monate', 'Das Märchen von den zwölf Monaten', ['Familie', 'Fantasy', 'Drama'], 'ARD', ''),
                 ('holle', 'Frau Holle', ['Familie', 'Drama', 'TV-Film'], 'ZDF', 'Märchenperlen'),
                 ('trick', 'Trickfilm-Abenteuer', ['Familie', 'Drama', 'Animation'], 'ARD', ''))
        for i, (wid, title, genres, ch, topic) in enumerate(films):
            self.add(wid, title, genres, ref='tt70000%02d' % i, channel=ch, topic=topic)
        self.ages(**{'tt70000%02d' % i: 6 for i in range(len(films))})
        d = self.data()
        shown = sorted(t['title'] for t in d['movies'])
        self.assertEqual(shown, ['Bibi & Tina', 'Das Märchen von den zwölf Monaten', 'Frau Holle', 'Trickfilm-Abenteuer'])
        self.assertEqual({t['title']: t['weg'] for t in d['movies']}['Bibi & Tina'], 'alter')
        with self.db() as c:
            waiting = {w['title']: w['reason'] for w in kids_rules.waiting(c)}
            for title in ('Amore mio – Niemand ist wie Du', 'Trauung mit Hindernissen', 'Oma wider Willen', 'Wintertochter',
                          'Wer hat eigentlich die Liebe erfunden?'):
                self.assertIn(title, waiting)
                self.assertIn('kein eindeutiger Kinderfilm', waiting[title])
            kids_rules.choose(c, 'work', 'amore', 'allow', 'Amore mio')       # Eltern entscheiden selbst
        self.assertIn('Amore mio – Niemand ist wie Du', [t['title'] for t in self.data()['movies']])

    def test_kika_and_reference_paths_unchanged(self):
        self.add('kika', 'KiKA-Fernsehfilm', ['Drama', 'Familie', 'TV-Film'], channel='KiKA')
        self.add('ref', 'Kinderfilm', ['Kinder', 'Drama'], ref='tt7100001')
        self.assertEqual(sorted(t['title'] for t in self.data()['movies']), ['KiKA-Fernsehfilm', 'Kinderfilm'])


class EmptyPlatformSeries(Mixed):
    def series_page(self):
        return fake_page({'series': [{'cats': ['Kinder'], 'offers': [portal('justwatch', 'ts2949', 'The Beverly Hillbillies',
                                                                            kind='series', playable=1, source_genres=['Kinder'])]},
                                     {'cats': ['Kinder'], 'offers': [portal('pluto', 'pl-1', 'Peppa Wutz', kind='series',
                                                                            source_genres=['Kinder'])]}]})

    def build(self):
        kids_catalog.invalidate()
        return kids_catalog.build(self.root, self.db, page=self.series_page())

    def test_series_opened_empty_is_hidden_and_returns(self):
        d = self.build()
        self.assertEqual(sorted(t['title'] for t in d['series']), ['Peppa Wutz', 'The Beverly Hillbillies'])
        with self.db() as c, mock.patch('portal_title.model', return_value={'episodes': [], 'notes': []}):
            self.assertEqual(kids_catalog.episodes(self.root, c, d, 'justwatch', 'ts2949')['episodes'], [])
        self.assertEqual([t['title'] for t in self.build()['series']], ['Peppa Wutz'])
        with self.db() as c:   # nach Ablauf der Frist neuer Versuch
            c.execute('UPDATE kids_empty_series SET checked=?', (time.time() - kids_catalog.EMPTY_TTL - 1,))
        self.assertEqual(len(self.build()['series']), 2)

    def test_load_error_is_not_remembered(self):
        d = self.build()
        with self.db() as c, mock.patch('portal_title.model', return_value={
                'episodes': [], 'notes': ['Folgen konnten nicht aktualisiert werden: Zeitüberschreitung']}):
            kids_catalog.episodes(self.root, c, d, 'justwatch', 'ts2949')
        self.assertEqual(len(self.build()['series']), 2)

    def test_justwatch_loaded_without_playable_episode(self):
        import justwatch
        db = justwatch._connect(str(self.root))
        with db:
            now = time.time()
            db.execute("INSERT INTO justwatch_items(id,kind,title,series_id,playable,seen,updated) VALUES('te1','episode','Folge 1','ts2949',0,?,?)", (now, now))
            justwatch._set(db, 'series_checked:ts2949', now)
        db.close()
        self.assertEqual(justwatch.series_without_playable(str(self.root), ['ts2949', 'ts1']), {'ts2949'})
        self.assertEqual([t['title'] for t in self.build()['series']], ['Peppa Wutz'])


class Speed(Mixed):
    def test_labels_read_once_per_list(self):
        for i in range(30):
            self.add('f%d' % i, 'Kinderfilm %d' % i, ['Kinder'], channel='ZDF')
        for s in range(10):
            self.series('show:s%d' % s, 'Kinderserie %d' % s, [(3, 'KiKA', [], 'Folge %d')])
        self.data()
        calls = []
        real = catalog.category_labels
        with mock.patch.object(catalog, 'category_labels', side_effect=lambda c: calls.append(1) or real(c)):
            d = self.data()
        self.assertEqual(len(d['movies']), 30)
        self.assertLessEqual(len(calls), 8, len(calls))     # 0.6.113: 1 je Film + 1 je Reihe (≈ 45)


if __name__ == '__main__':
    unittest.main()
