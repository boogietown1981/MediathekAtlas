#!/bin/sh
# MediathekAtlas launcher for Linux (.deb and user installation), @VERSION@.
# Finds Python 3.9+, copies the program into a stable runtime folder (updates while the
# app runs stay safe) and starts the local server; the browser opens by itself.
#   mediathekatlas               start (opens the browser)
#   mediathekatlas --no-browser  start without browser (e.g. as systemd user service)
#   mediathekatlas --diagnose    write a diagnosis ZIP to the desktop/home folder
APP_DIR="${MEDIATHEKATLAS_APP:-@APP_DIR@}"
STATE_DIR="${MEDIATHEKATLAS_HOME:-$HOME/.mediathekatlas}"
mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
LOG="$STATE_DIR/startup.log"
: > "$LOG"
printf 'MediathekAtlas @VERSION@ Startprüfung (Linux)\n' >> "$LOG"
fail() {
  printf '%s\n' "$1" >> "$LOG"
  if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then
    if command -v zenity >/dev/null 2>&1; then zenity --error --title="MediathekAtlas" --text="$1\n\nProtokoll: $LOG" 2>/dev/null
    elif command -v kdialog >/dev/null 2>&1; then kdialog --title MediathekAtlas --error "$1\n\nProtokoll: $LOG" 2>/dev/null
    elif command -v notify-send >/dev/null 2>&1; then notify-send "MediathekAtlas" "$1"
    fi
  fi
  printf '%s\nProtokoll: %s\n' "$1" "$LOG" >&2
  exit 1
}
PY=""
for candidate in "${MEDIATHEKATLAS_PYTHON:-}" "$(command -v python3 2>/dev/null)" /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python3.*; do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  if "$candidate" -c 'import sys, sqlite3, ssl, urllib.request; sys.exit(0 if sys.version_info >= (3,9) else 1)' >> "$LOG" 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || fail "Kein Python ab 3.9 gefunden. Bitte das Paket python3 installieren (z. B. sudo apt install python3)."
printf 'Ausgewähltes Python: %s\n' "$PY" >> "$LOG"
command -v ffmpeg >/dev/null 2>&1 || printf 'Hinweis: ffmpeg fehlt – Downloads und Wiedergabe-Umwandlung brauchen ffmpeg (sudo apt install ffmpeg).\n' >> "$LOG"
RUNTIME="$("$PY" "$APP_DIR/stable_runtime.py" "$APP_DIR" "$STATE_DIR" 2>> "$LOG")" || fail "Programmdateien konnten nicht vorbereitet werden."
cd "$RUNTIME" || fail "Laufzeitordner nicht erreichbar: $RUNTIME"
export MEDIATHEKATLAS_HOME="$STATE_DIR"
if [ "${1:-}" = "--diagnose" ]; then exec "$PY" diagnostics_cli.py; fi
"$PY" server.py "$@" >> "$LOG" 2>&1 || fail "MediathekAtlas wurde mit einem Fehler beendet. Details stehen im Startprotokoll."
