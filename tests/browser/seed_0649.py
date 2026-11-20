"""Seeds a data folder with works of unknown kind and runs the 0.6.49 sweep (browser test unknown_reasons.cjs).
Usage: python3 tests/browser/seed_0649.py <data folder>"""
import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import catalog, catalog_service, storage_locations     # noqa: E402

root = storage_locations.data_root(Path(sys.argv[1]))


@contextmanager
def db():
    c = sqlite3.connect(root / 'catalog.db'); c.row_factory = sqlite3.Row
    try:
        with c: yield c
    finally: c.close()


def offer(title, topic, channel, n, duration=1500):
    return {'title': title, 'topic': topic, 'description': '', 'duration': duration, 'channel': channel,
            'url_video': 'https://example.org/%s-%d.mp4' % (channel, n), 'timestamp': 1795100000}


rows = [offer('Auf und davon %d' % n, 'DOK', 'SRF', n) for n in range(6)]
rows += [offer('Heimweh %d' % n, 'SRF bi de Lüt - Heimweh', 'SRF', 10 + n) for n in range(4)]
rows += [offer('La serie %d' % n, 'Serie e fiction - Serie', 'ARTE.IT', 20 + n) for n in range(3)]
rows += [offer('Kurzfilm %d' % n, 'Kurzschluss', 'ARTE.DE', 30 + n, duration=900) for n in range(3)]
rows += [offer('Neu', 'Puls', 'SRF', 40)]
with db() as c:
    catalog.initialize(c)
    catalog.ingest(c, rows)
    for wid, meta in c.execute('SELECT id, meta FROM works').fetchall():
        m = json.loads(meta)
        attempts = 0 if m['title'] == 'Neu' else 2
        if m['title'].startswith('Auf und davon') and m['title'] < 'Auf und davon 3':
            m['suggestions'] = [{'provider': 'IMDb Offline', 'kind': 'series', 'title': 'DOK', 'similarity': 1.0, 'year': 1954}]
        elif m['title'].startswith('Auf und davon'):
            m['suggestions'] = [{'provider': 'IMDb Offline', 'kind': 'movie', 'title': m['title'], 'similarity': 1.0}]
        if m['title'].startswith('Kurzfilm'):
            m['suggestions'] = [{'provider': 'TMDB', 'kind': 'movie', 'title': m['title'], 'similarity': 1.0}]
        if m['title'].startswith('Heimweh 0'):m['metadata_warnings'] = ['TVDB: Zeitüberschreitung']
        c.execute("UPDATE works SET state='review', attempts=?, meta=? WHERE id=?", (attempts, json.dumps(m), wid))
catalog_service.Service(db, lambda: {}, threading.Event(), root).unknown_sweep(force=True)
print(root)
