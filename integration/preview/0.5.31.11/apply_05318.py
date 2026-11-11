#!/usr/bin/env python3
"""0.5.31.8 shared catalogue presentation and Netzkino dialog CSS regression fix.

Additive patch against fully combined 0.5.31.7 source tree. Existing data and
source-specific download/policy APIs remain untouched. No GitHub writes.
"""
import argparse
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent

HTML='''<section id="atlas-source-content" aria-label="Gemeinsamer Film- und Serienkatalog">
  <div class="sectionhead"><div><h2 id="atlas-cross-title">Katalog · Serien</h2>
    <p class="muted">Gleiche Suche, Genres, Karten und Detailansichten für alle Quellen. Angebote und Downloadrechte bleiben getrennt.</p></div></div>
  <form id="atlas-cross-search" aria-label="Katalogsuche und Filter">
    <label><span>Suche</span><input id="atlas-cross-query" aria-label="Film oder Serie suchen" placeholder="Titel oder Serie suchen" maxlength="180"></label>
    <label><span>Genre</span><select id="atlas-cross-genre" aria-label="Nach Genre filtern"><option value="">Alle Genres</option></select></label>
    <label><span>Sortierung</span><select id="atlas-cross-sort" aria-label="Katalog sortieren"><option value="title">Titel A–Z</option><option value="year">Neuere zuerst</option></select></label>
    <button type="submit" class="primary">Suchen</button>
    <button id="atlas-cross-reset" type="button">Filter zurücksetzen</button>
  </form>
  <div class="atlas-uc-kind-bar" role="group" aria-label="Medienart und Seriennavigation">
    <button type="button" data-cross-kind="movies">Filme</button>
    <button type="button" data-cross-kind="series" class="primary">Serien</button>
    <button type="button" id="atlas-cross-back-series" hidden>← Zurück zur Serienliste</button>
    <button type="button" id="atlas-cross-open-portal">Plattformverwaltung</button>
  </div>
  <p id="atlas-cross-status" role="status"></p>
  <div id="atlas-cross-items" class="atlas-uc-grid" aria-label="Katalogtreffer" aria-live="polite"></div>
  <div class="atlas-cross-pager"><button type="button" id="atlas-cross-prev">← Zurück</button><span id="atlas-cross-page"></span><button type="button" id="atlas-cross-next">Weitere →</button></div>
  <p class="muted">Gesamt zeigt Quellenangebote gemeinsam, jedoch ohne ungeprüfte Identitätszusammenführung. Die Reihenfolge wird je angezeigter Seite sortiert; Seiten werden pro Quelle getrennt geladen.</p>
</section>'''

CHANGELOG='''## 0.5.31.8 – Einheitliche Katalognavigation und Detailfenster (Test)
- **Ursachenbehebung Netzkino-Modal:** Globale `aside`-Navigation wirkte ungewollt auf die Detail-Sidebar und versetzte das Cover an den Fensterrand; Sidebar nun `div`, Root-Navigation auf `body > aside` begrenzt. Vollbreiter, responsiver Infobereich mit zweispaltigen Fakten und unverändertem Provenienz-Abgleich.
- **Einheitliche Hauptansicht:** Gesamt / Mediatheken / Netzkino über eine Such-, Genre- und Sortierleiste; gleiche Film-/Serienkarten und Detailaktionen, gemeinsame Ergebnissicht ohne Vermischen der Datenbanken. Serienfolgen von Netzkino bleiben innerhalb des Hauptkatalogs navigierbar.
- **Bestandsschutz:** Der vollständige öffentlich-rechtliche Katalog mit Scanner, Fortschritt, Suchbaum und bisherigen Aktionen bleibt als erweiterter aufklappbarer Bereich erhalten; ArchiveMedia PR #24, Videoaudit PR #23, Netzkino GraphQL, Referenzprüfung und offizieller Player bleiben unverändert.
- **Präzision:** Katalogtreffer pro Quelle paginiert; globale Sortierung über Hunderttausende Werke und automatische Cross-Provider-Werkidentität werden nicht als erledigt behauptet. Pluto TV bleibt eine nicht aktive Quelle.

'''


def exactly(text, old, new, label):
    n=text.count(old)
    if n!=1:raise RuntimeError('%s: erwartete Stelle %s-mal statt einmal; keine Änderung' % (label,n))
    return text.replace(old,new,1)


def patch(project,dry_run=False):
    root=Path(project).resolve()
    required=('web/index.html','web/style.css','web/unified_catalog.js','netzkino.py',
              'server.py','version.py','build_macos.py','archive_companion.py',
              'portal_sources.py','portal_control.py','netzkino_enrichment.py',
              'web/netzkino_detail.js','web/netzkino.js','diagnostic_extensions.py',
              'video_backfill.py','CHANGELOG.md')
    for name in required:
        if not (root/name).is_file():raise RuntimeError('0.5.31.7-Quelle unvollständig: '+name)
    files={name:(root/name).read_text('utf8') for name in
           ('web/index.html','web/style.css','web/unified_catalog.js','netzkino.py',
            'server.py','version.py','build_macos.py','CHANGELOG.md')}
    server=files['server.py'];html=files['web/index.html'];css=files['web/style.css'];net=files['netzkino.py']
    for label in ('/api/netzkino-enrich','/api/netzkino-watch','/api/netzkino-details',
                  '/api/netzkino-grouped','/api/archive-companion','/api/portal-archive-probe',
                  '/api/video-audit'):
        if label not in server:raise RuntimeError('API fehlt: '+label)
    for label in ('id="archive-full-mode"','id="atlas-nk-quickfacts"',
                  'id="atlas-nk-reference"','id="netzkino-view-series"',
                  'id="atlas-source-content"','id="atlas-netzkino-detail"'):
        if label not in html:raise RuntimeError('UI fehlt: '+label)
    if 'VERSION=\'0.5.31.7\'' not in files['version.py']:
        raise RuntimeError('Unerwarteter Versionstand; 0.5.31.7 erforderlich')
    if 'def grouped_catalog(' not in net or 'def _view_rows(' not in net:
        raise RuntimeError('Netzkino-Klassifizierung fehlt')
    # The global rule aside{position:fixed} applied also to the movie modal.
    html=exactly(html,'<aside class="nk-detail-sidebar">','<div class="nk-detail-sidebar">','Nested-aside')
    html=exactly(html,'aria-label="Netzkino-Kurzdaten"></dl></aside>',
                   'aria-label="Netzkino-Kurzdaten"></dl></div>','Nested-aside closing')
    pattern=r'<section id="atlas-source-content" hidden>.*?</section>'
    html,n=re.subn(pattern,HTML,html,count=1,flags=re.S)
    if n!=1:raise RuntimeError('Gemeinsames Katalogfenster nicht eindeutig')
    # This only scopes the two global sidebar declarations, not cards or other elements.
    newcss,n=re.subn(r'(?<![\w.-])aside\{', 'body>aside{', css)
    if n==1:raise RuntimeError('Uneinheitliche globale Sidebar-CSS-Regeln; CSS nicht überschrieben')
    css=newcss+'\n'+(HERE/'web/unified_catalog_05318.css').read_text('utf8')
    server=exactly(server,"offset=q.get('offset',['0'])[0],limit=80)",
        "offset=q.get('offset',['0'])[0],limit=q.get('limit',['80'])[0],\n"
        "                genre=q.get('genre',[''])[0],sort=q.get('sort',['updated'])[0])",'Gruppierte Katalog-API')
    # Adapt only the read-only view and its filters, never the scanner, jobs or tables.
    net=exactly(net,
        "def grouped_catalog(root, *, view='movies', series_key='',query='',origin='all',limit=80,offset=0):",
        "def grouped_catalog(root, *, view='movies', series_key='',query='',origin='all',limit=80,offset=0,genre='',sort='updated'):",
        'View-Signatur')
    net=exactly(net,"    query=str(query or '').strip().casefold()[:180]",
'''    query=str(query or '').strip().casefold()[:180]
    genre=str(genre or '').strip().casefold()[:80]
    sort=sort if sort in ('title','year','updated') else 'updated'
    def genre_tokens(row):
        value=row.get('genres') or ''
        if isinstance(value,str):
            if value.startswith('['):
                try:value=json.loads(value)
                except (TypeError,ValueError):pass
            if isinstance(value,str):value=re.split(r'[,;|·]',value)
        if not isinstance(value,(list,tuple)):return []
        return [str(v).strip().casefold() for v in value if str(v).strip()]
    def genre_match(row):
        return not genre or genre in genre_tokens(row)''','Filter-Parsing')
    net=exactly(net,
        "            'poster':'','year':None,'series_url':'','evidence':classification['evidence'],",
        "            'poster':'','year':None,'genres':row.get('genres') or '',\n            'series_url':'','evidence':classification['evidence'],",
        'Seriengenres')
    net=exactly(net,
        "            if not group['poster']:group['poster']=row.get('poster') or ''",
        "            if not group['poster']:group['poster']=row.get('poster') or ''\n"
        "            if not group['genres']:group['genres']=row.get('genres') or ''",
        'Episodengenres')
    net=exactly(net,
        "    if view=='movies':\n        rows=[r for r in movies if not query or query in r['title'].casefold()]",
        "    if view=='movies':\n        rows=[r for r in movies if (not query or query in r['title'].casefold()) and genre_match(r)]",
        'Filmgenre')
    net=exactly(net,
        "             if not query or query in group['title'].casefold() or any(query in e['title'].casefold() for e in group['children'])]",
        "             if (not query or query in group['title'].casefold() or any(query in e['title'].casefold() for e in group['children']))\n"
        "             and (genre_match(group) or any(genre_match(e) for e in group['children']))]",
        'Seriengenre')
    net=exactly(net,
        "        rows=[] if group is None else [r for r in group['children'] if not query or query in r['title'].casefold()]",
        "        rows=[] if group is None else [r for r in group['children'] if (not query or query in r['title'].casefold()) and genre_match(r)]",
        'Episodengenre')
    net=exactly(net,
        "    counts={'movies':len(movies),'series':len(series),",
'''    if sort=='title' and view!='episodes':
        rows.sort(key=lambda r:r['title'].casefold())
    elif sort=='year' and view!='episodes':
        rows.sort(key=lambda r:(-int(r.get('year') or 0),r['title'].casefold()))
    available_genres=sorted({g for r in movies for g in genre_tokens(r)} |
        {g for group in series.values() for g in genre_tokens(group)} |
        {g for group in series.values() for child in group['children'] for g in genre_tokens(child)})
    counts={'movies':len(movies),'series':len(series),''','Sortierung/Genres')
    net=exactly(net,
        "            'view':view,'counts':counts,'series':group_header}",
        "            'view':view,'counts':counts,'series':group_header,'genres':available_genres}",
        'Genres im Ergebnis')
    version=exactly(files['version.py'],"VERSION='0.5.31.7'","VERSION='0.5.31.8'",'Version')
    build=exactly(files['build_macos.py'],"'CFBundleVersion':'517'","'CFBundleVersion':'518'",'Buildnummer')
    result={'web/index.html':html,'web/style.css':css,
            'web/unified_catalog.js':(HERE/'web/unified_catalog.js').read_text('utf8'),
            'netzkino.py':net,'server.py':server,'version.py':version,
            'build_macos.py':build,'CHANGELOG.md':CHANGELOG+files['CHANGELOG.md']}
    if dry_run:
        print('0.5.31.8: gemeinsame Ansicht und Nested-aside-Fix geprüft; keine Schreiboperation')
        return sorted(result)
    for path,content in result.items():
        (root/path).write_text(content,'utf8')
    print('0.5.31.8: UI und lesende Genre/Sortierung integriert; ArchiveMedia/Scanner/DB unberührt')
    return sorted(result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('project');p.add_argument('--dry-run',action='store_true')
    a=p.parse_args();patch(a.project,a.dry_run)
