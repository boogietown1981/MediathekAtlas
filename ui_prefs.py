"""Presentation of films and series in tiles and on the title page (0.5.55).

Björn (12.11.2026): under "Verwaltung" the presentation per film should be adjustable. One set of
choices for every platform, so that tiles and title pages look and behave alike everywhere. The
choices are stored in ``display.json`` next to the databases (no secrets, no titles) and apply to
every browser that opens this MediathekAtlas.
"""
from __future__ import annotations

import json
from pathlib import Path

SIZES = ('compact', 'normal', 'large')
START_SOURCES = ('all', 'mediatheken', 'netzkino', 'pluto', 'justwatch', 'rakuten', 'youtube', 'joyn', 'toggo', 'crunchyroll', 'plex')
START_KINDS = ('movies', 'series')
THEMES = ('dark', 'light', 'auto')   # 0.5.99: 'auto' follows the system setting of the browser

# key -> (group, label, default)
SWITCHES = {
    'card_poster': ('Kachel', 'Cover', True),
    'card_source': ('Kachel', 'Anbieter', True),
    'card_facts': ('Kachel', 'Art, Jahr und Genres', True),
    'card_rating': ('Kachel', 'Bewertung', True),
    'card_pick': ('Kachel', 'Auszeichnung „Großes Kino“ / „Serienfavorit“', True),
    'card_description': ('Kachel', 'Beschreibung', True),
    'card_play': ('Kachel', 'Knopf „Ansehen“', True),
    'card_offline': ('Kachel', 'Knopf „Offline speichern“', True),
    'card_external': ('Kachel', 'Verweis zum Anbieter', True),
    'merge_duplicates': ('Gesamtansicht', 'Gleiche Titel mehrerer Anbieter zu einer Kachel zusammenfassen', True),
    'title_backdrop': ('Titelseite', 'Großes Hintergrundbild', True),
    'title_cast': ('Titelseite', 'Besetzung und Stab', True),
    'title_info': ('Titelseite', 'Angaben wie Sender, Laufzeit und Quelle', True),
    'title_versions': ('Titelseite', 'Fassungen und Dateien', True),
}
DEFAULTS = {'card_size': 'normal', 'start_source': 'all', 'start_kind': 'movies', 'theme': 'dark',
            **{key: value[2] for key, value in SWITCHES.items()}}


def clean(data):
    """Only known keys with valid values; everything else falls back to the default."""
    out = dict(DEFAULTS)
    if not isinstance(data, dict):
        return out
    for key in SWITCHES:
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if data.get('card_size') in SIZES:
        out['card_size'] = data['card_size']
    if data.get('start_source') in START_SOURCES:
        out['start_source'] = data['start_source']
    if data.get('start_kind') in START_KINDS:
        out['start_kind'] = data['start_kind']
    if data.get('theme') in THEMES:
        out['theme'] = data['theme']
    return out


def load(root):
    try:
        return clean(json.loads((Path(root) / 'display.json').read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(root, data):
    value = clean({**load(root), **(data if isinstance(data, dict) else {})})
    path = Path(root) / 'display.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True), encoding='utf-8')
    tmp.replace(path)
    return value


def describe():
    return {'switches': [{'key': key, 'group': group, 'label': label} for key, (group, label, _) in SWITCHES.items()],
            'sizes': [{'key': 'compact', 'label': 'Kompakt'}, {'key': 'normal', 'label': 'Normal'},
                      {'key': 'large', 'label': 'Groß'}]}
