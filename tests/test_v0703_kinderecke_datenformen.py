"""0.6.103: Kinderecke leer und Live-Sender mit „'str' object has no attribute 'get'“ (Björn, 22.11.2026, 0.6.99).

Ursache (Traceback aus dem echten Log): kids_catalog._signals las ``item['source'].get('topic')``; bei Titeln anderer
Portale ist ``item['source']`` ein Text (Quellenname). Ein einziger solcher Titel leerte die ganze Liste, und
/api/kids-play (Live-Sender) scheiterte am selben Aufbau. Fehler seit den Gruppen (0.6.93), auch in 0.6.98.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kids_catalog  # noqa: E402


def pluto(i, source):
    return {'title': 'Film %d' % i, 'offers': [{'source': 'pluto', 'item': {
        'id': 'pluto-%d' % i, 'title': 'Film %d' % i, 'kind': 'movie', 'playable': 1, 'source': source,
        'metadata': 'kein Objekt' if i == 3 else None, 'categories': ['Kinder', {'x': 1}]}}]}


class DataShapeTests(unittest.TestCase):
    def test_text_none_and_dict_sources_never_empty_the_list(self):
        entries = [pluto(1, 'Pluto TV'), pluto(2, None), pluto(3, {'topic': 'Märchen'}), pluto(4, 7),
                   {'title': 'kaputt', 'offers': 'kein Angebot'}, 'kein Eintrag',
                   {'title': 'Mediathek', 'offers': [{'source': 'mediatheken', 'item': {
                       'id': 'o1', 'available': 1, 'source': 'ARD', 'metadata': {'title': 'Mediathekfilm'}}}]}]

        def page(root, db, kind='movies', genre='', offset=0, **kw):
            rows = entries if kind == 'movies' else []
            return {'items': rows[offset:offset + 48], 'total': len(rows), 'pending': []}
        data = kids_catalog.build('/r', None, page=page)
        self.assertEqual(sorted(t['title'] for t in data['movies']), ['Film 1', 'Film 2', 'Film 3', 'Film 4', 'Mediathekfilm'])
        self.assertEqual(kids_catalog.group_of(pluto(3, {'topic': 'Märchen'})), 'maerchen')   # Objekt wird weiter gelesen
        self.assertEqual(kids_catalog.group_of(pluto(1, 'Märchen-Portal')), 'mehr')              # Text nicht als Objekt

    def test_signals_with_odd_shapes(self):
        cats, text = kids_catalog._signals({'title': 'X', 'offers': [None, 'x', {'item': 'x'}, {'item': {'source': 'Pluto', 'metadata': 'y'}}]})
        self.assertEqual(cats, set())
        self.assertTrue(text.startswith('X'))


from test_v0691_kinderecke import Base  # noqa: E402


class KikaSeriesTests(Base):
    """Mac-Prüfung 0.6.98 (geflickte Kopie): KiKA-Reihen fehlten an Anteil oder Namenssperre."""
    def series(self, show, title, n, kids, channel, other=('Dokumentation',)):
        for i in range(n):
            self.add('%s-%d' % (show, i), '%s %d' % (title, i), ['Kinder'] if i < kids else list(other), kind='series',
                     show=show, episode=i + 1, channel=channel if i % 2 == 0 else 'WDR')
        with self.db() as c:
            c.execute("UPDATE works SET title=?, meta=json_set(meta,'$.title',?) WHERE show_key=?", (title, title, show))

    def test_kika_before_share_and_name(self):
        self.series('show:wma', 'Wissen macht Ah!', 25, 12, 'KiKA')           # 48 % – KiKA zählt vor dem Anteil
        self.series('show:krieg', 'Der Krieg und ich', 6, 3, 'KiKA', other=('Historie',))
        self.series('show:kikalive', 'KiKA LIVE', 4, 0, 'KiKA', other=('Talk',))
        self.series('show:heute', 'heute', 20, 2, 'ZDF', other=('Nachrichten',))
        titles = sorted(t['title'] for t in self.shelf()['series'])
        self.assertEqual(titles, ['Der Krieg und ich', 'KiKA LIVE', 'Wissen macht Ah!'])
        self.assertFalse(kids_catalog.show_name_blocked('Der Krieg und ich'))


if __name__ == '__main__':
    unittest.main()
