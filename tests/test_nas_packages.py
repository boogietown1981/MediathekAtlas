import ast,hashlib,http.client,json,os,re,shutil,socket,subprocess,sys,tarfile,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import access,build_nas
try:import PIL
except ImportError:PIL=None

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def call(port,method,path,body=None,headers=None):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
    try:
        c.request(method,path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json',**(headers or {})})
        r=c.getresponse();return r.status,r.read().decode(),r.getheader('Set-Cookie') or ''
    finally:c.close()

def extract(tar,dest):
    tar.extractall(dest,**({'filter':'data'} if hasattr(tarfile,'data_filter') else {}))

def wait_http(port):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:return call(port,'GET','/api/login-state')
        except OSError:time.sleep(.2)
    raise AssertionError('Server antwortet nicht')

class AccessTests(unittest.TestCase):
    def test_password_hash_session_and_change(self):
        with tempfile.TemporaryDirectory() as d:
            a=access.Access(d)
            self.assertFalse(a.configured())
            with self.assertRaises(ValueError):a.set_password('kurz')
            a.set_password('richtig-lang');self.assertTrue(a.configured())
            self.assertNotIn('richtig-lang',(Path(d)/'access.json').read_text())
            self.assertEqual(oct((Path(d)/'access.json').stat().st_mode&0o777),'0o600')
            token=a.login('1.2.3.4','richtig-lang');self.assertTrue(a.valid(token));self.assertFalse(a.valid('falsch'))
            with self.assertRaises(ValueError):a.login('1.2.3.4','falsch')
            fresh=a.change_password('richtig-lang','neues-passwort')
            self.assertFalse(a.valid(token));self.assertTrue(a.valid(fresh))
            a.logout(fresh);self.assertFalse(a.valid(fresh))
    def test_failed_logins_are_rate_limited(self):
        with tempfile.TemporaryDirectory() as d:
            a=access.Access(d);a.set_password('richtig-lang')
            for _ in range(access.FAILURES):
                with self.assertRaises(ValueError):a.login('9.9.9.9','x')
            with self.assertRaises(PermissionError):a.login('9.9.9.9','richtig-lang')
            self.assertTrue(a.valid(a.login('8.8.8.8','richtig-lang')))
    def test_setup_code_written_to_share_and_removed(self):
        with tempfile.TemporaryDirectory() as d:
            share=Path(d)/'share';a=access.Access(Path(d)/'state',[share]);(Path(d)/'state').mkdir()
            files=a.ensure_setup_code();self.assertIn(str(share/access.SETUP_FILE),files)
            code=re.search(r'\n([0-9A-F]{8})\n',(share/access.SETUP_FILE).read_text()).group(1)
            with self.assertRaises(ValueError):a.login('1.1.1.1',setup_code='00000000',new_password='richtig-lang')
            self.assertTrue(a.valid(a.login('1.1.1.1',setup_code=code.lower(),new_password='richtig-lang')))
            self.assertFalse((share/access.SETUP_FILE).exists());self.assertTrue(a.verify('richtig-lang'))
    def test_initial_password_from_install_wizard(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'initial-password').write_text('assistent-pw\n')
            a=access.Access(d);self.assertTrue(a.verify('assistent-pw'));self.assertFalse((Path(d)/'initial-password').exists())
    def test_cookie_parsing(self):
        self.assertEqual(access.cookie_token('a=1; mediathekatlas_session=abc; b=2','mediathekatlas_session'),'abc')
        self.assertEqual(access.cookie_token(None),'')

class PackageContentTests(unittest.TestCase):
    def test_macos_bundle_lists_every_runtime_module(self):
        tree=ast.parse((ROOT/'build_macos.py').read_text())
        listed=next(set(ast.literal_eval(n.iter)) for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.iter,ast.Tuple) and len(n.iter.elts)>5)
        self.assertEqual(listed,set(build_nas.app_files()))
    def test_shell_scripts_are_posix(self):
        for p in [ROOT/'packaging'/'nas'/'mediathekatlas-service.sh',ROOT/'packaging'/'qnap'/'shared'/'MediathekAtlas.sh',*(ROOT/'packaging'/'synology'/'scripts').iterdir()]:
            subprocess.run(['sh','-n',str(p)],check=True)

@unittest.skipUnless(PIL,'Pillow wird für Paket-Icons benötigt')
class NasPackageTests(unittest.TestCase):
    env={k:v for k,v in os.environ.items() if not k.startswith(('MEDIATHEKATLAS_','ATLAS_','SYNOPKG_'))}
    env['MEDIATHEKATLAS_DISABLE_BACKGROUND']='1'
    def login_flow(self,port,password,managed):
        status,body,_=call(port,'GET','/');self.assertEqual(status,200);self.assertIn('login.js',body);self.assertNotIn('atlas-token',body)
        self.assertEqual(call(port,'GET','/api/state')[0],401)
        self.assertEqual(call(port,'POST','/api/login',{'password':'falsch'})[0],403)
        status,_,cookie=call(port,'POST','/api/login',{'password':password});self.assertEqual(status,200)
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie);cookie=cookie.split(';')[0]
        status,body,_=call(port,'GET','/',headers={'Cookie':cookie,'Host':'nas.local:%d'%port});self.assertEqual(status,200)
        token=re.search(r'atlas-token" content="([^"]+)',body).group(1)
        status,body,_=call(port,'GET','/api/state',headers={'Cookie':cookie,'X-Atlas-Token':token});self.assertEqual(status,200)
        state=json.loads(body);self.assertEqual(state['server'],{'network':True,'managed':managed,'version':build_nas.VERSION})
        status,body,_=call(port,'POST','/api/shutdown',{},headers={'Cookie':cookie,'X-Atlas-Token':token});self.assertEqual(status,400)
        return state
    def test_spk_layout_and_service_lifecycle(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);spk=build_nas.build_spk(d/'dist')
            with tarfile.open(spk) as tar:
                names=tar.getnames();members={m.name:m for m in tar.getmembers()}
                for required in ('INFO','package.tgz','scripts/start-stop-status','scripts/postinst','conf/privilege','conf/resource','WIZARD_UIFILES/install_uifile_ger','PACKAGE_ICON.PNG','PACKAGE_ICON_256.PNG'):self.assertIn(required,names)
                self.assertEqual(members['scripts/start-stop-status'].mode,0o755)
                info=dict(re.findall(r'^(\w+)="(.*)"$',tar.extractfile('INFO').read().decode(),re.M))
                package=tar.extractfile('package.tgz').read()
                for name in names:
                    if name.startswith(('conf/','WIZARD_UIFILES/')):json.loads(tar.extractfile(name).read())
                extract(tar,d/'pkg')
            self.assertEqual(info['checksum'],hashlib.md5(package).hexdigest());self.assertEqual(info['arch'],'noarch')
            self.assertEqual(info['version'],build_nas.VERSION+'-'+build_nas.SPK_BUILD);self.assertNotIn('install_dep_packages',info)
            privilege=json.loads((d/'pkg'/'conf'/'privilege').read_text());self.assertEqual(privilege['defaults']['run-as'],'package')
            share=json.loads((d/'pkg'/'conf'/'resource').read_text())['data-share']['shares'][0]
            self.assertIn(privilege['username'],share['permission']['rw'])
            target=d/'pkg'/'target';target.mkdir()
            with tarfile.open(d/'pkg'/'package.tgz') as tar:extract(tar,target)
            self.assertTrue((target/'mediathekatlas'/'server.py').is_file());self.assertFalse((target/'mediathekatlas'/'build_nas.py').exists())
            ui=json.loads((target/'ui'/'config').read_text())['.url']['de.mediathekatlas'];self.assertEqual(ui['port'],str(build_nas.PORT))
            self.assertTrue((target/'ui'/'images'/'MediathekAtlas_256.png').is_file())
            for p in (d/'pkg'/'scripts').iterdir():self.assertNotIn('@PORT@',p.read_text())
            port=free_port();var=d/'var';var.mkdir()
            (var/'mediathekatlas.conf').write_text(f'PORT={port}\nPYTHON="{sys.executable}"\n')
            env={**self.env,'SYNOPKG_PKGDEST':str(target),'SYNOPKG_PKGVAR':str(var),'SYNOPKG_PKGNAME':'MediathekAtlas','ATLAS_DOWNLOADS':str(d/'share')}
            subprocess.run(['sh',str(d/'pkg'/'scripts'/'postinst')],env={**env,'wizard_password':'assistent-pw'},check=True)
            script=str(d/'pkg'/'scripts'/'start-stop-status')
            try:
                r=subprocess.run(['sh',script,'start'],env=env,capture_output=True,text=True,timeout=60);self.assertEqual(r.returncode,0,r.stdout+r.stderr+(var/'service.log').read_text())
                self.assertEqual(subprocess.run(['sh',script,'status'],env=env,capture_output=True).returncode,0)
                self.assertEqual(json.loads(wait_http(port)[1])['configured'],True)
                state=self.login_flow(port,'assistent-pw','synology')
                self.assertEqual(state['settings']['download_dir'],str(d/'share'))
                self.assertFalse((var/'initial-password').exists())
            finally:
                subprocess.run(['sh',script,'stop'],env=env,capture_output=True,timeout=60)
            self.assertEqual(subprocess.run(['sh',script,'status'],env=env,capture_output=True).returncode,3)
            self.assertIn('MediathekAtlas gestoppt',(var/'service.log').read_text())
    def test_qdk_project_and_service_lifecycle(self):
        project=build_nas.build_qdk_project()
        cfg=dict(re.findall(r'^(\w+)="(.*)"$',(project/'qpkg.cfg').read_text(),re.M))
        self.assertEqual(cfg['QPKG_VER'],build_nas.VERSION);self.assertEqual(cfg['QPKG_WEB_PORT'],str(build_nas.PORT))
        self.assertTrue((project/'shared'/cfg['QPKG_SERVICE_PROGRAM']).is_file())
        for name in ('MediathekAtlas.gif','MediathekAtlas_80.gif','MediathekAtlas_gray.gif'):self.assertEqual((project/'icons'/name).read_bytes()[:3],b'GIF')
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);os.chmod(d,0o755);qpkg_root=d/'MediathekAtlas';shutil.copytree(project/'shared',qpkg_root)
            port=free_port();(qpkg_root/'data').mkdir()
            run_as='nobody' if os.geteuid()==0 else ''
            (qpkg_root/'data'/'mediathekatlas.conf').write_text(f'PORT={port}\nPYTHON={sys.executable}\nDOWNLOADS={d/"Download"/"MediathekAtlas"}\n'+(f'RUN_AS={run_as}\n' if run_as else ''))
            # A fresh install without password: setup code lands in the download share.
            env={**self.env,'QPKG_ROOT':str(qpkg_root)};script=str(qpkg_root/'MediathekAtlas.sh')
            try:
                r=subprocess.run(['sh',script,'start'],env=env,capture_output=True,text=True,timeout=60);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                state=json.loads(wait_http(port)[1]);self.assertFalse(state['configured'])
                setup=d/'Download'/'MediathekAtlas'/access.SETUP_FILE;self.assertIn(str(setup),state['setup_files'])
                code=re.search(r'\n([0-9A-F]{8})\n',setup.read_text()).group(1)
                status,_,_=call(port,'POST','/api/login',{'setup_code':code,'new_password':'nas-passwort'});self.assertEqual(status,200)
                self.assertFalse(setup.exists())
                self.login_flow(port,'nas-passwort','qnap')
                if run_as:
                    pid=(qpkg_root/'data'/'mediathekatlas.pid').read_text().strip()
                    self.assertEqual(Path(f'/proc/{pid}/status').read_text().split('Uid:')[1].split()[0],'65534')
            finally:
                subprocess.run(['sh',script,'stop'],env=env,capture_output=True,timeout=60)
            self.assertEqual(subprocess.run(['sh',script,'status'],env=env,capture_output=True).returncode,3)

class PythonDetectionTests(unittest.TestCase):
    def test_preinst_accepts_any_python_package_and_explains_missing_one(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);packages=d/'var'/'packages'
            script=(ROOT/'packaging'/'synology'/'scripts'/'preinst').read_text().replace('/var/packages',str(packages)).replace('/usr/local/bin/python3 /usr/bin/python3','/fehlt/1 /fehlt/2')
            (d/'preinst').write_text(script);log=d/'log'
            r=subprocess.run(['sh',str(d/'preinst')],env={**os.environ,'SYNOPKG_TEMP_LOGFILE':str(log)},capture_output=True)
            self.assertEqual(r.returncode,1);self.assertIn('Python ab Version 3.9',log.read_text())
            # e.g. SynoCommunity python311 instead of the official Python3.9 package
            bin_dir=packages/'python311'/'target'/'bin';bin_dir.mkdir(parents=True);(bin_dir/'python3').symlink_to(sys.executable)
            self.assertEqual(subprocess.run(['sh',str(d/'preinst')],capture_output=True).returncode,0)

class DesktopModeTests(unittest.TestCase):
    def test_desktop_server_keeps_loopback_host_check_without_login(self):
        with tempfile.TemporaryDirectory() as d:
            env={**NasPackageTests.env,'MEDIATHEKATLAS_HOME':d}
            p=subprocess.Popen([sys.executable,'server.py','--no-browser'],cwd=ROOT,env=env,stdout=subprocess.PIPE,text=True)
            try:
                port=int(p.stdout.readline().strip().rsplit(':',1)[1])
                status,body,_=call(port,'GET','/',headers={'Host':f'127.0.0.1:{port}'});self.assertEqual(status,200);self.assertIn('atlas-token',body)
                self.assertEqual(call(port,'GET','/',headers={'Host':'evil.example'})[0],403)
                self.assertEqual(json.loads(call(port,'GET','/api/login-state',headers={'Host':f'127.0.0.1:{port}'})[1]),{'required':False})
            finally:p.terminate();p.wait(10);p.stdout.close()
if __name__=='__main__':unittest.main()
