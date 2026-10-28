import ast, os, plistlib, struct, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runtime_tools
ROOT=Path(__file__).resolve().parents[1]
class RuntimeTests(unittest.TestCase):
    def setUp(self):runtime_tools._CACHE.clear()
    def fake(self,path,text='ffmpeg version 9.0',exitcode=0):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" "'+text+'"\nexit '+str(exitcode)+'\n');path.chmod(0o755);return path
    def test_keg_only_ffmpeg_full(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.fake(Path(root)/'opt/ffmpeg-full/bin/ffmpeg')
            with patch('runtime_tools.shutil.which',return_value=None):
                c=runtime_tools.candidates('ffmpeg',prefixes=[root])
            with patch('runtime_tools.candidates',return_value=c):r=runtime_tools.status('ffmpeg')
            self.assertTrue(r['ok']);self.assertEqual(r['path'],str(path.resolve()))
    def test_cellar_without_opt_link(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.fake(Path(root)/'Cellar/ffmpeg-full/9.0.2/bin/ffprobe','ffprobe version 9.0.2')
            with patch('runtime_tools.shutil.which',return_value=None):c=runtime_tools.candidates('ffprobe',prefixes=[root])
            self.assertIn(str(path),c)
    def test_broken_binary_falls_back(self):
        with tempfile.TemporaryDirectory() as root:
            bad=self.fake(Path(root)/'bad','dyld: missing dylib',1)
            good=self.fake(Path(root)/'good')
            with patch('runtime_tools.candidates',return_value=[str(bad),str(good)]):r=runtime_tools.status('ffmpeg')
            self.assertTrue(r['ok']);self.assertEqual(r['path'],str(good));self.assertEqual(len(r['failed_candidates']),1)
    def test_wrong_program_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.fake(Path(root)/'ffmpeg','Python 3.12')
            self.assertFalse(runtime_tools.inspect_tool(str(p),'ffmpeg')['ok'])
    def test_installed_after_launch(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'ffmpeg'
            with patch('runtime_tools.candidates',return_value=[str(p)]),patch('runtime_tools.shutil.which',return_value=None):
                self.assertFalse(runtime_tools.status('ffmpeg')['ok'])
                self.fake(p)
                self.assertTrue(runtime_tools.status('ffmpeg',refresh=True)['ok'])
    def test_python39_syntax(self):
        for p in ROOT.rglob('*.py'):
            if 'build' in p.relative_to(ROOT).parts:continue
            ast.parse(p.read_text(),feature_version=(3,9))
    def test_launcher_with_python_outside_standard_paths(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'Custom Python'/ 'python3';path.parent.mkdir()
            path.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then echo "Python 3.9 (test fixture)"; exit 0; fi\necho "SERVER_STARTED:$1"\n')
            path.write_text(path.read_text().replace('echo "SERVER_STARTED:$1"', 'case "$1" in *stable_runtime.py) exec '+__import__('shlex').quote(sys.executable)+' "$@";; esac\necho "SERVER_STARTED:$1"'))
            path.chmod(0o755)
            env={**os.environ,'MEDIATHEKATLAS_PYTHON':str(path),'MEDIATHEKATLAS_HOME':str(Path(root)/'state')}
            r=subprocess.run(['bash',str(ROOT/'launcher.sh')],env=env,capture_output=True,timeout=15)
            self.assertEqual(r.returncode,0)
            log=(Path(root)/'state'/'startup.log').read_text()
            self.assertIn('SERVER_STARTED:server.py',log);self.assertIn(str(path),log)
    def test_bundle_icon_and_version(self):
        bundle=ROOT/'build'/'MediathekAtlas.app'/'Contents'
        if not bundle.exists():self.skipTest('Build first')
        p=plistlib.loads((bundle/'Info.plist').read_bytes());self.assertEqual(p['CFBundleShortVersionString'],'0.4.7')
        data=(bundle/'Resources'/p['CFBundleIconFile']).read_bytes()
        self.assertEqual(data[:4],b'icns');self.assertEqual(struct.unpack('>I',data[4:8])[0],len(data))
        tags=[];pos=8
        while pos<len(data):
            tags.append(data[pos:pos+4]);size=struct.unpack('>I',data[pos+4:pos+8])[0];self.assertGreater(size,8);pos+=size
        self.assertEqual(pos,len(data));self.assertIn(b'ic10',tags);self.assertIn(b'icp4',tags)
if __name__=='__main__':unittest.main()
