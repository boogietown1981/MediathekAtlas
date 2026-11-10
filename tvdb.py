"""TheTVDB v4 client with bounded requests and credential-scoped outage protection.

Never include credentials, tokens, response bodies or provider URLs in diagnostic errors.
"""
import hashlib
import json
import threading
import time

import core
import diagnostics

_LOCK = threading.RLock()
_TOKENS = {}
_CACHE = {}
_PAUSED = {}
_FAILURES = {}
_REQUEST_TIMEOUT = 12
_MAX_CACHE_ENTRIES = 512


class TVDBError(ValueError):
    def __init__(self, status=0, reason='network', paused=False):
        self.status = status
        self.reason = reason
        self.paused = paused
        messages = {
            401: 'Zugang abgelehnt. Projektschlüssel und gegebenenfalls Abonnenten-PIN prüfen.',
            403: 'Zugang nicht freigeschaltet. API-Berechtigung bzw. Abonnement prüfen.',
            429: 'Anfragelimit erreicht; automatische Abfragen werden vorübergehend pausiert.',
        }
        if status in messages:
            message = messages[status]
        elif reason == 'timeout' or status == 408:
            message = 'Zeitüberschreitung bei der Anbieteranfrage.'
        elif reason == 'invalid_response':
            message = 'Ungültige API-Antwort.'
        elif reason == 'upstream' or status >= 500:
            message = 'Anbieterdienst vorübergehend nicht verfügbar.'
        else:
            message = 'Netzwerk nicht erreichbar.'
        super().__init__('TVDB' + (' HTTP ' + str(status) if status else '') + ': ' + message)


def _json(path, token='', body=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if body is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with core.open_url(
            'https://api4.thetvdb.com/v4/' + path,
            json.dumps(body).encode() if body is not None else None,
            headers,
            timeout=_REQUEST_TIMEOUT,
        ) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise TVDBError(reason='invalid_response')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('status') != 'success':
            raise TVDBError(reason='invalid_response')
        return data
    except core.urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise TVDBError(status, 'upstream' if status >= 500 else 'http') from None
    except (TimeoutError,):
        raise TVDBError(reason='timeout') from None
    except (core.urllib.error.URLError, OSError):
        raise TVDBError(reason='network') from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TVDBError(reason='invalid_response') from None


def request(path, key, pin='', params=None, force=False):
    credential = hashlib.sha256(json.dumps([key, pin]).encode()).hexdigest()
    if params:
        path += '?' + core.urllib.parse.urlencode(params)
    ck = (credential, path)
    # Serialize cache misses and authentication for identical credentials.
    # Failures are handled once per credential, not once per waiting worker.
    with _LOCK:
        now = time.monotonic()
        pause = _PAUSED.get(credential)
        if not force and pause and now < pause[0]:
            raise TVDBError(pause[1], pause[2], paused=True)
        cached = _CACHE.get(ck)
        if not force and cached and now - cached[0] < 21600:
            return cached[1]
        try:
            for attempt in range(2):
                token = _TOKENS.get(credential)
                if force or not token or time.monotonic() - token[0] > 27 * 86400:
                    body = {'apikey': key}
                    if pin:
                        body['pin'] = pin
                    value = _json('login', body=body).get('data', {}).get('token')
                    if not isinstance(value, str) or not value:
                        raise TVDBError(reason='invalid_response')
                    diagnostics.register_secrets(value)
                    token = (time.monotonic(), value)
                    _TOKENS[credential] = token
                try:
                    result = _json(path, token[1])
                    break
                except TVDBError as exc:
                    if exc.status == 401 and attempt == 0:
                        _TOKENS.pop(credential, None)
                        continue
                    raise
        except TVDBError as exc:
            if exc.status in (401, 403, 429):
                delay = 3600
            elif exc.status in (408, 425) or exc.status >= 500 or exc.status == 0:
                # 60, 120, 240, 480, 900 seconds; protect a bulk queue
                # against repeated 12-second login failures.
                failures = _FAILURES.get(credential, 0) + 1
                _FAILURES[credential] = failures
                delay = min(900, 60 * 2 ** min(failures - 1, 4))
            else:
                delay = 0
            if delay:
                _PAUSED[credential] = (time.monotonic() + delay, exc.status, exc.reason)
                diagnostics.event('tvdb_circuit_open', reason=exc.reason,
                                  status=exc.status, cooldown_seconds=delay)
                raise TVDBError(exc.status, exc.reason, paused=True) from None
            raise
        _PAUSED.pop(credential, None)
        _FAILURES.pop(credential, None)
        if len(_CACHE) >= _MAX_CACHE_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[ck] = (time.monotonic(), result)
        return result


def test_access(key, pin=''):
    if not key:
        return {'ok': False, 'message': 'Kein TVDB-Projektschlüssel gespeichert. Zuerst Einstellungen speichern.'}
    try:
        request('search', key, pin, {'query': 'Bibi und Tina', 'type': 'series', 'limit': 1}, force=True)
        result = {'ok': True, 'message': 'TVDB erreichbar. Anmeldung und Serienabfrage erfolgreich.'}
    except TVDBError as exc:
        result = {'ok': False, 'message': str(exc)}
    diagnostics.event('provider_connection_test', provider='TVDB', **result)
    return result
