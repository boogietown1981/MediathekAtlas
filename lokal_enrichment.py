"""IMDb/TVDB/TMDB/OMDb/Wikidata-Abgleich für Titel lokaler Filmarchive (0.6.151).

Dieselbe Umsetzung wie bei den Film-Plattformen (portal_enrichment): Titel und Jahr aus NFO bzw. Dateiname, konservativ
nur eine eindeutige Referenz; Folgen nutzen den Bericht ihrer Serie; Berichte in lokal.sqlite3."""
from __future__ import annotations

import portal_enrichment as engine
import lokal

SPEC = engine.Spec(name=lokal.NAME, key='lokal', items='lokal_items', checks='lokal_reference_checks',
                   connect=lokal._connect, valid_id=lambda v: bool(lokal.VALID_ID.fullmatch(v)),
                   last_success=lambda db: 0)
UNCHECKED = engine.UNCHECKED


def cached(root, item_id):
    return engine.cached(SPEC, root, item_id)


def all_cached(root):
    return engine.all_cached(SPEC, root)


def _nfo_ids(root, item_id):
    """IMDb-/TMDB-Nummer aus der NFO-Datei des Titels (Folgen: ihrer Serie)."""
    db = lokal._connect(root)
    try:
        row = engine.subject(SPEC, db, item_id)
    finally:
        db.close()
    return (row.get('imdb_id') or ''), (row.get('tmdb_id') or ''), row


def archive_candidate(tconst, row):
    """Kandidat direkt über die IMDb-Nummer aus dem lokalen IMDb-Archiv (ohne Netz); None ohne Archiv/Treffer."""
    import imdb_archive
    archive = imdb_archive.ACTIVE
    if not archive or not getattr(archive, 'updated', 0):
        return None
    try:
        hit = archive._reader().execute('SELECT b.*,r.averageRating,r.numVotes FROM title_basics b LEFT JOIN title_ratings r '
                                        'ON r.tconst=b.tconst WHERE b.tconst=?', (tconst,)).fetchone()
    except Exception:
        return None
    if not hit:
        return None
    kind = 'series' if hit['titleType'] in ('tvSeries', 'tvMiniSeries') else 'movie'
    return {'title': row.get('title') or hit['primaryTitle'], 'kind': kind, 'year': hit['startYear'], 'provider': 'IMDb Offline',
            'reference_id': tconst, 'genres': (hit['genres'] or '').split(',') if hit['genres'] else [],
            'genre_source': 'IMDb Offline', 'similarity': 1.0, 'confidence': 'high', 'year_mismatch': False,
            'episode_verified': False, 'runtime_agrees': False, 'runtime_mismatch': False, 'rating': hit['averageRating'],
            'votes': hit['numVotes'], 'reason': 'IMDb-Nummer aus der NFO-Datei', 'season': None, 'episode': None,
            'poster': '', 'episode_reference_id': None}


def nfo_lookup(lookup, imdb_id, tmdb_id, row, archive=archive_candidate):
    """Steht in der NFO-Datei eine IMDb-/TMDB-Nummer, gilt sie: andere Nummern desselben Anbieters fallen weg
    (kein „mehrdeutig“), fehlt der Treffer, kommt er direkt aus dem IMDb-Archiv."""
    if not imdb_id and not tmdb_id:
        return lookup

    def wrapped(row_arg, meta, settings):
        result = dict(lookup(row_arg, meta, settings) or {})
        keep = []
        for cand in result.get('candidates') or []:
            provider, ref = cand.get('provider'), str(cand.get('reference_id') or '')
            if imdb_id and provider in ('IMDb Offline', 'OMDb') and ref != imdb_id:
                continue
            if tmdb_id and provider == 'TMDB' and ref.split('/')[-1] != tmdb_id:
                continue
            keep.append(cand)
        if imdb_id and not any(c.get('provider') == 'IMDb Offline' for c in keep):
            extra = archive(imdb_id, row)
            if extra:
                keep.insert(0, extra)
        result['candidates'] = keep
        return result
    return wrapped


def enrich(root, item_id, settings, *, lookup=None, now=None, force=False):
    imdb_id, tmdb_id, row = _nfo_ids(root, item_id)
    if lookup is None:
        import core
        lookup = core.candidates
    return engine.enrich(SPEC, root, item_id, settings, lookup=nfo_lookup(lookup, imdb_id, tmdb_id, row), now=now, force=force)


def pending(root, limit=10, now=None):
    return engine.pending(SPEC, root, limit, now)


def metrics(root):
    return engine.metrics(SPEC, root)
