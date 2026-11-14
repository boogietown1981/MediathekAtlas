#!/bin/sh
# MediathekAtlas @VERSION@ – installation for the current user, no root rights needed.
# Program: ~/.local/share/mediathekatlas/app · Start: ~/.local/bin/mediathekatlas and the app menu.
# Data (catalogue, settings) stays in ~/.mediathekatlas and survives updates and removal.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/mediathekatlas/app"
BIN="$HOME/.local/bin"
command -v python3 >/dev/null 2>&1 || { echo "Python 3.9+ fehlt (z. B. sudo apt install python3 / sudo dnf install python3)."; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' || { echo "Python ist älter als 3.9."; exit 1; }
mkdir -p "$DATA/mediathekatlas" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/256x256/apps" "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
rm -rf "$APP.new" && cp -R "$SRC/app" "$APP.new"
[ -d "$APP" ] && rm -rf "$APP.old" && mv "$APP" "$APP.old"
mv "$APP.new" "$APP" && rm -rf "$APP.old"
sed "s#@APP_DIR@#$APP#" "$SRC/mediathekatlas.sh" > "$BIN/mediathekatlas" && chmod 755 "$BIN/mediathekatlas"
sed "s#@EXEC@#$BIN/mediathekatlas#" "$SRC/mediathekatlas.desktop" > "$DATA/applications/mediathekatlas.desktop"
sed "s#@EXEC@#$BIN/mediathekatlas#" "$SRC/mediathekatlas.service" > "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/mediathekatlas.service"
cp "$SRC/mediathekatlas.png" "$DATA/icons/hicolor/256x256/apps/mediathekatlas.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
echo "MediathekAtlas @VERSION@ installiert. Start über das Anwendungsmenü oder: $BIN/mediathekatlas"
command -v ffmpeg >/dev/null 2>&1 || echo "Hinweis: ffmpeg fehlt (für Downloads/Wiedergabe-Umwandlung empfohlen)."
