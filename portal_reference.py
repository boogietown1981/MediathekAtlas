"""Shared use of IMDb/TVDB/TMDB/OMDb/Wikidata reference checks for portal titles (0.5.38).

Netzkino (netzkino_enrichment) and Pluto TV (pluto_enrichment) store one reference report per
title, produced by the same ARD/ZDF provider chain (core.candidates) and the same conservative
evaluation (netzkino_enrichment.analyze). This module turns such a report into what every
source shows the same way:

* ``categories``: canonical German genres exactly as in the Mediathek catalogue tree
  (metadata.genre_names), reference genres first, the portal's own labels as fallback;
  'Unbekannt' when neither names a genre.
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


def categories(provider_genres, report=None):
    import metadata
    names = []
    if isinstance(report, dict):
        # The unique IMDb/TVDB/TMDB reference decides, as for Mediathek works; then the merged report.
        for ref in (report.get('reference_genres'), (report.get('metadata') or {}).get('genres')):
            names = metadata.genres(split_labels(ref)) if ref else []
            if names:
                break
    if not names:
        names = metadata.genres(split_labels(provider_genres))
    return names or [UNKNOWN]


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


def summary(provider_genres, report):
    """Fields a catalogue row gets: categories, score (reference rating), reference status."""
    out = {'categories': categories(provider_genres, report), 'score': rating(report),
           'reference_status': (report or {}).get('status') or 'unchecked'}
    sel = selected(report)
    if sel:
        out['reference'] = {'provider': sel['provider'], 'id': sel['reference_id']}
    return out


def matches(row, genre):
    if not genre:
        return True
    want = str(genre).strip().casefold()
    return any(c.casefold() == want for c in row.get('categories') or [UNKNOWN])


def facets(rows):
    """[{'genre','n'}] like catalog.tree, sorted by name, 'Unbekannt' last."""
    counts = {}
    for row in rows:
        for name in set(row.get('categories') or [UNKNOWN]):
            counts[name] = counts.get(name, 0) + 1
    return [{'genre': g, 'n': counts[g]} for g in sorted(counts, key=lambda g: (g == UNKNOWN, g.casefold()))]


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
    meta['genres'] = categories(meta.get('genres'), report)
    if meta['genres'] == [UNKNOWN]:
        meta['genres'] = []
    sel = selected(report)
    if sel:
        meta.update(provider=sel['provider'], reference_id=sel['reference_id'], source_provider=own_provider)
        if sel['provider'] in ('IMDb Offline', 'OMDb'):
            meta['imdb_id'] = sel['reference_id']
    rate = rating(report)
    if rate and meta.get('rating') is None:
        meta.update(rating=rate['value'], votes=ref.get('votes'), rating_source=rate['source'])
    return meta
