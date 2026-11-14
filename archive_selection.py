"""Staffel- und Folgenauswahl für einen Archive.org-Upload (0.5.88), aus Archive Media.

ArchiveMedia ``selection_matrix``: before a download of many files the user says what is wanted
(sound language, subtitles, resolution, file format) and sees for every episode which file would
be taken and why the others are not. One file per episode: the best that fits. Until now every
file of an upload had to be started by hand.

Pure functions over the stored manifest (portal_sources.archive_detail_document) and the stored
track checks (portal_video_probes). A language written in a file name is a hint, a language read
from the tracks is a proof; ``verified`` asks for the proof. Nothing is fetched here.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

HEIGHTS = (0, 480, 720, 1080, 1440, 2160)
FORMATS = ('', '.mkv', '.mp4', '.avi', '.webm', '.m4v', '.mov', '.ts', '.mpeg', '.mpg', '.ogv')
MODES = ('any', 'exact', 'at_least', 'at_most')
BLOCKED_ROLES = ('bdmv_stream', 'transport_segment', 'extra_or_clip', 'short_unknown')
MAX_FILES = 300          # one request never queues more


def _languages(data, key):
    value = data.get(key, [])
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError('Sprachfilter ungültig')
    return sorted({v.lower() for v in value if isinstance(v, str) and 2 <= len(v) < 10 and v.replace('-', '').isalnum()})


def criteria(data):
    """Checked wishes of the user; unknown or wrong values are refused, not guessed."""
    data = data if isinstance(data, dict) else {}
    out = {'audio': _languages(data, 'audio'), 'subtitle': _languages(data, 'subtitle')}
    for key in ('audio_match', 'subtitle_match'):
        value = data.get(key, 'all')
        if value not in ('any', 'all'):
            raise ValueError('Sprachmodus ungültig')
        out[key] = value
    out['resolution_mode'] = data.get('resolution_mode', 'any')
    if out['resolution_mode'] not in MODES:
        raise ValueError('Auflösungsmodus ungültig')
    try:
        out['height'] = int(data.get('height') or 0)
    except (TypeError, ValueError):
        raise ValueError('Auflösung ungültig') from None
    if out['height'] not in HEIGHTS:
        raise ValueError('Auflösung ungültig')
    if out['resolution_mode'] != 'any' and not out['height']:
        raise ValueError('Auflösung erforderlich')
    out['format'] = str(data.get('format', '')).lower()
    if out['format'] not in FORMATS:
        raise ValueError('Formatfilter ungültig')
    out['verified'] = data.get('verified') is True       # languages must be proven by the tracks
    out['originals'] = data.get('originals') is True     # no files Archive.org derived itself
    season = data.get('season')
    out['season'] = int(season) if isinstance(season, int) and 0 <= season <= 200 else None
    return out


def quality_bucket(height):
    try:
        h = int(height or 0)
    except (TypeError, ValueError):
        h = 0
    return 2160 if h >= 2000 else 1440 if h >= 1400 else 1080 if h >= 1000 else 720 if h >= 700 else 480 if h >= 1 else 0


def facts(variant, probe=None):
    """What is known about a file: languages (with their origin), height, format."""
    probe = probe if isinstance(probe, dict) else {}
    proven_audio = [str(x).lower() for x in probe.get('audio_languages_from_tracks') or []]
    proven_subs = [str(x).lower() for x in probe.get('subtitle_languages_from_tracks') or []]
    sidecars = [str(s.get('language') or '').lower() for s in variant.get('sidecar_subtitles') or [] if isinstance(s, dict)]
    hint_audio = [str(x).lower() for x in variant.get('audio_hint_languages') or []]
    hint_subs = [str(x).lower() for x in variant.get('subtitle_hint_languages') or []]
    return {'audio': proven_audio or hint_audio, 'audio_proven': bool(proven_audio),
            'subtitle': sorted({*proven_subs, *[s for s in sidecars if s]} or set(hint_subs)),
            'subtitle_proven': bool(proven_subs or any(sidecars)),
            'height': quality_bucket(variant.get('height')),
            'format': PurePosixPath(str(variant.get('filename') or '')).suffix.lower(),
            'original': str(variant.get('source') or '').lower() == 'original'}


def _matches(available, wanted, mode):
    if not wanted:
        return True
    have = set(available)
    return all(x in have for x in wanted) if mode == 'all' else any(x in have for x in wanted)


def rejection(variant, known, c):
    """Why a file is not taken, or None."""
    if variant.get('technical_role') in BLOCKED_ROLES:
        return 'Technisches Segment oder Clip'
    if variant.get('identity_warning'):
        return 'Folge nicht eindeutig zugeordnet'
    if not _matches(known['audio'], c['audio'], c['audio_match']):
        return 'Gewünschte Tonsprache nicht angegeben'
    if not _matches(known['subtitle'], c['subtitle'], c['subtitle_match']):
        return 'Gewünschte Untertitel nicht angegeben'
    if c['verified']:
        if c['audio'] and not known['audio_proven']:
            return 'Tonsprache nicht durch die Tonspur belegt (erst „Format und Tonspuren prüfen“)'
        if c['subtitle'] and not known['subtitle_proven']:
            return 'Untertitel nicht belegt'
    mode, target, h = c['resolution_mode'], c['height'], known['height']
    if mode == 'exact' and h != target:
        return 'Auflösung passt nicht' if h else 'Auflösung unbekannt'
    if mode == 'at_least' and h < target:
        return 'Auflösung zu niedrig' if h else 'Auflösung unbekannt'
    if mode == 'at_most' and (not h or h > target):
        return 'Auflösung zu hoch' if h else 'Auflösung unbekannt'
    if c['format'] and known['format'] != c['format']:
        return 'Dateiformat passt nicht'
    if c['originals'] and not known['original']:
        return 'Von Archive.org umgerechnete Fassung'
    return None


def score(variant, known, c):
    """Higher is better: proven languages, then the resolution closest to the wish (without a
    wish the highest), then the uploader's original, then the larger file."""
    h = known['height']
    closeness = -abs(h - c['height']) if c['height'] else h
    return (int(known['audio_proven']), int(known['subtitle_proven']), closeness, int(known['original']),
            int(variant.get('size_bytes') or 0), str(variant.get('filename') or ''))


def matrix(detail, probes=None, wishes=None):
    """One row per episode (or one for a film) with the file that would be loaded."""
    c = criteria(wishes)
    probes = probes if isinstance(probes, dict) else {}
    variants = [v for v in (detail or {}).get('video_variants') or [] if isinstance(v, dict) and v.get('filename')]
    series = any(v.get('kind') == 'series' for v in variants)
    groups, unassigned = defaultdict(list), 0
    for v in variants:
        if series:
            season, episode = v.get('season'), v.get('episode')
            if not isinstance(season, int) or not isinstance(episode, int):
                unassigned += 1
                continue
            if c['season'] is not None and season != c['season']:
                continue
            key = (season, episode)
        else:
            # A film upload: every logical file family is its own row (several films in one upload).
            key = ('movie', str(v.get('family_id') or v['filename']))
        groups[key].append(v)
    rows = []
    for key in sorted(groups, key=lambda k: (0, k[0], k[1]) if series else (1, 0, k[1])):
        options = [(v, facts(v, probes.get(v['filename']))) for v in groups[key]]
        reasons = defaultdict(int)
        fitting = []
        for v, known in options:
            bad = rejection(v, known, c)
            if bad:
                reasons[bad] += 1
            else:
                fitting.append((v, known))
        winner = max(fitting, key=lambda pair: score(pair[0], pair[1], c)) if fitting else None
        v, known = winner if winner else (None, None)
        rows.append({'season': key[0] if series else None, 'episode': key[1] if series else None,
                     'filename': v['filename'] if v else None, 'title': (v or options[0][0]).get('title') or '',
                     'quality': known['height'] if v else None, 'format': known['format'] if v else None,
                     'audio': known['audio'] if v else [], 'audio_proven': known['audio_proven'] if v else False,
                     'subtitle': known['subtitle'] if v else [], 'size_bytes': v.get('size_bytes') if v else None,
                     'duration_seconds': v.get('duration_seconds') if v else None,
                     'options': len(options), 'matching': len(fitting), 'reasons': dict(reasons),
                     'status': 'matched' if v else 'missing'})
    matched = [r for r in rows if r['filename']]
    seasons = sorted({v.get('season') for v in variants if series and isinstance(v.get('season'), int)})
    return {'kind': 'series' if series else 'movie', 'criteria': c, 'rows': rows, 'seasons': seasons,
            'matched': len(matched), 'missing': len(rows) - len(matched), 'unassigned_files': unassigned,
            'estimated_bytes': sum(r['size_bytes'] or 0 for r in matched),
            'unknown_sizes': sum(1 for r in matched if not r['size_bytes']),
            'complete': bool((detail or {}).get('inventory_complete')) and bool((detail or {}).get('display_complete')),
            'note': 'Die Übersicht kennt nur die Folgen, die in diesem Upload liegen. Fehlt eine Folge im Upload, '
                    'fehlt sie auch hier.'}


def choose(result, picks=None):
    """File names to queue: the winners, optionally only the rows the user ticked."""
    names = [r['filename'] for r in result['rows'] if r['filename']]
    if picks is not None:
        if not isinstance(picks, list) or len(picks) > MAX_FILES * 4:
            raise ValueError('Auswahl ungültig')
        wanted = {str(p) for p in picks}
        names = [n for n in names if n in wanted]
    if len(names) > MAX_FILES:
        raise ValueError('Höchstens %d Dateien auf einmal; bitte eine Staffel wählen' % MAX_FILES)
    return names


def enqueue(c, download_dir, item_id, wishes=None, picks=None, queue=None):
    """Queue the chosen files of one upload. Only winners of the matrix can be queued, so a request
    cannot name arbitrary files."""
    import archive_downloads
    import portal_sources
    saved = portal_sources.archive_saved_detail(c, item_id)
    if not saved.get('detail') or saved['detail'].get('source') != 'internet_archive':
        raise ValueError('Bitte erst den Archiv-Dateibestand prüfen')
    result = matrix(saved['detail'], saved.get('probes'), wishes)
    names = choose(result, picks)
    if not names:
        raise ValueError('Keine passende Datei für diese Auswahl')
    queue = queue or archive_downloads.enqueue
    created = existing = 0
    failed = []
    for name in names:
        try:
            answer = queue(c, download_dir, item_id, name)
        except ValueError as exc:
            failed.append({'filename': name, 'error': str(exc)[:200]})
            continue
        if answer.get('created') is False:
            existing += 1
        else:
            created += 1
    return {'ok': True, 'created': created, 'existing': existing, 'failed': failed, 'files': len(names),
            'estimated_bytes': sum(r['size_bytes'] or 0 for r in result['rows'] if r['filename'] in set(names))}
