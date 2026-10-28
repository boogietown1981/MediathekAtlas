"""Copy executable resources out of transient macOS app locations before launch."""
import hashlib,os,shutil,sys,tempfile
from pathlib import Path

def prepare(source,state):
    source=Path(source).resolve();parent=Path(state)/'runtime';parent.mkdir(parents=True,exist_ok=True)
    files=[p for p in source.rglob('*') if p.is_file() and not any(x in ('.git','build','dist','__pycache__') for x in p.relative_to(source).parts) and p.suffix!='.pyc']
    digest=hashlib.sha256()
    for p in sorted(files):digest.update(str(p.relative_to(source)).encode());digest.update(p.read_bytes())
    dest=parent/digest.hexdigest()[:20]
    if (dest/'web'/'index.html').is_file():return dest
    staging=Path(tempfile.mkdtemp(prefix='stage-',dir=parent))
    try:
        for p in files:
            target=staging/p.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        if not (staging/'server.py').exists() or not (staging/'web'/'index.html').exists():raise ValueError('App-Ressourcen fehlen')
        try:staging.rename(dest)
        except FileExistsError:
            if not (dest/'web'/'index.html').is_file():raise
        return dest
    finally:
        if staging.exists():shutil.rmtree(staging)
if __name__=='__main__':print(prepare(sys.argv[1],sys.argv[2]))
