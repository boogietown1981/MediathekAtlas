"""ArchiveMedia: one inventory for every published file, regardless of IA mediatype.

A file's extension establishes a possible *file kind*, never the identity of a
book, recording, operating system or film. Generated files remain searchable in
inventory but do not make new catalog works. No media bytes are downloaded.
"""
from __future__ import annotations
import json
from pathlib import PurePosixPath

VIDEO={'.mp4','.mkv','.avi','.mov','.m4v','.webm','.mpg','.mpeg','.ts','.m2ts','.mts','.ogv','.wmv','.flv','.vob'}
AUDIO={'.mp3','.flac','.m4a','.aac','.ogg','.oga','.opus','.wav','.aiff','.aif','.wma','.alac','.ape','.mid','.midi','.mka'}
SOFTWARE={'.exe','.msi','.msix','.appx','.cab','.msu','.msm','.dmg','.pkg','.deb','.rpm','.apk','.ipa','.appimage','.flatpak','.snap','.whl','.spk','.qpkg','.jar'}
DOCUMENTS={'.pdf','.epub','.djvu','.mobi','.azw','.azw3','.cbz','.cbr','.txt','.rtf','.doc','.docx','.odt','.html','.htm','.md','.chm','.xls','.xlsx','.xlsm','.ods','.csv','.tsv','.ppt','.pptx','.odp','.pages','.numbers','.key','.tex'}
IMAGES={'.jpg','.jpeg','.png','.gif','.webp','.tif','.tiff','.bmp','.svg','.heic','.avif'}
SUBTITLES={'.srt','.ass','.ssa','.vtt','.sub','.smi','.sbv','.ttml'}
HELPERS={'.xml','.json','.torrent','.sqlite','.nfo','.sfv','.log','.m3u','.m3u8','.pls','.cue','.mpls','.clpi','.bdjo','.bdmv'}
GENERATED=('_files.xml','_meta.xml','_reviews.xml','_scandata.xml','_abbyy.gz','_djvu.xml','_djvu.txt','_text.pdf','__ia_thumb','_thumb.jpg')
CATEGORY_SET={'video','audio','software','documents','images','other'}
SCHEMA='''
CREATE TABLE IF NOT EXISTS file_inventory (
 item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, extension TEXT, category TEXT NOT NULL,
 file_role TEXT NOT NULL, reason TEXT NOT NULL, source TEXT,
 original TEXT, format TEXT, bytes INTEGER, duration REAL, md5 TEXT, sha1 TEXT,
 metadata_json TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(item_id,filename));
CREATE INDEX IF NOT EXISTS ix_inventory_category ON file_inventory(category,file_role,item_id);
CREATE TABLE IF NOT EXISTS item_sections (
 item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 category TEXT NOT NULL, subtype TEXT NOT NULL DEFAULT 'unknown',
 subtype_reason TEXT, content_files INTEGER NOT NULL DEFAULT 0,
 completeness TEXT NOT NULL DEFAULT 'full', updated TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(item_id,category));
CREATE INDEX IF NOT EXISTS ix_item_sections_category ON item_sections(category,subtype,item_id);
CREATE INDEX IF NOT EXISTS ix_item_sections_completeness ON item_sections(completeness,item_id);
CREATE TABLE IF NOT EXISTS inventory_state (key TEXT PRIMARY KEY,value TEXT NOT NULL);
'''

def _value(v):
    if isinstance(v,list):return ', '.join(str(x) for x in v)
    return str(v or '')

def _number(v):
    try:return int(v)
    except (TypeError,ValueError):return None

def _duration(v):
    try:
        if v is None:return None
        if ':' not in str(v):return float(v)
        t=0.0
        for part in str(v).split(':'):t=t*60+float(part)
        return t
    except (TypeError,ValueError):return None

def classify(filename, data=None):
    data=data or {}
    filename=str(filename or '').replace('\\','/')
    name=PurePosixPath(filename).name.casefold()
    ext=PurePosixPath(name).suffix.casefold()
    fformat=_value(data.get('format')).casefold()
    if any(name.endswith(s) for s in GENERATED) or '/_ia_thumb' in filename.casefold():
        return 'other','auxiliary','Automatisch erzeugte Archive.org-Hilfsdatei'
    if ext in SUBTITLES:return 'other','sidecar','Untertiteldatei; gehört möglicherweise zu Video'
    if ext in HELPERS:return 'other','auxiliary','Metadaten, Playlist oder Prüfdatei'
    if ext in VIDEO:cat='video'
    elif ext in AUDIO:cat='audio'
    elif ext in SOFTWARE:cat='software'
    elif ext in DOCUMENTS:cat='documents'
    elif ext in IMAGES:cat='images'
    else:
        # Generic containers do NOT prove the presence of executable software.
        return 'other','unknown','Mehrdeutiger oder nicht unterstützter Dateityp'
    if '/bdmv/' in filename.casefold() or name.endswith(('.m2ts','.mts')):
        role='technical' if cat=='video' else 'content'
    elif _value(data.get('source')).casefold()=='derivative' or _value(data.get('original')):
        role='derivative'
    else:role='content'
    return cat,role,'Dateiendung '+ext+'; keine inhaltliche Bestätigung'

def store(c,item_id,metadata,files):
    """Upsert complete manifest; one IA item may belong to *many* media sections."""
    from catalog_taxonomy import classify_entry
    names=[]; grouped={cat:[] for cat in CATEGORY_SET}; counts={cat:0 for cat in CATEGORY_SET}
    for f in files:
        if not isinstance(f,dict) or not isinstance(f.get('name'),str) or not f['name']:continue
        name=f['name'][:1200]
        cat,role,reason=classify(name,f)
        names.append(name);grouped[cat].append(f)
        if role=='content':counts[cat]+=1
        extra={k:f.get(k) for k in ('title','artist','album','track','disc','bitrate','sample_rate','isbn','pages','version','publisher','year','creator','language') if f.get(k) is not None}
        c.execute('''INSERT INTO file_inventory(item_id,filename,extension,category,file_role,reason,source,original,format,bytes,duration,md5,sha1,metadata_json)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id,filename) DO UPDATE SET
                     extension=excluded.extension,category=excluded.category,file_role=excluded.file_role,reason=excluded.reason,
                     source=excluded.source,original=excluded.original,format=excluded.format,bytes=excluded.bytes,
                     duration=excluded.duration,md5=excluded.md5,sha1=excluded.sha1,metadata_json=excluded.metadata_json,updated=CURRENT_TIMESTAMP''',
                  (item_id,name,PurePosixPath(name).suffix.lower(),cat,role,reason,_value(f.get('source')),
                   _value(f.get('original')),_value(f.get('format')),_number(f.get('size')),_duration(f.get('length')),
                   _value(f.get('md5')),_value(f.get('sha1')),json.dumps(extra,ensure_ascii=False)[:2500]))
    # Avoid SQLITE_MAX_VARIABLE_NUMBER on uploads containing many thousands of files.
    c.execute('CREATE TEMP TABLE IF NOT EXISTS _inventory_seen(filename TEXT PRIMARY KEY)')
    c.execute('DELETE FROM _inventory_seen')
    c.executemany('INSERT OR IGNORE INTO _inventory_seen(filename) VALUES(?)',((x,) for x in names))
    c.execute('DELETE FROM file_inventory WHERE item_id=? AND NOT EXISTS (SELECT 1 FROM _inventory_seen s WHERE s.filename=file_inventory.filename)',(item_id,))
    c.execute('DELETE FROM _inventory_seen')
    for cat in ('audio','software','documents','images'):
        if not grouped[cat]:continue
        if cat in ('audio','software','documents'):
            subtype,reason=classify_entry(cat,metadata,grouped[cat]);
        else:subtype,reason='images','Bilddateien nach Dateiendung erkannt'
        c.execute('''INSERT INTO item_sections(item_id,category,subtype,subtype_reason,content_files,completeness)
                    VALUES(?,?,?,?,?,'full') ON CONFLICT(item_id,category) DO UPDATE SET
                    subtype=excluded.subtype,subtype_reason=excluded.subtype_reason,content_files=excluded.content_files,
                    completeness='full',updated=CURRENT_TIMESTAMP''',(item_id,cat,subtype,reason,counts[cat]))
    c.execute("DELETE FROM item_sections WHERE item_id=? AND category NOT IN ('video') AND NOT EXISTS (SELECT 1 FROM file_inventory f WHERE f.item_id=item_sections.item_id AND f.category=item_sections.category)",(item_id,))
    # Item may contain a true video even if its Archive.org mediatype says software/texts.
    if grouped['video']:
        c.execute('''INSERT INTO item_sections(item_id,category,subtype,subtype_reason,content_files,completeness)
            VALUES(?,'video','unknown','Videodateien innerhalb des Archive-Eintrags',?,'full')
            ON CONFLICT(item_id,category) DO UPDATE SET content_files=excluded.content_files,completeness='full',updated=CURRENT_TIMESTAMP''',(item_id,counts['video']))
    else:c.execute("DELETE FROM item_sections WHERE item_id=? AND category='video'",(item_id,))
    return {'files':len(names),'categories':{k:len(v) for k,v in grouped.items() if v},'video':len(grouped['video'])}

def backfill_legacy(c):
    """Reconstruct only *known* files; mark as partial, never invent missing files."""
    if c.execute("SELECT value FROM inventory_state WHERE key='legacy_backfill_1'").fetchone():return
    for table in ('variants','catalog_assets'):
        if table=='variants':
            rows=c.execute('SELECT item_id,filename,source,original,format,bytes,duration,md5,sha1 FROM variants').fetchall()
        else:rows=c.execute('SELECT item_id,filename,source,original,format,bytes,duration,md5,sha1 FROM catalog_assets').fetchall()
        for r in rows:
            f=dict(r);cat,role,reason=classify(f['filename'],f)
            c.execute('''INSERT OR IGNORE INTO file_inventory(item_id,filename,extension,category,file_role,reason,source,original,format,bytes,duration,md5,sha1,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(r['item_id'],r['filename'],PurePosixPath(r['filename']).suffix.lower(),cat,role,
                      'Teilbestand aus älterer Datenbank: '+reason,r['source'],r['original'],r['format'],r['bytes'],r['duration'],r['md5'],r['sha1'],'{}'))
    c.execute('''INSERT OR IGNORE INTO item_sections(item_id,category,subtype,subtype_reason,content_files,completeness)
      SELECT item_id,category,'unknown','Unvollständiges Dateiinventar aus älterer Version',COUNT(*),'partial'
      FROM file_inventory WHERE category NOT IN ('other') GROUP BY item_id,category''')
    c.execute("INSERT OR REPLACE INTO inventory_state(key,value) VALUES('legacy_backfill_1','done')")

def listings(c,category,page=1,query='',limit=50,subtype=''):
    if category not in ('audio','software','documents','images'):raise ValueError('Ungültige Katalogkategorie')
    page=max(1,int(page));limit=max(1,min(100,int(limit)))
    where='WHERE s.category=?';p=[category]
    if subtype:
        from catalog_taxonomy import SUBTYPES
        if subtype not in SUBTYPES.get(category,('images',)):raise ValueError('Ungültige Unterkategorie')
        where+=' AND s.subtype=?';p.append(subtype)
    if query:
        where+=' AND (i.title LIKE ? OR i.creator LIKE ? OR i.id LIKE ?)';p.extend(['%'+query[:120]+'%']*3)
    total=c.execute('SELECT COUNT(*) FROM item_sections s JOIN items i ON i.id=s.item_id '+where,p).fetchone()[0]
    rows=c.execute('''SELECT s.item_id,s.category,s.subtype,s.subtype_reason,s.completeness,i.title,i.creator,i.year,i.language,
        COALESCE((SELECT album FROM catalog_entries WHERE item_id=i.id),'') album,
        COALESCE((SELECT publisher FROM catalog_entries WHERE item_id=i.id),'') publisher,
        (SELECT COUNT(*) FROM file_inventory f WHERE f.item_id=i.id AND f.category=s.category) assets,
        (SELECT COALESCE(SUM(bytes),0) FROM file_inventory f WHERE f.item_id=i.id AND f.category=s.category) total_bytes
        FROM item_sections s JOIN items i ON i.id=s.item_id '''+where+
        ''' ORDER BY i.title COLLATE NOCASE,i.id LIMIT ? OFFSET ?''',(*p,limit,(page-1)*limit)).fetchall()
    return {'items':[dict(x) for x in rows],'total':total,'page':page,'perpage':limit}

def detail(c,item_id,category=None):
    if category is None:
        sect=c.execute('SELECT category FROM item_sections WHERE item_id=? ORDER BY category LIMIT 1',(item_id,)).fetchone()
        if not sect:return None
        category=sect['category']
    sect=c.execute('SELECT * FROM item_sections WHERE item_id=? AND category=?',(item_id,category)).fetchone()
    row=c.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
    if not sect or not row:return None
    d=dict(row);d.update(dict(sect));d['item_id']=item_id;d['description']=row['description']
    d['album']='';d['publisher']='';d['external_data']=None;d['external_provider']=None;d['external_identifier']=None
    legacy=c.execute('SELECT album,publisher,external_data,external_provider,external_identifier FROM catalog_entries WHERE item_id=?',(item_id,)).fetchone()
    if legacy and c.execute('SELECT 1 FROM catalog_entries WHERE item_id=? AND category=?',(item_id,category)).fetchone():d.update(dict(legacy))
    d['files']=[dict(x) for x in c.execute('''SELECT filename,extension,format,bytes,duration,source,original,file_role,reason,metadata_json
      FROM file_inventory WHERE item_id=? AND category=? ORDER BY CASE WHEN file_role='content' THEN 0 ELSE 1 END,filename LIMIT 300''',(item_id,category))]
    d['all_files']=c.execute('SELECT COUNT(*) FROM file_inventory WHERE item_id=? AND category=?',(item_id,category)).fetchone()[0]
    return d

def inventory_list(c,category='',page=1,query='',limit=80):
    if category and category not in CATEGORY_SET:raise ValueError('Ungültige Kategorie')
    page=max(1,int(page));limit=max(1,min(int(limit),150));where='WHERE 1=1';p=[]
    if category:where+=' AND f.category=?';p.append(category)
    if query:where+=' AND (f.filename LIKE ? OR f.item_id LIKE ?)';p.extend(['%'+query[:160]+'%']*2)
    total=c.execute('SELECT COUNT(*) FROM file_inventory f '+where,p).fetchone()[0]
    rows=c.execute('''SELECT f.item_id,f.filename,f.category,f.file_role,f.reason,f.extension,f.format,f.bytes,
          s.completeness FROM file_inventory f LEFT JOIN item_sections s ON s.item_id=f.item_id AND s.category=f.category '''+where+
          ''' ORDER BY f.item_id,f.filename LIMIT ? OFFSET ?''',(*p,limit,(page-1)*limit)).fetchall()
    return {'total':total,'page':page,'perpage':limit,'items':[dict(r) for r in rows]}

def metrics(c):
    counts={r['category']:r['n'] for r in c.execute('SELECT category,COUNT(*) n FROM file_inventory GROUP BY category')}
    sections={r['category']:r['n'] for r in c.execute('SELECT category,COUNT(*) n FROM item_sections GROUP BY category')}
    partial=c.execute("SELECT COUNT(*) FROM item_sections WHERE completeness='partial'").fetchone()[0]
    partial_items=c.execute("SELECT COUNT(DISTINCT item_id) FROM item_sections WHERE completeness='partial'").fetchone()[0]
    tracked_items=c.execute('SELECT COUNT(DISTINCT item_id) FROM item_sections').fetchone()[0]
    full_items=max(0,tracked_items-partial_items)
    return {'files':sum(counts.values()),'by_category':counts,'sections':sections,'partial_sections':partial,
            'partial_items':partial_items,'tracked_items':tracked_items,'full_items':full_items,
            'full_percentage':round(100*full_items/tracked_items,1) if tracked_items else None,
            'unknown_files':counts.get('other',0)}
