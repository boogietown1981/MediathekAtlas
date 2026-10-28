"""Export existing logs without starting the web server or catalogue import."""
import json,os,sqlite3,subprocess,sys,time
from pathlib import Path
import diagnostics

def main():
    root=Path(os.environ.get('MEDIATHEKATLAS_HOME',Path.home()/'Library'/'Application Support'/'MediathekAtlas' if sys.platform=='darwin' else Path.home()/'.mediathekatlas'))
    # Read only the secrets needed for redaction; never export settings or database.
    if (root/'catalog.db').exists():
        c=None
        try:
            c=sqlite3.connect((root/'catalog.db').as_uri()+'?mode=ro',uri=True,timeout=2)
            row=c.execute('SELECT payload FROM settings WHERE id=1').fetchone()
            if row:
                settings=json.loads(row[0]);diagnostics.register_secrets(settings.get('tmdb'),settings.get('omdb'))
        except (sqlite3.Error,ValueError):pass
        finally:
            if c:c.close()
    diagnostics.setup(root)
    target=Path.home()/'Desktop'
    if not target.is_dir():target=Path.home()
    dest=target/('MediathekAtlas_Diagnose_'+time.strftime('%Y%m%d-%H%M%S')+'.zip')
    with dest.open('xb') as f:f.write(diagnostics.export({'mode':'offline_export'}))
    print(dest,flush=True)
    if sys.platform=='darwin':subprocess.run(['/usr/bin/open','-R',str(dest)],check=False)
if __name__=='__main__':main()
