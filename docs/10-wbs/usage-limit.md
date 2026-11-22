# 사람별 사용 한도와 내 사용량 작업 목록(10단계 WBS)

2026-11-21 16시대 KST 작성(Claude). 입력: 도메인 [usage-limit.md](../01-domain/usage-limit.md)(TERM-199·200, 바뀌는 CTX-029·006), 요구사항 [usage-limit.md](../02-prd/usage-limit.md)(REQ-484\~490), 흐름 [FL-179](../03-user-flow/FL-179-usage-limit.md), 기능 명세 [usage-limit.md](../04-functional-spec/usage-limit.md)(SPEC-397\~399), 표 [021_usage_limit.sql](../../marong/migrations/021_usage_limit.sql)·[통화 009_usage_limit.sql](../../marong/call/migrations/009_usage_limit.sql)(설명 [05-erd/usage-limit.md](../05-erd/usage-limit.md)), 계약 [unified.openapi.yaml](../../api/unified.openapi.yaml) 0.2.0-draft(API-243, 바뀌는 API-216·234·236·240), 화면 상태 [08-screens/usage-limit.md](../08-screens/usage-limit.md)(SCR-165·169·107·001), 시험 계획 [12-qa/usage-limit.md](../12-qa/usage-limit.md)(TC-496\~509).

## GPT 인계

- 목표: 계정마다 사용 한도(무제한·기본·직접 숫자)를 두고, 각자 앱과 웹의 '내 마롱이'에서 자기 사용량과 한도를 봐요. 지금 쓰는 사람은 모두 무제한이에요. 관리자 화면의 초대 링크 날짜에 만든 때·쓴 때·만료 이름표를 붙여요. 동희님 2026-11-21 프로젝트 채팅: "야 근데 사람별 사용한도는 어디서 봐? 자기가 자기꺼. (지금은 기능만 만들고 현경이나 나나 등등은 무제한으로 해놔야댐)"(D106, 15:31 KST), "날짜는 왜 이따위임"(15:46 KST, 관리자 화면 사진).
- 시작: 설계는 `main`에 있어요(PR #78·#80). `main` 머리(2026-11-21 16:44 KST에 `986c730`)에서 새 브랜치 `codex/usage-limit`. 초안 PR 하나예요. 시작 허락은 D118(2026-11-21 16:47 KST "야 넥서스 하지 말고 걍 작업해")이에요.
- 읽을 것: [기능 명세](../04-functional-spec/usage-limit.md)의 SPEC-397\~399와 3.1\~3.6절, [계약](../../api/unified.openapi.yaml)의 API-243과 API-216·234·236·240(머리 설명의 14\~18번), [마이그레이션 021](../../marong/migrations/021_usage_limit.sql)·[통화 009](../../marong/call/migrations/009_usage_limit.sql), [화면 상태](../08-screens/usage-limit.md), [시험 계획](../12-qa/usage-limit.md)의 TC-496\~509. 이 밖의 문서는 읽지 않아도 돼요.
- 화면 모양: [와이어프레임](https://claude.ai/artifact/W1E3o6x6THzQ1oTbYxtcey)(원본 [`design/usage-limit-wireframe.html`](../../design/usage-limit-wireframe.html))은 상태와 문구를 눌러 보는 용이에요. 실제 화면은 지금 `unified.css`·`chat.css`의 부품과 얼린 토큰만 써요. 새 토큰은 없어요.
- 이미 된 것: 설계와 마이그레이션 두 파일이에요. 2026-11-21에 버리는 Postgres(`pgserver`, 합성 행)에서 확인했어요: 백필·다시 돌리기·제약·권한, 그리고 `call.friend_month_usd`가 지금 `personal_budget_blocked`의 합(TC-173 자료로 0.036)과 같음([표 문서 3절](../05-erd/usage-limit.md#3-검사2026-11-21-kst-claude-버리는-pgserver-db-합성-행만)). 운영 DB에는 적용하지 않았어요. 코드는 아직 아무것도 바꾸지 않았어요.
- 순서: TASK-411 → 412 → (413, 414, 415) → (416, 417) → 418 → 419. 413·414·415는 서로 다른 파일이라 같이 해도 돼요. 화면(416·417)은 API(414·415)가 끝난 뒤예요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node와 Playwright(화면). 모델·결제 API는 부르지 않아요. 통화 비용 합은 `tools/vertex_live/test_call_cost.py`처럼 합성 행으로 만들어요. 시험 데이터는 합성 데이터만이에요.
- 반영: 서버 반영을 해요(TASK-419). ① DB와 바뀌는 파일 백업, 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-usage-limit/`에 먼저 둠 ② 마이그레이션 021 → 통화 009(마이그레이션 관리자 역할로, 두 번 돌려도 됨) ③ 앱 서버와 통화 서버 파일 ④ 앱 서버의 설정에 통화 서버와 같은 `MARONG_CALL_PERSON_MONTHLY_USD` 값이 있게 함(값은 출력하지 않고 두 서비스의 값이 같은지만 확인. 앱 서버가 기본 통화 월 한도를 계산할 때 써요) ⑤ 통화가 없을 때만 두 서비스 재시작 ⑥ 확인: `usage_unlimited`가 거짓인 프로필 수가 0(반영 전 프로필 수와 같은 수가 참), 로그 5분 오류 없음, 동희님 계정으로 API-234가 `limit: null`과 `callMonth.limited: false`. 켜고 끄는 설정은 따로 두지 않아요: 모두 무제한으로 시작해서 반영만으로는 누구의 동작도 바뀌지 않아요. 11/15 상시 반영 허락('만들어지는대로 계속 넣어')에 들어가요.
- 하면 안 되는 것: 반영 때 누구의 한도를 '기본'이나 '직접'으로 바꾸기(동희님이 관리자 화면에서 직접 해요). 친구 응답(API-216·234)에 달러 값 넣기. 전체 통화 예산(150달러, 80·100·120% 규칙), 그림 월 예산, 전체 합계 한도(검색·쇼핑 읽기·통화 검색·먼저 말 걸기), 동시 통화 상한을 계정 한도로 풀기. 앱 서버 역할에 통화 비용 표 읽기 권한 주기(합은 `call.friend_month_usd`로만). 공통 날짜 함수(`unified.js`의 `date`) 바꾸기. 새 디자인 토큰. 티켓 판매·결제.
- 겹치는 파일: `marong/usage.py`, `tools/vertex_live/server.py`, `tools/vertex_live/call_cost.py`, `marong/app_profile.py`, `marong/app_admin.py`, `marong/app_chat_static/admin.js`·`profile.js`·`chat.js`, `tools/vertex_live/static/app.js`. 같은 날 열린 통화 연결 고치기(`tools/vertex_live/`)와 반려동물 앱 안 기능(D110\~117, 마이그레이션 022)이 겹칠 수 있어요. 먼저 합친 쪽에 맞춰요. 마이그레이션 번호는 021이 이 패키지, 022가 반려동물이에요.
- 사람 확인: TC-509(반영 뒤 동희님 아이폰 웹과 현경님 폰 앱에서 '내 사용량'이 '무제한'으로 보임, 동희님 관리자 화면의 날짜 이름표와 한도 줄). 현경님 폰은 동희님이 부탁해요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-496\~508 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TC-509의 서버 쪽 확인.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드가 답해요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_usage_limit.py                     # TC-496~506 (새 파일, 이름은 바꿔도 됨)
.venv/bin/python tests/test_unified_usage.py && .venv/bin/python tests/test_unified_profile.py && .venv/bin/python tests/test_unified_auth.py   # 기존 시험
for f in tools/vertex_live/test_*.py; do .venv/bin/python "$f" || exit 1; done   # 통화 서버 시험(test_call_cost.py 포함)
(cd apps/android && npm ci && npm test && npm run test:browser)  # 화면 TC-507·508. Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인해요
```

## 작업

- 담당: 모두 GPT예요. 서버 반영도 GPT가 해요(D65, AGENTS.md).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 약 6일이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-411 | 마이그레이션 021과 통화 009를 시험 DB에 넣기: `tests/pg.py`에 적용 함수(예: `apply_usage_limit()`, 020·008 뒤)를 더하고, 표 문서 3절의 확인을 저장소 시험으로 옮겨요 | SPEC-397 | TBL-167, `call.friend_month_usd`, `marong/migrations/021_usage_limit.sql`, `marong/call/migrations/009_usage_limit.sql`, `tests/pg.py` | 없음 | GPT | 0.5 | TC-496\~498 통과. 기존 `tests/test_unified_*.py` 통과 |
| TASK-412 | 유효 한도 함수 하나(명세 3.1, 입출력 없음)와 `Usage`의 사람별 판단: `blocked`와 `_write`가 같은 프로필 행에서 세 칸을 읽어 그 사람의 유효 하루 한도로 막고 티켓을 빼요. `MARONG_DAILY_UNITS`는 기본 한도로만. 프로필 행이 없거나 읽기 실패면 지금처럼 막지 않음 | SPEC-397 | `marong/usage.py`, `tools/vertex_live/call_memory.py`(같은 `Usage`를 씀) | TASK-411 | GPT | 1 | TC-499·500 통과. `tests/test_unified_usage.py` 통과 |
| TASK-413 | 통화 서버의 사람별 통화 월 한도: 통화 홈 상태(API-124)와 통화 시작(API-107)이 그 사람의 유효 통화 월 한도를 계산하고, 있을 때만 `call.friend_month_usd`로 합을 읽어 넘으면 `budget_exhausted`. 없으면 합을 읽지 않음. `personal_budget_blocked`는 친구 id와 한도를 받게 바꾸고 SQL은 함수로 옮김. `PERSONAL_BUDGET`은 기본 한도로만. 읽기 실패·1초 넘음은 지금처럼 막지 않고 `personal_call_budget_unknown` | SPEC-397 | `tools/vertex_live/server.py`, `tools/vertex_live/call_cost.py`, `tools/vertex_live/test_call_cost.py` | TASK-412 | GPT | 1 | TC-501 통과. `tools/vertex_live/test_*.py` 통과 |
| TASK-414 | 내 사용량 API: API-234와 API-216의 `usageToday`를 한 함수에서 같은 `Usage` 모양으로(`limit` = 유효 하루 한도, `callMonth` = `{limited, percent, resetsAt}`). 앱 서버도 `MARONG_CALL_PERSON_MONTHLY_USD`를 기본 한도로 읽고, 한도가 있을 때만 `call.friend_month_usd`를 1초 제한으로 불러요. 실패면 `percent`만 null | SPEC-399 | API-234, API-216, `marong/app_profile.py`, `marong/usage.py` | TASK-412 | GPT | 1 | TC-502·503 통과. 두 API의 응답마다 계약 스키마에 맞음 |
| TASK-415 | 관리자 API: API-236에 `defaults`와 줄마다 `limits`·`effective`·`callMonthUsd`(합 읽기 실패면 모두 null, `admin_call_month_unknown`), 새 API-243 `PUT /chat/admin/api/members/{friendId}/limits`(검사, UPDATE 하나, 로그 `admin_limits friend=<id> mode=<mode>`만), API-240에 `createdAt`·`usedAt`·`revokedAt`. 달러는 소수 둘째 자리 문자열 | SPEC-398 | API-236, API-240, API-243, `marong/app_admin.py`, `marong/app_chat.py`(경로 더하기) | TASK-412 | GPT | 1 | TC-504\~506 통과. API-243이 나열한 응답(200·400·403·404·503)마다 시험 통과 |
| TASK-416 | '내 사용량' 카드(SCR-165): 그룹 이름을 '내 사용량'으로, 줄 넷과 상태(화면 정의 1절, 문구는 명세 3.3). 하루 한도 안내의 '내 사용량 보기' 링크(SCR-107 글 대화 띠, SCR-001 통화 홈). 날짜는 화면 정의 4절의 짧은 모양 | SPEC-399 | SCR-165, SCR-107, SCR-001, `marong/app_chat_static/profile.js`·`chat.js`·`unified.js`(짧은 날짜 함수 더하기만), `tools/vertex_live/static/app.js` | TASK-414 | GPT | 0.5 | TC-508 통과. 낮·밤 테마와 360px 폭에서 넘치지 않음 |
| TASK-417 | 관리자 화면(SCR-169): 초대 링크 날짜 줄(상태별 이름표, 명세 3.4), 새 링크 칸의 '만료 …(7일 뒤)', '마지막 사용'의 짧은 모양, 기본 한도 줄, 사람 줄의 한도와 이번 달 통화, '한도 바꾸기' 칸(명세 3.5) | SPEC-398 | SCR-169, `marong/app_chat_static/admin.js`·`admin.html` | TASK-415 | GPT | 0.5 | TC-507 통과 |
| TASK-418 | 기존 문서 맞추기(명세 3.6 표): `docs/04-functional-spec/unified.md`의 SPEC-390·394·395와 3.12 본문, `docs/08-screens/unified.md`의 SCR-165 '오늘 쓴 양' 줄과 SCR-169 표에 '바뀜 → usage-limit.md' 표시, README의 `MARONG_DAILY_UNITS` 설명. 새 설계를 쓰지 않고 3.6이 적은 내용만 옮겨요 | SPEC-397\~399 | 위 문서 | TASK-416, TASK-417 | GPT | 0.5 | 3.6 표의 행마다 고친 곳이 PR 설명에 있음. `git grep -n "MARONG_DAILY_UNITS"`로 남은 옛 설명이 없음 |
| TASK-419 | 서버 반영(GPT 인계의 '반영' ①\~⑥)과 되돌리기 준비 | SPEC-397\~399 | 운영 DB, 앱 서버, 통화 서버 | TASK-418 | GPT | 0.5 | TC-509의 서버 쪽 확인 통과. 백업·되돌리기 경로와 확인 숫자(개수만)가 PR 설명에 있음 |

## 확인

- 모든 TASK가 SPEC을 하나 이상 가리키고, SPEC-397\~399가 모두 TASK를 가져요(397: 411\~413·418·419, 398: 415·417·418·419, 399: 414·416·418·419).
- 끝 조건마다 시험이나 확인할 수 있는 결과가 있어요.
- 순서가 TASK ID와 같고 고리가 없어요.
- 열린 질문: 없어요. 운영 서버의 지금 설정값(`MARONG_DAILY_UNITS`, `MARONG_CALL_PERSON_MONTHLY_USD`, 앱 서버에 둘째 값이 있는지)은 설계 때 확인하지 못했어요(도메인 6절). 반영 ④에서 GPT가 '설정됨/비어 있음'과 두 서비스의 값이 같은지만 확인해요.

## 11단계 진행

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-411 | 시험 통과 | `e9a1309` | WSL의 임시 PostgreSQL에서 TC-496~498 통과. |
| TASK-412 | 시험 통과 | `61a8a70` | 계정별 판단, 동시 티켓 차감, 무제한 계정 확인. |
| TASK-413 | 시험 통과 | `61a8a70` | 통화 상태 및 시작 메시지, 합 조회 생략 및 제한 시간 확인. |
| TASK-414 | 시험 통과 | `61a8a70` | 프로필과 사용량 응답 일치, 계정 격리, 통화 월 합 조회 오류 확인. |
| TASK-415 | 시험 통과 | `61a8a70` | 관리자 변경과 권한, 200·400·403·404·503 응답, 날짜 필드 확인. |
| TASK-416 | 시험 통과 | `cc062eb` | Playwright에서 360px, 낮·밤 테마, 안내 링크 확인. |
| TASK-417 | 시험 통과 | `cc062eb` | Playwright에서 초대 링크 날짜와 한도 변경 확인. |
| TASK-418 | 완료 | | README, 기존 통합 기능 명세 및 화면 정의에 변경 내용 반영. |
| TASK-419 | 운영 서버·웹 확인 | `fef8bcf` | 2026-11-22 16:07:05 KST. 021 및 통화 009 적용. 기존 프로필 2개 중 무제한 2개, 제한 0개. 내 사용량 API 200과 하루·월 통화 무제한, 관리자 한도 변경 창 확인. 실제 폰 확인 대기. |
