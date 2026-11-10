"""Portable macOS app ZIP must be extractable, complete and executable."""
import plistlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from packaging.macos_zip import APP_NAME, LAUNCHER, PLIST, RESOURCES, build_zip, verify_zip


class PortableMacOSZipTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = self.root / APP_NAME
        for name in (LAUNCHER, PLIST,
                     RESOURCES + "server.py", RESOURCES + "catalog.py",
                     RESOURCES + "version.py", RESOURCES + "video_causality.py",
                     RESOURCES + "web/index.html", RESOURCES + "web/app.js"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stub", encoding="utf-8")
        (self.root / PLIST).write_bytes(
            plistlib.dumps({"CFBundleExecutable": "MediathekAtlas",
                            "CFBundleShortVersionString": "0.5.31"}))
        (self.root / LAUNCHER).chmod(0o755)
        self.output = self.root / "dist" / "app.zip"

    def test_bundle_is_valid_and_launcher_remains_executable(self):
        build_zip(self.app, self.output)
        result = verify_zip(self.output, "0.5.31")
        self.assertEqual(result["version"], "0.5.31")
        self.assertEqual(result["files"], 8)
        with zipfile.ZipFile(self.output) as z:
            launcher = z.getinfo(LAUNCHER)
            self.assertTrue((launcher.external_attr >> 16) & 0o111)

    def test_non_executable_launcher_is_rejected_before_build(self):
        (self.root / LAUNCHER).chmod(0o644)
        with self.assertRaisesRegex(ValueError, "nicht ausführbar"):
            build_zip(self.app, self.output)

    def test_missing_source_file_is_rejected(self):
        (self.root / (RESOURCES + "video_causality.py")).unlink()
        build_zip(self.app, self.output)
        with self.assertRaisesRegex(ValueError, "Dateien fehlen"):
            verify_zip(self.output, "0.5.31")

    def test_version_mismatch_is_rejected(self):
        build_zip(self.app, self.output)
        with self.assertRaisesRegex(ValueError, "Falsche App-Version"):
            verify_zip(self.output, "0.5.30")


if __name__ == "__main__":
    unittest.main()
