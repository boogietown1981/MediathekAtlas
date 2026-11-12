"""Live-TV by station (0.5.50).

Collects the live channels every source offers and merges them by station, so the
Live-TV tab can list "Das Erste", "ZDF", "3sat" … once, with one play button per provider.

Sources so far:
- ARD/ZDF & Co.: the MediathekView film list carries the broadcasters' official live streams
  under the topic "Livestream" (ListeFilme.THEMA_LIVE in MServer). They are ordinary offers
  in the catalogue database and play through /api/play?offer=<id> (HLS via ffmpeg/native HLS).
- Pluto TV: live channels of the local Pluto catalogue (pluto.channels), played through
  /api/play?pluto=<id> (official stitcher stream incl. adverts).
- Rakuten TV (0.5.51): free FAST channels, plain HLS via /api/play?rakuten=<id>.
- Joyn (0.5.65): the live channels of joyn.de. Joyn plays them in its own player (Widevine as far
  as known); until a recording shows an unprotected stream they only link to joyn.de ('link'
  instead of 'play'). Joyn+ channels are marked.

A new provider only needs a loader returning channel dicts (see _channel) and an entry in
PROVIDERS. Live streams are never stored offline. Nothing here fetches from the network:
everything comes from catalogues that are already stored locally.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata

from catalog import LIVE_TOPICS  # one definition: catalog.mark_live keeps them out of the work scan

PUBLIC = 'Öffentlich-rechtlich'
REGIONAL = 'Regional (ARD)'
GROUP_ORDER = (PUBLIC, REGIONAL)

# Canonical station keys -> display name, group, sort position. Keys are normalised names
# (lower case, letters and digits only). Several spellings map onto one station.
STATIONS = [
    ('daserste', 'Das Erste', PUBLIC, ('ard', 'daserste', 'ardlive', 'erstes', 'ardhd')),
    ('zdf', 'ZDF', PUBLIC, ('zdf', 'zdfhd')),
    ('3sat', '3sat', PUBLIC, ('3sat', 'dreisat')),
    ('arte', 'arte', PUBLIC, ('arte', 'artede', 'artefr')),
    ('phoenix', 'phoenix', PUBLIC, ('phoenix', 'phoenixhd')),
    ('zdfneo', 'ZDFneo', PUBLIC, ('zdfneo', 'neo')),
    ('zdfinfo', 'ZDFinfo', PUBLIC, ('zdfinfo',)),
    ('kika', 'KiKA', PUBLIC, ('kika', 'kikahd')),
    ('one', 'ONE', PUBLIC, ('one', 'ardone', 'einsfestival')),
    ('tagesschau24', 'tagesschau24', PUBLIC, ('tagesschau24', 'tagesschau', 'einsplus')),
    ('ardalpha', 'ARD alpha', PUBLIC, ('ardalpha', 'bralpha', 'alpha')),
    ('dw', 'DW', PUBLIC, ('dw', 'deutschewelle', 'dwdeutsch')),
    ('orf1', 'ORF 1', PUBLIC, ('orf1', 'orfeins')),
    ('orf2', 'ORF 2', PUBLIC, ('orf2',)),
    ('srf1', 'SRF 1', PUBLIC, ('srf1',)),
    ('br', 'BR Fernsehen', REGIONAL, ('br', 'brfernsehen', 'bayerischesfernsehen')),
    ('hr', 'hr-fernsehen', REGIONAL, ('hr', 'hrfernsehen')),
    ('mdr', 'MDR', REGIONAL, ('mdr', 'mdrfernsehen')),
    ('ndr', 'NDR', REGIONAL, ('ndr', 'ndrfernsehen')),
    ('rbb', 'rbb', REGIONAL, ('rbb', 'rbbfernsehen')),
    ('radiobremen', 'Radio Bremen', REGIONAL, ('radiobremen', 'radiobrementv', 'rb')),
    ('sr', 'SR Fernsehen', REGIONAL, ('sr', 'srfernsehen')),
    ('swr', 'SWR', REGIONAL, ('swr', 'swrfernsehen')),
    ('wdr', 'WDR', REGIONAL, ('wdr', 'wdrfernsehen')),
]
_ALIAS = {alias: key for key, _, _, aliases in STATIONS for alias in aliases}
_KNOWN = {key: (name, group, pos) for pos, (key, name, group, _) in enumerate(STATIONS)}
# Regional windows keep their own entry ("BR Nord", "NDR Hamburg") but sort under the station.
_REGIONAL_PREFIXES = sorted((k for k, (_, g, _) in _KNOWN.items() if g == REGIONAL), key=len, reverse=True)

PROVIDERS = (('mediathek', 'ARD, ZDF & Co.'), ('pluto', 'Pluto TV'), ('rakuten', 'Rakuten TV'), ('joyn', 'Joyn'))
PROVIDER_NAMES = dict(PROVIDERS)


def _fold(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(c for c in value if not unicodedata.combining(c))


def station_name(title, channel=''):
    """'Das Erste Livestream' -> 'Das Erste'; 'BR Livestream Nord' -> 'BR Nord'."""
    name = ' '.join(str(title or '').split())
    name = re.sub(r'(?i)\b(?:live[- ]?stream|livestreams?|im livestream|live[- ]?tv|live)\b', ' ', name)
    name = re.sub(r'(?i)\b(?:hd|sd)\b', ' ', name)
    name = ' '.join(re.sub(r'\s*[-–|:·]\s*$', '', re.sub(r'^\s*[-–|:·]\s*', '', name)).split())
    return name or ' '.join(str(channel or '').split()) or 'Sender'


def station_key(name):
    plain = re.sub(r'[^a-z0-9]+', '', _fold(name))
    if plain in _ALIAS:
        return _ALIAS[plain]
    return plain or 'sender'


def _station_info(key, name, fallback_group, regional=False):
    if key in _KNOWN:
        known_name, group, pos = _KNOWN[key]
        return known_name, group, pos
    # Only broadcaster lists contain regional windows; "Bravo" at Pluto is no BR programme.
    for prefix in _REGIONAL_PREFIXES if regional else ():
        if key.startswith(prefix) and len(key) > len(prefix):
            return name, REGIONAL, _KNOWN[prefix][2] + 0.5
    return name, fallback_group, 1000


def _channel(provider, item_id, title, play, *, channel='', group='', logo='', number=None,
             summary='', quality='', link=''):
    name = station_name(title, channel)
    key = station_key(name)
    display, group, pos = _station_info(key, name, group or PROVIDER_NAMES.get(provider, provider), provider == 'mediathek')
    return {'provider': provider, 'provider_name': PROVIDER_NAMES.get(provider, provider), 'id': item_id,
            'title': ' '.join(str(title or '').split())[:200], 'station': display, 'key': key, 'group': group,
            'position': pos, 'logo': logo or '', 'number': number, 'summary': (summary or '')[:400],
            'quality': quality, 'play': play, 'link': link if str(link).startswith('https://') else ''}


# ---------------------------------------------------------------- providers

def mediathek_channels(c):
    """Official live streams of ARD, ZDF & Co. from the MediathekView film list (topic 'Livestream')."""
    marks = ','.join('?' * len(LIVE_TOPICS))
    rows = c.execute('SELECT o.id,o.payload FROM works w JOIN offers o ON o.work_id=w.id '
                     'WHERE w.topic IN (%s) AND o.active=1 ORDER BY o.rank DESC' % marks, LIVE_TOPICS).fetchall()
    out, seen = [], set()
    for offer_id, payload in rows:
        try:
            row = json.loads(payload)
        except ValueError:
            continue
        url = row.get('url_video_hd') or row.get('url_video') or row.get('url_video_low') or ''
        if not re.match(r'(?i)^https?://', str(url)):
            continue
        item = _channel('mediathek', offer_id, row.get('title'), {'offer': offer_id}, channel=row.get('channel'),
                        group=PUBLIC, summary=row.get('description') or '',
                        quality='HLS' if re.search(r'(?i)\.m3u8', url) else 'Stream')
        if not item['station'] or item['station'] == 'Sender':
            item['station'] = ' '.join(str(row.get('channel') or 'Sender').split())
        # The same stream may appear more than once (e.g. HD and SD lists): keep the best ranked.
        ident = (item['key'], item['title'].casefold())
        if ident in seen:
            continue
        seen.add(ident)
        item['broadcaster'] = ' '.join(str(row.get('channel') or '').split())
        out.append(item)
    return out


def pluto_channels(root):
    import pluto
    out = []
    for row in pluto.channels(root):
        out.append(_channel('pluto', row['id'], row['title'], {'pluto': row['id']},
                            group=row.get('category') or row.get('genre') or 'Pluto TV',
                            logo=row.get('poster') or '', number=row.get('number'),
                            summary=row.get('summary') or '', quality='mit Werbung'))
    return out


def rakuten_channels(root):
    """Free Rakuten TV live channels (0.5.51): plain HLS via /api/play?rakuten=<id>, with adverts."""
    import rakuten
    return [_channel('rakuten', row['id'], row['title'], {'rakuten': row['id']},
                     group=row.get('category') or 'Rakuten TV', logo=row.get('poster') or '',
                     number=row.get('number'), summary=row.get('summary') or '', quality='mit Werbung')
            for row in rakuten.channels(root)]


def joyn_channels(root):
    """Joyn live channels (0.5.65): link to joyn.de only (no playback released, see joyn.py)."""
    import joyn
    out = []
    for row in joyn.channels(root):
        plus = row.get('offer') == 'plus'
        out.append(_channel('joyn', row['id'], row['title'], None, group=row.get('genre') or 'Joyn',
                            logo=row.get('poster') or '', summary=row.get('summary') or '',
                            quality=' · '.join(x for x in ('Joyn+' if plus else 'kostenlos', row.get('quality') or '',
                                                           'bei Joyn ansehen') if x),
                            link=row.get('web_url') or ''))
    return out


BUDGET = 4.0     # seconds one provider may take before the tab shows its last known channels
_LAST = {}       # provider -> channels of the last complete answer
_LAST_LOCK = threading.Lock()


def channels(c, root, budget=None):
    """All live channels of all providers; a broken or slow provider never hides the others.

    0.5.67 (Björn, 12.11.2026: the tab stayed at "Live-Sender werden geladen …" with 0.5.61): the
    platform catalogues are read side by side with a time limit. A provider that does not answer in
    time (its database is busy while the catalogue is loaded) is shown with its last known channels
    and named in the status line instead of holding back the whole tab."""
    budget = BUDGET if budget is None else budget
    found, errors, results = [], {}, {}
    loaders = (('pluto', lambda: pluto_channels(root)), ('rakuten', lambda: rakuten_channels(root)),
               ('joyn', lambda: joyn_channels(root)))

    def work(key, loader):
        try:
            results[key] = ('ok', loader())
        except Exception as exc:  # local database problems are reported per provider
            results[key] = ('error', str(exc)[:200] or exc.__class__.__name__)

    threads = [(key, threading.Thread(target=work, args=(key, loader), daemon=True, name='live_tv_' + key))
               for key, loader in loaders]
    for _, thread in threads:
        thread.start()
    try:   # the film list lives in the caller's database connection, so it is read here
        found.extend(mediathek_channels(c))
    except Exception as exc:
        errors['mediathek'] = str(exc)[:200] or exc.__class__.__name__
    deadline = time.monotonic() + budget
    for key, thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
        state, value = results.get(key, ('late', None))
        if state == 'ok':
            with _LAST_LOCK:
                _LAST[key] = value
            found.extend(value)
            continue
        with _LAST_LOCK:
            known = list(_LAST.get(key) or [])
        found.extend(known)
        errors[key] = (('antwortet gerade nicht (Katalog wird vermutlich geladen)' if state == 'late' else value)
                       + (' · letzter bekannter Stand: %d Sender' % len(known) if known else ''))
    return found, errors


def _group_rank(group):
    return (GROUP_ORDER.index(group), '') if group in GROUP_ORDER else (len(GROUP_ORDER), _fold(group))


def overview(c, root, query='', provider='', group=''):
    """Live channels merged by station, grouped and sorted for the Live-TV tab."""
    found, errors = channels(c, root)
    counts = {key: 0 for key, _ in PROVIDERS}
    for ch in found:
        counts[ch['provider']] = counts.get(ch['provider'], 0) + 1
    stations = {}
    for ch in found:
        st = stations.setdefault(ch['key'], {'key': ch['key'], 'name': ch['station'], 'group': ch['group'],
                                             'position': ch['position'], 'logo': '', 'number': None,
                                             'summary': '', 'sources': []})
        # A known public station keeps its group even if another provider files it elsewhere.
        if _group_rank(ch['group']) < _group_rank(st['group']):
            st['group'], st['position'] = ch['group'], ch['position']
        st['logo'] = st['logo'] or ch['logo']
        st['summary'] = st['summary'] or ch['summary']
        if st['number'] is None and ch['number'] is not None:
            st['number'] = ch['number']
        st['sources'].append({k: ch[k] for k in ('provider', 'provider_name', 'id', 'title', 'quality', 'play', 'link')})
    items = list(stations.values())
    q = _fold(query).strip()[:100]
    if q:
        items = [s for s in items if q in _fold(s['name']) or q in _fold(s['group'])
                 or any(q in _fold(x['title']) for x in s['sources'])]
    if provider:
        items = [s for s in items if any(x['provider'] == provider for x in s['sources'])]
    groups = {}
    for s in items:
        groups[s['group']] = groups.get(s['group'], 0) + 1
    if group:
        items = [s for s in items if s['group'] == group]
    items.sort(key=lambda s: (_group_rank(s['group']), s['position'],
                              s['number'] if s['number'] is not None else 1e9, _fold(s['name'])))
    for s in items:
        s['sources'].sort(key=lambda x: [k for k, _ in PROVIDERS].index(x['provider'])
                          if x['provider'] in counts else 99)
        s.pop('position', None)
    return {'stations': items, 'total': len(items),
            'groups': [{'name': g, 'count': n} for g, n in sorted(groups.items(), key=lambda kv: _group_rank(kv[0]))],
            'providers': [{'key': k, 'name': n, 'channels': counts.get(k, 0), 'error': errors.get(k, '')}
                          for k, n in PROVIDERS]}


def summary(c, root):
    """Counters for the diagnosis export; no titles or addresses."""
    found, errors = channels(c, root)
    return {'channels': {k: sum(1 for ch in found if ch['provider'] == k) for k, _ in PROVIDERS},
            'stations': len({ch['key'] for ch in found}), 'errors': errors}


def is_live_topic(topic):
    return str(topic or '').strip() in LIVE_TOPICS
