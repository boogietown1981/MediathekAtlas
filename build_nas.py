"""Build NAS packages: Synology SPK (DSM 7) and the QNAP QDK project / QPKG.

Pure Python, therefore one architecture-independent package per platform
(x86_64, ARM64, ARMv7 and older models with Python 3.9+).

  python3 build_nas.py                     # SPK + QDK project in build/qnap
  python3 build_nas.py --qbuild /path/qbuild  # additionally the .qpkg via QNAP's QDK
Build-only dependency: Pillow (icons).
"""
import argparse,hashlib,io,shutil,subprocess,sys,tarfile,time
from pathlib import Path
from version import VERSION
ROOT=Path(__file__).resolve().parent
PACKAGING=ROOT/'packaging'
NAME='MediathekAtlas';PORT=8730;SPK_BUILD='0001'
# Everything the server needs at runtime; build helpers stay out of packages.
BUILD_ONLY={'build_icons.py','build_macos.py','build_nas.py'}
APP_DIRS=('web','vendor','assets')

def app_files():
    return sorted(p.name for p in ROOT.glob('*.py') if p.name not in BUILD_ONLY)+['LICENSE']

def copy_app(dest):
    dest.mkdir(parents=True)
    for name in app_files():shutil.copy2(ROOT/name,dest/name)
    for name in APP_DIRS:
        shutil.copytree(ROOT/name,dest/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store','*.icns'))

def render(text,port=PORT):return text.replace('@VERSION@',VERSION).replace('@PORT@',str(port))

def icon(size,fmt='PNG',gray=False):
    from PIL import Image
    im=Image.open(ROOT/'assets'/'icon.png').convert('RGBA').resize((size,size),Image.Resampling.LANCZOS)
    if gray:im=im.convert('LA').convert('RGBA')
    if fmt=='GIF':
        # GIF has 1-bit transparency; flatten onto the dark app background.
        flat=Image.new('RGBA',im.size,(12,17,26,255));flat.alpha_composite(im);im=flat.convert('P',palette=Image.Palette.ADAPTIVE)
    out=io.BytesIO();im.save(out,format=fmt);return out.getvalue()

def add_bytes(tar,name,data,mode=0o644):
    info=tarfile.TarInfo(name);info.size=len(data);info.mode=mode;info.mtime=int(time.time());info.uname=info.gname='root'
    tar.addfile(info,io.BytesIO(data))

def add_tree(tar,path,arcname):
    def reset(info):
        info.uid=info.gid=0;info.uname=info.gname='root'
        if info.isdir():info.mode=0o755
        elif info.name.endswith('.sh'):info.mode=0o755
        else:info.mode=0o644
        return info
    tar.add(path,arcname=arcname,filter=reset)

def build_spk(out_dir,port=PORT):
    src=PACKAGING/'synology';stage=ROOT/'build'/'synology'
    if stage.exists():shutil.rmtree(stage)
    target=stage/'target';copy_app(target/'mediathekatlas')
    (target/'bin').mkdir();shutil.copy2(PACKAGING/'nas'/'mediathekatlas-service.sh',target/'bin'/'mediathekatlas-service.sh')
    (target/'ui'/'images').mkdir(parents=True)
    for name in ('config','MediathekAtlas.sc'):(target/'ui'/name).write_text(render((src/'ui'/name).read_text(),port))
    for size in (16,24,32,48,64,72,256):(target/'ui'/'images'/f'{NAME}_{size}.png').write_bytes(icon(size))
    package=io.BytesIO()
    with tarfile.open(fileobj=package,mode='w:gz') as tar:
        for child in sorted(target.iterdir()):add_tree(tar,child,child.name)
    package=package.getvalue()
    info={'package':NAME,'version':f'{VERSION}-{SPK_BUILD}','os_min_ver':'7.0-40000','displayname':NAME,
          'description':'Catalogue of the German public broadcasters\' media libraries with metadata matching and organised downloads to the NAS.',
          'description_ger':'Katalog der öffentlich-rechtlichen Mediatheken mit Metadatenabgleich und geordneten Downloads auf das NAS.',
          'maintainer':NAME,'arch':'noarch','install_dep_packages':'Python3.9','dsmuidir':'ui','dsmappname':'de.mediathekatlas',
          'adminprotocol':'http','adminport':str(port),'adminurl':'/','ctl_stop':'yes','thirdparty':'yes',
          'checksum':hashlib.md5(package).hexdigest()}
    out_dir.mkdir(parents=True,exist_ok=True)
    spk=out_dir/f'{NAME}-{VERSION}-noarch.spk'
    with tarfile.open(spk,'w',format=tarfile.USTAR_FORMAT) as tar:
        add_bytes(tar,'INFO',''.join(f'{k}="{v}"\n' for k,v in info.items()).encode())
        add_bytes(tar,'package.tgz',package)
        for folder,mode in (('scripts',0o755),('conf',0o644),('WIZARD_UIFILES',0o644)):
            for p in sorted((src/folder).iterdir()):add_bytes(tar,f'{folder}/{p.name}',render(p.read_text(),port).encode(),mode)
        add_bytes(tar,'PACKAGE_ICON.PNG',icon(64));add_bytes(tar,'PACKAGE_ICON_256.PNG',icon(256))
        add_bytes(tar,'LICENSE',(ROOT/'LICENSE').read_bytes())
    return spk

def build_qdk_project(port=PORT):
    src=PACKAGING/'qnap';project=ROOT/'build'/'qnap'
    if project.exists():shutil.rmtree(project)
    shared=project/'shared';copy_app(shared/'mediathekatlas')
    (shared/'bin').mkdir()
    shutil.copy2(PACKAGING/'nas'/'mediathekatlas-service.sh',shared/'bin'/'mediathekatlas-service.sh')
    (shared/'MediathekAtlas.sh').write_text(render((src/'shared'/'MediathekAtlas.sh').read_text(),port))
    for p in (shared/'MediathekAtlas.sh',shared/'bin'/'mediathekatlas-service.sh'):p.chmod(0o755)
    for name in ('qpkg.cfg','package_routines'):(project/name).write_text(render((src/name).read_text(),port))
    icons=project/'icons';icons.mkdir()
    (icons/f'{NAME}.gif').write_bytes(icon(64,'GIF'));(icons/f'{NAME}_80.gif').write_bytes(icon(80,'GIF'))
    (icons/f'{NAME}_gray.gif').write_bytes(icon(64,'GIF',gray=True))
    # No per-architecture folders: qbuild then emits one generic package for all models.
    return project

def build_qpkg(project,qbuild,out_dir):
    subprocess.run([qbuild,'--build-dir',str(project/'build')],cwd=project,check=True)
    built=sorted((project/'build').glob(f'{NAME}_*.qpkg'))
    if not built:raise SystemExit('qbuild hat kein QPKG erzeugt')
    out_dir.mkdir(parents=True,exist_ok=True)
    result=[]
    for qpkg in built:
        dest=out_dir/qpkg.name;shutil.copy2(qpkg,dest);result.append(dest)
        md5=qpkg.with_suffix('.qpkg.md5')
        if md5.exists():shutil.copy2(md5,out_dir/md5.name)
    return result

def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument('--out',default=str(ROOT/'dist'));a.add_argument('--port',type=int,default=PORT)
    a.add_argument('--qbuild',help='Pfad zu qbuild aus dem QNAP QDK; ohne Angabe nur das QDK-Projekt')
    a.add_argument('--only',choices=('spk','qpkg'))
    args=a.parse_args(argv);out=Path(args.out)
    if args.only!='qpkg':print(build_spk(out,args.port))
    if args.only!='spk':
        project=build_qdk_project(args.port);print(project)
        if args.qbuild:
            for p in build_qpkg(project,args.qbuild,out):print(p)

if __name__=='__main__':main()
