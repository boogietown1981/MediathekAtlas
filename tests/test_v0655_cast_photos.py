"""0.6.55: Besetzung mit Fotos – Regie in der Reihe, Fotos lokal gespeichert (people-photos/, Größenbudget)."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import cast_photos

ROOT = Path(__file__).resolve().parents[1]
JPEG = b'\xff\xd8\xff\xe0' + b'0' * 2000


class FakeTmdb:
    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, path, params):
        self.calls.append(path)
        if path not in self.data:
            raise OSError('offline')
        return self.data[path]


class Fetch:
    def __init__(self, data=JPEG, fail=False):
        self.data, self.fail, self.urls = data, fail, []

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError('offline')
        return self.data


class CastPhotoStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cast_photos._FAILED.clear()
        tmdb = FakeTmdb({'movie/278/credits': {
            'cast': [{'name': 'Tim Robbins', 'profile_path': '/abc.jpg', 'character': 'Andy'}],
            'crew': [{'name': 'Frank Darabont', 'job': 'Director', 'profile_path': '/fd.jpg'}]}})
        self.out = cast_photos.lookup(self.root, 'k' * 32, [{'name': 'Frank Darabont'}, {'name': 'Tim Robbins'}],
                                      {'kind': 'movie', 'provider': 'TMDB', 'reference_id': '278'}, tmdb)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lookup_names_local_files_for_cast_and_director(self):
        self.assertEqual(self.out['files'], {'Tim Robbins': 'abc.jpg', 'Frank Darabont': 'fd.jpg'})
        self.assertEqual(self.out['photos']['Tim Robbins'], 'https://image.tmdb.org/t/p/w185/abc.jpg')
        # cached second opening also names the files
        again = cast_photos.lookup(self.root, 'k' * 32, ['Tim Robbins'], {'kind': 'movie', 'provider': 'TMDB', 'reference_id': '278'}, FakeTmdb({}))
        self.assertEqual(again['files'], {'Tim Robbins': 'abc.jpg'})

    def test_photo_is_downloaded_once_and_then_read_locally(self):
        fetch = Fetch()
        data, kind = cast_photos.photo(self.root, 'abc.jpg', fetch)
        self.assertEqual((data, kind), (JPEG, 'image/jpeg'))
        self.assertEqual(fetch.urls, ['https://image.tmdb.org/t/p/w185/abc.jpg'])
        self.assertTrue((self.root / 'people-photos' / 'abc.jpg').is_file())
        self.assertEqual(cast_photos.photo(self.root, 'abc.jpg', Fetch(fail=True))[0], JPEG)   # offline: from the store
        self.assertEqual(cast_photos.store_stats(self.root)['files'], 1)

    def test_only_photos_handed_out_by_a_lookup_and_safe_names(self):
        fetch = Fetch()
        for name in ('other.jpg', '../abc.jpg', 'abc.jpg/../x', '', 'a b.jpg', 'x.svg'):
            self.assertIsNone(cast_photos.photo(self.root, name, fetch), name)
        self.assertEqual(fetch.urls, [])
        self.assertEqual(cast_photos.file_name('https://evil.example/t/p/w185/abc.jpg'), '')

    def test_failed_or_non_image_download_is_not_stored_and_not_retried_at_once(self):
        fail = Fetch(fail=True)
        self.assertIsNone(cast_photos.photo(self.root, 'abc.jpg', fail))
        self.assertIsNone(cast_photos.photo(self.root, 'abc.jpg', fail))
        self.assertEqual(len(fail.urls), 1)
        self.assertIsNone(cast_photos.photo(self.root, 'fd.jpg', Fetch(data=b'<html>blocked</html>')))
        self.assertFalse((self.root / 'people-photos' / 'fd.jpg').exists())

    def test_budget_removes_the_least_recently_shown_photos(self):
        folder = self.root / 'people-photos'
        folder.mkdir()
        old = time.time() - 1000
        for i in range(10):
            f = folder / ('p%d.jpg' % i)
            f.write_bytes(b'x' * 1000)
            os.utime(f, (old + i, old + i))
        removed = cast_photos.prune(folder, budget=5000)
        left = sorted(f.name for f in folder.iterdir())
        self.assertEqual(removed, 6)
        self.assertEqual(left, ['p6.jpg', 'p7.jpg', 'p8.jpg', 'p9.jpg'])
        self.assertEqual(cast_photos.prune(folder, budget=5000), 0)


class CastPhotoWiringTests(unittest.TestCase):
    def test_server_route_is_signed_and_checks_the_page_token(self):
        s = (ROOT / 'server.py').read_text(encoding='utf-8')
        i = s.index("@ROUTES.get('/api/cast-photo',stage='signed')")
        body = s[i:i + 700]
        self.assertIn('compare_digest', body)
        self.assertIn('cast_photos.photo(ROOT', body)
        self.assertIn("'cast_photos':lambda:__import__('cast_photos').store_stats(ROOT)", s)

    def test_title_pages_show_regie_and_load_local_photos(self):
        js = (ROOT / 'web' / 'titleview.js').read_text(encoding='utf-8')
        self.assertIn("'/api/cast-photo?'", js)
        self.assertIn("crew:credits.directors", js)
        self.assertIn("crew:m.directors", js)
        self.assertIn('Besetzung & Regie', js)
        self.assertIn('Einstellungen öffnen', js)
        self.assertIn("crew: m.directors || []", (ROOT / 'web' / 'portal_title.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
