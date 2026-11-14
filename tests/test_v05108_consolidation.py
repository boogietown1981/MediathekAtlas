"""0.5.108 (Phase A, Review 14.11.2026): every catalogue platform reloads a partial or failed
catalogue once after an update, not only Plex, ServusTV and RTL+; small review fixes."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PLATFORMS = ('pluto', 'justwatch', 'rakuten', 'joyn', 'toggo', 'crunchyroll', 'youtube', 'netzkino',
             'plex', 'servustv', 'rtlplus')


class _OneRound:
    """Stop event that lets loop() run exactly one round."""
    def __init__(self):
        self.calls = 0

    def wait(self, _seconds):
        self.calls += 1
        return self.calls > 1


class RetryAfterUpdateTests(unittest.TestCase):
    def test_every_platform_loop_asks_for_the_reload(self):
        # 0.6.0: the rule lives once in provider_base.catalog_due; every platform asks it.
        self.assertIn('portal_reference.retry_after_update(root, module, current)', (ROOT / 'provider_base.py').read_text())
        for name in PLATFORMS:
            source = (ROOT / (name + '.py')).read_text(encoding='utf-8')
            self.assertIn('provider_base.catalog_due(root, sys.modules[__name__], ', source, name)

    def test_partial_catalogue_starts_once_per_version(self):
        import portal_reference
        for name in ('pluto', 'justwatch', 'rakuten', 'joyn', 'toggo', 'crunchyroll', 'netzkino'):
            module = importlib.import_module(name)
            with self.subTest(platform=name), tempfile.TemporaryDirectory() as tmp:
                db = module._connect(tmp)
                with db:
                    module._set(db, 'last_attempt', '1000')
                    module._set(db, 'last_success', '900')
                    module._set(db, 'last_result', 'partial')
                db.close()
                started = []
                with mock.patch.object(module, 'start_sync', lambda root: started.append(root)), \
                        mock.patch.object(portal_reference, 'first_load_due', lambda current: False):
                    module.loop(tmp, _OneRound())
                    module.loop(tmp, _OneRound())
                self.assertEqual(started, [tmp], name)   # first round reloads, second does not

    def test_complete_catalogue_is_left_alone(self):
        import portal_reference
        import toggo
        with tempfile.TemporaryDirectory() as tmp:
            db = toggo._connect(tmp)
            with db:
                toggo._set(db, 'last_result', 'complete')
            db.close()
            self.assertFalse(portal_reference.retry_after_update(tmp, toggo, toggo.state(tmp)))


class RepositoryTests(unittest.TestCase):
    def test_old_integration_kit_is_gone(self):
        self.assertFalse((ROOT / 'integration').exists())
        self.assertFalse((ROOT / '.github' / 'workflows' / 'assemble-053111.yml').exists())
        self.assertNotIn('integration/preview', (ROOT / '.github' / 'workflows' / 'tests.yml').read_text())


class Ed25519Tests(unittest.TestCase):
    def test_rfc8032_vector_and_non_canonical_point(self):
        import ed25519_lite as e
        sk = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
        pk = e.public_key(sk)
        self.assertEqual(pk.hex(), 'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
        sig = e.sign(sk, b'')
        self.assertTrue(e.verify(pk, b'', sig))
        # y = p + 1 encodes the same point as y = 1 (the neutral element) but is not canonical
        self.assertIsNone(e._decompress((e.P + 1).to_bytes(32, 'little')))
        self.assertIsNotNone(e._decompress((1).to_bytes(32, 'little')))


if __name__ == '__main__':
    unittest.main()
