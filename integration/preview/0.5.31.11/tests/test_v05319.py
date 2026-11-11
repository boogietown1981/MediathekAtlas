"""0.5.31.9: authorised standalone files only, with persistent/resumable jobs."""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import netzkino_downloads as dl

ITEM='a'*32

class FakeReply:
    def __init__(self, body, status=200, headers=None):
        self.body=io.BytesIO(body)
        self.status=status
        self.headers=headers or {'Content-Type':'video/mp4','Content-Length':str(len(body)), 'ETag':'"version-1"'}
    def __enter__(self):return self
    def __exit__(self,*a):self.body.close()
    def read(self,n):return self.body.read(n)
    def getcode(self):return self.status

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'state';self.out=Path(self.tmp.name)/'movies'
        dl.initialize(self.root)
        def conn(root):
            c=sqlite3.connect(str(self.root/'fake_netzkino.sqlite3'));c.row_factory=sqlite3.Row
            c.execute('CREATE TABLE IF NOT EXISTS netzkino_catalog(id TEXT,title TEXT,year INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS netzkino_links(id TEXT,title TEXT)')
            return c
        c=conn(self.root)
        try:
            c.execute('INSERT INTO netzkino_catalog VALUES(?,?,?)',(ITEM,'Ein berechtigtes Beispiel',2011))
            c.commit()
        finally:c.close()
        fake=types.SimpleNamespace(_connect=conn)
        self.patch=mock.patch.dict(sys.modules,{'netzkino':fake});self.patch.start();self.addCleanup(self.patch.stop)

    def enqueue(self):
        return dl.enqueue(self.root,ITEM,'https://files.rightsholder.example/test.mp4',
            'written_permission','Explizite Genehmigung vom Rechteinhaber für diese Datei',True)

    def test_requires_separate_permission(self):
        with self.assertRaisesRegex(ValueError,'Bestätigung'):dl.enqueue(self.root,ITEM,'https://files.rightsholder.example/test.mp4','written_permission','Lizenz vorhanden',False)
        with self.assertRaisesRegex(ValueError,'Freigabe'):dl.enqueue(self.root,ITEM,'https://files.rightsholder.example/test.mp4','written_permission','Zu kurz',True)
        with self.assertRaises(ValueError):dl.enqueue(self.root,ITEM,'https://files.rightsholder.example/test.mp4','other','Berechtigung vom Rechteinhaber ausdrücklich dokumentiert',True)

    def test_blocks_provider_player_and_private_or_token_urls(self):
        cases=[
            'https://www.netzkino.de/video/film.mp4',
            'https://cdn.netzkino.de/film.mp4',
            'https://pluto.tv/stream.mp4',
            'https://127.0.0.1/film.mp4',
            'https://192.168.1.2/film.mp4',
            'https://server.local/a.mp4',
            'http://files.example.org/m.mp4',
            'https://files.example.org/a.m3u8',
            'https://files.example.org/a.mpd',
            'https://files.example.org/a.mp4?token=secret',
            'https://user:pass@files.example.org/a.mp4',
        ]
        for url in cases:
            with self.subTest(url=url),self.assertRaises(ValueError):dl.direct_url(url)

    def test_queue_persists_and_never_leaks_source_or_licence(self):
        job=self.enqueue();self.assertTrue(job['created'])
        self.assertEqual(job['id'],self.enqueue()['id'])
        rows=dl.listing(self.root)['items'];self.assertEqual(len(rows),1)
        self.assertNotIn('source_url',rows[0]);self.assertNotIn('rights_note',rows[0])
        self.assertEqual(dl.summary(self.root)['queued'],1)
        dl.initialize(self.root);self.assertEqual(dl.summary(self.root)['queued'],1)

    def test_authorized_direct_file_download(self):
        job=self.enqueue();claim=dl._claim(self.root)
        self.assertEqual(job['id'],claim['id'])
        body=b'0'*1041
        state=dl._work_one(self.root,self.out,claim,opener=lambda req:FakeReply(body))
        self.assertEqual(state,'complete')
        target=self.out/claim['target_name'];self.assertEqual(target.read_bytes(),body)
        self.assertFalse((self.out/(claim['target_name']+'.part')).exists())
        self.assertEqual(dl.listing(self.root)['items'][0]['bytes_done'],len(body))
        self.assertEqual(dl.summary(self.root)['complete'],1)

    def test_resume_with_matching_range_and_etag(self):
        job=self.enqueue();r=dl._claim(self.root)
        self.out.mkdir();(self.out/(r['target_name']+'.part')).write_bytes(b'abc')
        dl._update(self.root,r['id'],etag='"version-1"',bytes_done=3)
        r['etag']='"version-1"'
        def op(req):
            self.assertEqual(req.get_header('Range'),'bytes=3-')
            self.assertEqual(req.get_header('If-range'),'"version-1"')
            return FakeReply(b'def',206,{'Content-Type':'video/mp4','Content-Length':'3',
                'Content-Range':'bytes 3-5/6','ETag':'"version-1"'})
        self.assertEqual(dl._work_one(self.root,self.out,r,opener=op),'complete')
        self.assertEqual((self.out/r['target_name']).read_bytes(),b'abcdef')

    def test_no_overwrite_and_bad_content_error(self):
        self.enqueue();r=dl._claim(self.root);self.out.mkdir();(self.out/r['target_name']).write_bytes(b'exists')
        self.assertEqual(dl._work_one(self.root,self.out,r,opener=lambda _:FakeReply(b'video')),'error')
        self.assertEqual((self.out/r['target_name']).read_bytes(),b'exists')
        self.assertEqual(dl.listing(self.root)['items'][0]['error_code'],'target_exists')
        self.assertEqual(dl.action(self.root,r['id'],'resume')['state'],'queued')
        (self.out/r['target_name']).unlink();r=dl._claim(self.root)
        self.assertEqual(dl._work_one(self.root,self.out,r,opener=lambda _:FakeReply(b'<html/>',headers={'Content-Type':'text/html','Content-Length':'7'})),'error')
        self.assertFalse((self.out/r['target_name']).exists())

    def test_pause_and_persist_crash_recovery(self):
        self.enqueue();r=dl._claim(self.root)
        self.assertEqual(dl.action(self.root,r['id'],'pause')['state'],'paused')
        self.assertIsNone(dl._claim(self.root))
        dl.action(self.root,r['id'],'resume')
        self.assertEqual(dl._claim(self.root)['id'],r['id'])
        dl.initialize(self.root)
        self.assertEqual(dl.listing(self.root)['items'][0]['state'],'queued')

    def test_https_and_dns_unsafe_blocked(self):
        with mock.patch('socket.getaddrinfo',return_value=[(None,None,None,None,('10.0.0.1',443))]):
            with self.assertRaisesRegex(ValueError,'Private'):dl._resolve_public('files.example.org')
        with mock.patch('socket.getaddrinfo',return_value=[(None,None,None,None,('203.0.113.3',443))]):
            with self.assertRaisesRegex(ValueError,'Private'):dl._resolve_public('files.example.org')

    def test_build_patch_has_explicit_archivemedia_guards(self):
        src=(Path(__file__).resolve().parents[1]/'apply_05319.py').read_text()
        for text in ('archive_companion.py','portal_control.py','/api/netzkino-downloads',
                     'netzkino_licensed_file_worker','/api/netzkino-download-add'):
            self.assertIn(text,src)

if __name__=='__main__':unittest.main()
