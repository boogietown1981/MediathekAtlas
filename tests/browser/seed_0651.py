"""Seeds one data folder for the two-instance Verbund test (mesh_two_nodes.cjs).
Usage: python3 tests/browser/seed_0651.py <data folder> a|b
Both systems get the same 40 offers. A has recognised 30 films itself (before the Verbund);
both assign the same film manually but differently (conflict)."""
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import catalog, storage_locations     # noqa: E402

root = storage_locations.data_root(Path(sys.argv[1])); side = sys.argv[2]


@contextmanager
def db():
    c = sqlite3.connect(root / 'catalog.db'); c.row_factory = sqlite3.Row
    try:
        with c: yield c
    finally: c.close()


rows = [{'title': 'Spielfilm Nummer %d' % i, 'channel': 'ARD', 'topic': 'Spielfilm', 'duration': 5400,
         'description': 'Spielfilm Deutschland, eine lange Beschreibung für Werk %d mit genug Text' % i,
         'url_video': 'https://example.org/%d.mp4' % i, 'timestamp': 1795100000} for i in range(40)]
with db() as c:
    catalog.initialize(c)
    catalog.ingest(c, rows)
    # Offline test: no catalogue download, no provider keys.
    c.execute('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,payload TEXT)')
    c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)', (json.dumps({'auto_catalog': False, 'mesh_name': 'Mac ' + side.upper()}),))
    works = c.execute('SELECT id, meta FROM works ORDER BY id').fetchall()
    for n, (wid, meta) in enumerate(works):
        m = json.loads(meta)
        if n == 0:
            m.update(title='Eigener Titel ' + side.upper(), kind='movie', year=2000 if side == 'a' else 1999, state='user_confirmed')
            catalog.save_metadata(c, wid, m)
        elif side == 'a' and n <= 30:
            m.update(kind='movie', year=2001, provider='TMDB', reference_id='ref-%d' % n, state='auto_matched')
            catalog.save_metadata(c, wid, m, 'matched')
        else:
            # Not yet recognised: pause the local retry so only the Verbund can recognise it in this test.
            c.execute('UPDATE works SET next_try=? WHERE id=?', (4102444800, wid))
print(root)
