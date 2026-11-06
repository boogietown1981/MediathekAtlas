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

class SeveralConnectionsTests(unittest.TestCase):
    """Synology, QNAP and Mac: every system may hold several connections at once."""
    def start_nas(self,d,name):
        home=d/name;home.mkdir();(home/'initial-password').write_text('nas-passwort\n');port=nas.free_port()
        env={**nas.NasPackageTests.env,'MEDIATHEKATLAS_HOME':str(home),'MEDIATHEKATLAS_LISTEN':'127.0.0.1','MEDIATHEKATLAS_LOGIN':'1','MEDIATHEKATLAS_PORT':str(port),'MEDIATHEKATLAS_DOWNLOAD_DIR':str(d/(name+'-share'))}
        p=subprocess.Popen([sys.executable,'server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.addCleanup(lambda:(p.terminate(),p.wait(10)))
        nas.wait_http(port);cookie=nas.call(port,'POST','/api/login',{'password':'nas-passwort'})[2].split(';')[0]
        token=re.search(r'name="atlas-token" content="([^"]+)"',nas.call(port,'GET','/',headers={'Cookie':cookie})[1]).group(1)
        h={'Cookie':cookie,'X-Atlas-Token':token}
        api=lambda body:nas.call(port,'POST','/api/mesh-direct',body,h)
        status,body,_=api({'action':'share'});self.assertEqual(status,200,body)
        url='http://127.0.0.1:%d'%port;code=url+'#'+json.loads(body)['key']
        deadline=time.monotonic()+15
        while True:
            try:meshpeer.Peer(url,json.loads(body)['key']).hello();break
            except meshpeer.PeerError:
                if time.monotonic()>deadline:raise
                time.sleep(.3)
        state=lambda:json.loads(nas.call(port,'GET','/api/state',headers=h)[1])['settings']
        return url,code,api,state,home
    def test_codes_are_added_not_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(os.path.realpath(d))
            syn_url,syn_code,syn_api,syn_state,syn_home=self.start_nas(d,'synology')
            q_url,q_code,q_api,q_state,q_home=self.start_nas(d,'qnap')
            status,body,_=syn_api({'action':'connect','code':syn_code})
            self.assertNotEqual(status,200);self.assertIn('dieses Systems selbst',body)
            status,body,_=syn_api({'action':'connect','code':q_code});self.assertEqual(status,200,body)
            status,body,_=q_api({'action':'connect','code':syn_code});self.assertEqual(status,200,body)
            # Connecting must not touch the system's own share key (the 0.5.14 bug).
            self.assertEqual(syn_state()['mesh_peers'],[q_url]);self.assertTrue(syn_state()['mesh_shared'])
            self.assertTrue(meshpeer.Peer(syn_url,syn_code.split('#')[1]).hello())
            # The Mac holds both connections and relays between them.
            (d/'mac').mkdir();mac=meshjournal.Journal(meshjournal.check_folder(d/'mac',create=True),B,'Mac')
            mac.append('match.manual',{'work':'w1','dest':'w1','outcome':'manual','meta':{'title':'Persona'},'providers':[]});mac.flush(force=True)
            peers=meshpeer.peer_list({'mesh_peers':[{'url':syn_url,'key':syn_code.split('#')[1]},{'url':q_url,'key':q_code.split('#')[1]},{'url':q_url+'/','key':q_code.split('#')[1]}]})
            self.assertEqual([p['url'] for p in peers],[syn_url,q_url])
            for p in peers:meshpeer.Peer(p['url'],p['key']).sync(mac.root,mac.node)
            for home in (syn_home,q_home):self.assertTrue((home/'verbund'/'nodes'/B/'events-000001.jsonl').is_file())
            status,body,_=syn_api({'action':'remove','url':q_url});self.assertEqual(status,200,body)
            self.assertEqual(syn_state()['mesh_peers'],[]);self.assertTrue(syn_state()['mesh_shared'])
            status,body,_=syn_api({'action':'unshare'});self.assertFalse(syn_state()['mesh_shared'])
    def test_old_single_connection_is_still_read(self):
        key=meshpeer.new_key()
        self.assertEqual(meshpeer.peer_list({'mesh_peer':'http://nas:8730/','mesh_key':key}),[{'url':'http://nas:8730','key':key}])
        self.assertEqual(meshpeer.peer_list({'mesh_peers':'kaputt','mesh_peer':''}),[])

if __name__=='__main__':unittest.main()
