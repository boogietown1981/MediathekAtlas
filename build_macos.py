"""Build an unsigned .app with a shared robust launcher and Finder icon."""
from pathlib import Path
import shutil,plistlib
from version import VERSION
ROOT=Path(__file__).parent
app=ROOT/'build'/'MediathekAtlas.app'
if app.exists():shutil.rmtree(app)
resources=app/'Contents'/'Resources';code=resources/'app';macos=app/'Contents'/'MacOS'
code.mkdir(parents=True);macos.mkdir(parents=True)
for name in ('core.py','stable_runtime.py','imdb_archive.py','matching.py','artwork.py','downloads.py','runtime_tools.py','metadata.py','provider_stats.py','tvdb.py','series_download.py','diagnostics.py','diagnostics_cli.py','catalog.py','catalog_service.py','meshjournal.py','meshpeer.py','filmlist.py','broadcaster.py','server.py','instance.py','access.py','version.py','LICENSE'):
    shutil.copy2(ROOT/name,code/name)
for name in ('web','vendor','assets'):
    shutil.copytree(ROOT/name,code/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(ROOT/'assets'/'MediathekAtlas.icns',resources/'MediathekAtlas.icns')
plist={'CFBundleName':'MediathekAtlas','CFBundleDisplayName':'MediathekAtlas','CFBundleIdentifier':'de.mediathekatlas.desktop','CFBundleVersion':'32','CFBundleShortVersionString':VERSION,'CFBundleExecutable':'MediathekAtlas','CFBundleIconFile':'MediathekAtlas.icns','CFBundlePackageType':'APPL','LSUIElement':True,'LSMinimumSystemVersion':'11.0'}
(app/'Contents'/'Info.plist').write_bytes(plistlib.dumps(plist))
launcher=macos/'MediathekAtlas';shutil.copy2(ROOT/'launcher.sh',launcher);launcher.chmod(0o755)
print(app)
