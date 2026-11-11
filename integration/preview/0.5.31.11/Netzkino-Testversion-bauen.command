#!/bin/bash
# MediathekAtlas 0.5.31.11: PR #23 + PR #24 ArchiveMedia + Netzkino/Video audit.
# Makes a separate, unsigned .app. It does not push commits, modify existing
# installations or touch any live catalogue. Diagnostics are read-only.
set -Eeuo pipefail
cd "$(dirname "$0")"
PREVIEW_DIR="$(pwd -P)"
mkdir -p "$HOME/Downloads"
WORKDIR="$(mktemp -d "$HOME/Downloads/MediathekAtlas-Integration-XXXXXX")"
LOG="$WORKDIR/Build-Protokoll.txt"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
step=0
failure() {
  local code="$1" line="$2"
  trap - ERR
  printf '\nFEHLER in Schritt %s (Zeile %s, Code %s)\n' "$step" "$line" "$code"
  echo "Unveränderte Installation. Build-Protokoll: $LOG"
  /usr/bin/open "$WORKDIR" || true
  /usr/bin/open -a TextEdit "$LOG" || true
  exit "$code"
}
trap 'failure $? $LINENO' ERR

echo 'MediathekAtlas 0.5.31.11 – Mediatheken-Dashboard, Episoden-Queue, Netzkino, ArchiveMedia'
echo "Buildordner: $WORKDIR"
echo "Build-Protokoll: $LOG"
echo 'PR #23: Video-/Episodenprüfung; PR #24: ArchiveMedia-Portale; 0.5.31.2: Netzkino GraphQL.'
if ! command -v python3 >/dev/null; then echo 'Python 3.9+ erforderlich.'; false; fi
python3 -c 'import sys; assert sys.version_info >= (3,9),sys.version'
if ! command -v git >/dev/null; then echo 'Git wird zum Abruf beider geprüfter PR-Quellstände benötigt.'; false; fi
SRC="$WORKDIR/Quellcode"
step=1
echo '[1/16] Originalstand von PR #23 abrufen …'
GIT_TERMINAL_PROMPT=0 git clone --progress --depth 1 --branch feature/0.5.31-video-causality-checks \
  https://github.com/boogietown1981/MediathekAtlas.git "$SRC"
BASE_EXPECTED='89d9438095ddcc0e40c5cc22128b746d2cb9c451'
BASE_ACTUAL="$(git -C "$SRC" rev-parse HEAD)"
if [ "$BASE_ACTUAL" != "$BASE_EXPECTED" ]; then
  echo 'Der Referenzstand von PR #23 hat sich geändert; ein unkontrollierter Merge wird verhindert.'
  false
fi
step=2
echo '[2/16] ArchiveMedia-/Portalstand PR #24 UNABHÄNGIG klonen und verifizieren …'
# Two independent shallow clones: never mutate the first clone's .git/shallow.
# This avoids "fatal: shallow file has changed since we read it" on macOS.
PORTAL_SRC="$WORKDIR/ArchiveMedia-PR24-Quelle"
GIT_TERMINAL_PROMPT=0 git clone --progress --depth 1 --no-tags \
  --branch feature/external-portals-catalog-adapters \
  https://github.com/boogietown1981/MediathekAtlas.git "$PORTAL_SRC"
PORTAL_EXPECTED='c7b6cf9c84a911299a4d1d37f98892959e71fbeb'
PORTAL_ACTUAL="$(git -C "$PORTAL_SRC" rev-parse HEAD)"
if [ "$PORTAL_ACTUAL" != "$PORTAL_EXPECTED" ]; then
  echo 'Der Referenzstand von PR #24 hat sich geändert. Nicht blind fortsetzen.'
  false
fi
step=3
echo '[3/16] Netzkino, Queue-Fix und Altbestandsprüfung einbauen …'
python3 "$PREVIEW_DIR/apply_preview.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_preview.py" "$SRC"
python3 "$PREVIEW_DIR/apply_05311.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05311.py" "$SRC"
python3 "$PREVIEW_DIR/apply_05312.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05312.py" "$SRC"
step=4
echo '[4/16] Alle offenen PR-Funktionen in einem Quellstand integrieren …'
python3 "$PREVIEW_DIR/merge_portals.py" "$SRC" --portal-repo "$PORTAL_SRC" --dry-run
python3 "$PREVIEW_DIR/merge_portals.py" "$SRC" --portal-repo "$PORTAL_SRC"
step=5
echo '[5/16] Plattformdiagnosen einbauen …'
python3 "$PREVIEW_DIR/apply_05313.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05313.py" "$SRC"
step=6
echo '[6/16] Netzkino-Kategorie- und Portal-UI-Fix einbauen …'
python3 "$PREVIEW_DIR/apply_05314.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05314.py" "$SRC"
step=7
echo '[7/16] Netzkino-Serien und Episoden konsolidieren …'
python3 "$PREVIEW_DIR/apply_05315.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05315.py" "$SRC"
step=8
echo '[8/16] Netzkino-Details, yt-dlp-Prüfung und Gesamtansicht einbauen …'
python3 "$PREVIEW_DIR/apply_05316.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05316.py" "$SRC"
echo '      IMDb/TMDB/TVDB/OMDb/Wikidata-Metadatenabgleich ergänzen …'
python3 "$PREVIEW_DIR/apply_05317.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05317.py" "$SRC"
step=9
echo '[9/16] Einheitliche Katalogansicht und Nested-Sidebar-Fehler korrigieren …'
python3 "$PREVIEW_DIR/apply_05318.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05318.py" "$SRC"
step=10
echo '[10/16] Berechtigte Direktdatei-Downloads und Offline-Anzeige integrieren …'
python3 "$PREVIEW_DIR/apply_05319.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_05319.py" "$SRC"
step=11
echo '[11/16] Netzkino-Wiedergabe ohne Browser-Redirect und Katalogabdeckung einbauen …'
python3 "$PREVIEW_DIR/apply_053110.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_053110.py" "$SRC"
step=12
echo '[12/16] Sichtbares Mediatheken-Dashboard, Staffel-404, Episoden-Queue und Anbieterstatus einbauen …'
python3 "$PREVIEW_DIR/apply_053111.py" "$SRC" --dry-run
python3 "$PREVIEW_DIR/apply_053111.py" "$SRC"
step=13
echo '[13/16] Vollständigkeit und Syntax prüfen …'
for module in netzkino.py netzkino_details.py netzkino_enrichment.py yt_dlp_probe.py netzkino_downloads.py video_backfill.py diagnostic_extensions.py archive_companion.py \
  portal_sources.py portal_control.py portal_metadata_policy.py vendor/archive_portals/video_triage.py; do
  test -f "$SRC/$module" || { echo "Fehlendes ArchiveMedia- oder Netzkino-Modul: $module"; false; }
done
python3 -m compileall -q "$SRC" -x '/\.git/'
if command -v node >/dev/null; then
  for js in "$SRC/web/app.js" "$SRC/web/netzkino.js" "$SRC/web/netzkino_detail.js" "$SRC/web/netzkino_downloads.js" "$SRC/web/unified_catalog.js" "$SRC/web/video_audit.js" "$SRC/web/player.js"; do node --check "$js"; done
  node "$PREVIEW_DIR/tests/netzkino_ui_smoke.cjs"
  node "$PREVIEW_DIR/tests/netzkino_series_ui_smoke.cjs"
  node "$PREVIEW_DIR/tests/unified_catalog_ui_smoke.cjs"
else
  echo 'Node.js nicht installiert: JS-Syntax wird im späteren CI geprüft; kein JS-Testnachweis.'
fi
# This check guards against silently dropping the ArchiveMedia full-mode UI.
python3 - "$SRC" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=(p/'server.py').read_text();h=(p/'web/index.html').read_text()
for api in ('/api/archive-companion','/api/portal-archive-inspect','/api/portal-netzkino-add',
            '/api/netzkino-sync','/api/netzkino-grouped','/api/netzkino-details',
            '/api/netzkino-metadata-probe','/api/netzkino-enrich','/api/netzkino-reference-report','/api/netzkino-downloads','/api/netzkino-download-add','/api/netzkino-download-action','/api/netzkino-watch','/api/video-audit','/api/diagnostics'):
    assert api in s, f'API-Funktion fehlt: {api}'
for marker in ('id="portals"','id="archive-full-mode"','id="netzkino"',
               'id="video-audit-panel"','id="netzkino-view-series"',
               'id="atlas-netzkino-detail"','id="atlas-nk-reference"','data-catalog-source="all"','id="pluto-info"'):
    assert marker in h, f'UI-Funktion fehlt: {marker}'
for marker in ('diagnostic_extensions.py','archive_companion.py','portal_sources.py','netzkino.py','netzkino_details.py','yt_dlp_probe.py','netzkino_enrichment.py','netzkino_downloads.py','video_backfill.py'):
    assert marker in (p/'build_macos.py').read_text(),f'App-Build verpackt {marker} nicht'
assert 'def grouped_catalog(' in (p/'netzkino.py').read_text(), 'Netzkino-Serienklassifizierung fehlt'
assert 'media_classification' in (p/'diagnostic_extensions.py').read_text(), 'Diagnose-Klassifizierung fehlt'
assert 'netzkino_public_details' in (p/'netzkino_details.py').read_text(), 'Netzkino-Detailcache fehlt'
assert 'MovieDetails' in (p/'netzkino.py').read_text(), 'GraphQL-Detailoperation fehlt'
assert 'external_references' in (p/'diagnostic_extensions.py').read_text(), 'Referenz-Diagnose fehlt'
assert 'def enrich(' in (p/'netzkino_enrichment.py').read_text(), 'Anbieter-Referenzabgleich fehlt'
assert 'id="atlas-nk-quickfacts"' in h, 'Kompakte Netzkino-Detailansicht fehlt'
assert 'quickFacts.replaceChildren()' in (p/'web/netzkino_detail.js').read_text(), 'Responsive Detailfelder fehlen'
assert '<aside class="nk-detail-sidebar">' not in h, 'Cover-Sidebar verwechselt mit App-Navigation'
assert '<div class="nk-detail-sidebar">' in h, 'Detail-Sidebar-Korrektur fehlt'
assert 'id="atlas-nk-download-form"' in h, 'Lizenzierte Direktdatei-UI fehlt'
assert 'netzkino_downloads.py' in (p/'build_macos.py').read_text(), 'Downloadverwaltung nicht gebündelt'
assert 'id="atlas-cross-genre"' in h, 'Gemeinsamer Genrefilter fehlt'
assert "advanced.id='atlas-catalog-advanced'" in (p/'web/unified_catalog.js').read_text(), 'Erweiterte Mediatheken-Funktionen nicht erhalten'
assert 'genre=q.get' in s, 'Lesender Netzkino-Genrefilter fehlt'
assert 'category_cap_hits' in (p/'netzkino.py').read_text(), 'Katalogabdeckungs-Diagnose fehlt'
assert 'category_over_20' in (p/'netzkino.py').read_text(), 'Neue realistische Kategoriegrößen-Diagnose fehlt'
assert 'atlas-main-dashboard' in (p/'web/unified_catalog.js').read_text(), 'Mediatheken-Dashboard nicht direkt sichtbar'
assert 'atlas-worker-group' in (p/'web/app.js').read_text(), 'Statusgruppen unter Letzte Erkennung fehlen'
assert 'tmdb_season_unavailable' in (p/'metadata.py').read_text(), '404 Staffelfehler nicht isoliert'
assert 'LIMIT 48' in (p/'catalog_service.py').read_text(), 'Episodenpriorisierung fehlt'
assert 'category_cap_hits' in (p/'diagnostic_extensions.py').read_text(), 'Katalogabdeckung nicht im Diagnoseexport'
assert "window.AtlasNetzkinoDetail = {open, play}" in (p/'web/netzkino_detail.js').read_text(), 'Direkte Wiedergabefunktion fehlt'
assert 'mode=\'native_unavailable\'' in s, 'Keine stillschweigende Browserweiterleitung'
assert 'NSWorkspace.shared.open' not in (p/'netzkino_webplayer.swift').read_text(), 'WebKit könnte Browser automatisch öffnen'
print('ArchiveMedia-/Netzkino-/Serien-/Audit-Parität und macOS-Modulpaket: OK')
PY
step=14
echo '[14/16] Projekt-Regressionstests einschließlich ArchiveMedia ausführen …'
(cd "$SRC" && python3 -m unittest discover -s tests -q)
step=15
echo '[15/16] Unabhängige Netzkino-/Diagnose-/Installer-Tests ausführen …'
(cd "$PREVIEW_DIR" && python3 -m unittest discover -s tests -q)
step=16
echo '[16/16] Native macOS-Test-App erstellen …'
(cd "$SRC" && python3 build_macos.py)
BUILT="$SRC/build/MediathekAtlas.app"
test -x "$BUILT/Contents/MacOS/MediathekAtlas"
for file in netzkino.py netzkino_details.py netzkino_enrichment.py yt_dlp_probe.py netzkino_downloads.py video_backfill.py diagnostic_extensions.py archive_companion.py \
 portal_sources.py portal_control.py portal_metadata_policy.py; do
 test -f "$BUILT/Contents/Resources/app/$file" || { echo "Modul fehlt im App-Paket: $file"; false; }
done
test -f "$BUILT/Contents/Resources/app/assets/netzkino_seed.json"
test -f "$BUILT/Contents/Resources/app/vendor/archive_portals/work_validation.py"
# A native WKWebView runs the ORIGINAL Netzkino web player, not media extraction.
# The helper is optional: no Swift compiler => the official browser remains available.
SWIFTC=""
if command -v xcrun >/dev/null 2>&1; then
  SWIFTC="$(xcrun --find swiftc 2>/dev/null || true)"
fi
if [ -n "$SWIFTC" ]; then
  echo 'Nativer Netzkino-WebKit-Player: wird optional gebaut …'
  if "$SWIFTC" "$PREVIEW_DIR/netzkino_webplayer.swift" \
      -framework AppKit -framework WebKit -o "$BUILT/Contents/Resources/app/netzkino_webplayer"; then
    chmod 755 "$BUILT/Contents/Resources/app/netzkino_webplayer"
    echo 'WebKit-Fenster integriert. Wiedergabe erfolgt über die offizielle Netzkino-Seite.'
  else
    rm -f "$BUILT/Contents/Resources/app/netzkino_webplayer"
    echo 'WARNUNG: Swift konnte nicht kompiliert werden. Offizieller Browser bleibt als Rückfalloption.'
  fi
else
  echo 'Kein Swift-Compiler: Die Filmseite kann weiterhin im offiziellen Browser geöffnet werden.'
fi
APP="$WORKDIR/MediathekAtlas-0.5.31.11-Integration-Test.app"
/usr/bin/ditto "$BUILT" "$APP"
/usr/bin/plutil -lint "$APP/Contents/Info.plist"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$APP.zip"
cat > "$WORKDIR/README-Testhinweise.txt" <<'TEXT'
MediathekAtlas 0.5.31.11: unsignierte Test-App; alte Anwendung regulär schließen.
Bisherige Anwenderdaten werden beim Build nicht verändert. Der erste App-Start
nutzt dieselbe MediathekAtlas-Datenbank wie die vorherige Version.
Portalübersicht: ArchiveMedia-Vollmodus benötigt separat laufendes ArchiveMedia.
Katalog: Gesamt/Mediatheken/Netzkino mit gemeinsamer Suche, Genres und Sortierung.
Netzkino: Detailfenster, Film-/Serien-/Folgenansicht ohne verschobenes Cover.
Mediatheken: Scanner, Erkennung und Katalogkennzahlen wieder direkt im Hauptdashboard sichtbar.
Mediatheken: Unter Letzte Erkennung sind die Statuskacheln in vier Gruppen organisiert.
Mediatheken: Das erweiterte Such-/Scanwerkzeug bleibt separat aufklappbar.
Netzkino: Kompakte zweispaltige Kurzdaten + ARD-Providerkette auf Klick; optional yt-dlp Metadata-Only, kein Download.
Netzkino: importierter HAR-Katalog ist kein Live-Verfügbarkeitsnachweis.
Netzkino: „Ansehen“ startet den offiziellen Player in einem separaten MediathekAtlas-WebKit-Fenster.
Kein automatischer Aufruf von Safari; wenn der native Player auf diesem Mac nicht erstellt werden konnte,
wird eine Fehlermeldung angezeigt. „Beim Anbieter öffnen“ bleibt als eigene manuelle Aktion.
Netzkino-Katalog: 29/29 geprüfte Startseiten-Kategorien bedeutet NICHT vollständige 2.500+ Titel.
Anzeige und Diagnose melden echte Kategoriegrößen (auch über 20), nicht eine erfundene Seitenobergrenze.
Netzkino-Dateien: Erweitertes Expertenformular nur für separat dokumentierte Lizenz-Direktdateien.
Normale AVOD-/Plus-Streams, DRM und Werbung bleiben unangetastet.
Diagnose: Live-Protokoll > Diagnose-ZIP; offline: App --diagnose.
ArchiveMedia PR #24, 0.5.31 PR #23, Netzkino, Pluto-Info und Videoaudit sind enthalten.
Ein erfolgreicher Build beweist noch keinen vollständigen Netzkino-Live-Abgleich.
TEXT
echo
printf '%s\n' '============================================'
echo 'MACOS-APP ERSTELLT – 0.5.31.11 + DASHBOARD + EPISODEN-QUEUE + NETZKINO'
echo "APP:      $APP"
echo "APP-ZIP:  $APP.zip"
echo 'TESTS:    Repo + Erweiterungen erfolgreich'
echo "LOG:      $LOG"
printf '%s\n' '============================================'
echo 'Nur lokal integriert: keine GitHub-PRs wurden automatisch gemergt.'
/usr/bin/open -R "$APP" || /usr/bin/open "$WORKDIR" || true
