#!/usr/bin/env python3
"""Add explicit-rights direct-file download queue without Netzkino stream extraction.

Applies after apply_05318 to the verified local PR #23/#24 integration tree.
Non-destructive: no edits to broadcaster or ArchiveMedia downloader databases.
"""
import argparse
from pathlib import Path

HERE=Path(__file__).resolve().parent
CHANGELOG='''## 0.5.31.9 – Gesondert berechtigte Datei-Downloads (Test)
- Netzkino-Titeldetails zeigen den offiziellen Weg zur Offline-Nutzung in der Netzkino-App und zusätzlich eine **separat lizenzierte** Direktdatei-Option. Netzkino AVOD-/Plus-Angebote erhalten **keinen** automatischen Downloadstatus; die Filmlizenz und der erlaubte Datei-Endpunkt müssen unabhängig vorliegen.
- Eigene persistente SQLite-Warteschlange für ausdrücklich freigegebene HTTPS-MP4/MKV/WebM/MOV-Dateien. Ein Worker, Fortschritt, Pause, Retry und Range-Wiederaufnahme mit Datei-Validator; atomare Veröffentlichung und No-Overwrite. Keine `yt-dlp`-Downloads, keine HLS/DASH-, DRM-, Werbe- oder Geo-Umgehung.
- Ausführliche lokale Fehlermeldungen ohne Medien-URL/Token in UI oder Diagnose. Filmdatenbank/ArchiveMedia/öffentlich-rechtliche Jobs bleiben getrennt und unverändert.
- Quellcode-Freigabe ist keine Kopierlizenz für Inhalte: Die in der App angegebene Rechtebasis wird **nicht unabhängig verifiziert**. Automatische Dateiausleitung für den normalen Netzkino-Katalog bleibt deaktiviert.

'''


def once(s,old,new,label):
    count=s.count(old)
    if count!=1:raise RuntimeError(f'{label}: erwartete Einbaustelle {count}-mal statt einmal; Build bricht sicher ab')
    return s.replace(old,new,1)


def patch(project,dry_run=False):
    p=Path(project).resolve()
    required=['server.py','web/index.html','web/netzkino_detail.js','web/style.css',
              'build_macos.py','version.py','CHANGELOG.md','netzkino.py',
              'archive_companion.py','portal_control.py','yt_dlp_probe.py',
              'netzkino_enrichment.py','video_backfill.py']
    for n in required:
        if not (p/n).is_file():raise RuntimeError('Integrationsquelle fehlt: '+n)
    d={name:(p/name).read_text('utf8') for name in
       ('server.py','web/index.html','web/netzkino_detail.js','web/style.css',
        'build_macos.py','version.py','CHANGELOG.md')}
    s=d['server.py']
    for marker in ("if path=='/api/netzkino-watch':", "if path=='/api/netzkino-enrich':",
                   "if path=='/api/archive-companion':", "if path=='/api/video-audit':"):
        if marker not in s:raise RuntimeError('Plattformbestandsschutz fehlt: '+marker)
    if "VERSION='0.5.31.8'" not in d['version.py']:raise RuntimeError('Version 0.5.31.8 erforderlich')
    s=once(s,'portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment',
           'portal_metadata_policy, netzkino_details, yt_dlp_probe, netzkino_enrichment, netzkino_downloads',
           'Server-Import')
    s=once(s,"        if path=='/api/netzkino-reference-report':",
'''        if path=='/api/netzkino-downloads':
            return self.send(netzkino_downloads.listing(ROOT))
        if path=='/api/netzkino-reference-report':''','Lese-Route')
    s=once(s,"            if path=='/api/netzkino-enrich':",
'''            if path=='/api/netzkino-download-add':
                if NETWORK:raise ValueError('Berechtigte Direktdateien nur im lokalen macOS-Modus')
                result=netzkino_downloads.enqueue(ROOT,str(d.get('id','')),
                    d.get('file_url',''),d.get('rights_basis',''),
                    d.get('rights_note',''),confirmed=d.get('confirmed') is True)
                diagnostics.event('netzkino_licensed_download_enqueued',created=result['created'])
                return self.send(result)
            if path=='/api/netzkino-download-action':
                if NETWORK:raise ValueError('Dateiverwaltung nur im lokalen macOS-Modus')
                result=netzkino_downloads.action(ROOT,d.get('id',''),d.get('action',''),
                    output=Path(DEFAULT_DOWNLOAD_DIR)/'Netzkino-lizenzierte-Dateien')
                diagnostics.event('netzkino_licensed_download_control',action=d.get('action',''))
                return self.send(result)
            if path=='/api/netzkino-enrich':''','Schreib-Routen')
    s=once(s,"    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()",
'''    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()
    if not NETWORK and not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):
        # Separate low-concurrency worker; does not alter broadcaster/ArchiveMedia queues.
        threading.Thread(target=netzkino_downloads.loop,
            args=(ROOT,Path(DEFAULT_DOWNLOAD_DIR)/'Netzkino-lizenzierte-Dateien',STOP),
            daemon=True,name='netzkino_licensed_file_worker').start()''','Workerstart')
    # Leave existing web token/session guard intact; expose only counts, not private URLs.
    s=once(s,"'threads':[t.name for t in threading.enumerate()]",
           "'netzkino_licensed_downloads':netzkino_downloads.summary(ROOT),'threads':[t.name for t in threading.enumerate()]",
           'Diagnosezähler')
    s=once(s,"'/netzkino_detail.js','/unified_catalog.js'",
           "'/netzkino_detail.js','/netzkino_downloads.js','/unified_catalog.js'",
           'Asset-Freigabe')
    html=once(d['web/index.html'],'<div id="atlas-nk-actions"></div>',
'''<details id="atlas-nk-downloads">
          <summary>Download / Offline-Nutzung</summary>
          <p>Die kostenlose Netzkino-Wiedergabe ist keine allgemeine Datei-Downloadfreigabe. Die vom Anbieter angebotene Offline-Funktion nutzt du über die <a href="https://play.google.com/store/apps/details?id=de.netzkino.android.ics" target="_blank" rel="noopener noreferrer">offizielle Android-App</a> (Geräteunterstützung beim Anbieter prüfen).</p>
          <p>Ein eigener Datei-Download ist hier nur möglich, wenn du **zusätzlich** die entsprechende Berechtigung und eine vom Rechteinhaber bereitgestellte direkte Videodatei besitzt. Keine Streaming-/Player-URLs einfügen.</p>
          <form id="atlas-nk-download-form">
            <label class="nk-download-wide">Berechtigter direkter HTTPS-Dateilink (MP4, MKV, WebM, MOV)<input id="atlas-nk-download-url" type="url" required maxlength="1200" placeholder="https://rechteinhaber.example/film.mp4"></label>
            <label>Nachweisart<select id="atlas-nk-download-basis" required>
              <option value="">Bitte auswählen</option>
              <option value="written_permission">Ausdrückliche schriftliche Downloadfreigabe</option>
              <option value="rights_holder">Eigene Rechte am Film</option>
              <option value="public_domain">Nachweislich gemeinfreies Werk</option>
            </select></label>
            <label class="nk-download-wide">Quelle der Berechtigung / Freigabe (ohne Tokens)<textarea id="atlas-nk-download-note" required minlength="24" maxlength="600" rows="2"></textarea></label>
            <label class="nk-download-wide nk-download-check"><input type="checkbox" id="atlas-nk-download-confirm" required> Ich habe das Recht, diese konkrete Datei unabhängig vom Netzkino-Stream lokal herunterzuladen.</label>
            <button class="primary" type="submit">Berechtigten Datei-Download vormerken</button>
          </form>
          <p id="atlas-nk-download-status" role="status"></p>
          <div id="atlas-nk-download-jobs" aria-live="polite"></div>
        </details><div id="atlas-nk-actions"></div>''','Rechte-Dialog')
    html=once(html,'<script src="/netzkino_detail.js"></script>',
              '<script src="/netzkino_detail.js"></script><script src="/netzkino_downloads.js"></script>',
              'UI-Skript')
    js=once(d['web/netzkino_detail.js'],"      const m = data.details || {};",
'''      const m = data.details || {};
      if (window.AtlasNetzkinoDownloads) window.AtlasNetzkinoDownloads.mount(id);''',
            'Downloadbereich im Film öffnen')
    build=once(d['build_macos.py'],"'netzkino_enrichment.py'",
               "'netzkino_enrichment.py','netzkino_downloads.py'",'Downloadmodul ins App-Bundle')
    build=once(build,"'CFBundleVersion':'518'","'CFBundleVersion':'519'",'Mac-Buildnummer')
    outputs={
        'server.py':s,'web/index.html':html,'web/netzkino_detail.js':js,
        'web/style.css':d['web/style.css']+'\n'+(HERE/'web/netzkino_downloads.css').read_text('utf8'),
        'build_macos.py':build,
        'version.py':once(d['version.py'],"VERSION='0.5.31.8'","VERSION='0.5.31.9'",'Projektversion'),
        'CHANGELOG.md':CHANGELOG+d['CHANGELOG.md'],
        'netzkino_downloads.py':(HERE/'netzkino_downloads.py').read_text('utf8'),
        'web/netzkino_downloads.js':(HERE/'web/netzkino_downloads.js').read_text('utf8')
    }
    if dry_run:
        print('0.5.31.9: gesonderte Lizenz-Dateien, ArchiveMedia-/Netzkino-/Audit-Bestandsschutz validiert')
        return sorted(outputs)
    for path,data in outputs.items():
        target=p/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(data,'utf8')
    print('0.5.31.9: Rechte-geprüfter Direktdatei-Worker, UI und Diagnose integriert')
    return sorted(outputs)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('root');a.add_argument('--dry-run',action='store_true')
    x=a.parse_args();patch(x.root,x.dry_run)
