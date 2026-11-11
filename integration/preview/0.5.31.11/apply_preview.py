#!/usr/bin/env python3
"""Safely install local Netzkino streaming link preview into a MediathekAtlas checkout.

No network connections, GitHub modifications, database migrations or media downloads.
"""
from __future__ import annotations
import argparse
import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent

NETZKINO_VIEW = '''<section id="netzkino" hidden>
  <div class="sectionhead"><h2>Netzkino · Streaming-Katalog</h2>
    <a href="https://www.netzkino.de/" target="_blank" rel="noopener noreferrer" class="netzkino-open">Netzkino öffnen</a>
  </div>
  <p class="muted">Separate Streaming-Bibliothek: offizielle Filmseiten öffnen, ohne Video-Downloads.
     Die Zuordnung im Netzkino-Katalog ist zunächst ein Hinweis, keine bestätigte Werkidentität.</p>
  <div class="panel netzkino-sync-panel">
    <h3>Öffentlichen Netzkino-Katalog prüfen</h3>
    <p class="muted">Öffentliche Film- und Kategorieninformationen über die im Browser beobachtete Netzkino-GraphQL-Schnittstelle.
       Startbestand: bereinigter HAR-Katalog vom 11.11.2026. Live-Abgleich erfolgt nur auf ausdrücklichen Wunsch bzw. mit aktivierter Tagesautomatik.
       Keine Player-/Stream-Abfragen, keine DRM-Umgehung, keine bestätigte Verfügbarkeit.</p>
    <div class="netzkino-sync-actions"><button type="button" id="netzkino-sync" class="primary">↻ Katalog jetzt prüfen</button>
      <label class="check"><input type="checkbox" id="netzkino-auto"> Alle 24 Stunden automatisch nachprüfen (Opt-in)</label></div>
    <p id="netzkino-sync-summary" class="muted">Katalogstatus wird geladen …</p>
  </div>
  <details class="panel netzkino-manual"><summary>Einzelne Netzkino-Filmseite manuell hinzufügen</summary>
    <form id="netzkino-add" class="netzkino-form">
      <label>Filmtitel<input id="netzkino-title" type="text" minlength="2" maxlength="180" required placeholder="Filmtitel"></label>
      <label>Netzkino-Filmseite (HTTPS)<input id="netzkino-url" type="url" required placeholder="https://www.netzkino.de/…"></label>
      <button class="primary" type="submit">Filmseite merken</button>
    </form>
  </details>
  <div class="netzkino-toolbar"><label>Netzkino-Titel suchen
    <input type="search" id="netzkino-filter" placeholder="Titel suchen"></label>
    <label>Quelle<select id="netzkino-origin"><option value="all">Alle Netzkino-Einträge</option>
    <option value="catalog">Katalog / HAR-Startbestand</option><option value="manual">Manuell gemerkt</option></select></label></div>
  <p id="netzkino-status" class="muted" role="status">Netzkino-Verknüpfungen werden geladen …</p>
  <div id="netzkino-items" class="netzkino-grid" aria-live="polite"></div>
  <div class="netzkino-pages"><button type="button" id="netzkino-prev">← Zurück</button>
    <span id="netzkino-page-label" class="muted">Seite 1</span>
    <button type="button" id="netzkino-next">Weiter →</button></div>
</section>
'''

CSS = '''
/* Netzkino: isolated public-metadata catalogue, no downloads. */
.netzkino-sync-panel{max-width:760px;margin:16px 0}.netzkino-sync-actions{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.netzkino-sync-actions .check{margin:0}.netzkino-sync-actions input{width:auto}.netzkino-manual{max-width:760px;margin:16px 0}.netzkino-manual summary{cursor:pointer}.netzkino-form{max-width:760px;margin:16px 0 22px}.netzkino-form label{display:block}
.netzkino-toolbar{max-width:460px}.netzkino-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(265px,1fr));gap:14px;margin-top:16px}
.netzkino-pages{display:flex;align-items:center;justify-content:flex-end;gap:14px;margin:18px 0}.netzkino-item{border:1px solid #304559;border-radius:13px;background:#152233;padding:19px;min-width:0}
.netzkino-item h3{font-size:16px;margin:0 0 10px;overflow-wrap:anywhere}.netzkino-item{display:flex;flex-direction:column;gap:10px}.netzkino-poster{height:260px;width:100%;object-fit:contain;background:#0a111d;border-radius:8px}.netzkino-facts{font-size:12px;color:#a1c9bf}.netzkino-description{font-size:12px;line-height:1.5;color:#b4c4d3;max-height:66px;overflow:hidden}.netzkino-actions{margin-top:auto}
.netzkino-item small{display:block;margin-bottom:18px}.netzkino-actions{display:flex;gap:10px;flex-wrap:wrap}
.netzkino-open{display:inline-block;padding:10px 14px;color:#9aefcf;border:1px solid #3a665c;border-radius:8px;text-decoration:none;font-weight:600}
.netzkino-open:hover{background:#24433b}.netzkino-error{color:#ffaf9d!important}
@media(max-width:650px){.netzkino-grid{grid-template-columns:minmax(0,1fr)}}
'''
CHANGELOG = '''## Unreleased: Netzkino-Streaming-Preview (lokaler Patch, Basis v0.5.31)
- Separater Netzkino-Reiter: manuell geprüfte Filmseiten als Streaming-Verknüpfungen speichern und über den offiziellen Webplayer öffnen.
- Isolierte lokale SQLite-Datenbank `netzkino_links.sqlite3`; kein Einfluss auf den Senderkatalog, Downloadjobs, MeshSync oder bestehende Metadaten.
- Nur HTTPS auf `netzkino.de`, keine fremden URLs, keine Stream-Extraktion, kein Video-Download und keine DRM-Umgehung.
- Regressionsprüfungen für URL-Validierung, Dubletten, Persistenz, Löschung und Suchfilter.
- Ausstehend: offizieller Katalogimport, Metadatenreferenzen und native macOS-/NAS-Integrationstests.

'''


def replace_once(content: str, old: str, new: str, label: str) -> str:
    if content.count(old) != 1:
        raise RuntimeError(f'{label}: erwarteter Code-Anker nicht eindeutig vorhanden ({content.count(old)} Treffer). Keine Dateien verändert.')
    return content.replace(old, new, 1)




def patch_macos_build(content):
    # Both 0.5.30/0.5.31 use an explicit source whitelist. The NAS build
    # enumerates Python modules already, and needs no modification.
    if "'netzkino.py'" in content: return content
    return replace_once(content, "'server.py'", "'netzkino.py','server.py'", 'macOS-App-Build')

def upgrade_files(project, server, html, js, css, changelog):
    """Migrate previous link-only patch without touching its SQLite data."""
    if "if path=='/api/netzkino-sync':" in server:
        raise RuntimeError('Netzkino-Katalog-Preview ist bereits eingebaut. Keine Dateien verändert.')
    server = replace_once(server,
        "return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0])})",
        "return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0],80,q.get('offset',['0'])[0]),'status':netzkino.state(ROOT),'total':netzkino.count_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0])})",
        'Netzkino-Listenstatus')
    server = replace_once(server,
        "if path=='/api/shutdown' and MANAGED:",
        "if path=='/api/netzkino-sync':\n"
        "                return self.send({'started':netzkino.start_sync(ROOT)})\n"
        "            if path=='/api/netzkino-auto':\n"
        "                return self.send({'status':netzkino.set_auto(ROOT,d.get('enabled'))})\n"
        "            if path=='/api/shutdown' and MANAGED:",
        'Netzkino neue Endpunkte')
    server = replace_once(server,
        "    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()",
        "    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()\n"
        "    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):\n"
        "        threading.Thread(target=netzkino.loop,args=(ROOT,STOP),daemon=True,name='netzkino_catalog_scheduler').start()",
        'Zeitplanung')
    old_view = '<section id="netzkino" hidden>'
    start = html.find(old_view)
    end = html.find('<section id="review" hidden>',start)
    if start < 0 or end <= start:
        raise RuntimeError('Netzkino-Ansicht für Upgrade nicht eindeutig erkannt.')
    html = html[:start] + NETZKINO_VIEW + html[end:]
    if '/* Netzkino: isolated streaming catalogue' not in css:
        css += '\n' + CSS
    changelog = CHANGELOG + changelog
    changes = {'server.py':server.encode(),'web/index.html':html.encode(),
        'web/style.css':css.encode(),'CHANGELOG.md':changelog.encode(),
        'netzkino.py':(SOURCE/'compat_05314/netzkino.py').read_bytes(),
        'web/netzkino.js':(SOURCE/'compat_05314/web/netzkino.js').read_bytes()}
    if (project/'build_macos.py').is_file():
        changes['build_macos.py'] = patch_macos_build((project/'build_macos.py').read_text(encoding='utf-8')).encode('utf-8')
    return changes

def patch_files(project: Path):
    required = ['server.py', 'web/index.html', 'web/app.js', 'web/style.css', 'CHANGELOG.md', 'version.py']
    for rel in required:
        if not (project / rel).is_file():
            raise RuntimeError('Kein vollständiger MediathekAtlas-Checkout: ' + rel + ' fehlt.')
    server = (project / 'server.py').read_text(encoding='utf-8')
    html = (project / 'web/index.html').read_text(encoding='utf-8')
    js = (project / 'web/app.js').read_text(encoding='utf-8')
    css = (project / 'web/style.css').read_text(encoding='utf-8')
    changelog = (project / 'CHANGELOG.md').read_text(encoding='utf-8')
    macbuild = (project/'build_macos.py').read_text(encoding='utf-8') if (project/'build_macos.py').is_file() else None
    version = (project / 'version.py').read_text(encoding='utf-8')
    if '0.5.31' not in version and '0.5.30' not in version:
        raise RuntimeError('Diese Preview ist nur gegen MediathekAtlas 0.5.30/0.5.31 geprüft; Installation abgebrochen.')
    if 'from version import VERSION' not in server:
        raise RuntimeError('Unbekannter MediathekAtlas-Serveraufbau; Installation abgebrochen.')
    if "if path=='/api/netzkino':" in server:
        return upgrade_files(project,server,html,js,css,changelog)

    server = replace_once(server,
        'import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions',
        'import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino',
        'Netzkino-Import')
    server = replace_once(server,
        "if path in ('/app.js','/player.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')",
        "if path in ('/app.js','/player.js','/netzkino.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')",
        'JavaScript-Bereitstellung')
    server = replace_once(server,
        "        if path=='/api/play':",
        "        if path=='/api/netzkino':\n"
        "            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)\n"
        "            return self.send({'items':netzkino.list_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0],80,q.get('offset',['0'])[0]),'status':netzkino.state(ROOT),'total':netzkino.count_links(ROOT,q.get('q',[''])[0],q.get('origin',['all'])[0])})\n"
        "        if path=='/api/play':",
        'Netzkino-Lesefunktion')
    server = replace_once(server,
        "            if path=='/api/shutdown' and MANAGED:",
        "            if path=='/api/netzkino-add':\n"
        "                return self.send({'item':netzkino.add(ROOT,d.get('title'),d.get('url'))})\n"
        "            if path=='/api/netzkino-remove':\n"
        "                return self.send({'removed':netzkino.remove(ROOT,d.get('id'))})\n"
        "            if path=='/api/netzkino-sync':\n"
        "                return self.send({'started':netzkino.start_sync(ROOT)})\n"
        "            if path=='/api/netzkino-auto':\n"
        "                return self.send({'status':netzkino.set_auto(ROOT,d.get('enabled'))})\n"
        "            if path=='/api/shutdown' and MANAGED:",
        'Netzkino-Schreibfunktionen')

    html = replace_once(html,
        '<button class="nav active" data-view="discover">▤ &nbsp; Katalog</button>',
        '<button class="nav active" data-view="discover">▤ &nbsp; Katalog</button><button class="nav" data-view="netzkino">▶ &nbsp; Netzkino</button>',
        'Netzkino-Navigation')
    html = replace_once(html,
        '<section id="review" hidden>',
        NETZKINO_VIEW + '<section id="review" hidden>',
        'Netzkino-Bereich')
    html = replace_once(html,
        '<script src="/player.js"></script>',
        '<script src="/player.js"></script><script src="/netzkino.js"></script>',
        'Netzkino-Frontend')
    js = replace_once(js,
        "['discover','review','queue','subscriptions','settings','logs']",
        "['discover','netzkino','review','queue','subscriptions','settings','logs']",
        'Tab-Wechsel')
    server = replace_once(server,
        "    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()",
        "    threading.Thread(target=SERVICE.supervise,args=(worker,),daemon=True,name='download_worker').start()\n"
        "    if not os.environ.get('MEDIATHEKATLAS_DISABLE_BACKGROUND'):\n"
        "        threading.Thread(target=netzkino.loop,args=(ROOT,STOP),daemon=True,name='netzkino_catalog_scheduler').start()",
        'Netzkino-Zeitplanung')
    if '/* Netzkino: isolated streaming catalogue' in css:
        raise RuntimeError('Die Netzkino-Styles sind bereits vorhanden.')
    css += CSS
    if '## Unreleased: Netzkino-Katalog-Preview' not in changelog:
        changelog = CHANGELOG + changelog

    changes = {
        'server.py': server.encode('utf-8'),
        'web/index.html': html.encode('utf-8'),
        'web/app.js': js.encode('utf-8'),
        'web/style.css': css.encode('utf-8'),
        'CHANGELOG.md': changelog.encode('utf-8'),
        'netzkino.py': (SOURCE/'compat_05314/netzkino.py').read_bytes(),
        'web/netzkino.js': (SOURCE/'compat_05314/web/netzkino.js').read_bytes(),
    }
    if macbuild is not None:
        changes['build_macos.py'] = patch_macos_build(macbuild).encode('utf-8')
    for rel in ('netzkino.py', 'web/netzkino.js'):
        if (project / rel).exists():
            raise RuntimeError(f'{rel} existiert bereits. Bitte die Upgrade-Funktion verwenden.')
    return changes


def install(project: Path, dry_run=False):
    project = project.expanduser().resolve()
    modifications = patch_files(project)
    if dry_run:
        print('Änderungen möglich (nur Vorschau):', ', '.join(modifications))
        return modifications
    suffix = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = project.parent / (project.name + '-Netzkino-Backup-' + suffix)
    backup.mkdir(exist_ok=False)
    originals = {}
    changed = []
    try:
        for rel in modifications:
            path = project / rel
            if path.exists():
                originals[rel] = path.read_bytes()
                target = backup / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(originals[rel])
        for rel, data in modifications.items():
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write into a temporary sibling and rename, so truncated edits cannot be observed.
            with tempfile.NamedTemporaryFile(prefix='.netzkino-', dir=target.parent, delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)
            try:
                if target.exists():
                    os.chmod(tmp_path, target.stat().st_mode & 0o777)
                os.replace(tmp_path, target)
            finally:
                tmp_path.unlink(missing_ok=True)
            changed.append(rel)
    except Exception:
        for rel in reversed(changed):
            target = project / rel
            if rel in originals:
                target.write_bytes(originals[rel])
            else:
                target.unlink(missing_ok=True)
        raise
    print('Lokale Preview installiert. GitHub blieb unverändert.')
    print('Backup:', backup)
    for rel in changed:
        print(' +', rel)
    return modifications


def main():
    parser = argparse.ArgumentParser(description='Netzkino-Streaming-Vorschau für MediathekAtlas')
    parser.add_argument('project', type=Path, help='Pfad zum MediathekAtlas-Quellverzeichnis')
    parser.add_argument('--dry-run', action='store_true', help='Nur Voraussetzungen und Änderungsankerpunkte prüfen')
    args = parser.parse_args()
    try:
        install(args.project, args.dry_run)
    except (ValueError, OSError, RuntimeError) as exc:
        print('Abbruch:', exc, file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
