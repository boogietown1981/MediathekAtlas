import unittest
from unittest.mock import patch
from types import SimpleNamespace
import downloads

class TransferTests(unittest.TestCase):
    def test_space_checks_target_and_rejects_shortage(self):
        with patch('downloads.shutil.disk_usage',return_value=SimpleNamespace(free=100)) as usage:
            self.assertEqual(downloads.require_space('/target',100),100)
            with self.assertRaisesRegex(ValueError,'Speicher'):
                downloads.require_space('/target',101)
            usage.assert_called_with('/target')

    def test_measured_tracks_do_not_invent_language(self):
        result=downloads.quality_summary({'streams':[
            {'codec_type':'video','codec_name':'h264','width':1920,'height':1080},
            {'codec_type':'audio','codec_name':'aac','channels':2},
            {'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'deu'}},
            {'codec_type':'attachment'}]})
        self.assertEqual(len(result),3)
        self.assertEqual(result[0]['height'],1080)
        self.assertIsNone(result[1]['language'])
        self.assertEqual(result[2]['language'],'deu')
