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
* 0.6.98: Eine ARD/ZDF-Reihe muss selbst eindeutig Kinderprogramm sein (show_is_kids); ein einzelnes Werk mit
  „Kinder“ öffnet keine Nachrichten- oder Talkreihe mehr.
* 0.6.91: Als eindeutiges Kinder-Signal zählt auch der Sender (KiKA) oder eine Kinder-/Märchenreihe des Angebots
  (catalog.kids_signal_clause), weil erkannte Filme nur die Referenz-Genres tragen.
* Folgen und Abspielen gibt es nur für Titel, die gerade in dieser Liste stehen (``allowed``): Die
  Kinderecke kann so keine beliebigen Katalogeinträge öffnen.
"""
from __future__ import annotations

import re
import threading
import time

REF_KEYS = ('offer', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'toggo', 'plex', 'servustv', 'job',
            'samsung', 'redbulltv')   # 0.6.99: Live-Sender (Samsung TV Plus, Red Bull TV) der Kinderecke
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
    offer = _dict(offer)
    source, item = offer.get('source'), _dict(offer.get('item'))
    if source not in SOURCES:
        return None
    if source == 'mediatheken':
        meta, src = _dict(item.get('metadata')), _dict(item.get('source'))
        title = meta.get('title') or src.get('title')
        if item.get('series_parent') or view == 'series':
            show = str(item.get('show_key') or '')
            if not show or len(show) > 200:
                return None
            return _tile(source, 'series', title, meta.get('year'), meta.get('poster'), series={'show': show})
        if not item.get('available') and not item.get('downloaded'):
            return None
        return _tile(source, 'movie', title, meta.get('year'), meta.get('poster'), ref={'offer': str(item.get('id') or '')},
                     duration=src.get('duration'))
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
                try:
                    tile = next((t for t in (_from_offer(o, view) for o in _dict(entry).get('offers') or []) if t), None)
                except Exception as exc:   # 0.6.103: ein Titel mit unerwarteter Form wird übersprungen, nie die ganze Liste
                    _skipped(entry, exc)
                    tile = None
                if tile and tile['id'] not in seen:
                    seen.add(tile['id'])
                    try:
                        tile['group'] = group_of(entry)
                    except Exception as exc:   # 0.6.103: eine unerwartete Angebotsform kostet nie die ganze Liste
                        _skipped(entry, exc)
                        tile['group'] = 'mehr'
                    tiles.append(tile)
            offset += len(items)
            if not items or offset >= int(data.get('total') or 0):
                break
        out[view] = tiles[:MAX_TITLES]
    out['series'] = _kids_shows(db, out['series'])
    _fold_small_groups(out)
    out['groups'] = [{'id': g, 'name': name, 'icon': icon} for g, name, icon, _ in GROUPS
                     if any(t.get('group') == g for v in ('movies', 'series') for t in out[v])]
    out['pending'] = pending
    return out


# 0.6.93 (Björn, 22.11.2026: „für Filme und Serien noch eine Gruppierung, die es meiner Tochter leichter macht, etwas
# zu finden, also nicht zu granular, aber auch nicht alles in einem Ordner“): wenige feste Gruppen mit Bild-Symbol,
# abgeleitet aus den Kategorien (categories.py) und Texten des Katalogs (Titel, Reihe, Rohgenres), ohne KI.
# Jeder Titel steht in genau einer Gruppe (die erste passende); Gruppen mit weniger als MIN_GROUP Titeln gehen in
# „Noch mehr“, damit es nicht zu fein wird.
GROUPS = (
    ('maerchen', 'Märchen', '🏰', re.compile(r'(?i)m(?:ä|a|ae)rchen|fairy ?tale|sechs auf einen streich|grimm|andersen|prinzessin|princess')),
    ('trick', 'Zeichentrick', '🎨', re.compile(r'(?i)\banim|zeichentrick|trickfilm|cartoon|\banime\b')),
    ('tiere', 'Tiere & Natur', '🐾', re.compile(r'(?i)\btiere?\b|animal|natur|wildlife|\bzoo\b|bauernhof|\bpferd|\bhund|\bkatze')),
    ('wissen', 'Wissen', '🔬', re.compile(r'(?i)wissen|doku|documentar|science(?! ?fiction)|\bchecker|sendung mit der maus|löwenzahn|planet schule|experiment|erklär')),
    ('abenteuer', 'Abenteuer', '🗺️', re.compile(r'(?i)abenteuer|adventure|fantasy|action|science.?fiction|piraten|ritter|drache|weltraum')),
    ('lustig', 'Lustiges', '😂', re.compile(r'(?i)kom(?:ö|o|oe)die|comedy|lustig|witzig|sitcom|slapstick')),
    ('mehr', 'Noch mehr', '⭐', None),
)
GROUP_CATEGORIES = {'trick': {'Animation'}, 'tiere': {'Natur & Tiere'}, 'wissen': {'Wissen & Technik', 'Dokumentation'},
                    'abenteuer': {'Abenteuer', 'Fantasy', 'Action', 'Science-Fiction'}, 'lustig': {'Komödie'}}
MIN_GROUP = 3


def _dict(value):
    return value if isinstance(value, dict) else {}


_SKIP_LOGGED = set()


def _skipped(entry, exc):
    """Einen übersprungenen Titel protokollieren (je Fehlerart einmal je Programmlauf)."""
    kind = '%s: %s' % (type(exc).__name__, str(exc)[:120])
    if kind in _SKIP_LOGGED:
        return
    _SKIP_LOGGED.add(kind)
    try:
        import diagnostics
        diagnostics.event('kids_title_skipped', error=kind, title=str(_dict(entry).get('title') or '')[:80])
    except Exception:
        pass


def _signals(entry):
    """(Kategorien, Text) aller Angebote eines zusammengeführten Titels.

    0.6.103 (Björn 22.11.2026 mit 0.6.99: Kinderecke leer, Live-Sender „'str' object has no attribute 'get'“): bei
    Plattform-Angeboten ist ``item['source']`` ein Text (Anbietername), kein Angebot wie bei den Mediatheken. Jedes Feld
    wird deshalb nur gelesen, wenn es die erwartete Form hat."""
    cats, text = set(), [str(entry.get('title') or '')]
    for offer in entry.get('offers') or []:
        item = _dict(_dict(offer).get('item'))
        for c in item.get('categories') or []:
            if isinstance(c, str):
                cats.add(c)
        meta, src = _dict(item.get('metadata')), _dict(item.get('source'))
        for value in (item.get('title'), item.get('genre'), meta.get('title'), src.get('topic'), src.get('title')):
            if isinstance(value, str):
                text.append(value)
        for many in (item.get('source_genres'), meta.get('genres'), item.get('genres')):
            if isinstance(many, (list, tuple)):
                text.extend(str(x) for x in many[:20])
    return cats, ' | '.join(text)[:2000]


def group_of(entry):
    """Gruppe eines Katalogtitels: Märchen vor Zeichentrick (Märchen gibt es auch gezeichnet), sonst Kategorie oder Text."""
    cats, text = _signals(entry)
    for gid, _name, _icon, rx in GROUPS:
        if rx is None:
            return gid
        if (GROUP_CATEGORIES.get(gid, set()) & cats) or rx.search(text):
            return gid
    return 'mehr'


def _fold_small_groups(out):
    counts = {}
    for view in ('movies', 'series'):
        for t in out.get(view) or []:
            counts[t.get('group')] = counts.get(t.get('group'), 0) + 1
    for view in ('movies', 'series'):
        for t in out.get(view) or []:
            if counts.get(t.get('group'), 0) < MIN_GROUP:
                t['group'] = 'mehr'


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
    if (name, str(value)) in _LIVE_SEEN:          # 0.6.99: zuletzt ausgelieferte Kinder-Live-Sender
        return True
    return (source, str(value)) in _EPISODES_SEEN


_EPISODES_SEEN = set()    # (quelle, id) der zuletzt ausgelieferten, geprüften Folgen
_LIVE_SEEN = set()        # 0.6.99: (ref-Name, id) der zuletzt ausgelieferten Kinder-Live-Sender


def live(c, root):
    """0.6.99: Kinder- und Familiensender (live_tv.kids_stations); merkt sie für /api/kids-play."""
    import live_tv
    stations = live_tv.kids_stations(c, root)
    _LIVE_SEEN.clear()
    for st in stations:
        (name, value), = st['ref'].items()
        _LIVE_SEEN.add((name, str(value)))
    return stations


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
            meta, src = _dict(e.get('metadata')), _dict(e.get('source'))
            title = meta.get('episode_title') or src.get('title') or meta.get('title')
            out.append(_episode('mediatheken', {'offer': str(e.get('id') or '')}, title, meta.get('season'), meta.get('episode'),
                                meta.get('poster') or _dict(show.get('show')).get('poster'), src.get('duration')))
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


# 0.6.98 (Mac-Prüfung 0.6.91 nicht bestanden: „Politik“, „NACHTCAFÉ“, „heute“, „Aktuelle Kamera“, „Abendschau“
# öffneten Hunderte Folgen mit Nachrichten und Beiträgen über Krankheit und Krieg). Eine Reihe stand schon in 0.6.90
# in der Liste, sobald EIN Werk „Kinder“ trug (Politik 11 von 2.047, heute 16 von 12.005, Abendschau 2 von 432 –
# Genre aus Beschreibung/Beitragstitel, broadcaster.genres); 0.6.91 öffnete dann alle Folgen. Jetzt:
# * Eine ARD/ZDF-Reihe gehört nur hinein, wenn sie selbst eindeutig Kinderprogramm ist: unter den letzten
#   SHOW_SAMPLE Werken sind mindestens SHOW_SHARE der eingeordneten Kinderprogramm (Kinder-Regel oder KiKA/TOGGO/
#   Kinderreihe); Werke ohne Einordnung oder nur mit kinderfreundlichen Kategorien zählen nicht dagegen.
# * Nachrichten-, Talk-, Politik- und Magazinnamen (NOT_KIDS_SHOW) nie, außer der Name sagt Kinder (logo!, KiKA).
# * Je Folge: eine Folge mit Ausschluss-Genre oder mit einer Kategorie außerhalb von KIDS_FRIENDLY (Nachrichten,
#   Talk, Drama, Dokumentation …) erscheint nur, wenn sie selbst Kinderprogramm ist.
SHOW_SHARE = 0.8
SHOW_SAMPLE = 100
KIDS_FRIENDLY = ('Kinder', 'Familie', 'Animation', 'Abenteuer', 'Fantasy', 'Komödie', 'Natur & Tiere',
                 'Wissen & Technik', 'Musik', 'Musical')
NOT_KIDS_SHOW = re.compile(
    r'(?i)\b(?:heute|tagesschau|tagesthemen|nachrichten|news|journal|politik\w*|abendschau|landesschau|aktuelle kamera|'
    r'brisant|frontal|zib|nachtcaf[eé]|3nach9|extra 3|talk\w*|magazin\w*|review|schlager\w*|crisis|maischberger|'
    r'lanz|illner|hart aber fair|presseclub|kontraste|panorama|monitor|plusminus|report|mex|markt|reportage\w*|'
    r'kriminal\w*|aktenzeichen|tatort|polizeiruf|wetter|sportschau|sportstudio)\b')
KIDS_NAME = re.compile(r'(?i)kinder|\bkids?\b|\bkika\b|logo!|\btivi\b|sendung mit der maus|sandmännchen|checker|toggo')


def show_name_blocked(title):
    title = str(title or '')
    return bool(NOT_KIDS_SHOW.search(title)) and not KIDS_NAME.search(title)


def _work_query(c):
    """Abfrage je Reihe vorbereiten (Kategorie-Etiketten und Kinderreihen einmal lesen, nicht je Reihe)."""
    import catalog
    import categories
    kids, kids_args = catalog.category_clause(c, CATEGORY)
    sig, sig_args = catalog.kids_signal_clause(c)
    labels = catalog.category_labels(c)
    bad = [r for name in categories.NOT_FOR_KIDS for r in labels.get(name) or []]
    bad_sql = ('EXISTS(SELECT 1 FROM work_genres b WHERE b.work_id=w.id AND b.genre IN (%s))' % ','.join('?' * len(bad))) if bad else '0'
    sql = ("SELECT w.id, ((%s) OR ((%s) AND NOT %s)) AS kids, %s AS bad, "
           "(SELECT group_concat(g.genre, char(31)) FROM work_genres g WHERE g.work_id=w.id) AS genres "
           "FROM works w WHERE w.show_key=? ORDER BY w.rowid DESC LIMIT ?" % (kids, sig, bad_sql, bad_sql))
    return sql, list(kids_args) + list(sig_args) + bad + bad, {}


def _work_rows(c, show_key, limit=None, query=None):
    """[(work_id, kids, against)] je Werk der Reihe (neueste zuerst)."""
    import categories
    sql, args, names_of = query or _work_query(c)
    friendly = set(KIDS_FRIENDLY)
    out = []
    for wid, is_kids, is_bad, genres in c.execute(sql, args + [show_key, int(limit or -1)]):
        names = set()
        for raw in (genres or '').split('\x1f'):
            if raw:
                if raw not in names_of:
                    names_of[raw] = set(categories.of_label(raw))
                names |= names_of[raw]
        # „kids“ folgt der Kinder-Regel (catalog.category_clause): 0.6.99 lässt KiKA/TOGGO und Elternfreigaben
        # auch neben einem Ausschluss-Genre zu, sonst schließt die Regel es selbst aus
        against = not is_kids and (bool(is_bad) or bool(names - friendly))
        out.append((wid, bool(is_kids), against))
    return out


def show_is_kids(c, show_key, title='', query=None):
    """Ist die ARD/ZDF-Reihe selbst eindeutig Kinderprogramm? (Regel oben; 0.6.99: Elternfreigabe/-sperre gehen vor)"""
    import kids_rules
    if kids_rules.show_allowed(c, show_key):
        return True
    # 0.6.103 (Björn: „alles was definitiv von KiKA oder TOGGO kommt“): eine Reihe mit Angeboten vom Kindersender
    # gilt vor Anteil und Namenssperre („Wissen macht Ah!“ 48 %, „Der Krieg und ich“, „KiKA LIVE“)
    if c.execute("SELECT 1 FROM works w JOIN offers k ON k.work_id=w.id AND k.active=1 WHERE w.show_key=? "
                 "AND lower(trim(json_extract(k.payload,'$.channel'))) IN (%s) LIMIT 1" % ','.join('?' * len(kids_rules.ALWAYS_CHANNELS)),
                 [show_key] + list(kids_rules.ALWAYS_CHANNELS)).fetchone():
        return True
    if show_name_blocked(title):
        return False
    rows = _work_rows(c, show_key, SHOW_SAMPLE, query)
    kids = sum(1 for _, k, _ in rows if k)
    against = sum(1 for _, k, a in rows if a and not k)
    return kids > 0 and kids >= SHOW_SHARE * (kids + against)


def _kids_shows(db, tiles):
    """Nur Reihen der Mediatheken behalten, die selbst Kinderprogramm sind (eine Verbindung für alle)."""
    shows = [t for t in tiles if t.get('source') == 'mediatheken' and (t.get('series') or {}).get('show')]
    if not shows or db is None:
        return tiles
    with db() as c:
        query = _work_query(c)
        drop = {t['id'] for t in shows if not show_is_kids(c, t['series']['show'], t.get('title'), query)}
    return [t for t in tiles if t['id'] not in drop]


def excluded_works(c, show_key):
    """Folgen einer Kinderreihe, die nicht in die Kinderecke gehören.

    0.6.91: Folgen ohne eigenen Abgleich bleiben drin (sonst waren Kinderserien „leer“). 0.6.98: heraus fällt jede
    Folge mit Ausschluss-Genre und jede, die eine Kategorie außerhalb von KIDS_FRIENDLY trägt (Nachrichten, Talk,
    Drama, Dokumentation …), ohne selbst Kinderprogramm zu sein. Ist die Reihe selbst kein Kinderprogramm
    (show_is_kids), fallen alle Folgen heraus."""
    import kids_rules
    rows = _work_rows(c, show_key)
    # 0.6.99: von den Eltern gesperrte Serie/Folgen fallen heraus, einzeln freigegebene Folgen bleiben drin
    blocked = kids_rules.blocked_works(c, show_key)
    if blocked is None or not show_is_kids(c, show_key, _show_title(c, show_key)):
        return {wid for wid, _, _ in rows}
    out = {wid for wid, kids, against in rows if against and not kids}
    allowed = {r[0] for r in c.execute("SELECT substr(key,6) FROM kids_choices WHERE choice='allow' AND key LIKE 'work:%'")} if out else set()
    return (out - allowed) | blocked


def _show_title(c, show_key):
    row = c.execute('SELECT title FROM works WHERE show_key=? ORDER BY rowid DESC LIMIT 1', (show_key,)).fetchone()
    return row[0] if row else ''


def _episode(source, ref, title, season, episode, poster, duration):
    def num(v, hi):
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= hi else None
    season, episode = num(season, 999), num(episode, 9999)
    label = str(title or 'Folge')[:200]
    return {'source': source, 'ref': ref, 'key': watch_key(ref), 'title': label, 'season': season, 'episode': episode,
            'poster': _https(poster), 'duration': _seconds(duration)}


def with_progress(data, marks):
    """Kopie der Liste mit Abspielstand (Weiterschauen) je Film."""
    out = {'pending': data.get('pending', False), 'groups': data.get('groups') or []}
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
