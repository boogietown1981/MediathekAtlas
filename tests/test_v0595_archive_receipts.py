"""0.5.95: Prüfsumme und signierter Archivnachweis für Archive.org-Downloads im Verbund."""
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive_receipts as receipts  # noqa: E402
import ed25519_lite  # noqa: E402
import meshjournal  # noqa: E402
from tests._wiring import wired  # noqa: E402

NODE_A, NODE_B = 'a' * 32, 'b' * 32


def job(folder, name='Film.mkv', content=b'stored-bytes', identifier='upload_1', file='film.mp4', source=b'source-bytes', matched='md5', job_id='j1'):
    path = Path(folder) / name
    path.write_bytes(content)
    out = {'id': job_id, 'origin': 'internet_archive', 'archive_identifier': identifier, 'archive_file': file, 'path': str(path),
           'metadata': {'title': 'Ein Film', 'year': 1950}}
    if source is not None:
        out['source_check'] = {'sha256': hashlib.sha256(source).hexdigest(), 'size': len(source), 'matched': matched}
    return out


class SignatureTests(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for secret, public, message, signature in (
                ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a', '',
                 'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
                ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb', '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c', '72',
                 '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')):
            seed, text = bytes.fromhex(secret), bytes.fromhex(message)
            self.assertEqual(ed25519_lite.public_key(seed).hex(), public)
            self.assertEqual(ed25519_lite.sign(seed, text).hex(), signature)
            self.assertTrue(ed25519_lite.verify(bytes.fromhex(public), text, bytes.fromhex(signature)))
            self.assertFalse(ed25519_lite.verify(bytes.fromhex(public), text + b'x', bytes.fromhex(signature)))

    def test_bad_input_is_refused_not_raised(self):
        seed = bytes(32)
        public, signature = ed25519_lite.public_key(seed), ed25519_lite.sign(seed, b'm')
        for pub, sig in ((public[:31], signature), (public, signature[:63]), (b'\xff' * 32, signature), (public, signature[:32] + b'\xff' * 32), ('x', signature)):
            self.assertFalse(ed25519_lite.verify(pub, b'm', sig))
        other = ed25519_lite.public_key(b'\x01' * 32)
        self.assertFalse(ed25519_lite.verify(other, b'm', signature))


class ChecksumTests(unittest.TestCase):
    def digests(self, data):
        out = receipts.hashers()
        for h in out.values():
            h.update(data)
        return out

    def test_published_checksums(self):
        self.assertEqual(receipts.expectation({'md5': 'A' * 32, 'sha1': 'b' * 40}), {'md5': 'a' * 32, 'sha1': 'b' * 40})
        self.assertEqual(receipts.expectation({'md5': 'zz', 'sha1': 'b' * 39}), {})
        self.assertEqual(receipts.expectation(None), {})

    def test_match_mismatch_and_unknown(self):
        data = b'video'
        good = {'md5': hashlib.md5(data).hexdigest(), 'sha1': hashlib.sha1(data).hexdigest()}
        self.assertEqual(receipts.source_check(good, self.digests(data), 5), {'sha256': hashlib.sha256(data).hexdigest(), 'size': 5, 'matched': 'sha1'})
        self.assertEqual(receipts.source_check({'md5': good['md5']}, self.digests(data), 5)['matched'], 'md5')
        self.assertEqual(receipts.source_check({}, self.digests(data), 5)['matched'], '')
        with self.assertRaisesRegex(ValueError, 'stimmt nicht mit der Prüfsumme von Archive.org'):
            receipts.source_check(good, self.digests(b'broken'), 6)
        with self.assertRaisesRegex(ValueError, 'MD5'):
            receipts.source_check({'md5': good['md5']}, self.digests(b'broken'), 6)

    def test_download_is_compared_while_it_arrives(self):
        import core
        import downloads
        if not downloads.tool('ffmpeg'):
            self.skipTest('ffmpeg unavailable')
        with tempfile.TemporaryDirectory() as root:
            sample = Path(root) / 'sample.mp4'
            subprocess.run([downloads.tool('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:d=1', '-c:v', 'mpeg4', str(sample)], check=True)
            raw = sample.read_bytes()

            class Response(io.BytesIO):
                headers = {'Content-Length': str(len(raw)), 'Content-Type': 'video/mp4'}
            meta = {'title': 'Geprüft', 'kind': 'movie', 'year': 2020, 'provider': 'manuell'}
            row = {'_id': 'archive:x:1', '_download_url': 'https://archive.org/download/x/a.mp4', '_expect': {'md5': hashlib.md5(raw).hexdigest()}}
            updates = {}
            with patch('core.open_url', return_value=Response(raw)):
                downloads.run(row, meta, Path(root) / 'good', 'best', lambda s, *a, **k: updates.update(k), lambda: False)
            self.assertEqual(updates['source_check'], {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'matched': 'md5'})
            self.assertTrue(core.existing_download(core.target(Path(root) / 'good', meta, 'archive:x:1')))
            bad = dict(row, _expect={'md5': '0' * 32})
            with patch('core.open_url', return_value=Response(raw)):
                with self.assertRaisesRegex(ValueError, 'Prüfsumme von Archive.org'):
                    downloads.run(bad, meta, Path(root) / 'bad', 'best', lambda *a, **k: None, lambda: False)
            self.assertEqual([p.name for p in (Path(root) / 'bad').rglob('*') if p.is_file()], [], 'nothing of a rejected download stays')
            plain = {'_id': 'plain', 'url_video': 'https://example.org/v.mp4'}
            seen = {}
            with patch('core.open_url', return_value=Response(raw)):
                downloads.run(plain, dict(meta, title='Ohne'), Path(root) / 'plain', 'hd', lambda s, *a, **k: seen.update(k), lambda: False)
            self.assertNotIn('source_check', seen, 'other downloads are not hashed')

    def test_manifest_and_job_carry_the_checksums(self):
        import archive_downloads
        import portal_sources
        doc = {'metadata': {'identifier': 'upload_1', 'title': 'Ein Film', 'mediatype': 'movies'},
               'files': [{'name': 'film.mp4', 'source': 'original', 'format': 'MPEG4', 'size': '1000', 'length': '600', 'md5': 'A' * 32, 'sha1': 'c' * 40}]}
        detail = portal_sources.archive_detail_document('upload_1', doc)
        variant = detail['video_variants'][0]
        self.assertEqual((variant['md5'], variant['sha1']), ('a' * 32, 'c' * 40))
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        portal_sources.initialize(c)
        row = portal_sources.entry('internet_archive', 'upload_1', 'Ein Film', 'https://archive.org/details/upload_1')
        c.execute('INSERT INTO portal_items(id,source,external_id,title,title_key,year,page_url,metadata,discovered,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (row['id'], row['source'], row['external_id'], row['title'], 'ein film', None, row['page_url'], '{}', 0, 0))
        portal_sources.save_archive_detail(c, row['id'], detail)
        with tempfile.TemporaryDirectory() as folder:
            built = archive_downloads.build_job(c, folder, row['id'], 'film.mp4')
        self.assertEqual(built['source']['_expect'], {'md5': 'a' * 32, 'sha1': 'c' * 40})


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='receipts-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.a, self.b, self.files = Path(self.tmp) / 'a', Path(self.tmp) / 'b', Path(self.tmp) / 'files'
        for folder in (self.a, self.b, self.files):
            folder.mkdir()

    def published(self, root):
        items = receipts.unpublished(root)
        receipts.mark_published(root, items)
        return items

    def test_key_is_private_and_stable(self):
        seed, public = receipts.keypair(self.a)
        self.assertEqual(receipts.keypair(self.a), (seed, public))
        self.assertNotEqual(receipts.keypair(self.b)[1], public)
        self.assertEqual((self.a / 'receipt_key.json').stat().st_mode & 0o077, 0)

    def test_receipt_and_second_copy(self):
        data = receipts.issue(self.a, job(self.files), now=1000)
        self.assertEqual((data['stored_size'], data['source_check'], data['withdrawn']), (12, 'md5', False))
        self.assertTrue(ed25519_lite.verify(bytes.fromhex(data['pub']), receipts.statement(data), bytes.fromhex(data['sig'])))
        view = receipts.overview(self.a)
        self.assertEqual((view['counts']['own'], view['counts']['single'], view['files'][0]['status']), (1, 1, 'single'))
        self.assertNotIn('source_sha256', view['files'][0]['own'])
        sent = self.published(self.a)
        self.assertEqual(len(sent), 1)
        self.assertEqual(receipts.unpublished(self.a), [])
        self.assertTrue(meshjournal.valid_event({'v': 1, 'node': NODE_A, 'seq': 1, 'hlc': 5, 'type': meshjournal.RECEIPT, 'data': sent[0]}, NODE_A))
        # B has not loaded the file: it only knows A's copy.
        self.assertTrue(receipts.accept(self.b, NODE_A, sent[0]))
        self.assertFalse(receipts.accept(self.b, NODE_A, sent[0]), 'the same receipt twice changes nothing')
        view = receipts.overview(self.b, {NODE_A: 'NAS'})
        self.assertEqual((view['files'][0]['status'], view['files'][0]['copies'][0]['name'], view['counts']['remote_only']), ('remote_only', 'NAS', 1))
        self.assertEqual(receipts.remote(self.b, 'upload_1', 'film.mp4')['node'], NODE_A)
        # B loads the same source; its stored file differs (own remux), the source is the same.
        receipts.issue(self.b, job(self.files, name='B.mkv', content=b'other-container'), now=1100)
        entry = receipts.overview(self.b, {NODE_A: 'NAS'})['files'][0]
        self.assertEqual((entry['status'], entry['copies'][0]['same_source'], entry['copies'][0]['trust']), ('second_copy', True, 'valid'))
        self.assertTrue(receipts.accept(self.a, NODE_B, self.published(self.b)[0]))
        self.assertEqual(receipts.overview(self.a)['counts']['second_copy'], 1)

    def test_forged_and_altered_receipts_are_refused(self):
        data = receipts.issue(self.a, job(self.files), now=1000)
        for change in ({'stored_size': 13}, {'file': 'other.mp4'}, {'stored_sha256': 'f' * 64}, {'withdrawn': True, 'stored_sha256': ''}, {'at': 2000},
                       {'pub': receipts.keypair(self.b)[1]}, {'sig': '0' * 128}):
            self.assertFalse(receipts.accept(self.b, NODE_A, {**data, **change}), change)
        for broken in ({**data, 'identifier': '../x'}, {**data, 'file': '/etc/passwd'}, {**data, 'file': 'a/../b'}, {**data, 'stored_size': -1},
                       {**data, 'converted': 1}, {**data, 'source_check': 'crc'}, {**data, 'sig': 'zz'}, {k: v for k, v in data.items() if k != 'pub'}, 'text'):
            self.assertFalse(receipts.valid_data(broken))
            self.assertFalse(receipts.accept(self.b, NODE_A, broken))
        self.assertEqual(receipts.overview(self.b)['total'], 0)
        self.assertFalse(receipts.accept(self.b, receipts.SELF, data), 'nobody writes into the own receipts')

    def test_changed_key_does_not_count(self):
        self.assertTrue(receipts.accept(self.b, NODE_A, receipts.issue(self.a, job(self.files), now=1000)))
        receipts.issue(self.b, job(self.files, name='B.mkv'), now=1001)
        (self.a / 'receipt_key.json').unlink()
        again = receipts.issue(self.a, job(self.files), now=1500)
        self.assertTrue(receipts.accept(self.b, NODE_A, again))
        view = receipts.overview(self.b)
        self.assertEqual((view['files'][0]['status'], view['files'][0]['copies'][0]['trust'], view['counts']['attention']), ('single', 'key_changed', 1))
        self.assertIsNone(receipts.remote(self.b, 'upload_1', 'film.mp4'))

    def test_different_source_is_shown(self):
        receipts.accept(self.b, NODE_A, receipts.issue(self.a, job(self.files, source=b'one'), now=1000))
        receipts.issue(self.b, job(self.files, name='B.mkv', source=b'two'), now=1001)
        view = receipts.overview(self.b)
        self.assertEqual((view['files'][0]['copies'][0]['same_source'], view['counts']['attention']), (False, 1))
        receipts.issue(self.b, job(self.files, name='B.mkv', source=None), now=1002)
        entry = receipts.overview(self.b)['files'][0]
        self.assertEqual((entry['copies'][0]['same_source'], entry['own']['source_known'], entry['own']['source_check']), (None, False, ''))

    def test_withdraw_after_delete(self):
        first = receipts.issue(self.a, job(self.files), now=1000)
        receipts.accept(self.b, NODE_A, first)
        self.published(self.a)
        gone = receipts.withdraw_job(self.a, job(self.files), now=900)
        self.assertTrue(gone['withdrawn'] and gone['at'] > first['at'], 'a withdrawal is always newer than the receipt, even with a wrong clock')
        self.assertIsNone(receipts.withdraw(self.a, 'upload_1', 'film.mp4'), 'only once')
        self.assertEqual(receipts.overview(self.a)['total'], 0)
        sent = self.published(self.a)
        self.assertEqual([d['withdrawn'] for d in sent], [True])
        self.assertTrue(receipts.accept(self.b, NODE_A, sent[0]))
        self.assertEqual(receipts.overview(self.b)['total'], 0)
        self.assertFalse(receipts.accept(self.b, NODE_A, first), 'the old receipt does not come back')
        self.assertIsNone(receipts.withdraw_job(self.a, {'origin': 'netzkino'}))

    def test_recheck(self):
        receipts.issue(self.a, job(self.files), now=1000)
        self.assertEqual(receipts.recheck(self.a, 'upload_1', 'film.mp4', now=2000)['state'], 'ok')
        self.assertEqual(receipts.overview(self.a)['files'][0]['own']['checked'], 2000)
        (self.files / 'Film.mkv').write_bytes(b'stored-bytez')
        self.assertEqual(receipts.recheck(self.a, 'upload_1', 'film.mp4')['state'], 'changed')
        view = receipts.overview(self.a)
        self.assertEqual((view['files'][0]['own']['check_state'], view['counts']['attention']), ('changed', 1))
        (self.files / 'Film.mkv').unlink()
        self.assertEqual(receipts.recheck(self.a, 'upload_1', 'film.mp4')['state'], 'missing')
        self.assertEqual(receipts.overview(self.a)['total'], 0)
        self.assertTrue(receipts.unpublished(self.a)[0]['withdrawn'])
        with self.assertRaisesRegex(ValueError, 'keinen Nachweis'):
            receipts.recheck(self.a, 'upload_1', 'film.mp4')

    def test_only_archive_downloads_and_missing_list(self):
        with self.assertRaisesRegex(ValueError, 'nur für Archive.org'):
            receipts.issue(self.a, {'origin': 'netzkino', 'path': str(self.files / 'x')})
        with self.assertRaisesRegex(ValueError, 'nicht gefunden'):
            receipts.issue(self.a, dict(job(self.files), path=str(self.files / 'fehlt.mkv')))
        c = sqlite3.connect(':memory:')
        c.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,payload TEXT,state TEXT)')
        one, two = job(self.files, name='1.mkv', file='1.mp4', job_id='1'), job(self.files, name='2.mkv', file='2.mp4', job_id='2')
        lost = dict(job(self.files, name='3.mkv', file='3.mp4', job_id='3'), path=str(self.files / 'weg.mkv'))
        for j, state in ((one, 'done'), (two, 'done'), (lost, 'done'), ({'id': '4', 'origin': 'netzkino'}, 'done'), (dict(one, id='5', archive_file='5.mp4'), 'queued')):
            c.execute('INSERT INTO jobs VALUES(?,?,?)', (j['id'], json.dumps(j), state))
        self.assertEqual([j['id'] for j in receipts.missing(c, self.a)], ['1', '2'])
        receipts.issue(self.a, one)
        self.assertEqual([j['id'] for j in receipts.missing(c, self.a)], ['2'])
        self.assertEqual(receipts.overview(self.a, pending=1)['pending'], 1)

    def test_converted_copy_is_marked(self):
        data = receipts.issue(self.a, dict(job(self.files), encoded={'at': 1}), now=1000)
        self.assertTrue(data['converted'])
        receipts.accept(self.b, NODE_A, data)
        self.assertTrue(receipts.overview(self.b)['files'][0]['copies'][0]['converted'])


class JournalTests(unittest.TestCase):
    def test_receipt_travels_through_the_journal(self):
        self.assertEqual(meshjournal.DOWNLOAD_TYPES, ('download.claim', 'download.done', 'download.release'))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name in ('a', 'b', 'files', 'verbund'):
                (tmp / name).mkdir()
            folder = meshjournal.check_folder(tmp / 'verbund', create=True)
            receipts.issue(tmp / 'a', job(tmp / 'files'), now=1000)
            sender, receiver = meshjournal.Journal(folder, NODE_A, 'A'), meshjournal.Journal(folder, NODE_B, 'B')
            for data in receipts.unpublished(tmp / 'a'):
                sender.append(meshjournal.RECEIPT, data)
            sender.flush(force=True)
            events, _, invalid = receiver.read({})
            self.assertEqual(([e['type'] for e in events], invalid), ([meshjournal.RECEIPT], 0))
            self.assertTrue(receipts.accept(tmp / 'b', events[0]['node'], events[0]['data']))
            self.assertEqual(receipts.overview(tmp / 'b', {NODE_A: 'A'})['files'][0]['copies'][0]['name'], 'A')
            self.assertFalse(meshjournal.valid_event({**events[0], 'data': {**events[0]['data'], 'file': '../x'}}, NODE_A))


class WiringTests(unittest.TestCase):
    def test_routes_package_and_page(self):
        for needle in ("'/api/archive-receipts'", "'/api/archive-receipts-create'", "'/api/archive-receipt-check'", "'/api/archive-receipt-fetch'"):
            self.assertTrue(wired(needle), needle)
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        for needle in ("name='archive_receipt'", 'archive_receipts.withdraw_job(ROOT', 'target=archive_receipt,args=(dict(job),True)'):
            self.assertIn(needle, server)
        service = (ROOT / 'catalog_service.py').read_text(encoding='utf-8')
        self.assertIn('archive_receipts.accept(self.root', service)
        self.assertIn('self.mesh_receipts(journal,folder)', service)
        build = (ROOT / 'build_macos.py').read_text(encoding='utf-8')
        self.assertIn("'archive_receipts.py','ed25519_lite.py'", build)
        page = (ROOT / 'web' / 'storage.js').read_text(encoding='utf-8')
        for needle in ("api('archive-receipts')", "api('archive-receipt-check'", "api('archive-receipt-fetch'", "api('archive-receipts-create'"):
            self.assertIn(needle, page)
        self.assertNotIn('seed', json.dumps(receipts.overview(tempfile.mkdtemp(prefix='receipts-key-'))), 'the secret never leaves the module')


if __name__ == '__main__':
    unittest.main()
