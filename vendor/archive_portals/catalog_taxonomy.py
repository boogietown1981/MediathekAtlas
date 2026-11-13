"""Conservative, evidence-labeled media subclasses. No subtype is inferred from item language alone."""
from __future__ import annotations
import re
from pathlib import PurePosixPath

SUBTYPES={
 'audio':('music','audiobook','podcast','radio','speech','unknown'),
 'software':('windows','macos','linux','android','ios','multi','unknown'),
 'documents':('book','pdf','ebook','word','spreadsheet','presentation','text','comic','other','unknown'),
}
_EXT={
 'windows':{'.exe','.msi','.msix','.appx','.cab','.msu','.msm'},
 'macos':{'.dmg','.pkg'},
 'linux':{'.deb','.rpm','.appimage','.flatpak','.snap'},
 'android':{'.apk'},'ios':{'.ipa'},
 'ebook':{'.epub','.mobi','.azw','.azw3'},
 'word':{'.doc','.docx','.odt','.rtf','.pages'},
 'spreadsheet':{'.xls','.xlsx','.xlsm','.ods','.csv','.tsv','.numbers'},
 'presentation':{'.ppt','.pptx','.odp','.key'},
 'text':{'.txt','.md','.tex'}, 'comic':{'.cbz','.cbr'},
 'pdf':{'.pdf'},
}

def classify_entry(category,metadata,files):
    """Classify the *upload*, not every file. Conflicting OS families => multi.
    Return conservative (subtype, documented signal). Never claim program compatibility
    on the strength of an ambiguous ZIP/ISO extension alone.
    """
    if category not in SUBTYPES:raise ValueError('unknown category')
    extensions={PurePosixPath(str(f.get('name',''))).suffix.casefold() for f in files}
    hint=' '.join(str(metadata.get(k) or '') if not isinstance(metadata.get(k),list) else ' '.join(map(str,metadata[k])) for k in ('title','subject','description','collection')).casefold()[:1800]
    if category=='software':
        seen={label for label in ('windows','macos','linux','android','ios') if extensions & _EXT[label]}
        # Only explicit contextual platform terms are allowed when no specific installer is found.
        if not seen:
            for label,pat in {'windows':r'\bwindows\b|\bwin(?:32|64)\b', 'macos':r'\bmac\s?os\b|\bmacintosh\b|\bos\s?x\b',
                              'android':r'\bandroid\b', 'ios':r'\bios\b|\biphone\b|\bipad\b',
                              'linux':r'\blinux\b|\bubuntu\b|\bdebian\b'}.items():
                if re.search(pat,hint):seen.add(label)
            reason='Explizite Plattformangabe im Archive.org-Text' if seen else 'Keine eindeutige Plattform'
        else:reason='Installationsdateiendung(en)'
        return ('multi' if len(seen)>1 else next(iter(seen)) if seen else 'unknown',reason)
    if category=='documents':
        if (metadata.get('isbn') or re.search(r'\b(?:isbn|book|ebook|buch|libro|livre)\b',hint)) and extensions & (_EXT['ebook']|_EXT['pdf']):
            return 'book','Buchhinweis und Buch-/PDF-Dateiformat'
        seen={k for k in ('ebook','word','spreadsheet','presentation','text','comic','pdf') if extensions & _EXT[k]}
        if len(seen)==1:return next(iter(seen)),'Dateiendung(en)'
        if not seen:return 'unknown','Kein unterstützter Dokumenttyp'
        # PDF plus DOCX etc is usually one book in multiple formats; do not invent a type.
        return 'other','Verschiedene Dokumentformate im selben Upload'
    if category=='audio':
        for kind,pat in {'audiobook':r'\baudio\s?book\b|\bh[oö]rbuch\b',
                         'podcast':r'\bpodcast\b', 'radio':r'\bradio\b|\bbroadcast\b',
                         'speech':r'\bspeech\b|\blecture\b|\bvortrag\b'}.items():
            if re.search(pat,hint):return kind,'Themenangabe des Archive.org-Uploads'
        if metadata.get('album') or metadata.get('artist'):
            return 'music','Explizite Künstler-/Albumangabe'
        return 'unknown','Audioinhalt nicht ausreichend zugeordnet'
    return 'unknown','Ohne Beleg'
