import json,os,re,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import meshjournal,meshpeer
import test_nas_packages as nas

A='a'*32;B='b'*32

class StoreTests(unittest.TestCase):
    def test_code_parsing(self):
        key=meshpeer.new_key()
        self.assertEqual(meshpeer.parse_code('http://synology:8730/#'+key),('http://synology:8730',key))
        self.assertEqual(meshpeer.parse_code('100.101.1.2:8730#'+key),('http://100.101.1.2:8730',key))
        for bad in ('ftp://x#'+key,'http://user:pw@x:1#'+key,'http://x:1#kurz'):
            with self.assertRaises(meshpeer.PeerError):meshpeer.parse_code(bad)
    def test_store_rules(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(meshpeer.store(d,A,'nodes/%s/events-000001.jsonl'%B,b'x\n',100))
            self.assertFalse(meshpeer.store(d,A,'nodes/%s/events-000001.jsonl'%B,b'anders\n',200),'segments are immutable')
            self.assertEqual((Path(d)/'nodes'/B/'events-000001.jsonl').read_bytes(),b'x\n')
            self.assertFalse(meshpeer.store(d,A,'nodes/%s/node.json'%A,b'{}',100),'own directory is never written')
            self.assertTrue(meshpeer.store(d,A,'nodes/%s/node.json'%B,b'1',100))
            self.assertFalse(meshpeer.store(d,A,'nodes/%s/node.json'%B,b'0',50),'older heartbeat ignored')
            self.assertTrue(meshpeer.store(d,A,'nodes/%s/node.json'%B,b'2',150))
            for bad in ('../x','nodes/%s/../../x'%B,'nodes/%s/events-1.jsonl'%B,'nodes/%s/x.partial'%B,'/etc/passwd'):
                with self.assertRaises(meshpeer.PeerError):meshpeer.store(d,A,bad,b'',1)
            self.assertEqual(sorted(meshpeer.index(d)),['nodes/%s/events-000001.jsonl'%B,'nodes/%s/node.json'%B])

class ErrorMessageTests(unittest.TestCase):
    def test_real_cause_is_reported(self):
        import http.server,threading
        answers={'/api/peer/index':(503,b'{"error":"Verbund auf der Gegenstelle nicht aktiv: Ordner fehlt"}')}
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                code,body=answers[self.path];self.send_response(code);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=srv.serve_forever,daemon=True).start()
        try:
            peer=meshpeer.Peer('http://127.0.0.1:%d'%srv.server_port,meshpeer.new_key())
            with self.assertRaisesRegex(meshpeer.PeerError,'Ordner fehlt'):peer.hello()
            answers['/api/peer/index']=(403,b'{}')
            with self.assertRaisesRegex(meshpeer.PeerError,'Schlüssel'):peer.hello()
            answers['/api/peer/index']=(200,b'<html>Router</html>')
            with self.assertRaisesRegex(meshpeer.PeerError,'kein MediathekAtlas'):peer.hello()
        finally:srv.shutdown();srv.server_close()
        with self.assertRaisesRegex(meshpeer.PeerError,'läuft kein MediathekAtlas'):meshpeer.Peer('http://127.0.0.1:%d'%srv.server_port,meshpeer.new_key()).hello()

class DirectConnectionTests(unittest.TestCase):
    def test_mac_mirrors_journal_with_nas_over_http(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(os.path.realpath(d));home=d/'nas';home.mkdir();(home/'initial-password').write_text('nas-passwort\n')
            port=nas.free_port()
            env={**nas.NasPackageTests.env,'MEDIATHEKATLAS_HOME':str(home),'MEDIATHEKATLAS_LISTEN':'127.0.0.1','MEDIATHEKATLAS_LOGIN':'1','MEDIATHEKATLAS_PORT':str(port),'MEDIATHEKATLAS_DOWNLOAD_DIR':str(d/'share')}
            p=subprocess.Popen([sys.executable,'server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                nas.wait_http(port);url='http://127.0.0.1:%d'%port
                with self.assertRaises(meshpeer.PeerError):meshpeer.Peer(url,meshpeer.new_key()).hello()
                cookie=nas.call(port,'POST','/api/login',{'password':'nas-passwort'})[2].split(';')[0]
                token=re.search(r'name="atlas-token" content="([^"]+)"',nas.call(port,'GET','/',headers={'Cookie':cookie})[1]).group(1)
                status,body,_=nas.call(port,'POST','/api/mesh-direct',{'action':'share'},{'Cookie':cookie,'X-Atlas-Token':token})
                self.assertEqual(status,200,body);share=json.loads(body);key=share['key'];self.assertTrue(share['network'])
                peer=meshpeer.Peer(url,key)
                deadline=time.monotonic()+15
                while True:
                    try:info=peer.hello();break
                    except meshpeer.PeerError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.3)
                nas_node=info['node'];self.assertTrue(any(f.endswith('node.json') for f in info['files']))
                self.assertTrue((home/'verbund'/'nodes'/nas_node/'node.json').is_file())
                # The Mac side: its own journal in a local folder, one published segment.
                (d/'mac').mkdir();mac=meshjournal.Journal(meshjournal.check_folder(d/'mac',create=True),B,'Mac Einsbach')
                mac.append('match.manual',{'work':'w1','dest':'w1','outcome':'manual','meta':{'title':'Persona'},'providers':[]});mac.flush(force=True)
                mac.heartbeat({'recognizing':True,'rate':1,'providers':[]})
                first=peer.sync(mac.root,mac.node)
                self.assertEqual((first['sent'],first['peer']),(2,info['name']));self.assertGreaterEqual(first['received'],1)
                self.assertEqual((home/'verbund'/'nodes'/B/'events-000001.jsonl').read_bytes(),(mac.dir/'events-000001.jsonl').read_bytes())
                self.assertTrue((d/'mac'/'nodes'/nas_node/'node.json').is_file())
                again=peer.sync(mac.root,mac.node);self.assertEqual((again['sent'],again['received']),(0,0))
                # Nobody may write into the NAS's own directory.
                status=peer._call('PUT','/api/peer/file',{'path':'nodes/%s/node.json'%nas_node,'mtime':int(time.time())+999},b'{}',limit=4096)
                self.assertFalse(json.loads(status)['stored'])
                with self.assertRaises(meshpeer.PeerError):peer._call('PUT','/api/peer/file',{'path':'../../x'},b'x',limit=4096)
                with self.assertRaises(meshpeer.PeerError):meshpeer.Peer(url,meshpeer.new_key()).sync(mac.root,mac.node)
            finally:p.terminate();p.wait(10)

if __name__=='__main__':unittest.main()
