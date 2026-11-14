#!/bin/sh
# Removes the program of a user installation. Catalogue and settings in ~/.mediathekatlas stay.
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
systemctl --user disable --now mediathekatlas 2>/dev/null || true
rm -rf "$DATA/mediathekatlas" "$HOME/.local/bin/mediathekatlas" "$DATA/applications/mediathekatlas.desktop" \
  "$DATA/icons/hicolor/256x256/apps/mediathekatlas.png" "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/mediathekatlas.service"
echo "MediathekAtlas entfernt. Daten bleiben in ~/.mediathekatlas (bei Bedarf selbst löschen)."
