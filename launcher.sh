#!/bin/bash
# Shared Finder/Terminal launcher. Never relies on a login shell or alters installs.
export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
LAUNCH_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$LAUNCH_DIR/../Resources/app/server.py" ]; then
  APP_DIR="$(cd "$LAUNCH_DIR/../Resources/app" && pwd)"
else
  APP_DIR="$LAUNCH_DIR"
fi
STATE_DIR="${MEDIATHEKATLAS_HOME:-$HOME/Library/Application Support/MediathekAtlas}"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
LOG="$STATE_DIR/startup.log"
# 0.6.47: the detached supervisor (see below) keeps the log of the start that launched it.
if [ -z "${MEDIATHEKATLAS_SUPERVISED:-}" ]; then
  : > "$LOG"
fi
# 0.6.72: the version comes from version.py (it said 0.6.62 for every later version).
APP_VERSION="$(sed -n "s/^VERSION='\(.*\)'.*/\1/p" "$APP_DIR/version.py" 2>/dev/null | head -n 1)"
printf 'MediathekAtlas %s Startprüfung\n' "${APP_VERSION:-?}" >> "$LOG"
# 0.6.48: dialogs only where someone can answer them (MEDIATHEKATLAS_NO_DIALOG=1 for tests and headless starts;
# a dialog without a screen kept the script waiting for ever).
OSASCRIPT=/usr/bin/osascript
if [ "${MEDIATHEKATLAS_NO_DIALOG:-}" = "1" ]; then OSASCRIPT=/nonexistent/osascript; fi
FOUND_PYTHON=""
# 0.6.143 (M1-Air-Diagnose 26.11.2026: machine x86_64, Python aus /usr/local): auf Apple Silicon zuerst ein Python
# suchen, das nativ als arm64 läuft, und es mit „arch -arm64“ starten (wirkt auch, wenn die App mit „Mit Rosetta
# öffnen“ gestartet wurde). Nur wenn keines da ist, läuft ein Intel-Python unter Rosetta 2 weiter (mit Hinweis).
PYCMD=()
ARM_PREFIX=()
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ] && [ -x /usr/bin/arch ]; then
  ARM_PREFIX=(/usr/bin/arch -arm64)
fi
PY_CHECK='import sys, platform, sqlite3, ssl, pathlib, urllib.request; print(sys.version, platform.machine()); sys.exit(0 if sys.version_info >= (3,9) else 1)'
try_python() {
  local candidate="$1"
  [ -n "$candidate" ] && [ -x "$candidate" ] || return 1
  printf 'Python prüfen: %s\n' "$candidate" >> "$LOG"
  if [ "${#ARM_PREFIX[@]}" -gt 0 ] && [ "${2:-}" = "arm64" ]; then
    if "${ARM_PREFIX[@]}" "$candidate" -c "$PY_CHECK" >> "$LOG" 2>&1; then
      FOUND_PYTHON="$candidate";PYCMD=("${ARM_PREFIX[@]}" "$candidate")
      return 0
    fi
    return 1
  fi
  if "$candidate" -c "$PY_CHECK" >> "$LOG" 2>&1; then
    FOUND_PYTHON="$candidate";PYCMD=("$candidate")
    return 0
  fi
  return 1
}
shopt -s nullglob
CANDIDATES=("${MEDIATHEKATLAS_PYTHON:-}" \
  /opt/homebrew/bin/python3 /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 \
  /opt/homebrew/opt/python@3.*/libexec/bin/python3 \
  /usr/local/opt/python@3.*/libexec/bin/python3 \
  /opt/homebrew/opt/python@3.*/bin/python3.* \
  /usr/local/opt/python@3.*/bin/python3.* \
  /opt/local/bin/python3 /opt/local/bin/python3.* \
  "$(command -v python3 || true)" /usr/bin/python3)
if [ "${#ARM_PREFIX[@]}" -gt 0 ]; then
  printf 'Apple Silicon: suche zuerst ein natives arm64-Python.\n' >> "$LOG"
  for candidate in "${CANDIDATES[@]}"; do
    if try_python "$candidate" arm64; then break; fi
  done
fi
if [ -z "$FOUND_PYTHON" ]; then
  for candidate in "${CANDIDATES[@]}"; do
    if try_python "$candidate"; then break; fi
  done
  if [ -n "$FOUND_PYTHON" ] && [ "${#ARM_PREFIX[@]}" -gt 0 ]; then
    printf 'Hinweis: kein arm64-Python gefunden, %s läuft unter Rosetta 2 (langsamer, mehr Arbeitsspeicher). Abhilfe: Python von python.org (Universal) oder Homebrew unter /opt/homebrew installieren.\n' "$FOUND_PYTHON" >> "$LOG"
  fi
fi
if [ -z "$FOUND_PYTHON" ]; then
  MESSAGE="MediathekAtlas konnte kein startbares Python ab 3.9 finden. Eine vorhandene Installation wurde möglicherweise nicht erkannt. Details stehen im Startprotokoll. FFmpeg wurde noch nicht geprüft."
  printf '%s\n' "$MESSAGE" >> "$LOG"
  if [ -x "$OSASCRIPT" ]; then
    "$OSASCRIPT" - "$LOG" <<'APPLESCRIPT'
on run argv
 set answer to display dialog "Python konnte nicht gestartet werden. Details stehen im Startprotokoll. FFmpeg wurde noch nicht geprüft." buttons {"Schließen", "Protokoll öffnen"} default button "Protokoll öffnen" with title "MediathekAtlas – Startprüfung"
 if button returned of answer is "Protokoll öffnen" then
  do shell script "/usr/bin/open -a TextEdit " & quoted form of (item 1 of argv)
 end if
end run
APPLESCRIPT
  else
    printf '%s\nProtokoll: %s\n' "$MESSAGE" "$LOG"
  fi
  exit 1
fi
printf 'Ausgewähltes Python: %s\n' "${PYCMD[*]}" >> "$LOG"
RUNTIME_DIR="$("${PYCMD[@]}" "$APP_DIR/stable_runtime.py" "$APP_DIR" "$STATE_DIR" 2>> "$LOG")" || exit 1
cd "$RUNTIME_DIR" || exit 1
if [ "${1:-}" = "--diagnose" ]; then
  exec "${PYCMD[@]}" diagnostics_cli.py
fi
# 0.6.47 (found on Björn's MacBook Pro M4, 20.11.2026): this script is the executable of the macOS app. While it
# waited here for a hanging Python process, macOS still counted the app as running and a double click did nothing
# at all ("already running"), so the start check of 0.6.46 (open a healthy instance, replace a hanging one) never
# ran. Inside the .app the script therefore hands the server loop to a detached copy of itself in a new session
# and ends at once; every double click then reaches server.py and its start check. Paths do not matter: the
# runtime is copied by content hash (stable_runtime.py) and the instance lock lives in the data folder, so App
# Translocation (a random path for every start from a quarantined download) changes nothing.
# Start from Terminal (Start.command, launcher.sh) keeps running in the foreground as before.
if [ "$APP_DIR" != "$LAUNCH_DIR" ] && [ -z "${MEDIATHEKATLAS_SUPERVISED:-}" ] && [ "${MEDIATHEKATLAS_FOREGROUND:-}" != "1" ]; then
  printf 'Startskript übergibt an einen eigenständigen Prozess (App gilt danach nicht mehr als „läuft noch“).\n' >> "$LOG"
  if MEDIATHEKATLAS_SUPERVISED=1 MEDIATHEKATLAS_PYTHON="$FOUND_PYTHON" "${PYCMD[@]}" -c '
import subprocess, sys
log = open(sys.argv[1], "ab")
subprocess.Popen(sys.argv[2:], start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
' "$LOG" /bin/bash "$0" "$@" >> "$LOG" 2>&1; then
    exit 0
  fi
  printf 'Übergabe fehlgeschlagen, Start im Vordergrund.\n' >> "$LOG"
fi
while :; do
  "${PYCMD[@]}" server.py >> "$LOG" 2>&1
  STATUS=$?
  # 0.6.20: Speicherort für System und Datenbank nicht erreichbar (z. B. externes Laufwerk abgezogen).
  if [ "$STATUS" -eq 3 ] && [ -x "$OSASCRIPT" ] && [ -f "$STATE_DIR/storage-problem.txt" ]; then
    # 0.6.25: dritter Knopf „Bisherigen Ort verwenden“ stellt nur den Zeiger zurück (nichts wird kopiert oder gelöscht).
    REVERT="no"
    # 0.6.86: Status 4 = der bisherige Datenstand liegt im Standardordner; der Knopf heißt dann so.
    "${PYCMD[@]}" storage_locations.py --home "$STATE_DIR" --revert-info >> "$LOG" 2>&1
    case $? in 0) REVERT="Bisherigen Ort verwenden";; 4) REVERT="Standardordner verwenden";; esac
    ANSWER="$("$OSASCRIPT" - "$STATE_DIR/storage-problem.txt" "$REVERT" <<'APPLESCRIPT'
on run argv
 set message to read POSIX file (item 1 of argv) as «class utf8»
 if item 2 of argv is not "no" then
  set answer to display dialog message buttons {"Beenden", (item 2 of argv), "Erneut versuchen"} default button "Erneut versuchen" with title "MediathekAtlas – Speicherort fehlt" with icon caution
 else
  set answer to display dialog message buttons {"Beenden", "Erneut versuchen"} default button "Erneut versuchen" with title "MediathekAtlas – Speicherort fehlt" with icon caution
 end if
 return button returned of answer
end run
APPLESCRIPT
)"
    if [ "$ANSWER" = "Erneut versuchen" ]; then continue; fi
    if [ "$ANSWER" = "Bisherigen Ort verwenden" ] || [ "$ANSWER" = "Standardordner verwenden" ]; then
      if "${PYCMD[@]}" storage_locations.py --home "$STATE_DIR" --revert >> "$LOG" 2>&1; then continue; fi
    fi
    exit 3
  fi
  break
done
# 0.6.48 (Björns Mac, 20.11.2026): Ein neuer Start ersetzt eine hängende Instanz und beendet sie (SIGTERM, nach
# Frist SIGKILL). Der Python-Prozess endet dann mit 143 bzw. 137 (128 + Signal); das ist kein Startfehler und
# bekommt keinen Fehlerdialog, nur einen Eintrag im Startprotokoll.
if [ "$STATUS" -eq 137 ] || [ "$STATUS" -eq 143 ]; then
  printf 'MediathekAtlas wurde von außen beendet (Status %s, z. B. durch einen neuen Start); kein Startfehler.\n' "$STATUS" >> "$LOG"
  exit 0
fi
if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 3 ] && [ -x "$OSASCRIPT" ]; then
  "$OSASCRIPT" - "$LOG" <<'APPLESCRIPT'
on run argv
 display dialog "Python wurde gefunden, aber die Anwendung konnte nicht gestartet werden. Das Startprotokoll enthält die genaue Fehlermeldung." buttons {"OK"} default button "OK" with title "MediathekAtlas"
 do shell script "/usr/bin/open -a TextEdit " & quoted form of (item 1 of argv)
end run
APPLESCRIPT
fi
exit "$STATUS"
