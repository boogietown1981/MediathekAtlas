"""Central control of the background tasks (0.5.55).

Björn (12.11.2026): under "Verwaltung" the processing of the tasks should be controllable. Until
now every background loop decided for itself (settings flags, per-platform "auto" switches) and
nothing could be paused without changing those settings.

One small registry for all loops:

* ``paused(task)`` / ``wait_if_paused(task, stop)`` – cooperative pause, checked by the loop
  between two work items (a running item is finished, nothing is torn down);
* ``priority(task)`` – ``high`` / ``normal`` / ``low``; loops with a pause between items scale
  that pause with ``factor(task)``;
* ``request(task)`` / ``take_request(task)`` – "run now";
* ``note(task, ...)`` – what the loop is doing at the moment (shown in the list).

The choices are stored in ``task-control.json`` next to the databases and survive restarts.
Unknown task ids are ignored, so an older file never breaks a newer version.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

PRIORITIES = ('high', 'normal', 'low')
FACTOR = {'high': 0.35, 'normal': 1.0, 'low': 3.0}
PRIORITY_LABEL = {'high': 'Hoch', 'normal': 'Normal', 'low': 'Niedrig'}

PORTALS = (('netzkino', 'Netzkino'), ('pluto', 'Pluto TV'), ('justwatch', 'JustWatch TV'),
           ('rakuten', 'Rakuten TV'), ('youtube', 'YouTube'), ('joyn', 'Joyn'), ('toggo', 'TOGGO'))

# id -> definition. ``can``: pause, start (run now), priority, cancel.
TASKS = {
    'filmlist': {'label': 'Filmliste ARD, ZDF & Co.', 'group': 'Katalogabrufe',
                 'hint': 'Lädt die Filmliste der öffentlich-rechtlichen Mediatheken und gleicht den Katalog ab.',
                 'can': ('pause', 'start')},
    'recognition': {'label': 'Werkerkennung', 'group': 'Werkzuordnung',
                    'hint': 'Ordnet Filme und Serien aus ARD, ZDF & Co. über IMDb, TVDB, TMDB und Wikidata zu.',
                    'can': ('pause',)},
    'episodes': {'label': 'Folgenabgleich', 'group': 'Werkzuordnung',
                 'hint': 'Bestätigt Staffel und Folge erkannter Serien.',
                 'can': ('pause',)},
    'artwork': {'label': 'Cover und Bilder', 'group': 'Werkzuordnung',
                'hint': 'Lädt Poster und Hintergrundbilder zu erkannten Werken.',
                'can': ('pause',)},
    'imdb': {'label': 'IMDb-Archiv aktualisieren', 'group': 'Werkzuordnung',
             'hint': 'Wöchentlicher Abruf der IMDb-Datensätze für die Offline-Erkennung.',
             'can': ('pause', 'start')},
    'downloads': {'label': 'Downloads', 'group': 'Downloads',
                  'hint': 'Arbeitet die Download-Warteschlange ab. Pausiert: ein laufender Download wird beendet, '
                          'weitere starten erst nach dem Fortsetzen.',
                  'can': ('pause',)},
    'subscriptions': {'label': 'Download-Abos', 'group': 'Downloads',
                      'hint': 'Legt aus Abos neue Download-Aufträge an.',
                      'can': ('pause',)},
    'backup': {'label': 'Datenbanksicherung', 'group': 'Wartung',
               'hint': 'Sichert die Katalogdatenbank wöchentlich geprüft nach „Backups“ (4 automatische bleiben, '
                       'eigene Sicherungen werden nie automatisch gelöscht).',
               'can': ('pause', 'start')},
}
for _key, _name in PORTALS:
    TASKS['catalog:' + _key] = {
        'label': _name + ' · Katalogabruf', 'group': 'Katalogabrufe', 'portal': _key,
        'hint': 'Lädt den Katalog von ' + _name + ' (automatisch nur, wenn der tägliche Abruf eingeschaltet ist).',
        'can': ('pause', 'start')}
for _key, _name in PORTALS:
    TASKS['enrich:' + _key] = {
        'label': _name + ' · Werkzuordnung', 'group': 'Werkzuordnung', 'portal': _key,
        'hint': 'Prüft jeden Titel von ' + _name + ' gegen IMDb, TVDB und TMDB (ein Titel alle paar Sekunden).',
        'can': ('pause', 'priority')}

_LOCK = threading.RLock()
_PATH = None
_STATE = {}          # id -> {'paused': bool, 'priority': str}
_NOTES = {}          # id -> {'text': str, 'at': float, ...}
_REQUESTS = set()
_WAKE = threading.Event()


def configure(path):
    """Load the stored choices. Call once at start; without it everything runs unpaused."""
    global _PATH
    with _LOCK:
        _PATH = Path(path)
        _STATE.clear()
        try:
            stored = json.loads(_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            stored = {}
        if isinstance(stored, dict):
            for task, value in stored.items():
                if task in TASKS and isinstance(value, dict):
                    _STATE[task] = {'paused': value.get('paused') is True,
                                    'priority': value.get('priority') if value.get('priority') in PRIORITIES else 'normal'}


def _save():
    if _PATH is None:
        return
    data = {k: v for k, v in _STATE.items() if v.get('paused') or v.get('priority', 'normal') != 'normal'}
    tmp = _PATH.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding='utf-8')
        tmp.replace(_PATH)
    except OSError:
        pass   # the choice still applies until the next start


def _check(task):
    if task not in TASKS:
        raise ValueError('Unbekannte Aufgabe')
    return TASKS[task]


def paused(task):
    return bool(_STATE.get(task, {}).get('paused'))


def priority(task):
    return _STATE.get(task, {}).get('priority', 'normal')


def factor(task):
    return FACTOR[priority(task)]


def set_paused(task, value):
    spec = _check(task)
    if 'pause' not in spec['can']:
        raise ValueError('Diese Aufgabe lässt sich nicht pausieren')
    with _LOCK:
        _STATE.setdefault(task, {'paused': False, 'priority': 'normal'})['paused'] = bool(value)
        _save()
    _WAKE.set()
    return status_of(task)


def set_priority(task, value):
    spec = _check(task)
    if 'priority' not in spec['can']:
        raise ValueError('Für diese Aufgabe gibt es keine Priorität')
    if value not in PRIORITIES:
        raise ValueError('Unbekannte Priorität')
    with _LOCK:
        _STATE.setdefault(task, {'paused': False, 'priority': 'normal'})['priority'] = value
        _save()
    _WAKE.set()
    return status_of(task)


def pause_all(value, group=''):
    """Pause or continue every pausable task (optionally of one group)."""
    with _LOCK:
        for task, spec in TASKS.items():
            if 'pause' in spec['can'] and (not group or spec['group'] == group):
                _STATE.setdefault(task, {'paused': False, 'priority': 'normal'})['paused'] = bool(value)
        _save()
    _WAKE.set()


def request(task):
    """Ask a loop to run now (the loop picks it up with take_request)."""
    _check(task)
    with _LOCK:
        _REQUESTS.add(task)
    _WAKE.set()


def take_request(task):
    with _LOCK:
        if task in _REQUESTS:
            _REQUESTS.discard(task)
            return True
    return False


def wait_if_paused(task, stop, poll=1.0):
    """Block while the task is paused. Returns False when the application stops."""
    while paused(task):
        note(task, 'Pausiert')
        if stop.wait(poll):
            return False
    return not stop.is_set()


def note(task, text='', **extra):
    """Remember what a loop is doing right now (cheap, memory only)."""
    if task in TASKS:
        _NOTES[task] = {'text': str(text)[:200], 'at': time.time(), **extra}


def status_of(task):
    spec = _check(task)
    seen = _NOTES.get(task) or {}
    return {'id': task, 'label': spec['label'], 'group': spec['group'], 'hint': spec['hint'],
            'can': list(spec['can']), 'portal': spec.get('portal', ''),
            'paused': paused(task), 'priority': priority(task),
            'note': seen.get('text', ''), 'note_at': seen.get('at', 0)}


def overview():
    return [status_of(task) for task in TASKS]
