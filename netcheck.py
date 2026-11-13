"""Why a catalogue server is unreachable (0.5.46).

Björn (12.11.2026): "die Kataloge synchronisieren nicht mehr" – Netzkino showed only
"Netzkino-Katalogserver nicht erreichbar", although HTTPS to the Mediathek list works on the same Mac.
The generic message hid the cause. ``cause(exc)`` names it (name resolution, certificate, timeout,
refused, proxy …) without URLs or secrets; ``probe()`` checks DNS, TCP and TLS of every catalogue
host for the diagnostics export, in parallel and with short timeouts.
"""
from __future__ import annotations

import socket
import ssl
import threading
import time
import urllib.error

# Fixed catalogue hosts (no user input reaches this list).
CATALOG_HOSTS = ('data.netzkino.de', 'www.netzkino.de', 'boot.pluto.tv', 'service-vod.clusters.pluto.tv',
                 'service-channels.clusters.pluto.tv', 'apis.justwatch.com', 'gizmo.rakuten.tv', 'api.joyn.de', 'production-n.toggo.de', 'www.crunchyroll.com', 'i.mjh.nz', 'jmp2.uk', 'www.googleapis.com', 'liste.mediathekview.de')


def _root(exc):
    seen = set()
    while isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError) and id(exc) not in seen:
        seen.add(id(exc))
        if not isinstance(exc.reason, BaseException):
            break
        exc = exc.reason
    return exc


def cause(exc):
    """Short German cause of a network failure, '' when it is not a network error."""
    exc = _root(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return 'HTTP %d' % exc.code
    if isinstance(exc, ssl.SSLCertVerificationError):
        return 'Zertifikat konnte nicht geprüft werden (Zertifikatsspeicher von Python oder Proxy/Filter mit eigenem Zertifikat)'
    if isinstance(exc, ssl.SSLError):
        return 'TLS-Verbindung fehlgeschlagen'
    if isinstance(exc, socket.gaierror):
        return 'Name nicht auflösbar (DNS, Werbe-/Inhaltsfilter oder keine Internetverbindung)'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'Zeitüberschreitung (Server antwortet nicht oder Verbindung zu langsam)'
    if isinstance(exc, ConnectionRefusedError):
        return 'Verbindung abgelehnt (Firewall oder Proxy)'
    if isinstance(exc, ConnectionResetError):
        return 'Verbindung vom Gegenüber oder einem Filter abgebrochen'
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason or '')
        if 'proxy' in reason.lower() or 'tunnel' in reason.lower():
            return 'Proxy verweigert die Verbindung'
        return 'Netzwerkfehler'
    if isinstance(exc, OSError):
        return 'Netzwerkfehler (%s)' % (exc.__class__.__name__,)
    return ''


def kind(exc):
    """Stable technical key for diagnostics events."""
    exc = _root(exc)
    for cls, key in ((urllib.error.HTTPError, 'http'), (ssl.SSLCertVerificationError, 'certificate'), (ssl.SSLError, 'tls'),
                     (socket.gaierror, 'dns'), (socket.timeout, 'timeout'), (TimeoutError, 'timeout'),
                     (ConnectionRefusedError, 'refused'), (ConnectionResetError, 'reset'), (urllib.error.URLError, 'url'),
                     (OSError, 'os')):
        if isinstance(exc, cls):
            return key
    return 'other'


def with_cause(message, exc):
    c = cause(exc)
    return message.rstrip('.') + (' – ' + c if c else '') + '.'


def _check(host, timeout, out):
    started = time.monotonic()
    row = {'host': host}
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        row['dns'] = 'ok'
        row['families'] = sorted({'IPv6' if i[0] == socket.AF_INET6 else 'IPv4' for i in infos})
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            row['tcp'] = 'ok'
            with ctx.wrap_socket(raw, server_hostname=host):
                row['tls'] = 'ok'
    except Exception as exc:  # report, never raise
        row['error'] = kind(exc)
        row['cause'] = cause(exc) or exc.__class__.__name__
    row['ms'] = int((time.monotonic() - started) * 1000)
    out.append(row)


def probe(hosts=CATALOG_HOSTS, timeout=5.0):
    out = []
    threads = [threading.Thread(target=_check, args=(h, timeout, out), daemon=True) for h in hosts]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout * 2 + 1)
    order = {h: i for i, h in enumerate(hosts)}
    return sorted(out, key=lambda r: order.get(r['host'], 99))


_TRUST = {'checked': False, 'source': 'system', 'ca_certs': None}
_FALLBACK_BUNDLES = ('/etc/ssl/cert.pem', '/usr/local/etc/openssl@3/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem',
                     '/etc/ssl/certs/ca-certificates.crt')


def ensure_trust_store():
    """Python from python.org on macOS ships without root certificates until "Install Certificates"
    is run; then every HTTPS catalogue request fails. Verification stays on: when the default
    context knows no CA at all, the macOS system bundle (or certifi) is used as trust store."""
    if _TRUST['checked']:
        return dict(_TRUST)
    _TRUST['checked'] = True
    try:
        count = ssl.create_default_context().cert_store_stats().get('x509_ca', 0)
    except Exception:
        count = 0
    _TRUST['ca_certs'] = count
    import os
    paths = ssl.get_default_verify_paths()
    has_dir = bool(paths.capath and os.path.isdir(paths.capath) and any(n.endswith('.0') for n in os.listdir(paths.capath)))
    if count or paths.cafile or has_dir:
        return dict(_TRUST)
    bundle = ''
    try:
        import certifi  # optional
        bundle = certifi.where()
    except Exception:
        bundle = next((p for p in _FALLBACK_BUNDLES if os.path.isfile(p)), '')
    if bundle:
        def context(*args, **kwargs):
            kwargs.setdefault('cafile', bundle)
            return ssl.create_default_context(**{k: v for k, v in kwargs.items() if k in ('cafile', 'capath', 'cadata', 'purpose')})
        ssl._create_default_https_context = context  # same verification, other trust store
        _TRUST['source'] = bundle
        try:
            _TRUST['ca_certs'] = context().cert_store_stats().get('x509_ca', 0)
        except Exception:
            pass
    else:
        _TRUST['source'] = 'missing'
    return dict(_TRUST)
