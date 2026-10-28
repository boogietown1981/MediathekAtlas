"""Non-destructive filesystem organization & Kodi/Jellyfin sidecar export.

No re-encoding or media container modification. Files are downloaded under their new
name and metadata accompanies them as UTF-8 NFO and JSON. Existing unrelated files
are never overwritten. Every optional network action is bounded.
"""
from __future__ import annotations
import json, re, hashlib, os, tempfile, urllib.parse, urllib.request, logging
from pathlib import Path
from xml.etree import ElementTree as ET

MEDIA_PATH_LIMIT=120

def clean_path_part(value):
    val=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',str(value or ''))
    val=' '.join(val.strip(' .').split())
    val=re.sub(r'\.+$','',val)
    return val[:MEDIA_PATH_LIMIT].rstrip(' .') or 'Unbekannt'

def _verified_language_codes(variant, column, origin_column):
    """Never advertise filename guesses or uploader claims as proven tracks."""
    origin=str(variant.get(origin_column) or '').lower()
    if column=='audio_languages':
        verified=origin.startswith('ffprobe')
    else:
        verified=origin.startswith('ffprobe') or origin in ('sidecar','ffprobe+sidecar')
    if not verified:return []
    codes=[]
    for value in str(variant.get(column) or '').split(','):
        value=value.strip().lower()
        if value and value not in ('und','unknown','unbekannt','?') and value not in codes:
            codes.append(value)
    return codes


def unresolved_target(download_dir, variant):
    """Use source identity, not an unverified film/episode title."""
    root=Path(download_dir).expanduser().resolve()
    ext=Path(variant['filename']).suffix.lower()
    if ext not in {'.mp4','.mkv','.avi','.m4v','.mov','.webm','.ts','.mpeg','.mpg','.ogv','.wmv','.m2ts','.mts','.vob','.flv'}:
        raise ValueError('Unzulässiges Videoformat')
    item=clean_path_part(variant['item_id'])
    original=clean_path_part(Path(variant['filename']).stem)
    token=hashlib.sha256((variant['item_id']+'/'+variant['filename']).encode('utf-8')).hexdigest()[:8]
    return root/'Unsortiert'/item/(original+' ['+token+']'+ext),token


def canonical_target(download_dir,group,variant,options):
    """Stable, human-readable destination for one physical Archive.org file.

    Title and episode identity must be confirmed. Dub/Sub appear only when
    the corresponding streams or caption sidecars have direct evidence.
    """
    root=Path(download_dir).expanduser().resolve()
    title=clean_path_part(group['title'])
    year=(' ('+str(group['year'])+')') if group.get('year') else ''
    name=title+year
    if group.get('kind')=='series':
        season=variant.get('season');episode=variant.get('episode')
        if not isinstance(season,int) or not isinstance(episode,int) or season<0 or episode<0:
            raise ValueError('Keine bestätigte Serienfolge')
        folder=root/'Serien'/name/('Season %02d'%season)
        stem='%s - S%02dE%02d'%(name,season,episode)
    else:
        folder=root/'Filme'/name
        stem=name
    height=variant.get('height') or 0
    if height:
        band='2160p' if height>=2000 else f'{height}p'
        stem+=' - '+band
    audio=_verified_language_codes(variant,'audio_languages','audio_origin')
    sub=_verified_language_codes(variant,'subtitle_languages','subtitle_origin')
    if audio:stem+=' - Dub-'+clean_path_part('+'.join(x.upper() for x in audio))
    if sub:stem+=' - Sub-'+clean_path_part('+'.join(x.upper() for x in sub))
    ext=Path(variant['filename']).suffix.lower()
    if ext not in {'.mp4','.mkv','.avi','.m4v','.mov','.webm','.ts','.mpeg','.mpg','.ogv','.wmv','.m2ts','.mts','.vob','.flv'}:
        raise ValueError('Unzulässiges Videoformat')
    dest=folder/(clean_path_part(stem)+ext)
    token=hashlib.sha256((variant['item_id']+'/'+variant['filename']).encode('utf-8')).hexdigest()[:8]
    return dest,token


def planned_target(download_dir, group, variant, options=None):
    """Pure planning API used by the UI preview AND actual downloader."""
    if group.get('match_state')=='confirmed' and not variant.get('identity_warning') and (group.get('kind')!='series' or
         isinstance(variant.get('season'),int) and isinstance(variant.get('episode'),int)):
        dest,token=canonical_target(download_dir,group,variant,options or {})
        return dest,token,True
    dest,token=unresolved_target(download_dir,variant)
    return dest,token,False

def choose_collision_safe(dest,token,variant,overwrite_same=False):
    # If dest is taken, never overwrite it unless it is exactly the already known local file.
    if not dest.exists():return dest
    if overwrite_same and variant.get('local_path') and Path(variant['local_path']).resolve()==dest.resolve():return dest
    unique=dest.with_name(dest.stem+' ['+token+']'+dest.suffix)
    if unique.exists() and (not overwrite_same or not variant.get('local_path') or Path(variant['local_path']).resolve()!=unique.resolve()):
        # File may be from the same source but we have no provenance to prove that.
        raise FileExistsError('Zieldatei existiert bereits: '+str(unique))
    return unique

def write_atomic(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.archivemedia-',suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(content);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def node(parent,name,value):
    if value is not None and str(value).strip():ET.SubElement(parent,name).text=str(value)

def render_nfo(group,variant,is_show=False):
    tag='tvshow' if is_show else 'episodedetails' if group['kind']=='series' else 'movie'
    root=ET.Element(tag)
    node(root,'title',group['title'])
    node(root,'originaltitle',group['title'])
    node(root,'year',group.get('year'))
    node(root,'plot',group.get('description'))
    if not is_show and group['kind']=='series':
        node(root,'showtitle',group['title']);node(root,'season',variant.get('season'));node(root,'episode',variant.get('episode'))
    if not is_show:
        duration=variant.get('duration') or group.get('expected_runtime')
        if duration:node(root,'runtime',int(round(float(duration)/60)))
        for lang in _verified_language_codes(variant,'audio_languages','audio_origin'):
            stream=ET.SubElement(ET.SubElement(root,'fileinfo'),'audio');node(stream,'language',lang)
    # Store source identifiers only as reference, not invented provider IDs.
    if group.get('reference_id') and group.get('reference') in ('tmdb','tvmaze'):
        u=ET.SubElement(root,'uniqueid',{'type':str(group['reference']),'default':'true'});u.text=str(group['reference_id'])
    if group.get('poster'):node(root,'thumb',group.get('poster'))
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def save_poster(group,poster_path):
    url=str(group.get('poster') or '')
    if not url:return False
    try:
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in {'archive.org','image.tmdb.org','static.tvmaze.com'}:return False
        if poster_path.is_file():return True
        request=urllib.request.Request(url,headers={'User-Agent':'ArchiveMedia/0.7 (local media exporter)'})
        with urllib.request.urlopen(request,timeout=15) as source:
            data=source.read(4*1024*1024+1)
            ctype=source.headers.get('Content-Type','')
        if len(data)>4*1024*1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG')):return False
        # Normalize file extension for the actual image, leave original bytes intact.
        suffix='.png' if data.startswith(b'\x89PNG') else '.jpg'
        write_atomic(poster_path.with_suffix(suffix),data)
        return True
    except (OSError,ValueError,TimeoutError) as exc:
        logging.warning('Poster nicht verfügbar: %s',exc)
        return False

def export_sidecars(path,group,variant,opts,provenance=None):
    if not opts.get('write_metadata',True):return []
    created=[]
    nfo=path.with_suffix('.nfo');write_atomic(nfo,render_nfo(group,variant));created.append(str(nfo))
    meta={
      'schema':'ArchiveMedia-v0.7','work':{'title':group['title'],'type':group['kind'],'year':group.get('year'),
                 'description':group.get('description'),'reference':group.get('reference'),'reference_id':group.get('reference_id'),
                 'season':variant.get('season'),'episode':variant.get('episode')},
      'file':{'name':path.name,'original_filename':variant.get('filename'),'archive_item':variant['item_id'],
              'origin_url':'https://archive.org/details/'+urllib.parse.quote(variant['item_id'],safe=''),
              'width':variant.get('width'),'height':variant.get('height'),'seconds':variant.get('duration'),
              'audio_languages':variant.get('audio_languages'),'audio_evidence':variant.get('audio_origin'),
              'audio_hint_languages':variant.get('audio_hint_languages'),'audio_hint_source':variant.get('audio_hint_source'),
              'subtitle_languages':variant.get('subtitle_languages'),'subtitle_evidence':variant.get('subtitle_origin'),
              'subtitle_hint_languages':variant.get('subtitle_hint_languages'),'subtitle_hint_source':variant.get('subtitle_hint_source'),
              'media_source':variant.get('media_source'),'runtime_validation':variant.get('validation'),
              'licenseurl':variant.get('licenseurl'),'rights':variant.get('rights'),
              'subtitle_files':provenance or []},
      'caveats':['Languages inferred from filenames are not verified audio tracks.',
                 'Archive.org availability does not demonstrate download rights.']}
    js=path.with_name(path.stem+'.metadata.json');write_atomic(js,json.dumps(meta,ensure_ascii=False,indent=2).encode('utf-8'));created.append(str(js))
    if group['kind']=='series':
        show_folder=path.parent.parent
        show_nfo=show_folder/'tvshow.nfo'
        if not show_nfo.is_file():write_atomic(show_nfo,render_nfo(group,variant,is_show=True));created.append(str(show_nfo))
    if opts.get('fetch_poster',True):
        root_folder=path.parent.parent if group['kind']=='series' else path.parent
        save_poster(group,root_folder/'poster.jpg')
    return created
