"""0.6.46 Kinderfilme und Kinderserien in der Kinderecke (Björn, 20.11.2026: „Kinderfilme und -serien
sollen auch in der Kinderecke verfügbar sein“).

Bis 0.6.45 zeigte die Kinderecke (/kinder, web/kids.*) nur die fertig geladenen Videos der YouTube-Abos
im Profil „Kinder“. Dieses Modul ergänzt Filme und Serien aus dem gemeinsamen Katalog (unified_index):

* Aufgenommen wird nur, was dort unter der festen Kategorie „Kinder“ steht. Diese Kategorie ist bewusst
  streng (categories.refine, catalog.category_clause, 0.5.103): nur eindeutige Kinder-Signale, nie neben
  Horror/Thriller/Krimi/Erotik/Krieg, höchstens FSK 6, und erst nach dem Abgleich der Metadaten
  („Unklassifiziert“ kommt nie hinein). „Familie“ allein reicht nicht.
* Nur Quellen, die im eigenen Player ohne Kopierschutz laufen: ARD/ZDF & Co., Netzkino, Pluto TV,
  JustWatch TV, Rakuten TV, TOGGO, Plex, ServusTV. Joyn, RTL+ und Crunchyroll öffnen nur beim Anbieter,
  YouTube-Katalogtitel nur im YouTube-Player mit fremden Vorschlägen: Beides führt aus der Kinderecke
  hinaus und bleibt draußen. Eine fertige Offline-Kopie spielt automatisch lokal (streaming.resolve).
* Serienfolgen von ARD/ZDF werden je Folge noch einmal geprüft: eine Folge mit Ausschluss-Genre erscheint
  nicht, auch wenn die Serie als Ganzes passt (0.6.91: Folgen ohne eigene Kinder-Einordnung bleiben drin).
* 0.6.91: Als eindeutiges Kinder-Signal zählt auch der Sender (KiKA) oder eine Kinder-/Märchenreihe des Angebots
  (catalog.kids_signal_clause), weil erkannte Filme nur die Referenz-Genres tragen.
* Folgen und Abspielen gibt es nur für Titel, die gerade in dieser Liste stehen (``allowed``): Die
  Kinderecke kann so keine beliebigen Katalogeinträge öffnen.
"""
from __future__ import annotations

import re
import threading
import time

REF_KEYS = ('offer', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'toggo', 'plex', 'servustv', 'job')
SOURCES = ('mediatheken', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'toggo', 'plex', 'servustv')
CATEGORY = 'Kinder'
# 0.6.91: 240 je Art schnitt die Liste nach dem Titel ab: Mit großen Kinderkatalogen von Pluto TV, Rakuten und
# JustWatch endete sie bei „D…“, Märchenfilme wie „Die Gänsemagd“ oder „Schneewittchen“ kamen nie an.
MAX_TITLES = 1500         # je Art (Filme, Serien)
MAX_EPISODES = 400
TTL = 120.0
_SAFE_ID = re.compile(r'^[A-Za-z0-9_.:\-]{1,200}$')

_LOCK = threading.Lock()
_CACHE = {}               # root -> (monotonic, shelf)
_BUILDING = set()         # 0.6.81: Wurzeln, deren Liste gerade im Hintergrund erneuert wird


def _https(value):
    value = str(value or '')
    return value if value.startswith('https://') and len(value) <= 600 and not any(ch in value for ch in ' <>"\'') else ''


def _year(value):
    try:
        year = int(str(value or '')[:4])
    except (TypeError, ValueError):
        return None
    return year if 1880 <= year <= 2100 else None


def _seconds(value):
    try:
        value = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    return value if 0 < value < 86400 else 0


def watch_key(ref):
    """Schlüssel für Weiterschauen (watch_state.KEY): '<quelle>:<id>' wie im großen Player."""
    for name, value in (ref or {}).items():
        key = '%s:%s' % (name, value)
        if _SAFE_ID.fullmatch(key):
            return key
    return ''


def _tile(source, kind, title, year, poster, ref=None, series=None, duration=0):
    entry = {'source': source, 'kind': kind, 'title': str(title or 'Ohne Titel')[:200], 'year': _year(year),
             'poster': _https(poster), 'duration': _seconds(duration)}
    if ref:
        entry['ref'] = ref
        entry['key'] = watch_key(ref)
    if series:
        entry['series'] = series
    entry['id'] = '%s:%s' % (source, (ref or series or {}).get('id') or next(iter((ref or series or {}).values()), ''))
    return entry


def _from_offer(offer, view):
    """Kachel aus einem Angebot des gemeinsamen Katalogs; None, wenn es hier nicht abspielbar ist."""
    source, item = offer.get('source'), offer.get('item') or {}
    if source not in SOURCES:
        return None
    if source == 'mediatheken':
        meta = item.get('metadata') or {}
        title = meta.get('title') or (item.get('source') or {}).get('title')
        if item.get('series_parent') or view == 'series':
            show = str(item.get('show_key') or '')
            if not show or len(show) > 200:
                return None
            return _tile(source, 'series', title, meta.get('year'), meta.get('poster'), series={'show': show})
        if not item.get('available') and not item.get('downloaded'):
            return None
        return _tile(source, 'movie', title, meta.get('year'), meta.get('poster'), ref={'offer': str(item.get('id') or '')},
                     duration=(item.get('source') or {}).get('duration'))
    item_id = str(item.get('id') or '')
    if source == 'netzkino':
        if item.get('kind') == 'series' or view == 'series':
            key = str(item.get('series_key') or '')
            if not re.fullmatch(r'series-[a-f0-9]{24}', key):
                return None
            return _tile(source, 'series', item.get('title'), item.get('year'), item.get('poster'), series={'id': key})
        if not re.fullmatch(r'[a-f0-9]{32}', item_id):
            return None
        return _tile(source, 'movie', item.get('title'), item.get('year'), item.get('poster'), ref={'netzkino': item_id},
                     duration=item.get('duration'))
    if not item_id or len(item_id) > 200:
        return None
    if item.get('kind') == 'series' or view == 'series':
        return _tile(source, 'series', item.get('title'), item.get('year'), item.get('poster'), series={'id': item_id})
    if item.get('playable') in (0, False, None) or item.get('kind') == 'channel':
        return None
    return _tile(source, 'movie', item.get('title'), item.get('year'), item.get('poster'), ref={source: item_id},
                 duration=item.get('duration'))


def build(root, db, modules=None, merge=True, page=None):
    """{'movies': [...], 'series': [...], 'pending': bool} aus unified_index (Kategorie „Kinder“)."""
    if page is None:
        import unified_index
        page = unified_index.page
    out, pending = {}, False
    for view in ('movies', 'series'):
        tiles, seen, offset = [], set(), 0
        while len(tiles) < MAX_TITLES:
            data = page(root, db, kind=view, genre=CATEGORY, sort='title', offset=offset, merge_duplicates=merge, modules=modules)
            items = data.get('items') or []
            pending = pending or bool(data.get('pending'))
            for entry in items:
                # die erste abspielbare Quelle eines zusammengeführten Titels (Reihenfolge des Katalogs)
                tile = next((t for t in (_from_offer(o, view) for o in entry.get('offers') or []) if t), None)
                if tile and tile['id'] not in seen:
                    seen.add(tile['id'])
                    tiles.append(tile)
            offset += len(items)
            if not items or offset >= int(data.get('total') or 0):
                break
        out[view] = tiles[:MAX_TITLES]
    out['pending'] = pending
    return out


def shelf(root, db, modules=None, merge=True, page=None, fresh=False):
    """Zwischengespeichert (TTL), damit die Kinderecke beim Neuladen jede Minute nichts neu aufbaut.

    0.6.81 (Nachtdiagnose 21.11.2026: /api/kids 15,2 s): Ist die Liste älter als TTL, antwortet die Kinderecke
    sofort mit der bisherigen und baut die neue im Hintergrund (höchstens ein Aufbau gleichzeitig). Nur ohne
    jede Liste (erster Aufruf nach dem Start, vom Server vorab gebaut) oder mit ``fresh`` wird gewartet.
    """
    key = str(root)
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and not fresh:
            age = now - hit[0]
            if age <= (5.0 if hit[1].get('pending') else TTL):
                return hit[1]
            if not hit[1].get('pending'):
                if key not in _BUILDING:
                    _BUILDING.add(key)
                    threading.Thread(target=_refresh, args=(root, db, modules, merge, page), daemon=True,
                                     name='kids_shelf_refresh').start()
                return hit[1]
    return _build_store(root, db, modules, merge, page)


def _build_store(root, db, modules, merge, page):
    value = build(root, db, modules, merge, page)
    with _LOCK:
        _CACHE[str(root)] = (time.monotonic(), value)
    return value


def _refresh(root, db, modules, merge, page):
    started = time.monotonic()
    try:
        value = _build_store(root, db, modules, merge, page)
        seconds = time.monotonic() - started
        if seconds >= 2:            # 0.6.82 (Mac-Prüfung 0.6.81): langsame Erneuerung in der Diagnose sichtbar
            import diagnostics
            diagnostics.event('kids_shelf_refreshed', seconds=round(seconds, 2), movies=len(value.get('movies') or []),
                              series=len(value.get('series') or []), pending=bool(value.get('pending')))
    except Exception:
        pass                       # die bisherige Liste bleibt; der nächste Aufruf versucht es erneut
    finally:
        with _LOCK:
            _BUILDING.discard(str(root))


def invalidate():
    """Liste verwerfen (der nächste Aufruf baut neu und wartet darauf)."""
    with _LOCK:
        _CACHE.clear()


def _listed(data, source, kind, field, value):
    return any(t['source'] == source and (t.get(kind) or {}).get(field) == value
               for t in data.get('movies', []) + data.get('series', []))


def allowed_ref(data, ref):
    """Darf die Kinderecke diesen Film abspielen? Nur, was in ihrer Liste steht (oder eine geprüfte Folge)."""
    if not isinstance(ref, dict) or len(ref) != 1:
        return False
    (name, value), = ref.items()
    source = 'mediatheken' if name == 'offer' else name
    if _listed(data, source, 'ref', name, value):
        return True
    return (source, str(value)) in _EPISODES_SEEN


_EPISODES_SEEN = set()    # (quelle, id) der zuletzt ausgelieferten, geprüften Folgen


def _remember(source, episodes):
    for e in episodes:
        (name, value), = e['ref'].items()
        _EPISODES_SEEN.add(('mediatheken' if name == 'offer' else name, value))
    while len(_EPISODES_SEEN) > 20000:
        _EPISODES_SEEN.pop()


def episodes(root, c, data, source, series_id, marks=None):
    """Folgen einer Kinderserie aus der Liste, sortiert; nur abspielbare und (ARD/ZDF) einzeln geprüfte."""
    marks = marks or {}
    field = 'show' if source == 'mediatheken' else 'id'
    if source not in SOURCES or not _listed(data, source, 'series', field, series_id):
        raise ValueError('Diese Serie gibt es in der Kinderecke nicht')
    out = []
    if source == 'mediatheken':
        import catalog
        blocked = excluded_works(c, series_id)
        show = catalog.show_detail(c, series_id, limit=MAX_EPISODES)
        for e in show.get('episodes') or []:
            if e.get('work_id') in blocked or not (e.get('available') or e.get('downloaded')):
                continue
            meta, src = e.get('metadata') or {}, e.get('source') or {}
            title = meta.get('episode_title') or src.get('title') or meta.get('title')
            out.append(_episode('mediatheken', {'offer': str(e.get('id') or '')}, title, meta.get('season'), meta.get('episode'),
                                meta.get('poster') or (show.get('show') or {}).get('poster'), src.get('duration')))
    else:
        import portal_title
        model = portal_title.model(root, source, series_id)
        for e in model.get('episodes') or []:
            if not e.get('playable') or not e.get('id'):
                continue
            ref = {source: e['id']}
            out.append(_episode(source, ref, e.get('title'), e.get('season'), e.get('episode'), e.get('poster'), e.get('duration')))
    out = [e for e in out if e['key']][:MAX_EPISODES]
    for e in out:
        mark = marks.get(e['key']) or {}
        e['done'] = bool(mark.get('done'))
        e['pos'] = 0 if e['done'] else (mark.get('pos') or 0)
        e['progress'] = round(min(1, e['pos'] / e['duration']), 3) if e['duration'] and e['pos'] else 0
    _remember(source, out)
    return {'source': source, 'series': series_id, 'episodes': out}


def excluded_works(c, show_key):
    """0.6.91: Folgen einer Kinderserie, die nicht in die Kinderecke gehören (Ausschluss-Genre an der Folge).

    Bis 0.6.88 musste jede Folge selbst unter „Kinder“ stehen. Folgen ohne eigenen Abgleich („Unklassifiziert“)
    oder mit nur den Genres der Serienreferenz (IMDb „Animation“ ohne „Family“) fielen so heraus: Björn
    (22.11.2026) sah die Serien „alle leer“, obwohl ARD/ZDF-Folgen gefunden waren. Die Serie als Ganzes hat die
    Kinder-Regel bestanden; einzeln fällt nur noch heraus, was ein Ausschluss-Genre trägt (Horror, Thriller,
    Krimi, Erotik, Krieg)."""
    import catalog
    import categories
    labels = catalog.category_labels(c)
    raw = [r for name in categories.NOT_FOR_KIDS for r in labels.get(name) or []]
    if not raw:
        return set()
    return {r[0] for r in c.execute('SELECT DISTINCT w.id FROM works w JOIN work_genres g ON g.work_id=w.id WHERE w.show_key=? '
                                    'AND g.genre IN (%s)' % ','.join('?' * len(raw)), [show_key] + raw)}


def _episode(source, ref, title, season, episode, poster, duration):
    def num(v, hi):
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= hi else None
    season, episode = num(season, 999), num(episode, 9999)
    label = str(title or 'Folge')[:200]
    return {'source': source, 'ref': ref, 'key': watch_key(ref), 'title': label, 'season': season, 'episode': episode,
            'poster': _https(poster), 'duration': _seconds(duration)}


def with_progress(data, marks):
    """Kopie der Liste mit Abspielstand (Weiterschauen) je Film."""
    out = {'pending': data.get('pending', False)}
    for view in ('movies', 'series'):
        rows = []
        for t in data.get(view) or []:
            t = dict(t)
            mark = marks.get(t.get('key') or '') or {}
            t['done'] = bool(mark.get('done'))
            t['pos'] = 0 if t['done'] else (mark.get('pos') or 0)
            t['progress'] = round(min(1, t['pos'] / t['duration']), 3) if t.get('duration') and t['pos'] else 0
            rows.append(t)
        out[view] = rows
    return out
