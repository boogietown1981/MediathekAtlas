#!/usr/bin/env python3
"""0.5.31.10: reliable in-app Netzkino watch + honest home-page catalog coverage.

Applies after 0.5.31.9; strictly source-only. This does not create download
rights, guess private GraphQL operations, or modify any user database.
"""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent
CHANGELOG='''## 0.5.31.10 – In-App-Wiedergabe und ehrliche Katalogabdeckung (Test)
- „Ansehen“ ruft den offiziellen Netzkino-Player in einem nativen WebKit-Fenster innerhalb der lokalen macOS-Anwendung auf. Es erfolgt kein automatischer Browser-Redirect mehr. Fehlende WebKit-Unterstützung wird verständlich gemeldet; „Beim Anbieter öffnen“ bleibt eine separate manuelle Aktion.
- Im gemeinsamen Hauptkatalog und im Plattformkatalog wird „▶ Ansehen“ direkt angeboten. Eine Serienkarte führt weiterhin zur Folgenübersicht.
- Der Netzkino-Abgleich wird nicht mehr als vollständiger Gesamtkatalog bezeichnet: Der aktuelle Adapter kennt kuratierte Startseitenkategorien mit oftmals 20 Elementen. Diagnose zählt Kategorien am beobachteten Anzeigelimit. Es wird keine unbelegte GraphQL-Paginierung erfunden, keine fehlenden 1.700 Titel behauptet und kein Katalogeintrag entfernt.
- Die separate Verwaltung ausdrücklich lizenzierter Dateien bleibt im aufklappbaren Expertenbereich erhalten, wird aber nicht mehr als regulärer Netzkino-Filmdownload dargestellt. Weiterhin keine Freigabe zur Aufzeichnung werbefinanzierter Streams/Umgehung von Schutzmaßnahmen.
- Bestehende Mediatheken-, IMDb/TMDB/TVDB-, Videoaudit-, Serien- und ArchiveMedia-Funktionen bleiben erhalten. Keine automatische GitHub-Schreiboperation.

'''


def one(s, old, new, label):
    count=s.count(old)
    if count!=1:raise RuntimeError(f'{label}: erwarteter Einbausatz {count}-mal statt einmal; Quellstand nicht verändert')
    return s.replace(old,new,1)


def patch(project,dry_run=False):
    p=Path(project).resolve()
    required=('server.py','netzkino.py','diagnostic_extensions.py','web/netzkino.js','web/netzkino_detail.js',
              'web/unified_catalog.js','web/index.html','web/style.css','build_macos.py',
              'version.py','CHANGELOG.md','archive_companion.py','portal_control.py',
              'netzkino_downloads.py','yt_dlp_probe.py','netzkino_enrichment.py','netzkino_webplayer.swift')
    for name in required:
        if not (p/name).is_file():raise RuntimeError('Version 0.5.31.9 unvollständig: '+name)
    d={name:(p/name).read_text('utf-8') for name in required if name not in (
        'archive_companion.py','portal_control.py','netzkino_downloads.py',
        'yt_dlp_probe.py','netzkino_enrichment.py')}
    if "VERSION='0.5.31.9'" not in d['version.py']:
        raise RuntimeError('Ausgangsversion muss 0.5.31.9 sein')
    for tag in ('/api/netzkino-downloads','/api/archive-companion','/api/netzkino-watch',
                '/api/netzkino-metadata-probe','/api/video-audit','/api/netzkino-enrich'):
        if tag not in d['server.py']:raise RuntimeError('Bestehende API verloren: '+tag)
    for tag in ('id="archive-full-mode"','id="atlas-nk-downloads"',
                'id="atlas-nk-reference"','data-catalog-source="all"'):
        if tag not in d['web/index.html']:raise RuntimeError('Bestandsschutz UI fehlt: '+tag)
    if 'window.AtlasNetzkinoDownloads' not in d['web/netzkino_detail.js']:
        raise RuntimeError('Bestehende Datei-Queue-UI fehlt')
    n=d['netzkino.py']
    n=one(n,"'catalog_scope':'Öffentlich sichtbare Startseiten- und Kategorieelemente; keine Vollständigkeitsgarantie',",
          "'catalog_scope':'Kuratierte Startseiten-Kategorien, nicht der vollständige Netzkino-Katalog',\n            'coverage_status':'startpage_only',\n            'category_cap_hits':int(_get(db,'category_cap_hits','0')),",
          'Unvollständiger Anbieter-Katalog')
    n=one(n,"('categories_empty',0),('category_error_types','{}'),",
          "('categories_empty',0),('category_cap_hits',0),('category_error_types','{}'),",
          'Kategoriegrenzen zurücksetzen')
    n=one(n,"    stopped_for_access=False\n    stopped_for_budget=False",
          "    cap_hits=0\n    stopped_for_access=False\n    stopped_for_budget=False",
          'Kategoriegrenz-Zähler')
    n=one(n,"                    content=category.get('content')\n                    if content is None",
          "                    content=category.get('content')\n                    # 20 is the observed homepage-category card limit (HAR), not a proven API page size.\n                    if isinstance(content,dict) and isinstance(content.get('nodes'),list) and len(content['nodes'])>=20:\n                        cap_hits+=1\n                    if content is None",
          'Sichtbare Kategorielimit-Erkennung')
    n=one(n,"('categories_empty',empty),('category_error_types',json.dumps(error_types,sort_keys=True)),",
          "('categories_empty',empty),('category_cap_hits',cap_hits),('category_error_types',json.dumps(error_types,sort_keys=True)),",
          'Persistierte Kategoriegrenzen')
    n=one(n,"category_errors=failures,partial=partial)",
          "category_errors=failures,category_cap_hits=cap_hits,partial=partial,coverage_status='startpage_only')",
          'Diagnose-Event Katalogabdeckung')
    n=one(n,"'category_errors':failures,'categories_empty':empty,\n                    'error_types':error_types,'partial':partial,'ok':True}",
          "'category_errors':failures,'categories_empty':empty,'category_cap_hits':cap_hits,\n                    'coverage_status':'startpage_only','error_types':error_types,'partial':partial,'ok':True}",
          'Katalogabgleich-Resultat')
    d['netzkino.py']=n
    diagnostic=d['diagnostic_extensions.py']
    diagnostic=one(diagnostic, "'categories_empty','category_error_types','last_result'",
                   "'categories_empty','category_cap_hits','category_error_types','last_result'",
                   'Offline-Diagnose liest Kategoriegrenzen')
    diagnostic=one(diagnostic,"categories_empty=_int(values.get('categories_empty')),",
                   "categories_empty=_int(values.get('categories_empty')),\n                          category_cap_hits=_int(values.get('category_cap_hits')),\n                          coverage_status='startpage_only',",
                   'Export der tatsächlichen Startseitenabdeckung')
    d['diagnostic_extensions.py']=diagnostic

    js=d['web/netzkino.js']
    js=one(js,"status.last_result === 'complete' ? 'Vollständig abgefragt' :",
          "status.last_result === 'complete' ? 'Startseiten-Abgleich erfolgreich (Gesamtkatalog nicht vollständig)' :",
          'Ehrlicher Status')
    js=one(js,"` · Fehler ${status.category_errors || 0} · Leer ${status.categories_empty || 0}` : '';",
          "` · Fehler ${status.category_errors || 0} · Leer ${status.categories_empty || 0}` +\n        ` · Am beobachteten 20-Titel-Limit ${status.category_cap_hits || 0}` : '';",
          'Kategoriegrenz-Hinweis')
    js=one(js,"const open = make('a', '▶ Bei Netzkino ansehen', 'netzkino-open');\n        open.href = isGroup ? item.series_url : item.url;\n        if (isGroup && !item.series_url) open.hidden = true;\n        open.target = '_blank'; open.rel = 'noopener noreferrer';\n        actions.append(open);",
          "const play = make('button', '▶ In MediathekAtlas ansehen', 'netzkino-open');\n        play.type = 'button';\n        play.hidden = isGroup; // open a series via its episode list, not an arbitrary series URL\n        play.onclick = async () => {\n          play.disabled = true;\n          try { await window.AtlasNetzkinoDetail.play(item.id); }\n          catch (e) { message('Integrierte Wiedergabe nicht verfügbar: ' + e.message, true); }\n          finally { play.disabled = false; }\n        };\n        actions.append(play);",
          'Plattformkarten ohne Browser-Automatik')
    d['web/netzkino.js']=js

    details=d['web/netzkino_detail.js']
    details=one(details,"  let currentId = null;\n  async function open(id) {",
          "  let currentId = null;\n  async function play(id) {\n    if (!/^[a-f0-9]{32}$/.test(String(id || ''))) throw new Error('Ungültiger Film');\n    const result = await window.api('netzkino-watch', {id});\n    if (result.mode !== 'native_webkit')\n      throw new Error('Der native Netzkino-WebKit-Player ist auf diesem Mac nicht installiert. Die offizielle Filmseite kann weiterhin separat geöffnet werden.');\n    return result;\n  }\n  async function open(id) {",
          'Gemeinsame In-App-Wiedergabefunktion')
    details=one(details,"""          const result = await window.api('netzkino-watch', {id});
          if (result.mode === 'official_browser') {
            const popup = window.open(result.page_url, '_blank', 'noopener,noreferrer');
            $('atlas-nk-evidence').textContent = popup ? 'Offizielle Filmseite im Browser geöffnet.' :
              'WebKit-Helfer nicht verfügbar. Bitte „Beim Anbieter öffnen“ wählen, falls der Browser das Pop-up blockiert.';
          } else {
            $('atlas-nk-evidence').textContent = 'Der offizielle Netzkino-Player wurde im separaten macOS-Fenster geöffnet.';
          }""",
          """          await play(id);
          $('atlas-nk-evidence').textContent = 'Der offizielle Netzkino-Player läuft im separaten macOS-WebKit-Fenster innerhalb von MediathekAtlas.';""",
          'Kein automatischer Browser-Fallback')
    details=one(details,'  window.AtlasNetzkinoDetail = {open};','  window.AtlasNetzkinoDetail = {open, play};','Playback-API')
    d['web/netzkino_detail.js']=details

    unified=d['web/unified_catalog.js']
    unified=one(unified,"    actions.append(details);\n    if (item.source==='netzkino') actions.append(el('small','Offizielle Wiedergabe · keine Downloadfreigabe'));",
          """    actions.append(details);
    if (item.source==='netzkino' && item.kind!=='series') {
      const watch=el('button','▶ Ansehen','atlas-uc-play');watch.type='button';
      watch.onclick=async()=>{
        watch.disabled=true;
        try {await window.AtlasNetzkinoDetail.play(item.id);}
        catch(e){$('atlas-cross-status').textContent='Integrierte Wiedergabe: '+e.message;}
        finally{watch.disabled=false;}
      };
      actions.append(watch);
    }
    if (item.source==='netzkino') actions.append(el('small','Offizieller Player im Mac-Fenster · kein Stream-Mitschnitt'));""",
          'Direktes Ansehen in Gesamtansicht')
    unified=one(unified,"notes.push('Netzkino: '+data.total+' Treffer'+(seriesKey?' · '+seriesTitle:''));",
          "notes.push('Netzkino: '+data.total+' Treffer · Startseitenindex, kein vollständiger Gesamtkatalog'+(seriesKey?' · '+seriesTitle:''));",
          'Ehrlicher Umfang auch im gemeinsamen Katalog')
    d['web/unified_catalog.js']=unified

    server=d['server.py']
    server=one(server,"""                diagnostics.event('netzkino_official_player',mode='official_browser')
                return self.send({'mode':'official_browser','page_url':page})""",
          """                diagnostics.event('netzkino_official_player',mode='native_unavailable')
                return self.send({'mode':'native_unavailable'})""",
          'In-App-Wiedergabe ohne stillen Browserredirect')
    d['server.py']=server

    swift=d['netzkino_webplayer.swift']
    swift=one(swift,'            NSWorkspace.shared.open(url)\n            decisionHandler(.cancel)',
          '            // User-selected off-domain links never launch Safari automatically.\n            decisionHandler(.cancel)',
          'Externe Playernavigation blockieren')
    swift=one(swift,'        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }\n        return nil',
          '        // Provider pop-ups are not needed for normal playback; do not redirect outside MediathekAtlas.\n        if let url = navigationAction.request.url, validPage(url) { webView.load(URLRequest(url: url)) }\n        return nil',
          'In-App-Popups')
    d['netzkino_webplayer.swift']=swift

    html=d['web/index.html']
    html=one(html,'<summary>Download / Offline-Nutzung</summary>',
          '<summary>Expertenfunktion: separat lizenzierte Videodateien (kein Netzkino-Stream-Download)</summary>',
          'Keine irreführende Downloadbenennung')
    d['web/index.html']=html
    d['version.py']=one(d['version.py'],"VERSION='0.5.31.9'","VERSION='0.5.31.10'",'Versionsnummer')
    d['build_macos.py']=one(d['build_macos.py'],"'CFBundleVersion':'519'","'CFBundleVersion':'520'",'macOS Buildnummer')
    d['CHANGELOG.md']=CHANGELOG+d['CHANGELOG.md']
    if dry_run:
        print('0.5.31.10: In-App-Player, 20er-Kategorielimits, Bestandsschutz: OK')
        return sorted(d)
    for name,content in d.items():
        target=p/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,'utf-8')
    print('0.5.31.10: WebKit-Wiedergabe ohne automatische Browserweiterleitung + Katalogabdeckung integriert')
    return sorted(d)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();patch(args.root,args.dry_run)
