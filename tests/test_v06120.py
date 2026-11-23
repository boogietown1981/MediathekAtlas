"""0.6.120 (Mac-Prüfung 0.6.119): ARD/MDR „Mittagsmagazin“ bekam SRFs „MittagsMagazin“ (ein show_key über Sender hinweg);
3 „Kikaninchen“ (Ausschnitte, kind 'other') blieben unter dem KiKANiNCHEN-Schlüssel."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog  # noqa: E402


class SenderSpelling(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.c = sqlite3.connect(Path(tmp.name) / 'catalog.db');self.c.row_factory = sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c);self.n = 0

    def add(self, topic, work_title, channel, show, kind='series', state='format'):
        self.n += 1
        url = 'https://example.org/%d.mp4' % self.n
        catalog.ingest(self.c, [{'title': 'Ausgabe %d' % self.n, 'topic': topic, 'description': 'x', 'duration': 900,
                                 'channel': channel, 'url_video': url}])
        wid = self.c.execute("SELECT work_id FROM offers WHERE json_extract(payload,'$.url_video')=?", (url,)).fetchone()[0]
        m = json.loads(self.c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
        m.update(kind=kind, title=work_title)
        self.c.execute('UPDATE works SET title=?,kind=?,state=?,show_key=?,meta=? WHERE id=?', (work_title, kind, state, show, json.dumps(m), wid))
        return wid

    def titles(self, channel):
        return {r[0] for r in self.c.execute("""SELECT DISTINCT w.title FROM works w JOIN offers o ON o.work_id=w.id
            WHERE json_extract(o.payload,'$.channel')=?""", (channel,))}

    def test_other_senders_keep_their_spelling(self):
        show = catalog.showkey({'kind': 'series', 'title': 'Mittagsmagazin'})
        for _ in range(3):self.add('MittagsMagazin', 'MittagsMagazin', 'SRF', show)
        for _ in range(4):self.add('Mittagsmagazin', 'Mittagsmagazin', 'ARD', show)
        for _ in range(2):self.add('Mittagsmagazin', 'Mittagsmagazin', 'MDR', show)
        self.assertEqual(catalog.unify_show_spelling(self.c), {})
        self.assertEqual((self.titles('ARD'), self.titles('MDR'), self.titles('SRF')),
                         ({'Mittagsmagazin'}, {'Mittagsmagazin'}, {'MittagsMagazin'}))

    def test_same_sender_still_gets_the_brand_also_for_extras(self):
        show = catalog.showkey({'kind': 'series', 'title': 'KiKANiNCHEN'})
        for _ in range(3):self.add('KiKANiNCHEN', 'Kikaninchen', 'KiKA', show, state='identified')
        extra = self.add('KiKANiNCHEN', 'Kikaninchen', 'KiKA', show, kind='other')
        other = self.add('Kikaninchen', 'Kikaninchen', 'ARD', show)
        self.assertEqual(catalog.unify_show_spelling(self.c), {'Kikaninchen': 'KiKANiNCHEN'})
        self.assertEqual(self.c.execute('SELECT title FROM works WHERE id=?', (extra,)).fetchone()[0], 'KiKANiNCHEN')
        self.assertEqual(self.c.execute('SELECT title FROM works WHERE id=?', (other,)).fetchone()[0], 'Kikaninchen')


if __name__ == '__main__':
    unittest.main()
