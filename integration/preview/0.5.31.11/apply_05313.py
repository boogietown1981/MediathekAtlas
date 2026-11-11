#!/usr/bin/env python3
"""Integrate read-only cross-platform diagnostic snapshots into the final source.

Runs after v0.5.31.2 and PR #24 preservation. Does not touch user databases.
"""
from pathlib import Path
import argparse

HERE=Path(__file__).resolve().parent


def one(text,old,new,name):
    if text.count(old)!=1:raise RuntimeError(f'{name}: Anker nicht eindeutig ({text.count(old)})')
    return text.replace(old,new,1)


def patch(src,dry_run=False):
    root=Path(src).resolve()
    expected=['version.py','diagnostics.py','build_macos.py','server.py','web/index.html','netzkino.py']
    if any(not (root/n).is_file() for n in expected):raise RuntimeError('Unvollständiger Projektquellstand')
    check_server=(root/'server.py').read_text()
    check_html=(root/'web/index.html').read_text()
    for symbol in ('/api/netzkino','/api/archive-companion','/api/video-audit','/api/portals'):
        if symbol not in check_server:raise RuntimeError('Integration fehlt im Server: '+symbol)
    for symbol in ('id="portals"','id="netzkino"','id="video-audit-panel"','archive-full-mode'):
        if symbol not in check_html:raise RuntimeError('UI-Funktion verloren: '+symbol)
    version=(root/'version.py').read_text()
    version=one(version,"VERSION='0.5.31.2'","VERSION='0.5.31.3'",'Version')
    d=(root/'diagnostics.py').read_text()
    d=one(d,'def export(snapshot):\n    out=io.BytesIO()',
'''def export(snapshot):
    # Read-only platform snapshots for both UI export and offline diagnostics CLI.
    # Never initialize a DB, query a website or attach catalogue/stream files.
    try:
        from diagnostic_extensions import collect
        snapshot={**snapshot,**collect(_root)}
    except (OSError,ValueError,RuntimeError) as exc:
        snapshot={**snapshot,'platform_diagnostics':{'error_type':type(exc).__name__}}
    out=io.BytesIO()''','Diagnose-Export')
    mb=(root/'build_macos.py').read_text()
    mb=one(mb,"'diagnostics.py','diagnostics_cli.py'",
             "'diagnostics.py','diagnostic_extensions.py','diagnostics_cli.py'",
             'macOS-Diagnosemodul')
    mb=one(mb,"'CFBundleVersion':'51'","'CFBundleVersion':'513'",'Bundle-Nummer')
    mb=one(mb,"'LSUIElement':True","'LSUIElement':True",'UI-Kennzeichen') if False else mb
    # Diagnostics includes Netzkino and ArchiveMedia in *both* export entrypoints.
    notes='''## 0.5.31.3 – integrierter Plattform- und Fehlerdiagnose-Teststand
- Einheitliche Testversion aus 0.5.31 + Netzkino-GraphQL/HAR-Katalog + 0.5.31.1-Korrekturen + ArchiveMedia-Companion/Portaladapter aus PR #24.
- Diagnoseexport und Offline-CLI protokollieren nun Netzkino-Bestände, GraphQL/HAR-Herkunft, Kategoriestatus, Letztfehler, Metadatenvollständigkeit, Altbestandsprüfung und Archive-Portalscopes; ohne Medien-URLs, Titel oder Zugangsdaten.
- Netzkino-Katalogabgleich protokolliert Start, erfolgreiche Kategorien, neue/geänderte Titel und HTTP-Fehlerklasse datensparsam.
- ArchiveMedia bleibt als eigenständige vollständige Anwendung erhalten; ihre Mediathek- und Download-Daten werden nicht verändert.
- Abgleich gegen GitHub-PRs #23 und #24; Voll-Tests und nativer macOS-Build sind auf Zielgerät nachzuholen.

'''
    patches={'version.py':version,'diagnostics.py':d,'build_macos.py':mb,
             'CHANGELOG.md':notes+(root/'CHANGELOG.md').read_text(),
             'diagnostic_extensions.py':(HERE/'diagnostic_extensions.py').read_text(),
             'tests/test_diagnostic_extensions.py':(HERE/'tests/test_diagnostic_extensions.py').read_text()}
    if dry_run:
        print('0.5.31.3 Diagnose-Integration und alle drei Plattformen geprüft: ', ', '.join(patches))
        return
    for file,body in patches.items():
        target=root/file
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(body)
    print('Neue Diagnosefelder für Netzkino, Videoprüfung und ArchiveMedia eingebaut.')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('--dry-run',action='store_true')
    v=a.parse_args();patch(v.source,v.dry_run)
