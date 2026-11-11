#!/usr/bin/env python3
"""Add ARD-grade provider enrichment to Netzkino without touching ArchiveMedia.

Must run after apply_05316. Preflight verifies all anchors before any writes.
"""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent

CHANGELOG='''## 0.5.31.7 – Anbieterübergreifende Netzkino-Metadatenprüfung (Preview)
- Kompakter Netzkino-Detaildialog: Kurzdaten (Jahr, FSK, Laufzeit, Land, Sprache, Zugang) links als zweispaltige Kacheln; Beschreibung und vollständige Credits rechts. Responsive ohne versteckte Felder.
- Netzkino-Titeldetails können die bestehende ARD/ZDF-Kette IMDb Offline, TVDB, TMDB, OMDb und Wikidata verwenden. Nur auf Nutzerauswahl; Ergebnisse werden sieben Tage lokal zwischengespeichert, unvollständige Providerergebnisse kürzer.
- Datenprovenienz je ergänztem Feld; vorhandene Netzkino-Titel, Covers, Beschreibungen und Rechte bleiben maßgeblich. Film-/Serienidentitäten werden nicht automatisch als bestätigt markiert; widersprüchliche Referenzen erfordern Prüfung.
- Ausdrückliche Serien-/Folgen-Trennung: Ein bestätigter Serientitel weist noch keine konkret verfügbare Episode nach.
- Diagnose: aggregierte Referenzstatus-Zähler ohne Film-IDs, Titel, Streamingadressen oder API-Schlüssel.
- Deutsche Mediathek, PR #23 Videoaudit, PR #24 ArchiveMedia, Netzkino-GraphQL, yt-dlp-Metadatenprobe und offizielle WebKit-Wiedergabe unverändert.

'''
CSS='''
/* Version 0.5.31.7: source-attributed metadata only, no inter-platform merge. */
#atlas-nk-reference{border-top:1px solid #344d56;padding-top:12px;margin:14px 0;white-space:normal}
#atlas-nk-reference h3{font-size:14px;margin:4px 0 8px}
#atlas-nk-reference p,#atlas-nk-reference li{font-size:12px;line-height:1.45}
#atlas-nk-reference .nk-ref-warning{color:#ffd09b}
#atlas-nk-reference-facts{display:grid;grid-template-columns:minmax(120px,30%) minmax(0,1fr);gap:7px 12px;overflow-wrap:anywhere}
#atlas-nk-reference-facts dt{font-size:11px;color:#a9bfce}
#atlas-nk-reference-facts dd{font-size:12px;margin:0}
#atlas-nk-reference .nk-ref-candidates{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
#atlas-nk-reference .nk-ref-candidate{border:1px solid #3a5665;border-radius:8px;padding:9px;min-width:200px;max-width:100%;font-size:12px}
#atlas-nk-reference .nk-ref-candidate small{display:block;line-height:1.5}
'''


# Compact two-column facts in the left details column. Long descriptions and
# provider comparisons stay in the wider right column. This is presentation only.
CSS += r'''
/* Compact Netzkino metadata (user feedback 11 Nov 2026). */
#atlas-netzkino-detail {width:min(1120px,96vw);max-width:1120px;padding:clamp(14px,2vw,26px)}
#atlas-netzkino-detail .nk-detail-layout {grid-template-columns:minmax(195px,245px) minmax(0,1fr);gap:20px;align-items:start}
#atlas-netzkino-detail .nk-detail-sidebar {min-width:0;display:flex;flex-direction:column;align-items:stretch;gap:12px}
#atlas-netzkino-detail #atlas-nk-image {max-height:265px;max-width:100%;object-fit:contain;align-self:stretch}
#atlas-netzkino-detail .nk-detail-main {min-width:0}
#atlas-netzkino-detail #atlas-nk-description {font-size:13px;line-height:1.6;margin:0 0 12px;overflow-wrap:anywhere}
#atlas-netzkino-detail #atlas-nk-quickfacts {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:0}
#atlas-nk-quickfacts .nk-detail-field {display:flex;flex-direction:column;min-width:0;gap:4px;padding:9px 10px;margin:0;border:1px solid #2e4b55;border-radius:8px;background:#172c37}
#atlas-nk-quickfacts .nk-detail-field dt {font-size:10px;line-height:1.2;color:#a8c4d1}
#atlas-nk-quickfacts .nk-detail-field dd {font-size:12px;line-height:1.35;font-weight:600;overflow-wrap:anywhere}
#atlas-nk-quickfacts .nk-detail-field--wide {grid-column:1/-1}
#atlas-netzkino-detail #atlas-nk-facts {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:17px;row-gap:0;margin:0}
#atlas-nk-facts .nk-detail-field {display:flex;flex-direction:column;min-width:0;gap:4px;padding:9px 0}
#atlas-nk-facts .nk-detail-field--wide {grid-column:1/-1}
#atlas-nk-facts .nk-detail-field dt {font-size:11px}
#atlas-nk-facts .nk-detail-field dd {font-size:12px;line-height:1.45;overflow-wrap:anywhere}
@media(max-width:810px) {
  #atlas-netzkino-detail .nk-detail-layout {grid-template-columns:1fr}
  #atlas-netzkino-detail .nk-detail-sidebar {display:grid;grid-template-columns:minmax(110px,180px) minmax(0,1fr);gap:12px}
  #atlas-netzkino-detail #atlas-nk-image {max-height:215px}
}
@media(max-width:520px) {
  #atlas-netzkino-detail .nk-detail-sidebar {grid-template-columns:1fr}
  #atlas-netzkino-detail #atlas-nk-image {max-height:190px}
  #atlas-netzkino-detail #atlas-nk-facts {grid-template-columns:1fr}
}
'''

def one(s,old,new,name):
    n=s.count(old)
    if n!=1:raise RuntimeError(f'{name}: erwartete Code-Stelle fehlt/mehrdeutig ({n}); kein Patch')
    return s.replace(old,new,1)


def patch(project,dry_run=False):
    root=Path(project).resolve()
    required=('server.py','web/index.html','web/netzkino_detail.js','web/style.css',
        'version.py','build_macos.py','diagnostic_extensions.py','archive_companion.py',
        'portal_sources.py','portal_control.py','netzkino.py','netzkino_details.py',
        'yt_dlp_probe.py','video_backfill.py','metadata.py','CHANGELOG.md')
    for name in required:
        if not (root/name).is_file():raise RuntimeError('0.5.31.6-Integrationsquelle fehlt: '+name)
    data={name:(root/name).read_text('utf-8') for name in (
        'server.py','web/index.html','web/netzkino_detail.js','web/style.css',
        'version.py','build_macos.py','diagnostic_extensions.py','metadata.py','CHANGELOG.md')}
    s=data['server.py']
    for marker in ("if path=='/api/archive-companion':", "if path=='/api/portal-archive-probe':",
            "if path=='/api/netzkino-details':", "if path=='/api/netzkino-watch':",
            "if path=='/api/netzkino-metadata-probe':", "if path=='/api/video-audit':"):
        if marker not in s:raise RuntimeError('Bestehende API fehlt: '+marker)
    html=data['web/index.html']
    for marker in ('id="archive-full-mode"','id="archive-platform-controls"',
                   'id="atlas-netzkino-detail"','data-catalog-source="all"',
                   'id="netzkino-view-series"'):
        if marker not in html:raise RuntimeError('Vorhandene Oberfläche fehlt: '+marker)
    s=one(s,'portal_metadata_policy, netzkino_details, yt_dlp_probe',
          'portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment','Import')
    s=one(s,"        if path=='/api/netzkino-grouped':",
'''        if path=='/api/netzkino-reference-report':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send(netzkino_enrichment.cached(ROOT,q.get('id',[''])[0]))
        if path=='/api/netzkino-grouped':''','Read-only Cache-Route')
    s=one(s,"            if path=='/api/netzkino-metadata-probe':",
'''            if path=='/api/netzkino-enrich':
                item_id=str(d.get('id',''))
                with SERVICE.provider_slots:
                    result=netzkino_enrichment.enrich(ROOT,item_id,settings(),
                                                        force=d.get('force') is True)
                diagnostics.event('netzkino_reference_check',status=result['status'],
                    candidates=len(result.get('references',[])),
                    checked_providers=len(result.get('provider_checks',[])))
                return self.send(result)
            if path=='/api/netzkino-metadata-probe':''','Metadaten-API')
    html=one(html,'<p id="atlas-nk-evidence" role="status"></p><div id="atlas-nk-validation" role="status"></div>',
        '<p id="atlas-nk-evidence" role="status"></p><div id="atlas-nk-reference" role="status"></div><dl id="atlas-nk-reference-facts"></dl><div id="atlas-nk-validation" role="status"></div>',
        'Referenzdetails')
    html=one(html,
        '<div class="nk-detail-layout"><img id="atlas-nk-image" alt="Filmcover" hidden>\n    <div><p id="atlas-nk-description"></p><dl id="atlas-nk-facts"></dl>',
        '<div class="nk-detail-layout"><aside class="nk-detail-sidebar"><img id="atlas-nk-image" alt="Filmcover" hidden><dl id="atlas-nk-quickfacts" aria-label="Netzkino-Kurzdaten"></dl></aside>\n    <div class="nk-detail-main"><p id="atlas-nk-description"></p><dl id="atlas-nk-facts"></dl>',
        'Kompakte Detailspalte')
    js=data['web/netzkino_detail.js']
    js=one(js,"    facts.replaceChildren(); actions.replaceChildren();",
'''    facts.replaceChildren(); actions.replaceChildren();
    $('atlas-nk-reference').replaceChildren();$('atlas-nk-reference-facts').replaceChildren();''',
         'Cache-UI zurücksetzen')
    js=one(js,'      const watch = node(\'button\', \'▶ In MediathekAtlas ansehen\', \'primary\');',
'''      const refArea = $('atlas-nk-reference');
      const refFields = $('atlas-nk-reference-facts');
      const sourceNames = {description:'Beschreibung', genres:'Genres', cast:'Besetzung',
          directors:'Regie',writers:'Drehbuch',poster:'Poster',rating:'Bewertung',
          votes:'Bewertungsstimmen',series_description:'Serienbeschreibung',reference_description:'Weitere Inhaltsangabe'};
      const renderReference = (report) => {
        if (id !== currentId) return;
        refArea.replaceChildren();refFields.replaceChildren();
        const messages = {unchecked:'Referenzen noch nicht abgeglichen',
          candidate:'Plausible Referenz gefunden · noch keine bestätigte Werkidentität',
          review:'Widersprüchliche Referenzen · bitte manuell prüfen',
          no_match:'Keine ausreichend eindeutige Referenz gefunden',
          partial:'Einige Anbieter waren nicht erreichbar; später erneut prüfen'};
        refArea.append(node('h3','IMDb / TMDB / TVDB / OMDb / Wikidata'),
          node('p',messages[report.status]||'Erkennung wird geprüft'));
        if (report.status==='unchecked') return;
        for (const [field,source] of Object.entries(report.field_sources||{})) {
          if (source==='Netzkino' || !Object.hasOwn(sourceNames,field)) continue;
          const v=report.metadata?.[field];
          if (field==='poster') continue;
          makeField(refFields,sourceNames[field]+' · '+source,
            field==='rating' && typeof v==='number' ? v+' / 10' : v);
        }
        if (!m.description && report.metadata?.description && report.field_sources?.description!=='Netzkino') {
          $('atlas-nk-description').textContent=report.metadata.description;
        }
        for (const reference of (report.references||[]).slice(0,8)) {
          const box=node('div',undefined,'nk-ref-candidate');
          box.append(node('strong',reference.provider+' · '+reference.title),
            node('small',[reference.year,reference.reference_id,
              reference.episode_verified?'Episode unabhängig bestätigt':null]
              .filter(Boolean).join(' · ')));
          if (reference.issues?.length) box.append(node('small',reference.issues.join(' / '),'nk-ref-warning'));
          const container=refArea.querySelector('.nk-ref-candidates')||node('div',undefined,'nk-ref-candidates');
          if (!container.parentElement) refArea.append(container);
          container.append(box);
        }
        if (report.warnings?.length) refArea.append(node('p',report.warnings.join(' · '),'nk-ref-warning'));
        refArea.append(node('small','Referenzkandidaten sind keine Downloadberechtigung oder automatische Werkbestätigung.'));
      };
      window.api('netzkino-reference-report?id='+encodeURIComponent(id)).then(renderReference).catch(()=>{});
      const enrich=node('button','Mit IMDb, TMDB, TVDB und Co. abgleichen');
      enrich.type='button';
      enrich.onclick=async()=>{
        enrich.disabled=true;
        refArea.textContent='Externe Referenzen werden mit den vorhandenen Anbieterzugängen geprüft …';
        try {
          const result=await window.api('netzkino-enrich',{id,force:true});
          renderReference(result);
        } catch(e) {if (id===currentId)refArea.textContent='Referenzprüfung nicht verfügbar: '+e.message;}
        finally {enrich.disabled=false;}
      };
      actions.append(enrich);
      const watch = node('button', '▶ In MediathekAtlas ansehen', 'primary');''',
         'On-demand Provider-Abgleich')
    js=one(js,
        "    if (!value || (Array.isArray(value) && !value.length)) return;",
        "    if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return;",
        'FSK 0 als gültigen Wert anzeigen')
    js=one(js, "    const facts = $('atlas-nk-facts');",
        "    const facts = $('atlas-nk-facts');\n    const quickFacts = $('atlas-nk-quickfacts');",
        'Kurzdaten-Container')
    js=one(js, "    facts.replaceChildren(); actions.replaceChildren();",
        "    facts.replaceChildren(); quickFacts.replaceChildren(); actions.replaceChildren();",
        'Kurzdaten beim Wechsel leeren')
    # One and the same data, arranged into compact left-hand fact tiles.
    js=one(js, "    host.append(row);",
        "    if (['Originalsprache','Zugangshinweis','Originaltitel','Besetzung'].includes(name)) row.classList.add('nk-detail-field--wide');\n    host.append(row);",
        'Breite Fakten nach Inhalt')
    js=one(js, '''      makeField(facts, 'Originaltitel', m.original_title);
      makeField(facts, 'Jahr', m.year);
      makeField(facts, 'Laufzeit', m.duration_seconds ? Math.round(m.duration_seconds / 60) + ' Minuten' : null);
      makeField(facts, 'Genres', m.genres);
      makeField(facts, 'FSK', m.fsk == null ? null : m.fsk);
      makeField(facts, 'Land', m.country);
      makeField(facts, 'Originalsprache', m.original_language);
      makeField(facts, 'Besetzung', m.cast);
      makeField(facts, 'Regie', m.directors);
      makeField(facts, 'Drehbuch', m.writers);
      makeField(facts, 'Zugangshinweis', m.access_types);''',
        '''      // Compact sidebar, leaving the broad content area for descriptions/credits.
      makeField(quickFacts, 'Jahr', m.year == null ? '–' : m.year);
      makeField(quickFacts, 'FSK', m.fsk == null ? '–' : m.fsk);
      makeField(quickFacts, 'Laufzeit', m.duration_seconds ? Math.round(m.duration_seconds / 60) + ' Min.' : '–');
      makeField(quickFacts, 'Land', m.country || '–');
      makeField(quickFacts, 'Originalsprache', m.original_language || 'Unbekannt');
      makeField(quickFacts, 'Zugangshinweis', m.access_types?.length ? m.access_types : ['Nicht geprüft']);
      makeField(facts, 'Originaltitel', m.original_title);
      makeField(facts, 'Genres', m.genres);
      makeField(facts, 'Besetzung', m.cast);
      makeField(facts, 'Regie', m.directors);
      makeField(facts, 'Drehbuch', m.writers);''',
        'Kompakte Fakten statt langer vertikaler Liste')
    # Object.hasOwn is ES2022; use a broadly supported equivalent on macOS WebKit.
    js=js.replace('Object.hasOwn(sourceNames,field)', 'Object.prototype.hasOwnProperty.call(sourceNames,field)')
    css=data['web/style.css']+CSS
    provider=one(data['metadata.py'],
        "        checks.append(value);provider_stats.observe(value['provider'],value['status'],value['count'])",
        "        checks.append(value)\n        if not settings.get('_external_reference_validation',False):\n            provider_stats.observe(value['provider'],value['status'],value['count'])",
        'Providerstatistik getrennt halten')
    build=one(data['build_macos.py'],"'netzkino_details.py','yt_dlp_probe.py'",
              "'netzkino_details.py','yt_dlp_probe.py','netzkino_enrichment.py'",'macOS Modul')
    build=one(build,"'CFBundleVersion':'516'","'CFBundleVersion':'517'",'Bundle-Version')
    version=one(data['version.py'],"VERSION='0.5.31.6'","VERSION='0.5.31.7'",'Version')
    diag=data['diagnostic_extensions.py']
    # Must retain all existing aggregate diagnostics, without adding source URLs.
    diag=one(diag,"            result['metadata_coverage']=quality",
'''            if 'netzkino_reference_checks' in tables:
                statuses={}
                for (payload,) in db.execute('SELECT payload FROM netzkino_reference_checks'):
                    try:state=json.loads(payload).get('status')
                    except (ValueError,TypeError,AttributeError):state='invalid'
                    if state not in ('candidate','review','no_match','partial'):state='invalid'
                    statuses[state]=statuses.get(state,0)+1
                result['external_references']={'checked':sum(statuses.values()),
                                                'by_status':statuses}
            else:result['external_references']={'checked':0,'by_status':{}}
            result['metadata_coverage']=quality''','Diagnose Zähler')
    outputs={'server.py':s,'web/index.html':html,'web/netzkino_detail.js':js,
        'web/style.css':css,'build_macos.py':build,'version.py':version,
        'diagnostic_extensions.py':diag,'metadata.py':provider,
        'netzkino_enrichment.py':(HERE/'netzkino_enrichment.py').read_text('utf-8'),
        'CHANGELOG.md':CHANGELOG+data['CHANGELOG.md']}
    if dry_run:
        print('0.5.31.7: Provider-Anbindung und ArchiveMedia-Schutz: alle Einbaupunkte OK')
        return list(outputs)
    for name,content in outputs.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,'utf-8')
    print('0.5.31.7: ARD-Providerkette für Netzkino, ohne Änderungen an Werkdaten oder GitHub')
    return list(outputs)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('project');p.add_argument('--dry-run',action='store_true')
    a=p.parse_args();patch(a.project,a.dry_run)
