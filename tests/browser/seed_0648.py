"""Seeds a data folder with a DMAX/TLC catalogue and a Joyn series with episodes (0.6.48 browser test).
Usage: python3 tests/browser/seed_0648.py <data folder>"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import dailyme, dmax, filmfriend, joyn, storage_locations   # noqa: E402
import test_v0648_dmax as D                              # noqa: E402
import test_v0648_joyn_episodes as J                     # noqa: E402
import test_v0652_filmfriend as F                        # noqa: E402
import test_v0662_dailyme as M                           # noqa: E402

root = storage_locations.data_root(Path(sys.argv[1]))
assert dmax.sync(root, opener=D.FakeDisco(), now=D.NOW)['ok']
assert filmfriend.sync(root, opener=F.FakeFilmfriend(), now=F.NOW)['ok']        # 0.6.52
assert dailyme.sync(root, opener=M.Site(), now=M.NOW)['ok']                     # 0.6.62
db = joyn._connect(root)
with db:
    joyn._store(db, [{'id': 's.a_stromberg', 'kind': 'series', 'title': 'Stromberg', 'path': '/serien/stromberg',
                      'series_id': '', 'season': None, 'episode': None, 'year': None, 'duration': None, 'rating': '',
                      'genre': 'Comedy', 'summary': 'Büro-Comedy.', 'poster': '', 'imdb_id': '', 'imdb_score': None,
                      'imdb_votes': None, 'number': None, 'category': joyn.FREE, 'brand': 'ProSieben', 'offer': 'free',
                      'seasons': 2, 'quality': '', 'playable': 0, 'drm': 1,
                      'web_url': 'https://www.joyn.de/serien/stromberg'}], D.NOW)
    joyn._set(db, 'last_success', D.NOW)
    joyn._set(db, 'last_result', 'complete')
db.close()
# stamped far ahead, so the running server keeps this list and does not try joyn.de (blocked in CI)
joyn.load_episodes(root, {'id': 's.a_stromberg', 'path': '/serien/stromberg'}, fetch=lambda url: J.PAGE, now=4102444800)
print(root)
