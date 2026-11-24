# 관리 페이지 업데이트 내역: 시험 계획(12단계, 기능 변경 4)

상태: 2026-11-24 체크포인트 통과(D172, [도메인 0.4절](../01-domain/admin-changelog.md#04-체크포인트-답2026-11-24)). TC-711(반영 뒤 맞춰 보기)은 꼭 돌려요(D175). 처음 초안은 같은 날 KST, Claude. 시험을 쓰고 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)). 작업은 [작업 목록](../10-wbs/admin-changelog.md)의 TASK-540\~545예요.
입력: [기능 명세](../04-functional-spec/admin-changelog.md) SPEC-500\~504의 받아들임 조건과 3.1\~3.6절, 요구사항 REQ-620\~625와 승인된 REQ-581·585, 흐름 FL-215·216, 계약 `api/admin.openapi.yaml` 0.3.0-draft의 API-300, 화면 정의 [SCR-220](../08-screens/admin-changelog.md), [지난 내역 초안](../10-wbs/admin-changelog-backfill.md).

돌리는 법(`Runs as`)은 [관리 페이지 시험 계획](admin.md)과 같아요: `unit`(함수 하나), `api`(HTTP 경로를 부름, 관리자 확인은 시험용 Access JWT와 시험 이메일 해시. 이 기능은 DB를 쓰지 않음), `e2e`(Playwright Chromium, 밤 테마, 가짜 백엔드), `server`(운영 서버 읽기와 반영 도구), `device`(동희님이 직접).

시험 데이터는 지어낸 단위만 써요: 단위 이름 '시험 반영 가'·'시험 반영 나', 근거 `PR #9001`·`abc1234`, 앱 단위 `app-9.9.9`(코드 999). 단, TC-700과 TC-712는 저장소의 실제 `marong/changelog/` 폴더를 그대로 읽어요(공개 저장소의 글이라 개인 정보가 없어야 하고, 그걸 TC-703이 봐요). 운영 로그, 실제 친구 이름, 대화는 쓰지 않아요.

## ① 파일 형식과 저장소 시험(TASK-540)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-700 | 저장소의 내역 폴더가 모두 통과 | SPEC-500, REQ-621 | unit(`tests/test_changelog.py`) | 저장소 `marong/changelog/`의 모든 `*.json` | 파일마다 `validate_unit` → 폴더 전체의 이름·`id`·겹침 검사 | 모든 파일이 통과, 파일 이름 = `id` + `.json`, `id` 겹침 없음. `.json`이 아닌 파일은 읽지 않음 | 통과. Windows Python 3.12 `68a9d11`. 저장소 내역 파일 48개, 제외 0개 |
| TC-701 | 틀린 파일은 그 이유로 실패 | SPEC-500, REQ-621 | unit | 명세 3.1 '틀린 예' 표의 파일 열하나(시험 안에서 만듦) | 각각 `validate_unit` | 각 파일이 표에 적힌 이유 이름(`json`·`schema`·`name`·`too_big` 등)으로 실패. 3.1의 바른 예시는 통과 | 통과. Windows Python 3.12 `68a9d11`. 명세의 잘못된 파일 11개를 포함해 검사 이유 확인 |
| TC-702 | 앱 단위가 릴리스 기록과 맞음 | SPEC-500, REQ-623 | unit | 시험 폴더 셋: ⓐ `app-0.3.2.json`(코드 11) ⓑ `app-9.9.8.json`과 `app-9.9.9.json`(둘 다 코드 999) ⓒ `app-9.9.9.json`(코드 999) 하나 | 폴더마다 검사 | ⓐ 실패(`tools/app_release.py`의 `PAST_RELEASES`는 10) ⓑ 둘 다 `duplicate`로 실패 ⓒ `PAST_RELEASES`에 없는 새 버전이라 통과 | 통과. Windows Python 3.12 `68a9d11`. 릴리스 기록과 다른 앱 버전 코드, 중복 코드, 신규 버전 확인 |
| TC-703 | 개인 정보 패턴을 막음 | SPEC-500, REQ-625 | unit | 항목 글에 각각 `friend@example.com`, UUID, 22자 토큰 패턴, `010-1234-5678`, `http://`가 든 파일 다섯. 그리고 저장소 폴더 전체 | 각각 `validate_unit` | 다섯 모두 `privacy`로 실패. 저장소 폴더에는 이 패턴이 하나도 없음. 사람 이름은 이 시험이 잡지 못해서 Claude PR 리뷰가 봄(SPEC-503 ②) | 통과. Windows Python 3.12 `68a9d11`. 개인정보 패턴 5개와 저장소 파일 검증 |

## ② API-300(TASK-541)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-704 | 차례와 모양 | SPEC-501, REQ-620, REQ-621 | api(`tests/test_admin.py`) | 시험 폴더: 서버 단위 셋(반영일 2026-11-24 둘: `20261124-b`는 근거 PR #9001, `20261124-a`는 PR #9003. 그리고 `null` 하나), 앱 단위 하나, 항목 근거가 빈 항목 하나 | 관리자 JWT로 `GET /chat/admin/api/changes` | 200, 응답이 계약 `AdminChanges` 스키마에 맞음. 차례는 `sortOn` 늦은 것부터, 같은 날은 근거의 가장 큰 PR 번호가 큰 것부터(`20261124-a`가 `-b`보다 먼저. `id` 차례와 반대라서 규칙을 가려냄), 같으면 `id` 거꾸로(명세 3.3). `null` 단위의 `sortOn`은 `id` 앞 날짜. 근거마다 `label`과 GitHub 주소(`/pull/<n>`, `/commit/<sha>`). 빈 항목 근거는 단위 근거로 채워짐 | 통과. Windows Python 3.12 `68a9d11`. 응답 형식과 세 단계 정렬 확인. `46d6d29`의 48개 단위를 OpenAPI 스키마로도 검증 |
| TC-705 | 읽지 못한 파일, 없는 폴더, 열 수 없는 폴더 | SPEC-501, REQ-620 | api | ⓐ 깨진 JSON 하나 + 32KB 넘는 파일 하나 + 파일 이름과 `id`가 다른 파일 하나 + 바른 파일 둘 ⓑ `versionCode`가 같은 앱 단위 둘 ⓒ 폴더 없음 ⓓ 읽기 권한 없는 폴더(시험에서 함수를 바꿔 `PermissionError`) | 각각 API-300 | ⓐ 200, `units` 둘, `skipped` 3, 로그 `admin_changes file=… result=invalid reason=json`·`too_big`·`name` 세 줄 ⓑ 200, 둘 다 빠지고 `skipped` 2(`duplicate`) ⓒ 200 `{units: [], skipped: 0}`, 로그 `result=missing_dir` ⓓ 500 `internal`. 로그에 글 내용이 없음 | 통과. Windows Python 3.12 `68a9d11`. 정상 파일을 유지하며 폴더와 심볼릭 링크를 제외하고 HTTP 200 응답. WSL의 실제 FIFO를 포함한 파일 검증에서 정상 단위 1개, 제외 3개 |
| TC-706 | 권한, 캐시, 응답의 개인 정보, 속도 | SPEC-501, REQ-625 | api | 관리자 아닌 JWT, 증명 없음, 관리자 JWT. 파일 300개(각 3KB) | 각각 API-300. 300개 폴더는 다섯 번 측정해 중앙값 | 관리자 아님 403 `not_allowed`, 증명 없음 403. 관리자 200에 `Cache-Control: no-store`. 응답 본문에 `@`·설치 ID·토큰 패턴이 없음. 300개 폴더의 응답이 500ms 안(노트북에서. 앱 서버에서 재지 않은 것은 작업 목록 '확인하지 못한 것') | 통과. Windows Python 3.12 `68a9d11`. 300 × 3072바이트, 5회 요청 중앙값 47.0ms |

## ③ 화면(TASK-542)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-707 | 상태마다 화면과 글 | SPEC-502, REQ-620, REQ-621, SCR-220 | e2e(`admin.e2e.cjs`) | 계약의 예시 `normal`·`empty`와 그것을 늘린 가짜 응답: `skipped` 2, `units: []`와 `skipped` 3, `deployedOn: null`, `backfilled: true`와 '기록 없음', 이름 40자·항목 40자·변경 전후 100자, 글에 `<img src=x onerror=…>`, 500, 403, 응답을 늦춤 | `/chat/admin/changes`를 상태마다 엶 | 08 화면 정의의 상태 표 그대로: #normal(첫 그룹 머리 '11월 24일 · …', 작은 줄 '서버 반영 · PR #…' 또는 '앱 0.3.4(12) · …', 칸 차례 3.4), #empty·#unreadable·#skipped·#no-date·#backfilled·#long의 글은 08 3절 문구와 같음(`units: []`이고 `skipped` 3이면 #empty가 아니라 #unreadable), #loading 뒤 자리 움직임 없음, 공통#error의 '다시 해 볼게요'가 API-300을 다시 부름, 403은 공통#forbidden. `<img …>`는 글자 그대로 보이고 이미지 요청이 없음 | 통과. Windows Playwright Chromium `68a9d11`. 합성 응답으로 상태·새로고침·재시도·텍스트 처리와 로딩 중 제목·영역 칩 유지 확인 |
| TC-708 | 영역 칩으로 거르기 | SPEC-502, REQ-622 | e2e | #normal 응답(영역 여섯이 섞임, '대화' 항목은 없음)과 같은 응답에 `skipped` 2 | 칩 '통화' → '대화' → '전체 보기' → '전체'를 차례로 누름. 네트워크 요청 수를 셈. `skipped` 2 응답으로 '대화'를 한 번 더 | '통화': 통화 항목만, 통화 항목이 없는 그룹은 숨김, 세는 줄이 거른 수, `aria-pressed="true"`는 '통화'만. '대화': #filter-empty와 '전체 보기'. '전체 보기'와 '전체'는 #normal. API-300 요청은 처음 한 번뿐. `skipped` 2 응답의 #filter-empty에서도 #skipped 줄이 남음. 칩 높이 44px 이상 | 통과. Windows Playwright Chromium `68a9d11`. 영역 필터, 남은 항목 수, API 요청 수 확인 |
| TC-709 | 폭마다 배치, 가로 넘침, 탭 줄 | SPEC-502, REQ-581, REQ-585, SCR-220 | e2e | TC-707의 #long과 #normal | 폭 360·430·1024·1280·1440px로 엶(1024·1280px는 스크롤 막대를 숨기지 않는 실행으로도 한 번 더) → 페이지 `scrollWidth` → 칸마다 `scrollWidth`와 `clientWidth` → 표의 `display` → 탭 줄의 `scrollWidth`·`clientWidth`와 지금 탭의 `getBoundingClientRect` → Tab 키 차례 | 모든 폭에서 페이지 `scrollWidth` ≤ 화면 폭, 칸 밖으로 나간 요소 없음. 360·430px는 카드(항목마다 변경 전·후 두 칸), 1024px부터 칸 여섯의 표(구분 72px · 영역 104px · 근거 112px). 1024px부터 탭 일곱이 한 줄에 들어감(탭 줄 `scrollWidth` ≤ `clientWidth`). 360·430px에서 처음 그린 뒤 탭 '업데이트 내역'이 탭 줄 안에 보임(4-7이 '바꿈'일 때). Tab 차례: 칩 일곱 → 그룹마다 근거 링크, 폰과 넓은 폭이 같음. 화면 읽기 트리에서 칸마다 머리('변경 전' 등)가 붙음 | 통과. Windows Playwright Chromium `68a9d11`. 14개 폭·상태 조합, 넘친 셀 0개. [노트북](evidence/admin-changelog/laptop-1280.png)·[폰](evidence/admin-changelog/phone-360.png) 합성 캡처 |
| TC-710 | 여덟째 경로와 탭 일곱 | SPEC-450(4-5), SPEC-502, REQ-620 | api(`tests/test_admin.py`) | 관리자 JWT, 증명 없음 | `/chat/admin/changes`와 `/chat/admin/changes/`(끝 `/`), `/chat/admin/changes/x`를 GET. 증명 없이 여덟 경로(TC-620의 일곱 + `/changes`) | `/changes` 200 HTML, 탭 일곱이고 '업데이트 내역'에만 `aria-current="page"`, 탭 차례는 개요 · 회원 · 초대 링크 · 앱 버전 · 비용 · 아이템 · 업데이트 내역. 끝 `/`는 301, 모르는 하위 경로는 404(SPEC-450 그대로). 증명 없이 여덟 경로 모두 403 | 통과. Windows Python 3.12 `68a9d11`. 탭 일곱, 관리자 증명 없이 여덟 경로 403 확인 |

TC-620(승인, [admin 12](admin.md))은 4-9가 '바꿈'이면 '탭 여섯' → '탭 일곱', 경로 여덟으로 고쳐요. TC-637·640·641은 그대로이고 TASK-542 뒤에 다시 돌려요(탭이 하나 늘어도 통과해야 함).

## ④ 반영 도구와 지난 내역(TASK-543·544)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-711 | `put`·`check`·되돌리기 | SPEC-503, REQ-623 | unit(`tests/test_changelog.py`, `deploy/ovh.sh`의 서버 쪽 함수를 임시 폴더, 시험 시계, 가짜 `history.json`으로) | 서버 단위 `20261201-sihum.json`(반영일 2026-12-01)과 임시 반영 폴더 `20261201-sihum.Ab3dEf7h`, 앱 단위 `app-9.9.9.json`(코드 999), 형식이 틀린 파일 하나 | ⓐ 시험 시계 2026-11-30T15:10Z(한국 12-01 00:10)에 `put` → `check` ⓑ 같은 파일, 시계 2026-11-30T14:50Z에 `put` → `check` ⓒ 앱 단위 `put` → `check`(`history.json`에 9.9.9 코드 999) ⓓ 코드 1000 ⓔ 틀린 파일 `put` ⓕ 반영 폴더를 지우고 `put`, 그리고 `20261201-sihum`과 `20261201-sihum.Zz9yXw8v` 둘을 두고 `put` ⓖ 되돌리기 | ⓐ 복사됨(0644), 반영 폴더에 `changelog.json`·`changelog.sha256`·복사 시각, `check`가 `ok` ⓑ `mismatch deployedOn`과 0 아닌 종료 코드(한국 날짜 11-30) ⓒ `ok` ⓓ `mismatch versionCode` ⓔ 복사 0번, 0 아닌 종료 코드, 서버 폴더 그대로 ⓕ 둘 다 복사 0번, 0 아닌 종료 코드 ⓖ 그 단위 파일만 없어지고 다른 파일 수 그대로. 운영 반영(TASK-545) 뒤에는 실제 `check` 결과 `ok` 줄을 PR에 적음 | 통과. 로컬 Windows·WSL Python 3.12 `68a9d11`. 운영 `20f059f`에 2차 반영 후 `ok 20261124-admin-changelog` 확인. 재시작 한국 날짜 2026-11-24와 기록 일치, 서비스 계정 검증도 통과 |
| TC-712 | 지난 내역을 초안대로 옮김 | SPEC-504, REQ-624 | unit | 저장소 `marong/changelog/`(TASK-543 뒤)와 [초안](../10-wbs/admin-changelog-backfill.md) | `backfilled: true` 단위를 셈 → 항목을 셈 → 단위마다 근거 수 → 앱 단위 여덟의 버전 이름·코드·반영일을 초안 1절의 표와 비교 → PR #7·#8을 근거로 가진 단위 찾기 | 단위 47개, 항목 79개(초안 1·2절의 합계). 모든 단위의 근거가 하나 이상. 반영일이 '기록 없음'인 단위는 `deployedOn: null`. 앱 단위 여덟(0.2.2(5)\~0.3.4(12))이 초안의 표와 같음(`PAST_RELEASES`에 없는 0.3.3·0.3.4도 여기서 봄). PR #7·#8(되돌림·운영에 나가지 않음)을 근거로 가진 단위가 없음 | 통과. Windows Python 3.12 `68a9d11`. 승인 초안과 지난 내역 47개 단위·79개 항목의 전체 필드 대조 |

## ⑤ 반영 뒤(TASK-545)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-713 | 반영한 서버에서 화면 걷기와 동희님 확인 | SPEC-501, SPEC-502, REQ-620\~622, REQ-581, REQ-585 | server와 device | 운영 서버(읽기만) | GPT: 동희님 Access로 `/chat/admin/changes`와 API-300 GET(`units` 수와 `skipped`만 적음), 증명 없이 GET 403, 로그 5분. 그다음 브라우저(Aside CLI, D65)로 360px와 1280px에서 가로 넘침과 오류만 봄. 동희님: 아이폰과 노트북에서 탭을 열어 표를 읽어 봄 | 200·403, `units` 48, `skipped` 0, 오류 0. 동희님이 '읽힌다'고 답함(결과는 동희님 말 그대로, 어디서·언제). 운영 화면은 공개 저장소의 글이라 스크린샷을 PR에 올려도 되지만, 다른 관리 화면은 찍지 않음 | 서버·사용자 화면 부분 확인. `20f059f`, 2026-11-24 19:39:38 KST. 서비스 active, health 200, 비인증 화면·API 403, 파일 해시 54/54, 제공 정적 파일 4/4, `300`초 로그 오류 0건. 서비스 계정으로 읽은 단위 48개·제외 0개. 2026-11-24 19:48:46 KST, 마롱이 항목 91에서 업데이트 내역 탭의 표시를 묻자 사용자님이 “맞게 보임”이라고 답했어요(e1922, 화면 부분 통과 기록 e1924). 기기별 확인과 360·1280px 가로 넘침 측정, 관리자 인증 GET 200·API-300 응답은 확인 대기예요. |

## 범위 확인

| 요구사항 | 시험 |
| --- | --- |
| REQ-620 | TC-704, 705, 707, 710, 713 |
| REQ-621 | TC-700, 701, 704, 707 |
| REQ-622 | TC-708, 713 |
| REQ-623 | TC-702, 711 |
| REQ-624 | TC-712 |
| REQ-625 | TC-703, 706 |
| REQ-581·585(승인) | TC-709, 713 |

## 확인하지 못한 것

- TC-709의 목업 측정은 목업 파일이지 구현이 아니에요. 구현의 CSS 이름과 칸 폭이 달라지면 다시 측정해요.
- 실제 아이폰 Safari의 표 카드 모양(`display: flex`로 바꾼 `<tr>`의 읽기)은 TC-713에서 동희님이 봐요. 화면 읽기 프로그램(VoiceOver)으로 칸 머리가 붙는지는 이 계획에서 기기로 보지 않아요(TC-709가 Chromium의 접근성 트리로 봐요).

## 로컬 회귀 시험

- `tests/test_admin.py` 19개, `tests/test_changelog.py` 6개 통과. 관리 화면 브라우저 시험 16개와 전체 브라우저 시험 91개가 통과했어요.
- 전체 브라우저 시험의 이전 실행에서 TC-618의 앱 업데이트 배너 시간 조건이 실패했어요. `main`의 배너 시험 18개와 구현 브랜치의 전체 재실행은 통과했어요.
- `npm test`에서 34개가 통과했고, 릴리스 APK의 병합 매니페스트를 확인하는 1개는 빌드 산출물이 없어 건너뛰었어요.
