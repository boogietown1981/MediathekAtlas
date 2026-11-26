"""0.6.148 (Björn 26.11.2026: „bitte auch geladene Videos bei der Anzeige bevorzugen, also geladene Filme und Serien“,
auf Nachfrage: auch im normalen Katalog): welche Titel eine lokale Kopie haben, für die Reihenfolge der Listen.

Grundlage wie beim Abspielen (streaming.resolve): ARD/ZDF & Co. über ``downloaded_items`` (je Werk; eine Reihe gilt als
geladen, sobald eine ihrer Folgen geladen ist), Plattform-Kopien (Netzkino, Pluto, Plex, ServusTV, Red Bull TV …) über
fertige Aufträge der gemeinsamen Warteschlange mit ``<origin>_id`` und vorhandener Datei. Nur lesen, ohne Netz."""
from __future__ import annotations

import json
from pathlib import Path

CHUNK = 500


_CACHE = {}
TTL = 30.0


def invalidate():
    _CACHE.clear()


def portal_copies_cached(c):
    """portal_copies, höchstens TTL alt (jeder Index-Aufbau fragte sonst alle fertigen Aufträge ab)."""
    import time
    hit = _CACHE.get('portal')
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    value = portal_copies(c)
    _CACHE['portal'] = (time.monotonic(), value)
    return value


def portal_copies(c):
    """{(quelle, id)} fertiger Plattform-Kopien, deren Datei noch da ist."""
    import netzkino_downloads
    out = set()
    try:
        rows = c.execute("SELECT payload FROM jobs WHERE state='done' AND json_valid(payload) AND json_extract(payload,'$.origin') IN (%s)"
                         % ','.join('?' * len(netzkino_downloads.PORTAL_LICENSES)), list(netzkino_downloads.PORTAL_LICENSES)).fetchall()
    except Exception:
        return out
    for (payload,) in rows:
        try:
            job = json.loads(payload)
        except (TypeError, ValueError):
            continue
        origin = job.get('origin') if isinstance(job, dict) else None
        if origin not in netzkino_downloads.PORTAL_LICENSES:
            continue
        item = str(job.get(origin + '_id') or '')
        path = job.get('path') or job.get('target') or ''
        try:
            if item and path and Path(path).is_file():
                out.add((origin, item))
        except OSError:
            continue
    return out


def local_works(c, series=False):
    """works.id mit lokaler Kopie; ``series``: dazu alle Werke einer Reihe, von der eine Folge geladen ist.
    Wenige Abfragen über die (kleine) Tabelle downloaded_items, nie je Katalogeintrag."""
    try:
        done = {r[0] for r in c.execute('SELECT identity FROM downloaded_items')}
        if not done or not series:
            return done
        shows = {r[0] for r in c.execute('SELECT DISTINCT w.show_key FROM works w JOIN downloaded_items d ON d.identity=w.id '
                                         'WHERE w.show_key IS NOT NULL')}
        out = set(done)
        shows = list(shows)
        for i in range(0, len(shows), CHUNK):
            part = shows[i:i + CHUNK]
            out |= {r[0] for r in c.execute('SELECT id FROM works WHERE show_key IN (%s)' % ','.join('?' * len(part)), part)}
        return out
    except Exception:
        return set()


def mark_entries(c, entries, series=False):
    """Einträge des gemeinsamen Index (unified_index.merge) mit lokaler Kopie: setzt ``local`` und gibt die Anzahl zurück."""
    works = local_works(c, series)
    portal = portal_copies_cached(c)
    n = 0
    for e in entries:
        hit = False
        for o in e['offers']:
            if o.get('source') == 'mediatheken':
                hit = str(o.get('id')) in works
            else:
                hit = (o.get('source'), str((o.get('item') or {}).get('id') or '')) in portal
            if hit:
                break
        if hit:
            e['local'] = True
            n += 1
        else:
            e.pop('local', None)
    return n


def local_first(items):
    """Geladene Einträge vorn, sonst Reihenfolge unverändert (stabil)."""
    return sorted(items, key=lambda e: not e.get('local'))
