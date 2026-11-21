# 사람별 사용 한도와 내 사용량: 시험 계획(12단계)

상태: 2026-11-21 16시대 KST 작성(Claude). 아직 돌리지 않았어요. 시험을 쓰고 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)). 작업은 [작업 목록](../10-wbs/usage-limit.md)의 TASK-411\~419예요.
입력: [기능 명세](../04-functional-spec/usage-limit.md) SPEC-397\~399의 받아들임 조건, 요구사항 REQ-484\~490, 흐름 [FL-179](../03-user-flow/FL-179-usage-limit.md), 계약 `api/unified.openapi.yaml` 0.2.0-draft(API-243, API-216·234·236·240), 화면 정의 [08-screens/usage-limit.md](../08-screens/usage-limit.md), 표 TBL-167과 `call.friend_month_usd`(`marong/migrations/021_usage_limit.sql`, `marong/call/migrations/009_usage_limit.sql`).

돌리는 법(`Runs as`)은 [통합 앱 시험 계획](unified.md)과 같아요: `unit`(함수 하나), `api`(`pgserver`의 빈 DB에 020·008·021·009를 적용하고 HTTP 경로를 부름, 시험 시계), `e2e`(Playwright Chromium 360·430px, 낮·밤 테마, 가짜 백엔드), `server`(반영한 서버에서 읽기 확인), `device`(사람이 실제 폰에서 봄). 진짜 모델과 결제 API는 부르지 않아요.

시험 데이터는 합성 데이터만 써요. 사람은 '시험친구 가'·'시험친구 나'이고, 통화 비용은 `tools/vertex_live/test_call_cost.py`처럼 지어낸 통화·토큰·단가 행으로 만들어요. 설정값은 시험 안에서만 정해요(`MARONG_DAILY_UNITS`, `MARONG_CALL_PERSON_MONTHLY_USD`). 운영 DB의 값, 친구 이름, 대화를 넣지 않아요.

## ① 표와 함수(TASK-411)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-496 | 있던 프로필은 무제한, 새 프로필은 기본 | SPEC-397, REQ-490, TBL-167 | api(`tests/test_usage_limit.py`) | 020·008까지 적용한 DB에 프로필 2행 | 021·009 적용 → 두 행 읽기 → 프로필 1행 더 넣기 | 앞 두 행은 (`usage_unlimited` 참, 비움, 비움). 새 행은 (거짓, 비움, 비움) | |
| TC-497 | 다시 돌려도 관리자 값이 남고, 틀린 조합은 DB가 막음 | SPEC-397, REQ-487, TBL-167 | api(`tests/test_usage_limit.py`) | TC-496의 DB | 한 행을 (거짓, 비움, 비움)으로 바꾼 뒤 021·009를 다시 적용 → 무제한인데 하루 5, 하루 0·100001, 통화 0·1000.01 UPDATE → 하루 200·통화 5 UPDATE | 바꾼 행이 무제한으로 돌아가지 않음. 틀린 UPDATE는 모두 제약 오류이고 행이 그대로. 하루 200·통화 5는 들어감 | |
| TC-498 | 통화 합 함수의 값과 권한 | SPEC-397, SPEC-399, `call.friend_month_usd` | api(`tests/test_usage_limit.py`) | TC-173과 같은 합성 통화(10,000·1,000 토큰, 단가 3·6), 다른 친구 하나, `usage_mode` 없이 닫힌 2분 구간 하나인 셋째 친구 | 이 친구의 이번 달 합 → 다른 친구의 합 → 다음 달 범위의 합 → 셋째 친구의 합 → `marong` 역할로 함수 실행과 `call.live_usage` 읽기 → `marong_call` 역할로 한도 칸 UPDATE → `PUBLIC` 실행 권한 확인 | 0.036(지금 `personal_budget_blocked`가 0.036에서 막고 0.037에서 막지 않는 것과 같음), 다른 친구 0, 다음 달 0, 셋째 친구 0.10(분당 0.05달러 어림). `marong`은 실행되고 표 읽기는 권한 오류. `marong_call`의 UPDATE는 권한 오류. `PUBLIC` 실행 권한 없음 | |

## ② 한도 적용(TASK-412·413)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-499 | 무제한 계정은 막지 않고 티켓도 빼지 않음 | SPEC-397, REQ-485, API-103#202 | api(`tests/test_usage_limit.py`) | '시험친구 가' 무제한, `MARONG_DAILY_UNITS=10`, 오늘 단위 50, 티켓 5 | 글 보내기(API-103) → 통화 홈 상태(API-124) → `usage_daily`와 티켓 읽기 | 202이고 답이 옴. API-124의 `canCall`이 참. 티켓 5 그대로, `tickets_used` 0. 사용량은 계속 셈(REQ-480) | |
| TC-500 | 직접 하루 한도와 기본 한도 | SPEC-397, REQ-486, API-103#429(`daily_limit`), API-107#101(메시지 `daily_limit`) | api(`tests/test_usage_limit.py`) | (가) 직접(하루 10), 설정값 비움, 오늘 단위 10, 티켓 0 (나) 기본, 설정값 비움, 오늘 단위 5000 (다) 기본, `MARONG_DAILY_UNITS=1000`, 오늘 단위 1000, 티켓 2 | 각각 글 보내기와 통화 시작 | (가) 429 `daily_limit`, 통화 시작은 메시지 `daily_limit` (나) 막지 않음 (다) 막지 않고 티켓이 넘은 만큼 빠짐(지금 티켓 식 그대로) | |
| TC-501 | 사람별 통화 월 한도 | SPEC-397, REQ-486, API-107#101(메시지 `budget_exhausted`), API-124#200 | api(`tools/vertex_live/test_call_cost.py`) | (가) 직접(통화 월 5.00), 이번 달 합 5.10 (나) 무제한, `MARONG_CALL_PERSON_MONTHLY_USD=1`, 합 5.00 (다) 유효 통화 월 한도 없음 (라) 무제한, 전체 예산 100% (마) 직접(5.00)이고 함수가 1초를 넘김 | 각각 API-124와 통화 시작. (다)는 DB 쿼리 기록을 셈 | (가) `budget_exhausted` (나) 통화가 시작됨 (다) `call.friend_month_usd` 쿼리 0번 (라) 지금처럼 거절 (마) 막지 않고 로그 `personal_call_budget_unknown` | |

## ③ 내 사용량(TASK-414)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-502 | 내 사용량 응답의 모양 | SPEC-399, REQ-488, API-234#200, API-216#200 | api(`tests/test_usage_limit.py`) | (가) 무제한 (나) 직접(하루 1000, 통화 월 5.00), 오늘 단위 320, 이번 달 합 2.00, 시험 시계 2026-11-21 (다) 직접(통화 월 5.00)이고 함수 실패 | API-234와 API-216을 같은 때 부름 | (가) `limit` null, `callMonth` `{limited: false, percent: null, resetsAt: null}` (나) `limit` 1000, `callMonth.percent` 40, `resetsAt` `2026-12-01T09:00:00+09:00` (다) 200이고 `percent`만 null. 세 경우 모두 응답에 달러가 없고, API-216의 `usageToday`가 API-234와 같음. 계약 스키마에 맞음 | |
| TC-503 | 자기 것만 보임 | SPEC-399, REQ-489, API-234#200, API-216#200 | api(`tests/test_usage_limit.py`) | 시험친구 가(무제한)·나(직접, 다른 숫자와 사용량) | 가의 쿠키로 API-234·API-216 → 나의 쿠키로 같은 요청 | 가의 응답 어디에도 나의 사용량·한도·이름이 없고, 나도 마찬가지. 경로·질의에 친구 id를 넣을 자리가 없음 | |

## ④ 관리자(TASK-415)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-504 | 계정 한도 바꾸기 | SPEC-398, REQ-487, API-243#200 | api(`tests/test_usage_limit.py`) | 시험친구 가, `MARONG_CALL_PERSON_MONTHLY_USD=3` | `{mode: unlimited}` → `{mode: custom, dailyUnits: 200}` → 같은 값 다시 → `{mode: custom, dailyUnits: 10}` 뒤 가가 단위 10·티켓 0으로 글 보내기 → `{mode: default}` | 첫째 행 (참, 비움, 비움)이고 `effective` 둘 다 null. 둘째 행 (거짓, 200, 비움)이고 `effective` `{dailyUnits: 200, callMonthlyUsd: "3.00"}`. 같은 값은 200이고 `updated_at`이 바뀌지 않음. 서버 재시작 없이 429 `daily_limit`. 로그는 `admin_limits friend=<id> mode=<mode>`뿐이고 이름·숫자가 없음 | |
| TC-505 | 바꾸기 거절 | SPEC-398, API-243#400(`invalid_input`), API-243#403(`not_allowed`), API-243#403(`cross_site`), API-243#404(`not_found`) | api(`tests/test_usage_limit.py`) | 시험친구 가, 프로필 없는 기존 친구 행 하나 | `custom`에 숫자 없음, `dailyUnits` 0·100001·"abc", `callMonthlyUsd` "0"·"1000.01"·"1.234", `unlimited`에 `dailyUnits` 5, `mode` "free" → 일반 회원 쿠키만 있는 요청 → 다른 `Origin` → 없는 친구 id와 프로필 없는 친구 | 400은 모두 행이 그대로. Access 증명이 없으면 403 `not_allowed`, 다른 Origin은 403 `cross_site`, 둘 다 404 `not_found` | |
| TC-506 | 회원 목록과 초대 링크 목록의 새 칸 | SPEC-398, REQ-484, REQ-431, API-236#200, API-240#200 | api(`tests/test_usage_limit.py`) | 무제한·기본·직접 회원 셋, 이번 달 합성 통화 비용, 초대 링크 넷(열림·씀·기간 지남·거둠) | API-236 → 함수가 실패하게 하고 API-236 → API-240 | `defaults`와 줄마다 `limits`·`effective`·`callMonthUsd`(소수 둘째 자리 문자열). 함수 실패면 모든 `callMonthUsd`가 null이고 200, 로그 `admin_call_month_unknown`. API-240 줄마다 `createdAt`, 쓴 링크만 `usedAt`, 거둔 링크만 `revokedAt`. 계약 스키마에 맞음 | |

## ⑤ 화면(TASK-416·417)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-507 | 관리자 화면의 날짜 이름표와 한도 바꾸기 | SPEC-398, REQ-487, REQ-431, SCR-169#invite-open, SCR-169#invite-used, SCR-169#invite-expired, SCR-169#invite-revoked, SCR-169#created, SCR-169#limits-edit, SCR-169#limits-custom, SCR-169#limits-invalid, SCR-169#limits-saved, SCR-169#call-month-unknown | e2e(Playwright) | TC-506과 같은 가짜 백엔드, 시험 시계 2026-11-21 15:50 KST | 관리자 화면을 엶 → 새 링크 만들기 → 사람 줄에서 '한도 바꾸기' → '직접 정하기'에 하루 0 → 200과 5.5 → 저장 → 통화 비용 실패 응답으로 다시 엶 | 초대 링크 줄의 날짜가 '만든 때 11월 21일 오후 2:59 · 만료 11월 28일 오후 2:59(7일 남음)', '… · 쓴 때 …', '… · 만료됨 …', '… · 거둔 때 …' 모양. 새 링크 칸에 '만료 …(7일 뒤)'. 하루 0은 '숫자를 확인해 주세요(하루 1~100000, 통화 월 0.01~1000)'이고 요청이 서버로 가더라도 행이 그대로. 저장 뒤 '한도 · 직접(하루 200 · 통화 월 $5.50)'과 띠 '한도를 바꿨어요'. 실패면 '이번 달 통화 —'. 360px에서 가로로 넘치지 않음 | |
| TC-508 | '내 사용량' 카드와 하루 한도 안내 링크 | SPEC-399, REQ-488, SCR-165#usage, SCR-165#usage-unlimited, SCR-165#usage-limit, SCR-165#usage-over, SCR-165#tickets, SCR-165#call-month-unlimited, SCR-165#call-month, SCR-165#call-month-over, SCR-165#call-month-unknown, SCR-165#usage-error, SCR-107#daily-limit, SCR-001#daily-limit | e2e(Playwright) | 가짜 API-234 응답 여섯(무제한, 한도 있음, 넘음·티켓, 넘음·티켓 0, 통화 합 실패, 500), 가짜 API-103 429와 API-124 `daily_limit` | 응답마다 SCR-165를 엶 → 글 대화에서 429를 받고 '내 사용량 보기' → 통화 홈의 막힘 상태에서 같은 링크 | 화면 정의 1절의 문구 그대로('하루 한도 · 무제한', '오늘 320 / 1000', '티켓 3장', '40% 썼어 · 12월 1일 오전 9시에 다시 채워져', '이번 달 통화를 다 썼어…', '이번 달 통화 양은 지금 못 불러왔어', '지금은 못 불러왔어'). 무제한 줄에는 막대가 없음. 달러가 화면 어디에도 없음. 두 링크가 SCR-165의 카드로 감. 낮·밤 테마와 360·430px에서 넘치지 않음 | |

## ⑥ 반영 뒤(TASK-419)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-509 | 운영에서 모두 무제한이고 자기 것이 보임 | SPEC-397, SPEC-399, REQ-490, REQ-488, D106 | server, device | 운영 DB(개수만 읽음), 동희님 아이폰 웹, 현경님 폰 앱 | 서버: 반영 전 프로필 수와 반영 뒤 `usage_unlimited`가 참인 수·거짓인 수를 읽음, 로그 5분. 동희님: 웹 '내 마롱이'와 관리자 화면을 봄. 현경님: 앱 '내 마롱이'를 봄(동희님이 부탁) | 참인 수 = 반영 전 프로필 수, 거짓인 수 0, 로그에 Traceback·ERROR 0. 두 사람의 '내 사용량'에 '하루 한도 · 무제한'과 '이번 달 통화 · 무제한'. 관리자 화면의 초대 링크 날짜에 이름표, 사람 줄마다 '한도 · 무제한' | |

## 범위 확인

- SPEC-397: TC-496\~501, 509. SPEC-398: TC-497, 504\~507. SPEC-399: TC-498, 502·503, 508, 509.
- REQ-484: TC-506. REQ-485: TC-499. REQ-486: TC-500·501. REQ-487: TC-497, 504, 507. REQ-488: TC-502, 508, 509. REQ-489: TC-503. REQ-490: TC-496, 509.
- API-243이 나열한 응답: 200(TC-504), 400·403·404(TC-505), 503은 TASK-415의 끝 조건에서 DB를 내린 시험으로 봐요. API-234·216의 200(TC-502·503), API-236·240의 200(TC-506).
- 브라우저 에이전트 걷기는 하지 않아요: 새 흐름이 화면 둘의 상태 바꿈이라 e2e 두 개(TC-507·508)와 사람 확인(TC-509)으로 봐요.
