#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/MediathekAtlas.app/Contents/MacOS/MediathekAtlas" ]; then
  exec /bin/bash "$HERE/MediathekAtlas.app/Contents/MacOS/MediathekAtlas" --diagnose
fi
exec /bin/bash "$HERE/launcher.sh" --diagnose
