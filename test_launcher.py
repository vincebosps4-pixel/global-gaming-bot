import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from instance_lock import InstanceLock
from launcher import Supervisor, checked_files, version_tuple


def archive(extra=None):
    files={name:b'' for name in ('bot.py','community.py','storage.py','instance_lock.py','requirements.txt','test_bot.py','test_community.py','test_launcher.py')}
    files['VERSION']=b'1.0.0'
    if extra:
        files.update(extra)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        for name,raw in files.items():
            z.writestr(name,raw)
    raw=buf.getvalue()
    return raw,hashlib.sha256(raw).hexdigest()


class UpdateTests(unittest.TestCase):
    def test_valid_package_and_version(self):
        raw,digest=archive()
        self.assertIn('bot.py',checked_files(raw,digest,'1.0.0'))
        self.assertGreater(version_tuple('1.10.0'),version_tuple('1.9.0'))

    def test_rejects_secret_overwrite_traversal_and_unexpected_files(self):
        for name in ('../config/token.txt','config/token.txt','data/community.sqlite3','C:/evil.py','unexpected.py'):
            with self.subTest(name=name):
                raw,digest=archive({name:b'x'})
                with self.assertRaises(ValueError):
                    checked_files(raw,digest,'1.0.0')

    def test_rejects_hash_and_version_mismatch(self):
        raw,digest=archive()
        for h,v in [('0'*64,'1.0.0'),(digest,'1.0.1')]:
            with self.assertRaises(ValueError):
                checked_files(raw,h,v)

    def test_duplicate_and_oversized_entries_rejected(self):
        raw,digest=archive({'README.md':b'x'*(1024*1024+1)})
        with self.assertRaises(ValueError):
            checked_files(raw,digest,'1.0.0')

    def test_two_instances_cannot_share_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'lock'
            first=InstanceLock(path)
            try:
                with self.assertRaises(RuntimeError):
                    InstanceLock(path)
            finally:
                first.close()
            second=InstanceLock(path)
            second.close()

    def test_install_failure_keeps_current_process_and_version(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Supervisor(temp)
            s.state['current']='1.0.0'
            s.prepare=Mock(side_effect=ValueError('failed validation'))
            s.stop=Mock()
            with self.assertRaises(ValueError):
                s.activate('1.1.0',{})
            s.stop.assert_not_called()
            self.assertEqual(s.state['current'],'1.0.0')

    def test_rollback_preserves_data_and_blocks_failed_release(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Supervisor(temp)
            data=s.data/'community.sqlite3'
            data.write_bytes(b'untouched')
            s.state.update(current='1.1.0',previous='1.0.0')
            s.stop=Mock()
            s.start=Mock()
            self.assertTrue(s.rollback())
            self.assertEqual(s.state['current'],'1.0.0')
            self.assertIn('1.1.0',s.state['failed'])
            self.assertEqual(data.read_bytes(),b'untouched')

    def test_download_links_must_match_pinned_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Supervisor(temp)
            release={'tag_name':'v1.1.0','assets':[{'name':'global-gaming-bot.zip','browser_download_url':'https://example.com/bad.zip'}]}
            with patch('launcher.download',return_value=json.dumps(release).encode()):
                with self.assertRaises(ValueError):
                    s.latest()


if __name__=='__main__':
    unittest.main()
