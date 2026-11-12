"""One title page for every film portal (0.5.42).

Björn (12.11.2026): the details of Netzkino, Pluto TV and JustWatch TV looked different and the
JustWatch dialog was broken; "egal bei welcher Plattform durchgängig … die spezifischen
Informationen je Anbieter nicht verlieren … Backend und Frontend gleich". The catalogue and the
platform tabs therefore open the same title page as the Mediathek works (web/titleview.js hero:
poster, facts line with ★ rating, actions, overview, info list, cast). This module turns the three
detail sources into one model:

* common fields: kind, title, year, duration, age rating, categories (portal_reference), rating,
  description, poster, cast/directors/writers (portal facts first, then the reference report);
* ``provider_facts``: everything only that portal publishes (its genres/categories, access notes,
  original title, live-channel number, links …), shown in the section "Angaben von <Anbieter>";
* ``reference``: the IMDb/TVDB/TMDB/OMDb/Wikidata report (same for all sources);
* ``offline``/``playable``: what the page may offer (30 days offline, player, official page).
"""
from __future__ import annotations

PROVIDERS = {'netzkino': 'Netzkino', 'pluto': 'Pluto TV', 'justwatch': 'JustWatch TV'}
OFFLINE_DAYS = 30
KIND_LABEL = {'movie': 'Film', 'series': 'Serie', 'episode': 'Folge', 'channel': 'Live-Sender'}


def _names(value, limit=24):
    out = []
    for v in value or []:
        name = v.get('name') if isinstance(v, dict) else v
        name = ' '.join(str(name or '').split())
        if name and name not in out:
            out.append(name)
    return out[:limit]


def _text(value, limit=4000):
    return ' '.join(str(value or '').split())[:limit]


def _https(url):
    url = str(url or '')
    return url if url.startswith('https://') else ''


def _year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1880 <= year <= 2100 else None


def _base(source, item_id, report):
    import portal_reference
    meta = (report or {}).get('metadata') or {}
    return {'source': source, 'provider': PROVIDERS[source], 'id': item_id, 'kind': 'movie', 'title': '',
            'series': None, 'season': None, 'episode': None, 'year': None, 'duration': None, 'age_rating': '',
            'description': '', 'poster': '', 'fanart': _https(meta.get('backdrop')),
            'categories': [], 'rating': portal_reference.rating(report),
            'cast': _names(meta.get('cast')), 'directors': _names(meta.get('directors')),
            'writers': _names(meta.get('writers')), 'country': _text(meta.get('country'), 80),
            'language': _text(meta.get('original_language'), 80), 'original_title': _text(meta.get('original_title'), 200),
            'provider_facts': [], 'reference': report or {'status': 'unchecked'},
            'playable': False, 'web_url': '', 'offline': {'allowed': False, 'days': OFFLINE_DAYS},
            'notes': []}


def _fill_from_reference(model, report):
    meta = (report or {}).get('metadata') or {}
    if not model['description']:
        model['description'] = _text(meta.get('description'))
    if not model['poster']:
        model['poster'] = _https(meta.get('poster'))
    if not model['year']:
        model['year'] = _year(meta.get('year'))
    if not model['duration'] and isinstance(meta.get('duration_seconds'), (int, float)):
        model['duration'] = int(meta['duration_seconds'])


def _portal(root, source, item_id):
    import portal_reference
    mod = __import__(source)
    data = mod.item(root, item_id)
    it, parent, report = data.get('item') or {}, data.get('series'), data.get('reference') or {}
    m = _base(source, item_id, report)
    m.update(kind=it.get('kind') or 'movie', title=_text(it.get('title'), 200), year=_year(it.get('year')),
             duration=it.get('duration') or None, age_rating=_text(it.get('rating'), 20),
             description=_text(it.get('summary')), poster=_https(it.get('poster')),
             season=it.get('season'), episode=it.get('episode'))
    m['categories'] = [c for c in (it.get('categories') or portal_reference.categories(it.get('genre'), report))
                       if c != portal_reference.UNKNOWN]
    if it.get('score'):
        m['rating'] = it['score']
    if parent:
        m['series'] = {'id': parent.get('id'), 'title': _text(parent.get('title'), 200)}
    if m['kind'] == 'channel':
        m['playable'] = True
    elif m['kind'] != 'series':
        m['playable'] = it.get('playable') not in (0, False)
        # 0.5.48: JustWatch releases some titles only at night (youth protection): reserve the download.
        night = source == 'justwatch' and not m['playable']
        m['offline'] = {'allowed': m['playable'] or night, 'days': OFFLINE_DAYS, 'night': night}
    m['web_url'] = _https(it.get('web_url'))
    facts = m['provider_facts']
    if it.get('genre'):
        facts.append([PROVIDERS[source] + '-Genre', _text(it['genre'], 200)])
    if it.get('category'):
        facts.append([PROVIDERS[source] + '-Kategorie', _text(it['category'], 200)])
    if it.get('number'):
        facts.append(['Sendernummer', str(it['number'])])
    if it.get('imdb_id'):
        facts.append(['IMDb-ID laut ' + PROVIDERS[source], _text(it['imdb_id'], 20)])
    if it.get('imdb_score') is not None and source == 'justwatch':
        votes = it.get('imdb_votes')
        facts.append(['IMDb-Bewertung laut JustWatch', ('%s / 10' % it['imdb_score']) + (' · %s Stimmen' % votes if votes else '')])
    if source == 'justwatch':
        facts.append(['Paket', 'JustWatch TV Free (mit Werbung)'])
        facts.append(['Stream', 'freigegeben' if m['playable'] else 'derzeit nicht freigegeben (oft Jugendschutz: nur 0 bis 6 Uhr) – nachts offline speicherbar'])
    if source == 'pluto':
        facts.append(['Angebot', 'Pluto TV, kostenlos mit Werbung'])
    _fill_from_reference(m, report)
    return m


def _netzkino(root, item_id):
    import netzkino_details, netzkino_enrichment, portal_reference
    try:
        report = netzkino_enrichment.cached(root, item_id)
    except Exception:
        report = {'status': 'unchecked'}
    data = netzkino_details.get(root, item_id)
    d = data.get('details') or {}
    m = _base('netzkino', item_id, report)
    m.update(title=_text(d.get('title'), 200), year=_year(d.get('year')),
             duration=d.get('duration_seconds') or None,
             age_rating=('FSK %s' % d['fsk']) if d.get('fsk') not in (None, '') else '',
             description=_text(d.get('description')), poster=_https(d.get('poster')),
             playable=True, web_url=_https(data.get('page_url')))
    m['offline'] = {'allowed': True, 'days': OFFLINE_DAYS}
    m['categories'] = [c for c in portal_reference.categories(d.get('genres'), report) if c != portal_reference.UNKNOWN]
    # Netzkino's own credits are more complete than most references.
    for key in ('cast', 'directors', 'writers'):
        if d.get(key):
            m[key] = _names(d[key])
    m['country'] = _text(d.get('country'), 80) or m['country']
    m['language'] = _text(d.get('original_language'), 80) or m['language']
    m['original_title'] = _text(d.get('original_title'), 200) or m['original_title']
    facts = m['provider_facts']
    if d.get('genres'):
        facts.append(['Netzkino-Genres', ', '.join(_names(d['genres']))])
    if d.get('access_types'):
        facts.append(['Zugangshinweis', ', '.join(_names(d['access_types']))])
    facts.append(['Datenstand', ('Detailabruf eingeschränkt (%s)' % data['error_type']) if data.get('error_type')
                  else ('zwischengespeichert' if data.get('cached') else 'aktuell geladen')])
    m['notes'].append('Werkidentität und Wiedergaberechte sind nicht unabhängig bestätigt.')
    # 0.5.45: an explicit episode ("Serie - Folge 3 …") links back to its grouped series page.
    import netzkino
    cls = netzkino.classify_media({'title': d.get('title') or ''})
    if cls.get('media_type') == 'episode' and netzkino.series_id(cls.get('series_title')):
        m.update(kind='episode', season=cls.get('season'), episode=cls.get('episode'),
                 title=_text(cls.get('episode_title'), 200) or m['title'],
                 series={'id': netzkino.series_id(cls['series_title']), 'title': _text(cls['series_title'], 200)})
    _fill_from_reference(m, report)
    return m


def _episode(source, e, series_poster=''):
    """One episode row, the same for every portal (0.5.45)."""
    def num(v, hi):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        return v if 0 <= v <= hi else None
    title = _text(e.get('episode_title') or e.get('title'), 200)
    playable = e.get('playable') not in (0, False)
    return {'id': str(e.get('id') or ''), 'title': title, 'season': num(e.get('season'), 999),
            'episode': num(e.get('episode'), 9999), 'duration': e.get('duration') or None,
            'year': _year(e.get('year')), 'summary': _text(e.get('summary') or e.get('description'), 1200),
            'poster': _https(e.get('poster')) or series_poster, 'playable': playable,
            'offline': playable or source == 'justwatch', 'night': source == 'justwatch' and not playable,
            'web_url': _https(e.get('web_url'))}


def _sort_episodes(rows):
    return sorted(rows, key=lambda e: (e['season'] is None, e['season'] or 0, e['episode'] is None, e['episode'] or 0, e['title']))


def _netzkino_series(root, key):
    """Netzkino series are grouped from single titles (netzkino.grouped_catalog)."""
    import netzkino
    data = netzkino.grouped_catalog(root, view='episodes', series_key=key, limit=1000)
    series = data.get('series') or {}
    if not series:
        raise ValueError('Netzkino-Serie nicht im Katalog; bitte Katalog neu laden')
    m = _base('netzkino', key, {'status': 'unchecked'})
    poster = _https(series.get('poster'))
    m.update(kind='series', title=_text(series.get('title'), 200), year=_year(series.get('year')), poster=poster,
             categories=[c for c in series.get('categories') or [] if c != 'Unbekannt'])
    items = data.get('items') or []
    m['description'] = next((_text(e.get('summary')) for e in items if e.get('summary')), '')
    m['episodes'] = _sort_episodes([_episode('netzkino', e, poster) for e in items])
    facts = m['provider_facts']
    if series.get('genres'):
        facts.append(['Netzkino-Genres', _text(series['genres'], 200)])
    facts.append(['Folgen bei Netzkino', str(len(items))])
    gaps = ['Staffel %s: Folge %s' % (g.get('season'), ', '.join(str(x) for x in g.get('episodes') or []))
            for g in series.get('numbering_gaps') or []]
    if gaps:
        facts.append(['Fehlende Folgennummern', '; '.join(gaps)])
    m['notes'].append('Netzkino führt Serienfolgen als einzelne Titel; MediathekAtlas fasst sie anhand der Folgentitel zusammen.')
    return m


def model(root, source, item_id):
    if source not in PROVIDERS:
        raise ValueError('Unbekannte Plattform')
    if source == 'netzkino' and str(item_id).startswith('series-'):
        m = _netzkino_series(root, item_id)
    else:
        m = _netzkino(root, item_id) if source == 'netzkino' else _portal(root, source, item_id)
        if m['kind'] == 'series':
            # Episodes belong on the series page, the same for every portal (Björn, 12.11.2026).
            mod = __import__(source)
            data = mod.episodes(root, item_id)
            m['episodes'] = _sort_episodes([_episode(source, e, m['poster']) for e in data.get('items') or []])
            if data.get('error'):
                m['notes'].append('Folgen konnten nicht aktualisiert werden: ' + _text(data['error'], 200))
    if not m['title']:
        raise ValueError('Titel nicht im Katalog; bitte Katalog neu laden')
    m['kind_label'] = KIND_LABEL.get(m['kind'], 'Titel')
    if m['original_title'] and m['original_title'] != m['title']:
        m['provider_facts'].insert(0, ['Originaltitel', m['original_title']])
    return m
