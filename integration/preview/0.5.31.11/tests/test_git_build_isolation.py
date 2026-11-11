"""Regression: independent shallow clones prevent the macOS Git step-2 failure."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import merge_portals

BASE=Path(__file__).resolve().parents[1]

class IndependentCloneTests(TestCase):
    def test_installer_does_not_fetch_second_branch_into_first_shallow_clone(self):
        command=(BASE/'Netzkino-Testversion-bauen.command').read_text('utf8')
        self.assertIn('PORTAL_SRC="$WORKDIR/ArchiveMedia-PR24-Quelle"', command)
        self.assertIn('git clone --progress --depth 1 --no-tags', command)
        self.assertIn('git -C "$PORTAL_SRC" rev-parse HEAD', command)
        self.assertIn('--portal-repo "$PORTAL_SRC"', command)
        self.assertNotIn('git -C "$SRC" fetch',command)
        self.assertIn('BASE_EXPECTED',command)
        self.assertIn('PORTAL_EXPECTED',command)

    def test_merge_requires_a_distinct_repo(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(RuntimeError,'nicht denselben Git-Klon'):
                merge_portals._check_portal_repo(root,root)
            with self.assertRaisesRegex(RuntimeError,'erforderlich'):
                merge_portals._check_portal_repo(root,None)

    def test_merge_rejects_unpinned_pr24(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=root/'portals'
            p.mkdir()
            subprocess.run(['git','init','-q',str(p)],check=True)
            (p/'test').write_text('x')
            subprocess.run(['git','-C',str(p),'add','test'],check=True)
            subprocess.run(['git','-C',str(p),'-c','user.email=tests@example.com','-c','user.name=Tests','commit','-qm','test'],check=True)
            with self.assertRaisesRegex(RuntimeError,'erwarteter Commit'):
                merge_portals._check_portal_repo(root,p)
