"""Cast photos for title pages (0.5.80).

Björn (12.11.2026) wanted the cast on the title pages with photos, like a media server.
The names come from IMDb (offline dataset, with ``nm`` person ids), from the portals or from
the reference report. Photos come from TMDB only (``image.tmdb.org``, already an allowed
artwork host) and only when a TMDB key is configured.

Identity rules, because a wrong face is worse than none:

1. The title's own credits: with a TMDB id (directly, via the IMDb/TVDB id or one unambiguous
   search hit with a matching year), ``movie/<id>/credits`` or ``tv/<id>/aggregate_credits``
   give name -> photo (and the role, if the page has none).
2. A person with an IMDb ``nm`` id is looked up exactly (``find/nm…``).
3. There is no blind name search: "Peter Müller" without a title context stays without photo.

Answers are cached in ``people.sqlite`` in the data folder (hits 90 days, misses 14 days), so a
title page asks TMDB at most once per person and period. Nothing here runs without a request
from a title page.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import unicodedata

IMAGE = 'https://image.tmdb.org/t/p/w185'
HIT_TTL = 90 * 86400
MISS_TTL = 14 * 86400
MAX_PEOPLE = 24
MAX_EXACT = 12          # exact nm look-ups per request (the rest follows on the next opening)
NM = re.compile(r'^nm\d{5,10}$')
TT = re.compile(r'^tt\d{5,10}$')
_LOCK = threading.Lock()


def fold(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return re.sub(r'[^a-z0-9]+', '', ''.join(c for c in value if not unicodedata.combining(c)))


def _db(root):
    db = sqlite3.connect(str(root / 'people.sqlite'), timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS photos(key TEXT PRIMARY KEY, url TEXT, role TEXT, checked REAL)')
    return db


def _cached(db, key, now):
    row = db.execute('SELECT url,role,checked FROM photos WHERE key=?', (key,)).fetchone()
    if not row:
        return None
    url, role, checked = row
    if now - (checked or 0) > (HIT_TTL if url else MISS_TTL):
        return None
    return {'url': url or '', 'role': role or ''}


def _store(db, key, url, role, now):
    db.execute('INSERT OR REPLACE INTO photos VALUES(?,?,?,?)', (key, url or '', role or '', now))


def _photo(path):
    return IMAGE + path if isinstance(path, str) and re.fullmatch(r'/[A-Za-z0-9._-]+\.(?:jpg|jpeg|png|webp)', path) else ''


def _people(raw):
    out, seen = [], set()
    for p in raw or []:
        if isinstance(p, str):
            p = {'name': p}
        if not isinstance(p, dict):
            continue
        name = ' '.join(str(p.get('name') or '').split())[:120]
        if not name or fold(name) in seen:
            continue
        seen.add(fold(name))
        nm = str(p.get('imdb_id') or '').strip()
        out.append({'name': name, 'imdb_id': nm if NM.match(nm) else ''})
        if len(out) >= MAX_PEOPLE:
            break
    return out


def _year(value):
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1880 <= year <= 2100 else None


def resolve_title(tmdb, context):
    """TMDB id and kind ('movie'/'tv') of the title, or (None, kind)."""
    kind = 'tv' if context.get('kind') in ('series', 'tv', 'episode') else 'movie'
    provider, ref = context.get('provider') or '', str(context.get('reference_id') or '')
    if provider == 'TMDB' and ref.isdigit():
        return int(ref), kind
    if str(context.get('tmdb_id') or '').isdigit():
        return int(context['tmdb_id']), kind
    imdb = str(context.get('imdb_id') or '')
    if not TT.match(imdb) and provider in ('IMDb Offline', 'OMDb', 'IMDb') and TT.match(ref):
        imdb = ref
    lookups = []
    if TT.match(imdb):
        lookups.append((imdb, 'imdb_id'))
    if provider == 'TVDB' and ref.isdigit():
        lookups.append((ref, 'tvdb_id'))
    for ident, source in lookups:
        hits = tmdb('find/' + ident, {'external_source': source})
        for key, k in (('movie_results', 'movie'), ('tv_results', 'tv')):
            if len(hits.get(key) or []) == 1:
                return hits[key][0]['id'], k
    title, year = ' '.join(str(context.get('title') or '').split()), _year(context.get('year'))
    if not title or not year:   # a search without a year is too ambiguous for faces
        return None, kind
    found = tmdb('search/' + kind, {'query': title}).get('results') or []
    wanted = fold(title)
    hits = [h for h in found if wanted in (fold(h.get('title') or h.get('name')), fold(h.get('original_title') or h.get('original_name')))
            and (_year(h.get('release_date') or h.get('first_air_date')) or 0) in (year - 1, year, year + 1)]
    return (hits[0]['id'], kind) if len(hits) == 1 else (None, kind)


def credits(tmdb, tmdb_id, kind):
    """folded name -> (photo url, role) from the title's own credits."""
    out = {}
    if kind == 'tv':
        data = tmdb('tv/%d/aggregate_credits' % int(tmdb_id), None)
        for p in data.get('cast') or []:
            roles = [r.get('character') for r in p.get('roles') or [] if r.get('character')]
            out.setdefault(fold(p.get('name')), (_photo(p.get('profile_path')), ', '.join(roles[:2])))
    else:
        data = tmdb('movie/%d/credits' % int(tmdb_id), None)
        for p in data.get('cast') or []:
            out.setdefault(fold(p.get('name')), (_photo(p.get('profile_path')), p.get('character') or ''))
    for p in data.get('crew') or []:
        out.setdefault(fold(p.get('name')), (_photo(p.get('profile_path')), ''))
    return out


def lookup(root, key, people, context=None, tmdb=None):
    """Photos for the given people: {'photos': {name: url}, 'roles': {name: role}, 'configured': bool}."""
    people = _people(people)
    context = context if isinstance(context, dict) else {}
    result = {'photos': {}, 'roles': {}, 'files': {}, 'configured': bool(key), 'source': 'TMDB'}
    if not people or not key:
        return result
    try:
        return _lookup(root, key, people, context, tmdb, result)
    finally:
        # 0.6.55: the page loads photos through /api/cast-photo (stored locally), the remote URL stays for older pages.
        result['files'] = {n: file_name(u) for n, u in result['photos'].items() if file_name(u)}


def _lookup(root, key, people, context, tmdb, result):
    if tmdb is None:
        import core

        def tmdb(path, params):
            return core.tmdb(path, key, params)
    now = time.time()
    title_key = 'title:%s:%s:%s' % (fold(context.get('title'))[:80], _year(context.get('year')) or '',
                                    context.get('reference_id') or context.get('imdb_id') or '')
    with _LOCK:
        db = _db(root)
        try:
            missing = []
            for p in people:
                hit = _cached(db, p['imdb_id'] or (title_key + ':' + fold(p['name'])), now)
                if hit is None:
                    missing.append(p)
                elif hit['url']:
                    result['photos'][p['name']] = hit['url']
                    if hit['role']:
                        result['roles'][p['name']] = hit['role']
            if not missing:
                return result
            errors = []
            known = {}
            try:
                tmdb_id, kind = resolve_title(tmdb, context)
                if tmdb_id:
                    known = credits(tmdb, tmdb_id, kind)
            except Exception as exc:   # no network, quota: the page keeps its initials
                errors.append(exc.__class__.__name__)
            exact = 0
            for p in missing:
                url, role = known.get(fold(p['name']), ('', ''))
                if not url and p['imdb_id'] and exact < MAX_EXACT and not errors:
                    exact += 1
                    try:
                        hits = tmdb('find/' + p['imdb_id'], {'external_source': 'imdb_id'}).get('person_results') or []
                        if len(hits) == 1:
                            url = _photo(hits[0].get('profile_path'))
                    except Exception as exc:
                        errors.append(exc.__class__.__name__)
                        break
                if errors and not url:
                    continue   # not cached: the next opening tries again
                # A role belongs to this title, so a person-wide (nm) entry keeps only the photo.
                _store(db, p['imdb_id'] or (title_key + ':' + fold(p['name'])), url, '' if p['imdb_id'] else role, now)
                if url:
                    result['photos'][p['name']] = url
                    if role:
                        result['roles'][p['name']] = role
            db.commit()
            if errors:
                result['error'] = errors[0]
            return result
        finally:
            db.close()


# --- 0.6.55: photos stored locally ------------------------------------------------------------
# Björn's list item "Besetzung mit Fotos": the title page loads the pictures from MediathekAtlas
# itself (/api/cast-photo), not from image.tmdb.org. The first view downloads one photo (w185,
# ~10-20 KB), later views and offline use read the file from ``people-photos/`` in the data
# folder. The folder has a size budget; the least recently shown photos go first.
PHOTO_DIR = 'people-photos'
BUDGET = 48 * 1024 * 1024      # ~3000 faces
MAX_PHOTO = 1024 * 1024
FILE = re.compile(r'^[A-Za-z0-9_-]{1,64}\.(?:jpg|jpeg|png|webp)$')
FAIL_TTL = 30 * 60             # a photo TMDB did not deliver is not asked again for 30 min
_FAILED = {}
_FILE_LOCK = threading.Lock()


def file_name(url):
    """'abc.jpg' for a photo URL produced by _photo(), otherwise ''."""
    url = str(url or '')
    if not url.startswith(IMAGE + '/'):
        return ''
    name = url[len(IMAGE) + 1:]
    return name if FILE.match(name) else ''


def _image_type(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def _known(root, name):
    """Only photos that a lookup handed out are fetched (no free proxy for image.tmdb.org)."""
    path = root / 'people.sqlite'
    if not path.exists():
        return False
    db = sqlite3.connect(str(path), timeout=10)
    try:
        return bool(db.execute('SELECT 1 FROM photos WHERE url=? LIMIT 1', (IMAGE + '/' + name,)).fetchone())
    finally:
        db.close()


def prune(folder, budget=None):
    """Deletes the least recently shown photos until the folder is below 80 % of the budget."""
    budget = BUDGET if budget is None else budget
    try:
        files = [(f.stat().st_mtime, f.stat().st_size, f) for f in folder.iterdir() if f.is_file()]
    except OSError:
        return 0
    total = sum(size for _, size, _ in files)
    if total <= budget:
        return 0
    removed = 0
    for _, size, f in sorted(files, key=lambda x: x[0]):
        if total <= budget * 0.8:
            break
        try:
            f.unlink()
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


def photo(root, name, fetch=None, budget=None):
    """(bytes, content type) of one cast photo from the local store, downloaded once; None if unavailable."""
    if not FILE.match(str(name or '')):
        return None
    folder = root / PHOTO_DIR
    target = folder / name
    try:
        if target.is_file():
            data = target.read_bytes()
            kind = _image_type(data)
            if kind:
                try:
                    os.utime(target)   # shown again: stays when the budget prunes
                except OSError:
                    pass
                return data, kind
    except OSError:
        pass
    now = time.time()
    if now - _FAILED.get(name, 0) < FAIL_TTL or not _known(root, name):
        return None
    if fetch is None:
        import core

        def fetch(url):
            with core.open_url(url, timeout=15) as r:
                return r.read(MAX_PHOTO + 1)
    try:
        data = fetch(IMAGE + '/' + name)
    except Exception:
        _FAILED[name] = now
        if len(_FAILED) > 2000:
            _FAILED.clear()
        return None
    kind = _image_type(data or b'')
    if not kind or len(data) > MAX_PHOTO:
        _FAILED[name] = now
        return None
    with _FILE_LOCK:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / ('.' + name + '.part')
            tmp.write_bytes(data)
            os.replace(tmp, target)
            prune(folder, budget)
        except OSError:
            pass   # read-only or full disk: the photo is still shown this time
    return data, kind


def store_stats(root):
    """Photo store for diagnostics and settings: {'files', 'bytes', 'budget'}."""
    folder = root / PHOTO_DIR
    count = size = 0
    try:
        for f in folder.iterdir():
            if f.is_file() and not f.name.startswith('.'):
                count += 1
                size += f.stat().st_size
    except OSError:
        pass
    return {'files': count, 'bytes': size, 'budget': BUDGET}
