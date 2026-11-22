"""0.6.98 (zuerst als 0.6.98 gebaut): Korrektur nach nicht bestandener Mac-Prüfung von 0.6.91 (22.11.2026).

Die Kinderecke zeigte „Politik“, „NACHTCAFÉ“, „heute“, „Aktuelle Kamera“, „Abendschau“ mit Hunderten Folgen
(Nachrichten, Beiträge über Krankheit und Krieg). Ursachen:
* broadcaster.genres nahm „Kinder“ aus Beschreibung oder Beitragstitel („Wenn Kinder pflegen“): NACHTCAFÉ trug
  in allen 302 Werken „Kinder“, Politik in 11 von 2.047, heute in 16 von 12.005, Abendschau in 2 von 432.
* Eine Reihe stand in der Liste, sobald EIN Werk „Kinder“ trug (schon 0.6.90); 0.6.91 öffnete dann alle Folgen.
"""
import json
import unittest

from test_v0691_kinderecke import Base  # noqa: E402  (tests/ liegt im Suchpfad)
import broadcaster, catalog, kids_catalog  # noqa: E402


class GenreHintTests(unittest.TestCase):
    def test_kids_only_from_programme_name(self):
        self.assertNotIn('Kinder', broadcaster.genres('NACHTCAFÉ', 'NACHTCAFÉ', 'Wenn Kinder ihre Eltern pflegen',
                                                      names=('NACHTCAFÉ', 'NACHTCAFÉ')))
        self.assertNotIn('Kinder', broadcaster.genres('Abendschau', 'Kinderarmut in Berlin', names=('Abendschau',)))
        self.assertIn('Kinder', broadcaster.genres('Die Sendung mit der Maus', 'Die Sendung mit der Maus', 'Lach- und Sachgeschichten',
                                                   names=('Die Sendung mit der Maus', 'Die Sendung mit der Maus')))
        self.assertEqual(broadcaster.genres('logo!', 'Kindernachrichten', names=('logo!', 'logo! Nachrichten für Kinder'))[0], 'Kinder')


class ShowTests(Base):
    BAD = ('Politik', 'NACHTCAFÉ', 'heute', 'Aktuelle Kamera', 'Abendschau')

    def series(self, show, title, n, kids, other=('Nachrichten',), channel='Das Erste', topic=''):
        for i in range(n):
            genres = ['Kinder'] if i < kids else list(other)
            self.add('%s-%d' % (show, i), '%s %d' % (title, i), genres, kind='series', show=show, season=1, episode=i + 1,
                     channel=channel, topic=topic or title)
        with self.db() as c:
            c.execute("UPDATE works SET title=?, meta=json_set(meta,'$.title',?) WHERE show_key=?", (title, title, show))

    def test_news_talk_and_magazine_series_stay_out(self):
        self.series('show:politik', 'Politik', 40, 2, other=('Talk',))
        self.series('show:nachtcafe', 'NACHTCAFÉ', 30, 30)                 # alle Werke fälschlich „Kinder“
        self.series('show:heute', 'heute', 60, 3)
        self.series('show:kamera', 'Aktuelle Kamera', 20, 2, other=('Dokumentation',))
        self.series('show:abendschau', 'Abendschau', 40, 2, other=('Magazin',))
        self.series('show:maus', 'Die Sendung mit der Maus', 20, 18, other=('Dokumentation',))
        self.series('show:logo', 'logo!', 10, 10)
        self.series('show:kika', 'Schloss Einstein', 6, 0, other=(), channel='KiKA')
        self.series('show:wissen', 'Planet Wissen', 30, 3, other=('Dokumentation',))
        self.series('show:loewe', 'Wolkenwald', 10, 9)                      # eine Nachrichten-Folge darin
        data = self.shelf()
        titles = sorted(t['title'] for t in data['series'])
        for bad in self.BAD + ('Planet Wissen',):
            self.assertNotIn(bad, titles)
        self.assertEqual(titles, ['Die Sendung mit der Maus', 'Schloss Einstein', 'Wolkenwald', 'logo!'])
        with self.db() as c:
            # Maus: alle 20, auch Doku-Folgen – die Reihe „Die Sendung mit der Maus“ ist selbst das Kinder-Signal
            self.assertEqual(len(kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:maus')['episodes']), 20)
            eps = kids_catalog.episodes(self.root, c, data, 'mediatheken', 'show:loewe')['episodes']
            self.assertEqual(len(eps), 9)                                  # Nachrichten-Folge ohne Kinder-Einordnung nicht
            for bad in ('show:politik', 'show:heute', 'show:nachtcafe'):
                self.assertEqual(kids_catalog.excluded_works(c, bad), {r[0] for r in c.execute('SELECT id FROM works WHERE show_key=?', (bad,))})
                with self.assertRaises(ValueError):
                    kids_catalog.episodes(self.root, c, data, 'mediatheken', bad)

    def test_name_rule(self):
        for name in self.BAD + ('heute 19:00 Uhr', 'BRISANT', 'frontal', 'DW Nachrichten', 'Best of ZIB 2', 'Hamburg Journal',
                                'CRISIS - Hinter der Front', '3nach9', 'extra 3', 'phoenix review', 'Schlager–Spaß mit Andy Borg',
                                'Landesschau Rheinland-Pfalz', 'mex', 'Kinder-Talk'):
            self.assertTrue(kids_catalog.show_name_blocked(name), name)
        for name in ('logo!', 'Die Sendung mit der Maus', 'KiKA Live', 'Checker Tobi', 'Schloss Einstein', 'Löwenzahn'):
            self.assertFalse(kids_catalog.show_name_blocked(name), name)


class HealTests(Base):
    def test_derived_kids_genre_removed_unless_name_or_channel(self):
        def derived(wid, title, show, channel='SWR', topic=None):
            self.add(wid, title, ['Kinder', 'Talk'], kind='series', show=show, channel=channel, topic=topic or show)
            with self.db() as c:
                m = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
                m.update(genre_source='Sender (abgeleitet)', title=show)
                c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(m), wid))
        derived('nc', 'Wenn Kinder pflegen', 'NACHTCAFÉ')
        derived('maus', 'Lachgeschichte', 'Die Sendung mit der Maus')
        derived('kika', 'Folge', 'Schloss Einstein', channel='KiKA')
        self.add('tmdb', 'Film', ['Kinder'])                                # Referenz-Genre bleibt
        with self.db() as c:
            self.assertEqual(catalog.heal_derived_kids_v0696(c), 1)
            self.assertEqual(catalog.heal_derived_kids_v0696(c), 0)          # nur einmal
            genres = {wid: sorted(r[0] for r in c.execute('SELECT genre FROM work_genres WHERE work_id=?', (wid,)))
                      for wid in ('nc', 'maus', 'kika', 'tmdb')}
            self.assertEqual(json.loads(c.execute("SELECT meta FROM works WHERE id='nc'").fetchone()[0])['genres'], ['Talk'])
        self.assertEqual(genres, {'nc': ['Talk'], 'maus': ['Kinder', 'Talk'], 'kika': ['Kinder', 'Talk'], 'tmdb': ['Kinder']})


if __name__ == '__main__':
    unittest.main()
