#!/bin/sh
# QTS App Center service script (runs as root). The server itself is started
# as the unprivileged user RUN_AS (default httpdusr), see bin/mediathekatlas-service.sh.
CONF=/etc/config/qpkg.conf
QPKG_NAME="MediathekAtlas"
if [ -z "$QPKG_ROOT" ]; then
  QPKG_ROOT=$(/sbin/getcfg $QPKG_NAME Install_Path -f $CONF)
fi
ATLAS_APP="$QPKG_ROOT/mediathekatlas"
ATLAS_HOME="$QPKG_ROOT/data"
ATLAS_MANAGED=qnap
ATLAS_PORT=@PORT@
export ATLAS_APP ATLAS_HOME ATLAS_MANAGED ATLAS_PORT
SERVICE="$QPKG_ROOT/bin/mediathekatlas-service.sh"

conf_value(){ [ -f "$ATLAS_HOME/mediathekatlas.conf" ] && sed -n "s/^$1=//p" "$ATLAS_HOME/mediathekatlas.conf" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/'; }

# Downloads go to a regular share, visible in File Station and via SMB.
default_downloads(){
  for share in Download Multimedia Public; do
    path=$(/sbin/getcfg "$share" path -f /etc/config/smb.conf 2>/dev/null)
    [ -z "$path" ] && [ -d "/share/$share" ] && path="/share/$share"
    if [ -n "$path" ] && [ -d "$path" ]; then echo "$path/MediathekAtlas"; return 0; fi
  done
  echo "$ATLAS_HOME/downloads"
}

prepare(){
  ATLAS_RUN_AS=$(conf_value RUN_AS)
  [ -n "$ATLAS_RUN_AS" ] || ATLAS_RUN_AS=httpdusr
  if [ "$(id -u)" = 0 ] && [ "$ATLAS_RUN_AS" != root ]; then
    id "$ATLAS_RUN_AS" >/dev/null 2>&1 || { echo "Benutzer $ATLAS_RUN_AS fehlt. RUN_AS=… in $ATLAS_HOME/mediathekatlas.conf setzen."; exit 1; }
  fi
  ATLAS_DOWNLOADS=$(conf_value DOWNLOADS)
  [ -n "$ATLAS_DOWNLOADS" ] || ATLAS_DOWNLOADS=$(default_downloads)
  mkdir -p "$ATLAS_HOME" "$ATLAS_DOWNLOADS"
  if [ "$(id -u)" = 0 ] && [ "$ATLAS_RUN_AS" != root ]; then
    chown -R "$ATLAS_RUN_AS" "$ATLAS_HOME"
    # Group "everyone" lets NAS users read and tidy up downloaded files.
    chown "$ATLAS_RUN_AS:everyone" "$ATLAS_DOWNLOADS" 2>/dev/null || chown "$ATLAS_RUN_AS" "$ATLAS_DOWNLOADS"
    chmod 2775 "$ATLAS_DOWNLOADS"
  fi
  export ATLAS_RUN_AS ATLAS_DOWNLOADS
}

case "$1" in
  start)
    if [ -x /sbin/getcfg ]; then
      ENABLED=$(/sbin/getcfg $QPKG_NAME Enable -u -d FALSE -f $CONF)
      if [ "$ENABLED" != "TRUE" ]; then echo "$QPKG_NAME is disabled."; exit 1; fi
    fi
    prepare; /bin/sh "$SERVICE" start;;
  stop) /bin/sh "$SERVICE" stop;;
  restart) prepare; /bin/sh "$SERVICE" restart;;
  status) /bin/sh "$SERVICE" status;;
  remove) ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 1;;
esac
