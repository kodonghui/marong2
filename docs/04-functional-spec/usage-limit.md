# 마롱이 사람별 사용 한도와 내 사용량: 기능 명세

상태: 초안(2026-11-21 KST, Claude). 이 문서의 행은 모두 proposed예요. 구현·서버 반영은 GPT가 하고(D60), PR 합치기는 동희님이 해요.
입력: [요구사항](../02-prd/usage-limit.md) REQ-484\~490, [사용자 흐름](../03-user-flow/FL-179-usage-limit.md) FL-179와 [FL-177](../03-user-flow/FL-177-usage.md), [도메인](../01-domain/usage-limit.md)의 TERM-199\~200, 통합 앱 명세 [unified.md](unified.md)의 SPEC-390·394·395와 3.12절, 동희님이 2026-11-21 15:46 KST 프로젝트 채팅에 올린 관리자 화면 사진("날짜는 왜 이따위임").
뒤 단계: 05 표는 `marong/migrations/021_usage_limit.sql`과 `marong/call/migrations/009_usage_limit.sql`, 06 API는 API-243과 바뀌는 API-216·234·236·240, 08 화면은 SCR-165·169와 SCR-107·001의 막힘 안내, 10 작업은 TASK-411\~419, 12 시험은 TC-496\~509가 이 SPEC 번호를 따라가요.
기준 코드: `main` `ad9f2f4`. 표시: [사실] 코드·기록에서 확인, [새 제안] Claude가 새로 정한 숫자·문구·이름, [추정] 근거 있는 짐작, [확인 안 함] 아직 보지 않은 것.
ID 번호: SPEC-397\~399.

## 1. 공통 규칙

통합 앱 명세 [1절](unified.md#1-공통-규칙)을 그대로 따라요(응답 모양, 오류 코드, 로그, 시각, 비동기). 더하는 것만 적어요.

1. 계정 한도(TERM-199)는 프로필 표(TBL-167)의 칸 셋이에요: `usage_unlimited`, `daily_units`, `call_monthly_usd`. CTX-027의 API(이름·캐릭터·목소리 바꾸기, API-217·226·228)는 이 칸을 바꾸지 않아요. 바꾸는 곳은 관리자 API-243 하나와 마이그레이션 021뿐이에요.
2. 유효 한도는 한 함수에서만 계산해요(3.1). 앱 서버와 통화 서버가 같은 함수를 불러요.
3. 이번 달 그 사람의 통화 비용은 DB 함수 하나(`call.friend_month_usd`, 3.2)에서만 계산해요. 통화 서버의 막기와 앱 서버의 비율·관리자 화면이 같은 값을 읽어요.
4. 돈 값은 API에서 소수 둘째 자리까지의 문자열이에요(예: `"5.00"`). 부동소수로 바꾸지 않아요[새 제안].
5. 로그: 관리자가 한도를 바꾸면 `admin_limits friend=<id> mode=<mode>`만 남겨요. 이름과 사용량 숫자는 남기지 않아요.
6. 설정값(바뀌는 줄):

| 설정값 | 값 | 기본 | 쓰는 곳 |
| --- | --- | --- | --- |
| `MARONG_DAILY_UNITS` | 사용 단위. 이제 기본 한도(TERM-200)예요. 계정 한도가 '기본'이거나 하루 숫자가 빈 계정에만 걸려요 | 비움 | SPEC-397 |
| `MARONG_CALL_PERSON_MONTHLY_USD` | 달러. 이제 기본 한도(TERM-200)예요. 계정 한도가 '기본'이거나 통화 월 숫자가 빈 계정에만 걸려요 | 비움 | SPEC-397 |

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-397 | 계정 한도와 유효 한도 | REQ-484, REQ-485, REQ-486, REQ-490, FL-179, FL-177, D106 | 마이그레이션 021과 통화 009가 적용됨. 프로필 행이 있는 친구 | 마이그레이션 021이 프로필 표에 칸 셋을 더하고, 칸을 처음 더하는 그 실행에서만 이미 있는 모든 행을 `usage_unlimited = true`로 바꿔요(REQ-490). 새 행의 기본은 `false`·`null`·`null`('기본')이에요. 가입·잇기 코드(SPEC-373)는 고치지 않아요.<br>유효 한도는 3.1의 함수 하나로 계산해요. 하루 한도 확인(`Usage.blocked`)과 티켓 빼기(`Usage._write`)는 지금 읽는 프로필 행에서 세 칸을 같이 읽어 그 사람의 유효 하루 한도로 판단해요. 서버 설정값 `MARONG_DAILY_UNITS`는 기본 한도로만 쓰여요.<br>통화 서버는 통화 홈 상태(API-124)와 통화 시작(API-107)에서 그 사람의 유효 통화 월 한도를 계산하고, 값이 있을 때만 `call.friend_month_usd`(3.2)를 불러 합이 한도 이상이면 지금처럼 `budget_exhausted`로 거절해요. 값이 없으면 합을 읽지 않아요 | 프로필 행 없음 → 지금처럼 사람별 한도 없음(막지 않음, 티켓 안 빠짐)<br>한도 읽기 DB 오류 → 지금처럼 막지 않고 `usage_failed lookup` 로그<br>통화 합 읽기 실패·1초 넘음 → 지금처럼 막지 않고 `personal_call_budget_unknown` 로그<br>설정값이 숫자가 아님 → 지금처럼 서버 시작 실패<br>세 칸의 조합이 틀림(무제한인데 숫자 있음) → DB 제약이 거절 | Given 프로필 2행이 있는 DB, When 021 적용, Then 두 행 모두 `usage_unlimited = true`. Then 새로 넣은 행은 `false`·`null`·`null`<br>Given 021을 한 번 더 적용, Then 관리자가 '기본'으로 바꾼 행이 무제한으로 돌아가지 않음<br>Given 무제한 계정, `MARONG_DAILY_UNITS=10`, 오늘 단위 50, 티켓 5, When 글 보내기, Then 202이고 티켓 5, `tickets_used` 0<br>Given '기본' 계정, 설정값 비움, When 오늘 단위 5000, Then 막지 않음<br>Given 직접(하루 10) 계정, 설정값 비움, 오늘 단위 10, 티켓 0, Then 글 보내기 429 `daily_limit`, 통화 시작 메시지 `daily_limit`<br>Given 직접(통화 월 5.00) 계정, 이번 달 합 5.10, Then 통화 시작 메시지 `budget_exhausted`. Given 무제한 계정, `MARONG_CALL_PERSON_MONTHLY_USD=1`, 이번 달 합 5.00, Then 통화 시작됨<br>Given 유효 통화 월 한도 없음, Then `call.friend_month_usd`를 부르는 쿼리가 0번<br>Given 전체 예산 100%, Then 무제한 계정의 통화도 지금처럼 거절<br>Given `usage_unlimited = true`, `daily_units = 5`로 UPDATE, Then 제약 오류 | proposed |
| SPEC-398 | 관리자 화면: 계정 한도 바꾸기와 날짜 표시 | REQ-487, REQ-484, REQ-489, REQ-431, REQ-438, FL-179, D106, 동희님 관찰(11/21 15:46 KST) | Access를 지난 관리자(SPEC-395) | 회원 목록(API-236)의 줄마다 `limits`(`mode`, `dailyUnits`, `callMonthlyUsd`), `effective`(유효 한도), `callMonthUsd`(이번 달 통화 비용, UTC 달)가 더해지고, 응답 맨 위에 `defaults`(기본 한도 둘)가 더해져요.<br>계정 한도 바꾸기 API-243 `PUT /chat/admin/api/members/{friendId}/limits` `{mode, dailyUnits?, callMonthlyUsd?}`: `unlimited` → (참, 비움, 비움), `default` → (거짓, 비움, 비움), `custom` → (거짓, 넣은 값). `custom`은 둘 가운데 하나 이상이 있어야 하고, 빈 쪽은 기본 한도를 따라요. UPDATE 하나로 바꾸고 200 `{limits, effective}`. 지금 값과 같으면 200이고 아무것도 바뀌지 않아요. 바꾼 값은 그 친구의 다음 요청부터 적용돼요(서버 재시작 없음).<br>초대 링크 목록(API-240)의 줄마다 `createdAt`, `usedAt`, `revokedAt`이 더해져요. 화면은 날짜마다 이름표를 붙여요(3.4): 쓴 링크는 '만든 때 · 쓴 때', 열린 링크는 '만든 때 · 만료(며칠 남음)', 기간 지난 링크는 '만든 때 · 만료됨', 거둔 링크는 '만든 때 · 거둔 때' | Access 없음·동희님 아님 → 403 `not_allowed`<br>Origin이 다름 → 403 `cross_site`<br>`mode`가 목록 밖, `custom`인데 둘 다 비움, 범위 밖(하루 1\~100000 정수, 통화 월 `0.01`\~`1000.00`, 소수 둘째 자리까지), `unlimited`·`default`에 숫자가 있음 → 400 `invalid_input`<br>없는 친구, 프로필 행 없는 친구 → 404 `not_found`<br>이번 달 통화 비용 읽기 실패·1초 넘음 → 그 응답의 `callMonthUsd`를 모두 `null`로 두고 목록은 200, `admin_call_month_unknown` 로그 | Given `{mode: "unlimited"}`, Then 행이 (참, 비움, 비움)이고 응답 `effective`가 둘 다 null<br>Given `{mode: "custom", dailyUnits: 200}`, 설정값 `MARONG_CALL_PERSON_MONTHLY_USD=3`, Then 행이 (거짓, 200, 비움)이고 `effective` `{dailyUnits: 200, callMonthlyUsd: "3.00"}`<br>Given `custom`에 둘 다 없음, `dailyUnits` 0·100001·"abc", `callMonthlyUsd` "0"·"1000.01"·"1.234", `unlimited`에 `dailyUnits` 5, Then 모두 400이고 행이 그대로<br>Given 일반 회원의 로그인 쿠키만 있는 요청, Then 403<br>Given 한도를 10으로 바꾼 직후, When 그 친구가 단위 10에서 티켓 0으로 글 보내기, Then 429(재시작 없이)<br>Given 쓴 초대 링크 하나, Then API-240 줄에 `createdAt`·`usedAt`이 있고 화면 줄이 '만든 때 11월 21일 오후 2:59 · 쓴 때 11월 21일 오후 3:01' 모양 | proposed |
| SPEC-399 | 내 사용량 보기 | REQ-488, REQ-489, FL-179, D106 | 로그인된 친구(프로필 행 있음) | 오늘 사용량(API-234)과 프로필(API-216)의 `usageToday`가 한 함수에서 같은 모양을 줘요: `{day, chatTurns, callSeconds, images, units, tickets, limit, callMonth}`. `limit`은 그 사람의 유효 하루 한도(없으면 null). `callMonth`는 `{limited, percent, resetsAt}`: 유효 통화 월 한도가 없으면 `limited = false`이고 나머지는 null, 있으면 `percent` = 내림(이번 달 합 ÷ 한도 × 100)과 `resetsAt` = 다음 UTC 달 1일 00:00(한국 시각 1일 09:00)이에요. 친구에게 달러 값은 주지 않아요.<br>'내 마롱이'(SCR-165)의 카드 이름이 '오늘 쓴 양'에서 '내 사용량'으로 바뀌고 3.3의 줄을 보여요. 앱과 웹은 같은 화면이에요.<br>모든 값은 로그인한 친구의 id로만 읽어요. 경로나 요청에 다른 친구 id가 없고, 응답에 다른 사람의 값이 없어요(REQ-489).<br>하루 한도 막힘 안내(SCR-107#daily-limit, SCR-001#daily-limit)에 '내 사용량 보기'(SCR-165) 링크를 둬요 | 이번 달 통화 합 읽기 실패·1초 넘음 → `callMonth` `{limited: true, percent: null, resetsAt}`이고 200. 화면은 그 줄만 '이번 달 통화 양은 지금 못 불러왔어'<br>오늘 사용량 읽기 실패 → 지금처럼 SCR-165#usage-error<br>`percent`가 100을 넘음(통화 중에 넘은 경우) → 그대로 주고 화면 막대는 100에서 멈춤 | Given 무제한 계정, Then API-234 `limit` null, `callMonth.limited` false, 화면 '하루 한도 무제한', '이번 달 통화 무제한'<br>Given 직접(하루 1000, 통화 월 5.00), 오늘 단위 320, 이번 달 합 2.00, Then `limit` 1000, `callMonth.percent` 40, 화면 막대 둘과 '오늘 320 / 1000', '40% 썼어 · 12월 1일 오전 9시에 다시 채워져'<br>Given 시험친구 가·나, When 가의 쿠키로 API-234·API-216, Then 응답 어디에도 나의 사용량·한도·이름이 없음<br>Given 직접(통화 월 5.00)이고 통화 합 함수가 실패, Then 200이고 그 줄만 못 불러왔다는 문구<br>Given API-216의 `usageToday`와 같은 때의 API-234, Then 두 값이 같음 | proposed |

## 3. 세부 규칙

### 3.1 유효 한도

`marong/usage.py`에 입출력이 없는 함수 하나로 둬요(이름은 구현이 정해요. 예: `effective_limits(profile, defaults)`).

```text
입력: 프로필 행의 usage_unlimited, daily_units, call_monthly_usd
      기본 한도 default_daily(MARONG_DAILY_UNITS, 없으면 None), default_call(MARONG_CALL_PERSON_MONTHLY_USD, 없으면 None)
usage_unlimited가 참   → (None, None)
아니면                 → (daily_units 또는 default_daily, call_monthly_usd 또는 default_call)
프로필 행이 없음        → (None, None)   (지금과 같음)
```

- `Usage(pool, limit)`의 `limit`은 이제 기본 하루 한도예요. `get`·`blocked`·`_write`는 이미 읽는 `friend_profiles` 행에서 세 칸을 같이 읽어 위 함수로 그 사람의 하루 한도를 얻어요. 쿼리 수는 늘지 않아요.
- `blocked`: 유효 하루 한도가 없으면 거짓. 있으면 지금처럼 `units >= 한도 AND tickets = 0`.
- `_write`: 유효 하루 한도가 없으면 티켓을 빼지 않아요. 있으면 지금 식 그대로(`min(tickets, max(0, units - max(old, 한도)))`).
- 통화 서버: `server.py`의 `PERSONAL_BUDGET`은 기본 통화 월 한도로만 쓰여요. 사람의 유효 통화 월 한도는 로그인 확인 때 이미 읽는 사람 정보에 세 칸을 더해 같은 함수로 얻어요[새 제안]. `personal_budget_blocked`는 `(store, friend, limit)`로 바뀌고 한도가 없으면 바로 거짓이에요.

### 3.2 이번 달 통화 비용(`call.friend_month_usd`)

- 통화 009가 만드는 SQL 함수예요: `call.friend_month_usd(p_friend bigint, p_start timestamptz, p_end timestamptz) RETURNS numeric`. 몸통은 지금 `call_cost.py`의 `personal_budget_blocked` SQL과 같은 식이고, 사람을 `call.callers.friend_id = p_friend`로 찾아요. 그 친구의 통화 계정이 없으면 0이에요.
- `SECURITY DEFINER`, `STABLE`, `SET search_path = pg_catalog, call`. `PUBLIC`의 실행 권한은 빼고 `marong`(앱 서버)과 `marong_call`(통화 서버)에만 줘요. 앱 서버 역할은 통화 비용 표를 직접 읽지 못하는 채로 이 합만 받아요[새 제안].
- 달 경계는 지금처럼 UTC 달(`call_cost.bounds`)이에요. 부르는 쪽이 `p_start`·`p_end`를 넘겨요.
- 시험: 지금 `tools/vertex_live/test_call_cost.py`의 개인 상한 시험 자료(합 0.036)로 함수 값이 같은지 봐요.

### 3.3 '내 사용량' 카드 문구(SCR-165)

| 줄 | 한도 없음 | 한도 있음 |
| --- | --- | --- |
| 오늘 | '오늘 · 글 답 12번 · 통화 8분 · 그림 1장'(지금 줄 그대로) | 같음 |
| 하루 한도 | '하루 한도 · 무제한' | 막대(`units`/`limit`)와 '오늘 320 / 1000'. 넘으면 지금 문구('오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져' 또는 티켓으로 이어 가는 문구) |
| 티켓 | 잔액이 0이면 줄 없음, 있으면 '티켓 3장' | 같음 |
| 이번 달 통화 | '이번 달 통화 · 무제한' | 막대(100에서 멈춤)와 '40% 썼어 · 12월 1일 오전 9시에 다시 채워져'. 100 이상이면 '이번 달 통화를 다 썼어. 12월 1일 오전 9시에 다시 채워져'. `percent`가 null이면 '이번 달 통화 양은 지금 못 불러왔어' |

- 날짜는 한국 시각이고 3.4의 짧은 모양이에요. 문구는 [새 제안]이에요.
- '무제한' 줄에는 막대를 그리지 않아요.

### 3.4 관리자 화면의 날짜 표시(SCR-169)

지금 화면(`marong/app_chat_static/admin.js`)은 초대 링크 줄에 상태와 만료 시각만 이름표 없이 보여요(`date(inv.expiresAt)`). 그래서 오늘 만든 링크에 7일 뒤 날짜가 보여요[사실]. API-240에는 만든 때·쓴 때가 없어요[사실].

- 날짜 모양: 한국 시각, 올해면 '11월 21일 오후 2:59', 다른 해면 '2025년 11월 21일 오후 2:59'[새 제안]. 공통 함수(`unified.js`의 `date`)는 다른 화면도 쓰므로, 관리자 화면과 '내 사용량'에서 쓰는 짧은 모양 함수를 따로 둬요.
- 초대 링크 줄: 첫 줄 '종류 · 메모', 둘째 줄 상태(쓴 링크는 '씀(쓴 사람)'), 셋째 줄 날짜:

| 상태 | 셋째 줄 |
| --- | --- |
| 열림 | '만든 때 11월 21일 오후 2:59 · 만료 11월 28일 오후 2:59(7일 남음)' |
| 씀 | '만든 때 11월 21일 오후 2:59 · 쓴 때 11월 21일 오후 3:01' |
| 기간 지남 | '만든 때 11월 12일 오후 7:16 · 만료됨 11월 19일 오후 7:16' |
| 거둠 | '만든 때 11월 12일 오후 7:16 · 거둔 때 11월 13일 오전 9:00' |

- 새 링크를 만든 칸(#created)의 날짜에도 '만료'를 붙여요: '만료 11월 28일 오후 2:59(7일 뒤)'.
- 가입한 사람 줄의 '마지막 사용'도 같은 짧은 모양이에요.

### 3.5 관리자 화면의 계정 한도(SCR-169)

- '가입한 사람' 그룹 위에 한 줄: '기본 한도 · 하루 {n 또는 없음} · 통화 월 {$n 또는 없음}'. 서버 설정값이라 화면에서 바꾸지 않아요.
- 사람 줄에 한 줄 더: '한도 · 무제한' 또는 '한도 · 기본(하루 없음 · 통화 월 없음)' 또는 '한도 · 직접(하루 200 · 통화 월 $5.00)', 그리고 '이번 달 통화 $1.23'(읽기 실패면 '이번 달 통화 —').
- 버튼 '한도 바꾸기' → 칸: 칩 셋('무제한', '기본 한도', '직접 정하기'). '직접 정하기'를 고르면 숫자 칸 둘('하루 사용 단위', '통화 월 달러')과 안내 '비운 칸은 기본 한도를 따라요'. '저장' → API-243 → 200이면 그 줄을 응답 값으로 바꾸고 띠 '한도를 바꿨어요'. 400이면 칸 아래 '숫자를 확인해 주세요(하루 1\~100000, 통화 월 0.01\~1000)'.

### 3.6 기존 명세가 바뀌는 곳

이 명세가 반영되면 아래 행의 본문을 고쳐요. 고치는 일은 구현 PR에서 하고, 여기에는 무엇이 바뀌는지만 적어요.

| 기존 | 문서 | 처리 | 바뀌는 내용 | 따르는 곳 |
| --- | --- | --- | --- | --- |
| SPEC-390 통화 예산 사람별 상한 | [unified.md](unified.md) | 바꿈 | 상한이 `MARONG_CALL_PERSON_MONTHLY_USD` 하나에서 그 사람의 유효 통화 월 한도로. 합 계산은 `call.friend_month_usd`로 옮김. 거절 메시지·끊지 않는 규칙·실패 처리는 그대로 | SPEC-397 |
| SPEC-394 사용량 세기와 한도 | [unified.md](unified.md) | 바꿈 | '한도는 `MARONG_DAILY_UNITS`가 있을 때만'을 '그 사람의 유효 하루 한도가 있을 때만'으로. API-234·216의 모양에 `callMonth`가 더해지고 `limit`이 유효 하루 한도가 됨. 세는 때·단위 식·티켓 식은 그대로 | SPEC-397, SPEC-399 |
| SPEC-395 관리자 화면 | [unified.md](unified.md) | 바꿈 | 회원 목록에 계정 한도·유효 한도·이번 달 통화 비용·기본 한도, 초대 링크 목록에 만든 때·쓴 때·거둔 때, 새 API-243 | SPEC-398 |
| SPEC-373 가입 때 만드는 것 | [unified.md](unified.md) | 그대로 | 새 프로필 행은 칸 기본값으로 '기본'이 돼서 코드가 바뀌지 않음 | SPEC-397 |
| 3.12 사용량, 단위, 한도, 티켓 | [unified.md](unified.md#312-사용량-단위-한도-티켓spec-394) | 바꿈 | 한도 문단의 `MARONG_DAILY_UNITS`를 '유효 하루 한도(SPEC-397 3.1)'로, API-234의 `limit` 설명을 같은 뜻으로 | SPEC-397 |

## 4. 받아들임 조건이 닿는 곳

| SPEC | 요구사항 | 흐름 | API | 화면 | 표 |
| --- | --- | --- | --- | --- | --- |
| SPEC-397 | REQ-484, REQ-485, REQ-486, REQ-490 | FL-179, FL-177 | API-103, API-107, API-124(바뀌는 거절 근거) | SCR-107, SCR-001 | TBL-167, TBL-172, `call.friend_month_usd` |
| SPEC-398 | REQ-487, REQ-484, REQ-431, REQ-438 | FL-179 | API-243, API-236, API-240 | SCR-169 | TBL-167, TBL-164 |
| SPEC-399 | REQ-488, REQ-489 | FL-179 | API-234, API-216 | SCR-165, SCR-107, SCR-001 | TBL-167, TBL-172, `call.friend_month_usd` |
