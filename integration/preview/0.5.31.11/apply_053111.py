#!/usr/bin/env python3
"""0.5.31.11: visible mediatheken scan dashboard, grouped recognition status,
conservative episode queue scheduling, TMDB per-season 404 resilience, OMDb
reason, and honest Netzkino category counts. No user databases or GitHub writes.
Run after 0.5.31.10 integration, including PRs #23/#24.
"""
import argparse
from pathlib import Path

CHANGELOG = '''## 0.5.31.11 – Mediatheken-Dashboard, Episoden-Queue und Diagnose (Test)
- Die Scanner-/Erkennungsübersicht ist im Mediatheken- und Gesamtkatalog wieder direkt sichtbar, nicht mehr im eingeklappten Expertenbereich. Die Zahlen bleiben ausdrücklich auf den Mediathekenbestand bezogen.
- Unter „Letzte Erkennung“: getrennte responsive Bereiche für Worker, Qualität, Episoden & Senderbelege sowie Fehler/Wiederholungen. Jeder bisherige Statuszähler bleibt sichtbar.
- Episoden-Worker priorisieren innerhalb der **48 ältesten fälligen Aufgaben** Fälle mit expliziten Staffel-/Folgenhinweisen; weder Aufgaben noch Wartezeiten werden gelöscht oder umgeschrieben. Manuelle Priorität hat weiterhin Vorrang.
- TMDB-HTTP-404 für einzelne Staffeln verwirft keine bereits erkannten Serienmetadaten; die Episodenliste bleibt als unvollständig gekennzeichnet, ohne falsche Bestätigung.
- OMDb-Anbieterstatus zeigt auch den konkreten Grund einer Pause (z. B. Schlüssel abgelehnt), ohne Schlüssel anzuzeigen.
- Netzkino-Kategoriediagnose unterscheidet >=20 Einträge, >20 Einträge und größte beobachtete Kategorie. Eine feste 20er-API-Grenze wird nicht mehr behauptet. Auch 29/29 Kategorien bedeutet nicht vollständigen Gesamtkatalog.
- ArchiveMedia-Vollmodus, Netzkino-Wiedergabe, deutsche Metadatenprovider, Videoaudit und bestehende Downloads bleiben erhalten. Keine Änderung an Live-Daten oder GitHub.

'''

def one(s,old,new,label):
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: erwartete Textstelle {n}-mal gefunden; keine Änderung vorgenommen')
    return s.replace(old,new,1)


def patch(root,dry_run=False):
    root=Path(root).resolve()
    needed=['server.py','catalog_service.py','catalog.py','metadata.py','netzkino.py',
            'diagnostic_extensions.py','web/index.html','web/app.js','web/style.css',
            'web/netzkino.js','web/unified_catalog.js','version.py','build_macos.py','CHANGELOG.md',
            'archive_companion.py','portal_sources.py','portal_control.py','netzkino_downloads.py',
            'yt_dlp_probe.py','netzkino_enrichment.py','web/netzkino_detail.js','video_backfill.py']
    for name in needed:
        if not (root/name).is_file():raise RuntimeError('Quelldatei fehlt: '+name)
    keys=['catalog_service.py','metadata.py','netzkino.py','diagnostic_extensions.py',
          'web/index.html','web/app.js','web/style.css','web/netzkino.js',
          'web/unified_catalog.js','version.py','build_macos.py','CHANGELOG.md']
    d={k:(root/k).read_text('utf-8') for k in keys}
    if "VERSION='0.5.31.10'" not in d['version.py'].splitlines():
        raise RuntimeError('Erwartet 0.5.31.10, erhalten: '+d['version.py'].strip()[:80])
    for marker in ('/api/archive-companion','/api/netzkino-grouped','/api/video-audit',
                   '/api/netzkino-watch','/api/netzkino-enrich','/api/netzkino-downloads'):
        if marker not in (root/'server.py').read_text('utf-8'):
            raise RuntimeError('Bestandsschutz: API fehlt: '+marker)

    # Re-home original metrics rather than copying/resetting the live status DOM.
    unified=d['web/unified_catalog.js']
    unified=one(unified,
        '    discover.append(advanced);\n  }\n  function updateControls() {',
        '''    discover.append(advanced);
    // Restore the actual historic mediatheken status board *above* the shared
    // catalogue. Move live nodes with IDs; do not clone elements or handlers.
    const historic=advanced.querySelector('.background-status');
    if (!historic) throw new Error('Scan- und Erkennungsübersicht fehlt');
    const dashboard=el('section',undefined,'background-status atlas-main-dashboard');
    dashboard.id='atlas-main-dashboard';
    dashboard.setAttribute('aria-label','Mediatheken-Scanner und Metadatenabgleich');
    dashboard.append(el('h2','Mediatheken · Scan & Erkennung','atlas-dashboard-heading'));
    const oldSummary=historic.querySelector('summary');
    if(oldSummary) oldSummary.remove();
    while(historic.firstChild) dashboard.append(historic.firstChild);
    historic.remove();
    discover.insertBefore(dashboard,body);
    // Keep the existing last-recognition and provider panels side by side,
    // but place worker/queue statistics in their own full-width responsive row.
    const workers=$('metadata-workers-status');
    const statusBottom=dashboard.querySelector('.atlas-status-bottom');
    if(workers && statusBottom){
      const overview=el('section',undefined,'atlas-worker-overview');
      overview.append(el('h3','Verarbeitung & Warteschlangen'));
      overview.append(workers);
      statusBottom.insertAdjacentElement('afterend',overview);
      const recognition=dashboard.querySelector('#metadata-status')?.closest('.atlas-status-panel');
      const title=recognition?.querySelector('h3');
      if(title)title.textContent='Letzte Erkennung';
    }
  }
  function updateControls() {''',
        'Sichtbarer Scanner statt verborgenem Details-Block')
    d['web/unified_catalog.js']=unified

    # The newly moved worker grid contains sections; use a semantic div, not <small>.
    html=d['web/index.html']
    html=one(html,'<small id="metadata-workers-status" class="muted">Worker werden gestartet …</small>',
             '<div id="metadata-workers-status" class="muted">Worker werden gestartet …</div>',
             'Status-Container semantisch korrekt')
    d['web/index.html']=html

    css=d['web/style.css']
    css+='''
/* 0.5.31.11: restore front-page mediatheken statistics & group last recognition. */
#discover > #atlas-main-dashboard{display:block;min-width:0;margin:8px 0 22px;padding:18px;border:1px solid #324852;border-radius:13px;background:#101d29}
#discover[data-source="netzkino"] > #atlas-main-dashboard{display:none!important}
#discover[data-source="mediatheken"] > #atlas-main-dashboard,#discover[data-source="all"] > #atlas-main-dashboard{display:block!important}
#atlas-main-dashboard .atlas-dashboard-heading{font-size:18px;margin:0 0 14px;line-height:1.35}
#atlas-main-dashboard .atlas-status-bottom{grid-template-columns:repeat(2,minmax(0,1fr));align-items:stretch}
#atlas-main-dashboard .atlas-status-panel{min-height:116px}
#atlas-main-dashboard #metadata-status{display:flex;flex-direction:column;gap:5px}
#atlas-main-dashboard .atlas-worker-overview{margin-top:13px;border:1px solid #2c4750;background:#10242c;border-radius:11px;padding:13px}
#atlas-main-dashboard .atlas-worker-overview>h3{font-size:13px;color:#d9ebf1;margin:0 0 11px}
#atlas-main-dashboard #metadata-workers-status{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin:0;min-width:0}
#atlas-main-dashboard .atlas-worker-group{border:1px solid #344956;border-radius:10px;background:#12212d;min-width:0;padding:10px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;align-content:start}
#atlas-main-dashboard .atlas-worker-group h4{grid-column:1/-1;font-size:12px;color:#dcf0eb;margin:0 0 3px}
#atlas-main-dashboard .atlas-worker-group .atlas-worker-chip{min-height:45px;padding:8px;font-size:11px}
#atlas-main-dashboard .atlas-worker-hint{grid-column:1/-1}
@media(max-width:1450px){#atlas-main-dashboard #metadata-workers-status{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){#atlas-main-dashboard .atlas-status-bottom{grid-template-columns:minmax(0,1fr)}}
@media(max-width:660px){#atlas-main-dashboard #metadata-workers-status{grid-template-columns:1fr}#atlas-main-dashboard .atlas-worker-group{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:440px){#atlas-main-dashboard .atlas-worker-group{grid-template-columns:1fr}}
'''
    d['web/style.css']=css

    app=d['web/app.js']
    app=one(app,
'''   workers.replaceChildren();
   for(const [kind,label] of chips){
     const item=el('span',label,'atlas-worker-chip');
     item.dataset.kind=kind;
     workers.append(item);
   }
   workers.append(el('span','Externe Anbieteranfragen bleiben auf zwei gleichzeitig begrenzt.','atlas-worker-hint'));''',
'''   workers.replaceChildren();
   // The grouping is presentation only: keep every existing session counter.
   const groupSpec=[
     ['Worker & Scan', ['identity','episode']],
     ['Erkennungsqualität', ['identified','confirmed']],
     ['Episoden & Senderbelege', ['queue','due','episode-checks','sender','sender-matches','shorts']],
     ['Fehler & Wiederholungen', ['retry']]
   ];
   for(const [name,kinds] of groupSpec){
     const group=el('section',undefined,'atlas-worker-group');
     group.append(el('h4',name));
     for(const [kind,label] of chips.filter(([id])=>kinds.includes(id))){
       const item=el('span',label,'atlas-worker-chip');
       item.dataset.kind=kind;
       group.append(item);
     }
     if(name==='Fehler & Wiederholungen' && !c.sqlite_busy_retries_session)
       group.append(el('span','Keine SQLite-Sperrkonflikte seit Start','atlas-worker-chip'));
     workers.append(group);
   }
   workers.append(el('span','Externe Anbieteranfragen bleiben auf zwei gleichzeitig begrenzt. Fällige Episoden sind keine bestätigten Folgen.','atlas-worker-hint'));''',
'Worker-Status semantisch gruppiert')
    app=one(app,
"  ['OMDb',pauses.omdb?.paused?'Pausiert · '+Math.ceil(pauses.omdb.remaining_seconds/60)+' Min.':settings.omdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.omdb_set&&!pauses.omdb?.paused],",
"  ['OMDb',pauses.omdb?.paused?'Pausiert: '+({key:'Schlüssel abgelehnt',inactive:'Schlüssel nicht aktiviert',auth:'Zugang abgelehnt',limit:'Anfragelimit',network:'Netzwerk',response:'Ungültige Antwort'}[pauses.omdb.reason]||'Anbieterfehler')+' · '+Math.ceil(pauses.omdb.remaining_seconds/60)+' Min.':settings.omdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.omdb_set&&!pauses.omdb?.paused],",
'OMDb-Pausengrund statt nur Pausendauer')
    d['web/app.js']=app

    # Try explicit episode numbering ahead of identical-title guesses in a bounded
    # due window. No disk writes/cooldown resets; explicit user priority wins.
    cat=d['catalog_service.py']
    cat=one(cat,
'''        return c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 1",
                         (now,now)+params).fetchone()

    def pick(self,c):''',
'''        rows=c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 48",
                       (now,now)+params).fetchall()
        if not rows:return None
        def evidence(row):
            try:m=json.loads(row['meta'] or '{}')
            except (TypeError,ValueError):return 0
            season,episode=m.get('season'),m.get('episode')
            if isinstance(season,int) and not isinstance(season,bool) and season>=0 and isinstance(episode,int) and not isinstance(episode,bool) and episode>0:
                return 3
            if m.get('sender_page_id') or m.get('sender_evidence'):
                return 2
            if m.get('episode_title') and m['episode_title']!=m.get('title'):
                return 1
            return 0
        return max(rows,key=evidence)  # stable FIFO for equal evidence

    def pick(self,c):''',
'Begrenzte Priorisierung evidenzreicher Episoden')
    d['catalog_service.py']=cat

    meta=d['metadata.py']
    meta=one(meta,
'''                episodes.extend(core.tmdb(f"tv/{d['id']}/season/{number}",key).get('episodes',[]))
            resolve_episode(epmeta,c,episodes)
            if not c['episode_scan_complete'] and meta.get('season') is None:c['episode_verified']=False''',
'''                try:
                    season_data=core.tmdb(f"tv/{d['id']}/season/{number}",key)
                except ValueError as exc:
                    # One unavailable/missing season is not a failure of the
                    # series identity. Never claim a complete episode scan.
                    if 'HTTP 404' not in str(exc):raise
                    c['episode_scan_complete']=False
                    diagnostics.event('tmdb_season_unavailable',provider='TMDB',season=number,
                                      series_id=str(d['id'])[:32])
                    continue
                episodes.extend(season_data.get('episodes',[]))
            if c['episode_scan_complete']:
                resolve_episode(epmeta,c,episodes)
            else:
                c['episode_verified']=False
                c['reason']='Serienmetadaten erkannt; mindestens eine Staffel konnte nicht vollständig geprüft werden.' ''',
'TMDB 404 pro Staffel statt Verlust der Serienmetadaten')
    d['metadata.py']=meta

    nk=d['netzkino.py']
    nk=one(nk,
"            'category_cap_hits':int(_get(db,'category_cap_hits','0')),",
"            'category_cap_hits':int(_get(db,'category_cap_hits','0')),\n            'category_over_20':int(_get(db,'category_over_20','0')),\n            'category_max_items':int(_get(db,'category_max_items','0')),",
'Netzkino-Kategoriegrößen im Status')
    nk=one(nk,
"('categories_empty',0),('category_cap_hits',0),('category_error_types','{}'),",
"('categories_empty',0),('category_cap_hits',0),('category_over_20',0),('category_max_items',0),('category_error_types','{}'),",
'Kategoriegrößen Reset')
    nk=one(nk,"    cap_hits=0\n    stopped_for_access=False",
              "    cap_hits=0\n    over_20=0\n    category_max=0\n    stopped_for_access=False",
'Kategoriegrößen Laufzeit')
    nk=one(nk,
'''                    # 20 is the observed homepage-category card limit (HAR), not a proven API page size.
                    if isinstance(content,dict) and isinstance(content.get('nodes'),list) and len(content['nodes'])>=20:
                        cap_hits+=1
                    if content is None''',
'''                    # Counts of observed category size, NOT a pagination limit.
                    if isinstance(content,dict) and isinstance(content.get('nodes'),list):
                        count=len(content['nodes'])
                        category_max=max(category_max,count)
                        if count>=20:cap_hits+=1
                        if count>20:over_20+=1
                    if content is None''',
'Tatsächlich beobachtete Netzkino-Kategoriegrößen')
    nk=one(nk,
"('categories_empty',empty),('category_cap_hits',cap_hits),('category_error_types',json.dumps(error_types,sort_keys=True)),",
"('categories_empty',empty),('category_cap_hits',cap_hits),('category_over_20',over_20),('category_max_items',category_max),('category_error_types',json.dumps(error_types,sort_keys=True)),",
'Netzkino-Kategoriegrößen persistieren')
    nk=one(nk,
"category_errors=failures,category_cap_hits=cap_hits,partial=partial,coverage_status='startpage_only')",
"category_errors=failures,category_cap_hits=cap_hits,category_over_20=over_20,category_max_items=category_max,partial=partial,coverage_status='startpage_only')",
'Netzkino-Kategoriegrößen Ereignis')
    nk=one(nk,
"'category_errors':failures,'categories_empty':empty,'category_cap_hits':cap_hits,",
"'category_errors':failures,'categories_empty':empty,'category_cap_hits':cap_hits,\n                    'category_over_20':over_20,'category_max_items':category_max,",
'Netzkino-Kategoriegrößen Ergebnis')
    d['netzkino.py']=nk
    ext=d['diagnostic_extensions.py']
    ext=one(ext,"'categories_empty','category_cap_hits','category_error_types','last_result'",
            "'categories_empty','category_cap_hits','category_over_20','category_max_items','category_error_types','last_result'",
'Offline Diagnose Netzkino-Kategorien')
    ext=one(ext,"category_cap_hits=_int(values.get('category_cap_hits')),",
            "category_cap_hits=_int(values.get('category_cap_hits')),\n                          category_over_20=_int(values.get('category_over_20')),\n                          category_max_items=_int(values.get('category_max_items')),",
'Kategorieabdeckung Diagnosefelder')
    d['diagnostic_extensions.py']=ext
    web=d['web/netzkino.js']
    web=one(web,
"` · Am beobachteten 20-Titel-Limit ${status.category_cap_hits || 0}` : '';",
"` · Kategorien mit ≥20 Titeln ${status.category_cap_hits || 0}` +\n        ` · über 20 Titel ${status.category_over_20 || 0}` +\n        ` · größte Kategorie ${status.category_max_items || 0}` : '';",
'Keine behauptete 20-Titel-Obergrenze')
    d['web/netzkino.js']=web

    d['version.py']=one(d['version.py'],"VERSION='0.5.31.10'","VERSION='0.5.31.11'",'Version')
    d['build_macos.py']=one(d['build_macos.py'],"'CFBundleVersion':'520'","'CFBundleVersion':'521'",'Build-Version')
    d['CHANGELOG.md']=CHANGELOG+d['CHANGELOG.md']
    if dry_run:
        print('0.5.31.11 alle Einbaustellen geprüft; keine Schreiboperation')
        return sorted(d)
    for name,content in d.items():
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(content,'utf-8')
    print('0.5.31.11 Dashboard, Gruppierung, Queue, TMDB, OMDb, Netzkino-Katalogdiagnose integriert')
    return sorted(d)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--dry-run',action='store_true')
    opts=p.parse_args();patch(opts.root,opts.dry_run)
