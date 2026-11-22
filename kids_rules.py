"""0.6.99 Wer kommt in die Kinderecke? Altersfreigabe, Altersgrenze und Freigabe durch die Eltern.

Björn, 22.11.2026:
* „einige Kinderfilme sind dem Bereich Fantasy zugeordnet, z. B. Bibi & Tina … gehören natürlich auch in die
  Kinderecke … aber erst, wenn sie mit der Validierung der IMDb auch für Kinder freigegeben sind; die
  Altersempfehlung würde ich gerne variabel anpassen und an den normalen Stand knüpfen“
* „das soll für alle Kategorien gelten“
* „wenn ein Film oder eine Serie nicht identifiziert wird und nichts für Kinder ist, soll er im Zweifelsfall dort
  nicht auftauchen, und ich gebe ihn dann manuell frei“

Regel (Kategorie „Kinder“, gilt in Kinderecke und Werkkatalog gleich):
* Automatisch nur erkannte Werke (state matched/manual/identified), und zwar entweder
  a) mit belegter Altersfreigabe bis zur eingestellten Grenze und der Kategorie Familie (categories.KIDS_AGE_HINTS;
     Bibi & Tina, Märchen = Family/Fantasy), nie neben categories.AGE_PATH_EXCLUDED (Romantik, Science-Fiction,
     Action, Mystery). Fantasy/Abenteuer allein (Netzkino „Alien Predator War“, FSK 12) und ein FSK-12-Drama (Arrival)
     warten auf Freigabe („im Zweifel nicht“, 0.6.105), oder
  b) mit eindeutigem Kinder-Signal (Genre „Kinder“, Familie + Animation, KiKA, Kinder-/Märchenreihe), solange
     keine höhere Freigabe bekannt ist.
* Sicherheitsnetz: nie neben Horror, Thriller, Krimi, Erotik, Krieg; Weg a) zusätzlich nie neben Romantik
  (FSK-0-Liebesfilme sind kein Kinderprogramm).
* Alles vom Kindersender KiKA oder von TOGGO (auch ZDFtivi) kommt immer hinein, auch ohne Erkennung.
* Eine belegte Freigabe über der Grenze schließt immer aus.
* Eltern-Freigabe („allow“) nimmt ein Werk oder eine ganze Serie auf, auch ohne Erkennung; „block“ nimmt es heraus.

Altersfreigaben: Das IMDb-Archiv enthält keine. Für erkannte Werke mit IMDb-Kennung holt ``fetch_round`` die
FSK aus Wikidata (Eigenschaft P1981 „FSK-Altersfreigabe“, gebündelt je 150 Kennungen, höchstens eine Abfrage
alle paar Sekunden, Pause nach Fehlern). Plattformen mit eigener FSK (Netzkino, filmfriend, Pluto …) nutzen diese
über ``categories.KIDS_MAX_AGE``.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request

AGES = (0, 6, 12)
DEFAULT_MAX_AGE = 12      # Björn 22.11.2026 23:08: „mein Standard wäre auch 12 und nicht 6“
# Björn 22.11.2026 23:08: „alles, was definitiv von KiKA oder TOGGO kommt, sollte freigegeben werden“ – auch ohne
# Erkennung und ohne Genre-Sicherheitsnetz (TOGGO-Plattform: toggo._summary, immer „Kinder“).
ALWAYS_CHANNELS = ('kika', 'kika.de', 'toggo', 'zdf-tivi', 'zdftivi')
STATE_KEY = 'kids_max_age_v0696'
IDENTIFIED = "w.state IN ('matched','manual','identified')"
# 0.6.106 (Mac-Abfrage Kinderreihen 22.11.): „Checker Can, Checker Tobi und Checker Julian“ (38 Werke) und „Paula, Anna
# und die wilden Tiere“ (25) sind als Beiträge ihrer Sendung abgelegt (state 'format'). Solche Ablagen zählen nur über das
# Angebot (Kindersender oder catalog.FORMAT_KIDS_TOPIC), nie über das aus dem Sendungsnamen abgeleitete Genre
# (Durchsicht Kinderecke: „Kinderärzte im Einsatz“, „Kinderarmut in Deutschland“, „Ein Herz für Kinder“).
FORMAT = "w.state='format'"
# 0.6.105: die IMDb-Kennung steht bei TMDB-/TVDB-Treffern in meta.imdb_id, reference_id ist dann die TMDB-ID
# (Mac-Prüfung 0.6.103: reference_ages blieb leer)
REF = "COALESCE(NULLIF(json_extract(w.meta,'$.imdb_id'),''),json_extract(w.meta,'$.reference_id'))"

HINT_GENRES = ('Kinder', 'Familie', 'Animation', 'Fantasy', 'Abenteuer')   # Kandidaten für „Wartet auf Freigabe“

SCHEMA = """
CREATE TABLE IF NOT EXISTS kids_choices(key TEXT PRIMARY KEY, choice TEXT NOT NULL, title TEXT, kind TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS reference_ages(ref TEXT PRIMARY KEY, age INTEGER, label TEXT, source TEXT, checked REAL);
"""

SPARQL = 'https://query.wikidata.org/sparql'
BATCH = 150
ROUND_REFS = 1500
RECHECK_DAYS = 60
PAUSE_SECONDS = 3600
_PAUSE = [0.0]
STATUS = {'checked': 0, 'with_age': 0, 'last_round': None, 'last_error': '', 'paused_until': 0}
_LOCK = threading.Lock()


def ensure(c):
    c.executescript(SCHEMA)


def max_age(c):
    import catalog
    try:
        value = catalog.get_state(c, STATE_KEY, DEFAULT_MAX_AGE)
    except Exception:
        return DEFAULT_MAX_AGE
    return value if value in AGES else DEFAULT_MAX_AGE


LIVE_KEY = 'kids_live_v0696'


def live_enabled(c):
    """0.6.99: Kinder-Live-Sender in der Kinderecke zeigen (Elternbereich, Standard an)."""
    import catalog
    try:
        return catalog.get_state(c, LIVE_KEY, True) is not False
    except Exception:
        return True


def set_live(c, value):
    import catalog
    catalog.set_state(c, LIVE_KEY, bool(value))
    return bool(value)


def apply_limit(c):
    """Grenze auch für die Plattformen (categories.classify) übernehmen."""
    import categories
    categories.KIDS_MAX_AGE = max_age(c)
    return categories.KIDS_MAX_AGE


def set_max_age(c, value):
    import catalog
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError('Altersgrenze 0, 6 oder 12')
    if value not in AGES:
        raise ValueError('Altersgrenze 0, 6 oder 12')
    catalog.set_state(c, STATE_KEY, value)
    apply_limit(c)
    return value


def _key(kind, value):
    value = str(value or '')
    if kind not in ('work', 'show') or not value or len(value) > 200:
        raise ValueError('Unbekannter Eintrag')
    return '%s:%s' % (kind, value)


def choose(c, kind, value, choice, title=''):
    """Eltern-Freigabe: choice 'allow', 'block' oder '' (zurücknehmen)."""
    ensure(c)
    key = _key(kind, value)
    if choice in ('', None, 'none'):
        c.execute('DELETE FROM kids_choices WHERE key=?', (key,))
        return {'key': key, 'choice': ''}
    if choice not in ('allow', 'block'):
        raise ValueError('Freigeben oder sperren')
    c.execute('INSERT OR REPLACE INTO kids_choices VALUES(?,?,?,?,?)', (key, choice, str(title or '')[:200], kind, time.time()))
    return {'key': key, 'choice': choice}


def choices(c):
    ensure(c)
    return [{'key': k, 'kind': kind, 'id': k.split(':', 1)[1], 'choice': ch, 'title': t or '', 'updated': u}
            for k, ch, t, kind, u in c.execute('SELECT key,choice,title,kind,updated FROM kids_choices ORDER BY title COLLATE NOCASE')]


def _chosen(choice):
    return ("(w.id IN (SELECT substr(key,6) FROM kids_choices WHERE choice='%s' AND key LIKE 'work:%%') OR "
            "w.show_key IN (SELECT substr(key,6) FROM kids_choices WHERE choice='%s' AND key LIKE 'show:%%'))" % (choice, choice))


def kids_clause(c, signal, signal_args, has):
    """SQL (auf works w) für die Kategorie „Kinder“ nach der Regel oben. ``signal``: das eindeutige Kinder-Signal
    aus catalog.category_clause, ``has(names)``: dessen Helfer für Genre-Bedingungen."""
    import categories
    ensure(c)
    limit = max_age(c)
    bad, bad_args = has(categories.NOT_FOR_KIDS)
    soft, soft_args = has(categories.AGE_PATH_EXCLUDED)
    hint, hint_args = has(categories.KIDS_AGE_HINTS)
    age_ok = 'EXISTS(SELECT 1 FROM reference_ages a WHERE a.ref=%s AND a.age IS NOT NULL AND a.age<=?)' % REF
    age_high = 'EXISTS(SELECT 1 FROM reference_ages a WHERE a.ref=%s AND a.age>?)' % REF
    channel = ("EXISTS(SELECT 1 FROM offers k WHERE k.work_id=w.id AND k.active=1 AND lower(json_extract(k.payload,'$.channel')) IN (%s))"
               % ','.join('?' * len(ALWAYS_CHANNELS)))
    import catalog
    fmt_sig, fmt_args = catalog.format_kids_signal_clause(c)
    sql = ('NOT %s AND (%s OR (%s AND NOT %s) OR (%s AND NOT %s AND NOT %s AND (%s OR (%s AND %s AND NOT %s))) '
           'OR (%s AND NOT %s AND NOT %s AND %s))'
           % (_chosen('block'), _chosen('allow'), channel, age_high, IDENTIFIED, bad, age_high, signal, age_ok, hint, soft,
              FORMAT, bad, age_high, fmt_sig))
    return sql, (list(ALWAYS_CHANNELS) + [limit] + list(bad_args) + [limit] + list(signal_args) + [limit]
                 + list(hint_args) + list(soft_args) + list(bad_args) + [limit] + list(fmt_args))


def blocked_works(c, show_key):
    ensure(c)
    if c.execute("SELECT 1 FROM kids_choices WHERE key=? AND choice='block'", ('show:' + show_key,)).fetchone():
        return None          # ganze Serie gesperrt
    return {r[0] for r in c.execute("""SELECT w.id FROM works w JOIN kids_choices k ON k.key='work:'||w.id
        WHERE w.show_key=? AND k.choice='block'""", (show_key,))}


def show_allowed(c, show_key):
    ensure(c)
    return bool(c.execute("SELECT 1 FROM kids_choices WHERE key=? AND choice='allow'", ('show:' + show_key,)).fetchone())


# ------------------------------------------------------------------ „Wartet auf Freigabe“
def waiting(c, limit=300):
    """Titel mit Kinder-Hinweis, die die Regel (noch) nicht erfüllen: nicht erkannt, keine Freigabe bekannt oder
    über der Grenze. Je Serie ein Eintrag. Nur lesen."""
    import catalog
    import categories
    ensure(c)
    labels = catalog.category_labels(c)
    hint = [r for name in HINT_GENRES for r in labels.get(name) or []]
    bad = [r for name in categories.NOT_FOR_KIDS for r in labels.get(name) or []]
    signal, signal_args = catalog.kids_signal_clause(c)
    kids, kids_args = catalog.category_clause(c, 'Kinder')
    hint_sql = ('EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))' % ','.join('?' * len(hint))) if hint else '0'
    bad_sql = ('EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s))' % ','.join('?' * len(bad))) if bad else '0'
    unit = "CASE WHEN w.kind='series' THEN 'show:'||w.show_key ELSE 'work:'||w.id END"
    sql = ("""SELECT %s unit,w.kind,MIN(w.title) title,MIN(w.year) year,MAX(%s) identified,
              MAX((SELECT a.age FROM reference_ages a WHERE a.ref=%s)) age,
              MAX(CASE WHEN (SELECT 1 FROM reference_ages a WHERE a.ref=%s) THEN 1 ELSE 0 END) age_checked,
              COUNT(*) n, MIN(w.show_key) show_key, MIN(w.id) work_id
           FROM works w WHERE w.kind IN ('movie','series')
             AND EXISTS(SELECT 1 FROM offers o WHERE o.work_id=w.id AND o.active=1)
             AND (%s OR %s) AND NOT %s
             AND NOT EXISTS(SELECT 1 FROM kids_choices k WHERE k.key=%s)
           GROUP BY unit HAVING SUM(CASE WHEN %s THEN 1 ELSE 0 END)=0
           ORDER BY title COLLATE NOCASE LIMIT ?""" % (unit, IDENTIFIED, REF, REF, signal, hint_sql, bad_sql, unit, kids))
    args = list(signal_args) + hint + bad + list(kids_args) + [int(limit)]
    out = []
    lim = max_age(c)
    for r in c.execute(sql, args):
        if not r['identified']:
            reason = 'Nicht erkannt'
        elif r['age'] is not None and r['age'] > lim:
            reason = 'FSK %d (über der Grenze)' % r['age']
        elif r['age'] is not None:
            reason = 'FSK %d, aber kein Familien- oder Kinderhinweis' % r['age']   # 0.6.105: Fantasy/Abenteuer allein
        elif r['age_checked']:
            reason = 'Keine Altersfreigabe bekannt'
        else:
            reason = 'Altersfreigabe wird noch gesucht'
        kind, _, ident = r['unit'].partition(':')
        out.append({'kind': kind, 'id': ident, 'title': r['title'] or 'Ohne Titel', 'year': r['year'],
                    'type': 'Serie' if r['kind'] == 'series' else 'Film', 'reason': reason,
                    'age': r['age'], 'works': r['n']})
    return out


# ------------------------------------------------------------------ Altersfreigaben aus Wikidata
def _candidates(c, now, limit):
    """IMDb-Kennungen erkannter Werke ohne (frische) Prüfung; Werke mit Kinder-Hinweis zuerst."""
    import catalog
    ensure(c)
    labels = catalog.category_labels(c)
    hint = [r for name in HINT_GENRES for r in labels.get(name) or []]
    fresh = now - RECHECK_DAYS * 86400
    base = ("SELECT DISTINCT %s ref FROM works w WHERE %s AND w.kind IN ('movie','series') AND %s LIKE 'tt%%' "
            "AND NOT EXISTS(SELECT 1 FROM reference_ages a WHERE a.ref=%s AND a.checked>?)" % (REF, IDENTIFIED, REF, REF))
    out = []
    if hint:
        q = base + ' AND EXISTS(SELECT 1 FROM work_genres g WHERE g.work_id=w.id AND g.genre IN (%s)) LIMIT ?' % ','.join('?' * len(hint))
        out = [r[0] for r in c.execute(q, [fresh] + hint + [limit])]
    if len(out) < limit:
        seen = set(out)
        out += [r[0] for r in c.execute(base + ' LIMIT ?', (fresh, limit * 2)) if r[0] not in seen][:limit - len(out)]
    return [r for r in out if isinstance(r, str) and re.fullmatch(r'tt\d{5,10}', r)]


def _query(refs, version='', timeout=40):
    values = ' '.join('"%s"' % r for r in refs)
    query = ('SELECT ?imdb ?label WHERE { VALUES ?imdb { %s } ?item wdt:P345 ?imdb ; wdt:P1981 ?fsk . '
             '?fsk rdfs:label ?label . FILTER(LANG(?label) = "de") }' % values)
    url = SPARQL + '?' + urllib.parse.urlencode({'query': query, 'format': 'json'})
    req = urllib.request.Request(url, headers={'Accept': 'application/sparql-results+json',
                                               'User-Agent': 'MediathekAtlas/%s (lokale Mediathek-App)' % version})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(4_000_000).decode('utf-8'))
    found = {}
    import categories
    for b in (data.get('results') or {}).get('bindings') or []:
        ref = (b.get('imdb') or {}).get('value')
        label = (b.get('label') or {}).get('value') or ''
        age = categories.age_of(label)
        if ref and age is not None:
            found[ref] = max(found.get(ref, -1), age)      # mehrere Angaben: die strengste gilt
            found.setdefault(ref + '#label', label)
    return found


def store(c, refs, found, source='Wikidata FSK', now=None):
    ensure(c)
    now = time.time() if now is None else now
    for ref in refs:
        age = found.get(ref)
        c.execute('INSERT OR REPLACE INTO reference_ages VALUES(?,?,?,?,?)',
                  (ref, age, found.get(ref + '#label', '') if age is not None else '', source, now))


def fetch_round(db, version='', query=None, stop=None, gap=3.0):
    """Eine Runde: bis ROUND_REFS Kennungen in Bündeln abfragen. Rückgabe: Anzahl geprüft."""
    query = query or _query
    now = time.time()
    if _PAUSE[0] > now:
        return 0
    with db() as c:
        refs = _candidates(c, now, ROUND_REFS)
    done = 0
    for i in range(0, len(refs), BATCH):
        if stop is not None and stop.is_set():
            break
        part = refs[i:i + BATCH]
        try:
            found = query(part, version)
        except Exception as exc:
            _PAUSE[0] = time.time() + PAUSE_SECONDS
            with _LOCK:
                STATUS.update(last_error=str(exc)[:160] or exc.__class__.__name__, paused_until=_PAUSE[0])
            break
        with db() as c:
            store(c, part, found)
        done += len(part)
        with _LOCK:
            STATUS['last_error'] = ''
        if gap and i + BATCH < len(refs):
            time.sleep(gap)
    with _LOCK:
        STATUS['last_round'] = time.time()
    return done


def summary(c):
    ensure(c)
    checked, with_age = c.execute('SELECT COUNT(*),COUNT(age) FROM reference_ages').fetchone()
    by_age = {str(a): n for a, n in c.execute('SELECT age,COUNT(*) FROM reference_ages WHERE age IS NOT NULL GROUP BY age')}
    with _LOCK:
        state = dict(STATUS)
    return {'max_age': max_age(c), 'live': live_enabled(c), 'ages': list(AGES), 'checked': checked, 'with_age': with_age, 'by_age': by_age,
            'last_round': state['last_round'], 'last_error': state['last_error'],
            'paused_until': state['paused_until'] if state['paused_until'] > time.time() else 0}


def loop(db, stop, version='', event=None, error=None, interval=1200):
    """Hintergrund: alle 20 Minuten eine Runde (nach dem Start 3 Minuten warten)."""
    if stop.wait(180):
        return
    while not stop.is_set():
        try:
            n = fetch_round(db, version, stop=stop)
            if n and event:
                with db() as c:
                    s = summary(c)
                event('kids_ages_round', checked=n, total=s['checked'], with_age=s['with_age'])
        except Exception as exc:
            if error:
                error('kids_ages_failed', exc)
        if stop.wait(interval):
            return
