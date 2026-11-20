"""Seeds the cast photo store for cast_photos.cjs (0.6.55): cached TMDB answers and two local photos, no network.
Usage: python3 tests/browser/seed_0655.py <data folder>"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]

import cast_photos, storage_locations     # noqa: E402

root = storage_locations.data_root(Path(sys.argv[1]))
root.mkdir(parents=True, exist_ok=True)
title_key = 'title:%s:%s:%s' % (cast_photos.fold('Die Verurteilten')[:80], 1994, 'tt0111161')
db = cast_photos._db(root)
now = time.time()
cast_photos._store(db, 'nm0000209', cast_photos.IMAGE + '/robbins.png', '', now)
cast_photos._store(db, title_key + ':' + cast_photos.fold('Frank Darabont'), cast_photos.IMAGE + '/darabont.png', '', now)
cast_photos._store(db, title_key + ':' + cast_photos.fold('Bob Gunton'), '', '', now)       # known: no photo
db.commit(); db.close()


def png(rgb, size=16):
    import struct, zlib
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''.join(b'\x00' + bytes(rgb) * size for _ in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


folder = root / cast_photos.PHOTO_DIR
folder.mkdir(exist_ok=True)
(folder / 'robbins.png').write_bytes(png((200, 120, 60)))
(folder / 'darabont.png').write_bytes(png((60, 120, 200)))
print(root)
