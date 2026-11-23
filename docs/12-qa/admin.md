# 마롱이 관리 페이지 다시 만들기: 시험 계획(12단계)

상태: 2026-11-23 새벽 KST 작성(Claude 마롱이 봇). 아직 돌리지 않았어요. TC-640·641과 TC-639의 노트북 폭은 2026-11-23 노트북 폭 기능 변경(D140)으로 더한 제안이고 체크포인트 전이에요([요구사항의 기능 변경 목록 2](../02-prd/admin.md#노트북-폭-기능-변경-목록-2)). 시험을 쓰고 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)). 작업은 [작업 목록](../10-wbs/admin.md)의 TASK-490\~501이에요.
입력: [기능 명세](../04-functional-spec/admin.md) SPEC-450\~458의 받아들임 조건과 1절 공통 규칙, 요구사항 REQ-570\~585, 흐름 [FL-200](../03-user-flow/FL-200-admin-overview.md)·[FL-201](../03-user-flow/FL-201-admin-app-version.md), 계약 `api/admin.openapi.yaml` 0.1.0-draft(API-280·281), 바뀌지 않는 API-235\~243·263\~266(`api/unified.openapi.yaml` 등), PR #101의 API-267(읽기만), 화면 정의 [08-screens/admin.md](../08-screens/admin.md)(넓은 폭은 1.1절), 표 문서 [05-erd/admin.md](../05-erd/admin.md)(함수 `call.month_budget`).

돌리는 법(`Runs as`)은 [사람별 사용 한도 시험 계획](usage-limit.md)과 같아요: `unit`(함수 하나), `api`(`pgserver`의 빈 DB에 020·008·021·009·022·010과 통화 011을 적용하고 HTTP 경로를 부름, 시험 시계, 관리자 확인은 시험용 Access JWT와 시험 이메일 해시), `e2e`(Playwright Chromium 360·430px와 노트북 1280·1440px, 나뉘는 폭 시험은 768·1023·1024px도, 낮·밤 테마, 가짜 백엔드. 노트북 폭은 D140 2-12), `server`(반영한 서버에서 읽기 확인), `device`(사람이 실제 화면에서 봄). 진짜 모델, 결제, FCM은 부르지 않아요.

시험 데이터는 합성 데이터만 써요. 사람은 '시험친구 가'·'시험친구 나'·'시험친구 다'이고, 이름이 같은 두 친구가 필요한 시험은 '시험친구 가'를 두 `friendId`(7, 9)에 둬요. 통화 비용은 `tools/vertex_live/test_call_cost.py`처럼 지어낸 통화·토큰·단가 행으로, 앱 버전은 PR #101 계약의 API-267 예시(`behind`, `empty`)와 그것을 늘린 가짜 응답으로 만들어요. 운영 DB의 값, 실제 친구 이름, 대화, 실제 이메일은 넣지 않아요.

## ① 틀과 경로(TASK-492)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-620 | 화면 경로 일곱이 같은 틀과 탭 줄을 줌 | SPEC-450, REQ-570, REQ-571 | api(`tests/test_admin.py`) | 관리자 JWT | `/chat/admin/`, `/members`, `/members/7`, `/invites`, `/app`, `/costs`, `/items`를 차례로 GET | 모두 200 HTML이고 탭 여섯(`<a href>`)이 있음. 지금 화면의 탭에만 `aria-current="page"`. 응답 헤더에 CSP `script-src 'self'`가 그대로 | |
| TC-621 | 관리자 아님·모르는 경로·끝 `/` | SPEC-450, 공통 규칙 1 | api(`tests/test_admin.py`) | 증명 없는 요청, 다른 이메일 JWT, 관리자 JWT | 증명 없이 일곱 경로 → 다른 이메일로 일곱 경로 → 관리자로 `/chat/admin/foo`, `/chat/admin/members/abc`, `/chat/admin/members/0` → `/chat/admin/members/` | 처음 둘은 모두 403(401이 아님). 모르는 경로와 숫자가 아닌·0인 `friendId`는 404. 끝 `/`는 301로 `/chat/admin/members` | |

## ② 개요 API(TASK-491)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-622 | 개요의 숫자와 주의 항목 다섯 | SPEC-451, REQ-572, REQ-573, API-280#200 | api(`tests/test_admin.py`) | 회원 3, 프로필 없는 친구 1, 오늘 단위 합 420(한국 시각 04:00 뒤 행만), 통화 합 121.40·예산 150, 캐릭터 그림 17/20달러, 가짜 앱 함수(최신 0.3.3을 30시간 전에 올림, 0.3.2 폰 1·0.3.3 폰 1), 23시간 뒤 만료되는 열린 링크 1 | API-280 | 숫자가 그대로(`spentUsd` `"121.40"`, `percent` 80, `state` `warn`, `images.budgetPercent` 85, `app.devices` 2, `behind` 1). `attention`이 `call_budget`(80), `image_budget`(85), `app_behind`(1), `invite_expiring`(1), `unlinked_friend`(1) 차례. `Cache-Control: no-store` | |
| TC-623 | 손볼 일 없음, 한 부분 실패, 차례 읽기 | SPEC-451, API-280#200 | api(`tests/test_admin.py`) | (가) 문턱 아래 자료 (나) 통화 함수가 2초 걸리게 함 (다) 앱 함수가 없음(앱 업데이트 TASK-480 전) (라) 그림 함수가 예외 (마) 초대 링크 만료 수 쿼리가 2초 걸림 (바) 다섯 부분이 모두 2초 걸림 (사) 시험이 풀의 연결 넷을 먼저 잡아 둠 | 각각 API-280, 로그 읽기 | (가) `attention` 빈 목록 (나) 200이고 `callMonth` null, 다른 부분은 값, 로그 `admin_overview part=call result=failed` 한 줄 (다) `app` null (라) `images` null (마) `invite_expiring` 줄만 빠지고 로그 `part=invites` (바) 8초 안에 200이고 네 칸 null과 `invite_expiring` 없음, 로그 다섯 줄, 요청 동안 개요가 한 번에 쓴 연결은 하나(풀 사용 수를 셈) (사) 2초 뒤 503 `db_unavailable`. (가)\~(바)는 503이 아님 | |
| TC-624 | 권한·DB 없음·실리지 않는 것 | SPEC-451, REQ-580, API-280#403, API-280#500, API-280#503 | api(`tests/test_admin.py`) | TC-622 자료, 다른 이메일 JWT | 다른 이메일로 API-280 → DB를 내리고 API-280 → 회원 수 쿼리가 예외를 내게 하고 API-280 → 관리자로 응답 전체를 문자열로 검사 | 403 `not_allowed`, 503 `db_unavailable`, 500 `internal`(Problem 모양). 응답 글에 설치 ID·FID·이메일·토큰·초대 링크 주소·친구 이름이 없음(주의 항목은 개수만) | |
| TC-625 | 주의 항목 문턱의 경계 | SPEC-451 3.3 | unit(`tests/test_admin.py`) | 주의 항목 계산 함수에 넣는 값 | 통화 79·80·100·120% → 그림 79·80·100% → 앱: 올린 지 23·25시간, 마지막 상태 `needs_confirm`·`failed`, 멈춤 → 링크: 만료까지 23·25시간, 쓴 링크 → 잇지 않은 친구 0·1 | 통화 79 없음, 80 `warn`, 100·120 `danger`. 그림 79 없음, 80 `warn`, 100 `danger`. 앱 23시간 없음, 25시간 `warn`, `needs_confirm`·`failed`는 시간과 상관없이 `danger`, 멈춤이면 `app_behind` 없음과 `app_paused`. 링크 23시간만 셈. 친구 0 없음. 차례는 늘 3.3 | |

## ③ 화면(TASK-493\~497)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-626 | 개요 화면 | SPEC-451, REQ-572, REQ-573, SCR-169 | e2e(`apps/android/test/admin.e2e.cjs`) | 가짜 API-280: TC-622 응답, 빈 `attention`, `callMonth` null, `app` null, `app.latest` null, `image_budget` `danger` | 화면을 엶 → 주의 항목 줄을 누름 → 카드를 누름 → 탭을 30초 숨겼다 보임 → 61초 숨겼다 보임(가짜 시계) | 08의 SCR-169#attention·#calm·#card-unknown·#no-release 문구 그대로. 그림 `danger` 문구는 종류를 말하지 않음. 줄과 카드는 `target` 경로로 감. 30초는 다시 읽지 않고 61초는 API-280을 한 번 다시 읽음(공통#stale). 360·430px, 낮·밤 | |
| TC-627 | 회원 목록 | SPEC-452, REQ-574, SCR-200 | e2e(`admin.e2e.cjs`) | 가짜 API-236: 무제한·기본·직접 회원 셋, 프로필 없는 친구 하나, 빈 목록, 500 | 화면을 엶 → 줄을 누름 → '잇기 링크 만들기'를 누름 | 줄 셋과 아래 그룹 한 줄. 한도 문구가 usage-limit 08과 한 글자도 다르지 않음. 줄은 `/chat/admin/members/{friendId}`, 잇기는 `/chat/admin/invites?kind=link&friend={friendId}`. 빈 목록 '아직 가입한 사람이 없어요', 500은 공통#error | |
| TC-628 | 회원 한 사람 | SPEC-453, REQ-575, REQ-582, REQ-487, REQ-482, SCR-201 | e2e(`admin.e2e.cjs`) | 가짜 API-236·243·237·241·267. 회원 7과 이름이 같은 회원 9, 7의 폰 2대(0.3.2 뒤처짐, 0.3.3)와 9의 폰 1대, 7의 폰이 20대인 응답, 7의 폰이 없는 200줄 응답, API-267 503 | 한도를 무제한으로 저장 → 티켓 5 넣기 → 로그인 끊기에서 '그만두기' → 다시 '끊기'를 빠르게 두 번 → `/members/999` → 폰 그룹 보기(세 응답) → '앱 버전에서 보기' | API-243 200 뒤 '한도 · 무제한'과 띠. '티켓 5장'. '그만두기'는 API-241 요청 0번, 두 번 누름은 1번이고 '로그인 0개'. 999는 #missing. 7의 화면에 폰 줄 둘만(9의 폰이 섞이지 않음), 20대면 '최근 보고한 20대만 보여요', 200줄에 7의 폰이 없으면 '폰이 많아 일부만 보여요'(없다고 하지 않음), 503이면 폰 그룹만 '지금 못 불러왔어요'. 링크는 `/chat/admin/app#friend=7` | |
| TC-629 | 초대 링크 | SPEC-454, REQ-576, REQ-430, REQ-431, REQ-433, SCR-202 | e2e(`admin.e2e.cjs`) | 가짜 API-240(열림·씀·기간 지남·거둠 넷, 빈 목록), API-235(201, 400, 404), API-236 | 칩 '열림' → '전체' → `?kind=relogin&friend=2`로 엶 → `?kind=join&friend=2`로 엶 → 새 링크 만들기와 복사 → 400·404 응답 | '열림'에 한 줄, '전체'에 넷이고 날짜 이름표가 usage-limit 08과 같음. relogin 질의는 칸이 열리고 사람 2가 골라짐, join 질의는 칸이 닫힘. 만든 주소는 그때 한 번만 보이고 목록에는 주소가 없음. 400·404는 #invite-invalid·#member-missing 문구. 빈 목록 두 문구 | |
| TC-630 | 앱 버전 | SPEC-456, REQ-577, REQ-578, REQ-580, SCR-203, FL-201 | e2e(`admin.e2e.cjs`) | PR #101 API-267 예시 `behind`와 `empty`, 그것을 늘린 가짜 응답: `paused: true`, 모르는 상태 `foo`, 이름이 같은 `friendId` 7·9, 7의 폰 20대, `devices` 200줄, `fetches` 100칸, 503 | 화면을 엶 → 폰 줄을 누름 → `#friend=7`로 엶 → `#friend=abc`로 엶 → 네트워크 요청 기록 | `behind`: 맨 위 0.3.3, '시험친구 가 · 폰 1 · 0.3.2 · 뒤처짐'(예시 이름은 D139로 합성), 펼치면 명세 3.6 문구가 새것부터, `friendId`가 같은 받아 감 줄, 0.3.2에 '기록에서 채움'. `empty`: '아직 올린 버전이 없어요'. 멈춤 띠와 단추 없음. 'foo' 한 줄. '시험친구 가(7)'·'(9)'. 상한 안내 셋. `#friend=7`은 7의 첫 폰 줄이 펼쳐짐, `abc`는 맨 위 그대로. 요청은 API-267 하나뿐(API-236 없음, 쓰기 없음). 화면 글에 설치 ID·FID·APK 파일 이름이 없음 | |
| TC-633 | 비용 | SPEC-457, REQ-579, REQ-520, REQ-451, SCR-204 | e2e(`admin.e2e.cjs`) | 가짜 API-280(`percent` 80·101, `callMonth` null), API-236(`callMonthUsd` 1.23·0.40·null), API-266(정상, 500) | 화면을 엶 → 네트워크 요청 기록 → 사람 줄을 누름 | 80%는 '80% 넘음', 101%는 '다 씀'과 막대 가득, null은 통화 그룹만 '지금 못 불러왔어요'. 사람 줄은 큰 차례이고 null은 '—', 누르면 SCR-201. API-266 500은 그림 그룹만 오류 줄. 세 요청은 겹치지 않고 API-280 → API-236 → API-266 차례(앞 요청이 실패해도 다음을 부름) | |

## ④ 통화 월 예산 함수(TASK-490)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-631 | 함수의 합이 통화 서버의 합과 같음 | SPEC-457, REQ-579 | api(`tests/test_admin.py`) | TC-498과 같은 합성 통화(10,000·1,000 토큰, 단가 3·6), 검색·정리 비용 행, 지난달 행 하나, `monthly_budget_usd` 행 있음·없음 | 이번 UTC 달 범위로 `call.month_budget` → 같은 DB로 `call_cost.MonthlyCost.report(at, fresh=True)` → 예산 행을 지우고 다시 함수 | `spent_usd`가 `report(at, fresh=True)`의 `total`과 같음(소수 넷째 자리까지). 지난달 행은 들어가지 않음. 예산은 행이 있으면 그 값, 없으면 150 | |
| TC-632 | 함수의 권한과 다시 적용 | SPEC-457, 05 표 문서 3절 | api(`tests/test_admin.py`) | TC-631의 DB | 011을 한 번 더 적용 → `marong` 역할로 함수 실행 → `marong` 역할로 `call.live_usage` 읽기 → `marong_call` 역할로 함수 실행 → `PUBLIC` 실행 권한 확인 → `pg_proc`의 두 함수(`call.month_budget`, `call.friend_month_usd`) 설정 → `marong` 역할 세션에서 `pg_temp`에 가로채기를 만듦: 부르면 `RAISE EXCEPTION`하는 함수, 그 함수를 CHECK에 쓰는 도메인 `pg_temp.timestamptz`, 같은 이름의 임시 표 `live_usage`·`settings`(다른 숫자) → 같은 세션에서 두 함수 실행 | 다시 적용해도 오류 없음. `marong`은 실행되고 표 읽기는 권한 오류(지금 그대로). `marong_call`과 `PUBLIC`은 `call.month_budget` 실행 권한이 없음. 두 함수의 `proconfig`가 `search_path=pg_catalog, pg_temp`이고 `call.month_budget`의 `prosqlbody`가 비어 있지 않음(`BEGIN ATOMIC`). 가로채기를 만든 세션에서도 두 함수의 값이 만들기 전과 같고 가로채기 함수가 돌지 않음(오류 없음) | |

## ⑤ 공통 규칙과 화면 폭(TASK-492·496)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-634 | 사람이 쓴 글은 글자 그대로 | 공통 규칙 8, SPEC-456, REQ-580 | e2e(`admin.e2e.cjs`)와 api | 가짜 API-267 릴리스 노트 `<img src=x onerror=alert(1)>`, 친구 이름 `<b>가</b>`, 가짜 API-240 메모 `<script>x()</script>`, 300자 노트 | 앱 버전·초대 링크·회원 화면을 엶 → 콘솔·대화 상자·네트워크 기록 → `admin.js`에서 `innerHTML` 찾기 | 글자 그대로 보이고 `x` 요청·실행·대화 상자 없음. 300자 노트는 줄바꿈해 모두 보임. `git grep -n innerHTML marong/app_chat_static/admin*.js`가 0줄. 응답 헤더의 CSP가 TC-620과 같음 | |
| TC-637 | 360·430px에서 가로로 넘치지 않음 | REQ-581, REQ-571, SPEC-450 | e2e(`admin.e2e.cjs`) | 화면 일곱의 가장 긴 상태(SCR-169#attention, SCR-201#normal과 폰 20대, SCR-202#all, SCR-203#device-open과 300자 노트, SCR-204#normal), 이름 12자, 메모 40자 | 360·430px, 낮·밤으로 각각 엶 → `document.documentElement.scrollWidth` → 탭 줄 옆으로 밀기 → 누르는 칸 크기 | 페이지 `scrollWidth`가 화면 폭 이하. 탭 줄만 안에서 밀림. 누르는 칸은 44px 이상. 화면마다 스크린샷을 남김. PR에 붙이는 스크린샷은 합성 데이터('시험친구 가'·'시험친구 나')로 찍은 이것뿐이에요 | |
| TC-638 | 아이템 화면은 탭 줄만 바뀜 | SPEC-450, SPEC-417, SCR-186 | e2e(`apps/android/test/pet-decor.e2e.cjs`)와 api(`tests/test_decor.py`) | 지금 아이템 시험 자료 | 지금 시험 그대로 → `/chat/admin/items`에 탭 줄이 있고 '아이템'이 골라짐 | 지금 아이템 시험이 바꾸지 않고 통과. 탭 줄 하나가 더해진 것 말고 다르지 않음 | |
| TC-640 | 나뉘는 폭과 넓은 폭에서 가로로 넘치지 않음 | SPEC-458, REQ-585, REQ-581 | e2e(`admin.e2e.cjs`) | TC-637과 같은 가장 긴 상태(화면 일곱), 이름 12자, 메모 40자, 300자 노트 | 폭 360·768·1023·1024·1280·1440px, 낮·밤으로 각각 엶 → `document.documentElement.scrollWidth` → 본문 상자의 폭 → 칸마다 `getBoundingClientRect`로 칸끼리 겹침과 칸 밖으로 나간 요소 찾기 → 탭 줄의 `scrollWidth` | 모든 폭에서 페이지 `scrollWidth`가 화면 폭 이하. 360·768·1023px는 한 줄 기둥(칸 하나, 본문 720px 이하)이고 360·430px 결과는 TC-637과 같음. 1024·1280·1440px는 08 1.1절의 칸 수이고 본문 폭은 1024px에서 960px, 1280·1440px에서 1200px. 칸끼리 겹치지 않고 칸 밖으로 나간 요소 0개. 1024px 이상에서 탭 줄이 밀리지 않음(`scrollWidth`가 `clientWidth`와 같음). 화면마다 1280·1440px 스크린샷(합성 데이터 '시험친구 가'·'시험친구 나'만) | |
| TC-641 | 화면마다 넓은 배치의 칸과 상태 | SPEC-458, REQ-585, SCR-169, SCR-200, SCR-201, SCR-202, SCR-203, SCR-204, SCR-186 | e2e(`admin.e2e.cjs`) | TC-626\~630·633·636의 가짜 응답, 회원 `friendId` 7(이름이 같은 9도 있음) | 1280px로 08 1.1절 '상태가 놓이는 칸' 표의 상태를 엶(화면마다 #loading·일반·빈·오류 하나씩과 그룹 하나 실패, SCR-201은 #normal·#missing·#limits-saved·#ticket-added, SCR-202는 #creating·#created·#revoke-confirm) → 요소마다 어느 칸에 있는지 봄 → SCR-201에서 네트워크 요청 기록과 왼쪽 다른 줄 누름 → Tab 키로 끝까지 옮기며 차례 기록(360px와 견줌) → SCR-201#limits-edit를 연 채 창을 1280px에서 1000px로 줄였다 다시 늘림 | 상태마다 1.1절 표의 칸에 있음. 그룹 하나 실패는 그 칸만 바뀜. #loading의 회색 자리가 받은 뒤의 칸과 같은 자리. SCR-201: 왼쪽 줄 수가 API-236 `members` 수와 같고 7의 줄만 `aria-current="page"`(9의 줄은 아님), 요청은 API-236·API-267 한 번씩, 왼쪽 다른 줄은 그 사람의 경로로 감, #missing은 골라진 줄 없음, #limits-saved·#ticket-added 뒤 왼쪽 그 사람 줄도 같은 값. SCR-202의 만든 주소는 왼쪽 칸, 거두기 확인 줄은 그 줄 바로 아래. Tab 차례가 360px와 같음(SCR-201만 왼쪽 회원 줄이 맨 앞에 더해짐). 창 크기를 바꿔도 요청이 다시 가지 않고 열린 칸과 적던 숫자가 그대로. 1280·1440px, 낮·밤 | |

## ⑥ 초대 링크 거두기(TASK-498, D137)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-635 | 거두기 API | SPEC-455, REQ-583, API-281#200, API-281#403, API-281#404, API-281#409, API-281#500, API-281#503 | api(`tests/test_admin.py`) | 열린·쓴·기간 지난 링크, 다른 Origin, 없는 번호, 시험 시계(`sessions.now()`) | 열린 링크 거두기 → 같은 요청 다시 → 시험 시계를 만료 뒤로 옮겨 같은 요청 또 → 그 토큰으로 가입 → 쓴·기간 지난 링크 거두기 → 다른 Origin → `abc`·없는 번호 → UPDATE가 예외 → DB를 내림 → 가입과 거두기를 시험 잠금으로 동시에 | 200 `state: revoked`, 다시도 200이고 `revokedAt`이 처음 값, 만료 뒤에도 200(409가 아님), 가입은 지금의 거둔 링크 오류. 쓴·지난 링크 409 `invite_closed`이고 행이 그대로. 다른 Origin 403 `cross_site`. 404 `not_found`. 500, 503. 동시에는 하나만 성공. 로그 `admin_invite_revoke invite=<id> result=…`만(메모·이름 없음) | |
| TC-636 | 거두기 화면 | SPEC-455, REQ-583, SCR-202 | e2e(`admin.e2e.cjs`) | 가짜 API-281(200, 409) | '거두기' → '그만두기' → '거두기' → '거두기' 확인 → 409 응답 | '그만두기'는 요청 0번. 확인 뒤 1번이고 #revoked-now(띠 '링크를 거뒀어요', 줄이 '거둠'). 409는 #invite-closed 문구 | |

## ⑦ 반영 뒤(TASK-500)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-639 | 반영한 서버에서 화면 걷기와 동희님 확인 | SPEC-450\~458, REQ-570\~583, REQ-585 | server와 device | 운영 서버(읽기만) | GPT: 동희님 Access로 화면 경로 일곱 GET, 증명 없이 일곱 GET, API-280의 각 부분이 null인지만 확인, 로그 5분. 그다음 브라우저(Aside CLI, D65)로 화면 일곱을 360·430px와 1280px로 걸으며 가로 넘침과 오류만 봄(1280px는 넓은 배치인지도, D140 2-12). 운영 화면의 스크린샷과 화면 글은 저장소·PR·GitHub 댓글에 올리지 않음(친구 이름, 초대 메모, 마롱이 이름, 폰 순번, 알림 상태, 마지막 보고·사용 시각, 티켓 수가 보이고, GitHub 첨부 주소는 댓글을 지워도 남음). 스크린샷은 Orca 항목 댓글로 동희님께만 전하고, PR에는 상태 코드·null 여부와 '가로 넘침 없음/있음'만 적음. 동희님: 아이폰과 노트북에서 화면 여섯을 열어 봄(노트북에서는 넓은 배치) | 200 일곱, 403 일곱, `callMonth`·`images`·`app`·`usageToday`가 null이 아님(앱 업데이트 TASK-480 반영 전이면 `app`만 null), 로그에 오류 없음, 운영 화면에 가로 넘침 없음, 1280px는 넓은 배치(스크린샷은 Orca 항목에만). 동희님 말을 그 자리와 때와 함께 기록 | |

## 범위 확인

- 공통 규칙 9(차례로 부르기)와 공통#stale: TC-623, 626, 633.
- SPEC-450: TC-620, 621, 637, 638, 639. SPEC-451: TC-622\~626. SPEC-452: TC-627. SPEC-453: TC-628. SPEC-454: TC-629. SPEC-455: TC-635, 636. SPEC-456: TC-630, 634. SPEC-457: TC-631, 632, 633. SPEC-458: TC-640, 641, 639. 공통 규칙 8: TC-634.
- REQ-570: TC-620. REQ-571: TC-620, 637. REQ-572: TC-622, 626. REQ-573: TC-622, 625, 626. REQ-574: TC-627. REQ-575: TC-628. REQ-576: TC-629. REQ-577: TC-630. REQ-578: TC-630(요청이 API-267 하나, 단추 없음). REQ-579: TC-631, 633. REQ-580: TC-624, 630, 634. REQ-581: TC-637. REQ-582: TC-628. REQ-583: TC-635, 636. REQ-585: TC-640, 641, 639. REQ-584는 미룸이라 시험이 없어요.
- API-280이 나열한 응답: 200(TC-622·623), 403(TC-624), 500(TC-624), 503(TC-624). API-281: 200·403·404·409·500·503(TC-635). 바뀌지 않는 API-235\~243·266은 지금 시험(`test_unified_auth.py`, `test_usage_limit.py`, `test_scene_picture.py`)이 그대로 통과해야 해요. API-267은 PR #101의 TC-613이 봐요.
- TC-640·641은 체크포인트 뒤 고침인 노트북 폭(D140)이 썼어요. 남는 번호 TC-642\~669는 REQ-584(셸 명령을 화면으로, D138로 미룸)를 2026-12-23 뒤에 넣기로 할 때와 그 밖의 체크포인트 뒤 고침에 써요.
- 사람이 보지 않으면 모르는 것: 손볼 일 문구가 동희님께 쓸모 있는지, 24시간·80% 문턱이 맞는지, 동희님 노트북의 실제 폭(확대 비율)에서 넓은 배치가 보기 좋은지. TC-639의 동희님 확인과 그 뒤 말로 고쳐요.
