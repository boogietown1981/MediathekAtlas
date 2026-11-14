"""YouTube "Filme & TV" – the films YouTube itself offers free with adverts (0.6.4).

Björn (14.11.2026): besides the curated channels, the free films of YouTube's own film section
("Kostenlos mit Werbung") should be listed.

How the section can be read
---------------------------
* The YouTube Data API v3 does not expose the film section (the "YouTube Movies & TV" channel has
  no readable upload list), and youtube.com itself is not read by MediathekAtlas.
* JustWatch lists every provider's offers with a direct link. Its public GraphQL API is already
  used for JustWatch TV (justwatch.py); YouTube's free films are the offers of the YouTube packages
  with the monetisation types FREE and ADS. The YouTube packages are looked up by name
  (``packages``), with the known short names as fallback, so a renamed package does not break it.
* The link of an offer is the YouTube watch address; its video ID makes the title a normal
  YouTube item ('v.<ID>').

Copy protection
---------------
YouTube delivers its own films with Widevine and only in its own player. Such a title is therefore
a catalogue entry with the link "Bei YouTube ansehen" (``drm=1``): no own player, no offline copy,
nothing is bypassed. Where the Data API says the video may be embedded, the official embedded
player is offered as for every other YouTube title.
"""
from __future__ import annotations

import re
import time
import urllib.parse

import justwatch

REF = 'store:free'
LABEL = 'YouTube Filme & TV – kostenlos mit Werbung'
CHANNEL = 'YouTube Filme & TV'
KNOWN_PACKAGES = ('yfr', 'yot')            # "YouTube Free", "YouTube" (fallback when the lookup fails)
EXCLUDED = re.compile(r'(?i)premium|\btv\b|music|kids')
SHORT = re.compile(r'[a-z0-9]{2,6}')
PAGE = 40
MAX_PAGES = 150
MAX_ITEMS = 5000
REQUEST_GAP = 1.0
PROTECTED = 'Von YouTube nur im eigenen Player angeboten (kopiergeschützt): läuft bei YouTube, kein Offline'

PACKAGES_QUERY = '''query MediathekAtlasPackages($country: Country!, $platform: Platform!) {
  packages(country: $country, platform: $platform) { id clearName packageId shortName } }'''

# Same types and arguments as justwatch.CATALOG_QUERY; the offer filter is written into the query
# (package short names are checked against SHORT before).
TITLES_QUERY = '''query MediathekAtlasYouTubeFree($country: Country!, $language: Language!, $first: Int!,
  $after: String, $filter: TitleFilter) {
  popularTitles(country: $country, filter: $filter, first: $first, sortBy: POPULAR, sortRandomSeed: 0, after: $after) {
    edges { node { id objectType
      content(country: $country, language: $language) {
        title originalReleaseYear shortDescription runtime ageCertification
        posterUrl(profile: S718, format: JPG)
        genres { shortName translation(language: $language) }
        externalIds { imdbId }
        scoring { imdbScore imdbVotes } }
      offers(country: $country, platform: WEB, filter: {packages: [%s], monetizationTypes: [FREE, ADS]}) {
        standardWebURL monetizationType package { shortName clearName } } } }
    pageInfo { endCursor hasNextPage }
    totalCount } }'''


def is_ref(value):
    return str(value or '') == REF


def packages(post):
    """Short names of YouTube's packages at JustWatch (free offers are filtered by monetisation)."""
    try:
        data = justwatch._data(post(PACKAGES_QUERY, {'country': justwatch.COUNTRY, 'platform': 'WEB'}))
    except Exception:
        return list(KNOWN_PACKAGES)
    found = []
    for p in (data.get('packages') or [])[:2000]:
        if not isinstance(p, dict):
            continue
        name, short = str(p.get('clearName') or ''), str(p.get('shortName') or '')
        if name.lower().startswith('youtube') and not EXCLUDED.search(name) and SHORT.fullmatch(short) and short not in found:
            found.append(short)
    return found or list(KNOWN_PACKAGES)


def video_id(url):
    """Video ID from an offer link (youtube.com/watch?v=…, youtu.be/…); '' for anything else."""
    parts = urllib.parse.urlsplit(str(url or ''))
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or host not in ('www.youtube.com', 'youtube.com', 'm.youtube.com', 'youtu.be'):
        return ''
    if host == 'youtu.be':
        candidate = parts.path.strip('/')
    else:
        candidate = urllib.parse.parse_qs(parts.query).get('v', [''])[0] if parts.path == '/watch' else ''
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else ''


def entry_from(node):
    """One free YouTube film from a popularTitles node, or None (no film, no usable link)."""
    if not isinstance(node, dict) or node.get('objectType') != 'MOVIE':
        return None
    content = node.get('content') if isinstance(node.get('content'), dict) else {}
    title = justwatch._text(content.get('title'), 200)
    video = ''
    for offer in (node.get('offers') or [])[:20]:
        if isinstance(offer, dict) and offer.get('monetizationType') in ('FREE', 'ADS'):
            video = video_id(offer.get('standardWebURL'))
            if video:
                break
    if not title or not video:
        return None
    scoring = content.get('scoring') if isinstance(content.get('scoring'), dict) else {}
    imdb = ((content.get('externalIds') or {}).get('imdbId') or '') if isinstance(content.get('externalIds'), dict) else ''
    runtime = justwatch._int(content.get('runtime'), 1, 1440)
    return {'video': video, 'title': title, 'year': justwatch._int(content.get('originalReleaseYear'), 1880, 2100),
            'duration': runtime * 60 if runtime else None, 'rating': justwatch._text(content.get('ageCertification'), 20),
            'genre': justwatch.genres(content), 'summary': justwatch._text(content.get('shortDescription'), 1600),
            'poster': justwatch.poster(content.get('posterUrl')),
            'imdb_id': imdb if re.fullmatch(r'tt\d{5,10}', imdb) else '',
            'imdb_score': justwatch._float(scoring.get('imdbScore'), 0, 10),
            'imdb_votes': justwatch._int(scoring.get('imdbVotes'), 0)}


def load(post=None, gap=None, progress=None):
    """All free YouTube films JustWatch lists for Germany: (entries, without_link, partial)."""
    post = post or justwatch._post
    gap = REQUEST_GAP if gap is None else gap
    shorts = [s for s in packages(post) if SHORT.fullmatch(s)]
    query = TITLES_QUERY % ', '.join('"%s"' % s for s in shorts)
    found, cursor, pages, without, partial = {}, None, 0, 0, False
    while pages < MAX_PAGES and len(found) < MAX_ITEMS:
        variables = {'country': justwatch.COUNTRY, 'language': justwatch.LANGUAGE, 'first': PAGE, 'after': cursor,
                     'filter': {'packages': shorts, 'objectTypes': ['MOVIE'], 'monetizationTypes': ['FREE', 'ADS'],
                                'genres': [], 'excludeGenres': [], 'searchQuery': ''}}
        try:
            data = justwatch._data(post(query, variables))
        except Exception:
            if not found:
                raise
            partial = True          # keep what was read; the next run completes it
            break
        pages += 1
        pt = data.get('popularTitles') or {}
        edges = (pt.get('edges') or [])[:500]
        for edge in edges:
            entry = entry_from((edge or {}).get('node'))
            if entry:
                found.setdefault(entry['video'], entry)
            else:
                without += 1
        if progress:
            progress(len(found))
        info = pt.get('pageInfo') or {}
        cursor = info.get('endCursor') if isinstance(info.get('endCursor'), str) and len(info['endCursor']) < 200 else ''
        if not info.get('hasNextPage') or not cursor or not edges:
            break
        if gap:
            time.sleep(gap)
    return list(found.values()), without, partial


def item(entry, facts, source):
    """Catalogue row (youtube_items) of one free YouTube film; ``facts`` = Data API facts or None."""
    import youtube
    embed = bool(facts and facts.get('playable'))
    return {'id': 'v.' + entry['video'], 'kind': 'movie', 'title': entry['title'], 'path': entry['video'], 'series_id': '',
            'season': None, 'episode': None, 'year': entry['year'],
            'duration': entry['duration'] or (facts or {}).get('duration') or None,
            'rating': entry['rating'] or (facts or {}).get('rating') or '', 'genre': entry['genre'],
            'summary': entry['summary'], 'poster': entry['poster'] or (facts or {}).get('poster') or '',
            'imdb_id': entry['imdb_id'], 'imdb_score': entry['imdb_score'], 'imdb_votes': entry['imdb_votes'],
            'number': None, 'category': CHANNEL, 'raw_title': (facts or {}).get('title') or entry['title'],
            'language': '', 'published': (facts or {}).get('published') or '', 'source_id': source.get('id'),
            'playable': int(embed), 'reason': '' if embed else PROTECTED, 'offline': 0, 'drm': 1,
            'web_url': youtube.video_url(entry['video'])}
