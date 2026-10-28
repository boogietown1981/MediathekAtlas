"""Language/track evidence extraction. Signals are conservative: no guessing audio from item language."""
import re
import json
from pathlib import PurePosixPath

ALIASES = {
    'de': ('de', 'deu', 'ger', 'german', 'deutsch', 'alemán', 'aleman', 'allemand'),
    'en': ('en', 'eng', 'english', 'englisch', 'inglés', 'ingles', 'anglais'),
    'es': ('es', 'spa', 'esp', 'spanish', 'español', 'espanol', 'spanisch', 'castellano'),
    'ja': ('ja', 'jpn', 'jp', 'jap', 'japanese', 'japanisch', 'japonés', 'japones', 'japonais'),
    'fr': ('fr', 'fra', 'fre', 'french', 'français', 'francais', 'französisch'),
    'it': ('it', 'ita', 'italian', 'italiano', 'italienisch'),
    'pt': ('pt', 'por', 'portuguese', 'português', 'portugues'),
    'ko': ('ko', 'kor', 'korean', 'koreanisch'),
    'zh': ('zh', 'chi', 'zho', 'cn', 'chinese', 'mandarin', 'chinesisch'),
    'ru': ('ru', 'rus', 'russian', 'russisch'),
    'ar': ('ar', 'ara', 'arabic', 'arabisch'),
    'nl': ('nl', 'nld', 'dut', 'dutch', 'niederländisch'),
    'pl': ('pl', 'pol', 'polish', 'polnisch'),
    'tr': ('tr', 'tur', 'turkish', 'türkisch', 'turkce', 'türkçe'),
    'hi': ('hi', 'hin', 'hindi'),
    'sv': ('sv', 'swe', 'swedish', 'schwedisch'),
    'da': ('da', 'dan', 'danish', 'dänisch'),
    'fi': ('fi', 'fin', 'finnish', 'finnisch'),
    'no': ('no', 'nor', 'norwegian', 'norwegisch'),
    'cs': ('cs', 'ces', 'cze', 'czech', 'tschechisch'),
    'uk': ('uk', 'ukr', 'ukrainian', 'ukrainisch'),
    'th': ('th', 'tha', 'thai'),
    'vi': ('vi', 'vie', 'vietnamese'),
    'id': ('id', 'ind', 'indonesian'),
}
NAME = dict(de='Deutsch',en='Englisch',es='Spanisch',ja='Japanisch',fr='Französisch',it='Italienisch',pt='Portugiesisch',ko='Koreanisch',zh='Chinesisch',ru='Russisch',ar='Arabisch',nl='Niederländisch',pl='Polnisch',tr='Türkisch',hi='Hindi',sv='Schwedisch',da='Dänisch',fi='Finnisch',no='Norwegisch',cs='Tschechisch',uk='Ukrainisch',th='Thai',vi='Vietnamesisch',id='Indonesisch')
ALIAS_TO_CODE = {alias.casefold():code for code,aliases in ALIASES.items() for alias in aliases}
# Do not treat bare "it", "no", "hi", "ar", "cn" as language tokens: common words and format abbreviations.
AMBIGUOUS = {'it', 'no', 'hi', 'ar', 'cn', 'jp', 'fr', 'es', 'de', 'en', 'pt', 'id'}
SUB_EXT = {'.srt','.ass','.ssa','.vtt','.sub','.smi','.sbv','.ttml'}


def normalize_language(value):
    if not value:
        return None
    v=str(value).strip().casefold().replace('_','-')
    if v in ('und','unknown','unk','mul','multi','zxx','none','n/a','undefined'):
        return None
    v=v.split('-',1)[0]
    return ALIAS_TO_CODE.get(v)


def language_codes(text, allow_ambiguous=False):
    """Recognize isolated words and codes, not substrings in unrelated names."""
    found=[]
    for token in re.findall(r'[^\W_]+', str(text or '').casefold(),flags=re.UNICODE):
        if token in AMBIGUOUS and not allow_ambiguous:continue
        code=normalize_language(token)
        if code and code not in found:found.append(code)
    return found


def parse_filename_tracks(filename):
    """Extract only *explicit filename claims* about audio and subtitle languages.

    Natural language in a title must NEVER turn into a claimed audio language just
    because a generic (Dub)/(Dublado) marker happens to be nearby.
    """
    stem=PurePosixPath(str(filename)).stem
    stem=re.sub(r'(?i)\.ia$', '', stem)
    tokens=re.findall(r'[^\W_]+',stem.casefold().replace('_',' '),flags=re.UNICODE)
    audio=[]; subs=[]
    dub_tokens={'dub','dubbed','dublado','dublada','doblado','doblada',
                'synchronisiert','synchro','audio','tonspur','voices','voice'}
    sub_tokens={'sub','subs','subbed','subtitle','subtitles','untertitel',
                'subtitulado','subtitulada','vost','vostfr','hardsub','softsub'}
    def add(target,token):
        lang=normalize_language(token)
        if lang and lang not in target:target.append(lang)
    # Only directly adjacent explicit LANGUAGE + AUDIO/SUB or AUDIO/SUB + LANGUAGE.
    # E.g. 'Hagure Yuusha no Estetica (Dub)' is NOT Norwegian audio.
    for i,t in enumerate(tokens):
        lang=normalize_language(t)
        if not lang or len(t)<=2:continue
        # When between two markers, assign language to the NEXT marker:
        # 'JPN DUB ENG SUB' => ENG belongs to SUB, not DUB.
        following=tokens[i+1] if i+1<len(tokens) else None
        preceding=tokens[i-1] if i else None
        if following in dub_tokens:add(audio,t)
        elif following in sub_tokens:add(subs,t)
        elif preceding in dub_tokens:add(audio,t)
        elif preceding in sub_tokens:add(subs,t)
    # Dedicated compound forms: GERdub, EnglishSub, JapAudio.
    aliases=sorted((x for x in ALIAS_TO_CODE if len(x)>=3),key=len,reverse=True)
    expr='|'.join(re.escape(x) for x in aliases)
    for m in re.finditer(r'(?i)(?<![a-z])('+expr+r')(dubbed|dub|subbed|subs|sub|audio)(?![a-z])',stem):
        add(subs if m.group(2).lower().startswith('sub') else audio,m.group(1))
    # Short country codes are unambiguous only when delimiters explicitly mark
    # stream metadata, e.g. [DE-DUB] or [EN-SUB], not prose in parentheses.
    for marker in re.finditer(r'(?i)[\[(]\s*(DE|EN|ES|FR|IT|PT|JA|JP|NO|DA|SV|FI)\s*[-_. ]\s*(DUB|AUDIO|SUB|SUBS)\s*[\])]',stem):
        add(audio if marker.group(2).lower() in ('dub','audio') else subs,marker.group(1))
    for marker in re.finditer(r'(?i)[\[(]\s*(DUB|AUDIO|SUB|SUBS)\s*[-_. ]\s*(DE|EN|ES|FR|IT|PT|JA|JP|NO|DA|SV|FI)\s*[\])]',stem):
        add(audio if marker.group(1).lower() in ('dub','audio') else subs,marker.group(2))
    # A dual-audio declaration alone says >=2 tracks, NOT which language.
    # Names must be in a structured block adjacent to the declaration.
    dual=bool(re.search(r'(?i)\bdual[ -]?(?:audio|dub)\b',stem))
    multi=bool(re.search(r'(?i)\bmulti[ -]?(?:audio|dub|sub)|\bmultilang\b',stem))
    for i,t in enumerate(tokens):
        if t not in ('dual','multi') or i+1>=len(tokens) or tokens[i+1]!='audio':continue
        for j in range(i+2,min(i+9,len(tokens))):
            if tokens[j] in sub_tokens|dub_tokens:break
            if j+1<len(tokens) and tokens[j+1] in sub_tokens:break
            if len(tokens[j])>=3:add(audio,tokens[j])
    for m in re.finditer(r'(?i)\b(?:dual|multi)[ _.-]*audio[ _.-]*[\[(]([^\])]{3,90})[\])]',stem):
        for word in re.findall(r'[^\W_]+',m.group(1).casefold(),flags=re.UNICODE):
            if len(word)>=3:add(audio,word)
    audio_mode=('dual' if dual and len(audio)>=2 else
                'multi' if multi and len(audio)>=2 else
                'multi' if len(audio)>1 else 'dub' if audio else
                'dual-unknown' if dual else 'multi-unknown' if multi else 'unknown')
    sub_mode='multi' if len(subs)>1 else 'sub' if subs else ('sub-unknown' if any(x in tokens for x in sub_tokens) else 'unknown')
    hardsub=bool(re.search(r'(?i)hard[ ._-]*sub|burned[ ._-]*in',stem))
    return {'audio':audio,'subtitles':subs,'audio_mode':audio_mode,'subtitle_mode':sub_mode,
            'audio_origin':'filename' if audio else 'unknown',
            'subtitle_origin':'filename' if subs else 'unknown',
            'hardcoded_subtitles':hardsub}


def match_sidecar_subtitles(video_filename,files):
    """Sidecar captions are only matched on filename stem (never all SRTs in item)."""
    video=PurePosixPath(video_filename)
    video_stem=video.stem.casefold()
    def core(stem):
        parts=[t for t in re.split(r'[. _-]+',stem.casefold()) if t]
        marker={'dub','dubbed','sub','subs','subbed','subtitle','subtitles','dual','multi','audio','hardsub','softsub','1080p','720p','2160p','480p','bluray','dvdrip','webrip','x264','x265','hevc','hdr','repack','proper'}
        while len(parts)>1 and (parts[-1] in marker or normalize_language(parts[-1])):parts.pop()
        return '.'.join(parts)
    video_core=core(video_stem)
    results=[]
    for f in files:
        fname=str(f.get('name',''))
        subtitle=PurePosixPath(fname)
        if subtitle.suffix.casefold() not in SUB_EXT:continue
        if str(subtitle.parent).casefold() != str(video.parent).casefold():continue
        sub_stem=subtitle.stem.casefold()
        # Only same base + optional language/modifier suffix; avoid S01E02 sidecar matching S01E01.
        if not (sub_stem==video_stem or sub_stem.startswith(video_stem+'.') or sub_stem.startswith(video_stem+'_') or sub_stem.startswith(video_stem+'-') or (video_core and core(sub_stem)==video_core)):continue
        suffix=sub_stem[len(video_stem):] if sub_stem.startswith(video_stem) else sub_stem[len(video_core):]
        langs=language_codes(suffix,allow_ambiguous=True)
        results.append({'name':fname,'languages':langs,'format':subtitle.suffix[1:].lower(),'size':f.get('size')})
    return results


def csv_codes(value):
    if not value:return []
    try:
        entries=json.loads(value)
        if isinstance(entries,list):return sorted(set(filter(None,(normalize_language(x) for x in entries))))
    except (TypeError,ValueError):pass
    return sorted(set(filter(None,(normalize_language(x) for x in str(value).split(',')))))


def csv(values):return ','.join(sorted(set(v for v in values if v in NAME)))
