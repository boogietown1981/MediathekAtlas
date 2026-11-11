#!/usr/bin/env python3
"""Non-destructive Netzkino film/series/episode view patch for a verified 0.5.31.4 tree.

Applies after apply_05314, preserving both PR #23 (video audit) and PR #24
(ArchiveMedia companion/platform adapters). No network or app-data access.
"""
from pathlib import Path
import argparse

HERE=Path(__file__).resolve().parent
CHANGELOG='''## 0.5.31.5 – Netzkino: Filme / Serien / Folgen (lokale Testversion)
- Öffentliche Netzkino-Katalogeinträge getrennt nach Filmen und Serien anzeigen. Explizit mit Staffel- oder Folgennummer gekennzeichnete ContentMovie-Einträge werden als einzelne Episoden eingeordnet, ohne die Rohdaten umzuschreiben.
- Serien erhalten eine stabile, zusammengefasste Karte; Folgen sortiert nach Staffel und Folgennummer, jede Folge behält ihre offizielle Netzkino-URL. Unklare Film-Mehrteiler und Filmreihen werden nicht automatisch zu Serien.
- Nummerierungslücken werden als Kataloghinweise angezeigt, nicht als Verfügbarkeitsbehauptung. Manuelle Verknüpfungen bleiben erhalten.
- Diagnoseexport enthält getrennte Film-/Serien-/Episodenzähler, ohne Titel, URLs oder Nutzerdaten. Keine Veränderung des Download-, Werk- oder ArchiveMedia-Katalogs.
- ArchiveMedia-Vollmodus, Internet-Archive-Adapter, Netzkino-GraphQL-Abgleich, Warteschlangen-Fix und fortsetzbares Videoaudit bleiben erhalten.

'''
VIEW='''  <div class="netzkino-media-tabs" role="group" aria-label="Netzkino-Medienart">
    <button type="button" id="netzkino-view-movies" class="primary">Filme</button>
    <button type="button" id="netzkino-view-series">Serien</button>
    <button type="button" id="netzkino-back-series" hidden>← Zur Serienübersicht</button>
    <span id="netzkino-series-heading" role="status"></span>
  </div>
'''
ROUTE='''        if path=='/api/netzkino-grouped':
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            data=netzkino.grouped_catalog(ROOT,view=q.get('view',['movies'])[0],
                series_key=q.get('series_key',[''])[0],
                query=q.get('q',[''])[0],origin=q.get('origin',['all'])[0],
                offset=q.get('offset',['0'])[0],limit=80)
            data['status']=netzkino.state(ROOT)
            return self.send(data)
'''

def once(txt,old,new,name):
    n=txt.count(old)
    if n!=1:raise RuntimeError(f'{name}: erwarteter Integrationsanker fehlt oder ist mehrfach vorhanden ({n}). Keine Änderungen ausgeführt.')
    return txt.replace(old,new,1)

def patch(project,dry_run=False):
    root=Path(project).expanduser().resolve()
    expected=['netzkino.py','diagnostic_extensions.py','web/netzkino.js',
              'web/index.html','web/style.css','server.py','build_macos.py',
              'version.py','CHANGELOG.md','archive_companion.py','portal_control.py',
              'portal_sources.py','video_backfill.py']
    for name in expected:
        if not (root/name).is_file():raise RuntimeError(f'Quellstand unvollständig: {name}')
    server=(root/'server.py').read_text('utf-8')
    html=(root/'web/index.html').read_text('utf-8')
    css=(root/'web/style.css').read_text('utf-8')
    version=(root/'version.py').read_text('utf-8')
    build=(root/'build_macos.py').read_text('utf-8')
    for marker in ("if path=='/api/netzkino':","if path=='/api/netzkino-sync':",
                   "if path=='/api/archive-companion':","if path=='/api/portal-archive-inspect':",
                   "if path=='/api/video-audit':"):
        if marker not in server:raise RuntimeError(f'API aus älterem Strang fehlt: {marker}')
    for marker in ('id="netzkino"','id="archive-full-mode"',
                   'id="archive-platform-controls"','id="video-audit-panel"'):
        if marker not in html:raise RuntimeError('UI eines anderen Strangs fehlt: '+marker)
    if '/* 0.5.31.4: exact platform isolation' not in css:
        raise RuntimeError('Fehlerkorrektur 0.5.31.4 nicht enthalten.')
    current=(root/'netzkino.py').read_text('utf-8')
    if '_category_failure_type' not in current or 'def grouped_catalog(' in current:
        raise RuntimeError('Unerwartete Netzkino-Version; kein blindes Überschreiben.')
    js=(root/'web/netzkino.js').read_text('utf-8')
    if 'window.MediathekAtlasNetzkino = {refresh};' not in js or 'netzkino-grouped?' in js:
        raise RuntimeError('Netzkino-Frontend unerwartet; kein blindes Überschreiben.')
    patched={
        'server.py':once(server,"        if path=='/api/netzkino':",ROUTE+"        if path=='/api/netzkino':",'Lese-API'),
        'web/index.html':once(html,'  <div class="netzkino-toolbar">',VIEW+'  <div class="netzkino-toolbar">','Netzkino-Navigation'),
        'web/style.css':css+'\n'+(HERE/'web/netzkino_05315.css').read_text('utf-8'),
        'version.py':once(version,"VERSION='0.5.31.4'","VERSION='0.5.31.5'",'Versionsnummer'),
        'build_macos.py':once(build,"'CFBundleVersion':'514'","'CFBundleVersion':'515'",'Bundle-Versionsnummer'),
        'CHANGELOG.md':CHANGELOG+(root/'CHANGELOG.md').read_text('utf-8'),
        'netzkino.py':(HERE/'netzkino.py').read_text('utf-8'),
        'diagnostic_extensions.py':(HERE/'diagnostic_extensions.py').read_text('utf-8'),
        'web/netzkino.js':(HERE/'web/netzkino.js').read_text('utf-8'),
        'tests/test_v05315.py':(HERE/'tests/test_v05315.py').read_text('utf-8'),
    }
    assert 'def grouped_catalog(' in patched['netzkino.py']
    assert 'media_classification' in patched['diagnostic_extensions.py']
    assert 'netzkino-view-series' in patched['web/netzkino.js']
    if dry_run:
        print('0.5.31.5: Filme/Serien/Folgen + Diagnose, PR #23/24 und Netzkino-GraphQL-Parität: OK')
        return list(patched)
    for name,data in patched.items():
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(data,'utf-8')
    print('0.5.31.5: Netzkino-Gruppierung eingebaut; Bestandsdatenbanken und ArchiveMedia unverändert.')
    return list(patched)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('--dry-run',action='store_true')
    args=a.parse_args();patch(args.source,args.dry_run)
