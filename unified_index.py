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

SOURCES = ('mediatheken', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll', 'plex', 'servustv', 'rtlplus')
NAMES = {'mediatheken': 'ARD, ZDF & Co.', 'netzkino': 'Netzkino', 'pluto': 'Pluto TV',
         'justwatch': 'JustWatch TV', 'rakuten': 'Rakuten TV', 'youtube': 'YouTube', 'joyn': 'Joyn', 'toggo': 'TOGGO', 'crunchyroll': 'Crunchyroll', 'plex': 'Plex', 'servustv': 'ServusTV', 'rtlplus': 'RTL+'}
# Which offer represents a merged entry: curated catalogues first, uploads with free-text
# titles and landscape thumbnails (YouTube) and copy-protected offers (Rakuten) last.
RANK = {'mediatheken': 0, 'netzkino': 1, 'pluto': 2, 'justwatch': 3, 'rakuten': 4, 'youtube': 5, 'joyn': 6, 'toggo': 7, 'crunchyroll': 8, 'plex': 9, 'servustv': 10, 'rtlplus': 11}
# Sources whose year is the upload year, not the year of the work.
LOOSE_YEAR = {'youtube', 'servustv'}

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
          modules=None):
    """Complete merged index for one filter. ``db`` is the context-manager factory of the main
    catalogue; ``modules`` maps source -> module (tests pass fakes)."""
    import catalog
    if modules is None:
        import netzkino, pluto, justwatch, rakuten, youtube, joyn, toggo, crunchyroll, plex, servustv, rtlplus
        modules = {'netzkino': netzkino, 'pluto': pluto, 'justwatch': justwatch, 'rakuten': rakuten,
                   'youtube': youtube, 'joyn': joyn, 'toggo': toggo, 'crunchyroll': crunchyroll, 'plex': plex, 'servustv': servustv, 'rtlplus': rtlplus}
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
        with db() as c:
            # wait=False: on a cold start the grouping of the whole catalogue runs in the background
            # and the other sources are shown first (0.5.57).
            groups = catalog.listing(c, query=query, kind='series' if view == 'series' else 'movie', genre=genre,
                                     sort='title', downloaded='all', collection=collection, index_only=True,
                                     wait=False)
        found = [{'source': 'mediatheken', 'title': g[2] or 'Ohne Titel', 'year': g[3], 'id': g[0], 'episodes': g[1]}
                 for g in groups]
        offers += found
        counts['mediatheken'] = len(found)
    except catalog.ListingPending:
        pending.append('mediatheken')
    except Exception as exc:   # one broken source never hides the others
        errors['mediatheken'] = str(exc)[:160] or exc.__class__.__name__
    seconds['mediatheken'] = round(time.monotonic() - started, 2)
    for source in ('netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll', 'plex', 'servustv', 'rtlplus'):
        module = modules.get(source)
        if module is None:
            continue
        started = time.monotonic()
        try:
            if source == 'netzkino':
                found, facets = _netzkino_offers(module, root, view, query, genre, collection)
            else:
                found, facets = _portal_offers(source, module.listing, root, view, query, genre, collection)
            offers += found
            counts[source] = len(found)
            add_counts(facets)
        except Exception as exc:
            errors[source] = str(exc)[:160] or exc.__class__.__name__
        seconds[source] = round(time.monotonic() - started, 2)
    started = time.monotonic()
    entries = merge(offers, merge_duplicates, subtitles=view == 'movies')   # series: 'Star Trek' is not 'Star Trek: Voyager'
    if sort == 'year':
        entries.sort(key=lambda e: (-(e['year'] or 0), _sort_title(e['title'])))
    else:
        entries.sort(key=lambda e: _sort_title(e['title']))
    seconds['merge'] = round(time.monotonic() - started, 2)
    return {'entries': entries, 'counts': counts, 'errors': errors, 'pending': pending, 'seconds': seconds,
            'genre_counts': [{'genre': g, 'n': n} for g, n in sorted(genre_counts.items())],
            'merged': sum(1 for e in entries if len(e['offers']) > 1)}


PENDING_TTL = 2.0
_BUSY = set()
ON_BUILD = None   # set by the server: called with (key, index, seconds) after every build


def _build_into(key, builder):
    started = time.monotonic()
    value = builder()
    with _LOCK:
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
    with _BUILD:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and time.monotonic() - hit[0] <= (PENDING_TTL if hit[1].get('pending') else TTL):
                return hit[1]
        return _build_into(key, builder)


def invalidate():
    with _LOCK:
        _CACHE.clear()
        _BUSY.clear()


def page(root, db, kind='movies', query='', genre='', sort='title', collection='', offset=0,
         merge_duplicates=True, modules=None):
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
    key = (str(root), kind, query.casefold(), genre.casefold(), sort, collection, bool(merge_duplicates))
    index = _cached(key, lambda: build(root, db, kind, query, genre, sort, collection, merge_duplicates, modules))
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
                    row.update(episodes=offer['episodes'], series_parent=work['kind'] == 'series')
                    out.append({'source': 'mediatheken', 'item': row})
                else:
                    out.append({'source': offer['source'], 'item': offer['item']})
            if out:
                items.append({'title': entry['title'], 'year': entry['year'], 'offers': out})
    return {'items': items, 'total': len(index['entries']), 'offset': offset, 'page': PAGE,
            'counts': index['counts'], 'errors': index['errors'], 'genre_counts': index['genre_counts'],
            'merged': index['merged'], 'names': NAMES, 'pending': index.get('pending') or []}
