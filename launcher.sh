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
: > "$LOG"
printf 'MediathekAtlas 0.5.0 Startprüfung\n' >> "$LOG"
FOUND_PYTHON=""
try_python() {
  local candidate="$1"
  [ -n "$candidate" ] && [ -x "$candidate" ] || return 1
  printf 'Python prüfen: %s\n' "$candidate" >> "$LOG"
  if "$candidate" -c 'import sys, sqlite3, ssl, pathlib, urllib.request; print(sys.version); sys.exit(0 if sys.version_info >= (3,9) else 1)' >> "$LOG" 2>&1; then
    FOUND_PYTHON="$candidate"
    return 0
  fi
  return 1
}
shopt -s nullglob
for candidate in "${MEDIATHEKATLAS_PYTHON:-}" \
  /opt/homebrew/bin/python3 /usr/local/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 \
  /opt/homebrew/opt/python@3.*/libexec/bin/python3 \
  /usr/local/opt/python@3.*/libexec/bin/python3 \
  /opt/homebrew/opt/python@3.*/bin/python3.* \
  /usr/local/opt/python@3.*/bin/python3.* \
  /opt/local/bin/python3 /opt/local/bin/python3.* \
  "$(command -v python3 || true)" /usr/bin/python3; do
  if try_python "$candidate"; then break; fi
done
if [ -z "$FOUND_PYTHON" ]; then
  MESSAGE="MediathekAtlas konnte kein startbares Python ab 3.9 finden. Eine vorhandene Installation wurde möglicherweise nicht erkannt. Details stehen im Startprotokoll. FFmpeg wurde noch nicht geprüft."
  printf '%s\n' "$MESSAGE" >> "$LOG"
  if [ -x /usr/bin/osascript ]; then
    /usr/bin/osascript - "$LOG" <<'APPLESCRIPT'
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
printf 'Ausgewähltes Python: %s\n' "$FOUND_PYTHON" >> "$LOG"
RUNTIME_DIR="$("$FOUND_PYTHON" "$APP_DIR/stable_runtime.py" "$APP_DIR" "$STATE_DIR" 2>> "$LOG")" || exit 1
cd "$RUNTIME_DIR" || exit 1
if [ "${1:-}" = "--diagnose" ]; then
  exec "$FOUND_PYTHON" diagnostics_cli.py
fi
"$FOUND_PYTHON" server.py >> "$LOG" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ] && [ -x /usr/bin/osascript ]; then
  /usr/bin/osascript - "$LOG" <<'APPLESCRIPT'
on run argv
 display dialog "Python wurde gefunden, aber die Anwendung konnte nicht gestartet werden. Das Startprotokoll enthält die genaue Fehlermeldung." buttons {"OK"} default button "OK" with title "MediathekAtlas"
 do shell script "/usr/bin/open -a TextEdit " & quoted form of (item 1 of argv)
end run
APPLESCRIPT
fi
exit "$STATUS"
