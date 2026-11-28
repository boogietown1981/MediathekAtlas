"""0.6.171: PIN für den Elternbereich der Kinderecke (Abo-Profile/PIN, Punkt 3 des Umfangs vom 28.11.2026).

Ist eine PIN gesetzt, sperrt das Öffnen der Kinderecke DIESEN Browser: der Server merkt sich eine zufällige
Sperr-Kennung (Cookie ``atlas_kids_lock``, HttpOnly, SameSite=Strict) und lässt für ihn nur noch die Kinderecke zu;
die Hauptansicht leitet auf /kinder um, andere Aufrufe antworten 423. Der Eltern-Knopf fragt die PIN ab.

Ehrliche Grenzen (so auch in der Oberfläche):
* Die Sperre gilt nur für den Browser, in dem die Kinderecke geöffnet wurde. Wer die Browserdaten löscht oder einen
  anderen Browser bzw. ein anderes Gerät nimmt, ist nicht gesperrt.
* PIN vergessen: MediathekAtlas in einem anderen, nicht gesperrten Browser öffnen (im Netzwerkmodus mit Anmeldung)
  und unter Einstellungen → Kinderecke · Eltern zurücksetzen. Ein gesperrter Browser kann die PIN nicht ändern.

Die PIN wird nur gesalzen und gestreckt gespeichert (PBKDF2-SHA256) und nie protokolliert. Nach MAX_FAILS
Fehlversuchen wächst die Wartezeit (30 s, 60 s, … höchstens 15 min)."""
import hashlib
import hmac
import re
import secrets
import threading
import time

COOKIE = 'atlas_kids_lock'
COOKIE_SECONDS = 400 * 24 * 3600
ITERATIONS = 120000          # auf älteren NAS-CPUs noch unter einer Sekunde
PIN = re.compile(r'[0-9]{4,6}')
MAX_FAILS = 5
FIRST_WAIT = 30
MAX_WAIT = 900
MAX_LOCKS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS kids_pin(
 id INTEGER PRIMARY KEY CHECK(id=1),
 salt TEXT NOT NULL,
 hash TEXT NOT NULL,
 iterations INTEGER NOT NULL,
 set_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kids_locks(
 token TEXT PRIMARY KEY,
 created REAL NOT NULL DEFAULT 0);
"""

_FAILS = {}            # Sperr-Kennung (bzw. '' ohne) -> (Fehlversuche, gesperrt bis)
_LOCK = threading.Lock()


def ensure(c):
    c.executescript(SCHEMA)


def _hash(pin, salt, iterations):
    return hashlib.pbkdf2_hmac('sha256', pin.encode('ascii'), bytes.fromhex(salt), iterations).hex()


def _valid(pin):
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        raise ValueError('Die PIN muss aus 4 bis 6 Ziffern bestehen')
    return pin


def pin_set(c):
    ensure(c)
    return bool(c.execute('SELECT 1 FROM kids_pin WHERE id=1').fetchone())


def set_pin(c, pin):
    pin = _valid(pin)
    ensure(c)
    salt = secrets.token_hex(16)
    c.execute('INSERT OR REPLACE INTO kids_pin(id,salt,hash,iterations,set_at) VALUES(1,?,?,?,?)',
              (salt, _hash(pin, salt, ITERATIONS), ITERATIONS, time.time()))
    with _LOCK:
        _FAILS.clear()
    return True


def clear_pin(c):
    """PIN entfernen; alle gesperrten Browser sind damit frei."""
    ensure(c)
    c.execute('DELETE FROM kids_pin')
    c.execute('DELETE FROM kids_locks')
    with _LOCK:
        _FAILS.clear()
    return True


def _matches(c, pin):
    row = c.execute('SELECT salt,hash,iterations FROM kids_pin WHERE id=1').fetchone()
    if not row:
        return True
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        return False
    return hmac.compare_digest(_hash(pin, row[0], int(row[2])), row[1])


def lock(c):
    """Diesen Browser sperren (nur mit PIN). Rückgabe: neue Sperr-Kennung oder None."""
    if not pin_set(c):
        return None
    token = secrets.token_urlsafe(24)
    c.execute('INSERT INTO kids_locks(token,created) VALUES(?,?)', (token, time.time()))
    # alte Kennungen (verlorene Browser) begrenzen
    c.execute('DELETE FROM kids_locks WHERE token NOT IN (SELECT token FROM kids_locks ORDER BY created DESC LIMIT ?)', (MAX_LOCKS,))
    return token


def locked(c, token):
    """Ist dieser Browser gesperrt? Ohne PIN nie (eine entfernte PIN gibt alle frei)."""
    if not token or len(token) > 64:
        return False
    ensure(c)
    return bool(c.execute('SELECT 1 FROM kids_locks WHERE token=? AND EXISTS(SELECT 1 FROM kids_pin)', (token,)).fetchone())


def wait_seconds(token, now=None):
    now = time.time() if now is None else now
    with _LOCK:
        fails, until = _FAILS.get(token or '', (0, 0))
    return max(0, int(until - now + 0.999)) if until > now else 0


def unlock(c, token, pin, now=None):
    """PIN prüfen und die Sperre dieses Browsers aufheben. ValueError mit verständlichem Text bei Fehler/Pause."""
    now = time.time() if now is None else now
    key = token or ''
    wait = wait_seconds(key, now)
    if wait:
        raise ValueError('Zu viele falsche Versuche – bitte %d Sekunden warten' % wait)
    if not _matches(c, pin):
        with _LOCK:
            fails, _ = _FAILS.get(key, (0, 0))
            fails += 1
            until = now + min(MAX_WAIT, FIRST_WAIT * 2 ** (fails - MAX_FAILS)) if fails >= MAX_FAILS else 0
            _FAILS[key] = (fails, until)
            if len(_FAILS) > 1000:
                _FAILS.clear()
        raise ValueError('Falsche PIN' if not until else 'Falsche PIN – bitte %d Sekunden warten' % int(until - now))
    with _LOCK:
        _FAILS.pop(key, None)
    if token:
        c.execute('DELETE FROM kids_locks WHERE token=?', (token,))
    return True


def failures(token):
    with _LOCK:
        return _FAILS.get(token or '', (0, 0))[0]


def cookie(token, seconds=COOKIE_SECONDS):
    return '%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d' % (COOKIE, token, seconds)


# Was ein gesperrter Browser noch darf: die Kinderecke selbst, ihre Bilder, Wiedergabe und Abspielstand.
GET_ALLOWED = ('/kinder', '/kids.css', '/kids.js', '/hls.min.js', '/api/kids', '/api/kids-episodes', '/api/kids-play',
               '/api/kids-image', '/api/kids-live', '/api/kids-lock', '/api/stream', '/api/download-file')
POST_ALLOWED = ('/api/watch-progress', '/api/kids-lock')


def allowed(method, path):
    return path in (GET_ALLOWED if method == 'GET' else POST_ALLOWED)
