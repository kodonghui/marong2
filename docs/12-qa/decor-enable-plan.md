# 꾸미기 켜기 전 준비·복구 초안

2026-11-27 PR #141 리뷰 대응 초안이에요. **이번 작업에서 운영을 켜거나 배포하지 않아요.** PR 병합과 운영 변경은 별도 사용자님 승인 뒤에만 하고, 아래 명령은 그때 담당자가 조건을 다시 확인한 뒤 실행해요. 서버의 비밀 설정과 DB 백업 내용은 출력·PR·작업공간에 복사하지 않아요.

## 켜기 전 중단 조건

- TC-556과 TASK-443을 따라 꾸미기 스위치의 TC-538~555를 켜기 전에 확인해요. TC-543의 승인된 합성 API·화면 조건은 켜기 전에 모두 통과해야 해요. 실제 Access 관리자 이미지 확인은 운영 꾸미기가 꺼져 있으면 404이므로 켠 직후 운영 점검에서 따로 해요. TC-553은 승인 시험의 Playwright 터치 흉내를 켜기 전에 통과시켜요. D191에 따라 꾸미기는 친구 모두에게 한 번에 켜지고, TC-558의 아이폰·갤럭시 실기기 확인은 켠 뒤 실시해요. 격리 실기기 사전 확인은 추가 조치이며 필수 선행 조건으로 단정하지 않아요.
- TC-556에 따라 각 스위치에 해당하는 선행 시험을 확인해요. TC-537은 장면 스위치의 조건이고 강아지·고양이 각 2장 중 각 1장만 확인한 기록이므로 일부 확인이에요. 이미 켜진 장면 기능의 범위와 이 불일치는 별도로 판단하며, 이 기록만을 꾸미기의 독립 선행 조건으로 추가하지 않아요.
- TC-453·522는 1인칭 스위치의 조건이에요. TC-453의 초기 실패 뒤 PR #66의 `0c1ac30`에서 음성·글 각각 15/15 통과했고 `aa3f2f4`가 반영된 기록을 확인했어요. 이력상의 오래된 실패만으로 꾸미기를 중단하지 않으며, 현재 적용 버전·후속 변경에 의문이 있으면 운영 결정 전에 해결해요. 이미 켜진 다른 스위치의 현 상태를 이번 승인으로 바꾸지 않아요.
- PR #141의 리뷰·검사와 사용자님 병합 승인을 받고, 병합된 실제 main 커밋과 바로 전 main을 확정해요. 릴리스에 필요한 업데이트 내역 파일을 준비해 변경 목록에 넣어요. 현재 PR에는 CI 결과가 없으므로 이를 해결하기 전에는 준비 완료로 보지 않아요. 실제 Access 이미지 점검은 켠 직후 실행해요.
- 운영 서비스 설정 우선순위와 `/opt/marong-app` 파일의 해시, 022 표·제약, 백업 공간, 카탈로그 유효성·라이선스, 현재 행 수를 읽기 전용으로 다시 확인해요. 11/27 읽기에서는 환경 파일 7개 중 6번째 `/etc/marong-app/diary-features.conf` 한 곳에만 꾸미기 값이 있었고, unit `Environment`에는 없었어요. 이것은 당시 관찰일 뿐 다음 실행의 전제가 아니에요.
- `systemctl show marong-app.service -p FragmentPath -p DropInPaths -p EnvironmentFiles`로 unit·drop-in과 환경 파일의 순서를 다시 확인해요. `EnvironmentFile`은 unit의 `Environment`보다 우선하며 뒤에 읽는 환경 파일이 앞의 값을 덮어요. 각 파일은 관리자 권한의 로컬 검사로 `MARONG_DECOR`의 **정의 여부와 승자만** 확인하고 값이나 다른 설정을 화면·기록에 내지 않아요. 다른 파일에도 설정이 있거나 승자가 예상과 다르면 **중단**하고 그 실제 파일까지 백업·후보·복구 범위를 다시 정해요. 아래 스크립트는 현재 관찰된 diary 설정 한 파일만 바꾸도록 제한돼 있어 다른 파일은 덮지 않아요.
- 대화·통화가 없고 실제 폰 검사의 담당·시점이 정해졌는지 확인해요. 어떤 검사·승인·백업이 실패하거나 결과가 불확실하면 변경하지 않아요.

운영 승인 직전에 실행할 읽기 전용 검사의 예예요. 다른 환경 변수의 값과 파일 내용은 출력하지 않고 파일을 못 읽거나 현재 프로세스가 꺼짐 상태가 아니면 중단해요.

```sh
ssh opc@100.87.95.40 'sudo python3 - disabled' <<'PY'
import pathlib, re, shlex, subprocess, sys
mode = sys.argv[1]
if mode not in ('disabled','enabled','source-only'): raise SystemExit('STOP: invalid check mode')
p = subprocess.run(['systemctl','show','marong-app.service','-p','Environment','-p','EnvironmentFiles','-p','MainPID'],check=True,capture_output=True,text=True)
lines = p.stdout.splitlines()
env = next((s.partition('=')[2] for s in lines if s.startswith('Environment=')), '')
if any(s.split('=',1)[0] == 'MARONG_DECOR' for s in shlex.split(env)): raise SystemExit('STOP: unit environment defines decor')
files = [s.partition('=')[2].split(' (ignore_errors=',1)[0] for s in lines if s.startswith('EnvironmentFiles=')]
defined = []
for file in files:
    with open(file,encoding='utf-8') as stream:
        if any(re.match(r'^\s*(?:export\s+)?MARONG_DECOR\s*=',line) for line in stream): defined.append(file)
if defined != ['/etc/marong-app/diary-features.conf']: raise SystemExit('STOP: decor source changed')
if mode != 'source-only':
    pid = int(next(s.partition('=')[2] for s in lines if s.startswith('MainPID=')))
    if pid <= 1: raise SystemExit('STOP: app is not running')
    values = [s.split(b'=',1)[1] for s in pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if s.startswith(b'MARONG_DECOR=')]
    if values != [{'disabled':b'0','enabled':b'1'}[mode]]: raise SystemExit('STOP: decor state mismatch')
print('decor source and requested state verified')
PY
```

## 백업과 파일 비교

아래 `BASE`는 PR 병합 직전 main 전체 SHA, `RELEASE`는 승인된 병합 커밋 전체 SHA예요. 병합 전에는 값이 정해지지 않으므로 지금 값을 만들어 넣지 않아요. 병합 뒤 Git 이력과 PR에서 두 SHA, `RELEASE^1 == BASE`, RELEASE가 현재 배포할 main인지 확인해요. `git diff --name-status --no-renames "$BASE" "$RELEASE"`에서 실행 대상 파일을 전수 확인하고, `marong/`·`run_app.py` 이외 런타임 파일, 삭제·이름 변경, 심볼릭 링크가 있으면 이 절차를 멈추고 별도 계획을 만들어요. 문서·시험 파일은 서버에 복사하지 않아요.

1. 각 앱 런타임 파일에 대해 운영 파일의 SHA-256을 `BASE`의 같은 파일과 `RELEASE`의 파일에 각각 비교해요. 운영이 BASE와 같으면 RELEASE를 반영하고, 이미 RELEASE와 같으면 그대로 둬요. 둘 다 다르거나 BASE에 없는 파일인데 서버에 다른 파일이 있으면 **중단**해요. 서버의 독자 수정은 덮지 않고 3-way 차이를 검토해 별도의 승인된 결과를 준비해요. 현재 PR의 앱 변경은 `marong/app_admin.py`, `marong/app_decor.py`, `marong/diary_decor.py`, `marong/app_chat_static/`의 관리자 아이템·꾸미기·일기 JS/CSS예요. 실제 배포 목록은 병합 후 diff가 기준이에요.
2. 변경할 앱 파일과 실제 설정 승자 모두를 복구 대상에 넣어요. 이전에 없던 파일도 `before: null`로 기록해 새 파일의 정확한 RELEASE 해시가 남은 경우에만 복구 때 제거해요. 다른 파일이나 DB 행은 삭제하지 않아요. 새 경로의 부모 디렉터리가 없거나 설정 승자가 달라지면 이 스크립트는 중단해요.
3. 서버의 새 전용 경로를 `B=/home/opc/marong-deploy/20261127-decor-141`로 정해요. 아래 4번 서버 명령의 `mkdir`이 root 소유 `0700` 디렉터리를 단 한 번 만들어요. 이미 있으면 멈추고 기존 파일을 건드리지 않아요. 경로를 바꿔 다시 계획한다면 모든 서버·로컬 명령의 `B`와 예시 경로를 일치시켜요.
4. 다음 블록은 **서버 셸**에서 실행해요. 디렉터리 생성 뒤 변경 전 DB를 root만 읽는 `$B/db-before.dump`에 백업하고 읽을 수 있는지 확인해요. 실패하면 설정·코드를 건드리지 않아요. 롤백 스크립트는 뒤의 5번 stage 검증 뒤 설치해요.

```sh
set -eu
B=/home/opc/marong-deploy/20261127-decor-141
sudo mkdir -m 700 "$B"
sudo python3 - "$B" <<'PY'
import shutil, subprocess, sys
size = int(subprocess.check_output(['runuser','-u','postgres','--','psql','-d','marong','-Atqc','SELECT pg_database_size(current_database())'],text=True))
if shutil.disk_usage(sys.argv[1]).free < 2*size + 200*1024*1024: raise SystemExit('STOP: insufficient backup space')
print('backup space verified')
PY
sudo sh -c 'umask 077; runuser -u postgres -- pg_dump -Fc -d marong > "$1"' -- "$B/db-before.dump"
sudo test -s "$B/db-before.dump"
sudo pg_restore --list "$B/db-before.dump" >/dev/null
sudo sh -c 'sha256sum "$1" > "$2"' -- "$B/db-before.dump" "$B/db-before.sha256"
```

`pg_restore --list`는 덤프 목록을 읽는 검사이고 실제 복구 검증은 아니에요. 덤프는 보호된 서버에 보존하고, DB 복원은 별도 판단·승인 없이 실행하지 않아요.

5. 승인된 커밋의 각 RELEASE 파일과 BASE 파일을 `$B/stage/release/<저장소 상대 경로>`, `$B/stage/base/<저장소 상대 경로>`에 준비하고 해시를 원본 커밋과 대조해요. 새 파일은 BASE 파일이 없어요. 병합 후 로컬 저장소에서 다음처럼 두 커밋으로 stage를 만들어요. `BASE`와 `RELEASE`는 위에서 검증한 전체 SHA로 지정해야 하며, 새 임시 폴더만 써요. 이 명령은 Git에서 읽고 로컬 임시 폴더에만 써요.

```sh
LOCAL=/tmp/decor-141-stage
export BASE RELEASE LOCAL
set -eu
test -n "$BASE" && test -n "$RELEASE" && test "$(git rev-parse "$RELEASE^1")" = "$BASE"
python3 - <<'PY'
import hashlib, os, pathlib, re, subprocess
base, release, dst = os.environ['BASE'], os.environ['RELEASE'], pathlib.Path(os.environ['LOCAL'])
if dst.exists(): raise SystemExit('STOP: use a new local stage')
dst.mkdir(mode=0o700)
(dst/'base').mkdir(); (dst/'release').mkdir()
raw = subprocess.check_output(['git','diff','--name-status','--no-renames','-z',base,release])
parts = raw.decode().split('\0'); pairs = list(zip(parts[0::2], parts[1::2])); rows = []
for status, path in pairs:
    if not (path.startswith('marong/') or path == 'run_app.py'):
        if path.startswith(('docs/', 'tests/', 'apps/android/test/', 'deploy/', 'api/')): continue
        raise SystemExit('STOP: another runtime path needs a separate plan')
    if status not in ('A','M') or not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or '..' in pathlib.PurePosixPath(path).parts:
        raise SystemExit('STOP: unsupported change')
    rows.append((status,path))
    for name, ref in [('release',release)] + ([('base',base)] if status == 'M' else []):
        info = subprocess.check_output(['git','ls-tree',ref,'--',path],text=True).split()
        if not info or info[0] not in ('100644','100755'): raise SystemExit('STOP: non-regular file')
        target = dst/name/path; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','show',ref+':'+path]))
        target.chmod(0o755 if info[0]=='100755' else 0o644)
if not rows: raise SystemExit('STOP: empty app diff')
(dst/'changes.tsv').write_text(''.join(status+'\t'+path+'\n' for status,path in rows))
(dst/'rollback.py').write_bytes(subprocess.check_output(['git','show',release+':deploy/decor-rollback.py']))
paths = [p for p in dst.rglob('*') if p.is_file()]
(dst/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(dst).as_posix()+'\n' for p in paths))
print('staged app files:',len(rows))
PY
tar -C "$LOCAL" -cf "$LOCAL/stage.tar" base release changes.tsv rollback.py SHA256SUMS
```

다음 블록은 위 `LOCAL`이 유지된 **로컬 셸**에서 실행해요. `B`는 4번 서버 셸에서 만든 경로와 같아야 해요. 별도 운영 승인을 받은 뒤에만 위 tar와 같은 RELEASE의 `deploy/decor-rollback.py`를 서버의 `$B/stage/`와 `$B/rollback.py`로 옮겨요. `$B/rollback.py`는 root 소유 `0700`, stage는 root 소유 `0700`이고 tar는 소유자를 복원하지 않고 풀어요. SSH는 tar를 표준 입력으로 전송하며, 각 후보와 BASE 파일을 생성 시의 Git blob SHA-256 목록과 대조해요. 불일치면 중단해요.

```sh
set -eu
HOST=opc@100.87.95.40
B=/home/opc/marong-deploy/20261127-decor-141
ssh "$HOST" "sudo mkdir -m 700 '$B/stage'"
ssh "$HOST" "sudo tar -xf - --no-same-owner -C '$B/stage'" < "$LOCAL/stage.tar"
ssh "$HOST" "sudo sh -c 'cd \"$B/stage\" && sha256sum -c SHA256SUMS >/dev/null && install -o root -g root -m 700 rollback.py \"$B/rollback.py\"'"
```

다음 블록부터는 다시 **서버 셸**에서 실행하고 `B=/home/opc/marong-deploy/20261127-decor-141`를 지정해요(4번에서 정한 경로와 같게). 현재 관찰대로 설정 승자가 diary 설정 한 곳이고 `MARONG_DECOR=0` 줄이 정확히 하나일 때만 다음 명령으로 원본 전체를 보존한 후보를 만들어요. 다른 설정·주석·권한은 그대로이며 원본 값은 출력하지 않아요. 조건이 다르면 중단해요.

```sh
B=/home/opc/marong-deploy/20261127-decor-141
sudo python3 - "$B/stage/diary-features.conf" <<'PY'
import os, pathlib, re, sys
raw = pathlib.Path('/etc/marong-app/diary-features.conf').read_bytes()
lines = raw.splitlines(keepends=True)
matches = [i for i,line in enumerate(lines) if re.match(rb'^\s*(?:export\s+)?MARONG_DECOR\s*=',line)]
if len(matches) != 1 or lines[matches[0]].strip() != b'MARONG_DECOR=0': raise SystemExit('STOP: decor source changed')
lines[matches[0]] = lines[matches[0]].replace(b'MARONG_DECOR=0',b'MARONG_DECOR=1',1)
fd = os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as out: out.write(b''.join(lines))
PY
```

6. 다음 명령은 root만 읽는 `$B/targets.json`을 만들어요. `files` 배열에는 위 diff의 **모든** 앱 런타임 경로와 변경할 설정 파일을 각각 한 번 넣어요. 각 항목의 `expected_before`는 바로 직전 운영 파일의 SHA-256(없으면 `null`), `candidate`는 RELEASE 또는 설정 후보의 절대 경로, 앱 항목의 `main_baseline`은 BASE 파일의 절대 경로(새 파일이면 `null`)예요. 해시·설정 내용은 화면에 출력하지 않아요.

```sh
sudo python3 "$B/rollback.py" manifest "$B" --changes "$B/stage/changes.tsv"
```

생성되는 JSON의 모양은 아래와 같아요. 예시의 해시는 설명용 자리 표시이며 실제 파일을 손으로 만들거나 PR에 복사하지 않아요.

```json
{"files": [
  {"path": "/opt/marong-app/marong/app_decor.py", "candidate": "/home/opc/marong-deploy/20261127-decor-141/stage/release/marong/app_decor.py", "main_baseline": "/home/opc/marong-deploy/20261127-decor-141/stage/base/marong/app_decor.py", "expected_before": "<운영 파일의 SHA-256>"},
  {"path": "/etc/marong-app/diary-features.conf", "candidate": "/home/opc/marong-deploy/20261127-decor-141/stage/diary-features.conf", "expected_before": "<운영 설정 파일의 SHA-256>"}
]}
```

설정 후보와 `targets.json`도 root 소유 `0600`, stage는 `0700`으로 제한해요. `expected_before`와 실제 파일이 달라졌거나 앱 파일이 BASE·RELEASE 양쪽과 다르면 아래 `prepare`가 중단해요. 사용자·그룹·모드와 각 파일의 이전 바이트를 `$B/files/`에 저장하고 후보·이전 파일 해시도 고정해요. 심볼릭 링크, 다른 경로, 다른 설정 파일, 부모 디렉터리 누락, 확장 속성이나 ACL이 있는 파일은 거절하고 별도 복구 계획을 세워요.

```sh
sudo python3 "$B/rollback.py" prepare "$B/files" --manifest "$B/targets.json"
sudo python3 "$B/rollback.py" check "$B/files"
```

`prepare`와 `check`가 모두 성공하고 DB 덤프 검사도 성공해야 해요. 체크섬 불일치·변경 감지·공간 부족·권한 오류가 나면 중단하고 백업을 보존해요. 스크립트는 파일을 조작할 뿐 DB를 쓰거나 서비스를 재시작하지 않아요.

## 승인 후 배포·관찰과 실패 복구

1. 사용자님이 실제 운영 반영을 별도 승인했고 위 선행 조건이 모두 통과했는지 다시 확인해요. 맨 위 설정 출처 검사를 `disabled`로 다시 실행해 백업 뒤 우선순위가 바뀌지 않았는지도 확인해요. 안전한 중단 시점에 아래 명령으로 후보 파일을 반영해요. 스크립트는 시작 전 모든 후보 해시와 모든 대상의 이전/릴리스 해시를 검사하고, 각 파일을 임시 파일에서 교체하며 기존 소유자·그룹·모드를 보존해요. 새 파일의 부모 소유자·후보 모드를 사용하고 그룹·타인 쓰기 모드는 거절해요.

```sh
sudo python3 "$B/rollback.py" apply "$B/files" --execute
```

2. 성공하면 대화·통화가 없는 때 재시작 직전 UTC 시각을 기록하고 `sudo systemctl restart marong-app.service`를 실행한 뒤 `systemctl is-active --quiet marong-app.service`로 활성 상태를 확인해요. 환경 파일과 재시작한 프로세스의 `MARONG_DECOR`를 비밀값을 출력하지 않는 검사로 확인해요. 설정이 예상과 다르면 아래 복구 절차를 실행해요. `MARONG_DECOR`은 전역 설정이므로 재시작 직후 친구 모두에게 한 번에 적용돼요(D191). 아래 명령과 검사는 서버에서 실행하며 복구 뒤에는 검사의 인수만 `disabled`로 바꿔요.

```sh
set -eu
START=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
sudo systemctl restart marong-app.service
systemctl is-active --quiet marong-app.service
sudo python3 - enabled <<'PY'
from pathlib import Path
import subprocess, sys
expected = {'enabled':b'1','disabled':b'0'}[sys.argv[1]]
pid = int(subprocess.check_output(['systemctl','show','marong-app.service','-p','MainPID','--value'],text=True))
if pid <= 1: raise SystemExit('STOP: app is not running')
entries = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
values = [s.split(b'=',1)[1] for s in entries if s.startswith(b'MARONG_DECOR=')]
if values != [expected]: raise SystemExit('STOP: decor state mismatch')
print('decor state verified')
PY
```
재시작과 프로세스 상태 확인이 끝나면 **5분을 기다리지 않고 바로** 마롱이가 승인된 운영 화면을 확인해요. 상점·보관함·일기 꾸미기·관리 아이템 탭의 표시와 접근을 확인해요. 마롱이가 관리자 메일 코드로 Access에 로그인한 뒤 관리자 아이템 탭에서 실제 썸네일이 표시되는지 확인하고 결과만 기록해요. 문제가 있으면 아래 `rollback.py` 복구 절차를 실행해요. 개인 정보·대화·설정 값은 기록하지 않아요.

3. 읽기 전용 SQL로 `marong.decor_items`의 `item_set='v1'` 총수와 `state='listed'` 수를 각각 세고, 자동 등록이 기대한 48개인지 및 종류별 수(4·4·2·7·5·6·20)를 확인해요. 사전 상태가 0행인 경우에만 48개 전부 `listed`를 기대하며, 기존 행이나 내려간 항목이 있으면 덮지 않고 별도 판정해요. 0행에서 시작했을 때는 아래 검사로 결과만 확인할 수 있어요.

```sh
RESULT=$(sudo -u postgres psql -d marong -Atq -c "SELECT count(*)=48 AND count(*) FILTER (WHERE state='listed')=48 AND count(*) FILTER (WHERE kind='hat')=4 AND count(*) FILTER (WHERE kind='top')=4 AND count(*) FILTER (WHERE kind='scarf')=2 AND count(*) FILTER (WHERE kind='background')=7 AND count(*) FILTER (WHERE kind='paper')=5 AND count(*) FILTER (WHERE kind='font')=6 AND count(*) FILTER (WHERE kind='sticker')=20 FROM marong.decor_items WHERE item_set='v1'")
test "$RESULT" = t || { echo 'STOP: catalog count mismatch'; exit 2; }
echo 'catalog count verified'
```

결과가 `t`가 아니면 중단해요. 재시작 직전 UTC 시각을 `START`에 기록한 뒤 5분이 지나면 아래처럼 로그 내용을 출력하지 않고 해당 개수만 세요. 오류나 `decor_seed_skip`이 0이 아니면 중단하고 아래 복구를 실행해요.

```sh
set -o pipefail
sleep 300
sudo journalctl -u marong-app.service --since "$START" --no-pager -o cat | python3 -c 'import sys; lines=sys.stdin; error=skip=0
for line in lines:
    error += int("ERROR" in line or "Traceback" in line)
    skip += int("decor_seed_skip" in line)
print("error_lines:",error,"seed_skip_lines:",skip)
sys.exit(2 if error or skip else 0)'
```
4. 전체 적용 뒤 TC-558을 두 실기기에서 확인해요. 일기 화면과 글 대화·통화, 관리자와 기존 기능이 정상인지 확인하고 문제가 있으면 아래 `rollback.py` 복구 절차를 실행해요. 개인 정보·대화·설정 값은 기록하지 않아요.

복구가 필요할 때는 다른 배포나 설정 변경을 중지하고, 실제 복구 권한·안전한 서비스 중단 시점을 확인해요. 맨 위 설정 출처 검사의 명령 인수 `disabled`를 `source-only`로 바꿔 다시 실행해 실제 승자가 바뀌지 않았는지 확인해요(서비스가 죽어 있어도 출처는 검사). 승자가 달라졌으면 이 절차로 복구했다고 단정하지 말고 중단해 별도 계획을 세워요. `check`는 **전체** 백업 무결성과 현재 파일이 이 배포의 이전 해시 또는 후보 해시 중 하나인지 먼저 확인해요. 외부 변경·백업 변조가 하나라도 있으면 아무 파일도 복원하지 않고 중단해 사람이 3-way 비교해요. `rollback`은 이전 파일의 바이트·소유자·그룹·모드를 복원하고 원래 없던 파일은 정확히 이 릴리스의 해시와 같을 때만 제거해요. 부분 적용 뒤에도 다시 실행할 수 있으며 DB 행·스키마·덤프는 건드리지 않아요.

```sh
set -eu
sudo python3 "$B/rollback.py" check "$B/files"
sudo python3 "$B/rollback.py" rollback "$B/files" --execute
# 대화·통화가 없는 안전한 시점에만
START=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
sudo systemctl restart marong-app.service
systemctl is-active --quiet marong-app.service
sudo python3 "$B/rollback.py" check "$B/files"
```

복구 출력의 `restore verified`와 `check` 성공을 확인하고, 재시작 프로세스의 꾸미기 설정이 원래 꺼짐인지 값 비공개로 확인해요. 설정 우선순위를 다시 대조하고 앱의 꺼짐 응답과 기존 로그인·일기·통화 경로를 안전한 읽기 검사로 확인해요. 이후 5분 오류·`decor_seed_skip` 개수를 다시 세어 보고, 실패한 항목과 중단 시각을 기록해요. 복구가 중간에 실패하면 백업·DB 행을 유지하고 자동 DB 복원이나 추가 삭제 없이 중단해요.

꺼짐 응답은 현재 프로세스의 앱 포트를 내부에서만 읽어 다음처럼 검사할 수 있어요. 이 GET은 로그인 쿠키나 본문을 출력하지 않아요.

```sh
sudo python3 - <<'PY'
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
import subprocess
pid = int(subprocess.check_output(['systemctl','show','marong-app.service','-p','MainPID','--value'],text=True))
if pid <= 1: raise SystemExit('STOP: app is not running')
entries = Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
ports = [s.split(b'=',1)[1] for s in entries if s.startswith(b'MARONG_APP_PORT=')]
port = int(ports[0]) if len(ports)==1 else 8796
try:
    with urlopen(f'http://127.0.0.1:{port}/chat/api/shop',timeout=5) as response: status=response.status
except HTTPError as error: status=error.code
if status != 404: raise SystemExit('STOP: disabled shop did not return 404')
print('disabled shop verified')
PY
```
