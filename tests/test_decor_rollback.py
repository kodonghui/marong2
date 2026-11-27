"""Exercise the reviewed decor file rollback with synthetic files only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('decor_rollback', ROOT / 'deploy/decor-rollback.py')
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


def sha(content):
    return hashlib.sha256(content).hexdigest()


class DecorRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        self.config = self.root / 'diary-features.conf'
        self.release = self.root / 'release'
        self.release.mkdir(mode=0o700)
        self.stage = self.release / 'stage'
        self.stage.mkdir(mode=0o700)
        self.existing = self.app / 'existing.js'
        self.existing.write_bytes(b'before')
        self.existing.chmod(0o640)
        self.new = self.app / 'new.js'
        self.before_config = b'MARONG_DECOR=0\nOTHER_SETTING=synthetic\n'
        self.after_config = b'MARONG_DECOR=1\nOTHER_SETTING=synthetic\n'
        self.config.write_bytes(self.before_config)
        self.config.chmod(0o600)
        self.entries = []
        for index, (target, candidate, before) in enumerate([
            (self.existing, b'after', sha(b'before')),
            (self.new, b'new-content', None),
            (self.config, self.after_config, sha(self.before_config)),
        ]):
            staged = self.stage / str(index)
            staged.write_bytes(candidate)
            staged.chmod(0o644)
            entry = {'path': str(target), 'candidate': str(staged), 'expected_before': before}
            if target != self.config:
                if before is None:
                    entry['main_baseline'] = None
                else:
                    baseline = self.stage / ('base-' + str(index))
                    baseline.write_bytes(target.read_bytes())
                    entry['main_baseline'] = str(baseline)
            self.entries.append(entry)
        self.manifest = self.release / 'targets.json'
        self.manifest.write_text(json.dumps({'files': self.entries}))
        self.snapshot = self.release / 'snapshot'

    def prepare(self):
        rollback.prepare(self.manifest, self.snapshot, self.app, self.config)

    def test_partial_deployment_restores_only_listed_files_and_metadata(self):
        self.prepare()
        self.existing.write_bytes(b'after')
        self.existing.chmod(0o600)
        self.new.write_bytes(b'new-content')
        untouched = self.app / 'unrelated.js'
        untouched.write_bytes(b'unrelated')
        rollback.restore(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'before')
        self.assertEqual(self.existing.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.config.read_bytes(), self.before_config)
        self.assertEqual(untouched.read_bytes(), b'unrelated')
        rollback.restore(self.snapshot, self.app, self.config)

    def test_apply_then_restore_preserves_before_bytes_and_modes(self):
        self.prepare()
        rollback.apply(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'after')
        self.assertEqual(self.new.read_bytes(), b'new-content')
        self.assertEqual(self.config.read_bytes(), self.after_config)
        rollback.restore(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'before')
        self.assertEqual(self.existing.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.config.read_bytes(), self.before_config)

    def test_changed_candidate_stops_before_any_write(self):
        self.prepare()
        (self.stage / '1').write_bytes(b'changed-candidate')
        with self.assertRaisesRegex(ValueError, 'candidate changed'):
            rollback.apply(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'before')
        self.assertFalse(self.new.exists())
        self.assertEqual(self.config.read_bytes(), self.before_config)

    def test_external_change_stops_before_any_restore(self):
        self.prepare()
        self.existing.write_bytes(b'after')
        self.config.write_bytes(b'unexpected-change')
        with self.assertRaisesRegex(ValueError, 'changed outside'):
            rollback.restore(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'after')
        self.assertEqual(self.config.read_bytes(), b'unexpected-change')

    def test_tampered_backup_stops_before_any_restore(self):
        self.prepare()
        self.existing.write_bytes(b'after')
        (self.snapshot / '0000').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'backup copy'):
            rollback.restore(self.snapshot, self.app, self.config)
        self.assertEqual(self.existing.read_bytes(), b'after')

    def test_preflight_drift_and_symlink_are_refused(self):
        self.existing.write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'preflight'):
            self.prepare()
        self.assertFalse(self.snapshot.exists())
        self.existing.unlink()
        self.existing.symlink_to(self.config)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.prepare()
        self.assertFalse(self.snapshot.exists())

    def test_server_file_differing_from_main_and_release_is_refused(self):
        self.existing.write_bytes(b'different-server')
        self.entries[0]['expected_before'] = sha(b'different-server')
        self.manifest.write_text(json.dumps({'files': self.entries}))
        with self.assertRaisesRegex(ValueError, 'differs from both'):
            self.prepare()
        self.assertFalse(self.snapshot.exists())

    def test_extended_attributes_stop_before_any_backup(self):
        os.setxattr(self.existing, 'user.decor-test', b'synthetic')
        with self.assertRaisesRegex(ValueError, 'attributes or ACLs'):
            self.prepare()
        self.assertFalse(self.snapshot.exists())

    def test_config_candidate_cannot_change_other_settings(self):
        (self.stage / '2').write_bytes(b'MARONG_DECOR=1\nOTHER_SETTING=changed\n')
        with self.assertRaisesRegex(ValueError, 'more than decor'):
            self.prepare()
        self.assertFalse(self.snapshot.exists())

    def test_manifest_covers_changes_and_decor_config(self):
        self.manifest.unlink()
        (self.app / 'marong').mkdir()
        (self.app / 'marong' / 'example.py').write_bytes(b'before')
        for tree, content in [('base', b'before'), ('release', b'after')]:
            destination = self.stage / tree / 'marong'
            destination.mkdir(parents=True)
            (destination / 'example.py').write_bytes(content)
        (self.stage / 'diary-features.conf').write_bytes(self.after_config)
        changes = self.release / 'changes.tsv'
        changes.write_text('M\tmarong/example.py\n')
        rollback.make_manifest(self.release, changes, self.app, self.config)
        result = json.loads((self.release / 'targets.json').read_text())['files']
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['expected_before'], sha(b'before'))
        self.assertEqual(result[1]['expected_before'], sha(self.before_config))
        self.assertEqual((self.release / 'targets.json').stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            rollback.make_manifest(self.release, changes, self.app, self.config)

    def test_manifest_refuses_deleted_or_outside_files(self):
        self.manifest.unlink()
        changes = self.release / 'changes.tsv'
        for text in ('D\tmarong/old.py\n', 'M\tmarong/../../other\n', 'M\ttools/secret\n'):
            changes.write_text(text)
            with self.assertRaises(ValueError):
                rollback.make_manifest(self.release, changes, self.app, self.config)
        self.assertFalse((self.release / 'targets.json').exists())

    def test_database_backup_is_private_and_checked_without_restoring(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            rollback.verify_dump(self.release)
        dump = self.release / 'db-before.dump'
        checksum = self.release / 'db-before.sha256'
        dump.write_bytes(b'synthetic-dump')
        dump.chmod(0o600)
        checksum.write_text(sha(b'synthetic-dump') + '  db-before.dump\n')
        with patch.object(rollback.subprocess, 'run') as run:
            run.return_value.returncode = 0
            rollback.verify_dump(self.release)
            self.assertEqual(run.call_args.args[0][:2], ['pg_restore', '--list'])
            run.return_value.returncode = 1
            with self.assertRaisesRegex(ValueError, 'listing'):
                rollback.verify_dump(self.release)
        dump.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            rollback.verify_dump(self.release)


if __name__ == '__main__':
    unittest.main()
