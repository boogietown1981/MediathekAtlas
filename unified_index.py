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

SOURCES = ('mediatheken', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube')
NAMES = {'mediatheken': 'ARD, ZDF & Co.', 'netzkino': 'Netzkino', 'pluto': 'Pluto TV',
         'justwatch': 'JustWatch TV', 'rakuten': 'Rakuten TV', 'youtube': 'YouTube'}
# Which offer represents a merged entry: curated catalogues first, uploads with free-text
# titles and landscape thumbnails (YouTube) and copy-protected offers (Rakuten) last.
RANK = {'mediatheken': 0, 'netzkino': 1, 'pluto': 2, 'justwatch': 3, 'rakuten': 4, 'youtube': 5}
# Sources whose year is the upload year, not the year of the work.
LOOSE_YEAR = {'youtube'}

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


def merge(offers, enabled=True):
    """offers: dicts with source, title, year (+ payload). Returns entries {title, year, offers}.

    Conservative rules: same title key; years equal, one apart (cinema vs. broadcast year) or
    unknown; never two offers of the same source in one entry (remakes, parts, duplicates of one
    provider stay separate tiles)."""
    entries, by_key = [], {}
    for offer in offers:
        loose = offer['source'] in LOOSE_YEAR
        key = title_key(offer['title'], loose) or title_key(offer['title'])
        year = None if loose else _year(offer.get('year'))
        target = None
        if enabled and key:
            for entry in by_key.get(key, ()):
                if offer['source'] in entry['sources']:
                    continue
                if year is None or entry['year'] is None or abs(year - entry['year']) <= 1:
                    target = entry
                    break
        if target is None:
            target = {'key': key, 'year': year, 'sources': set(), 'offers': []}
            entries.append(target)
            if key:
                by_key.setdefault(key, []).append(target)
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
        import netzkino, pluto, justwatch, rakuten, youtube
        modules = {'netzkino': netzkino, 'pluto': pluto, 'justwatch': justwatch, 'rakuten': rakuten,
                   'youtube': youtube}
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
    for source in ('netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube'):
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
    entries = merge(offers, merge_duplicates)
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
