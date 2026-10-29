#!/bin/sh
# MediathekAtlas NAS service control, shared by the Synology and QNAP packages.
# Usage: mediathekatlas-service.sh start|stop|status|restart
# Environment from the platform wrapper:
#   ATLAS_APP        directory with server.py (read-only package files)
#   ATLAS_HOME       persistent state: SQLite catalogue, settings, logs (local disk)
#   ATLAS_DOWNLOADS  default download folder on a NAS share
#   ATLAS_PORT       fixed web port (LAN, login required)
#   ATLAS_MANAGED    synology|qnap (service is stopped via the NAS, not the web UI)
#   ATLAS_RUN_AS     optional: unprivileged user when started as root (QNAP)
# Optional overrides in $ATLAS_HOME/mediathekatlas.conf (KEY=VALUE, no shell code):
#   PORT, DOWNLOADS, PYTHON, FFMPEG, FFPROBE, RUN_AS, LISTEN
umask 002
PIDFILE="$ATLAS_HOME/mediathekatlas.pid"
LOG="$ATLAS_HOME/service.log"
CONF="$ATLAS_HOME/mediathekatlas.conf"

log(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; echo "$*"; }

# Parse KEY=VALUE without executing the file.
load_conf(){
  [ -f "$CONF" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue;; esac
    key=${line%%=*}; value=${line#*=}
    value=$(printf '%s' "$value" | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")
    case "$key" in
      PORT) ATLAS_PORT=$value;; DOWNLOADS) ATLAS_DOWNLOADS=$value;; PYTHON) ATLAS_PYTHON=$value;;
      FFMPEG) ATLAS_FFMPEG=$value;; FFPROBE) ATLAS_FFPROBE=$value;; RUN_AS) ATLAS_RUN_AS=$value;; LISTEN) ATLAS_LISTEN=$value;;
    esac
  done < "$CONF"
}

python_ok(){
  [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import sys,sqlite3,ssl,json;sys.exit(0 if sys.version_info>=(3,9) else 1)' >/dev/null 2>&1
}

find_python(){
  qnap_python=""
  if [ -x /sbin/getcfg ]; then
    qnap_root=$(/sbin/getcfg Python3 Install_Path -d "" -f /etc/config/qpkg.conf 2>/dev/null)
    [ -n "$qnap_root" ] && qnap_python="$qnap_root/python3/bin/python3"
  fi
  # Newest first; system Python on DSM 7 (3.8) and old QTS builds fail the version check.
  for candidate in "$ATLAS_PYTHON" \
    /var/packages/python313/target/bin/python3 /var/packages/python312/target/bin/python3 \
    /var/packages/python311/target/bin/python3 /var/packages/python310/target/bin/python3 \
    /var/packages/Python3.9/target/usr/bin/python3.9 /var/packages/Python3.9/target/usr/bin/python3 \
    "$qnap_python" /opt/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3 2>/dev/null)"; do
    if python_ok "$candidate"; then echo "$candidate"; return 0; fi
  done
  # Any other Python package (official Synology, SynoCommunity, QNAP), whatever its name.
  for candidate in /var/packages/*/target/bin/python3* /var/packages/*/target/usr/bin/python3* \
    /var/packages/*/target/usr/local/bin/python3*; do
    case "$candidate" in *-config) continue;; esac
    if python_ok "$candidate"; then echo "$candidate"; return 0; fi
  done
  return 1
}

running_pid(){
  [ -f "$PIDFILE" ] || return 1
  pid=$(cat "$PIDFILE" 2>/dev/null)
  case "$pid" in ''|*[!0-9]*) return 1;; esac
  kill -0 "$pid" 2>/dev/null || [ -d "/proc/$pid" ] || return 1
  # Guard against a reused PID after a reboot.
  if [ -r "/proc/$pid/cmdline" ] && ! tr '\0' ' ' < "/proc/$pid/cmdline" | grep -q 'server.py'; then return 1; fi
  echo "$pid"
}

rotate_log(){
  [ -f "$LOG" ] || return 0
  size=$(wc -c < "$LOG")
  [ "${size:-0}" -gt 5242880 ] && mv -f "$LOG" "$LOG.1"
  return 0
}

start(){
  if running_pid >/dev/null; then echo "MediathekAtlas läuft bereits."; return 0; fi
  mkdir -p "$ATLAS_HOME" && chmod 700 "$ATLAS_HOME" || { echo "Datenordner $ATLAS_HOME nicht beschreibbar"; return 1; }
  rotate_log
  PYTHON=$(find_python) || { log "Kein Python ab 3.9 gefunden. Synology: ein Python-Paket ab 3.9 installieren (z. B. „Python 3.9“ oder SynoCommunity „Python 3.11“). QNAP: „Python3“ aus dem App Center oder Entware. Pfad optional als PYTHON=… in $CONF"; return 1; }
  if ! mkdir -p "$ATLAS_DOWNLOADS" 2>/dev/null || [ ! -w "$ATLAS_DOWNLOADS" ]; then
    log "Download-Ordner $ATLAS_DOWNLOADS ist nicht beschreibbar. Ersatz: $ATLAS_HOME/downloads"
    ATLAS_DOWNLOADS="$ATLAS_HOME/downloads"; mkdir -p "$ATLAS_DOWNLOADS"
  fi
  export MEDIATHEKATLAS_HOME="$ATLAS_HOME" MEDIATHEKATLAS_LISTEN="${ATLAS_LISTEN:-0.0.0.0}" MEDIATHEKATLAS_PORT="$ATLAS_PORT" \
    MEDIATHEKATLAS_DOWNLOAD_DIR="$ATLAS_DOWNLOADS" MEDIATHEKATLAS_MANAGED="$ATLAS_MANAGED" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
  [ -n "$ATLAS_FFMPEG" ] && export MEDIATHEKATLAS_FFMPEG="$ATLAS_FFMPEG"
  [ -n "$ATLAS_FFPROBE" ] && export MEDIATHEKATLAS_FFPROBE="$ATLAS_FFPROBE"
  log "Start $("$PYTHON" -c 'import sys;print(sys.version.split()[0])') ($PYTHON), Port $ATLAS_PORT, Downloads $ATLAS_DOWNLOADS"
  cd "$ATLAS_APP" || return 1
  if [ "$(id -u)" = 0 ] && [ -n "$ATLAS_RUN_AS" ] && [ "$ATLAS_RUN_AS" != root ]; then
    # Drop root before any application code runs (initgroups keeps share groups).
    nohup "$PYTHON" -c 'import os,pwd,sys
u=pwd.getpwnam(sys.argv[1]);os.initgroups(u.pw_name,u.pw_gid);os.setgid(u.pw_gid);os.setuid(u.pw_uid)
os.environ["HOME"]=os.environ["MEDIATHEKATLAS_HOME"];os.execv(sys.executable,[sys.executable,"server.py","--no-browser"])' "$ATLAS_RUN_AS" >> "$LOG" 2>&1 &
  else
    HOME="$ATLAS_HOME" nohup "$PYTHON" server.py --no-browser >> "$LOG" 2>&1 &
  fi
  echo $! > "$PIDFILE"
  # Python itself is checked above; report early crashes (port in use, permissions).
  i=0
  while [ $i -lt 3 ]; do
    sleep 1; i=$((i+1))
    running_pid >/dev/null || { log "MediathekAtlas wurde direkt nach dem Start beendet. Details: $LOG"; rm -f "$PIDFILE"; return 1; }
  done
  log "MediathekAtlas läuft (PID $(cat "$PIDFILE")), Weboberfläche: http://<NAS>:$ATLAS_PORT/"
}

stop(){
  pid=$(running_pid) || { rm -f "$PIDFILE"; echo "MediathekAtlas ist nicht gestartet."; return 0; }
  kill -TERM "$pid" 2>/dev/null
  i=0
  while [ $i -lt 30 ] && kill -0 "$pid" 2>/dev/null; do sleep 1; i=$((i+1)); done
  if kill -0 "$pid" 2>/dev/null; then log "Beenden dauert zu lange, Prozess $pid wird hart beendet"; kill -KILL "$pid" 2>/dev/null; fi
  rm -f "$PIDFILE"; log "MediathekAtlas gestoppt"
}

: "${ATLAS_APP:?ATLAS_APP fehlt}" "${ATLAS_HOME:?ATLAS_HOME fehlt}"
mkdir -p "$ATLAS_HOME" 2>/dev/null
load_conf
ATLAS_PORT=${ATLAS_PORT:-8730}
ATLAS_DOWNLOADS=${ATLAS_DOWNLOADS:-$ATLAS_HOME/downloads}
case "$1" in
  start) start;;
  stop) stop;;
  restart) stop; start;;
  status) if running_pid >/dev/null; then echo "MediathekAtlas läuft."; exit 0; else echo "MediathekAtlas ist gestoppt."; exit 3; fi;;
  log) echo "$LOG";;
  *) echo "Verwendung: $0 {start|stop|restart|status|log}"; exit 1;;
esac
