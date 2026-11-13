"""Werkerkennung für Archive.org-Uploads (0.5.82), aus Archive Media übernommen.

An Archive.org item is an upload, not a work: the same film exists in several uploads, a series
is spread over many of them, the title carries upload counters and release tags, and the "year"
is often the upload date. Until now MediathekAtlas kept the uploads as a plain list
(portal_sources.portal_items). This module puts works on top of them:

- search title for the databases (ArchiveMedia work_title_queries.provider_query_title):
  release tags, upload counters and episode markers are removed, the stored upload stays as it is,
- one work per film (title and year) or series (title), uploads of one series belong together
  (ArchiveMedia series_merge: equal title; after the check also equal reference id),
- the same reference check as every other platform (portal_enrichment over core.candidates,
  shared through reference_share),
- year repair (ArchiveMedia year_repair): when the upload's year finds nothing, the check runs
  once more without it; a unique hit supplies the year of the work,
- anime without a hit are asked at AniList (ArchiveMedia anime_match: unique near-exact title only).

Everything lives in ``archive_works.sqlite3``; the uploads are read from the main database and
never changed. Nothing here allows or starts a download.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

import portal_enrichment as engine
from vendor.archive_portals import anime_match
from vendor.archive_portals import catalog_identity as identity_rules
from vendor.archive_portals import catalog_repair as repair_rules

DB_NAME = 'archive_works.sqlite3'
SOURCE = 'internet_archive'
VALID_ID = re.compile(r'aw[0-9a-f]{16}')
ANIME_TTL = 30 * 86400
ANIME_RETRY = 6 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_works(
 id TEXT PRIMARY KEY,
 kind TEXT NOT NULL,
 title TEXT NOT NULL,
 year INTEGER,
 duration REAL,
 genre TEXT NOT NULL DEFAULT '',
 summary TEXT NOT NULL DEFAULT '',
 poster TEXT NOT NULL DEFAULT '',
 series_id TEXT,
 seen REAL NOT NULL DEFAULT 0,
 year_claim INTEGER,
 year_state INTEGER NOT NULL DEFAULT 0,
 anime INTEGER NOT NULL DEFAULT 0,
 uploads INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS archive_work_items(
 item_id TEXT PRIMARY KEY,
 work_id TEXT NOT NULL,
 season INTEGER,
 episode INTEGER);
CREATE INDEX IF NOT EXISTS archive_work_items_work ON archive_work_items(work_id);
CREATE TABLE IF NOT EXISTS archive_anime(
 work_id TEXT PRIMARY KEY,
 checked REAL NOT NULL,
 title TEXT NOT NULL,
 payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS archive_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
# year_state: 0 = year of the upload not questioned yet, 1 = questioned, the year stays,
# 2 = the year of the upload found nothing, the work is matched without it (year repair).

ARCHIVE_COUNTER = re.compile(r'^0{2,}\d{2,4}[\s._-]+(.+)$')
SPLIT_COUNTER = re.compile(r'^(?:(?:0|[1-9]\d{0,2})[\s._-]+){1,3}\d{1,4}(?=[A-ZÀ-Þ])(.+)$')
SEASON = re.compile(r'(?i)\b(?:season|staffel|series)[\s._-]*(\d{1,2})\b')
YEAR_TAIL = re.compile(r'\s*[\[(]\s*((?:18|19|20)\d{2})\s*[\])]\s*$')
TECH_TAIL = re.compile(r'(?i)\s*[\[(]?\b(?:1080p|720p|480p|2160p|4k|x264|x265|h\.?264|h\.?265|hevc|blu-?ray|bdrip|dvdrip|vhsrip|webrip|web-dl|hdtv|'
                       r'full movie|ganzer film|complete series|komplette serie|german|deutsch|english|dub|sub(?:bed)?|remastered)\b[\])]?\s*$')
ANIME_HINT = re.compile(r'(?i)\b(?:anime|ova|oav|manga|fansub|sub(?:bed)? ?ita|dual audio)\b')


def connect(root):
    db = sqlite3.connect(Path(root) / DB_NAME, timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _meta(db, key, default=''):
    row = db.execute('SELECT value FROM archive_meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


SPEC = engine.Spec(name='Internet Archive', key='archive', items='archive_works', checks='archive_reference_checks',
                   connect=connect, valid_id=lambda v: bool(VALID_ID.fullmatch(v)),
                   last_success=lambda db: _meta(db, 'last_success', '0'))


def title_key(value):
    return anime_match.folded(value)


def query_title(value):
    """ArchiveMedia provider_query_title: release tags and upload counters away, nothing else."""
    original = str(value or '').strip()
    clean = repair_rules.release_title(original)
    match = ARCHIVE_COUNTER.match(clean) or SPLIT_COUNTER.match(clean)
    if match and identity_rules.meaning_title(match.group(1)):
        return match.group(1).strip()
    return clean


def parse(raw_title, year=None):
    """Upload title -> what the databases are asked: title, year, film or series, episode marks."""
    title = identity_rules.normalize_title(query_title(raw_title))
    season = episode = None
    kind = 'movie'
    mark = identity_rules.EPISODE.search(title)
    if mark:
        try:
            season = int(mark.group('s') or mark.group('s2') or 1)
            episode = int(mark.group('e') or mark.group('e2') or mark.group('e3'))
        except (TypeError, ValueError):
            season = episode = None
    head = title[:mark.start()] if mark else title
    found = SEASON.search(head if mark else title)
    if found:
        season = int(found.group(1))
        head = (head if mark else title)[:found.start()]
    if (mark or found) and identity_rules.meaning_title(head.strip(' -._:,(')):
        # Only a labelled episode or season makes a series; the part before the label is its name.
        kind, title = 'series', head.strip(' -._:,([')
    else:
        season = episode = None
    claimed = None
    for _ in range(4):
        tail = YEAR_TAIL.search(title)
        if tail and title[:tail.start()].strip(' -._'):
            claimed = claimed or int(tail.group(1))
            title = title[:tail.start()].strip(' -._')
            continue
        tech = TECH_TAIL.search(title)
        if tech and identity_rules.meaning_title(title[:tech.start()].strip(' -._')):
            title = title[:tech.start()].strip(' -._')
            continue
        break
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None
    # A year written into the title is the uploader's statement about the work; the item's own
    # year is often the upload date.
    year = claimed or (year if year and 1880 <= year <= 2100 else None)
    return {'title': title[:240], 'year': year, 'kind': kind, 'season': season, 'episode': episode}


def work_id(kind, title, year):
    key = '%s\x00%s\x00%s' % (kind, title_key(title), year if kind == 'movie' and year else '')
    return 'aw' + hashlib.sha1(key.encode()).hexdigest()[:16]


def rebuild(root, uploads, now=None):
    """Recompute works from all stored uploads (dicts with id, title, year, description)."""
    now = time.time() if now is None else float(now)
    works, members = {}, {}
    for item in uploads:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        parsed = parse(item.get('title'), item.get('year'))
        if not identity_rules.meaning_title(parsed['title']):
            continue
        wid = work_id(parsed['kind'], parsed['title'], parsed['year'])
        work = works.setdefault(wid, {'kind': parsed['kind'], 'titles': Counter(), 'year': parsed['year'] if parsed['kind'] == 'movie' else None,
                                      'summary': '', 'anime': False, 'uploads': 0})
        work['titles'][parsed['title']] += 1
        work['uploads'] += 1
        text = ' '.join(str(item.get('description') or '').split())[:2000]
        if len(text) > len(work['summary']):
            work['summary'] = text
        if ANIME_HINT.search(str(item.get('title') or '') + ' ' + text) or anime_match.script_hint(item.get('title'))[0] == 'ja':
            work['anime'] = True
        members[str(item['id'])] = (wid, parsed['season'], parsed['episode'])
    db = engine._conn(SPEC, root)
    try:
        with db:
            known = {r['id']: r for r in db.execute('SELECT id,year_claim,year_state FROM archive_works')}
            for wid, work in works.items():
                title = work['titles'].most_common(1)[0][0]
                old = known.get(wid)
                state = old['year_state'] if old and old['year_claim'] == work['year'] else 0
                db.execute("""INSERT INTO archive_works(id,kind,title,year,summary,seen,year_claim,year_state,anime,uploads)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,year=excluded.year,
                    summary=excluded.summary,seen=excluded.seen,year_claim=excluded.year_claim,year_state=excluded.year_state,
                    anime=excluded.anime,uploads=excluded.uploads""",
                           (wid, work['kind'], title, None if state == 2 else work['year'], work['summary'], now,
                            work['year'], state, int(work['anime']), work['uploads']))
            gone = [wid for wid in known if wid not in works]
            for wid in gone:
                db.execute('DELETE FROM archive_works WHERE id=?', (wid,))
                db.execute('DELETE FROM archive_reference_checks WHERE item_id=?', (wid,))
                db.execute('DELETE FROM archive_anime WHERE work_id=?', (wid,))
            db.execute('DELETE FROM archive_work_items')
            db.executemany('INSERT INTO archive_work_items(item_id,work_id,season,episode) VALUES(?,?,?,?)',
                           [(item_id, wid, s, e) for item_id, (wid, s, e) in members.items()])
            db.execute("INSERT INTO archive_meta(key,value) VALUES('last_success',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
    finally:
        db.close()
    return {'uploads': len(members), 'works': len(works), 'removed': len(gone)}


def sync(root, c, now=None):
    """Rebuild when the stored uploads changed (main database connection ``c``); cheap otherwise."""
    row = c.execute('SELECT COUNT(*),MAX(updated) FROM portal_items WHERE source=?', (SOURCE,)).fetchone()
    signature = '%s:%s' % (row[0], row[1])
    db = connect(root)
    try:
        if _meta(db, 'signature') == signature:
            return None
    finally:
        db.close()
    uploads = []
    for payload, in c.execute('SELECT metadata FROM portal_items WHERE source=?', (SOURCE,)):
        try:
            uploads.append(json.loads(payload))
        except ValueError:
            continue
    result = rebuild(root, uploads, now)
    db = connect(root)
    try:
        with db:
            db.execute("INSERT INTO archive_meta(key,value) VALUES('signature',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (signature,))
    finally:
        db.close()
    return result


def _work(root, wid):
    db = engine._conn(SPEC, root)
    try:
        row = db.execute('SELECT * FROM archive_works WHERE id=?', (wid,)).fetchone()
    finally:
        db.close()
    return dict(row) if row else None


def _set_year(root, wid, year, state):
    db = connect(root)
    try:
        with db:
            db.execute('UPDATE archive_works SET year=?,year_state=? WHERE id=?', (year, state, wid))
    finally:
        db.close()


def selected(report):
    """The unique reference of a report, or None."""
    if not isinstance(report, dict) or report.get('status') != 'candidate':
        return None
    return next((r for r in report.get('references') or [] if r.get('eligible')), None)


def enrich(root, item_id, settings, *, lookup=None, now=None, force=False, anime_lookup=None):
    """Reference check of one work, with year repair and the AniList question for anime."""
    now = time.time() if now is None else float(now)
    report = engine.enrich(SPEC, root, item_id, settings, lookup=lookup, now=now, force=force)
    work = _work(root, item_id)
    if work and work['kind'] == 'movie' and work['year'] and (work['year_state'] == 0 or force) and not selected(report) \
            and report.get('status') in ('no_match', 'review'):
        # Year repair: Archive.org often carries the upload date. Ask once without the year;
        # only a unique hit counts (remakes of the same name stay "review").
        _set_year(root, item_id, None, 2)
        second = engine.enrich(SPEC, root, item_id, settings, lookup=lookup, now=now, force=force)
        if selected(second):
            report = second
        else:
            _set_year(root, item_id, work['year'], 1)
            report = engine.enrich(SPEC, root, item_id, settings, lookup=lookup, now=now, force=False)
    if work and work['anime'] and not selected(report):
        _anime(root, work, now, anime_lookup, force)
    return report


def _anime(root, work, now, lookup, force):
    db = connect(root)
    try:
        old = db.execute('SELECT checked,title,payload FROM archive_anime WHERE work_id=?', (work['id'],)).fetchone()
    finally:
        db.close()
    if old and not force and old['title'] == work['title']:
        age = now - old['checked']
        if age < (ANIME_TTL if json.loads(old['payload']).get('id') else ANIME_RETRY):
            return
    try:
        hit = (lookup or anime_match.lookup_anime)(work['title'], work['year_claim'])
    except Exception:
        return    # AniList not reachable: ask again with the next round, store nothing
    payload = {}
    if hit:
        media = hit['media']
        titles = media.get('title') or {}
        payload = {'id': hit['id'], 'score': hit['score'], 'alias': str(hit.get('alias') or '')[:200],
                   'title': str(titles.get('english') or titles.get('romaji') or titles.get('native') or '')[:200],
                   'native': str(titles.get('native') or '')[:200], 'format': str(media.get('format') or '')[:20],
                   'episodes': media.get('episodes') if isinstance(media.get('episodes'), int) else None,
                   'year': media.get('seasonYear') or (media.get('startDate') or {}).get('year')}
    db = connect(root)
    try:
        with db:
            db.execute("""INSERT INTO archive_anime(work_id,checked,title,payload) VALUES(?,?,?,?)
                ON CONFLICT(work_id) DO UPDATE SET checked=excluded.checked,title=excluded.title,payload=excluded.payload""",
                       (work['id'], now, work['title'], json.dumps(payload, ensure_ascii=False)))
    finally:
        db.close()


def cached(root, item_id):
    return engine.cached(SPEC, root, item_id)


def pending(root, limit=10, now=None):
    return engine.pending(SPEC, root, limit, now)


def metrics(root):
    return engine.metrics(SPEC, root)


def loop(root, settings, slots, stop, main_db, *, gap=6.0, idle=1800.0):
    """Background check like every platform; ``main_db`` is the server's connection context."""
    import netzkino_enrichment as shared

    def todo(r, *a, **kw):
        with main_db() as c:
            sync(r, c)
        return pending(r, *a, **kw)
    return shared.loop(root, settings, slots, stop, gap=gap, idle=idle,
                       enrich_one=lambda r, i, s, **kw: enrich(r, i, s, **kw), pending_fn=todo, name='archive')


def _load(root):
    db = engine._conn(SPEC, root)
    try:
        works = {r['id']: dict(r) for r in db.execute('SELECT * FROM archive_works')}
        members = {r['item_id']: dict(r) for r in db.execute('SELECT * FROM archive_work_items')}
        reports, anime = {}, {}
        for wid, checked, ident, payload in db.execute('SELECT item_id,checked,identity,payload FROM archive_reference_checks'):
            work = works.get(wid)
            if not work or ident != engine._key(engine.identity(work)):
                continue
            try:
                reports[wid] = json.loads(payload)
            except ValueError:
                continue
        for wid, title, payload in db.execute('SELECT work_id,title,payload FROM archive_anime'):
            if wid in works and works[wid]['title'] == title:
                try:
                    anime[wid] = json.loads(payload)
                except ValueError:
                    continue
    finally:
        db.close()
    return works, members, reports, anime


def _groups(works, reports, anime):
    """ArchiveMedia series_merge: works with the same reference id are one work. work id -> group id."""
    by_ref = {}
    for wid in works:
        ref = selected(reports.get(wid))
        if ref:
            by_ref.setdefault('%s:%s' % (ref['provider'], ref['reference_id']), []).append(wid)
        elif (anime.get(wid) or {}).get('id'):
            by_ref.setdefault('AniList:%s' % anime[wid]['id'], []).append(wid)
    group = {wid: wid for wid in works}
    for ids in by_ref.values():
        head = min(ids, key=lambda w: (-works[w]['uploads'], w))
        for wid in ids:
            group[wid] = head
    return group


def _public(work, report, anime, uploads, group):
    ref = selected(report)
    meta = (report or {}).get('metadata') or {}
    year = work['year_claim']
    year_source = 'upload' if year else ''
    if ref and ref.get('year') and work['kind'] == 'movie' and ref['year'] != year:
        year, year_source = ref['year'], 'reference'
    elif not ref and (anime or {}).get('year') and not year:
        year, year_source = anime['year'], 'anilist'
    out = {'id': work['id'], 'group': group, 'kind': work['kind'], 'title': (ref or {}).get('title') or work['title'],
           'query_title': work['title'], 'year': year, 'year_source': year_source, 'year_upload': work['year_claim'],
           'status': (report or {}).get('status') or 'unchecked', 'uploads': uploads,
           'reference': {'provider': ref['provider'], 'id': ref['reference_id']} if ref else None,
           'rating': meta.get('rating') if ref else None, 'poster': meta.get('poster') if ref else '',
           'anime_hint': bool(work['anime']), 'anilist': anime if (anime or {}).get('id') else None}
    return out


def annotate(root, items):
    """Add ``work`` to listing entries of Archive.org uploads (read only, no provider traffic)."""
    wanted = [x for x in items if isinstance(x, dict) and x.get('source') == SOURCE]
    if not wanted:
        return items
    works, members, reports, anime = _load(root)
    group = _groups(works, reports, anime)
    size = Counter()
    for wid, work in works.items():
        size[group[wid]] += work['uploads']
    for item in wanted:
        member = members.get(item['id'])
        if not member or member['work_id'] not in works:
            continue
        wid = member['work_id']
        head = group[wid]
        public = _public(works[wid], reports.get(wid) or reports.get(head), anime.get(wid) or anime.get(head), size[head], head)
        public.update(season=member['season'], episode=member['episode'])
        item['work'] = public
    return items


def overview(root, query='', offset=0, limit=40):
    """Works instead of uploads: one entry per (merged) work, largest first."""
    works, members, reports, anime = _load(root)
    group = _groups(works, reports, anime)
    merged = {}
    for wid, work in works.items():
        merged.setdefault(group[wid], []).append(work)
    rows = []
    needle = title_key(query)
    for head, parts in merged.items():
        entry = _public(works[head], reports.get(head), anime.get(head), sum(p['uploads'] for p in parts), head)
        entry['titles'] = sorted({p['title'] for p in parts})[:8]
        if needle and needle not in title_key(entry['title'] + ' ' + ' '.join(entry['titles'])):
            continue
        rows.append(entry)
    rows.sort(key=lambda r: (-r['uploads'], title_key(r['title'])))
    offset = max(0, min(int(offset), 100000))
    limit = max(1, min(int(limit), 60))
    recognised = sum(1 for r in rows if r['reference'] or r['anilist'])
    return {'total': len(rows), 'recognised': recognised, 'offset': offset, 'items': rows[offset:offset + limit]}


def members_of(root, group_id):
    """Upload ids of a (merged) work."""
    if not VALID_ID.fullmatch(str(group_id or '')):
        raise ValueError('Ungültiges Werk')
    works, members, reports, anime = _load(root)
    group = _groups(works, reports, anime)
    rows = sorted((m['season'] or 0, m['episode'] or 0, item_id) for item_id, m in members.items()
                  if group.get(m['work_id']) == group_id)
    return [item_id for _, _, item_id in rows]


def summary(root):
    """Counts for the platform overview and the diagnosis (no titles)."""
    works, members, reports, anime = _load(root)
    group = _groups(works, reports, anime)
    return {'uploads': len(members), 'works': len(set(group.values())),
            'recognised': len({group[w] for w in works if selected(reports.get(w)) or (anime.get(w) or {}).get('id')}),
            'checked': len(reports), 'year_repaired': sum(1 for w in works.values() if w['year_state'] == 2),
            'series': sum(1 for w in works.values() if w['kind'] == 'series'),
            'anilist': sum(1 for a in anime.values() if a.get('id'))}
