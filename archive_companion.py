"""Read-only localhost companion for the full ArchiveMedia application.

MediathekAtlas intentionally does not replace ArchiveMedia's mature Clean Scan,
recognized uploader priority, large queues, recovery, anime references,
multi-file validation, export, or audio probe scheduler. Run the original app
alongside MediathekAtlas to preserve all its settings and existing database.

Only the *health* endpoint is queried. No remote hosts, arbitrary URLs, imports,
settings writes, downloads, or scan actions are sent to the companion.
"""
import json
import urllib.error
import urllib.request

HOST="127.0.0.1"
PORT=8789
HEALTH=f"http://{HOST}:{PORT}/api/health"
UI=f"http://{HOST}:{PORT}/"
MAX_BYTES=32768
TIMEOUT=2.5
MIN_SUPPORTED=(0,10,53)


def _version(raw):
    try:
        v=tuple(int(c) for c in str(raw).split("."))
        return v if len(v)==3 else ()
    except (TypeError,ValueError):return ()


def read_status(opener=None):
    """Return truthful availability; never silently launch another process."""
    opener=opener or urllib.request.urlopen
    request=urllib.request.Request(
        HEALTH,headers={"Accept":"application/json","User-Agent":"MediathekAtlas-Local-Companion/1"})
    try:
        with opener(request,timeout=TIMEOUT) as reply:
            # Deny cross-host redirects; localhost is the sole trusted origin.
            if getattr(reply,"url",HEALTH)!=HEALTH:
                raise ValueError("ArchiveMedia hat auf eine andere Adresse weitergeleitet")
            raw=reply.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError("Antwort von ArchiveMedia zu groß")
        data=json.loads(raw)
        if not isinstance(data,dict) or _version(data.get("version"))==():
            raise ValueError("Keine passende ArchiveMedia-API")
        compat=_version(data["version"])>=MIN_SUPPORTED
        return {"connected":True,"ready":bool(data.get("ready")),
                "version":data["version"],"compatible":compat,
                "phase":str(data.get("phase") or "")[:120],
                "ui_url":UI if compat else None,
                "mode":"independent_full_application",
                "write_access":False,
                "features_preserved":"ArchiveMedia continues running unchanged in its own process"}
    except (urllib.error.URLError,TimeoutError,ValueError,UnicodeError,OSError) as e:
        return {"connected":False,"ready":False,"version":None,
                "compatible":False,"phase":type(e).__name__,
                "ui_url":None,"mode":"independent_full_application",
                "write_access":False}
