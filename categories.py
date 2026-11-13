"""Einheitliche deutsche Kategorien für Filme und Serien aller Quellen (0.5.83).

Jeder Anbieter bringt eigene Genre-Bezeichnungen mit (ARD/ZDF, Netzkino, Pluto TV, JustWatch, Rakuten,
YouTube, Joyn sowie die Referenzen IMDb/TMDB/TVDB/Wikidata). Als Kategorie-Chips führte das zu Dubletten
(„Fantasie“/„Fantasy“, „Krimi“/„Kriminalfilms“), Mischsprachen und vielen Einzeltreffern.

Regeln (Björn, 13.11.2026):

* Die Rohgenres der Anbieter bleiben als Quelle gespeichert (work_genres, Portal-Spalte ``genre``).
* Angezeigt und gefiltert wird nur noch nach einer festen deutschen Liste ``CATEGORIES``.
* Eine Kategorie gibt es erst nach dem Abgleich der Metadaten. Vorher steht ein Titel unter
  ``UNCLASSIFIED`` („Unklassifiziert“). Nach dem Abgleich zählen die Genres der Referenz zuerst, die
  Anbieter-Genres als Ergänzung; passt keines, steht der Titel unter ``OTHER`` („Sonstige“).

Das Modul hat keine Abhängigkeiten und wird von catalog.py (ARD, ZDF & Co.), portal_reference.py
(alle Plattformen) und der Oberfläche (``/api/categories``) gemeinsam genutzt.
"""
from __future__ import annotations

import re

UNCLASSIFIED = 'Unklassifiziert'
OTHER = 'Sonstige'
# Ältere Stände zeigten 'Unbekannt'; als Filterwert weiter verstanden (gespeicherte Ansichten, Links).
LEGACY_UNKNOWN = 'Unbekannt'

# Feste Reihenfolge = Reihenfolge der Chips: zuerst Spielfilm-Genres, dann Sachthemen und Fernsehformate.
CATEGORIES = (
    'Action', 'Abenteuer', 'Animation', 'Biografie', 'Drama', 'Erotik', 'Fantasy', 'Historie', 'Horror',
    'Kinder & Familie', 'Komödie', 'Krieg', 'Krimi', 'Musical', 'Mystery', 'Romantik', 'Science-Fiction',
    'Thriller', 'Western',
    'Dokumentation', 'Natur & Tiere', 'Wissen & Technik', 'Politik & Gesellschaft', 'Nachrichten & Magazine',
    'Kultur', 'Musik', 'Sport', 'Reise', 'Ratgeber & Lifestyle', 'Talk', 'Show & Unterhaltung', 'Reality-TV',
)
SPECIAL = (UNCLASSIFIED, OTHER)
ORDER = {name: i for i, name in enumerate(CATEGORIES + SPECIAL)}

# Schlüsselwort-Regeln über den schreibweisenunabhängigen Schlüssel (klein, ß→ss, Bindestriche → Leerzeichen).
# Ein Label kann mehrere Kategorien treffen („Romantische Komödie“ → Romantik + Komödie). Reihenfolge egal.
_RULES = (
    ('Action', r'action|martial|kung ?fu|karate|superheld|superhero|katastroph|disaster|ploitation|eastern|\bheist\b|agenten|spionage|\bspy\b'),
    ('Abenteuer', r'abenteuer|adventure|schatzsuche|mantel ?und ?degen|swashbuckl|bergfilm|piraten'),
    ('Animation', r'anim|zeichentrick|trickfilm|cartoon|\banime\b|stop ?motion'),
    ('Biografie', r'biogra|biopic|portrat|porträt'),
    ('Drama', r'drama|dramedy|trag(?:i|ö|oe)d|tragik|seifenoper|\bsoap\b|telenovela|melodram|heimat|trauerspiel'),
    ('Erotik', r'erot|nur fur erwachsene|nur für erwachsene|\badult\b'),
    ('Fantasy', r'fantas|marchen|märchen|fairy ?tale|sword and sorcery|übernat|ubernat|supernatural'),
    ('Historie', r'histor|geschicht|mittelalter|antike|kostum|kostüm|period drama|\bhistory\b|epos'),
    ('Horror', r'horror|slasher|zombie|monster|splatter|grusel|vampir|werwolf'),
    ('Kinder & Familie', r'kinder|\bkids?\b|famil|children|jugend|teen|weihnacht|christmas'),
    ('Komödie', r'kom(?:ö|o|oe)die|comedy|dramedy|sitcom|kabarett|satire|parodie|parody|spoof|stand ?up|humor|mockbuster|slapstick'),
    ('Krieg', r'krieg|\bwar\b|milit'),
    ('Krimi', r'krimi|crime|detektiv|detective|polizei|police|noir|gangster|mafia|\bheist\b|whodunit'),
    ('Musical', r'musical'),
    ('Mystery', r'myster|geheimnis|paranormal|übernat|ubernat|supernatural'),
    ('Romantik', r'roman(?:ze|ti|ce)|liebe|love|leidenschaft'),
    ('Science-Fiction', r'science ?fiction|sci ?fi|scifi|science fiction|endzeit|dystop|space|weltraum|zeitreise|cyberpunk|speculative|spekulativ'),
    ('Thriller', r'thrill|suspense|spannung'),
    ('Western', r'western'),
    ('Dokumentation', r'doku(?!soap| soap)|documentar|documentary|reportage|sachtext|sachliteratur|\bfactual\b|true crime'),
    ('Natur & Tiere', r'natur|tiere|\btier\b|haustier|wildtier|\bpets?\b|animal|wildlife|umwelt|landwirtschaft|wetter'),
    ('Wissen & Technik', r'wissen|science(?! ?fiction)|technolog|technik|bildung|educational|instructional|lehr|medizin|forschung|luftfahrt|raumfahrt|eisenbahn'),
    ('Politik & Gesellschaft', r'politi|gesellschaft|wirtschaft|finanz|\brecht\b|justiz|offentliche|öffentliche|lgbt|zeitgeschehen|soziales'),
    ('Nachrichten & Magazine', r'nachricht|\bnews\b|magazin|information|boulevard'),
    ('Kultur', r'kultur|kunst|\bart\b|literatur|religion|theater|buhne|bühne|philosoph'),
    ('Musik', r'musik(?!al)|\bmusic\b|konzert|concert|\brap\b|hip ?hop|\bfolk|\brock\b|\boper\b|\bopera\b|schlager|\bjazz\b|\bklassik\b|klassische musik|\bpop\b'),
    ('Sport', r'sport|fussball|fußball|soccer|football|boxen|boxer|angeln|fishing|\bski|surf|skate|snowboard|wrestling|motorsport|autorennen|racing|cheerlead|mountainbik|tauchen|radfahren|eiskunstlauf|\bgolf\b|tennis|olymp|\bpoker\b|segeln|outdoor'),
    ('Reise', r'reise|travel|urlaub'),
    ('Ratgeber & Lifestyle', r'ratgeber|lifestyle|kochen|\bkoch|\bfood\b|cooking|garten|garden|heimwerk|diy|\bmode\b|fashion|gesundheit|health|verbraucher|einkaufen|shopping|auktion|sammler|anleitung|tutorial|\bauto\b|motorrad|wohnen|home and|selbstoptimierung'),
    ('Talk', r'\btalk|interview|podcast|gesprach|gespräch'),
    ('Show & Unterhaltung', r'show|quiz|gaming|\bgames?\b|unterhaltung|entertainment|variety|preisverleihung|veranstaltung|\bgala\b|e ?sport'),
    ('Reality-TV', r'reality|doku ?soap|dokusoap|casting|dating'),
)
_COMPILED = tuple((name, re.compile(rx)) for name, rx in _RULES)

# Wörter, die nur das Medium nennen; ein Label nur daraus trägt keine Kategorie.
_NOISE = {'film', 'filme', 'spielfilm', 'serie', 'serien', 'fernsehserie', 'tv serie', 'tv series', 'series', 'movie',
          'movies', 'fernsehsendung', 'sendung', 'webserie', 'tv show', 'tv film', 'fernsehfilm', 'tv movie',
          'miniserie', 'mini series', 'miniseries', 'kurzfilm', 'short', 'episodenfilm', 'anthologie', 'spezial',
          'deutscher film', 'independent film', 'indie filme', 'unbekannt', 'n a', 'sonstige', 'sonstiges',
          'unklassifiziert'}
# Ausnahmen, die eine Regel fälschlich treffen würde.
_OVERRIDE = {
    'eastern': ['Action'], 'tragikomodie': ['Drama', 'Komödie'], 'tragikomödie': ['Drama', 'Komödie'],
    'dokudrama': ['Dokumentation'], 'kampfsport': ['Sport'], 'sporttalk': ['Sport', 'Talk'],
    'feiertag': ['Kinder & Familie'], 'heimatfilm': ['Drama'], 'space western': ['Science-Fiction', 'Western'],
    'secret history': [], 'gemeinschaft': [], 'spekulativer spielfilm': ['Science-Fiction'],
    'point and click adventure': ['Abenteuer'], 'kinderfernsehen': ['Kinder & Familie'],
    'elternschaft': ['Kinder & Familie'], 'bildungsfernsehen': ['Wissen & Technik'],
    'kriegsfilm': ['Krieg'], 'eiskunstlauf': ['Sport'], 'kunst im öffentlichen raum': ['Kultur'],
    'landwirtschaft': ['Natur & Tiere'], 'verbraucherinformation': ['Ratgeber & Lifestyle'], 'kampfkunst': ['Action'], 'war': ['Krieg'], 'history': ['Historie'],
}


def key(label):
    text = str(label or '').casefold().replace('ß', 'ss').replace('&', ' and ')
    text = re.sub(r'[^\w]+', ' ', text)
    return ' '.join(text.split())


_CACHE = {}


def of_label(label):
    """Die festen Kategorien für ein Roh-Label (leer, wenn es keine trägt)."""
    raw = str(label or '').strip()
    if not raw:
        return []
    if raw in ORDER and raw not in SPECIAL:
        return [raw]
    hit = _CACHE.get(raw)
    if hit is not None:
        return list(hit)
    k = key(raw)
    folded = k.replace('ss', 'ß')
    if k in _NOISE:
        names = []
    elif k in _OVERRIDE or folded in _OVERRIDE or k.replace(' ', '') in _OVERRIDE:
        names = _OVERRIDE.get(k, _OVERRIDE.get(folded, _OVERRIDE.get(k.replace(' ', ''))))
    else:
        # Umlaute als ASCII-Variante mitprüfen (Anbieter schreiben „Komoedie“, „Komodie“).
        variants = {k, k.replace('ae', 'ä').replace('oe', 'ö').replace('ue', 'ü'),
                    k.replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')}
        names = sorted({name for name, rx in _COMPILED for v in variants if rx.search(v)}, key=ORDER.get)
        # „Science fiction“ ist kein Wissenschaftsthema, „Musical“ keine Musiksendung.
        if 'Science-Fiction' in names and 'Wissen & Technik' in names:
            names.remove('Wissen & Technik')
        if 'Reality-TV' in names and 'Drama' in names and 'soap' in k:
            names.remove('Drama')
        if 'Talk' in names and 'Show & Unterhaltung' in names:
            names.remove('Show & Unterhaltung')
        if 'Reality-TV' in names and 'Dokumentation' in names:
            names.remove('Dokumentation')
        if 'Fantasy' in names and 'Mystery' in names and 'fantas' not in k:
            names.remove('Fantasy')
    _CACHE[raw] = tuple(names)
    return list(names)


def of_labels(labels):
    """Feste Kategorien für mehrere Roh-Labels, in fester Reihenfolge, ohne Dubletten."""
    found = set()
    for label in labels or []:
        found.update(of_label(label))
    return sorted(found, key=ORDER.get)


def classify(reference_labels=(), provider_labels=(), checked=True):
    """Kategorien eines Titels.

    ``checked``: der Abgleich mit den Referenzen ist gelaufen. Sonst ``[UNCLASSIFIED]``.
    Danach entscheiden die Referenz-Genres; Anbieter-Genres ergänzen nur, wenn die Referenz keine
    Kategorie liefert (so landet ein Film nicht wegen eines Anbieter-Etiketts in einer falschen Gruppe)."""
    if not checked:
        return [UNCLASSIFIED]
    names = of_labels(reference_labels) or of_labels(provider_labels)
    return names or [OTHER]


def is_special(name):
    return name in SPECIAL or name == LEGACY_UNKNOWN


def sort_key(name):
    return (ORDER.get(name, len(ORDER)), str(name).casefold())


def wanted(value):
    """Filterwert → feste Kategorie (Groß-/Kleinschreibung egal; alte Roh-Labels werden übersetzt).
    Liefert (kategorie, roh): ``kategorie`` None, wenn der Wert keine feste Kategorie nennt."""
    text = str(value or '').strip()
    if not text:
        return None, ''
    for name in CATEGORIES + SPECIAL:
        if name.casefold() == text.casefold():
            return name, text
    if text.casefold() == LEGACY_UNKNOWN.casefold():
        return UNCLASSIFIED, text
    mapped = of_label(text)
    return (mapped[0] if len(mapped) == 1 else None), text


def describe():
    """Für /api/categories: feste Liste und Sonderwerte."""
    return {'category_names': list(CATEGORIES), 'unclassified': UNCLASSIFIED, 'other': OTHER}
