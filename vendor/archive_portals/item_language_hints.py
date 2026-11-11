# Evidence-labeled language hints from Internet Archive *item* metadata.
# Item language, upload-title dubbing claims, and actual audio tracks are separate.

from __future__ import annotations
import re
from vendor.archivemedia.linguistics import normalize_language

LATAM=re.compile(r"(?i)\b(?:espa[nñ]ol\s+(?:latino(?:americano)?|latam)|spanish\s+(?:latin\s+america(?:n)?|latam)|latino\s+dub|doblaje\s+latino|audio\s+latino)\b")
CASTELLANO=re.compile(r"(?i)\b(?:castellano|espa[nñ]ol\s+de\s+espa[nñ]a)\b")
ES_AUDIO=re.compile(r"(?i)\b(?:en\s+espa[nñ]ol(?:\s+latino(?:americano)?)?|audio\s+(?:en\s+)?espa[nñ]ol|doblad[oa]\s+(?:al\s+)?espa[nñ]ol|spanish\s+(?:audio|dub(?:bed)?)|espa[nñ]ol\s+doblado)\b")
SUB_ONLY=re.compile(r"(?i)\b(?:subtitulado|subtitulada|subt[ií]tulos?|subbed|subtitles?|subs?|vose|vostfr|hardsub|softsub)\b")
ES_SUB=re.compile(r"(?i)(?:\b(?:subtitulado|subtitulada|subt[ií]tulos?)\s+(?:en\s+)?espa[nñ]ol\b|\bspanish\s+subs?\b)")


def _as_text(value):
    if isinstance(value,(list,tuple)):return ' '.join(str(x) for x in value if x is not None)
    return str(value or '')


def _item_codes(value):
    # Metadata.language is ABOUT THE ITEM, not a confirmed audio language.
    values=value if isinstance(value,(list,tuple)) else re.split(r'[,;|]',_as_text(value))
    codes=[]
    for raw in values:
        code=normalize_language(str(raw).strip())
        if code and code not in codes:codes.append(code)
    return codes


def infer(metadata):
    title=_as_text(metadata.get('title'))[:400]
    langs=_item_codes(metadata.get('language'))
    region='LatAm' if LATAM.search(title) else 'ES' if CASTELLANO.search(title) else ''
    spanish=bool(ES_AUDIO.search(title) or CASTELLANO.search(title) or LATAM.search(title))
    explicit_sub=bool(ES_SUB.search(title))
    # A title that says 'Spanish SUB' without a dubbing marker is not Spanish audio.
    sub_only=bool(SUB_ONLY.search(title)) and not re.search(r'(?i)\b(?:doblaje|doblad[oa]|audio|dubbed|dub)\b',title)
    audio=[];source='';reason=''
    if spanish and not (sub_only or explicit_sub):
        audio=['es']
        source='archive-title+item-language' if 'es' in langs else 'archive-title'
        reason='Upload bezeichnet die Fassung als spanisch; technische Audiospur nicht geprüft'
    subs=['es'] if explicit_sub else []
    return {'archive_language_codes':','.join(langs),
            'audio_hint_languages':','.join(audio),'audio_hint_region':region if audio else '',
            'audio_hint_source':source,'audio_hint_reason':reason,
            'subtitle_hint_languages':','.join(subs),
            'subtitle_hint_source':'archive-title' if subs else ''}


FIELDS=('archive_language_codes','audio_hint_languages','audio_hint_region',
        'audio_hint_source','audio_hint_reason','subtitle_hint_languages','subtitle_hint_source')


def apply_to_item(c,identifier,metadata):
    info=infer(metadata)
    params=[info[key] for key in FIELDS]+[identifier]
    c.execute('UPDATE variants SET '+','.join(k+'=?' for k in FIELDS)+' WHERE item_id=?',params)
    return info


def backfill(c):
    # Offline only: use cached metadata.
    row=c.execute("SELECT value FROM catalog_meta WHERE key='item_language_hint_schema'").fetchone()
    if row and row[0]=='1':return 0
    total=0
    for item in c.execute("SELECT i.id,i.title,i.language FROM items i WHERE EXISTS(SELECT 1 FROM variants v WHERE v.item_id=i.id)").fetchall():
        apply_to_item(c,item['id'],{'title':item['title'],'language':item['language']})
        total+=1
    c.execute("INSERT INTO catalog_meta(key,value) VALUES('item_language_hint_schema','1') ON CONFLICT(key) DO UPDATE SET value='1'")
    return total
