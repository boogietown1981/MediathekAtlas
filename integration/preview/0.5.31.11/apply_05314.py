#!/usr/bin/env python3
"""Apply the 0.5.31.4 UI/error-visibility repair AFTER 0.5.31.3 integration.

Never accesses user data or external services. Fails on unexpected source state.
"""
from pathlib import Path
import argparse

CSS = '''
/* 0.5.31.4: exact platform isolation (ArchiveMedia is still present on its tab). */
#portals[data-platform="netzkino"] > #archive-full-mode,
#portals[data-platform="netzkino"] > #archive-platform-controls,
#portals[data-platform="netzkino"] > #portal-platform-overview,
#portals[data-platform="netzkino"] > .portal-dashboard,
#portals[data-platform="netzkino"] > .portal-browser,
#portals[data-platform="netzkino"] > .portal-rights-note,
#portals[data-platform="netzkino"] > #portal-status {display:none!important}
#portals[data-platform="overview"] > #archive-full-mode,
#portals[data-platform="overview"] > #archive-platform-controls {display:none!important}
#portals[data-platform="archive"] > #netzkino {display:none!important}
#portals[data-platform="netzkino"] > #netzkino {display:block!important}
#netzkino-sync-summary[data-phase="partial"] {color:#f3c687}
#netzkino-sync-summary[data-phase="failed"],
#netzkino-sync-summary[data-phase="ui-error"] {color:#ffad9c}
#netzkino .netzkino-sync-panel {max-width:none}
#netzkino .netzkino-toolbar {max-width:620px}
'''
CHANGELOG='''## 0.5.31.4 – Netzkino-Kategoriefehler / Plattformanzeige (Teststand)
- Leere Netzkino-Kategorien werden von echten GraphQL-/Netzwerkfehlern unterschieden; bei Kategoriefehlern bleibt ein vorhandener gültiger Homepage-Katalog als ausdrücklich unvollständiger Teilabgleich verfügbar.
- Rate-Limits (429) und Zugangsfehler (401/403) stoppen weitere Kategorieabfragen. Rückzug statt Umgehung. Vollständigkeitsstatus und letzter vollständiger Abgleich werden separat persistiert.
- Diagnose enthält nun Anzahl leerer Kategorien, Fehlerarten und letzten Teil-/Voll-Abgleich; keine Filmnamen, Medienlinks, HAR-Header oder Sitzungstokens.
- Ein UI-Ladefehler erscheint neben dem Katalog-Knopf statt nur unterhalb der Trefferliste. Beim Wechsel auf den Netzkino-Reiter werden Einträge neu geladen.
- Netzkino blendet ArchiveMedia-Companion, Archivscanner, alte Netzkino-Doppelformulare und gemischte Portal-Trefferliste aus. Der ArchiveMedia-Vollmodus bleibt im Archiv-Reiter erhalten.
- Isolierte Portaldaten, bestehende Arbeitsdatenbank und 0.5.31.1-Altbestandsprüfung bleiben unverändert. Kein automatischer Video-Download.
- Öffentliche GraphQL-Endpunkte sind anhand eines HAR verifiziert, die rechtliche Freigabe und dauerhafte Live-Nutzbarkeit nicht; Test-Build, noch kein offizielles Release.

'''


def _once(text,old,new,name):
    count=text.count(old)
    if count!=1:raise RuntimeError(f'{name}: Anker nicht eindeutig ({count}). Kein Patch ausgeführt.')
    return text.replace(old,new,1)


def patch(project,dry_run=False):
    root=Path(project).expanduser().resolve()
    expected=['web/index.html','web/app.js','web/style.css','web/netzkino.js',
              'netzkino.py','video_backfill.py','diagnostic_extensions.py',
              'archive_companion.py','portal_sources.py','portal_control.py',
              'build_macos.py','server.py','version.py','CHANGELOG.md']
    for name in expected:
        if not (root/name).is_file():raise RuntimeError('Integration unvollständig: '+name)
    app=(root/'web/app.js').read_text('utf-8')
    css=(root/'web/style.css').read_text('utf-8')
    html=(root/'web/index.html').read_text('utf-8')
    server=(root/'server.py').read_text('utf-8')
    js=(root/'web/netzkino.js').read_text('utf-8')
    netzkino=(root/'netzkino.py').read_text('utf-8')
    diag=(root/'diagnostic_extensions.py').read_text('utf-8')
    for marker in ('/api/archive-companion','/api/portal-archive-inspect','/api/netzkino-sync',
                   '/api/diagnostics','/api/video-audit'):
        if marker not in server:raise RuntimeError('API-Komponente verloren: '+marker)
    for marker in ('id="archive-full-mode"','id="archive-platform-controls"',
                   'id="netzkino"','id="netzkino-sync-summary"','id="video-audit-panel"'):
        if marker not in html:raise RuntimeError('UI-Komponente verloren: '+marker)
    if 'window.MediathekAtlasNetzkino = {refresh};' not in js:
        raise RuntimeError('Netzkino-Ladehook fehlt; nicht mit altem JavaScript ausliefern.')
    if '_category_failure_type' not in netzkino or "'last_result','partial'" not in netzkino:
        raise RuntimeError('Neue Netzkino-Kategoriebehandlung fehlt.')
    if "'category_error_types'" not in diag:raise RuntimeError('Neue Diagnosefelder fehlen.')
    html=_once(html,'ARCHIVEMEDIA CORE','MEDIATHEKATLAS · LOKAL','Globales Branding')
    app=_once(app,"  portalOffset=0;loadPortals();\n  if(name==='archive')loadArchiveCompanion();",
                  "  portalOffset=0;loadPortals();\n  if(name==='archive')loadArchiveCompanion();\n  if(name==='netzkino')window.MediathekAtlasNetzkino?.refresh?.();",
                  'Aktivierung der Netzkino-Ansicht')
    # PR #24's separate scanner is different from the GraphQL catalogue.
    app=_once(app,"'Automatisches Scannen nicht unterstützt'",
                  "'Externer Portal-Scanner nicht verfügbar; Netzkino-GraphQL-Abgleich über den Netzkino-Reiter'",
                  'Portalübersicht (Netzkino)')
    if '/* 0.5.31.4: exact platform isolation' in css:raise RuntimeError('0.5.31.4 bereits angewendet')
    css+=CSS
    version=_once((root/'version.py').read_text('utf-8'),"VERSION='0.5.31.3'",
                  "VERSION='0.5.31.4'",'Version')
    build=_once((root/'build_macos.py').read_text('utf-8'),
                "'CFBundleVersion':'513'","'CFBundleVersion':'514'",'macOS-Buildnummer')
    output={'web/index.html':html,'web/app.js':app,'web/style.css':css,'version.py':version,
            'build_macos.py':build,'CHANGELOG.md':CHANGELOG+(root/'CHANGELOG.md').read_text('utf-8')}
    if dry_run:
        print('0.5.31.4: Netzkino-GraphQL, Fehlerdiagnose, Altbestandsprüfung und ArchiveMedia-Parität geprüft.')
        return output
    for name,data in output.items():(root/name).write_text(data,'utf-8')
    print('0.5.31.4-Korrekturen eingebaut; alle ArchiveMedia-Komponenten erhalten.')
    return output

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('--dry-run',action='store_true')
    args=a.parse_args();patch(args.source,args.dry_run)
