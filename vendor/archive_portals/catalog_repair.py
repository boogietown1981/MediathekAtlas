"""ArchiveMedia v0.9.4: conservative, offline file-family and content role repair.

An Archive.org item is an upload container, NOT a media work or episode. Archive
transcodes are alternate encodings; Blu-ray STREAM files are assets until a
playlist/episode map proves otherwise. Never infer audio language from title.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import PurePosixPath

TECHNICAL_DIR=re.compile(r'(?i)(?:^|/)BDMV/(?:STREAM|BACKUP|PLAYLIST)/')
EXTRA=re.compile(r'(?i)(?:^|[\s._/\-\[\(])(trailer|teaser|sample|preview|menu|bonus|extras?|op|ed)(?=$|[\s._/\-\]\)])')
SEGMENT_EXT={'.ts','.m2ts','.mts'}
RELEASE_TAG=re.compile(r'(?i)\[\s*(?:BDMV|BD|DVD|Blu[- ]?ray|\d{6}|\d{8}|BSTD[- ]?\d+|BDMV[^\]]*)\s*\]')
DISC_PREFIX=re.compile(r'(?i)^(?:\[?(?:BDMV|DVDRIP|BLURAY|BDRIP)\]?\s*[\-_. ]*)+')
EPISODE=re.compile(r'(?i)(?:\bS\d{1,2}[\s._-]*E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b|\b(?:episode|ep|folge)[\s._-]*\d{1,3}\b)')


def release_title(value):
    """Remove optical-media release noise without discarding legitimate work names."""
    s=str(value or '')
    s=RELEASE_TAG.sub(' ',s)
    s=DISC_PREFIX.sub('',s)
    s=re.sub(r'(?i)\b(?:Blu[- ]?ray\s+BOX|Complete\s+BD\s+BOX)\b',' ',s)
    return re.sub(r'\s+',' ',s).strip(' -._') or str(value or '')


def canonical_source(filename,original=None,all_filenames=()):
    """Archive.org's `original` field is authoritative when it references a file.

    A missing original may be non-video (e.g. BDMV .m2ts); that identity is still
    useful for linking its derived encodes, but does not prove work identity.
    """
    name=str(filename or '').replace('\\','/')
    raw=str(original or '').replace('\\','/')
    if raw and raw!=name:return raw
    files=set(all_filenames)
    if name.lower().endswith('.ia.mp4'):
        stem=name[:-7]
        for candidate in (stem+'.mp4',stem+'.mkv',stem+'.avi',stem+'.m2ts',stem+'.ts',stem):
            if candidate in files:return candidate
    return name


def family_key(item_id,filename,original=None,all_filenames=()):
    src=canonical_source(filename,original,all_filenames)
    digest=hashlib.sha256((str(item_id)+'\0'+src).encode('utf-8')).hexdigest()[:24]
    return 'file:'+digest


def technical_role(filename,original=None,duration=None,files_in_item=1):
    name=str(filename or '').replace('\\','/')
    ext=PurePosixPath(name).suffix.lower()
    try:duration=float(duration) if duration is not None else None
    except (ValueError,TypeError):duration=None
    if TECHNICAL_DIR.search(name):return 'bdmv_stream'
    if EXTRA.search(name):return 'extra_or_clip'
    if ext in SEGMENT_EXT and files_in_item>1:return 'transport_segment'
    if ext=='.ts' and duration is not None and duration<300:return 'transport_segment'
    if duration is not None and duration<180:return 'short_unknown'
    if original and original!=name:return 'archive_derivative'
    if name.lower().endswith('.ia.mp4'):return 'archive_derivative'
    return 'primary_video'


def parent_episode_allowed(variants):
    """Only a singleton *logical* video can inherit its upload's ep number.

    Archive-generated encodes and their referenced original count as one family.
    Segmented disc/transport uploads are NEVER singleton episodes.
    """
    names={v['filename'] for v in variants}
    logical=set()
    for v in variants:
        role=technical_role(v['filename'],v.get('original'),v.get('duration'),len(variants))
        if role in ('bdmv_stream','transport_segment','extra_or_clip','short_unknown'):continue
        logical.add(canonical_source(v['filename'],v.get('original'),names))
    return len(logical)==1 and bool(logical)


def dedupe_metrics(variants):
    """Count file families and roles; never claim these prove identical content."""
    families={}
    roles={}
    names={v['filename'] for v in variants}
    for v in variants:
        role=technical_role(v['filename'],v.get('original'),v.get('duration'),len(variants))
        roles[role]=roles.get(role,0)+1
        families.setdefault(family_key(v.get('item_id'),v['filename'],v.get('original'),names),[]).append(v['filename'])
    return {'files':len(variants),'file_families':len(families),'derivative_families':sum(len(v)>1 for v in families.values()),'roles':roles}


def numbered_episode_candidates(variants):
    """Find shared numbered *series* within one Archive item.

    A leading number is an episode ONLY when >=3 distinct sequential-looking
    files share the same specific release title. Never infer 'episode 00001'
    from BDMV or arbitrary numbered clips.
    Returns {original-or-filename: (clean_work_title, number)}.
    """
    from pathlib import PurePosixPath
    from collections import defaultdict
    matched=defaultdict(list)
    all_names={x['filename'] for x in variants}
    for v in variants:
        filename=str(v['filename'])
        role=technical_role(filename,v.get('original'),v.get('duration'),len(variants))
        if role in ('bdmv_stream','transport_segment','extra_or_clip','short_unknown'):continue
        original=canonical_source(filename,v.get('original'),all_names)
        basename=PurePosixPath(original).stem
        m=re.match(r'^0*(?P<episode>[1-9]\d{0,2})[ ._-]+(?P<title>.+)$',basename)
        if not m:continue
        title=re.sub(r'(?i)\s*[\[(]\s*(?:dub|dubbed|sub|subbed|dual[ ._-]*audio|1080p|720p|480p)\s*[\])]\s*$', '', m.group('title')).strip(' -_.')
        # Require a real, distinctive work title; simple labels are not enough.
        if len(title)<7 or len(title.split())<2:continue
        key=re.sub(r'\W+',' ',title.casefold()).strip()
        matched[key].append((original,title,int(m.group('episode'))))
    out={}
    for same_title in matched.values():
        numbers={x[2] for x in same_title}
        if len(numbers)<3:continue
        for original,title,episode in same_title:
            out[original]=(title,episode)
    return out
