"""0.6.170: benannte Kinderprofile der Kinderecke (Abo-Profile, Punkt 1–2 des Umfangs vom 28.11.2026).

* Ein Profil je Kind: Name, Farbe und die YouTube-Abos, die dieses Kind NICHT sieht (``hidden``). Ein neues Abo ist
  für alle Kinder sichtbar; ein Kanal wird nur einmal geladen, egal wie viele Kinder ihn sehen.
* Eigener Gesehen-/Weiterschauen-Stand je Profil in watch_state, über ein Schlüssel-Präfix: Profil 1 behält die
  bisherigen Schlüssel (``job:…``) – der bisherige Stand gehört verlustfrei dem ersten Kind –, jedes weitere Profil
  bekommt ``kp<id>:``. Kennungen werden nie wiederverwendet (AUTOINCREMENT), ein gelöschtes Profil vererbt nichts.
* Ohne Profil verhält sich die Kinderecke wie bisher. Mit zwei und mehr Profilen fragt sie beim Öffnen, wer schaut.

Nur Speicher und Regeln; die Seiten sind web/kids.js (Auswahl) und web/kids_parents.js (Elternbereich)."""
import json
import re
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS kids_profiles(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 color TEXT NOT NULL DEFAULT '',
 hidden TEXT NOT NULL DEFAULT '[]',
 created REAL NOT NULL DEFAULT 0);
"""
MAX_PROFILES = 8
NAME_MAX = 30
COLORS = ('#ff5d8f', '#ff9a3f', '#ffd23f', '#45d483', '#3fc4ff', '#6c5ce7', '#c56cf0', '#fd7272')
PREFIX = re.compile(r'^kp(\d+):')


def ensure(c):
    c.executescript(SCHEMA)


def _row(r):
    try:
        hidden = sorted({int(x) for x in json.loads(r[3] or '[]')})
    except (TypeError, ValueError):
        hidden = []
    return {'id': int(r[0]), 'name': r[1], 'color': r[2] or COLORS[(int(r[0]) - 1) % len(COLORS)], 'hidden': hidden}


def profiles(c):
    ensure(c)
    return [_row(r) for r in c.execute('SELECT id,name,color,hidden FROM kids_profiles ORDER BY id')]


def get(c, profile_id):
    try:
        pid = int(profile_id)
    except (TypeError, ValueError):
        return None
    ensure(c)
    r = c.execute('SELECT id,name,color,hidden FROM kids_profiles WHERE id=?', (pid,)).fetchone()
    return _row(r) if r else None


def _name(value):
    name = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not name:
        raise ValueError('Bitte einen Namen eingeben')
    if len(name) > NAME_MAX:
        raise ValueError('Der Name darf höchstens %d Zeichen haben' % NAME_MAX)
    return name


def _color(value, fallback):
    value = str(value or '')
    return value if value in COLORS else fallback


def _hidden(value):
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError('Ungültige Kanalauswahl')
    out = set()
    for x in value[:500]:
        if isinstance(x, bool) or not isinstance(x, (int, str)) or not str(x).isdigit():
            raise ValueError('Ungültige Kanalauswahl')
        out.add(int(x))
    return json.dumps(sorted(out))


def save(c, data):
    """Profil anlegen (ohne id) oder ändern. Rückgabe: das Profil."""
    ensure(c)
    data = data or {}
    if data.get('id') in (None, ''):
        if c.execute('SELECT COUNT(*) FROM kids_profiles').fetchone()[0] >= MAX_PROFILES:
            raise ValueError('Höchstens %d Kinderprofile' % MAX_PROFILES)
        name = _name(data.get('name'))
        if c.execute('SELECT 1 FROM kids_profiles WHERE lower(name)=lower(?)', (name,)).fetchone():
            raise ValueError('Ein Profil „%s“ gibt es schon' % name)
        cur = c.execute('INSERT INTO kids_profiles(name,color,hidden,created) VALUES(?,?,?,?)',
                        (name, '', _hidden(data.get('hidden')) or '[]', time.time()))
        pid = cur.lastrowid
        c.execute('UPDATE kids_profiles SET color=? WHERE id=?', (_color(data.get('color'), COLORS[(pid - 1) % len(COLORS)]), pid))
        return get(c, pid)
    current = get(c, data.get('id'))
    if current is None:
        raise ValueError('Unbekanntes Kinderprofil')
    name = _name(data['name']) if 'name' in data else current['name']
    if c.execute('SELECT 1 FROM kids_profiles WHERE lower(name)=lower(?) AND id!=?', (name, current['id'])).fetchone():
        raise ValueError('Ein Profil „%s“ gibt es schon' % name)
    hidden = _hidden(data.get('hidden')) if 'hidden' in data else json.dumps(current['hidden'])
    c.execute('UPDATE kids_profiles SET name=?,color=?,hidden=? WHERE id=?',
              (name, _color(data.get('color'), current['color']), hidden, current['id']))
    return get(c, current['id'])


def delete(c, profile_id):
    """Profil entfernen. Sein Gesehen-Stand bleibt in watch_state liegen (wird nicht mehr angezeigt)."""
    current = get(c, profile_id)
    if current is None:
        raise ValueError('Unbekanntes Kinderprofil')
    c.execute('DELETE FROM kids_profiles WHERE id=?', (current['id'],))
    return current


def prefix(profile):
    """Schlüssel-Präfix in watch_state: '' für Profil 1 (bisheriger Stand) und ohne Profil, sonst 'kp<id>:'."""
    pid = (profile or {}).get('id') if isinstance(profile, dict) else profile
    return '' if not pid or int(pid) == 1 else 'kp%d:' % int(pid)


def key(profile, value):
    """watch_state-Schlüssel des Profils; ein schon vorangestelltes Präfix wird nicht doppelt gesetzt."""
    value = str(value or '')
    if PREFIX.match(value):
        value = PREFIX.sub('', value, count=1)
    return prefix(profile) + value


def marks(progress, profile):
    """Abspielstände eines Profils mit Schlüsseln ohne Präfix (wie die Kinderecke sie kennt)."""
    pre = prefix(profile)
    if not pre:
        return {k: v for k, v in (progress or {}).items() if not PREFIX.match(k)}
    return {k[len(pre):]: v for k, v in (progress or {}).items() if k.startswith(pre)}


def own_key(key):
    """Gehört der Schlüssel einem weiteren Kinderprofil (kp<id>:…)? Solche Einträge zeigt die Hauptansicht nicht."""
    return bool(PREFIX.match(str(key or '')))


def visible(data, profile):
    """YouTube-Teil von /api/kids auf die Kanäle des Profils beschränken."""
    hidden = {str(x) for x in (profile or {}).get('hidden') or ()}
    if not hidden:
        return data
    data = dict(data)
    data['channels'] = [ch for ch in data.get('channels') or [] if str(ch.get('id')) not in hidden]
    data['videos'] = [v for v in data.get('videos') or [] if str(v.get('abo')) not in hidden]
    return data


def public(c):
    """Für die Auswahl in der Kinderecke: nur Kennung, Name, Farbe."""
    return [{'id': p['id'], 'name': p['name'], 'color': p['color']} for p in profiles(c)]
