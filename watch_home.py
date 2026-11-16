"""0.6.8 Ansehen-Modus für Erwachsene (Björn, 15.11.2026: „Bitte auch einen Erwachsenen-Modus“).

Die Seite /ansehen zeigt dieselbe App ohne Verwaltung, aufgeräumt zum Anschauen (web/watch_mode.js).
Dieses Modul liefert in einem Aufruf, was nur auf dem Server liegt:
- fertige Offline-Kopien (Downloads, Netzkino-/Pluto-/YouTube-Offline), neueste zuerst,
- die Videos der YouTube-Abos im Profil „Für mich“ (0.6.11: youtube_abos.kids, profile='erwachsene';
  die Abos der Kinderecke erscheinen hier nicht mehr).
Weiterschauen/Merkliste (/api/watch), Kataloge (/api/unified) und Live-TV (/api/live-tv) holt die
Seite über die bestehenden Adressen.
"""
import json
from pathlib import Path

import youtube_abos

MAX_OFFLINE = 120
_KIND = {'movie': 'movie', 'series': 'episode', 'episode': 'episode'}


def _https(value):
    value = str(value or '')
    return value if value.startswith('https://') and not any(ch in value for ch in ' <>"\'') else ''


def _label(meta, source):
    title = str(meta.get('title') or source.get('title') or 'Video')
    season, episode = meta.get('season'), meta.get('episode')
    if isinstance(season, int) and isinstance(episode, int):
        title += ' · S%02dE%02d' % (season, episode)
    if meta.get('episode_title'):
        title += ' · ' + str(meta['episode_title'])
    return title[:220]


def offline(c, marks, limit=MAX_OFFLINE):
    """Fertige Downloads, deren Datei noch da ist (ohne die Abo-Videos, die kommen gebündelt)."""
    out = []
    for (payload,) in c.execute("SELECT payload FROM jobs WHERE state='done' ORDER BY rowid DESC LIMIT 600"):
        try:
            job = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if job.get('youtube_abo'):
            continue
        path = Path(str(job.get('path') or job.get('target') or ''))
        try:
            if not path.name or not path.is_file():
                continue
        except OSError:
            continue
        meta, source = job.get('metadata') or {}, job.get('source') or {}
        duration = source.get('duration') or meta.get('source_duration_seconds') or 0
        mark = marks.get('job:' + str(job.get('id'))) or {}
        try:
            duration = int(duration or 0)
        except (TypeError, ValueError):
            duration = 0
        out.append({'job': job.get('id'), 'title': _label(meta, source), 'kind': _KIND.get(meta.get('kind'), 'movie'),
                    'year': meta.get('year'), 'poster': _https(meta.get('poster')),
                    'local_poster': bool(youtube_abos.poster_file(job)),
                    'provider': str(meta.get('provider') or job.get('origin') or ''), 'duration': duration,
                    'until': job.get('offline_until'), 'new': not mark, 'done': bool(mark.get('done')),
                    'progress': round(min(1, (mark.get('pos') or 0) / duration), 3) if duration and not mark.get('done') else 0})
        if len(out) >= limit:
            break
    return out


def home(root, c, watch=None):
    import watch_state
    marks = watch if watch is not None else watch_state.overview(root).get('progress', {})
    return {'offline': offline(c, marks), 'abos': youtube_abos.kids(root, c, watch=marks, profile='erwachsene')}
