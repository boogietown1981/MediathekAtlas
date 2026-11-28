"""0.6.166 – Mac-Prüfung 0.6.165 und Messung Teil C (27.11.2026):
* TMNT bei Pluto: dieselbe Folge (gleicher Titel, gleiche Dauer) zweimal INNERHALB einer Reihe (S3E1/S3E324) – jetzt einmal.
* Diagnose: nach „Zurücknehmen“ meldet kids_undo_result, ob die Reihe wieder da ist und sonst warum; kids_list_changed nennt je weggefallener Kachel den Grund (keine_zulassung, keine_folge:<Weg>, nicht_im_katalog).
* Netzkino: 3.944 von 3.958 Filmen ohne Beschreibung, aber 3.752 gespeicherte Filmdetails – die Beschreibung (und fehlendes
  Jahr/FSK) kommt aus dem Detailspeicher in den Katalog, ohne vorhandene Werte zu überschreiben."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kids_catalog as kc
import netzkino
import netzkino_details as nd
from test_v06164 import show, ep, run


class WithinSeriesTests(unittest.TestCase):
    def test_same_title_same_length_within_one_series_once(self):
        parts = {'t': [ep('pluto', 'a', 'Ein Dino kommt selten allein', 3, 1, 1350),
                       ep('pluto', 'b', 'Ein Dino kommt selten allein', 3, 324, 1350),
                       ep('pluto', 'c', 'Fremde Welten', 4, 1, 1350), ep('pluto', 'd', 'Fremde Welten', 4, 401, 1100)]}
        head = show('t', 'TMNT')
        self.assertEqual([e['title'] for e in run(head, parts)], ['Ein Dino kommt selten allein', 'Fremde Welten', 'Fremde Welten'])


class DropReasonTests(unittest.TestCase):
    def test_removed_titles_carry_reason(self):
        events = []
        old = {'movies': [], 'series': [{'id': 'mediatheken:h', 'title': 'Heidi', 'source': 'mediatheken'},
                                        {'id': 'pluto:x', 'title': 'X', 'source': 'pluto'}]}
        with mock.patch.dict(kc.DROPPED, {'mediatheken:h': 'keine_zulassung'}, clear=True), \
                mock.patch('diagnostics.event', side_effect=lambda name, *a, **f: events.append(f)):
            kc._log_change(old, {'movies': [], 'series': []})
        removed = events[0]['removed_titles']
        self.assertTrue(any('Heidi' in r and 'keine_zulassung' in r for r in removed), removed)
        self.assertTrue(any(r.startswith('X ') and 'nicht_im_katalog' in r for r in removed), removed)


    def test_undo_reports_whether_title_is_back(self):
        import sqlite3, kids_rules
        c = sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        kids_rules.ensure(c)
        kids_rules.choose(c, 'show', 'h', 'block', 'Heidi')
        events = []
        with mock.patch.dict(kc._CACHE, {}, clear=True):
            kc.apply_to_twins(c, '/r', 'show', 'h', '', 'Heidi')
        self.assertIn(('heidi', 'mediatheken:h'), kc.UNDONE)
        with mock.patch.dict(kc.DROPPED, {'mediatheken:h': 'keine_zulassung'}, clear=True), \
                mock.patch.dict(kc.DROPPED_TITLES, {'mediatheken:h': 'heidi'}, clear=True), \
                mock.patch('diagnostics.event', side_effect=lambda name, *a, **f: events.append((name, f))):
            kc._report_undone({'movies': [{'id': 'netzkino:f', 'title': 'Heidi'}], 'series': []})
        self.assertEqual(events[0][0], 'kids_undo_result')
        self.assertEqual((events[0][1]['back'], events[0][1]['reasons']), (False, ['mediatheken:h=keine_zulassung']))
        self.assertEqual(events[0][1]['same_title'], ['netzkino:f'])          # gleichnamiger Film zählt nicht als zurück
        self.assertFalse(kc.UNDONE)


class NetzkinoDescriptionTests(unittest.TestCase):
    def test_details_fill_empty_catalogue_fields_once(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db = netzkino._connect(root)
        db.executescript(nd.SCHEMA)
        with db:
            for i, (summary, year) in enumerate((('', None), ('Eigene Beschreibung', 1999))):
                db.execute("INSERT INTO netzkino_catalog(id,title,url,source,confidence,created,updated,kind,year,summary) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?)", (('%032x' % i), 'Film %d' % i, 'https://www.netzkino.de/details/f%d' % i,
                                                         'graphql', 1, 0, 0, 'movie', year, summary))
                db.execute('INSERT INTO netzkino_public_details VALUES(?,?,?)', ('%032x' % i, json.dumps(
                    {'description': 'Text aus den Details %d' % i, 'year': 2001, 'fsk': 6}), 0))
        db.close()
        nd._FILLED.discard(str(root.resolve()))
        db = nd._connect(root)
        rows = {r['id']: dict(r) for r in db.execute('SELECT id,summary,year,fsk FROM netzkino_catalog')}
        db.close()
        self.assertEqual(rows['%032x' % 0]['summary'], 'Text aus den Details 0')
        self.assertEqual((rows['%032x' % 0]['year'], rows['%032x' % 0]['fsk']), (2001, 6))
        self.assertEqual((rows['%032x' % 1]['summary'], rows['%032x' % 1]['year']), ('Eigene Beschreibung', 1999))
        self.assertIn(str(root.resolve()), nd._FILLED)


if __name__ == '__main__':
    unittest.main()
