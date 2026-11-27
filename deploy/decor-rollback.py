#!/usr/bin/env python3
"""Prepare and restore only a reviewed decor deployment's files; never modify the DB.

Production use requires a root-only release directory.  See
`docs/12-qa/decor-enable-plan.md` for the manifest, preflight and restart steps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

APP = Path('/opt/marong-app')
CONFIG = Path('/etc/marong-app/diary-features.conf')
RELATIVE = re.compile(r'(?:marong/[A-Za-z0-9_./-]+|run_app\.py)\Z')


def fail(message):
    raise ValueError(message)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def require_no_xattrs(path):
    if os.listxattr(path):
        fail('extended attributes or ACLs need a separate recovery plan')


def sync_file(path):
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checked(path, app, config):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        fail('invalid target path')
    if path != config and app not in path.parents:
        fail('target outside the approved app and decor config')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            fail('symlink in target path')
    return path


def load(snapshot):
    snapshot = Path(snapshot)
    if snapshot.is_symlink() or not snapshot.is_dir():
        fail('snapshot missing or unsafe')
    meta = snapshot.stat()
    if meta.st_mode & 0o077:
        fail('snapshot directory must be private')
    return json.loads((snapshot / 'manifest.json').read_text())


def verify_dump(release):
    release = Path(release)
    dump, checksum = release / 'db-before.dump', release / 'db-before.sha256'
    if dump.is_symlink() or checksum.is_symlink() or not dump.is_file() or not checksum.is_file() or dump.stat().st_size == 0:
        fail('database backup missing or unsafe')
    if dump.stat().st_mode & 0o077:
        fail('database backup must be private')
    fields = checksum.read_text().split()
    if not fields or not re.fullmatch(r'[0-9a-f]{64}', fields[0]) or digest(dump) != fields[0]:
        fail('database backup checksum failed')
    result = subprocess.run(['pg_restore', '--list', str(dump)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        fail('database backup listing failed')


def make_manifest(release, changes, app=APP, config=CONFIG):
    release = Path(release)
    if release.is_symlink() or not release.is_dir() or release.stat().st_mode & 0o077:
        fail('release directory must be private')
    entries = []
    seen = set()
    for line in Path(changes).read_text().splitlines():
        parts = line.split('\t')
        if len(parts) != 2 or parts[0] not in ('A', 'M') or not RELATIVE.fullmatch(parts[1]):
            fail('unsupported change; inspect the release diff')
        status, relative = parts
        if '..' in Path(relative).parts or relative in seen:
            fail('unsafe or duplicate release path')
        seen.add(relative)
        target = checked(app / relative, app, config)
        candidate = release / 'stage' / 'release' / relative
        base = release / 'stage' / 'base' / relative if status == 'M' else None
        entries.append({'path': str(target), 'candidate': str(candidate),
                        'main_baseline': str(base) if base else None,
                        'expected_before': digest(target) if target.exists() else None})
    if not entries:
        fail('empty release diff')
    config = checked(config, app, config)
    if not config.is_file():
        fail('decor config is missing')
    entries.append({'path': str(config), 'candidate': str(release / 'stage' / 'diary-features.conf'),
                    'expected_before': digest(config)})
    output = release / 'targets.json'
    with output.open('x') as stream:
        os.chmod(output, 0o600)
        json.dump({'files': entries}, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(release)
    print('manifest prepared:', len(entries), 'files')


def prepare(spec, snapshot, app=APP, config=CONFIG):
    snapshot = Path(snapshot)
    if snapshot.exists() or snapshot.is_symlink():
        fail('snapshot already exists')
    parent = snapshot.parent.resolve(strict=True)
    if parent.stat().st_mode & 0o077:
        fail('release directory must be private')
    spec = json.loads(Path(spec).read_text())
    files = spec.get('files')
    if not isinstance(files, list) or not files:
        fail('empty file manifest')
    staged = []
    seen = set()
    for entry in files:
        target = checked(entry['path'], app, config)
        if str(target) in seen:
            fail('duplicate target')
        seen.add(str(target))
        candidate = Path(entry['candidate'])
        if candidate.is_symlink() or not candidate.is_file():
            fail('candidate missing or unsafe')
        require_no_xattrs(candidate)
        resolved = candidate.resolve(strict=True)
        if parent not in resolved.parents:
            fail('candidate outside release directory')
        if target.exists() and not target.is_file():
            fail('target is not a regular file')
        if target.exists():
            require_no_xattrs(target)
        if not target.parent.is_dir():
            fail('target parent is missing')
        before = digest(target) if target.exists() else None
        if 'expected_before' not in entry or before != entry['expected_before']:
            fail('target changed since preflight')
        if target == config:
            lines = target.read_bytes().splitlines(keepends=True)
            matches = [i for i, line in enumerate(lines) if re.match(rb'^\s*(?:export\s+)?MARONG_DECOR\s*=', line)]
            if len(matches) != 1 or lines[matches[0]].strip() != b'MARONG_DECOR=0':
                fail('decor config source changed')
            lines[matches[0]] = lines[matches[0]].replace(b'MARONG_DECOR=0', b'MARONG_DECOR=1', 1)
            if resolved.read_bytes() != b''.join(lines):
                fail('config candidate changes more than decor')
        if target != config:
            if 'main_baseline' not in entry:
                fail('main baseline is missing')
            main_baseline = entry['main_baseline']
            if main_baseline is not None:
                main_baseline = Path(main_baseline)
                if main_baseline.is_symlink() or not main_baseline.is_file() or parent not in main_baseline.resolve(strict=True).parents:
                    fail('main baseline missing or unsafe')
                main_baseline = digest(main_baseline)
            if before not in (main_baseline, digest(resolved)):
                fail('target differs from both main baseline and release; stop')
        old_stat = target.stat() if target.exists() else None
        staged.append((target, resolved, before, old_stat))
    snapshot.mkdir(mode=0o700)
    records = []
    for index, (target, candidate, before, old_stat) in enumerate(staged):
        name = f'{index:04d}'
        if before is not None:
            shutil.copy2(target, snapshot / name)
            sync_file(snapshot / name)
            if digest(snapshot / name) != before:
                fail('backup copy failed verification')
            latest = target.stat()
            if (digest(target), latest.st_uid, latest.st_gid, stat.S_IMODE(latest.st_mode)) != (before, old_stat.st_uid, old_stat.st_gid, stat.S_IMODE(old_stat.st_mode)):
                fail('target changed during backup')
        records.append({'path': str(target), 'candidate': str(candidate), 'before': before, 'after': digest(candidate), 'backup': name,
                        'uid': old_stat.st_uid if old_stat else None, 'gid': old_stat.st_gid if old_stat else None,
                        'mode': stat.S_IMODE(old_stat.st_mode) if old_stat else None})
    manifest = snapshot / 'manifest.json'
    manifest.write_text(json.dumps({'files': records}, ensure_ascii=True, indent=2) + '\n')
    manifest.chmod(0o600)
    sync_file(manifest)
    sync_dir(snapshot)
    sync_dir(snapshot.parent)
    print('snapshot prepared:', len(records), 'files')


def validate(snapshot, app=APP, config=CONFIG):
    snapshot = Path(snapshot)
    data = load(snapshot)
    records = data.get('files')
    if not isinstance(records, list) or not records:
        fail('empty saved manifest')
    for index, entry in enumerate(records):
        target = checked(entry['path'], app, config)
        if entry['backup'] != f'{index:04d}':
            fail('unsafe backup name')
        saved = snapshot / entry['backup']
        if entry['before'] is not None and (saved.is_symlink() or not saved.is_file() or digest(saved) != entry['before']):
            fail('backup copy failed verification')
        if target.exists() and not target.is_file():
            fail('target is not a regular file')
        if target.exists():
            require_no_xattrs(target)
        current = digest(target) if target.exists() else None
        if current not in (entry['before'], entry['after']):
            fail('target changed outside this release; stop before restoring')
    return records


def apply(snapshot, app=APP, config=CONFIG):
    snapshot = Path(snapshot)
    records = validate(snapshot, app, config)
    metadata = []
    for entry in records:
        candidate = Path(entry['candidate'])
        if candidate.is_symlink() or not candidate.is_file() or snapshot.parent.resolve() not in candidate.resolve().parents:
            fail('candidate missing or unsafe')
        require_no_xattrs(candidate)
        if digest(candidate) != entry['after']:
            fail('candidate changed since snapshot')
        target = checked(entry['path'], app, config)
        parent = target.parent.stat()
        uid = entry['uid'] if entry['before'] is not None else parent.st_uid
        gid = entry['gid'] if entry['before'] is not None else parent.st_gid
        mode = entry['mode'] if entry['before'] is not None else stat.S_IMODE(candidate.stat().st_mode)
        if mode & 0o022:
            fail('candidate mode permits group or other writes')
        metadata.append((uid, gid, mode))
    for entry, (uid, gid, mode) in zip(records, metadata):
        target = checked(entry['path'], app, config)
        current = digest(target) if target.exists() else None
        if current == entry['after']:
            continue
        if current != entry['before']:
            fail('target changed during apply')
        fd, temp_name = tempfile.mkstemp(prefix='.decor-apply-', dir=target.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            shutil.copy2(entry['candidate'], temp)
            require_no_xattrs(temp)
            os.chown(temp, uid, gid)
            os.chmod(temp, mode)
            sync_file(temp)
            os.replace(temp, target)
            sync_dir(target.parent)
        finally:
            if temp.exists():
                temp.unlink()
    for entry in records:
        target = checked(entry['path'], app, config)
        if not target.is_file() or digest(target) != entry['after']:
            fail('apply verification failed')
    print('apply verified:', len(records), 'files; database untouched')


def restore(snapshot, app=APP, config=CONFIG):
    snapshot = Path(snapshot)
    records = validate(snapshot, app, config)  # Validate every file before changing any.
    for entry in records:
        target = checked(entry['path'], app, config)
        current = digest(target) if target.exists() else None
        if current == entry['before']:
            if current is None:
                continue
            meta = target.stat()
            if (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) == (entry['uid'], entry['gid'], entry['mode']):
                continue
        elif current != entry['after']:
            fail('target changed during restore')
        if entry['before'] is None:
            target.unlink()  # Only a file from this release whose hash still matches.
            sync_dir(target.parent)
            continue
        fd, temp_name = tempfile.mkstemp(prefix='.decor-restore-', dir=target.parent)
        os.close(fd)
        temp = Path(temp_name)
        try:
            shutil.copy2(snapshot / entry['backup'], temp)
            require_no_xattrs(temp)
            os.chown(temp, entry['uid'], entry['gid'])
            os.chmod(temp, entry['mode'])
            sync_file(temp)
            os.replace(temp, target)
            sync_dir(target.parent)
        finally:
            if temp.exists():
                temp.unlink()
    for entry in records:
        target = checked(entry['path'], app, config)
        if (digest(target) if target.exists() else None) != entry['before']:
            fail('restore verification failed')
        if entry['before'] is not None:
            meta = target.stat()
            if (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) != (entry['uid'], entry['gid'], entry['mode']):
                fail('restored metadata mismatch')
    print('restore verified:', len(records), 'files; database untouched')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['manifest', 'prepare', 'check', 'apply', 'rollback'])
    parser.add_argument('snapshot')
    parser.add_argument('--manifest')
    parser.add_argument('--changes')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        fail('run as root')
    release = Path(args.snapshot) if args.mode == 'manifest' else Path(args.snapshot).parent
    if release.stat().st_uid != 0:
        fail('release directory must be owned by root')
    if args.mode == 'manifest':
        if not args.changes:
            fail('manifest requires --changes')
        make_manifest(args.snapshot, args.changes)
    elif args.mode == 'prepare':
        if not args.manifest:
            fail('prepare requires --manifest')
        verify_dump(release)
        prepare(args.manifest, args.snapshot)
    elif args.mode == 'check':
        print('snapshot valid:', len(validate(args.snapshot)), 'files')
    elif args.mode == 'apply':
        if not args.execute:
            fail('apply requires --execute')
        verify_dump(release)
        apply(args.snapshot)
    else:
        if not args.execute:
            fail('rollback requires --execute')
        restore(args.snapshot)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print('STOP:', type(error).__name__, str(error))
        raise SystemExit(2)
