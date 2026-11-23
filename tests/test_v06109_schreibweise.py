"""0.6.109: Schreibweise der Reihen nach der Mac-Prüfung A1 (0.6.106): 29.878 Werke, 137 Namen umgeschrieben, rund die
Hälfte schlechter (Programmschienen in Großschreibung gewannen). Jetzt nur ganz groß/ganz klein → gemischt, ganz groß nur
zu einer stilisierten Markenschreibung; die geänderten Paare werden gespeichert."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

import catalog
import catalog_service
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_diagnosis_fixes import database  # noqa: E402

BETTER = [('kulturzeit', 'Kulturzeit'), ('KIKA LIVE', 'KiKA LIVE'), ('scobel', 'Scobel'), ('maischberger', 'Maischberger')]
WORSE = [('MDR Sachsenspiegel', 'MDR SACHSENSPIEGEL'), ('ZDFinfo Doku', 'ZDFinfo doku'), ('phoenix runde', 'PHOENIX RUNDE'),
         ('Report Mainz', 'REPORT MAINZ'), ('WimS', 'Wims'), ('unter den linden', 'UNTER DEN LINDEN'), ('Presseclub', 'PRESSECLUB'),
         ('gesundheitheute', 'GESUNDHEITHEUTE'), ('ECO Talk', 'Eco Talk'), ('SingAlarm', 'Singalarm'), ('Respekt', 'RESPEKT'),
         ('Schweizweit', 'SCHWEIZWEIT'), ('BesserEsser', 'Besseresser'), ('UNBUBBLE', 'Unbubble'), ('Ich bin ich', 'ICH bin ICH'),
         ('Heimatjournal', 'HEIMATJOURNAL'), ('Erlebnis Hessen', 'erlebnis hessen'), ('Puls', 'PULS'), ('Makro', 'makro')]
NEUTRAL = [('Nano', 'nano'), ('PUR+', 'pur+'), ('Alles Wissen', 'alles wissen'), ('Auslandsjournal', 'auslandsjournal'),
           ('Extra 3', 'extra 3'), ('Live nach neun', 'Live nach Neun')]


class RuleTests(unittest.TestCase):
    def test_mac_a1_pairs(self):
        for old, new in BETTER:
            self.assertEqual(catalog.broadcaster_spelling(old, new), new, old)
        for old, new in WORSE + NEUTRAL:
            self.assertIsNone(catalog.broadcaster_spelling(old, new), old)


class HealTests(unittest.TestCase):
    def test_heal_keeps_pairs_and_counts_right(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        db = database(tmp.name)
        with db() as c:
            catalog.initialize(c)
            n = 0
            for old, new in [('kulturzeit', 'Kulturzeit'), ('Presseclub', 'PRESSECLUB')]:
                for i in range(6):
                    n += 1
                    m = {'kind': 'series', 'title': old, 'episode_title': 'F%d' % i}
                    topic = new if i < 4 else old        # the broadcaster mostly writes it this way
                    c.execute("INSERT INTO works(id,title,kind,show_key,meta,state,topic) VALUES(?,?,?,?,?,?,?)",
                              ('w%d' % n, old, 'series', 'show:' + old, json.dumps(m), 'identified', topic))
        svc = catalog_service.Service(db, lambda: {}, threading.Event(), Path(tmp.name))
        svc.heal_series_names()
        with db() as c:
            titles = {r[0]: r[1] for r in c.execute("SELECT show_key,MIN(title) FROM works GROUP BY 1")}
            self.assertEqual(titles, {'show:kulturzeit': 'Kulturzeit', 'show:Presseclub': 'Presseclub'})
            st = catalog.get_state(c, 'series_spelling_v06109')
        self.assertEqual(st['spelled'], 6)
        self.assertEqual([tuple(p) for p in st['pairs']], [('show:kulturzeit', 'kulturzeit', 'Kulturzeit')])


if __name__ == '__main__':
    unittest.main()
