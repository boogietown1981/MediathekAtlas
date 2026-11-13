"""Build an unsigned .app with a shared robust launcher and Finder icon."""
from pathlib import Path
import shutil,plistlib
from version import VERSION
ROOT=Path(__file__).parent
app=ROOT/'build'/'MediathekAtlas.app'
if app.exists():shutil.rmtree(app)
resources=app/'Contents'/'Resources';code=resources/'app';macos=app/'Contents'/'MacOS'
code.mkdir(parents=True);macos.mkdir(parents=True)
for name in ('core.py','range_relay.py','cast_photos.py','watch_state.py','storage_policy.py','archive_recognition.py','archive_selection.py','archive_scan_recovery.py','archive_uploaders.py','platform_registry.py','categories.py','task_control.py','ui_prefs.py','unified_index.py','portal_snapshot.py','stable_runtime.py','imdb_archive.py','matching.py','artwork.py','downloads.py','runtime_tools.py','metadata.py','local_library.py','negative_cache.py','provider_stats.py','tvdb.py','series_download.py','subscriptions.py','diagnostics.py','diagnostic_extensions.py','diagnostics_cli.py','catalog.py','catalog_service.py','meshjournal.py','streaming.py','meshpeer.py','filmlist.py','broadcaster.py','video_causality.py','netzkino.py','netzkino_details.py','yt_dlp_probe.py','netzkino_enrichment.py','netzkino_downloads.py','ytdl_bridge.py','pluto.py','pluto_downloads.py','pluto_enrichment.py','portal_reference.py','portal_enrichment.py','hls_guard.py','hls_variants.py','download_quality.py','page_scripts.py','http_timing.py','netcheck.py','reference_share.py','portal_title.py','job_queue.py','justwatch.py','justwatch_downloads.py','justwatch_enrichment.py','rakuten.py','rakuten_downloads.py','rakuten_enrichment.py','youtube.py','youtube_downloads.py','youtube_enrichment.py','live_tv.py','db_backup.py','archive_downloads.py','video_backfill.py','portal_sources.py','portal_control.py','portal_metadata_policy.py','archive_companion.py','joyn.py','joyn_enrichment.py','toggo.py','toggo_enrichment.py','server.py','instance.py','access.py','version.py','browser_extension.py','LICENSE'):
    shutil.copy2(ROOT/name,code/name)
for name in ('web','vendor','assets'):
    shutil.copytree(ROOT/name,code/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(ROOT/'assets'/'MediathekAtlas.icns',resources/'MediathekAtlas.icns')
plist={'CFBundleName':'MediathekAtlas','CFBundleDisplayName':'MediathekAtlas','CFBundleIdentifier':'de.mediathekatlas.desktop','CFBundleVersion':'591','CFBundleShortVersionString':VERSION,'CFBundleExecutable':'MediathekAtlas','CFBundleIconFile':'MediathekAtlas.icns','CFBundlePackageType':'APPL','LSUIElement':True,'LSMinimumSystemVersion':'11.0'}
(app/'Contents'/'Info.plist').write_bytes(plistlib.dumps(plist))
launcher=macos/'MediathekAtlas';shutil.copy2(ROOT/'launcher.sh',launcher);launcher.chmod(0o755)
# Optional native Netzkino player window (official web player in WKWebView). Until 0.5.32
# only the integration kit compiled it; now every macOS build does when Swift exists.
import subprocess,sys
swiftc=shutil.which('swiftc') if sys.platform=='darwin' else None
if swiftc and (ROOT/'netzkino_webplayer.swift').is_file():
    helper=code/'netzkino_webplayer'
    r=subprocess.run([swiftc,str(ROOT/'netzkino_webplayer.swift'),'-framework','AppKit','-framework','WebKit','-o',str(helper)])
    if r.returncode==0:helper.chmod(0o755)
    else:helper.unlink(missing_ok=True);print('WARNUNG: Netzkino-WebKit-Fenster nicht gebaut; „Beim Anbieter öffnen“ bleibt verfügbar.')
print(app)
