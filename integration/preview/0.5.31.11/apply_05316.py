#!/usr/bin/env python3
"""Source-only integration of on-demand details, yt-dlp probe and cross-source UI.

After apply_05315. Patch is atomic per source tree (preflight first) and never
reads/writes an app's actual user data, background tasks or GitHub refs.
"""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent

SOURCE_TABS='''<div class="atlas-source-switch" role="group" aria-label="Katalogquelle">
  <strong>Katalog</strong>
  <button type="button" data-catalog-source="all">Gesamt</button>
  <button type="button" data-catalog-source="mediatheken" class="primary">Mediatheken</button>
  <button type="button" data-catalog-source="netzkino">Netzkino</button>
</div>
<section id="atlas-source-content" hidden>
  <h2>Netzkino · Filme und Serien</h2>
  <p class="muted">Eigene Katalogquelle; gleiche Detailfelder, keine ungeprüfte Zusammenführung und keine automatische Downloadberechtigung.</p>
  <form id="atlas-cross-search"><input id="atlas-cross-query" aria-label="Gesamtkatalog durchsuchen" placeholder="Filme und Serien suchen"><button type="submit">Suchen</button></form>
  <div class="atlas-source-switch" role="group" aria-label="Netzkino-Medienart">
    <button type="button" data-cross-kind="movies" class="primary">Filme</button>
    <button type="button" data-cross-kind="series">Serien</button>
    <button type="button" id="atlas-cross-open-portal">Netzkino-Katalogverwaltung öffnen</button>
  </div>
  <p id="atlas-cross-status" role="status"></p>
  <div id="atlas-cross-items" class="nk-unified-grid"></div>
  <div class="atlas-cross-pager"><button type="button" id="atlas-cross-prev">← Zurück</button><span id="atlas-cross-page"></span><button type="button" id="atlas-cross-next">Weitere →</button></div>
</section>
'''
DIALOG='''<dialog id="atlas-netzkino-detail" aria-label="Netzkino Film- und Seriendetails">
  <div class="nk-detail-heading"><h2 id="atlas-nk-title">Netzkino-Details</h2><button type="button" id="atlas-nk-close" aria-label="Schließen">✕</button></div>
  <div class="nk-detail-layout"><img id="atlas-nk-image" alt="Filmcover" hidden>
    <div><p id="atlas-nk-description"></p><dl id="atlas-nk-facts"></dl>
      <p id="atlas-nk-evidence" role="status"></p><div id="atlas-nk-validation" role="status"></div>
      <div id="atlas-nk-actions"></div>
    </div>
  </div>
</dialog>'''
PLUTO='''<div id="pluto-info" class="panel">
  <h2>Pluto TV · vorbereitet, noch nicht aktiviert</h2>
  <p class="muted">Der bekannte yt-dlp-Pluto-Extractor ist derzeit als nicht funktionsfähig markiert. Für Pluto existiert noch kein geprüfter Katalogadapter und keine Downloadberechtigung. Die offizielle Wiedergabe und ein eigener Katalog werden erst nach unabhängiger Prüfung ergänzt.</p>
  <p class="muted">Keine Anmeldung, keine DRM-Umgehung und kein Entfernen von Werbung. ArchiveMedia, Netzkino und die deutschen Mediatheken bleiben unabhängig.</p>
</div>'''

CHANGELOG='''## 0.5.31.6 – Quellennavigation, Netzkino-Details, optionaler yt-dlp-Check (Preview)
- Hauptansicht: Gesamt / Mediatheken / Netzkino ohne Verschmelzen der beiden Datenbanken oder unerwiesene Dubletten-Zusammenführung. Netzkino wird zusätzlich im Hauptkatalog mit Filmen/Serien angezeigt.
- Detailfenster analog zur Mediatheken-Titelseite: Beschreibung, Originaltitel, Jahr, Genres, FSK, Laufzeit, Land, Originalsprache, Besetzung, Regie, Drehbuch und Anbieterkategorie – nur soweit vorhanden; fehlende Daten bleiben sichtbar als unbekannt.
- Bei manuellem Öffnen werden öffentlich sichtbare Netzkino MovieDetails-Metadaten per im HAR beobachteter GraphQL-Operation geladen und sieben Tage datensparsam zwischengespeichert; keine Streamadressen und keine massenhaften Filmseitenaufrufe.
- Optionaler yt-dlp-Metadatencheck nur nach Nutzerklick. Ausgabe-Whitelist, Zeit-/Größenlimits, kein Mediendownload, kein Übernehmen von Streaming-URLs und keine Verfügbarkeits- oder Rechtebestätigung.
- Native macOS-Wiedergabe im separaten, selbst erzeugten WKWebView-Fenster über die offizielle Netzkino-Seite, sofern Swift auf dem Ziel-Mac vorhanden; sonst Browserlink. Keine Werbung/DRM umgehen.
- Pluto-TV-Reiter als ausdrücklich noch nicht aktiver Platzhalter. Keine Behauptung eines vorhandenen Extraktors oder Downloadrechts.
- Diagnose ergänzt Zahl öffentlicher gecachter Details und gesperrter Wiederholungsversuche; keine Nutzerdaten, Titel oder URL-Export.
- PR #23 Videoaudit und PR #24 ArchiveMedia-Vollmodus sowie getrennte Downloadwarteschlangen unverändert; vollständiger nativer Build auf dem Mac erforderlich.

'''


def one(text,old,new,tag):
    n=text.count(old)
    if n!=1:raise RuntimeError(f'{tag}: erwarteter Einbaupunkt nicht eindeutig ({n}); keine Änderung vorgenommen')
    return text.replace(old,new,1)


def patch(project,dry_run=False):
    root=Path(project).resolve()
    required=['server.py','version.py','web/index.html','web/style.css','web/netzkino.js',
      'build_macos.py','netzkino.py','diagnostic_extensions.py','archive_companion.py',
      'portal_control.py','portal_sources.py','video_backfill.py','CHANGELOG.md']
    for name in required:
        if not (root/name).is_file():raise RuntimeError('0.5.31.5-Integrationsstand unvollständig: '+name)
    s=(root/'server.py').read_text('utf-8')
    html=(root/'web/index.html').read_text('utf-8')
    js=(root/'web/netzkino.js').read_text('utf-8')
    css=(root/'web/style.css').read_text('utf-8')
    n=(root/'netzkino.py').read_text('utf-8')
    build=(root/'build_macos.py').read_text('utf-8')
    version=(root/'version.py').read_text('utf-8')
    diag=(root/'diagnostic_extensions.py').read_text('utf-8')
    for key in ("if path=='/api/netzkino-grouped':","if path=='/api/archive-companion':",
                "if path=='/api/video-audit':", "if path=='/api/portal-archive-probe':"):
        if key not in s:raise RuntimeError('Vorhandene API verloren: '+key)
    for key in ('id="archive-full-mode"','id="archive-platform-controls"','id="netzkino"',
                'id="netzkino-view-series"','id="video-audit-panel"'):
        if key not in html:raise RuntimeError('Bestehende Oberfläche fehlt: '+key)
    if '_category_failure_type' not in n or 'def grouped_catalog(' not in n:
        raise RuntimeError('Netzkino-Adapter stammt nicht aus 0.5.31.5')
    n=one(n, "    'CategoryDataBySlug':'5e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8',",
        "    'CategoryDataBySlug':'5e84446505b1211c3d48d08b06685d4f081e984ec35d6dddde9a57183220fea8',\n    'MovieDetails':'692ee5a44d28183d6e0bf48b40343c2d231a5d1fcce5483c81f146936f00bf97',",
        'HAR-belegte MovieDetails-Anfrage')
    s=one(s,'subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy',
          'subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy, netzkino_details, yt_dlp_probe',
          'API-Module')
    s=one(s,"if path in ('/app.js','/player.js','/netzkino.js','/video_audit.js'):",
          "if path in ('/app.js','/player.js','/netzkino.js','/video_audit.js','/netzkino_detail.js','/unified_catalog.js'):",
          'Statische JS-Dateien')
    s=one(s,"        if path=='/api/netzkino-grouped':",
'''        if path=='/api/netzkino-details':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send(netzkino_details.get(ROOT,q.get('id',[''])[0]))
        if path=='/api/netzkino-grouped':''','Detailroute')
    s=one(s,"            if path=='/api/portal-netzkino-add':",
'''            if path=='/api/netzkino-metadata-probe':
                item_id=str(d.get('id',''))
                editorial=netzkino_details.get(ROOT,item_id)
                result=yt_dlp_probe.probe(editorial['page_url'],editorial['details'])
                diagnostics.event('netzkino_metadata_validation',status=result['status'],
                                  conflicts=len(result.get('warnings',[])))
                return self.send(result)
            if path=='/api/netzkino-watch':
                item_id=str(d.get('id',''))
                page=netzkino_details.find_page(ROOT,item_id)
                helper=Path(__file__).with_name('netzkino_webplayer')
                if sys.platform=='darwin' and helper.is_file() and os.access(helper,os.X_OK) and not NETWORK:
                    subprocess.Popen([str(helper),page],stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
                    diagnostics.event('netzkino_official_player',mode='native_webkit')
                    return self.send({'mode':'native_webkit'})
                diagnostics.event('netzkino_official_player',mode='official_browser')
                return self.send({'mode':'official_browser','page_url':page})
            if path=='/api/portal-netzkino-add':''','Metadatenprüfung und offizieller Player')
    html=one(html,'<section id="discover">','<section id="discover" data-source="mediatheken">'+SOURCE_TABS,'Hauptkatalog-Quellenwahl')
    html=one(html,'<button class="platform-tab" type="button" data-platform="netzkino">Netzkino</button>',
        '<button class="platform-tab" type="button" data-platform="netzkino">Netzkino</button>\n    <button class="platform-tab" type="button" data-platform="pluto">Pluto TV (Vorschau)</button>',
        'Pluto-Tab')
    html=one(html,'  <div id="portal-platform-overview"',PLUTO+'\n  <div id="portal-platform-overview"','Pluto-Hinweis')
    html=one(html,'<script src="/netzkino.js"></script>',
        '<script src="/netzkino.js"></script><script src="/netzkino_detail.js"></script><script src="/unified_catalog.js"></script>',
        'Detail- und Hauptkatalog-JS')
    html=one(html,'<script src="/app.js"></script>',DIALOG+'<script src="/app.js"></script>','Netzkino-Detaildialog')
    js=one(js,'        card.append(actions); host.append(card);',
'''        if (!isGroup && /^[a-f0-9]{32}$/.test(item.id || '')) {
          const detail = make('button', 'Details & Ansehen');
          detail.type = 'button';
          detail.onclick = () => window.AtlasNetzkinoDetail?.open(item.id);
          actions.prepend(detail);
        }
        card.append(actions); host.append(card);''','Netzkino-Detailaktion')
    js=one(js,'window.MediathekAtlasNetzkino = {refresh};',
        'window.MediathekAtlasNetzkino = {refresh, openSeries: key => {view=\"episodes\";seriesKey=key;offset=0;refresh();}};',
        'Seriennavigation aus Hauptansicht')
    css+='\n'+(HERE/'web/netzkino_05316.css').read_text('utf-8')
    build=one(build,"'netzkino.py','video_backfill.py'",
              "'netzkino.py','netzkino_details.py','yt_dlp_probe.py','video_backfill.py'",'macOS-Quellpaket')
    build=one(build,"'CFBundleVersion':'515'","'CFBundleVersion':'516'",'Bundle-Version')
    version=one(version,"VERSION='0.5.31.5'","VERSION='0.5.31.6'",'Projektversion')
    diag=one(diag, "            result['metadata_coverage']=quality",
'''            if 'netzkino_public_details' in tables:
                result['detail_cache_count']=int(db.execute('SELECT COUNT(*) FROM netzkino_public_details').fetchone()[0])
            else:result['detail_cache_count']=0
            if 'netzkino_detail_failures' in tables:
                result['detail_retries_deferred']=int(db.execute('SELECT COUNT(*) FROM netzkino_detail_failures').fetchone()[0])
            else:result['detail_retries_deferred']=0
            result['metadata_coverage']=quality''','Lese-Diagnose')
    outputs={
       'server.py':s,'web/index.html':html,'web/netzkino.js':js,'web/style.css':css,
       'netzkino.py':n,'build_macos.py':build,'version.py':version,
       'diagnostic_extensions.py':diag,
       'netzkino_details.py':(HERE/'netzkino_details.py').read_text('utf-8'),
       'yt_dlp_probe.py':(HERE/'yt_dlp_probe.py').read_text('utf-8'),
       'web/netzkino_detail.js':(HERE/'web/netzkino_detail.js').read_text('utf-8'),
       'web/unified_catalog.js':(HERE/'web/unified_catalog.js').read_text('utf-8'),
       'assets/netzkino_details_seed.json':(HERE/'assets/netzkino_details_seed.json').read_text('utf-8'),
       'netzkino_webplayer.swift':(HERE/'netzkino_webplayer.swift').read_text('utf-8'),
       'CHANGELOG.md':CHANGELOG+(root/'CHANGELOG.md').read_text('utf-8'),
    }
    if dry_run:
        print('0.5.31.6: Quellwahl, MovieDetails, yt-dlp, WebKit, Pluto-Hinweis, ArchiveMedia: Einbaupunkte OK')
        return list(outputs)
    for name,body in outputs.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body,'utf-8')
    print('0.5.31.6: Erweiterungen eingebaut; keine Katalogdaten oder GitHub-Refs verändert')
    return list(outputs)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('project');parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();patch(args.project,args.dry_run)
