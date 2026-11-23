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


def _platform_ok(source, item, view, limit):
    """0.6.109 (Mac-Prüfung 0.6.106): Plattform-Titel nach der AKTUELLEN Altersgrenze und strengerer Serienregel.

    * Die Kategorie „Kinder“ der Plattform-Kataloge wird beim Abgleich mit der damaligen Grenze berechnet; bei
      Grenze 6 blieben Netzkino-Filme mit FSK 12 („Run The Race“, „Die Bockreiter“) drin. Jetzt zählt die eigene
      FSK-Angabe des Anbieters gegen die Grenze im Elternbereich.
    * Serien kommen nicht über den Altersweg (Familie + FSK): Pluto-Familienserien für Erwachsene („Familie Dr. Kleist“,
      „Eine himmlische Familie“, „Moesha“, „Sabrina“) – nur mit Kinder-Genre bzw. Familie + Animation des Anbieters.
      TOGGO ist Kindersender und immer zugelassen."""
    import categories
    import portal_reference
    if source == 'toggo':
        return True
    age = portal_reference.age_of(item)
    if age is not None and age > limit:
        return False
    if item.get('kind') == 'series' or view == 'series':
        labels = []
        for many in (item.get('source_genres'), item.get('genres')):
            if isinstance(many, (list, tuple)):
                labels.extend(str(x) for x in many[:20])
        if isinstance(item.get('genre'), str):
            labels.extend(portal_reference.split_labels(item['genre']))
        return 'Kinder' in categories.refine(categories.of_labels(labels), age)
    return True


def _from_offer(offer, view, limit=None):
    """Kachel aus einem Angebot des gemeinsamen Katalogs; None, wenn es hier nicht abspielbar ist."""
    offer = _dict(offer)
    source, item = offer.get('source'), _dict(offer.get('item'))
    if source not in SOURCES:
        return None
    if source != 'mediatheken' and limit is not None and not _platform_ok(source, item, view, limit):
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
        # 0.6.112 (Mac-Prüfung 0.6.109: alle 231 TOGGO- und 18 Rakuten-Reihen öffneten ohne Folge, Kopierschutz):
        # eine Reihe, die der Anbieter als nicht abspielbar führt, erscheint nicht (Kopierschutz wird nicht umgangen)
        if item.get('playable') in (0, False) or item.get('drm') in (1, True):
            return None
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
    limit = _current_limit(db)
    for view in ('movies', 'series'):
        tiles, seen, offset = [], set(), 0
        while len(tiles) < MAX_TITLES:
            data = page(root, db, kind=view, genre=CATEGORY, sort='title', offset=offset, merge_duplicates=merge, modules=modules)
            items = data.get('items') or []
            pending = pending or bool(data.get('pending'))
            for entry in items:
                # die erste abspielbare Quelle eines zusammengeführten Titels (Reihenfolge des Katalogs)
                try:
                    tile = next((t for t in (_from_offer(o, view, limit) for o in _dict(entry).get('offers') or []) if t), None)
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
    out['movies'], out['series'] = _word_safe(db, out['movies']), _word_safe(db, out['series'])
    out['movies'] = _prefer_kids_offers(db, out['movies'])
    out['movies'], out['series'] = _parent_blocks(db, out['movies']), _parent_blocks(db, out['series'])
    _fold_small_groups(out)
    out['groups'] = [{'id': g, 'name': name, 'icon': icon} for g, name, icon, _ in GROUPS
                     if any(t.get('group') == g for v in ('movies', 'series') for t in out[v])]
    out['pending'] = pending
    return out


def _current_limit(db):
    """Altersgrenze aus dem Elternbereich (Standard 12)."""
    import categories
    import kids_rules
    if db is None:
        return categories.KIDS_MAX_AGE
    try:
        with db() as c:
            return kids_rules.max_age(c)
    except Exception:
        return categories.KIDS_MAX_AGE


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


_GEN = [0]   # 0.6.112: eine vor invalidate() begonnene Liste wird nicht gespeichert (alte Altersgrenze/Freigabe)


def _build_store(root, db, modules, merge, page):
    gen = _GEN[0]
    value = build(root, db, modules, merge, page)
    with _LOCK:
        if gen == _GEN[0]:
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
        _GEN[0] += 1
        _CACHE.clear()


def _listed(data, source, kind, field, value):
    return any(t['source'] == source and (t.get(kind) or {}).get(field) == value
               for t in data.get('movies', []) + data.get('series', []))


def allowed_ref(data, ref, c=None):
    """Darf die Kinderecke diesen Film abspielen? Nur, was in ihrer Liste steht (oder eine geprüfte Folge).

    0.6.109 (Mac-Prüfung 0.6.106: „ARD Livestream“ über die Reihe „Livestream“ abspielbar): mit Verbindung ``c``
    prüft der Server ein Mediatheken-Angebot zusätzlich je Werk nach derselben Regel wie die Liste."""
    if not isinstance(ref, dict) or len(ref) != 1:
        return False
    (name, value), = ref.items()
    source = 'mediatheken' if name == 'offer' else name
    if (name, str(value)) in _LIVE_SEEN:          # 0.6.99: zuletzt ausgelieferte Kinder-Live-Sender (nur „Fernsehen“)
        return True
    if not (_listed(data, source, 'ref', name, value) or (source, str(value)) in _EPISODES_SEEN):
        return False
    if c is not None and name == 'offer':
        return offer_allowed(c, str(value))
    return True


def offer_allowed(c, offer_id):
    """Ein Mediatheken-Angebot ist in der Kinderecke zulässig (siehe work_allowed)."""
    row = c.execute('SELECT work_id FROM offers WHERE id=?', (str(offer_id),)).fetchone()
    return bool(row) and work_allowed(c, row[0], str(offer_id))


def work_allowed(c, work_id, offer_id=None):
    """EINE Entscheidung je Werk/Angebot für Liste, Folgenliste, /api/kids-play und Nachladen (0.6.109).

    ``work_id``: works.id (Film oder Folge der Mediatheken); ``offer_id``: optional das konkrete Angebot (dann zählen
    dessen Sender und Titel, sonst alle aktiven Angebote des Werks). False für: Livestream, von den Eltern gesperrt,
    Sperrwort im Titel ohne Kindersender/Elternfreigabe, Folge außerhalb von show_basis/excluded_works, Film ohne
    Kinder-Regel (catalog.category_clause „Kinder“)."""
    import catalog
    import kids_rules
    w = c.execute('SELECT id, kind, show_key, title FROM works WHERE id=?', (str(work_id),)).fetchone()
    if not w:
        return False
    wid, kind, show, title = w[0], w[1], w[2], w[3]
    live, live_args = kids_rules.live_clause()
    if c.execute('SELECT 1 FROM works w WHERE w.id=? AND ' + live, [wid] + live_args).fetchone():
        return False
    if offer_id:
        offers = c.execute("SELECT lower(trim(json_extract(payload,'$.channel'))), json_extract(payload,'$.title') FROM offers "
                           "WHERE id=? AND work_id=?", (str(offer_id), wid)).fetchall()
        if not offers:
            return False
    else:
        offers = c.execute("SELECT lower(trim(json_extract(payload,'$.channel'))), json_extract(payload,'$.title') FROM offers "
                           "WHERE work_id=? AND active=1", (wid,)).fetchall()
    allowed = bool(c.execute("SELECT 1 FROM kids_choices WHERE key=? AND choice='allow'", ('work:' + wid,)).fetchone())
    # 0.6.113 (Mac-Prüfung 0.6.112: Young Crime/POV/#Ukraine spielten das ZDF-/WDR-/rbtv-Angebot eines Werks, das über
    # seinen KiKA-Zwilling zugelassen war): hat das Werk ein aktives Kindersender-Angebot, ist nur dieses zulässig
    twin = kids_offer(c, wid)
    if offer_id and twin and twin[0] != str(offer_id) and not allowed:
        return False
    kids_channel = allowed or any(ch in _kids_channels() for ch, _ in offers)
    if not kids_channel and (word_blocked(title) or any(word_blocked(t) for _, t in offers)):
        return False
    if kind == 'series' and show:
        return episode_paths(c, show).get(wid) is not None
    clause, args = catalog.category_clause(c, CATEGORY)
    return bool(c.execute('SELECT 1 FROM works w WHERE w.id=? AND (%s)' % clause, [wid] + list(args)).fetchone())


def kids_offer(c, work_id):
    """(offer_id, Sender) des aktiven Kindersender-Angebots eines Werks (KiKA vor TOGGO/ZDFtivi, stabil) oder None.
    Die Kinderecke spielt und lädt bei solchen Werken immer dieses Angebot (0.6.113)."""
    chans = sorted(_kids_channels())
    row = c.execute("SELECT id, json_extract(payload,'$.channel') FROM offers WHERE work_id=? AND active=1 "
                    "AND lower(trim(json_extract(payload,'$.channel'))) IN (%s) ORDER BY id LIMIT 1" % ','.join('?' * len(chans)),
                    [str(work_id)] + chans).fetchone()
    return (row[0], str(row[1] or '')) if row else None


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
        paths = episode_paths(c, series_id)
        show = catalog.show_detail(c, series_id, limit=MAX_EPISODES)
        for e in show.get('episodes') or []:
            path = paths.get(e.get('work_id'))
            if path is None or not (e.get('available') or e.get('downloaded')):
                continue
            meta, src = _dict(e.get('metadata')), _dict(e.get('source'))
            title = meta.get('episode_title') or src.get('title') or meta.get('title')
            # 0.6.106: Folgentitel mit heiklen Wörtern („Täter“, „Verhütung“) nur von Kindersendern oder mit Freigabe
            if word_blocked(title) and path not in ('freigabe', 'sender') and str(src.get('channel') or '').strip().lower() not in _kids_channels():
                continue
            offer_id, channel = str(e.get('id') or ''), str(src.get('channel') or '')
            if path == 'sender' and channel.strip().lower() not in _kids_channels():
                twin = kids_offer(c, e.get('work_id'))       # 0.6.113: den KiKA-Zwilling spielen, nicht ZDF/WDR/rbtv
                if not twin:
                    continue
                offer_id, channel = twin
            ep = _episode('mediatheken', {'offer': offer_id}, title, meta.get('season'), meta.get('episode'),
                          meta.get('poster') or _dict(show.get('show')).get('poster'), src.get('duration'))
            ep['channel'] = channel[:60]                            # 0.6.109: für die Prüfung je Folge sichtbar
            ep['weg'] = path                                        # 0.6.112: Zulassungsweg (episode_paths)
            out.append(ep)
    else:
        import portal_title
        model = portal_title.model(root, source, series_id)
        for e in model.get('episodes') or []:
            if not e.get('playable') or not e.get('id'):
                continue
            if source != 'toggo' and word_blocked(e.get('title')):   # 0.6.109: Pluto „Let's Talk About Sex“
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
# 0.6.106: „Kinder“/„Kids“ im Namen hebt die Namenssperre nicht mehr auf (Kinderarmut, Kinderärzte, Kindernachrichten
# kommen nur über ein KiKA-Angebot, das show_is_kids vorher prüft)
KIDS_NAME = re.compile(r'(?i)\bkika\b|logo!|\btivi\b|sendung mit der maus|sandmännchen|checker|toggo')


# 0.6.106 (Mac-Prüfung 0.6.105): Sicherheitsnetz über Titel, Reihen- und Folgentitel. Nur Angebote von Kindersendern
# (KiKA, TOGGO, ZDFtivi) sind ausgenommen, damit „Der Krieg und ich“ von KiKA bleibt.
BAD_WORDS = re.compile(
    r'(?i)porno|\bsex|missbrauch|\bdoping|\btäter|\bkrebs|\bkrieg|\bmord|\bkrimi|verhütung|vergewaltig|\bgewalt|'
    r'\bdrogen|\bsuizid|selbstmord|\bterror|\bnackt|\berotik|\bleiche|\bsterbe|\btöte|\bwaffe|\bamok|prostitu|\bfolter|'
    r'\bhorror|\bzombie|\bmonster|\bkiller|\bblut|lügde|\bgeheimsache|\bcrime|\bprostitution|\bentführ|\bkidnapp')


def word_blocked(title):
    return bool(BAD_WORDS.search(str(title or '')))


def _kids_channels():
    import kids_rules
    return set(kids_rules.ALWAYS_CHANNELS)


def _from_kids_channel(c, tile):
    """Ausnahme von der Wortsperre: Kindersender (Mediatheken: Angebot bzw. Reihe; TOGGO immer) oder Elternfreigabe."""
    if tile.get('source') == 'toggo':
        return True
    if tile.get('source') != 'mediatheken' or c is None:
        return False
    chans = sorted(_kids_channels())
    cond = "lower(trim(json_extract(o.payload,'$.channel'))) IN (%s)" % ','.join('?' * len(chans))
    ref, series = _dict(tile.get('ref')), _dict(tile.get('series'))
    # Elternfreigabe geht vor
    if ref.get('offer') and c.execute("SELECT 1 FROM offers o JOIN kids_choices k ON k.key='work:'||o.work_id AND k.choice='allow' "
                                      "WHERE o.id=?", (ref['offer'],)).fetchone():
        return True
    if series.get('show') and c.execute("SELECT 1 FROM kids_choices WHERE key=? AND choice='allow'", ('show:' + series['show'],)).fetchone():
        return True
    if ref.get('offer'):
        return bool(c.execute('SELECT 1 FROM offers o WHERE o.id=? AND ' + cond, [ref['offer']] + chans).fetchone())
    if series.get('show'):
        return bool(c.execute('SELECT 1 FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 WHERE w.show_key=? AND '
                              + cond + ' LIMIT 1', [series['show']] + chans).fetchone())
    return False


def block_target(tile):
    """0.6.113: was „Sperren“ in der Elternansicht für eine sichtbare Kachel sperrt – Mediatheken-Film: das Werk,
    Mediatheken-Reihe: die ganze Reihe (wirkt auch auf Abspielen und Nachladen), Plattform: die Kachel."""
    if tile.get('source') == 'mediatheken':
        if (tile.get('series') or {}).get('show'):
            return {'kind': 'show', 'id': tile['series']['show']}
        if tile.get('work'):
            return {'kind': 'work', 'id': tile['work']}
    return {'kind': 'tile', 'id': tile.get('id')}


def _parent_blocks(db, tiles):
    """0.6.113: von den Eltern gesperrte Plattform-Kacheln heraus; jede Kachel trägt ihr Sperrziel (``block``)."""
    for t in tiles:
        t['block'] = block_target(t)
    if db is None:
        return tiles
    import kids_rules
    with db() as c:
        blocked = kids_rules.blocked_tiles(c)
    return [t for t in tiles if t.get('id') not in blocked] if blocked else tiles


def _prefer_kids_offers(db, tiles):
    """0.6.113: Mediatheken-Filme mit KiKA-Zwilling zeigen und spielen das Kindersender-Angebot; jede Kachel nennt den
    Sender ihres Angebots (Prüfung). Ohne Datenbank unverändert."""
    films = [t for t in tiles if t.get('source') == 'mediatheken' and _dict(t.get('ref')).get('offer')]
    if not films or db is None:
        return tiles
    with db() as c:
        for t in films:
            row = c.execute("SELECT work_id, json_extract(payload,'$.channel') FROM offers WHERE id=?", (t['ref']['offer'],)).fetchone()
            if not row:
                continue
            t['work'] = row[0]                                       # 0.6.113: Sperrziel der Elternansicht
            t['channel'] = str(row[1] or '')[:60]
            try:
                import kids_rules
                t['weg'] = kids_rules.explain(c, row[0])           # 0.6.113: Zulassungsweg des Films (Prüfung)
            except Exception:
                t['weg'] = None
            if t['channel'].strip().lower() in _kids_channels():
                continue
            twin = kids_offer(c, row[0])
            if twin:
                t['ref'] = {'offer': twin[0]}
                t['key'] = watch_key(t['ref'])
                t['channel'] = twin[1][:60]
    return tiles


def _word_safe(db, tiles):
    """Titel mit heiklen Wörtern (BAD_WORDS) heraus, außer vom Kindersender."""
    hits = [t for t in tiles if word_blocked(t.get('title'))]
    if not hits:
        return tiles
    if db is None:
        drop = {t['id'] for t in hits if t.get('source') != 'toggo'}
    else:
        with db() as c:
            drop = {t['id'] for t in hits if not _from_kids_channel(c, t)}
    return [t for t in tiles if t['id'] not in drop]


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
    import kids_rules
    live, live_args = kids_rules.live_clause()
    # 0.6.109: Livestreams zählen nie als Kinderprogramm (auch nicht „KiKA Livestream“) und fallen immer heraus
    chans = list(kids_rules.ALWAYS_CHANNELS)
    sender = ("(NOT %s AND EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 "
              "AND lower(trim(json_extract(k.payload,'$.channel'))) IN (%s)))" % (live, ','.join('?' * len(chans))))
    sql = ("SELECT w.id, (NOT %s AND ((%s) OR ((%s) AND NOT %s))) AS kids, (%s OR %s) AS bad, "
           "(SELECT group_concat(g.genre, char(31)) FROM work_genres g WHERE g.work_id=w.id) AS genres, %s AS sender, "
           "%s AS live FROM works w WHERE w.show_key=? ORDER BY w.rowid DESC LIMIT ?"
           % (live, kids, sig, bad_sql, live, bad_sql, sender, live))
    return sql, (list(live_args) + list(kids_args) + list(sig_args) + bad + list(live_args) + bad
                 + list(live_args) + chans + list(live_args)), {}


def _work_rows(c, show_key, limit=None, query=None):
    """[(work_id, kids, against)] je Werk der Reihe (neueste zuerst)."""
    return [r[:3] for r in _work_facts(c, show_key, limit, query)]


def _work_facts(c, show_key, limit=None, query=None):
    """[(work_id, kids, against, sender, live)] je Werk der Reihe (neueste zuerst); sender = eigenes Angebot vom
    Kindersender (nicht Livestream)."""
    import categories
    sql, args, names_of = query or _work_query(c)
    friendly = set(KIDS_FRIENDLY)
    out = []
    for wid, is_kids, is_bad, genres, sender, live in c.execute(sql, args + [show_key, int(limit or -1)]):
        names = set()
        for raw in (genres or '').split('\x1f'):
            if raw:
                if raw not in names_of:
                    names_of[raw] = set(categories.of_label(raw))
                names |= names_of[raw]
        # „kids“ folgt der Kinder-Regel (catalog.category_clause): 0.6.99 lässt KiKA/TOGGO und Elternfreigaben
        # auch neben einem Ausschluss-Genre zu, sonst schließt die Regel es selbst aus
        against = not is_kids and (bool(is_bad) or bool(names - friendly))
        out.append((wid, bool(is_kids), against, bool(sender), bool(live)))
    return out


def show_basis(c, show_key, title='', query=None):
    """Warum eine Mediatheken-Reihe in der Kinderecke steht – oder None.

    0.6.109 (Mac-Prüfung 0.6.106: „Livestream“, „WUMMS“, „Sportschau“, „POV · Deine Geschichte zählt“, „Young Crime“,
    „#Ukraine · Mein Land im Krieg“ standen mit ALLEN Folgen drin, weil einzelne Angebote von KiKA kamen). Der
    Kindersender gilt je Folge, nicht je Reihe:
    * 'freigabe': von den Eltern freigegeben – alle Folgen außer Ausschluss-Genres und Sperren.
    * 'reihe': bekannte Kinderreihe (categories.KNOWN_KIDS_SERIES im Reihennamen oder im Thema eines Angebots) –
      Folgen wie bisher (Ausschluss-Genres und fremde Kategorien heraus).
    * Nachrichten-/Sportnamen (NOT_KIDS_SHOW) sonst nie.
    * 'anteil': mindestens SHOW_SHARE der eingeordneten letzten Werke sind Kinderprogramm (0.6.98) – Folgen wie 'reihe'.
    * 'gemischt': sonst nur, wenn Folgen ein eigenes Angebot vom Kindersender haben, und dann NUR die selbst
      zugelassenen Folgen (Young Crime: 24 KiKA, 34 ZDF)."""
    import catalog
    import kids_rules
    if kids_rules.show_allowed(c, show_key):
        return 'freigabe'
    title = title or _show_title(c, show_key)
    if catalog.KIDS_TOPIC.search(str(title or '')) or _curated_topic(c, show_key):
        return 'reihe'
    if show_name_blocked(title):
        return None
    if youth_show(title):
        # 0.6.112: Jugend-/Reportageformate (Young Crime, POV, ECHT) nur mit Folgen vom Kindersender, und dann nur diese
        return 'jugend' if _kids_channel_works(c, show_key, mixed=False) else None
    rows = _work_rows(c, show_key, SHOW_SAMPLE, query)
    kids = sum(1 for _, k, _ in rows if k)
    against = sum(1 for _, k, a in rows if a and not k)
    if not kids:
        return None
    if _kids_channel_works(c, show_key):
        # Kindersender und andere Sender in einer Reihe (WUMMS: 2 KiKA, 174 ARD/funk ohne Genre): nur die eigenen
        # Kinder-Folgen, auch wenn der Anteil unter den eingeordneten hoch aussieht
        return 'gemischt'
    if kids >= SHOW_SHARE * (kids + against):
        return 'anteil'               # 0.6.98: die Reihe ist selbst Kinderprogramm (≥ 80 % der eingeordneten)
    return None


def _kids_channel_works(c, show_key, mixed=True):
    """Hat die Reihe Folgen vom Kindersender UND (mixed) Folgen ohne Kindersender-Angebot (gemischte Reihe)?"""
    import kids_rules
    live, live_args = kids_rules.live_clause()
    chans = list(kids_rules.ALWAYS_CHANNELS)
    on_kids = ("EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 "
               "AND lower(trim(json_extract(k.payload,'$.channel'))) IN (%s))" % ','.join('?' * len(chans)))
    has = lambda neg: c.execute("SELECT 1 FROM works w WHERE w.show_key=? AND %s%s AND NOT %s LIMIT 1" % (neg, on_kids, live),
                                [show_key] + chans + live_args).fetchone()
    return bool(has('') and (has('NOT ') or not mixed))


def _curated_topic(c, show_key):
    import catalog
    topics = catalog.kids_topics(c)
    if not topics:
        return False
    return bool(c.execute("SELECT 1 FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 WHERE w.show_key=? "
                          "AND json_extract(o.payload,'$.topic') IN (%s) LIMIT 1" % ','.join('?' * len(topics)),
                          [show_key] + list(topics)).fetchone())


def show_is_kids(c, show_key, title='', query=None):
    """Gehört die ARD/ZDF-Reihe in die Kinderecke? (show_basis; Elternfreigabe/-sperre gehen vor)"""
    return show_basis(c, show_key, title, query) is not None


def _kids_shows(db, tiles):
    """Nur Reihen der Mediatheken behalten, die selbst Kinderprogramm sind (eine Verbindung für alle)."""
    shows = [t for t in tiles if t.get('source') == 'mediatheken' and (t.get('series') or {}).get('show')]
    if not shows or db is None:
        return tiles
    with db() as c:
        query = _work_query(c)
        drop = set()
        for t in shows:
            basis = show_basis(c, t['series']['show'], t.get('title'), query)
            # 0.6.112 (Mac-Prüfung 0.6.109: „#Ukraine · Mein Land im Krieg“ mit 0 Folgen): ohne eine zulässige,
            # abspielbare Folge keine Kachel
            if basis is None or not _has_episode(c, t['series']['show'], basis):
                drop.add(t['id'])
            else:
                t['basis'] = basis
    return [t for t in tiles if t['id'] not in drop]


# 0.6.112 (Mac-Prüfung 0.6.109: Young Crime zeigte 5 ZDF-Folgen, POV eine WDR-Folge „Rechtsextremismus unter
# Jugendlichen“): Jugend- und Reportageformate sind kein Kinderprogramm. Nur Folgen vom Kindersender oder mit
# Elternfreigabe; der Rest steht auf der Warteliste.
YOUTH_SHOW = re.compile(r'(?i)young crime|\bpov\b|deine geschichte zählt|\becht\b|\bjugend\w*|\bteens?\b|\bdrunter & drüber\b')


def youth_show(title):
    return bool(YOUTH_SHOW.search(str(title or '')))


_PATHS = {}   # 0.6.113: (Verbindung, Datenstand, Reihe) -> Wege; Nachladen fragt work_allowed je Folge (132 × ≈ 45 ms)


def _data_key(c):
    """Ändert sich mit jedem Schreiben (eigene Verbindung: total_changes, andere: PRAGMA data_version)."""
    try:
        path = c.execute('PRAGMA database_list').fetchone()[2] or ''
        if not path:
            return None            # :memory: – nie zwischenspeichern
        return (path, id(c), c.execute('PRAGMA data_version').fetchone()[0], c.total_changes, _GEN[0])
    except Exception:
        return None


def episode_paths(c, show_key, basis=None):
    """Weg je Folge (siehe _episode_paths); gleicher Datenstand derselben Verbindung wird nicht neu berechnet."""
    key = _data_key(c)
    if key is not None and basis is None:
        hit = _PATHS.get((key, show_key))
        if hit is not None:
            return hit
    value = _episode_paths(c, show_key, basis)
    if key is not None and basis is None:
        if len(_PATHS) > 256:
            _PATHS.clear()
        _PATHS[(key, show_key)] = value
    return value


def _episode_paths(c, show_key, basis=None):
    """{work_id: Weg oder None} je Folge einer Mediatheken-Reihe – EINE Entscheidung für Folgenliste, kids-play,
    Nachladen und Prüfung. Wege: 'freigabe' (Eltern), 'sender' (eigenes Angebot vom Kindersender), 'reihe' (bekannte
    Kinderreihe bzw. freigegebene Reihe), 'regel' (Kinder-Regel je Werk: Referenz-Genre, Familie + FSK, Kinderreihe im
    Thema), 'anteil' (Reihe zu ≥ 80 % Kinderprogramm, Folge selbst noch nicht eingeordnet). None = nicht zulässig.

    * Livestreams und gesperrte Folgen/Reihen: nie.
    * 'jugend' (Young Crime, POV, ECHT): nur 'sender'/'freigabe'.
    * 'gemischt' (Kindersender + andere Sender): 'sender', 'regel', 'freigabe'.
    * 'anteil': dazu nicht eingeordnete Folgen ohne fremde Kategorie ('anteil').
    * 'reihe'/'freigabe': jede Folge ohne Ausschluss-Genre/fremde Kategorie."""
    import kids_rules
    query = _work_query(c)
    facts = _work_facts(c, show_key, None, query)
    blocked = kids_rules.blocked_works(c, show_key)
    if basis is None and blocked is not None:
        basis = show_basis(c, show_key, _show_title(c, show_key), query)
    if blocked is None or basis is None:
        return {f[0]: None for f in facts}
    allowed = {r[0] for r in c.execute("SELECT substr(k.key,6) FROM kids_choices k JOIN works w ON w.id=substr(k.key,6) "
                                       "WHERE k.choice='allow' AND k.key LIKE 'work:%' AND w.show_key=?", (show_key,))}
    out = {}
    for wid, kids, against, sender, live in facts:
        if live or wid in blocked:
            path = None
        elif wid in allowed:
            path = 'freigabe'
        elif sender:
            path = 'sender'
        elif basis == 'jugend':
            path = None
        elif kids:
            path = 'regel'
        elif basis in ('reihe', 'freigabe') and not against:
            path = basis
        elif basis == 'anteil' and not against:
            path = 'anteil'
        else:
            path = None
        out[wid] = path
    return out


def _has_episode(c, show_key, basis):
    """Mindestens eine zulässige Folge mit aktivem Angebot, deren Titel nicht gesperrt ist (außer Kindersender/Freigabe)."""
    paths = episode_paths(c, show_key, basis)
    # Folgen vom Kindersender oder mit Freigabe: Sperrwörter gelten dort nicht (wie episodes/work_allowed)
    if any(p in ('freigabe', 'sender') and _active(c, wid) for wid, p in paths.items()):
        return True
    ok = [wid for wid, path in paths.items() if path]
    chans = _kids_channels()
    for i in range(0, len(ok), 500):
        part = ok[i:i + 500]
        for wid, title, otitle, ch in c.execute(
                "SELECT w.id, w.title, json_extract(o.payload,'$.title'), lower(trim(json_extract(o.payload,'$.channel'))) "
                "FROM works w JOIN offers o ON o.work_id=w.id AND o.active=1 WHERE w.id IN (%s)" % ','.join('?' * len(part)), part):
            if ch in chans or not word_blocked(otitle):
                return True
    return False


def _active(c, wid):
    return bool(c.execute('SELECT 1 FROM offers WHERE work_id=? AND active=1 LIMIT 1', (wid,)).fetchone())


def excluded_works(c, show_key):
    """Folgen einer Reihe, die nicht in die Kinderecke gehören (episode_paths ohne Weg)."""
    return {wid for wid, path in episode_paths(c, show_key).items() if path is None}


def _live_works(c, show_key):
    import kids_rules
    live, args = kids_rules.live_clause()
    return {r[0] for r in c.execute('SELECT w.id FROM works w WHERE w.show_key=? AND ' + live, [show_key] + args)}


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
