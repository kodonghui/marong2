# 통합 앱(MVP) 작업 목록(10단계 WBS, CTX-026~029)

2026-11-19 10시대 KST 작성(Claude). 입력: 설계 제안 [unified-app.md](../unified-app.md)(동희님 승인 D104), 도메인 [unified.md](../01-domain/unified.md)(CTX-026\~029, TERM-173\~198), 요구사항 [unified.md](../02-prd/unified.md)(REQ-430\~483), 흐름 FL-169\~178([03-user-flow](../03-user-flow/)), 기능 명세 [unified.md](../04-functional-spec/unified.md)(SPEC-370\~396), 표 [020_unified.sql](../../marong/migrations/020_unified.sql)·[통화 008_unified.sql](../../marong/call/migrations/008_unified.sql)(TBL-164\~172, 그림은 [05-erd/unified.md](../05-erd/unified.md)), 계약 [unified.openapi.yaml](../../api/unified.openapi.yaml)(API-211\~242), 화면 상태 [unified.md](../08-screens/unified.md)(SCR-163\~174), 시험 계획 [12-qa/unified.md](../12-qa/unified.md)(TC-430\~495).

## GPT 인계

- 목표: 카카오톡과 디스코드 없이 안드로이드 앱과 웹만으로 마롱이를 쓰게 해요. 지인은 초대 링크로 가입하고, 사람마다 자기 마롱이(이름, 반려동물 캐릭터, 통화 목소리)를 가지며, 친구끼리 서로 이어요. 범위는 동희님 주변 사람이 쓰는 MVP예요. 동희님 2026-11-19 이 설계 스레드: "카톡/디코는 서비스 x. 이제 apk랑 웹(나는 아이폰이라 웹에서 해야해)에서만 할거야"(D92), "초대링크로 ㄱㄱ"(D97), "일단 MVP를 내는거지 지금 서비스를 내는게 아니잔아"(D103), 설계 제안에 "승인"(D104).
- 시작: 이 설계 PR(#54)이 `main`에 합쳐진 뒤 `main` 머리에서 패키지마다 새 브랜치 `codex/unified-u1`\~`codex/unified-u10`. 설계를 쓸 때의 `main`은 `0953b86`이에요. 패키지마다 초안 PR 하나예요.
- 먼저 할 일(TASK-379 앞): 운영 서버의 봇 코드가 `main`과 꼭 같지 않아요. 2026-11-19 04:22 KST에 다시 뜬 코드에서 4개 파일은 PR #53 머리와 같고, `marong/agent.py`·`marong/discord_dm.py`·`marong/llm.py`·`marong/app_chat.py`는 `main`과도 PR #53과도 달라요. 이 4개의 출처를 확인해 `main`에 맞춘 뒤에 시작해요(맞추는 방법이 설계에 닿으면 '설계 질문'으로).
- 읽을 것: [기능 명세](../04-functional-spec/unified.md)의 SPEC-370\~396과 상세 절, [계약](../../api/unified.openapi.yaml)의 API-211\~242, [마이그레이션 020](../../marong/migrations/020_unified.sql)·[통화 008](../../marong/call/migrations/008_unified.sql)의 TBL-164\~172와 바뀌는 칸, [화면 상태](../08-screens/unified.md)의 SCR-163\~174와 바뀌는 화면, [시험 계획](../12-qa/unified.md)의 TC-430\~495. 캐릭터 만들기는 반려동물 명세 [pet.md](../04-functional-spec/pet.md)의 SPEC-316\~325를 결제 조건만 빼고 그대로 따르므로 그 절도 읽어요. 배경은 [설계 제안](../unified-app.md)이고, 제안과 단계 문서가 다르면 단계 문서가 맞아요. 화면은 얼려 둔 토큰 103개([design/base.tokens.json](../../design/base.tokens.json))와 지금 `chat.css`의 부품만 쓰고, 이 패키지의 목업은 따로 그리지 않았어요(09 건너뜀, 방향은 반려동물 A안과 지금 글 대화 화면).
- 이미 된 것: 설계만이에요(01\~08, 10과 12 시험 계획). 마이그레이션 두 파일은 초안이에요. 2026-11-19에 임시 Postgres 16.2(`pgserver`, 합성 행)에서 두 번 적용해 확인 44개가 통과했고([표 문서 8절](../05-erd/unified.md)), 운영 DB에는 적용하지 않았어요. 가져다 쓸 코드: `main`의 `marong/pet/`(반려동물 핵심 함수)와 PR #47(`codex/pet-create`, 합치지 않음)의 만들기 계산 함수·어댑터예요. 글 답의 모델·도구 반복은 PR #52로 이미 LangGraph예요.
- 순서: U1(TASK-379 → 380 → 381 → 382 → (383, 384, 385, 386))이 끝나야 나머지를 시작해요. U2(TASK-387 → 388) 다음에 U3(TASK-389 → 390 → (391, 393) → 392)이에요. U4(394, 395), U5(396 → 397), U6(398, 399 → 400, 401), U7(402, 403, 404, 405), U8(406)은 U1 뒤에 서로 독립이라 순서를 바꿔도 돼요. U9(407, 408)는 U2·U3·U4·U5의 화면이 있은 뒤, U10(409, 410)은 맨 끝이에요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node(`npm test`, Playwright), Java 21과 Gradle(영문 경로 사본), 안드로이드 에뮬레이터. 모델은 가짜(`tests/fakes.py`)로 돌려요. 진짜 모델을 부르는 시험은 캐릭터 만들기 한 번 분량(1달러 이하[추정])과 통화 대기 소리 확인만 해요. 시험 데이터는 합성 데이터만 쓰고, 친구 대화 원문·이름과 묶인 기억·사진을 넣지 않아요.
- 반영: 서버 반영을 해요. 순서는 [설계 제안 15절](../unified-app.md#15-적용과-되돌리기)의 11단계 그대로예요. ① 백업 ② 마이그레이션 020과 통화 008(더하기만, 두 번 돌려도 됨) ③ 앱 서버를 새 서비스로(`MARONG_AUTH=both`, `MARONG_LOOPS_HOME=bot`) ④ 동희님 `link` 링크 ⑤ 현경님 `link` 링크 ⑥ 먼저 연락 설정을 `discord_dm_links`에서 `contact_settings`로 한 번 더 복사한 뒤 글 대화 주소와 작업 루프를 앱 서버로(`MARONG_LOOPS_HOME=app`) ⑦ 앱·웹 경로에서 Access를 빼고 관리자 화면만 남김(`MARONG_AUTH=session`) ⑧ U2\~U8을 설정값으로 하나씩 켬 ⑨ 앱 0.3.0 ⑩ 지인에게 `join` 링크 ⑪ 디스코드 봇·음성 중계를 멈추고 꺼 둠. 켜고 끄는 설정은 `MARONG_AUTH`, `MARONG_LOOPS_HOME`, `MARONG_CHARACTER`, `MARONG_FRIENDS`, `MARONG_CALL_SHOP`, `MARONG_CALL_WAIT_SOUND`, `MARONG_TURN_PLAN`, `MARONG_DAILY_UNITS`(비우면 세기만)이고 나머지 값은 기능 명세의 설정 절에 있어요. 서버의 `prompt.md`는 덮어쓰지 않고 서버 파일과 비교해 합쳐요. 앱은 0.3.0, 패키지 `com.corthexhq.marong`, 기존 릴리스 키, versionCode는 서버 릴리스의 최신보다 큰 값이에요(2026-11-18 기록의 최신은 0.2.4·코드 7이라 8 이상, 빌드 전에 `app-release status`로 확인).
- 하면 안 되는 것: 가입 고지·동의·나이 확인, 결제·티켓 판매, 계정별 프롬프트 나누기, 지인 대화를 기록 시트에서 가리기, 글 답을 유료 공식 API로 옮기기(모두 서비스 때 볼 일, D99\~D103). 이메일이 같다고 계정을 자동으로 잇기(REQ-433). 기존 방의 대화·기억을 복사하거나 옮기기(REQ-453). 반려동물 캐릭터에 19금 절 넣기(D91). 초대 토큰·로그인 토큰·기기 코드의 원문을 DB나 로그에 남기기(REQ-435). 디스코드 봇·음성 중계의 코드·서비스·데이터 지우기(멈추고 꺼 두기만). 새 디자인 토큰 만들기. 반려동물 part의 화면(SCR-140\~162)·흐름(FL-150\~168)·표(TBL-140\~163) 고치기. 현경님 폰에서 직접 본 것이 아닌데 설치·로그인을 완료로 적기.
- 겹치는 파일: `marong/agent.py`·`marong/app_chat.py`·`marong/llm.py`는 PR #53(글 대화 추적)과, `marong/proactive.py`·`marong/schedules.py`·`marong/app_delivery.py`는 PR #41(일기·통화 비용)·PR #46(성향 3단계)과 겹쳐요. PR #53이 먼저 합쳐지고 U1이 그 위에서 시작하는 순서를 추천해요. PR #41·#46은 U1 뒤에 TASK-410으로 맞춰요. `docs/07-sitemap/sitemap.yaml`과 `.corthex/`는 설계 스레드만 써요([README](README.md#겹치는-파일)).
- 사람 확인: [설계 제안 16절](../unified-app.md#16-실기기-확인-기준)의 가\~마(동희님 아이폰 웹, 현경님 폰 앱, 지인 폰 새 가입, 두 계정의 친구 맺기, 통화 대기 소리)예요. 시험 계획에서는 '실기기'로 표시한 TC예요. Cloudflare Access 정책을 바꾸는 ⑦과 디스코드를 끄는 ⑪은 하기 전에 동희님께 한 번 알려요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-430\~495 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 그리고 디스코드 봇과 음성 중계를 끈 채로 하루 동안 글 답·먼저 말 걸기·일정 알림·통화가 도는 것(TC-495).
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

```bash
.venv/bin/python tests/test_unified_schema.py && .venv/bin/python tests/test_unified_auth.py   # U1: TC-430~443
.venv/bin/python tests/test_app_chat.py && .venv/bin/python tests/test_proactive.py && .venv/bin/python tests/test_schedules.py   # 기존 시험(디스코드 없이도 통과)
cd apps/android && npm test && npm run test:browser      # 화면 상태
cd apps/android/android && ./gradlew testDebugUnitTest lintDebug assembleDebug   # 앱 0.3.0
```

새 시험 파일 이름(`tests/test_unified_*.py`)은 추천이고 GPT가 바꿔도 돼요. 바꾸면 시험 계획의 '어디서' 칸에 적어요.

## 작업

- 담당: 모두 GPT예요. 빌드·서명·서버 반영도 GPT가 알아서 해요(D65). 실기기 확인은 동희님이 폰을 부탁하고 같이 봐요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 약 41.5일이에요.
- 패키지: U1 계정과 방(TASK-379\~386), U2 내 마롱이(387\~388), U3 캐릭터(389\~393), U4 목소리와 동시 통화(394\~395), U5 친구(396\~397), U6 통화 개선(398\~401), U7 글 답 도구(402\~405), U8 사용량(406), U9 웹과 앱(407\~408), U10 정리(409\~410).

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-379 | 마이그레이션 020(새 표 9개, `rooms.owner_friend_id`, `friendships`의 `state`·`requested_by`·`responded_at`·`close_a`·`close_b`, 기존 데이터 채우기)과 통화 008(권한)을 `pgserver`에서 돌려 확인하고 `schema.sql`·`tests/pg.py`에 반영. 초안은 임시 Postgres에서 확인했어요(표 문서 8절). 이 작업은 그 확인을 저장소 시험으로 옮기고, 틀린 곳이 나오면 고쳐 PR에 적어요 | SPEC-373, SPEC-375 | TBL-164\~172, `marong/migrations/020_unified.sql`, `marong/call/migrations/008_unified.sql`, `marong/schema.sql` | 없음 | GPT | 1 | 빈 DB와 합성 데이터가 든 DB에서 두 번 돌려도 통과. 채우기 뒤 기존 1:1 방의 주인, 먼저 연락 설정, `close_a`·`close_b`가 맞음. 옛 코드의 기존 시험 전부 통과 |
| TASK-380 | 초대 링크(만들기·상태 보기·쓰기), 로그인 쿠키(만들기·연장·끊기·쓰기 요청의 Origin 확인), 기기 추가 코드(만들기·쓰기·시도 제한). 토큰과 코드는 해시만 저장 | SPEC-370, SPEC-371, SPEC-372 | API-211\~215, TBL-164\~166, 새 모듈 `marong/auth.py`, `marong/app_chat.py` | TASK-379 | GPT | 2 | TC-430\~437 통과. API-211\~215가 나열한 응답마다 시험 통과, 응답이 계약 스키마에 맞음 |
| TASK-381 | 가입 때 만드는 것: `join`이면 친구 행·프로필(친구 코드)·먼저 연락 설정·방 `app:<friend_id>`(주인 칸)·사람 행·통화 계정·방의 통화 기억 보호 행(`call.kakao_guards`)을 한 트랜잭션으로, `link`·`relogin`이면 정한 친구 행에 프로필과 로그인만 | SPEC-373 | API-212, TBL-165·167·168, `marong.rooms`, `call.callers` | TASK-380 | GPT | 1 | TC-438 통과(중간 실패 때 아무 행도 안 남음, `link`는 정한 친구 행에만 이어짐) |
| TASK-382 | 로그인 확인 공통 함수 하나를 앱 서버(`_who`)와 통화 서버가 같이 씀. `MARONG_AUTH=access\|both\|session`, 로그인이 없으면 화면은 SCR-164로, API는 401 `login_required`. 디스코드 DM 연결 조건(`no_dm`)을 뺌 | SPEC-374 | API-101\~106·141과 통화 서버 API의 인증, `marong/access.py`, `marong/app_chat.py`, `marong/call/` | TASK-381 | GPT | 1.5 | TC-439\~441 통과. 세 설정값마다 Access만·둘 다·쿠키만 통과하는 시험 |
| TASK-383 | 방 주인으로 읽기: 답할 때 읽는 방 고르기(`_reply_rooms`)와 임베딩·요약·기억 읽기를 `rooms.owner_friend_id` 조건으로 | SPEC-375 | `marong/agent.py`, `marong/memory.py`, `marong/embed.py`, `marong/store.py` | TASK-382 | GPT | 1 | TC-442·443 통과(새 사람의 답에 자기 방의 기억만, 기존 두 계정의 읽기 결과가 바꾸기 전과 같음) |
| TASK-384 | 앱 서버 진입점: 디스코드 클라이언트 없이 글 대화 서버와 작업 루프(먼저 말 걸기, 일정 알림, 구글 동기화, 기억 정리)를 띄움. 루프는 `MARONG_LOOPS_HOME=bot\|app`인 쪽에서만 돌고 루프마다 DB 잠금으로 겹침을 막음. `app`으로 바꾸기 직전에 먼저 연락 설정을 `discord_dm_links`에서 `contact_settings`로 다시 복사하는 명령을 둠. 새 경로는 비동기로 | SPEC-376 | 새 모듈 `marong/app_server.py`, `marong/discord_dm.py`, 새 서비스 파일 `deploy/marong-app.service` | TASK-382 | GPT | 2 | TC-444·445 통과(앱 서버만으로 글 답·루프가 돎, 루프가 두 곳에서 겹쳐 돌지 않음) |
| TASK-385 | 보내기 경로: 앱 알림 → 없으면 방에 남김. 디스코드 분기와 일정 알림의 채널 조건을 빼고, 먼저 말 걸기 설정과 상태를 `contact_settings`에서 읽고 씀. 통화의 글로 보내기(SPEC-239)도 이 경로로 | SPEC-383 | TBL-168, `marong/app_delivery.py`, `marong/proactive.py`, `marong/schedules.py` | TASK-384 | GPT | 1.5 | TC-446\~448 통과. `tests/test_proactive.py`·`tests/test_schedules.py`가 디스코드 값 없이 통과 |
| TASK-386 | 가입·로그인·관리자 화면과 관리자 API(초대 링크 만들기·목록, 회원 목록, 로그인 끊기, 티켓 넣기). 관리자 경로는 Access 뒤 | SPEC-370, SPEC-395 | SCR-163·164·169, API-235\~237·240·241, `marong/app_chat_static/` | TASK-381 | GPT | 2 | TC-449 통과. 관리자 API가 나열한 응답마다 시험 통과, Access 없이 관리자 경로는 거절 |
| TASK-387 | 프로필 API(켜진 기능 `features`, 구글 연결 상태 `google` 포함)와 '내 마롱이' 화면, 마롱이 이름을 프롬프트의 캐릭터 구간·화면 머리말·알림 본문·통화 호출어에 반영. 글 대화 메뉴에 '내 마롱이'·'친구' 들어가는 곳 | SPEC-377 | API-216·217, SCR-165, SCR-107·109·112, TBL-167, `marong/agent.py`, `marong/app_push.py` | TASK-382 | GPT | 2 | TC-450\~452 통과 |
| TASK-388 | 프롬프트의 19금 절에 시작·끝 표시를 넣고, 쓰는 캐릭터가 반려동물일 때만 그 절을 뺌. 그 밖의 계정은 프롬프트가 바꾸기 전과 글자까지 같음 | SPEC-377 | `marong/prompt.md`, `marong/agent.py` | TASK-387 | GPT | 0.5 | TC-453 통과(기본 마롱이 계정의 프롬프트가 바꾸기 전과 같음을 비교하는 시험 포함) |
| TASK-389 | PR #47의 만들기 계산 함수·어댑터와 `marong/pet/`의 필요한 함수를 `marong/character/`로 옮기고 주인 키를 `friend_id`로 바꿈. 결제 조건은 가져오지 않음 | SPEC-378 | 새 패키지 `marong/character/` | TASK-379 | GPT | 1 | 옮긴 함수의 기존 시험이 새 위치에서 통과 |
| TASK-390 | 캐릭터 만들기 작업과 API: 사진 검사, 특징표, 미리 보기 1장, 후보 4장(다시 만들기 2번), 고르기와 표정 6장, 이름 짓기, 보관 목록(3개), 그림 내려주기. 작업은 비동기 일꾼이 돌림 | SPEC-378 | API-219\~226·229·242, TBL-169\~171, `MARONG_CHARACTER_DIR` | TASK-389, TASK-382 | GPT | 3 | TC-454\~459 통과(가짜 모델). API가 나열한 응답마다 시험 통과 |
| TASK-391 | 입혀 보기(저장하지 않는 고정 견본), 적용(`character_id`와 `bot_name`을 한 번에), 기본으로 되돌리기, 지우기(쓰던 캐릭터면 기본으로) | SPEC-379 | API-227·228·238, TBL-167·169 | TASK-390, TASK-387 | GPT | 1 | TC-460\~462 통과 |
| TASK-392 | 캐릭터 화면: 만들기(사진)·특징표·미리 보기·후보·이름 짓기와 입혀 보기. 글 대화 머리말과 통화 중 화면의 얼굴 | SPEC-378, SPEC-379 | SCR-166, SCR-170\~174, SCR-107·002, `marong/app_chat_static/`, `marong/call/static/` | TASK-391 | GPT | 2 | TC-463 통과. 낮·밤 테마와 360px 폭에서 넘치지 않음 |
| TASK-393 | 그림 예산: 이번 달 작업 비용 합이 `MARONG_IMAGE_MONTHLY_USD`의 80%면 관리자에게 한 번 알리고 100%면 새 만들기·그리기를 거절 | SPEC-380 | TBL-171, API-219·223·224 | TASK-390 | GPT | 0.5 | TC-464 통과 |
| TASK-394 | 사람별 통화 목소리: 목록 API, 견본 소리 파일, 고르기 화면, 통화 시작 때 `friend_profiles.voice`를 읽고 목록 밖 값이면 기본 | SPEC-385 | API-217·218, SCR-167, TBL-167, `marong/call/` | TASK-387 | GPT | 1.5 | TC-465\~467 통과 |
| TASK-395 | 동시 통화: 전역 하나 대신 사람마다 하나와 서버 전체 `MARONG_CALL_MAX`(기본 3). 거절은 409 `call_busy`, 503 `calls_full` | SPEC-386 | 통화 시작 API, SCR-001, `marong/call/` | TASK-382 | GPT | 1 | TC-468 통과 |
| TASK-396 | 친구: 친구 코드로 요청, 수락·거절, 가까운 사이(둘 다 켰을 때만), 끊기, 공유 켬·끔, 화면. 관리자 명령 `admin friendship … close`도 `close_a`·`close_b`를 같이 고치게 함 | SPEC-381 | API-230\~233·239·217, SCR-168, `marong.friendships` | TASK-387 | GPT | 2 | TC-469\~472 통과. API가 나열한 응답마다 시험 통과 |
| TASK-397 | 관계를 맥락에: 글 대화의 사전 조회와 통화 시작 때 넣는 기억에 친구 목록(이름, 관계, 가까운 사이 여부)을 넣음 | SPEC-382 | `marong/agent.py`, `marong/call/` | TASK-396 | GPT | 1 | TC-473·474 통과 |
| TASK-398 | 통화 지시문 고침: 앞뒤가 안 맞는 단어는 한 번 되묻기, 정정 받으면 바로 고치기, 친구가 꺼낸 화제 잇기, 능력 소개 문구 | SPEC-387 | 통화 지시문(`marong/call/`) | TASK-382 | GPT | 0.5 | TC-475·476 통과(합성 대본) |
| TASK-399 | 통화 쇼핑 도구: 글 대화의 쇼핑 읽기 함수를 통화 도구로 붙임(통화 한 번에 3번, 시간 제한 12초, 실패하면 "못 찾았어") | SPEC-388 | `marong/shopping.py`, `marong/call/`, `MARONG_CALL_SHOP` | TASK-382 | GPT | 1 | TC-477 통과 |
| TASK-400 | 도구 대기 소리: 도구가 돌거나 응답을 기다린 지 0.8초 뒤부터 반복 효과음, 마롱이 소리가 시작되면 바로 멈춤. 클라이언트에서 냄 | SPEC-389 | SCR-002#waiting, `marong/call/static/`, `MARONG_CALL_WAIT_SOUND` | TASK-399 | GPT | 1 | TC-478·479 통과 |
| TASK-401 | 사람별 통화 상한: 통화 시작 전에 그 사람의 이번 달 합을 `MARONG_CALL_PERSON_MONTHLY_USD`와 비교(비어 있으면 없음). 전체 월 150달러 규칙은 그대로 | SPEC-390 | 통화 시작 API, `marong/call/` | TASK-382 | GPT | 0.5 | TC-480 통과 |
| TASK-402 | 답 하나의 상한(모델 호출 6번, 도구 실행 8번, 넘으면 지금까지 결과로 답함)과 실행 전 확인(이번 답에 준 도구만, 일정 취소는 이번에 보여 준 번호만) | SPEC-393 | `marong/chat_tool_graph.py`, `marong/agent.py` | TASK-382 | GPT | 1 | TC-481\~483 통과 |
| TASK-403 | 사전 조회 동시 읽기: 일정, 구글 캘린더, 최근 대화, 기억 검색을 한꺼번에, 읽기마다 시간 제한, 하나가 실패해도 나머지로 답함 | SPEC-392 | `marong/agent.py` | TASK-382 | GPT | 1 | TC-484 통과 |
| TASK-404 | 턴 계획: `MARONG_TURN_PLAN=off\|shadow\|prefetch`. 처음은 `shadow`(기록만). 합성 말 60개로 의도·사전 조회 범위의 정확도를 측정해 PR에 적음. 실패하면 지금 방식으로 | SPEC-391 | `marong/agent.py`, 추적 기록 | TASK-403 | GPT | 1.5 | TC-485·486 통과. 측정 결과 표가 PR에 있음 |
| TASK-405 | `schedule_add` 도구 설명과 시스템 프롬프트에 겹쳐 적힌 규칙을 한 곳으로 모음 | SPEC-393 | `marong/schedules.py`, `marong/prompt.md` | TASK-402 | GPT | 0.5 | `tests/test_schedules.py` 통과, 도구 정의 글자 수가 줄어든 값을 PR에 적음 |
| TASK-406 | 사용량: 답·통화·그림·검색·쇼핑 읽기가 끝날 때 `usage_daily`에 더함(하루는 04:00 KST). `MARONG_DAILY_UNITS`가 있을 때만 한도, 넘으면 티켓에서 빼고 티켓이 0이면 429 `daily_limit`. 통화 쪽은 통화 서버가 사용량을 더하는 같은 트랜잭션에서 뺌 | SPEC-394 | API-234·237·216, TBL-172·167, SCR-165·001 | TASK-387 | GPT | 1.5 | TC-487\~489 통과 |
| TASK-407 | 웹: 홈 화면 추가용 설정 파일과 아이콘, 로그인한 브라우저에 앱과 같은 페이지, 웹을 열었을 때 밀린 연락과 약속 전화 받기 버튼, 설정 화면의 구글 캘린더 연결·끊기 | SPEC-384, SPEC-396, SPEC-383 | SCR-165·107, `marong/app_chat_static/`, `/google/` 페이지 | TASK-387 | GPT | 1.5 | TC-490·491 통과 |
| TASK-408 | 앱 0.3.0: Access 로그인 처리를 빼고 로그인 쿠키 유지, 글 대화 창에서 사진 고르기 동작, 알림 본문의 마롱이 이름. 빌드·서명·`app-release publish` | SPEC-371, SPEC-377 | `apps/android/`, API-141·142 | TASK-386, TASK-392 | GPT | 2 | TC-492\~494 통과. 서명 APK의 크기·SHA-256 기록, 릴리스 API가 0.3.0을 줌 |
| TASK-409 | 정리: 디스코드 봇과 음성 중계 서비스를 멈추고 꺼 둠(지우지 않음, 되돌리기 스크립트 먼저). 문서와 화면 문구에 남은 카카오톡·디스코드 안내를 지금 경로로 고침 | SPEC-376, SPEC-383 | 서버 서비스, `README.md`, `docs/` | TASK-384, TASK-385, TASK-408 | GPT | 1 | TC-495 통과(디스코드 없이 하루 동안 글 답·먼저 말 걸기·일정 알림·통화) |
| TASK-410 | PR #41(일기·통화 비용)과 PR #46(성향 3단계)의 디스코드 DM 연결 조건을 로그인 확인 공통 함수로 바꿔 `main`에 맞춤 | SPEC-374 | 두 PR의 브랜치 | TASK-382 | GPT | 1 | 두 PR의 시험이 `main` 위에서 통과 |

## 확인

- 명세 SPEC-370\~396마다 작업이 있어요: 370(TASK-380·386), 371(380·408), 372(380), 373(379·381), 374(382·410), 375(379·383), 376(384·409), 377(387·388·408), 378(389·390·392), 379(391·392), 380(393), 381(396), 382(397), 383(385·407·409), 384(407), 385(394), 386(395), 387(398), 388(399), 389(400), 390(401), 391(404), 392(403), 393(402·405), 394(406), 395(386), 396(407).
- API-211\~242를 만지는 작업(TASK-380·381·386·387·390·391·394·396·406)은 계약의 모든 응답에 시험이 있어야 끝나요.
- 의존에 고리가 없어요. 모든 작업이 번호가 더 작은 작업에만 기대요(TASK-409만 408에 기대고, 그것도 더 작은 번호예요).
- 표 TBL-164\~172마다 만지는 작업이 있어요: 164\~166(TASK-380), 165·167·168(381), 168(385), 167(387·391·394·406), 169\~171(390), 172(406).
- 화면 SCR-163\~174마다 작업이 있어요: 163·164·169(TASK-386), 165(387), 166·170\~174(392), 167(394), 168(396).

## 11단계 진행

GPT가 TASK마다 상태·커밋·확인한 것을 적어요(AGENTS.md '구현을 시작할 때' 6).

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
