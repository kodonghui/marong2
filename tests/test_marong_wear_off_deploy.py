"""Exercise the approved switch-off deployment and rollback with synthetic files."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wear_release',ROOT/'deploy/marong-wear-off.py')
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseTests(unittest.TestCase):
    def test_switch_check_uses_process_or_failed_service_sources(self):
        with patch.object(release.subprocess,'check_output',return_value='123'), patch.object(Path,'read_bytes',return_value=b'MARONG_DEFAULT_WEAR=0\0'):
            release.ensure_switch_off()
        with patch.object(release.subprocess,'check_output',return_value='123'), patch.object(Path,'read_bytes',return_value=b'MARONG_DEFAULT_WEAR=1\0'):
            with self.assertRaises(ValueError): release.ensure_switch_off()
        properties='Environment=OTHER=hidden\nEnvironmentFiles=/fixture (ignore_errors=no)\n'
        with patch.object(release.subprocess,'check_output',side_effect=['0',properties]), patch.object(Path,'read_text',return_value='OTHER=hidden\n'):
            release.ensure_switch_off()
        with patch.object(release.subprocess,'check_output',side_effect=['0',properties]), patch.object(Path,'read_text',return_value='MARONG_DEFAULT_WEAR=1\n'):
            with self.assertRaises(ValueError): release.ensure_switch_off()

    def test_rollback_requires_no_default_work(self):
        with patch.object(release.subprocess,'check_output',return_value='0\n'): release.ensure_drained()
        with patch.object(release.subprocess,'check_output',return_value='1\n'):
            with self.assertRaises(ValueError): release.ensure_drained()

    def test_backup_apply_restore_without_changing_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); app=root/'app'; app.mkdir(); (app/'marong').mkdir()
            existing=app/'marong'/'old.py'; existing.write_bytes(b'before'); existing.chmod(0o640)
            other=app/'marong'/'other.py'; other.write_bytes(b'untouched')
            target_new=app/'marong'/'new.py'
            work=root/'release'; work.mkdir(mode=0o700)
            for part in ('base/marong','release/marong'): (work/'stage'/part).mkdir(parents=True)
            (work/'stage/base/marong/old.py').write_bytes(b'before')
            (work/'stage/release/marong/old.py').write_bytes(b'after')
            (work/'stage/release/marong/new.py').write_bytes(b'new')
            (work/'stage/release/marong/old.py').chmod(0o644)
            (work/'stage/release/marong/new.py').chmod(0o644)
            rows=[{'path':'marong/old.py','before':sha(b'before'),'after':sha(b'after')},
                  {'path':'marong/new.py','before':None,'after':sha(b'new')}]
            (work/'stage/manifest.json').write_text(json.dumps(rows))
            with patch.object(release,'RELEASE',work), patch.object(release,'APP',app), patch.object(release,'NO_CONFIG',root/'none'), patch.object(release.rb,'verify_dump'):
                release.prepare()
                release.rb.apply(work/'files',app=app,config=root/'none')
                self.assertEqual((existing.read_bytes(),target_new.read_bytes()),(b'after',b'new'))
                release.rb.restore(work/'files',app=app,config=root/'none')
                self.assertEqual(existing.read_bytes(),b'before')
                self.assertEqual(existing.stat().st_mode&0o777,0o640)
                self.assertFalse(target_new.exists())
                self.assertEqual(other.read_bytes(),b'untouched')


if __name__ == '__main__':
    unittest.main()
