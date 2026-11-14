"""Systemmonitor (0.5.99): wie es dem Gerät geht, auf dem MediathekAtlas läuft, nach dem Vorbild von HomeTube.

One reading on request: processor load, memory, temperature (where the system offers it), the
drives of the data and the download folder, the size of the databases and what MediathekAtlas is
doing right now. Standard library only and no background thread: old Mac minis, ARM NAS and
routers pay nothing while nobody looks. Every value that the platform does not offer is ``None``
and shown as "unbekannt" - never guessed.

``assess`` turns the reading into plain hints (pure function, tested without a system).
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

STARTED = time.time()
GB = 1024 ** 3


def _meminfo(text):
    """(total, available) in bytes from the text of /proc/meminfo."""
    values = {}
    for line in text.splitlines():
        name, _, rest = line.partition(':')
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name.strip()] = int(parts[0]) * 1024
    total = values.get('MemTotal')
    available = values.get('MemAvailable')
    if available is None and total is not None:      # kernels before 3.14 (old NAS firmware)
        available = values.get('MemFree', 0) + values.get('Buffers', 0) + values.get('Cached', 0)
    return total, available


def _vm_stat(text, total):
    """Available memory on macOS: free, inactive and purgeable pages."""
    size, pages = 4096, {}
    for line in text.splitlines():
        if 'page size of' in line:
            digits = ''.join(ch for ch in line.split('page size of', 1)[1] if ch.isdigit())
            size = int(digits) if digits else size
            continue
        name, _, value = line.partition(':')
        value = value.strip().rstrip('.')
        if value.isdigit():
            pages[name.strip()] = int(value)
    if not pages:
        return None
    available = (pages.get('Pages free', 0) + pages.get('Pages inactive', 0) + pages.get('Pages purgeable', 0)) * size
    return min(available, total) if total else available


def memory():
    """(total, available) bytes of the machine, None where unknown."""
    try:
        if sys.platform.startswith('linux'):
            return _meminfo(Path('/proc/meminfo').read_text())
        if sys.platform == 'darwin':
            total = int(subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=3).stdout.strip())
            text = subprocess.run(['/usr/bin/vm_stat'], capture_output=True, text=True, timeout=3).stdout
            return total, _vm_stat(text, total)
        if os.name == 'nt':
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong),
                            ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong),
                            ('virtual_free', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
            status = Status()
            status.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total), int(status.available)
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        pass
    return None, None


def process_memory():
    """Memory of this MediathekAtlas process in bytes, or None."""
    try:
        if sys.platform.startswith('linux'):
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) * 1024
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == 'darwin' else peak * 1024)     # macOS reports bytes, Linux kilobytes (peak)
    except (OSError, ValueError, ImportError, IndexError):
        return None


def temperature(base='/sys/class/thermal'):
    """Highest temperature the system reports in °C (Linux thermal zones), or None."""
    best = None
    try:
        for zone in sorted(Path(base).glob('thermal_zone*/temp')):
            try:
                value = int(zone.read_text().strip()) / 1000
            except (OSError, ValueError):
                continue
            if 0 < value < 130:
                best = value if best is None else max(best, value)
    except OSError:
        return None
    return round(best, 1) if best is not None else None


def load():
    """(1, 5, 15 minute load averages) or None on systems without them (Windows)."""
    try:
        return tuple(round(v, 2) for v in os.getloadavg())
    except (OSError, AttributeError):
        return None


def drive(path):
    try:
        usage = shutil.disk_usage(path)
        return {'path': str(path), 'total_bytes': usage.total, 'free_bytes': usage.free}
    except OSError:
        return {'path': str(path), 'total_bytes': None, 'free_bytes': None}


def databases(root):
    """Size of the databases in the data folder, largest first."""
    files = []
    try:
        for entry in Path(root).iterdir():
            if entry.is_file() and entry.suffix in ('.db', '.sqlite3', '.sqlite'):
                files.append({'name': entry.name, 'bytes': entry.stat().st_size})
    except OSError:
        pass
    files.sort(key=lambda f: -f['bytes'])
    return {'total_bytes': sum(f['bytes'] for f in files), 'files': files[:8], 'count': len(files)}


def assess(reading):
    """Plain hints for one reading; an empty list means nothing stands out."""
    hints = []
    cores, averages = reading.get('cores') or 1, reading.get('load')
    if averages and averages[1] / cores >= 1.5:
        hints.append({'level': 'warn', 'text': 'Der Prozessor ist seit Minuten voll ausgelastet (Last %.1f bei %d Kernen). Umwandlungen und Erkennung laufen dann langsamer.' % (averages[1], cores)})
    total, available = reading.get('memory_total'), reading.get('memory_available')
    if total and available is not None and available / total < 0.08:
        hints.append({'level': 'warn', 'text': 'Kaum freier Arbeitsspeicher (%.0f %% frei). Auf einem NAS hilft es, andere Pakete zu beenden.' % (available / total * 100)})
    heat = reading.get('temperature')
    if heat is not None and heat >= 85:
        hints.append({'level': 'warn', 'text': 'Das Gerät ist sehr warm (%.0f °C). Eine laufende Umwandlung lässt sich unter Speicher abbrechen.' % heat})
    seen = set()
    for item in reading.get('drives') or []:
        free, whole = item.get('free_bytes'), item.get('total_bytes')
        if free is None or not whole or (whole, free) in seen:
            continue
        seen.add((whole, free))
        if free < 2 * GB:
            hints.append({'level': 'error', 'text': 'Auf dem Laufwerk von „%s“ sind weniger als 2 GB frei. Downloads und Umwandlungen werden abgelehnt.' % item['label']})
        elif free < 10 * GB or free / whole < 0.05:
            hints.append({'level': 'warn', 'text': 'Auf dem Laufwerk von „%s“ wird der Platz knapp (%.1f GB frei).' % (item['label'], free / GB)})
    return hints


def snapshot(root, download_dir, activity=None):
    """One reading of the machine and of MediathekAtlas."""
    total, available = memory()
    drives = [dict(drive(root), label='Daten und Datenbanken')]
    if download_dir:
        drives.append(dict(drive(download_dir), label='Downloads'))
    reading = {'time': time.time(), 'system': platform.system() or sys.platform, 'release': platform.release()[:60], 'machine': platform.machine()[:40],
               'python': platform.python_version(), 'cores': os.cpu_count() or 1, 'load': load(), 'memory_total': total, 'memory_available': available,
               'process_memory': process_memory(), 'threads': threading.active_count(), 'temperature': temperature(),
               'uptime_seconds': int(time.time() - STARTED), 'drives': drives, 'databases': databases(root), 'activity': activity or {}}
    reading['hints'] = assess(reading)
    return reading
