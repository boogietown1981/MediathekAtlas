"""Automatische Wiederholung vorübergehender Download-Fehler (0.6.13).

Björn, 16.11.2026: Abo-Videos blieben bei „0.0 MiB · Geschwindigkeit wird ermittelt“ hängen oder
endeten dauerhaft mit „YouTube verlangt eine Anmeldung („kein Bot“) … Später erneut versuchen“.
„Später“ musste er bisher selbst übernehmen. Jetzt:

* Eine Quelle meldet einen vorübergehenden Fehler mit :class:`RetryLater` (YouTube: Bot-Prüfung,
  „Too Many Requests“, Netzfehler, Download ohne Fortschritt).
* Der Auftrag bleibt in der Warteschlange und bekommt ``not_before`` mit wachsendem Abstand
  (:data:`BACKOFF`, je ±10 % gestreut). Erst nach dem letzten Versuch steht er auf „Fehler“.
* Eine Sperre (``block=True``, z. B. Bot-Prüfung) gilt für die ganze Quelle: Bis sie abläuft,
  startet kein weiterer Auftrag dieser Quelle (sonst würde jeder Folgeauftrag die Sperre bei YouTube
  verlängern). Die Abo-Prüfung wartet ebenfalls.
* „Jetzt versuchen“ (``job_queue.control(..., 'now')``) übergeht die Sperre einmal.

Nur Standardbibliothek; der Zustand der Sperre lebt im Speicher. Nach einem Neustart warten die
Aufträge trotzdem bis zu ihrem eigenen ``not_before``.
"""
from __future__ import annotations

import random
import threading
import time

BACKOFF = (15 * 60, 60 * 60, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600, 24 * 3600)
_LOCK = threading.Lock()
_BLOCKS = {}                      # Quelle -> (bis, Grund)


class RetryLater(ValueError):
    """Vorübergehender Fehler: später automatisch erneut versuchen.

    ``block``: die ganze Quelle pausiert (Sperre beim Anbieter), nicht nur dieser Auftrag."""

    def __init__(self, message, block=False):
        super().__init__(message)
        self.block = bool(block)


def source_of(job):
    src = (job or {}).get('source') or {}
    return str(src.get('_resolver') or job.get('origin') or '')


def blocked_until(source, now=None):
    """(Zeitpunkt, Grund) einer laufenden Sperre der Quelle, sonst (0, '')."""
    now = time.time() if now is None else float(now)
    with _LOCK:
        until, reason = _BLOCKS.get(source, (0.0, ''))
        if until <= now:
            _BLOCKS.pop(source, None)
            return 0.0, ''
        return until, reason


def block(source, until, reason=''):
    with _LOCK:
        old = _BLOCKS.get(source, (0.0, ''))[0]
        if until > old:
            _BLOCKS[source] = (float(until), str(reason)[:200])


def clear(source=None):
    with _LOCK:
        if source is None:
            _BLOCKS.clear()
        else:
            _BLOCKS.pop(source, None)


def _clock(ts):
    return time.strftime('%d.%m. %H:%M', time.localtime(ts))


def hold(job, now=None):
    """Vor dem Start: läuft eine Sperre der Quelle, den Auftrag bis zu ihrem Ende zurückstellen.
    Gibt True zurück, wenn der Auftrag warten muss (``job`` ist dann angepasst)."""
    now = time.time() if now is None else float(now)
    if job.pop('force_now', False):
        return False
    until, reason = blocked_until(source_of(job), now)
    if not until:
        return False
    job.update(not_before=until, note='Pausiert bis %s Uhr: %s' % (_clock(until), reason or 'Anbieter bremst'))
    return True


def reschedule(job, exc, now=None, rand=random.random):
    """Nach einem Fehler: bei :class:`RetryLater` den Auftrag mit wachsendem Abstand neu einreihen.
    Gibt True zurück, wenn der Auftrag wieder wartet; sonst bleibt es beim Fehler (der Text bekommt
    die Zahl der Versuche)."""
    if not isinstance(exc, RetryLater):
        return False
    now = time.time() if now is None else float(now)
    tries = int(job.get('retries') or 0) + 1
    message = str(exc)[:240]
    if tries > len(BACKOFF):
        job['error'] = '%s (nach %d automatischen Versuchen aufgegeben)' % (message, tries - 1)
        return False
    delay = BACKOFF[tries - 1] * (0.9 + 0.2 * rand())
    source = source_of(job)
    if exc.block:
        block(source, now + delay, message)
    until = max(now + delay, blocked_until(source, now)[0])
    job.update(state='queued', retries=tries, not_before=until, received=0, total=0, speed=0, eta=None, error='',
               last_error=message,
               note='%s · Versuch %d von %d um %s Uhr' % (message, tries + 1, len(BACKOFF) + 1, _clock(until)))
    return True
