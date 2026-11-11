#!/usr/bin/env python3
"""Apply v0.5.31.1 safety corrections on top of the Netzkino local preview.

No GitHub writes. No databases touched during installation. All patch anchors
must match exactly before creating an atomic, rollbackable backup.
"""
from __future__ import annotations
import argparse
import os
import tempfile
import datetime as dt
from pathlib import Path
import apply_preview

SOURCE=Path(__file__).resolve().parent

AUDIT_UI='''<div class="panel atlas-video-audit" id="video-audit-panel">
  <div class="sectionhead"><h3>Altbestandsprüfung · Videoformate</h3><button type="button" id="video-audit-refresh">↻ Aktualisieren</button></div>
  <p class="muted">Prüft auch bereits erkannte Werke. Automatisch bestätigte Treffer bleiben erhalten und werden bei Laufzeitkonflikten markiert. Manuelle Zuordnungen werden nicht verändert.</p>
  <p class="muted" id="video-audit-progress" role="status">Prüfstand wird geladen …</p>
  <progress id="video-audit-bar" value="0" max="100"></progress>
  <div id="video-audit-results" class="atlas-audit-results"></div>
</div>'''
CSS='''
/* v0.5.31.1: independent video-role backfill audit status. */
.atlas-video-audit{max-width:none;margin:14px 0 24px}.atlas-video-audit progress{width:100%;height:9px;accent-color:#67e1bc}
.atlas-audit-results{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:8px;margin:14px 0}
.atlas-audit-entry{padding:12px;background:#101b28;border:1px solid #304050;border-radius:8px}
.atlas-audit-entry strong{display:block;line-height:1.4}.atlas-audit-entry small{display:block;margin:6px 0;line-height:1.4}
'''
CHANGELOG='''## 0.5.31.1 – Netzkino + sichere Altbestands-Klassifizierung (lokale Testversion)
- Sichere Episoden-Trigger: Duplicate-Guard statt INSERT OR IGNORE innerhalb von UPSERT-Triggern; Bestandsjobs bleiben erhalten.
- Einmaliger fortsetzbarer lokaler Videorollen-Audit mit eigenem Cursor, kleiner Batchgröße, Persistenz und Fortschrittsanzeige. Auch bereits erkannte und automatisch bestätigte Werke werden geprüft.
- Manuell bestätigte Zuordnungen und fertige Downloads bleiben unverändert; automatische Treffer mit Laufzeitkonflikt erhalten eine Prüfmarkierung statt einer stillen Herabstufung.
- Separater Netzkino-Streaming-Katalog mit Link-Speicherung, opt-in Sitemap-Prüfung und offiziellem Player (kein Mediendownload).
- Die Live-Katalogquelle und macOS-Ausführung müssen auf dem Zielgerät noch überprüft werden.

'''

def one(src,old,new,why):
    return apply_preview.replace_once(src,old,new,why)

def patches(project):
    project=Path(project)
    expected=['catalog.py','catalog_service.py','server.py','web/index.html','web/style.css','version.py','build_macos.py']
    for p in expected:
        if not (project/p).is_file():raise RuntimeError('MediathekAtlas-Datei fehlt: '+p)
    files={p:(project/p).read_text('utf-8') for p in expected}
    cat=files['catalog.py']
    if 'episode_queue_safe_upsert_v05311' in cat or 'video_role_audit_cursor_v05311' in cat:
        raise RuntimeError('Korrektur ist bereits vorhanden.')
    cat=one(cat,
        ' INSERT OR IGNORE INTO episode_queue(work_id) VALUES(NEW.id);',
        ' INSERT INTO episode_queue(work_id) SELECT NEW.id\n'
        ' WHERE NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);',
        'SQL-Trigger bei INSERT')
    cat=one(cat,
        ' INSERT OR IGNORE INTO episode_queue(work_id)\n SELECT NEW.id WHERE',
        ' INSERT INTO episode_queue(work_id)\n SELECT NEW.id WHERE',
        'SQL-Trigger bei UPDATE')
    cat=one(cat,
        " AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0;\nEND;",
        " AND COALESCE(json_extract(NEW.meta,'$.video_role_needs_review'),0)=0\n"
        " AND NOT EXISTS(SELECT 1 FROM episode_queue WHERE work_id=NEW.id);\nEND;",
        'SQL-Trigger Duplikatschutz')
    cat=one(cat,
        "    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:",
        "    # Recreate the trigger definitions without altering existing queue rows.\n"
        "    # Outer UPSERT conflict handling must never override an inner OR IGNORE.\n"
        "    if not get_state(c,'episode_queue_safe_upsert_v05311',False):\n"
        "        c.executescript(\"\"\"DROP TRIGGER IF EXISTS episode_queue_work_insert;\n"
        "            DROP TRIGGER IF EXISTS episode_queue_work_update;\n"
        "            DROP TRIGGER IF EXISTS episode_queue_work_delete;\"\"\")\n"
        "        c.executescript(SCHEMA)\n"
        "        set_state(c,'episode_queue_safe_upsert_v05311',True)\n"
        "    if 'topic' not in [r[1] for r in c.execute('PRAGMA table_info(works)')]:",
        'Migration für Trigger')
    files['catalog.py']=cat

    service=files['catalog_service.py']
    service=one(service,
        'self.sync_loop,self.reclassify_loop,self.artwork_loop',
        'self.sync_loop,self.reclassify_loop,self.video_audit_loop,self.artwork_loop',
        'Audit-Worker registrieren')
    service=one(service,
        '    def reclassify_loop(self):',
        "    def video_audit_loop(self):\n"
        "        # Reads only local catalogue rows, in short persisted transactions.\n"
        "        import video_backfill\n"
        "        with self.db() as c:video_backfill.initialize(c)\n"
        "        while not self.stop.is_set():\n"
        "            try:\n"
        "                with self.db() as c:n=video_backfill.audit_batch(c,limit=120)\n"
        "            except sqlite3.OperationalError as exc:\n"
        "                if not sqlite_busy(exc):raise\n"
        "                self.sqlite_busy_count+=1\n"
        "                if self.stop.wait(.7):return\n"
        "                continue\n"
        "            if n==0:\n"
        "                diagnostics.event('video_audit_complete')\n"
        "                return\n"
        "            if self.stop.wait(.12):return\n\n"
        "    def reclassify_loop(self):",
        'Audit-Worker umsetzen')
    files['catalog_service.py']=service

    server=files['server.py']
    server=one(server,
        'import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino',
        'import core, downloads, runtime_tools, catalog, catalog_service, diagnostics, series_download, access, meshjournal, meshpeer, streaming, local_library, subscriptions, netzkino, video_backfill',
        'Audit-Serverimport')
    server=one(server,
        "if path in ('/app.js','/player.js','/netzkino.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')",
        "if path in ('/app.js','/player.js','/netzkino.js','/video_audit.js'):return self.send((Path(__file__).parent/'web'/path[1:]).read_bytes(),ctype='text/javascript')",
        'Audit-JavaScript')
    server=one(server,
        "        if path=='/api/netzkino':",
        "        if path=='/api/video-audit':\n"
        "            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)\n"
        "            with db() as c:\n"
        "                video_backfill.initialize(c)\n"
        "                return self.send(video_backfill.status(c,q.get('offset',['0'])[0]))\n"
        "        if path=='/api/netzkino':",
        'Audit-Status-API')
    files['server.py']=server

    html=files['web/index.html']
    html=one(html,
        '<section id="review" hidden>',
        '<section id="review" hidden>'+AUDIT_UI,
        'Audit-Dashboard')
    html=one(html,
        '<script src="/netzkino.js"></script>',
        '<script src="/netzkino.js"></script><script src="/video_audit.js"></script>',
        'Audit-Frontend')
    files['web/index.html']=html
    files['web/style.css'] += '\n'+CSS
    files['version.py']=one(files['version.py'],"VERSION='0.5.31'", "VERSION='0.5.31.1'", 'Versionskennzeichnung')
    files['build_macos.py']=one(files['build_macos.py'],"'netzkino.py','server.py'","'netzkino.py','video_backfill.py','server.py'",'macOS-Modulpaket')
    out={rel:body.encode('utf-8') for rel,body in files.items() if body != (project/rel).read_text('utf-8')}
    changelog=(project/'CHANGELOG.md').read_text('utf-8')
    out['CHANGELOG.md']=(CHANGELOG+changelog).encode('utf-8')
    out['video_backfill.py']=(SOURCE/'video_backfill.py').read_bytes()
    out['web/video_audit.js']=(SOURCE/'web/video_audit.js').read_bytes()
    return out

def install(project, dry_run=False):
    project=Path(project).expanduser().resolve()
    out=patches(project)
    if dry_run:
        print('0.5.31.1-Korrekturen geprüft:',', '.join(out))
        return out
    backup=project.parent/(project.name+'-05311-Backup-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(exist_ok=False)
    originals={};changed=[]
    try:
        for rel in out:
            target=project/rel
            if target.is_file():
                originals[rel]=target.read_bytes()
                b=backup/rel;b.parent.mkdir(parents=True,exist_ok=True);b.write_bytes(originals[rel])
        for rel,payload in out.items():
            target=project/rel;target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.v05311-',delete=False) as f:
                f.write(payload)
                staged=Path(f.name)
            try:
                if target.is_file():os.chmod(staged,target.stat().st_mode & 0o777)
                os.replace(staged,target)
            finally:staged.unlink(missing_ok=True)
            changed.append(rel)
    except BaseException:
        for rel in reversed(changed):
            target=project/rel
            if rel in originals:target.write_bytes(originals[rel])
            else:target.unlink(missing_ok=True)
        raise
    print('Korrekturen lokal installiert. Keine Bestandsdatenbank verändert. Backup:',backup)
    return out

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('project',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:install(args.project,args.dry_run)
    except (OSError,RuntimeError,ValueError) as e:
        parser.exit(1,'Korrektur abgebrochen: '+str(e)+'\n')

if __name__=='__main__':main()
