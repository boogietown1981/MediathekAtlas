"""Shared use of IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for portal titles (0.5.38).

Netzkino (netzkino_enrichment) and Pluto TV (pluto_enrichment) store one reference report per
title, produced by the same ARD/ZDF provider chain (core.candidates) and the same conservative
evaluation (netzkino_enrichment.analyze). This module turns such a report into what every
source shows the same way:

* ``categories``: since 0.5.83 the fixed German list of categories.py (reference genres first,
  the portal's own labels as fallback), 'Unklassifiziert' before the reference check.
* ``rating``: score from the selected reference (IMDb, TMDB …) with its source.
* ``apply``: job metadata for downloads (genres, description, cast, poster, NFO ids, rating),
  the same fields an ARD/ZDF download carries.
"""
from __future__ import annotations

import json
import re

UNKNOWN = 'Unbekannt'
NFO_PROVIDERS = ('IMDb Offline', 'TMDB', 'TVDB', 'OMDb')


def split_labels(value):
    """Portal genre field (JSON list, comma text or list) -> labels."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('['):
            try:
                value = json.loads(text)
            except ValueError:
                value = text
        if isinstance(value, str):
            value = re.split(r'\s*(?:[,;|·]|\s&\s)\s*', value)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip()][:20]


CHECKED = ('candidate', 'review', 'no_match')


def checked(report):
    """The reference check ran for this title (0.5.83): a result, an ambiguous result or no match.
    'partial' (providers paused) and 'unchecked' are retried later and stay unclassified."""
    if not isinstance(report, dict):
        return False
    return report.get('status') in CHECKED or bool(report.get('reference_genres'))


def reference_labels(report):
    if not isinstance(report, dict):
        return []
    # The unique IMDb/TVDB/TMDB reference decides, as for Mediathek works; then the merged report.
    for ref in (report.get('reference_genres'), (report.get('metadata') or {}).get('genres')):
        labels = split_labels(ref) if ref else []
        if labels:
            return labels
    return []


def categories(provider_genres, report=None, identified=False):
    """0.5.83: fixed German categories (categories.CATEGORIES) after the reference check,
    'Unklassifiziert' before it, 'Sonstige' when no label names a category. The provider's raw
    labels stay in the portal tables and appear as ``source_genres`` on the title page."""
    import categories as fixed
    return fixed.classify(reference_labels(report), split_labels(provider_genres), identified or checked(report))


def genre_names(provider_genres, report=None):
    """Canonical genre names for downloads/NFO (metadata.genres); unchanged since 0.5.38."""
    import metadata
    names = metadata.genres(reference_labels(report)) if isinstance(report, dict) else []
    return names or metadata.genres(split_labels(provider_genres))


def selected(report):
    """The unique eligible reference (only for status 'candidate')."""
    if not isinstance(report, dict) or report.get('status') != 'candidate' or not report.get('from_reference'):
        return None
    return next((r for r in report.get('references') or [] if r.get('eligible')
                 and r.get('provider') in NFO_PROVIDERS), None)


def rating(report):
    if not isinstance(report, dict):
        return None
    meta = report.get('metadata') or {}
    value = meta.get('rating')
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 10:
        return None
    source = (report.get('field_sources') or {}).get('rating') or ''
    label = {'IMDb Offline': 'IMDb', 'OMDb': 'IMDb'}.get(source, source)
    return {'value': round(float(value), 1), 'source': label, 'votes': meta.get('votes')}


def summary(provider_genres, report, identified=False):
    """Fields a catalogue row gets: categories, score (reference rating), reference status.

    ``identified``: the provider itself names the title's IMDb ID (JustWatch), so its genres are
    already classified data and count without our own reference check (0.5.83)."""
    out = {'categories': categories(provider_genres, report, identified), 'score': rating(report),
           'source_genres': split_labels(provider_genres)[:12],
           'reference_status': (report or {}).get('status') or 'unchecked'}
    sel = selected(report)
    if sel:
        out['reference'] = {'provider': sel['provider'], 'id': sel['reference_id']}
        # 0.5.63: year and title of the reference prove in the merged catalogue that "Ab ins Meer"
        # (upload without a year) and "Ab ins Meer: Auf der Suche …" (2012) are one film.
        if isinstance(sel.get('year'), int) and not isinstance(sel.get('year'), bool):
            out['reference']['year'] = sel['year']
        if sel.get('title'):
            out['reference']['title'] = str(sel['title'])[:240]
    return out


# "Entdecken" like the Mediathek catalogue (catalog.listing collection / app.js pickLabel):
# at least 7.5/10 with 10,000 IMDb or 1,000 TMDB votes; films -> 'Großes Kino', series -> 'Serienfavoriten'.
COLLECTIONS = {'cinema': 'movie', 'series': 'series'}


def is_pick(score):
    if not isinstance(score, dict):
        return False
    value, votes = score.get('value'), score.get('votes')
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 7.5 <= value <= 10:
        return False
    try:
        votes = int(votes or 0)
    except (TypeError, ValueError):
        return False
    need = {'IMDb': 10000, 'TMDB': 1000}.get(score.get('source'))
    return need is not None and votes >= need


def in_collection(row, collection, kind):
    """kind: 'movie' or 'series' of the row; empty collection keeps everything."""
    if not collection:
        return True
    return COLLECTIONS.get(collection) == kind and is_pick(row.get('score'))


def matches(row, genre):
    """Filter by a fixed category; 'Unbekannt' (older links) means 'Unklassifiziert'. A raw provider
    label that names exactly one category filters by that category."""
    if not genre:
        return True
    import categories as fixed
    name, raw = fixed.wanted(genre)
    cats = row.get('categories') or [fixed.UNCLASSIFIED]
    if name:
        return name in cats
    want = raw.casefold()
    return any(str(c).casefold() == want for c in cats) or \
        any(str(c).casefold() == want for c in row.get('source_genres') or [])


def facets(rows):
    """[{'genre','n'}] in the fixed order of categories.CATEGORIES, 'Unklassifiziert'/'Sonstige' last."""
    import categories as fixed
    counts = {}
    for row in rows:
        for name in set(row.get('categories') or [fixed.UNCLASSIFIED]):
            counts[name] = counts.get(name, 0) + 1
    return [{'genre': g, 'n': counts[g]} for g in sorted(counts, key=fixed.sort_key)]


def apply(meta, report, own_provider, *, series_report=False):
    """Complete download metadata like an ARD/ZDF job; portal's own fields keep priority.

    ``series_report``: the report describes the whole series (Pluto episodes), so its
    synopsis is kept as show description, never as the episode's own."""
    meta = dict(meta)
    ref = ((report or {}).get('metadata') or {}) if isinstance(report, dict) else {}
    if series_report and meta.get('kind') == 'series':
        if isinstance(ref.get('description'), str) and ref['description'] and not meta.get('show_description'):
            meta['show_description'] = ref['description']
        fields = ('poster',)
    else:
        fields = ('description', 'poster')
    for field in fields:
        if not meta.get(field) and isinstance(ref.get(field), str) and ref.get(field):
            meta[field] = ref[field]
    if not meta.get('cast') and ref.get('cast'):
        meta['cast'] = [{'name': n} for n in split_labels(ref['cast'])[:20]]
    for field in ('directors', 'writers'):
        if not meta.get(field) and ref.get(field):
            meta[field] = split_labels(ref[field])[:12]
    meta['genres'] = genre_names(meta.get('genres'), report)
    sel = selected(report)
    if sel:
        meta.update(provider=sel['provider'], reference_id=sel['reference_id'], source_provider=own_provider)
        if sel['provider'] in ('IMDb Offline', 'OMDb'):
            meta['imdb_id'] = sel['reference_id']
    rate = rating(report)
    if rate and meta.get('rating') is None:
        meta.update(rating=rate['value'], votes=ref.get('votes'), rating_source=rate['source'])
    return meta


def stored_result(last_result, active):
    """'running' left behind by an app restart during a catalogue run is reported as
    'interrupted'; the stored catalogue stays usable (0.5.41)."""
    return 'interrupted' if last_result == 'running' and not active else last_result


def first_load_due(current):
    """One automatic catalogue load on the very first start (never attempted), so nobody has to
    press "load" after installing; afterwards only the 24-hour automatic setting reloads."""
    return not current.get('running') and not current.get('last_success') and not current.get('last_attempt')
