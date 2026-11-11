#!/usr/bin/env python3
"""Merge additive PR #24 ArchiveMedia/portals into PR #23 + Netzkino preview.

Uses exact, frozen GitHub branch SHAs. Never checks out/replaces an existing app.
Fails closed whenever a source marker unexpectedly changes. Test before shipping.
"""
import argparse
import os
import subprocess
from pathlib import Path

PORTAL_COMMIT='c7b6cf9c84a911299a4d1d37f98892959e71fbeb'
# PR #24 is cloned independently; never fetch another shallow branch into
# PR #23's Git database (macOS Git can reject concurrent shallow updates).
ADDED=(
 'archive_companion.py', 'portal_control.py', 'portal_metadata_policy.py', 'portal_sources.py',
 'docs/EXTERNAL_PORTALS.md', 'docs/METADATA_EVIDENCE_MATRIX.md',
 'tests/test_archive_video_selection.py','tests/test_portal_metadata_contract.py',
 'tests/test_portal_scans.py','tests/test_v0532_portals.py',
 'vendor/archive_portals/LICENSE.txt','vendor/archive_portals/catalog_identity.py',
 'vendor/archive_portals/catalog_repair.py','vendor/archive_portals/container_tracks.py',
 'vendor/archive_portals/item_language_hints.py','vendor/archive_portals/media_probe.py',
 'vendor/archive_portals/reference_pipeline.py','vendor/archive_portals/unified_inventory.py',
 'vendor/archive_portals/video_triage.py','vendor/archive_portals/work_validation.py')


def _one(text, old, new, name):
    n=text.count(old)
    if n!=1:raise RuntimeError(f'{name}: erwartet genau eine Einbaustelle, gefunden {n}')
    return text.replace(old,new,1)


def _segment(source,begin,end,name):
    if source.count(begin)!=1 or source.count(end)<1:raise RuntimeError(f'{name}: Quellanker fehlen')
    return source.split(begin,1)[1].split(end,1)[0]


def integrate(files, pr24):
    """Pure, testable source merge. Returned mapping does not mutate inputs."""
    out=dict(files)
    # Do not replace 0.5.31.2's server or either database: add PR24's isolated routes.
    server=out['server.py']
    if 'portal_sources, portal_control' in server:raise RuntimeError('Portale bereits integriert')
    server=_one(server, 'subscriptions, netzkino, video_backfill',
                'subscriptions, netzkino, video_backfill, portal_sources, portal_control, archive_companion, portal_metadata_policy',
                'Servermodulimporte')
    server=_one(server, '    subscriptions.initialize(c)\n',
                '    subscriptions.initialize(c)\n    portal_sources.initialize(c)\n    portal_control.initialize(c)\n',
                'SQLite-Portalinitialisierung')
    getblock='        if path==\'/api/archive-companion\':' + _segment(
        pr24['server.py'], "        if path=='/api/archive-companion':", "        if path=='/api/catalog':", 'Portal-GET')
    server=_one(server,"        if path=='/api/catalog':",getblock+"        if path=='/api/catalog':",'Portal-GET-Routen')
    postblock="            if path=='/api/portal-controls':"+_segment(
        pr24['server.py'], "            if path=='/api/portal-controls':", "            if path=='/api/search':", 'Portal-POST')
    server=_one(server,"            if path=='/api/search':",postblock+"            if path=='/api/search':",'Portal-POST-Routen')
    server=_one(server,'        SERVICE.start()','        portal_control.Scheduler(db,STOP).start()\n        SERVICE.start()','Portal-Scheduler')
    out['server.py']=server

    # The external-portal dashboard is the single platform entry point. Its
    # Netzkino subtab embeds our larger GraphQL catalogue instead of duplicating
    # the main sidebar. The original PR24 portal browser and manual form remain.
    html=out['web/index.html']
    html=_one(html,'<button class="nav" data-view="netzkino">▶ &nbsp; Netzkino</button>',
              '<button class="nav" data-view="portals">◎ &nbsp; Plattformen</button>', 'Plattformnav')
    i=html.find('<section id="netzkino" hidden>')
    j=html.find('<section id="review" hidden>',i)
    if i<0 or j<0 or i>j:raise RuntimeError('Netzkino-Seite für Zusammenführung fehlt')
    nz=html[i:j].replace('<section id="netzkino" hidden>','<section id="netzkino">',1)
    html=html[:i]+html[j:]
    portals='<section id="portals" data-platform="overview" hidden>'+_segment(
        pr24['web/index.html'],'<section id="portals" data-platform="overview" hidden>',
        '<section id="title-view"','Portal-Dashboard')
    # Keep the Netzkino preview inside the official Netzkino platform tab.
    portals=_one(portals,'  <div id="portal-status" role="status" class="muted"></div>',
                 nz+'\n  <div id="portal-status" role="status" class="muted"></div>',
                 'Netzkino-Katalog in Plattform-UI')
    portals=portals.replace('Netzkino bleibt manuell.',
                            'Netzkino führt einen optionalen öffentlichen Katalogabgleich aus.')
    html=_one(html,'<section id="title-view"',portals+'<section id="title-view"','Portal-Dashboard')
    out['web/index.html']=html

    app=out['web/app.js']
    app=_one(app,"['discover','netzkino','review','queue','subscriptions','settings','logs']",
                 "['discover','portals','review','queue','subscriptions','settings','logs']",'Sidebar-Navigation')
    app=_one(app,"if(b.dataset.view==='subscriptions')loadSubscriptions();",
                 "if(b.dataset.view==='subscriptions')loadSubscriptions();if(b.dataset.view==='portals')loadPortals();",
                 'Plattform-Initialisierung')
    if 'let portalOffset=' in app:raise RuntimeError('Portal-JS doppelt vorhanden')
    if pr24['web/app.js'].count('let portalOffset=0,portalBusy=false;')!=1:raise RuntimeError('Portal-JS-Startmarker fehlt')
    app+='\nlet portalOffset=0,portalBusy=false;'+pr24['web/app.js'].split('let portalOffset=0,portalBusy=false;',1)[1]
    out['web/app.js']=app

    css=out['web/style.css']
    marker='/* External portal catalogue: rights-first, compact responsive layout. */'
    if pr24['web/style.css'].count(marker)!=1:raise RuntimeError('Portal-CSS-Marker fehlt')
    css+='\n'+marker+pr24['web/style.css'].split(marker,1)[1]
    css+='\n/* Integrated GraphQL catalogue is visible only on the Netzkino platform. */\n'
    css+='#portals #netzkino{display:none}\n#portals[data-platform="netzkino"] #netzkino{display:block}\n'
    # Avoid showing two separate manual-entry panels; PR24's legacy manual
    # form remains accessible through the existing portal browser.
    out['web/style.css']=css

    js=out['web/netzkino.js']
    if 'window.MediathekAtlasNetzkino = {refresh};' in js:
        # New JS binds to the platform tab itself and exposes refresh() to portalView.
        if 'isVisible()' not in js:raise RuntimeError('Netzkino-Hook unvollständig')
    else:
        js=_one(js,"  document.querySelector('[data-view=\"netzkino\"]').addEventListener('click', refresh);",
                      "  const sidebar = document.querySelector('[data-view=\"netzkino\"]);\n"
                      "  if (sidebar) sidebar.addEventListener('click', refresh);\n"
                      "  for (const tab of document.querySelectorAll('.platform-tab[data-platform=\"netzkino\"]'))\n"
                      "    tab.addEventListener('click', refresh);",'Netzkino-Tab-Hook')
        js=js.replace("if (!$('netzkino').hidden) refresh();",
                      "if (!$('portals').hidden && $('portals').dataset.platform === 'netzkino') refresh();")
    out['web/netzkino.js']=js

    mb=out['build_macos.py']
    mb=_one(mb,"'video_backfill.py','server.py'",
                "'video_backfill.py','portal_sources.py','portal_control.py','portal_metadata_policy.py','archive_companion.py','server.py'",
                'Build-Vollmodusmodule')
    out['build_macos.py']=mb

    original=pr24['CHANGELOG.md']
    change_begin='## In Arbeit – Isolierte externe Filmportale (noch keine Release-Freigabe)'
    if change_begin in original:
        notes=change_begin+original.split(change_begin,1)[1].split('## 0.5.30',1)[0]
        out['CHANGELOG.md']=notes+'\n'+out['CHANGELOG.md']
    return out


def _git_show(repo,path):
    return subprocess.check_output(['git','-C',str(repo),'show',f'HEAD:{path}'],stderr=subprocess.PIPE)


def _check_portal_repo(src, portal_repo):
    """Verify distinct, pinned PR24 checkout; never change the PR23 git store."""
    if portal_repo is None:
        raise RuntimeError('Separates PR #24-Quellverzeichnis erforderlich (--portal-repo)')
    portal=Path(portal_repo).expanduser().resolve()
    if portal == Path(src).expanduser().resolve():
        raise RuntimeError('PR #23 und PR #24 dürfen nicht denselben Git-Klon verwenden')
    result=subprocess.run(['git','-C',str(portal),'rev-parse','HEAD'],
                          capture_output=True,text=True,check=True)
    if result.stdout.strip()!=PORTAL_COMMIT:
        raise RuntimeError('ArchiveMedia-Branch wurde verändert: erwarteter Commit '+PORTAL_COMMIT)
    return portal


def check(src,portal_repo):
    return _check_portal_repo(src,portal_repo)


def install(src,dry_run=False,portal_repo=None):
    src=Path(src).expanduser().resolve()
    portal=_check_portal_repo(src,portal_repo)
    overlap=('server.py','web/index.html','web/app.js','web/style.css','build_macos.py','CHANGELOG.md')
    local={p:(src/p).read_text('utf-8') for p in (*overlap,'web/netzkino.js')}
    theirs={p:_git_show(portal,p).decode('utf-8') for p in overlap}
    combined=integrate(local,theirs)
    for p in ADDED:
        content=_git_show(portal,p)
        if (src/p).exists() and (src/p).read_bytes()!=content:
            raise RuntimeError('Vorhandene Datei dürfte nicht überschrieben werden: '+p)
        combined[p]=content
    if dry_run:
        print(f'ArchiveMedia-Portalintegration geprüft: {len(combined)} Dateien, {len(ADDED)} erhaltene PR24-Bausteine.')
        return
    for p,v in combined.items():
        dest=src/p;dest.parent.mkdir(parents=True,exist_ok=True)
        payload=v.encode('utf-8') if isinstance(v,str) else v
        dest.write_bytes(payload)
    print('ArchiveMedia-Vollmodus/Portale aus unabhängigem PR24-Klon in PR23 lokal integriert.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('--portal-repo',required=True);parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args();install(args.source,args.dry_run,portal_repo=args.portal_repo)
