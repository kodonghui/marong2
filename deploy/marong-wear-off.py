#!/usr/bin/env python3
"""Deploy/restore the approved switch-off app files; leave database rows and settings intact."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

RELEASE = Path(__file__).resolve().parent
EXPECTED_RELEASE = Path('/home/opc/marong-deploy/20261128-marong-wear-off')
APP = Path('/opt/marong-app')
NO_CONFIG = Path('/nonexistent-marong-wear-config')
spec = importlib.util.spec_from_file_location('decor_rollback', RELEASE / 'decor-rollback.py')
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)


def ensure_switch_off():
    pid = int(subprocess.check_output(['systemctl','show','marong-app.service','-p','MainPID','--value'],text=True))
    if pid > 1:
        entries = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
        values = [entry.partition(b'=')[2] for entry in entries if entry.startswith(b'MARONG_DEFAULT_WEAR=')]
        if values not in ([], [b'0']):
            raise ValueError('default wear is not off')
        return
    # A failed app has no process environment; inspect only the target switch in unit sources.
    props = subprocess.check_output(['systemctl','show','marong-app.service','-p','Environment','-p','EnvironmentFiles'],text=True)
    for line in props.splitlines():
        if line.startswith('Environment='):
            for token in shlex.split(line.partition('=')[2]):
                if token.startswith('MARONG_DEFAULT_WEAR=') and token != 'MARONG_DEFAULT_WEAR=0':
                    raise ValueError('default wear source is not off')
        elif line.startswith('EnvironmentFiles='):
            name = line.partition('=')[2].split(' (ignore_errors=',1)[0]
            for raw in Path(name).read_text().splitlines():
                match = re.match(r'^\s*(?:export\s+)?MARONG_DEFAULT_WEAR\s*=(.*)$',raw)
                if match and shlex.split(match.group(1),comments=True) != ['0']:
                    raise ValueError('default wear source is not off')


def ensure_drained():
    sql = """SELECT (SELECT count(*) FROM marong.outfit_firsts WHERE character_id IS NULL AND state='waiting') +
        (SELECT count(*) FROM marong.scene_pictures WHERE character_id IS NULL AND state IN ('queued','drawing'))"""
    out = subprocess.check_output(['runuser','-u','postgres','--','psql','-X','-A','-t','-v','ON_ERROR_STOP=1','-d','marong','-c',sql],text=True).strip()
    if out != '0':
        raise ValueError('default reaction or drawing work is not drained')


def prepare():
    rb.verify_dump(RELEASE)
    rows = json.loads((RELEASE / 'stage' / 'manifest.json').read_text())
    entries = []
    for row in rows:
        path = row['path']
        if not re.fullmatch(r'(?:marong/[A-Za-z0-9_./-]+|run_app\.py)',path) or '..' in Path(path).parts:
            raise ValueError('unsafe path')
        target = APP / path
        candidate = RELEASE / 'stage' / 'release' / path
        base = RELEASE / 'stage' / 'base' / path if row['before'] is not None else None
        if rb.digest(candidate) != row['after'] or (base is not None and rb.digest(base) != row['before']):
            raise ValueError('staged source mismatch')
        entries.append({'path':str(target),'candidate':str(candidate),'expected_before':row['before'],
                        'main_baseline':str(base) if base else None})
    manifest = RELEASE / 'targets.json'
    fd = os.open(manifest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'files':entries},stream)
        stream.flush(); os.fsync(stream.fileno())
    rb.prepare(manifest,RELEASE/'files',app=APP,config=NO_CONFIG)
    print('file backup verified:',len(rb.validate(RELEASE/'files',app=APP,config=NO_CONFIG)))


def main():
    if (os.geteuid() != 0 or RELEASE != EXPECTED_RELEASE or RELEASE.is_symlink() or not RELEASE.is_dir()
            or RELEASE.stat().st_uid != 0 or RELEASE.stat().st_mode & 0o077):
        raise ValueError('release directory is not private root context')
    mode = sys.argv[1] if len(sys.argv)==2 else ''
    if mode == 'prepare':
        prepare()
    elif mode == 'apply':
        ensure_switch_off(); rb.verify_dump(RELEASE)
        rb.apply(RELEASE/'files',app=APP,config=NO_CONFIG)
    elif mode == 'rollback':
        ensure_switch_off(); ensure_drained()
        rb.restore(RELEASE/'files',app=APP,config=NO_CONFIG)
    else:
        raise ValueError('invalid operation')


if __name__ == '__main__':
    try:
        main()
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print('STOP:',type(error).__name__,str(error))
        raise SystemExit(2)
