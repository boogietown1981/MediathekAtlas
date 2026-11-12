"""0.5.35: deterministic QPKG payload check (qbuild --extract copies via dd from a pipe)."""
import gzip
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_nas  # noqa: E402


class QpkgPayloadTests(unittest.TestCase):
    def test_payload_cut_by_header_offsets(self):
        payload = gzip.compress(b'x' * 5000)
        script = ('#!/bin/sh\nscript_len=%d\n'
                  'offset=$(/usr/bin/expr $script_len + 20480)\n'
                  "[ -f /usr/local/bin/python ] && /usr/local/bin/python -c \"with open('d', 'rw+') as f: f.seek(%d); f.truncate()\"\n"
                  'exit 1\n')
        size = 0
        for _ in range(3):  # script_len includes its own digits
            size = len(script % (size, len(payload)))
        body = (script % (size, len(payload))).encode()
        self.assertEqual(len(body), size)
        data = body + b'\0' * 20480 + payload + b'footer QNAPQPKG'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.qpkg'
            path.write_bytes(data)
            self.assertEqual(build_nas.qpkg_data(path), payload)
            path.write_bytes(data[:len(body) + 20480 + 10])
            with self.assertRaises(SystemExit):
                build_nas.qpkg_data(path)


if __name__ == '__main__':
    unittest.main()
