#!/usr/bin/env python3
"""Finish local v0.5.31.2 Netzkino GraphQL/HAR snapshot preview after 0.5.31.1 patches.

Only source files are modified; no existing user database or GitHub refs.
"""
import argparse,shutil
from pathlib import Path
import apply_preview
SOURCE=Path(__file__).resolve().parent

CHANGELOG='''## 0.5.31.2 – Netzkino-Katalogimport (lokale Preview)
- Die im Netzwerkmitschnitt vom 11.11.2026 beobachteten lesenden GraphQL-Katalogoperationen AllContent und CategoryDataBySlug ersetzen die ungeeignete Sitemap als Standardquelle.
- Bereinigter HAR-Startbestand: 449 unterscheidbare Film- und Serienobjekte; keine HTTP-Header, Sitzungen, Player-Streams oder Tokens enthalten. Der Snapshot ist ausdrücklich kein Live-Verfügbarkeitsnachweis.
- Katalogdaten je Film: Quelltitel, Jahr, Genre-Hinweise, FSK, Cover, Quellkategorie und AVOD-/Plus-Hinweis, soweit vom Anbieter geliefert.
- Begrenzte Kategorienabfragen, Timeouts, vorübergehende Fehler und HTTP-429-Rückzug. Keine automatischen Filmseiten-Massenabfragen und keine Medien-Downloads.
- Die bestehende SQLite-Netzkino-Datenbank wird verlustfrei um zusätzliche Felder erweitert. Bestehende manuelle Links, Downloads und MediathekView-Katalog bleiben erhalten.
- Eine Nutzungserlaubnis für automatisierten Abruf ist nicht bestätigt. Die Schnittstelle kann sich ändern; vollständige Filmabdeckung wird nicht behauptet.

'''

def patch(project,dry_run=False):
    project=Path(project).expanduser().resolve()
    v=project/'version.py'
    if not v.is_file() or 'VERSION=\'0.5.31.1\'' not in v.read_text('utf-8'):
        raise RuntimeError('Erst die 0.5.31.1-Korrekturen installieren.')
    if not (project/'netzkino.py').is_file() or '_QUERY_HASHES' not in (project/'netzkino.py').read_text('utf-8'):
        raise RuntimeError('Neuer GraphQL-Netzkino-Adapter fehlt.')
    target=project/'assets'/'netzkino_seed.json'
    data=(SOURCE/'assets'/'netzkino_seed.json').read_bytes()
    if len(data)>1024*1024:raise RuntimeError('Netzkino-Startkatalog zu groß.')
    if dry_run:
        print('0.5.31.2: Version, HAR-Startkatalog und Änderungsprotokoll geprüft. Kein Benutzerbestand verändert.')
        return
    if target.exists():raise RuntimeError('Bereits vorhandener Netzkino-Startkatalog wird nicht überschrieben.')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(data)
    v.write_text(v.read_text('utf-8').replace("VERSION='0.5.31.1'","VERSION='0.5.31.2'"),'utf-8')
    log=project/'CHANGELOG.md'
    log.write_text(CHANGELOG+log.read_text('utf-8'),'utf-8')
    print('0.5.31.2: Netzkino-GraphQL-Katalog und bereinigter Startbestand installiert; GitHub unverändert.')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('project',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    patch(args.project,args.dry_run)
