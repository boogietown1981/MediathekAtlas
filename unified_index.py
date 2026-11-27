"""One merged, globally sorted index of films and series across all sources (0.5.55).

Björn (12.11.2026): the dashboard should show only the films of all platforms, and the same film
offered by several providers appeared once per provider ("#Roxy" from Netzkino, Pluto TV and
YouTube next to each other).

Until now the view "Gesamt" asked every source for its own page 1, 2, 3 … and mixed the pages in
the browser: the order was only right within a page, a title could sit on different pages per
source, and the slowest source held back the whole view. This module builds the index on the
server instead:

* every source delivers its complete filtered list once (the ARD/ZDF list comes from the grouped
  listing cache of ``catalog``),
* entries for the same work are merged conservatively into one entry with several offers,
* the merged list is sorted and paged as a whole and kept in memory for a short time.

Merging never changes stored data and never asserts an identity: it is a presentation of
"same title, compatible year" and can be switched off (Verwaltung → Darstellung).
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata

PAGE = 48
TTL = 45.0
_MAX = 24
_CACHE = {}
_LOCK = threading.Lock()
_BUILD = threading.Lock()

SOURCES = ('mediatheken', 'lokal', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll', 'plex', 'servustv', 'redbulltv', 'dmax', 'filmfriend', 'dailyme', 'rtlplus')
NAMES = {'mediatheken': 'ARD, ZDF & Co.', 'lokal': 'Lokales Archiv', 'netzkino': 'Netzkino', 'pluto': 'Pluto TV',
         'justwatch': 'JustWatch TV', 'rakuten': 'Rakuten TV', 'youtube': 'YouTube', 'joyn': 'Joyn', 'toggo': 'TOGGO', 'crunchyroll': 'Crunchyroll', 'plex': 'Plex', 'servustv': 'ServusTV', 'redbulltv': 'Red Bull TV', 'dmax': 'DMAX & TLC', 'filmfriend': 'filmfriend', 'dailyme': 'dailyme TV', 'rtlplus': 'RTL+'}
# Which offer represents a merged entry: curated catalogues first, uploads with free-text
# titles and landscape thumbnails (YouTube) and copy-protected offers (Rakuten) last.
RANK = {'lokal': -1, 'mediatheken': 0, 'netzkino': 1, 'pluto': 2, 'justwatch': 3, 'rakuten': 4, 'youtube': 5, 'joyn': 6, 'toggo': 7, 'crunchyroll': 8, 'plex': 9, 'servustv': 10, 'rtlplus': 11, 'redbulltv': 12, 'dmax': 13, 'filmfriend': 14, 'dailyme': 15}
# Sources whose year is the upload year, not the year of the work.
LOOSE_YEAR = {'youtube', 'servustv', 'redbulltv'}

_BRACKETS = re.compile(r'\s*[\(\[\{].*$')
_TAIL = re.compile(r'\s+(?:\||–|—|-)\s+.*$')
_NOISE = re.compile(r'(?i)\b(?:ganzer film|kompletter film|full movie|auf deutsch|deutsch|german|hd|4k|uhd|'
                    r'film in voller länge|in voller länge|free movie|kostenlos)\b.*$')


def title_key(title, loose=False):
    """Comparison key: case, accents, punctuation and (for free-text upload titles) the advertising
    tail are ignored. '#Roxy (ROMANTISCHE KOMÖDIE mit …' and '#Roxy' give the same key."""
    text = str(title or '')
    if loose:
        text = _BRACKETS.sub('', text)
        text = _TAIL.sub('', text)
        text = _NOISE.sub('', text)
    text = unicodedata.normalize('NFKD', text.replace('ß', 'ss'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r'&', ' und ', text)
    return re.sub(r'[^a-z0-9]+', '', text)


def _year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1880 <= year <= 2100 else None


def _sort_title(title):
    text = unicodedata.normalize('NFKD', str(title or '').replace('ß', 'ss'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r'^[^a-z0-9]+', '', text) or text


_SUBTITLE = re.compile(r'\s*(?::|\s[-–—]\s).*$')


def _keys(offer):
    """Comparison keys of one offer, strongest first.

    Free-text upload titles (YouTube) get two: the short one without the advertising tail and the
    full one from the original title, because the tail after " - " is often the subtitle of the
    film ("Ab ins Meer - Auf der Suche nach der verlorenen Perle (Ganzer Film …)")."""
    title = offer['title']
    if offer['source'] not in LOOSE_YEAR:
        return [k for k in (title_key(title),) if k]
    keys = [title_key(title, True) or title_key(title)]
    raw = str((offer.get('item') or {}).get('raw_title') or title)
    full = title_key(_NOISE.sub('', _BRACKETS.sub('', raw)))
    if full and full not in keys:
        keys.append(full)
    return [k for k in keys if k]


def _evidence(offer):
    item = offer.get('item') or {}
    ref = item.get('reference') if isinstance(item.get('reference'), dict) else {}
    ids = set()
    if ref.get('provider') and ref.get('id'):
        ids.add(('IMDb' if ref['provider'] in ('IMDb Offline', 'OMDb') else ref['provider'], str(ref['id'])))
    if item.get('imdb_id'):
        ids.add(('IMDb', str(item['imdb_id'])))
    try:
        duration = float(item.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0.0
    # year: the one of the reference; the provider's own only where it is the film's year (not an upload date)
    year = _year(ref.get('year')) or (None if offer['source'] in LOOSE_YEAR else _year(offer.get('year')))
    titles = {k for k in _keys(offer) if k}
    if ref.get('title'):
        titles.add(title_key(ref['title']))
    words = _words(item.get('summary') or item.get('description') or '')
    return {'ids': ids, 'duration': duration, 'year': year, 'titles': titles - {''}, 'words': words}


def _words(text):
    text = unicodedata.normalize('NFKD', str(text or '').replace('ß', 'ss')).casefold()
    return {w for w in re.findall(r'[a-z0-9]{5,}', text)}


def _same_work(a, b):
    """Extra proof for "title" against "title: subtitle" from two providers. "Alien" (1979) never
    joins "Alien: Covenant" (2017).

    Against: both were matched to the same database with different entries, the years of the films
    lie more than one apart, or the running times differ by more than 15 %.
    For (0.5.63, more generous - Björn, 12.11.2026: "Ab ins Meer" still twice with 0.5.61): the same
    reference ID, the full title of one is a known title of the other (reference title), the same
    year (one apart at most), running times of feature length within two minutes, or descriptions
    that largely use the same words. A missing year is no contradiction, but no proof either."""
    ea, eb = _evidence(a), _evidence(b)
    if ea['ids'] & eb['ids']:
        return True
    if {p for p, _ in ea['ids']} & {p for p, _ in eb['ids']}:
        return False   # both checked against the same database with different results
    if ea['year'] and eb['year'] and abs(ea['year'] - eb['year']) > 1:
        return False
    da, db = ea['duration'], eb['duration']
    if da >= 600 and db >= 600 and abs(da - db) > 0.15 * max(da, db):
        return False
    if ea['titles'] & eb['titles']:
        return True
    if ea['year'] and eb['year']:
        return True
    if da >= 2400 and db >= 2400 and abs(da - db) <= 120:
        return True
    wa, wb = ea['words'], eb['words']
    return len(wa) >= 8 and len(wb) >= 8 and len(wa & wb) >= 0.5 * min(len(wa), len(wb))


def merge(offers, enabled=True, subtitles=True):
    """offers: dicts with source, title, year (+ payload). Returns entries {title, year, offers}.

    Conservative rules: same title key; years equal, one apart (cinema vs. broadcast year) or
    unknown; never two offers of the same source in one entry (remakes, parts, duplicates of one
    provider stay separate tiles).

    0.5.60 (Björn, 12.11.2026: "Ab ins Meer" from YouTube next to "Ab ins Meer: Auf der Suche nach
    der verlorenen Perle" from Netzkino): an upload title is also compared with its full original
    title, and with ``subtitles`` a title joins "title: subtitle" when a reference ID or the
    running time proves the same work."""
    entries, by_key, by_main = [], {}, {}

    def fits(entry, offer, year):
        if offer['source'] in entry['sources']:
            return False
        return year is None or entry['year'] is None or abs(year - entry['year']) <= 1

    for offer in offers:
        loose = offer['source'] in LOOSE_YEAR
        keys = _keys(offer)
        year = None if loose else _year(offer.get('year'))
        mains = []
        for key in keys:
            main = title_key(_SUBTITLE.sub('', str(offer['title'])))
            if main and main != key and main not in mains:
                mains.append(main)
        target = None
        if enabled:
            for key in keys:
                target = next((e for e in by_key.get(key, ()) if fits(e, offer, year)), None)
                if target:
                    break
            if target is None and subtitles:
                # this offer is the long title, an entry carries the short one - or the other way round
                candidates = [e for main in mains for e in by_key.get(main, ())]
                candidates += [e for key in keys for e in by_main.get(key, ())]
                target = next((e for e in candidates if fits(e, offer, year)
                               and any(_same_work(offer, other) for other in e['offers'])), None)
        if target is None:
            target = {'key': keys[0] if keys else '', 'year': year, 'sources': set(), 'offers': []}
            entries.append(target)
        for key in keys:
            if target not in by_key.setdefault(key, []):
                by_key[key].append(target)
        for main in mains:
            if target not in by_main.setdefault(main, []):
                by_main[main].append(target)
        target['offers'].append(offer)
        target['sources'].add(offer['source'])
        if target['year'] is None:
            target['year'] = year
    for entry in entries:
        entry['offers'].sort(key=lambda o: RANK.get(o['source'], 99))
        first = entry['offers'][0]
        entry['title'] = first['title']
        if entry['year'] is None:
            entry['year'] = _year(first.get('year'))
    return entries


def _portal_offers(source, module_listing, root, view, query, genre, collection):
    data = module_listing(root, view=view, query=query, offset=0, limit='all', genre=genre,
                          sort='title', collection=collection)
    offers = [{'source': source, 'title': row.get('title') or 'Ohne Titel', 'year': row.get('year'), 'item': row}
              for row in data.get('items') or []]
    return offers, data.get('genre_counts') or []


def _netzkino_offers(netzkino, root, view, query, genre, collection):
    data = netzkino.grouped_catalog(root, view=view, series_key='', query=query, origin='all', offset=0,
                                    limit='all', genre=genre, sort='title', collection=collection)
    offers = [{'source': 'netzkino', 'title': row.get('title') or 'Ohne Titel', 'year': row.get('year'), 'item': row}
              for row in data.get('items') or []]
    return offers, data.get('genre_counts') or []


def build(root, db, kind='movies', query='', genre='', sort='title', collection='', merge_duplicates=True,
          modules=None, language='', only='', reihen=False):
    """Complete merged index for one filter. ``db`` is the context-manager factory of the main
    catalogue; ``modules`` maps source -> module (tests pass fakes)."""
    import catalog
    if modules is None:
        import lokal, netzkino, pluto, justwatch, rakuten, youtube, joyn, toggo, crunchyroll, plex, servustv, rtlplus, redbulltv, dmax, filmfriend, dailyme
        modules = {'lokal': lokal, 'netzkino': netzkino, 'pluto': pluto, 'justwatch': justwatch, 'rakuten': rakuten,
                   'youtube': youtube, 'joyn': joyn, 'toggo': toggo, 'crunchyroll': crunchyroll, 'plex': plex, 'servustv': servustv, 'rtlplus': rtlplus,
                   'redbulltv': redbulltv, 'dmax': dmax, 'filmfriend': filmfriend, 'dailyme': dailyme}
    view = 'series' if kind == 'series' else 'movies'
    offers, counts, errors, genre_counts = [], {}, {}, {}

    def add_counts(rows):
        for row in rows:
            name = str(row.get('genre') or '').strip()
            if name:
                genre_counts[name] = genre_counts.get(name, 0) + int(row.get('n') or 0)

    pending, seconds = [], {}
    started = time.monotonic()
    try:
        if only and only != 'mediatheken':
            raise _Skip()
        with db() as c:
            # wait=False: on a cold start the grouping of the whole catalogue runs in the background
            # and the other sources are shown first (0.5.57).
            groups = catalog.listing(c, query=query, kind='series' if view == 'series' else 'movie', genre=genre,
                                     sort='title', downloaded='all', collection=collection, index_only=True,
                                     wait=False)
        found = [{'source': 'mediatheken', 'title': g[2] or 'Ohne Titel', 'year': g[3], 'id': g[0], 'episodes': g[1]}
                 for g in groups]
        if language:
            # 0.6.5: language filter (languages.mediathek_filter: candidates by text search)
            import languages
            with db() as c:
                mode, works = languages.mediathek_filter(c, language)
            found = [f for f in found if (f['id'] in works) == (mode == 'include')]
        offers += found
        counts['mediatheken'] = len(found)
    except _Skip:
        pass
    except catalog.ListingPending:
        pending.append('mediatheken')
    except Exception as exc:   # one broken source never hides the others
        errors['mediatheken'] = str(exc)[:160] or exc.__class__.__name__
    seconds['mediatheken'] = round(time.monotonic() - started, 2)
    for source in ('lokal', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll', 'plex', 'servustv', 'redbulltv', 'dmax', 'filmfriend', 'dailyme', 'rtlplus'):
        module = modules.get(source)
        if module is None or (only and only != source):
            continue
        started = time.monotonic()
        try:
            if source == 'netzkino':
                found, facets = _netzkino_offers(module, root, view, query, genre, collection)
            else:
                found, facets = _portal_offers(source, module.listing, root, view, query, genre, collection)
            if language:
                import languages
                found = [o for o in found if languages.matches(
                    languages.for_portal(root, source, o['item'], name=NAMES.get(source, source)), language)]
            offers += found
            counts[source] = len(found)
            add_counts(facets)
        except Exception as exc:
            errors[source] = str(exc)[:160] or exc.__class__.__name__
        seconds[source] = round(time.monotonic() - started, 2)
    started = time.monotonic()
    entries = merge(offers, merge_duplicates, subtitles=view == 'movies')   # series: 'Star Trek' is not 'Star Trek: Voyager'
    if reihen and view == 'movies' and not query:
        try:
            began = time.monotonic()
            entries = collapse_reihen(db, entries)
            seconds['reihen'] = round(time.monotonic() - began, 2)   # 0.6.155: Anteil am merge (Prüfung 0.6.154: 0,74 s)
        except Exception as exc:     # eine Zusammenfassung kostet nie die Liste
            errors['reihen'] = str(exc)[:160] or exc.__class__.__name__
    if sort == 'year':
        entries.sort(key=lambda e: (-(e['year'] or 0), _sort_title(e['title'])))
    else:
        entries.sort(key=lambda e: _sort_title(e['title']))
    # 0.6.148 (Björn 26.11.2026: „geladene Filme und Serien bevorzugen“, auch im normalen Katalog): Titel mit lokaler
    # Kopie stehen vorn, innerhalb beider Teile bleibt die gewählte Sortierung
    try:
        import local_titles
        began = time.monotonic()
        with db() as c:
            if local_titles.mark_entries(c, entries, series=view == 'series'):
                entries = local_titles.local_first(entries)
        seconds['local'] = round(time.monotonic() - began, 2)   # 0.6.155: Anteil am merge
    except Exception:
        pass
    seconds['merge'] = round(time.monotonic() - started, 2)
    return {'entries': entries, 'counts': counts, 'errors': errors, 'pending': pending, 'seconds': seconds,
            'genre_counts': [{'genre': g, 'n': n} for g, n in sorted(genre_counts.items())],
            'merged': sum(1 for e in entries if len(e['offers']) > 1)}


# 0.6.150 (Björn 26.11.2026 zu Tatort/Polizeiruf unter Filme: „wenn es Filme sind, dann ja, aber man kann sie auch als
# Reihe zusammenfassen, z. B. alle Tatort-Filme, bzw. wenn ein Film 1–n Teile hat“). Nur in der Filmliste ohne Suche
# (eine Suche zeigt weiter jeden Film einzeln):
# * Filmreihe: Reihenfilme (catalog.mark_series_films) derselben Mediatheken-Reihe ab REIHE_MIN Filmen werden EINE
#   Kachel mit dem Reihennamen; sie öffnet die Reihe wie eine Serie. Sendeplätze („FilmMittwoch im Ersten“, „Herzkino“,
#   „Fernsehfilm der Woche“ …) sind keine Reihe und bleiben einzeln (REIHE_SLOT). Titel, die auch bei einem anderen
#   Anbieter stehen (zusammengeführt), bleiben einzeln, damit kein Angebot verschwindet.
# * Mehrteiler: Titel „… Teil 1“, „… (2/3)“, „…, Teil zwei“ desselben Grundtitels ab zwei verschiedenen Teilen werden
#   EINE Kachel „Grundtitel“ (Mehrteiler · n Teile); sie zeigt die Teile über die Suche.
# 0.6.154 (Mac-Prüfung 0.6.150, BEFUND-06150.txt):
# * Eine Reihe ist ihr NAME, nicht ein show_key („Praxis mit Meerblick“ stand unter zwei show_keys als zwei Kacheln).
# * Eigene Filmwerke „Reihe: Titel“ / „Reihe – Titel“ (ORF-Schreibweise „Tatort: Azra“, „Polizeiruf 110: Paranoia“)
#   gehören zu ihrer Reihe, wenn es die Reihe gibt. „Tatort Matterhorn“ ohne Trenner bleibt einzeln (nicht sicher).
# * Die Kachel öffnet die Suche nach dem Reihennamen (wie ein Mehrteiler): dort steht jeder Film einzeln mit allen
#   Anbietern. Deshalb dürfen jetzt auch zusammengeführte Titel (Maria Wern bei zwei Anbietern) in die Reihe.
# * Mehrteiler: „Teil 1/ 2“ wird als Teil erkannt (Grundtitel nicht mehr „… Teil“); Teile mit verschiedenen Jahren sind
#   Fortsetzungen („Zärtliche Chaoten – Teil 1“ 1986, „Teil 2“ 1987) und bleiben einzeln; gezählt werden verschiedene
#   Teilnummern, nicht Fassungen (Audiodeskription, Varianten).
REIHE_MIN = 3
REIHE_SLOT = re.compile(r'(?i)film|kino|movie|cinema|sendeplatz|premiere|sommer|highlights?\b|mediathek')
PART = re.compile(r'(?i)^(?P<base>.*?\S)\s*[-–—:,(]?\s*(?:\(?\s*(?:(?:teil|part)\s*)?(?P<n>\d{1,2})\s*/\s*\d{1,2}\s*\)?|\(?(?:teil|part)\s+(?P<m>\d{1,2}|eins|zwei|drei|vier|fünf|one|two|three)\)?)\s*$')
PART_HINT = re.compile(r'(?i)\d\s*/\s*\d|teil|part')
# 0.6.156 (Mac-Prüfung 0.6.155: „Kolbenfresser Teil 1 Maisernte hautnah“ fiel aus dem Mehrteiler): „Teil n“ mit Zusatz
# dahinter zählt nur, wenn derselbe Grundtitel schon streng erkannte Teile hat
PART_LOOSE = re.compile(r'(?i)^(?P<base>.*?\S)\s*[-–—:,(]?\s*(?:teil|part)\s+(?P<n>\d{1,2})\b\s*[-–—:,.)]?\s*\S.*$')
DOKU = {'dokumentation', 'doku', 'dokumentarfilm', 'reportage', 'documentary', 'wissen', 'natur', 'technik'}
# 0.6.157 (Mac-Prüfung 0.6.156: „Kolbenfresser“, „Monster High Webisodes“, „The Lies We Tell …“ fielen aus den Mehrteilern):
# ohne IMDb gilt die Jahresregel nur für Spielfilme mit erzählendem Genre
FICTION = {'komödie', 'komoedie', 'drama', 'krimi', 'thriller', 'action', 'abenteuer', 'liebesfilm', 'romanze', 'romantik',
           'horror', 'science-fiction', 'science fiction', 'western', 'spielfilm', 'kriegsfilm', 'heimatfilm', 'comedy', 'crime'}
PART_WORDS = {'eins': 1, 'zwei': 2, 'drei': 3, 'vier': 4, 'fünf': 5, 'one': 1, 'two': 2, 'three': 3}
REIHE_PREFIX = re.compile(r'^(?P<name>[^:–—]{3,60}?)\s*(?::|\s[-–—])\s+\S')


def _part(title):
    m = PART.match(str(title or '').strip())
    if not m or len(m.group('base')) < 3:
        return None
    raw = (m.group('n') or m.group('m') or '').casefold()
    number = int(raw) if raw.isdigit() else PART_WORDS.get(raw)
    base = m.group('base').rstrip(' -–—:,(')
    return (base, number) if number and len(base) >= 3 else None


def _offer_genres(item):
    """Genres eines Plattform-Angebots (categories, source_genres, genres, genre-Text)."""
    out = set()
    for key in ('categories', 'source_genres', 'genres'):
        value = item.get(key)
        if isinstance(value, (list, tuple)):
            out |= {str(g).casefold().strip() for g in value}
    if isinstance(item.get('genre'), str):
        out |= {g.casefold().strip() for g in re.split(r'[,/|]', item['genre']) if g.strip()}
    return out


def _sequels(db, members, numbers=None):
    """Teile desselben Grundtitels aus verschiedenen Jahren: Fortsetzung (einzeln lassen) oder Mehrteiler?
    0.6.155: Fortsetzung, wenn mindestens zwei Teile verschiedene IMDb-Nummern tragen (eigene Filme).
    0.6.156/0.6.157: ohne IMDb entscheiden Genre und Jahre; Doku/Reportage oder kein erzählendes Genre → Mehrteiler.
    0.6.158 (Mac-Prüfung 0.6.157: „Zärtliche Chaoten“ bei Pluto TV, „Freitag der 13“ bei Rakuten/Joyn/Netzkino wieder als
    Mehrteiler): die Genres der Plattform-Angebote zählen mit (vorher nur Mediatheken-Werke), und ein erzählender Film ist
    eine Fortsetzung, sobald kein Jahr bei zwei verschiedenen Teilen vorkommt (Elvis Teil 1 und 2 beide 2005 → Mehrteiler)."""
    ids = [o['id'] for e in members for o in e['offers'] if o['source'] == 'mediatheken']
    imdb, genres = set(), set()
    for e in members:
        for o in e['offers']:
            if o['source'] != 'mediatheken':
                item = o.get('item') or {}
                imdb.add(str(item.get('imdb_id') or item.get('imdb') or ''))
                genres |= _offer_genres(item)
    if ids:
        with db() as c:
            marks = ','.join('?' * len(ids))
            for tt, gs in c.execute("SELECT json_extract(meta,'$.imdb_id'), json_extract(meta,'$.genres') FROM works "
                                    "WHERE id IN (%s) AND json_valid(meta)" % marks, ids):
                imdb.add(str(tt or ''))
                try:
                    genres |= {str(g).casefold() for g in (json.loads(gs) if gs else []) or []}
                except (TypeError, ValueError):
                    pass
    if len({i for i in imdb if i.startswith('tt')}) >= 2:
        return True
    if not numbers or genres & DOKU or not genres & FICTION:
        return False
    parts_of_year = {}
    for e, n in zip(members, numbers):
        if e.get('year'):
            parts_of_year.setdefault(e['year'], set()).add(n)
    return len(parts_of_year) >= 2 and all(len(p) == 1 for p in parts_of_year.values())


def collapse_reihen(db, entries):
    """Filmreihen und Mehrteiler der Filmliste zusammenfassen (siehe REIHE_MIN)."""
    ids = [o['id'] for e in entries for o in e['offers'] if o['source'] == 'mediatheken']
    shows, names = {}, {}
    if ids:
        with db() as c:
            for wid, show, title in c.execute(
                    "SELECT w.id, w.show_key, w.title FROM works w WHERE w.kind='series' AND json_valid(w.meta) "
                    "AND json_extract(w.meta,'$.series_film')=1"):
                name = str(title or show or '').strip()
                key = title_key(name)
                if show and key:
                    shows[wid] = key
                    names.setdefault(key, name)
    groups = {}
    for i, e in enumerate(entries):
        mediathek = [o for o in e['offers'] if o['source'] == 'mediatheken']
        key = next((shows[o['id']] for o in mediathek if o['id'] in shows), None)
        if key and not REIHE_SLOT.search(names[key]):
            groups.setdefault(('reihe', key), []).append(i)
    in_reihe = {i for k, v in groups.items() for i in v}
    for i, e in enumerate(entries):     # eigene Filmwerke „Tatort: Azra“ zu einer vorhandenen Reihe
        if i in in_reihe or not any(o['source'] == 'mediatheken' for o in e['offers']):
            continue
        m = REIHE_PREFIX.match(str(e['title'] or ''))
        key = m and title_key(m.group('name'))
        if key and ('reihe', key) in groups:
            groups[('reihe', key)].append(i);in_reihe.add(i)
    parts_of = {}
    for i, e in enumerate(entries):
        t = str(e['title'] or '')
        if i in in_reihe or not (PART_HINT.search(t)):
            continue
        part = _part(t)
        if part:
            parts_of[i] = part
            groups.setdefault(('teile', title_key(part[0])), []).append(i)
    for i, e in enumerate(entries):      # 0.6.156: „Teil 1 Maisernte hautnah“ zu vorhandenen Teilen desselben Grundtitels
        if i in in_reihe or i in parts_of:
            continue
        m = PART_LOOSE.match(str(e['title'] or '').strip())
        base = m and m.group('base').rstrip(' -–—:,(')
        if base and len(base) >= 3 and ('teile', title_key(base)) in groups:
            parts_of[i] = (base, int(m.group('n')))
            groups[('teile', title_key(base))].append(i)
    replace, drop = {}, set()
    for (what, key), members in groups.items():
        members.sort()
        years = [entries[i]['year'] for i in members if entries[i]['year']]
        if what == 'reihe':
            if len(members) < REIHE_MIN:
                continue
            offer = next(o for i in members for o in entries[i]['offers'] if o['source'] == 'mediatheken' and o['id'] in shows)
            offer = dict(offer, episodes=len(members), reihe=key)
            name = names[key]
            replace[members[0]] = {'title': name, 'year': max(years) if years else None, 'offers': [offer], 'reihe': key,
                                   'mehrteiler': {'query': name, 'parts': len(members), 'reihe': True}}
        else:
            numbers = {parts_of[i][1] for i in members}
            if len(numbers) < 2 or (len(set(years)) > 1 and _sequels(db, [entries[i] for i in members],
                                                                      [parts_of[i][1] for i in members])):
                continue    # ein Teil allein bzw. Fortsetzungen (siehe _sequels)
            first = entries[min(members, key=lambda i: (parts_of[i][1], i))]
            base = parts_of[min(members, key=lambda i: (parts_of[i][1], i))][0]
            replace[members[0]] = dict(first, title=base, year=min(years) if years else first['year'],
                                       mehrteiler={'query': base, 'parts': len(numbers)})
        keep = members[0]
        drop.update(i for i in members if i != keep)
    if not replace:
        return entries
    return [replace.get(i, e) for i, e in enumerate(entries) if i not in drop]


class _Skip(Exception):
    """A source left out by the ``only`` filter."""


PENDING_TTL = 2.0
_BUSY = set()
ON_BUILD = None   # set by the server: called with (key, index, seconds) after every build


_SERIAL = [0]
_GEN = [0]   # 0.6.112: a build started before invalidate() must not store its stale result (Kinder-Altersgrenze)


def _build_into(key, builder):
    started = time.monotonic()
    gen = _GEN[0]
    value = builder()
    if isinstance(value, dict):
        _SERIAL[0] += 1
        value['serial'] = _SERIAL[0]      # 0.6.116: Index-Stand für blätternde Leser (kids_catalog._collect)
    with _LOCK:
        if gen != _GEN[0]:
            return value
        _CACHE[key] = (time.monotonic(), value)
        while len(_CACHE) > _MAX:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]))
    if ON_BUILD:
        try:
            ON_BUILD(key, value, time.monotonic() - started)
        except Exception:
            pass
    return value


def _renew(key, builder):
    try:
        with _BUILD:
            _build_into(key, builder)
    except Exception:
        pass
    finally:
        with _LOCK:
            _BUSY.discard(key)


def _cached(key, builder):
    """Fresh index from memory; an outdated one is returned at once and renewed in the background
    (0.5.57: paging never waits for a rebuild). An index that still waits for a source is only
    kept for a moment."""
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit:
            ttl = PENDING_TTL if hit[1].get('pending') else TTL
            if now - hit[0] <= ttl:
                return hit[1]
            if not hit[1].get('pending'):
                if key not in _BUSY:
                    _BUSY.add(key)
                    threading.Thread(target=_renew, args=(key, builder), daemon=True,
                                     name='unified_index_renew').start()
                return hit[1]
    if _is_search(key):
        # 0.6.148 (Mac-Prüfung 0.6.144: „Geisternetze“ blieb nach dem Markierlauf 0 Treffer): eine Suche ist klein und
        # wartet nicht hinter dem Aufbau ganzer Listen (Kinderecke) auf _BUILD
        return _build_into(key, builder)
    with _BUILD:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and time.monotonic() - hit[0] <= (PENDING_TTL if hit[1].get('pending') else TTL):
                return hit[1]
        return _build_into(key, builder)


def _is_search(key):
    return isinstance(key, tuple) and len(key) > 2 and bool(key[2])


def invalidate(soft=False):
    """Forget every index. ``soft`` (0.6.144, Mac-Prüfung 0.6.142: Filme 54 s direkt nach dem Reihenfilm-Markierlauf auf
    dem Air, weil die Anfrage nach dem Leeren des Speichers hinter dem Kinderecke-Aufbau auf _BUILD wartete): the
    indexes stay readable and count as outdated – the next reader gets the previous answer at once and the renewal
    runs in the background. For content changes only; settings that must never show the old answer (Kinder-
    Altersgrenze, Anzeige) keep the hard variant."""
    with _LOCK:
        _GEN[0] += 1
        _BUSY.clear()
        if not soft:
            _CACHE.clear()
            return
        for key, (_, value) in list(_CACHE.items()):
            if value.get('pending') or _is_search(key):   # 0.6.148: Suchen neu, nicht veraltet beantworten
                _CACHE.pop(key)
            else:
                _CACHE[key] = (float('-inf'), value)


def page(root, db, kind='movies', query='', genre='', sort='title', collection='', offset=0,
         merge_duplicates=True, modules=None, language='', only='', reihen=False):
    """One page of the merged index with the full rows of each offer."""
    import catalog
    kind = 'series' if kind == 'series' else 'movies'
    query = str(query or '').strip()[:180]
    genre = str(genre or '').strip()[:80]
    sort = sort if sort in ('title', 'year') else 'title'
    collection = collection if collection in ('cinema', 'series') else ''
    try:
        offset = max(0, min(int(offset), 10000000))
    except (TypeError, ValueError):
        offset = 0
    import languages
    language = languages.valid_filter(language)
    only = only if only in SOURCES else ''
    reihen = bool(reihen) and kind == 'movies' and not query
    key = (str(root), kind, query.casefold(), genre.casefold(), sort, collection, bool(merge_duplicates), language, only, reihen)
    index = _cached(key, lambda: build(root, db, kind, query, genre, sort, collection, merge_duplicates, modules,
                                       language, only, reihen))
    chosen = index['entries'][offset:offset + PAGE]
    items = []
    with db() as c:
        for entry in chosen:
            out = []
            for offer in entry['offers']:
                if offer['source'] == 'mediatheken':
                    work = c.execute('SELECT * FROM works WHERE id=?', (offer['id'],)).fetchone()
                    row = catalog.item(c, work)
                    if not row:
                        continue   # merged or removed since the index was built
                    row.update(episodes=offer['episodes'], series_parent=work['kind'] == 'series' and kind == 'series')   # 0.6.137: Reihenfilm under Filme
                    if offer.get('reihe'):
                        # 0.6.150: Filmreihe unter Filme (Tatort, Polizeiruf …) öffnet wie eine Serie ihre Filme
                        row.update(series_parent=True, reihe=True, reihe_key=offer['reihe'], film_count=offer['episodes'])   # 0.6.156: show_key bleibt echt (Mac-Prüfung 0.6.155: „Serie nicht gefunden“)
                    elif kind != 'series':
                        catalog.as_series_film(row)   # 0.6.140: film title and year
                    lang = row.get('languages') or {}
                    row.update(lang=lang.get('short', ''), lang_text=lang.get('text', ''))
                    out.append({'source': 'mediatheken', 'item': row})
                else:
                    item = offer['item']
                    try:
                        lang = languages.for_portal(root, offer['source'], item, name=NAMES.get(offer['source'], ''))
                        item.update(lang=lang['short'], lang_text=lang['text'])
                    except Exception:
                        pass
                    out.append({'source': offer['source'], 'item': item})
            if out:
                items.append({'title': entry['title'], 'year': entry['year'], 'offers': out})
                if entry.get('local'):
                    items[-1]['local'] = True        # 0.6.148: geladen (lokale Kopie)
                if entry.get('mehrteiler'):
                    items[-1]['mehrteiler'] = entry['mehrteiler']   # 0.6.150
    return {'items': items, 'total': len(index['entries']), 'offset': offset, 'page': PAGE,
            'counts': index['counts'], 'errors': index['errors'], 'genre_counts': index['genre_counts'],
            'merged': index['merged'], 'names': NAMES, 'pending': index.get('pending') or [],
            'language': language, 'only': only,
            'index': index.get('serial')}   # 0.6.116: Kennung des Index-Stands – wer blättert, erkennt einen Neuaufbau zwischen den Seiten
