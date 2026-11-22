"""0.6.107 (Mac-Prüfung 0.6.105, 22.11.2026): grundsätzliche Zulassung der Kinderecke.

0.6.105 zeigte u. a. „Generation Porno - Was unsere Kinder online sehen“, „Die Kinder von Lügde“, „Geheimsache Doping:
Kinder“ (Folge „Täter“), „Sex and the Scientists · Wie wir künftig Kinder kriegen“, „Ein Herz für Kinder“, „KRIMI.DE“,
„#Ukraine · Mein Land im Krieg“ und eine Folge „Verhütung“. Ursache: das Wort „Kinder“ im Reihen-/Themennamen und das
daraus abgeleitete Genre „Kinder“ (broadcaster.GENRE_HINTS) galten als Kindersignal.

Jetzt automatisch nur: (a) Angebot eines Kindersenders (KiKA, TOGGO, ZDFtivi), (b) gepflegte Kinderreihe
(catalog.KIDS_SHOWS), (c) Altersweg mit Familie (0.6.105), (d) Elternfreigabe. Alles andere wartet auf Freigabe.
Dazu eine Wortsperre (kids_catalog.BAD_WORDS) für Titel und Folgentitel, ausgenommen Kindersender und Elternfreigabe.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import catalog, kids_catalog, kids_rules  # noqa: E402
from test_v0699_kinder_freigabe import Base  # noqa: E402

DERIVED = 'Sender (abgeleitet)'


class Admission(Base):
    def add_derived(self, wid, title, topic, state='format', kind='movie', show=None, channel='ARD', episode=None):
        """Wie auf der Prüfkopie: Genre „Kinder“ nur aus dem Sendernamen abgeleitet, Thema mit „Kinder“."""
        import json
        self.add(wid, title, ['Kinder', 'Dokumentation'], kind=kind, show=show, state=state, channel=channel, topic=topic,
                 episode=episode)
        with self.db() as c:
            meta = json.loads(c.execute('SELECT meta FROM works WHERE id=?', (wid,)).fetchone()[0])
            meta['genre_source'] = DERIVED
            c.execute('UPDATE works SET meta=? WHERE id=?', (json.dumps(meta), wid))


class RejectedTitles(Admission):
    """Alle gemeldeten Titel: auf 0.6.105 sichtbar, jetzt draußen."""
    CASES = [
        ('porno', 'Generation Porno - Was unsere Kinder online sehen', 'Generation Porno - Was unsere Kinder online sehen'),
        ('luegde', 'Die Kinder von Lügde', 'Die Kinder von Lügde'),
        ('sex', 'Sex and the Scientists · Wie wir künftig Kinder kriegen', 'Sex and the Scientists'),
        ('herz', 'Ein Herz für Kinder', 'Ein Herz für Kinder'),
        ('roma', 'Jenny und die Roma-Kinder', 'Jenny und die Roma-Kinder'),
        ('unsere', '#unsereKinder – wie kinderfreundlich ist Deutschland?', '#unsereKinder'),
        ('krimide', 'KRIMI.DE', 'Filme für Kinder'),
        ('ukraine', '#Ukraine · Mein Land im Krieg', 'Dokus für Kinder'),
        ('aerzte', 'Kinderärzte im Einsatz', 'Kinderärzte im Einsatz'),
        ('armut', 'Kinderarmut in Deutschland', 'Kinderarmut in Deutschland'),
        ('musik', 'Klassische Musik für Kinder', 'Klassische Musik für Kinder'),
    ]

    def test_not_shown(self):
        for wid, title, topic in self.CASES:      # erkannt (so auf 0.6.105 sichtbar) und als Sendungsformat (Erkennung 0.6.106)
            self.add_derived(wid + '-i', title, topic, state='identified')
            self.add_derived(wid + '-f', title, topic, state='format')
        self.add_derived('d1', 'Kinder', 'Geheimsache Doping: Kinder', kind='series', show='show:doping', episode=1, state='identified')
        self.add_derived('d3', 'Täter (S01/E03)', 'Geheimsache Doping: Kinder', kind='series', show='show:doping', episode=3, state='identified')
        self.assertEqual(self.titles(), [])

    def test_waiting_instead(self):
        """Nicht verloren: Kandidaten mit „Kinder“ im Thema landen in „Wartet auf Freigabe“."""
        self.add_derived('herz', 'Ein Herz für Kinder', 'Ein Herz für Kinder')
        self.add_derived('musik', 'Klassische Musik für Kinder', 'Klassische Musik für Kinder')
        with self.db() as c:
            ids = {w['id'] for w in kids_rules.waiting(c)}
        self.assertTrue({'herz', 'musik'} <= ids, ids)

    def test_identified_derived_genre(self):
        """Auch ein erkanntes Werk kommt nicht allein über das abgeleitete Genre „Kinder“ hinein."""
        self.add_derived('ident', 'Jenny und die Roma-Kinder', 'Reportage', state='identified')
        self.add_derived('matched', 'Ein Herz für Kinder', 'Gala', state='matched')
        self.assertEqual(self.titles(), [])

    def test_words(self):
        for title in ('Generation Porno', 'Die Kinder von Lügde', 'Geheimsache Doping: Kinder', 'Täter (S01/E03)',
                      'Sex and the Scientists', 'KRIMI.DE', '#Ukraine · Mein Land im Krieg', 'Verhütung',
                      'Missbrauch in der Kirche', 'Krebs bei Kindern', 'Mord im Dorf'):
            self.assertTrue(kids_catalog.word_blocked(title), title)
        for title in ('Die Sendung mit der Maus', 'Sesamstraße', 'Bibi & Tina', 'Pettersson und Findus',
                      'Das Märchen von den zwölf Monaten', 'Wissen macht Ah!'):
            self.assertFalse(kids_catalog.word_blocked(title), title)


class Kontrollen(Admission):
    """Positive Kontrollen: was hinein gehört, bleibt drin."""

    def test_curated_shows(self):
        for wid, title, topic, state in (
                ('maus', 'Die Sendung mit der Maus vom 22.11.', 'Die Sendung mit der Maus', 'format'),
                ('sand', 'Unser Sandmännchen: Pittiplatsch', 'Unser Sandmännchen', 'identified'),
                ('checker', 'Der Wald-Check', 'Checker Tobi', 'format'),
                ('anna', 'Der Biber', 'Anna und die wilden Tiere', 'identified')):
            self.add_derived(wid, title, topic, state=state, channel='Das Erste')
        self.assertEqual(self.titles(), ['Der Biber', 'Der Wald-Check', 'Die Sendung mit der Maus vom 22.11.',
                                         'Unser Sandmännchen: Pittiplatsch'])

    def test_kika_exempt_from_words(self):
        self.add('krieg', 'Der Krieg und ich', ['Drama'], channel='KiKA', state='retry')
        self.add('krimi', 'KRIMI.DE', ['Krimi'], channel='KiKA', state='retry')
        self.assertEqual(self.titles(), ['Der Krieg und ich', 'KRIMI.DE'])

    def test_age_path_family(self):
        self.add('pixar', 'Pixar-Film', ['Familie', 'Animation'], ref='tt2000001')
        self.add('bibi', 'Bibi & Tina', ['Familie', 'Komödie'], ref='tt2000002')
        self.add('doku', 'Kinder der Steppe', ['Dokumentation'], ref='tt2000003')     # kein Familiensignal
        self.ages(tt2000001=0, tt2000002=0, tt2000003=0)
        self.assertEqual(self.titles(), ['Bibi & Tina', 'Pixar-Film'])

    def test_parents_allow_lifts_word_block(self):
        self.add_derived('herz', 'Ein Herz für Kinder', 'Ein Herz für Kinder')
        self.add_derived('porno', 'Generation Porno - Was unsere Kinder online sehen', 'Generation Porno')
        with self.db() as c:
            kids_rules.choose(c, 'work', 'herz', 'allow', 'Ein Herz für Kinder')
            kids_rules.choose(c, 'work', 'porno', 'allow', 'Generation Porno')
        self.assertEqual(self.titles(), ['Ein Herz für Kinder', 'Generation Porno - Was unsere Kinder online sehen'])


class TopicRule(unittest.TestCase):
    def test_kinder_in_name_is_no_signal(self):
        for topic in ('Kinderfilme', 'Kinderserien', 'Ein Herz für Kinder', 'Kinderärzte im Einsatz', 'Filme für Kinder',
                      'Geheimsache Doping: Kinder', '#unsereKinder', 'Märchen der Welt'):
            self.assertIsNone(catalog.KIDS_TOPIC.search(topic), topic)
        for topic in ('Die Sendung mit der Maus', 'Unser Sandmännchen', 'Checker Tobi', 'Paula und die wilden Tiere',
                      'Sechs auf einen Streich', 'Sesamstraße', 'Löwenzahn', 'logo!', 'Schloss Einstein'):
            self.assertIsNotNone(catalog.KIDS_TOPIC.search(topic), topic)

    def test_name_block_without_kinder_exemption(self):
        self.assertTrue(kids_catalog.show_name_blocked('Kinder-Talk'))
        self.assertFalse(kids_catalog.show_name_blocked('logo!'))


if __name__ == '__main__':
    unittest.main()
