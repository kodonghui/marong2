# 관리 페이지 업데이트 내역 작업 목록(10단계 WBS, 기능 변경 4)

2026-11-24 KST 작성(Claude). 입력: 도메인 [admin-changelog.md](../01-domain/admin-changelog.md)(TERM-270·271, D170·D171), 요구사항 [admin-changelog.md](../02-prd/admin-changelog.md)(REQ-620\~625, 기능 변경 목록 4-1\~4-12), 흐름 [FL-215](../03-user-flow/FL-215-admin-changelog-view.md)·[FL-216](../03-user-flow/FL-216-changelog-write.md), 기능 명세 [admin-changelog.md](../04-functional-spec/admin-changelog.md)(SPEC-500\~504), 계약 [`api/admin.openapi.yaml`](../../api/admin.openapi.yaml)의 API-300, 화면 [SCR-220](../08-screens/admin-changelog.md), 목업 [design/admin-changelog-mockup.html](../../design/admin-changelog-mockup.html), [지난 내역 초안](admin-changelog-backfill.md), 시험 [TC-700\~713](../12-qa/admin-changelog.md).

상태: 2026-11-24 체크포인트 통과(D172\~D179, [도메인 0.4절](../01-domain/admin-changelog.md#04-체크포인트-답2026-11-24)). 이 설계 PR(#129)이 `main`에 합쳐지면 시작해요.

## GPT 인계

- 상태: **시작 가능**(2026-11-24 체크포인트 통과, D172\~D179). 설계 PR #129가 `main`에 합쳐진 뒤 시작해요. 설계 PR 합침과 GPT 시작은 마롱이가 지시해요. 구현 PR 병합은 동희님이고, 운영 반영(TASK-545)은 동희님 말 "반영까지 해"(D171)로 허락됐어요. 반영 뒤 맞춰 보기(TC-711)는 꼭 해요(D175).
- 목표: 관리 페이지에 일곱째 탭 '업데이트 내역'(SCR-220)을 더하고, 반영 단위마다 바뀐 것을 항목마다 '변경 전'·'변경 후'로 보여 줘요. 내역은 저장소 파일(`marong/changelog/<id>.json`)이고 반영 때 서버에 복사해요. 동희님 말(2026-11-24, 오랑이 전달, D170): "야 마롱이 관리자페이지에서 업데이트 내역 즉 change log 기록하라고 해줘. 어떤 기능이 추가되거나 개선되었는지 등등. 표로 나타내줘 전 후 나눠서". 표 모양·범위·반영(D171): "항목마다 '변경 전'·'변경 후' 칸", "앱·웹·통화·관리 등 서비스 전체 바뀐 것", "반영까지 해".
- 시작: 합쳐진 `main` 머리에서 새 브랜치 `codex/admin-changelog`. 초안 PR 하나예요. 관리 페이지 다시 만들기(TASK-490\~500)는 2026-11-24에 운영에 나갔어요(반영 폴더 `20261124-admin`). 기능 변경 3(꾸미기 꺼짐 안내·앱 지워진 폰, 설계는 PR #127로 합쳐짐, 구현은 TASK-502\~505)의 구현이 먼저 합쳐지면 그 위에서 해요.
- 읽을 것: 기능 명세의 1절(공통 규칙), SPEC-500\~504, 3.1(파일 형식, 틀린 예 열하나), 3.2(응답 모양), 3.3(차례), 3.4(칸과 이름), 3.5(반영 차례), 3.6(지난 내역 규칙). 계약의 API-300과 스키마 `AdminChanges`·`ChangeUnit`·`ChangeItem`·`ChangeEvidence`. 화면 정의 SCR-220 전체. 승인된 [관리 페이지 기능 명세](../04-functional-spec/admin.md)의 SPEC-450과 3.1(경로와 탭 줄, 4-5·4-6으로 일곱째 줄이 생김).
- 화면 모양: 목업 [design/admin-changelog/screen.html](../../design/admin-changelog/screen.html)이 지금 `chat.css`·`unified.css`를 그대로 링크하고, 새 부품 CSS는 [changelog.css](../../design/admin-changelog/changelog.css)예요. 이 CSS를 `unified.css`에 옮겨 쓰면 돼요(이름은 바꿔도 됨). 그리는 차례는 [screen.js](../../design/admin-changelog/screen.js)를 참고해요(모든 글 `textContent`). 새 토큰은 없어요(D67).
- 이미 된 것: 설계 문서, 목업, [지난 내역 초안](admin-changelog-backfill.md)(반영 단위 47개, 항목 79개의 표). 코드·파일·서버는 아무것도 바꾸지 않았어요.
- 순서: TASK-540 → TASK-541 → TASK-542, TASK-540 → TASK-543, TASK-540 → TASK-544, 모두 → TASK-545. TASK-542·543·544는 서로 다른 파일이라 같이 해도 돼요.
- 시험 환경: Python 3.12(AGENTS.md). 이 기능은 DB를 쓰지 않아서 `pgserver`가 필요 없어요(관리자 확인을 지나는 경로 시험은 지금 `tests/test_admin.py`의 틀을 써요). 화면은 Node와 Playwright(360·430px, 1024·1280·1440px, 밤 테마. 관리 페이지는 `data-theme="night"` 고정). 시험 파일은 지어낸 단위만 써요. 실제 친구 이름, 대화, 운영 로그를 넣지 않아요.
- 반영: 서버 반영을 해요(TASK-545). ① 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-admin-changelog/`에 먼저 둠 ② 앱 서버 파일(`marong/admin_changes.py`, `marong/app_admin.py`, `marong/app_chat.py`(경로를 더했다면), `marong/app_chat_static/admin.js`·`unified.css`)과 폴더 `marong/changelog/`(지난 내역 47개 파일)를 `/opt/marong-app/`에 복사 ③ 진행 중 통화가 없을 때 `marong-app`만 재시작 ④ 이 반영 자신의 단위 파일 `<날짜>-admin-changelog.json`을 TASK-544의 `changelog put`으로 올리고 `changelog check` ⑤ 확인: 동희님 Access로 `/chat/admin/changes`와 API-300이 200, 증명 없이 403, API-300의 `units` 수가 48이고 `skipped`가 0(수만 적음), 로그 5분 오류 없음. 마이그레이션 없음. 켜고 끄는 설정은 두지 않아요: 관리자만 보는 읽기 화면이고 친구 쪽 동작이 바뀌지 않아요(관리 페이지 다시 만들기 TASK-500과 같은 이유). 되돌리기는 파일을 되돌리고 `marong-app` 재시작이에요.
- 하면 안 되는 것: 내역을 DB에 넣기, 관리 페이지에서 내역을 쓰거나 고치는 단추나 API, PR 제목·커밋에서 내역을 자동으로 만들기(02 7절 범위 밖). 글을 `innerHTML`로 넣기, 인라인 스크립트(CSP `script-src 'self'`). 폴더 경로를 현재 폴더 기준으로 찾기: `marong-app` 서비스의 `WorkingDirectory`가 `/opt/marong`(옛 카톡 사본)이라서, 폴더는 모듈 파일 기준(`Path(__file__).parent / "changelog"`)으로 찾아요[사실, 2026-11-24 서버에서 `systemctl show`로 읽음]. 지난 내역 초안의 글을 고쳐 쓰기(바꿔야 하면 '설계 질문').
- 겹치는 파일: `marong/app_admin.py`(기능 변경 3의 구현도 고침), `marong/app_chat_static/admin.js`·`unified.css`, `tests/test_admin.py`, `deploy/ovh.sh`(앱 릴리스 블록 옆에 `changelog` 블록), `README.md`의 시험 목록. 먼저 합친 쪽에 맞춰요.
- 사람 확인: TC-713(반영 뒤 동희님이 아이폰과 노트북에서 탭을 열어 봄). 운영 화면은 공개 저장소의 내용과 같아서 스크린샷을 PR에 올려도 되지만, 탭 줄 위의 다른 화면(회원 등)은 찍지 않아요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-700\~712 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TC-711의 서버 쪽 확인과 TC-713.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드가 답해요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_changelog.py   # TC-700~703·711·712 (새 파일, 이름은 바꿔도 됨)
.venv/bin/python tests/test_admin.py       # TC-620(탭 일곱, 4-9)·704~706·710과 지금 관리자 시험
(cd apps/android && npm ci && npm test && npm run test:browser)   # 화면 TC-707~709와 TC-637·640·641 다시. Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인해요
```

## 작업

- 담당: 모두 GPT예요. 서버 반영도 GPT가 해요(D65, AGENTS.md). 지난 내역 초안과 기능 변경 목록 4-1\~4-12의 승인 문서 고침은 Claude가 이 설계 PR에서 했어요(D173).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 3일이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-540 | 내역 파일 형식과 검사 함수: `marong/admin_changes.py`에 `validate_unit(path, raw) -> (unit, reason)`(3.1의 규칙과 이유 이름 `json`·`schema`·`name`·`too_big`·`privacy`·`duplicate`)과 폴더를 읽는 `load_units`(파일마다 `validate_unit`, 파일 이름과 `id`가 다르면 `name`, 앱 단위의 `versionCode`가 겹치면 둘 다 `duplicate` → 통과한 단위와 `skipped` 수. 저장소 시험과 API-300이 같이 씀). 빈 폴더 `marong/changelog/`(파일이 없으면 Git이 폴더를 지우니, 지난 내역을 같은 PR에서 넣거나 `.json`이 아닌 `README.md`를 둠). 저장소 시험 `tests/test_changelog.py`: 폴더의 모든 파일, 파일 이름과 `id`, 겹침, 앱 단위와 `tools/app_release.py`의 `PAST_RELEASES` | SPEC-500 | `marong/admin_changes.py`, `marong/changelog/`, `tests/test_changelog.py`, `README.md` 시험 목록 | 없음 | GPT | 0.5 | TC-700\~703 통과 |
| TASK-541 | API-300 `GET /chat/admin/api/changes`: 관리자 확인(지금 `require_admin`), 폴더 읽기는 `load_units`를 `asyncio.to_thread`로, 요청마다 읽음(캐시 없음), `sortOn`과 근거 주소(`https://github.com/kodonghui/marong2/pull/<n>`, `/commit/<sha>`), 항목 근거가 비면 단위 근거, 3.3의 차례, `Cache-Control: no-store`, 로그 `admin_changes file=<이름> result=invalid reason=<이유>`와 `admin_changes result=missing_dir`(글 내용은 로그에 넣지 않음) | SPEC-501 | API-300, `marong/app_admin.py` | TASK-540 | GPT | 0.5 | TC-704\~706 통과 |
| TASK-542 | 화면 SCR-220: 경로 `/chat/admin/changes`가 관리 페이지 틀을 주고(SPEC-450, 4-5·4-6), `TABS`에 일곱째 `changes`('업데이트 내역'), `admin.js`에 이 화면을 그리는 함수(칩 일곱, 세는 줄, 그룹, 표, 상태 #loading·#normal·#filtered·#filter-empty·#empty·#skipped·#no-date·#backfilled·#long·#unreadable과 공통 #error·#forbidden·#stale), CSS는 목업의 `changelog.css`를 `unified.css`로. 4-7이 '바꿈'이면 처음 그릴 때 지금 탭이 탭 줄 밖이면 탭 줄만 밀어 보이게 함(모든 관리 화면 공통) | SPEC-502, SPEC-450(4-5·4-6), SCR-220 | SCR-220, `marong/app_admin.py`, `marong/app_chat_static/admin.js`·`unified.css` | TASK-541 | GPT | 0.75 | TC-707\~710 통과. TC-620(4-9로 탭 일곱), TC-637·640·641 다시 통과 |
| TASK-543 | 지난 내역 옮기기: [초안](admin-changelog-backfill.md) 1절의 반영 단위 47개를 2절의 항목 79개와 함께 `marong/changelog/<id>.json`으로(모두 `backfilled: true`, 반영일이 '기록 없음'이면 `null`). 초안의 글을 그대로 옮기고, 길이·형식이 맞지 않으면 옮기지 않고 '설계 질문' | SPEC-504 | `marong/changelog/*.json` | TASK-540 | GPT | 0.5 | TC-712 통과, TC-700이 47개 파일로 통과 |
| TASK-544 | 반영 도구: `deploy/ovh.sh changelog put <파일>`(서버에서 같은 검사 함수로 다시 봄 → `~/marong-deploy/`에서 이름이 `<id>` 또는 `<id>.XXXXXXXX`인 반영 폴더를 딱 하나 찾음(앱 단위는 `~/marong-deploy/<id>/`를 만듦), 없거나 둘이면 끝 → 그 폴더에 `changelog.json`·`changelog.sha256`·복사 시각(UTC) → `/opt/marong-app/marong/changelog/<id>.json`, root 소유 0644), `changelog check <id>`(서버 단위는 `put`이 남긴 복사 시각의 한국 날짜, 앱 단위는 `history.json`의 버전 이름·코드·게시 날짜, 그리고 sha256), 되돌리기가 그 단위 파일만 지움. `apps/android/README.md`의 릴리스 줄에 '릴리스 PR에 `app-<버전>.json`, 게시 뒤 `put`·`check`' 한 줄 | SPEC-503 | `deploy/ovh.sh`, `apps/android/README.md`, `tests/test_changelog.py` | TASK-540 | GPT | 0.5 | TC-711 통과(임시 반영 폴더·가짜 `history.json`) |
| TASK-545 | 서버 반영(GPT 인계의 '반영' ①\~⑤)과 되돌리기 준비. 이 반영 자신의 단위 파일(`<날짜>-admin-changelog.json`, 항목: 관리 '업데이트 내역 탭' 추가)을 구현 PR에 더함 | SPEC-501\~504 | 앱 서버 | TASK-541\~544 | GPT | 0.25 | 인계 ⑤ 확인 통과, TC-711의 서버 쪽 확인 결과(`ok` 줄)와 백업·되돌리기 경로가 PR 설명에 있음. TC-713은 동희님 |

## 확인

- 모든 TASK가 SPEC이나 화면을 하나 이상 가리키고, SPEC-500\~504가 모두 TASK를 가져요(500: 540, 501: 541·545, 502: 542, 503: 544·545, 504: 543).
- 끝 조건마다 시험이나 확인할 수 있는 결과가 있어요.
- 순서에 고리가 없어요.
- 승인된 문서 고침(기능 변경 목록 4-1\~4-12)은 이 목록에 없어요. Claude가 이 설계 PR에서 고쳤고(D173) 문서 줄마다 'D173 4-n'을 적었어요(AGENTS.md와 인계 형식 줄은 승인된 글 그대로). 그래서 TC-620의 글(4-9)과 AGENTS.md(4-10·4-11)가 구현보다 먼저 `main`에 들어가요. TC-620을 여덟 경로·탭 일곱으로 돌리는 것은 TASK-542예요.
- 열린 질문: 없어요(2026-11-24 질문 0\~7과 4-1\~4-12 모두 답함, D172\~D179).
- 확인하지 못한 것: 앱 서버에서 폴더 300개 파일을 500ms 안에 읽는지(TC-706은 노트북에서 측정해요). 운영에서 `deploy/ovh.sh`의 `changelog put`이 쓰는 파이썬이 `/opt/marong/.venv/bin/python`인지(2026-11-24 `marong-app`의 `ExecStart`가 그 파이썬이었음[사실], 반영 때 다시 봐요).

## 11단계 진행

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-540 | 구현 완료 | `9f3237b`, `46d6d29` | TC-700~703. 파일 48개 통과, 제외 0개 |
| TASK-541 | 구현 완료 | `9f3237b`, `68a9d11` | TC-704~706. Access JWT, 응답 계약, 파일 오류, 캐시 없음, 노트북에서 300개 파일 요청 중앙값 47.0ms. 일반 파일만 읽고 심볼릭 링크·FIFO·폴더는 제외 |
| TASK-542 | 구현 완료 | `9f3237b`, `46d6d29`, `8ea6c8c` | TC-707~710과 TC-620·637·640·641 통과. 합성 데이터로 확인한 14개 폭·상태 조합에서 가로 넘침 0개 |
| TASK-543 | 구현 완료 | `9f3237b` | TC-712. 승인 초안과 동일한 지난 내역 47개 단위·79개 항목 |
| TASK-544 | 구현 완료 | `9f3237b` | TC-711 로컬 시험 통과. Windows 임시 폴더에서 명령 결과를, WSL 임시 폴더에서 0644 권한을 포함해 확인 |
| TASK-545 | 반영 기록 준비, 운영 대기 | `46d6d29` | 예정일을 2026-11-24 KST로 기재한 내역 파일 추가. 운영 반영과 TC-711 운영 확인·TC-713은 리뷰 뒤 별도 지시 대기 |
