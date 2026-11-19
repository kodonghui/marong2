# 통합 앱(MVP) 작업 목록(10단계 WBS, CTX-026~029)

2026-11-19 10시대 KST 작성(Claude). 입력: 설계 제안 [unified-app.md](../unified-app.md)(동희님 승인 D104), 도메인 [unified.md](../01-domain/unified.md)(CTX-026\~029, TERM-173\~198), 요구사항 [unified.md](../02-prd/unified.md)(REQ-430\~483), 흐름 FL-169\~178([03-user-flow](../03-user-flow/)), 기능 명세 [unified.md](../04-functional-spec/unified.md)(SPEC-370\~396), 표 [020_unified.sql](../../marong/migrations/020_unified.sql)·[통화 008_unified.sql](../../marong/call/migrations/008_unified.sql)(TBL-164\~172, 그림은 [05-erd/unified.md](../05-erd/unified.md)), 계약 [unified.openapi.yaml](../../api/unified.openapi.yaml)(API-211\~242), 화면 상태 [unified.md](../08-screens/unified.md)(SCR-163\~174), 시험 계획 [12-qa/unified.md](../12-qa/unified.md)(TC-430\~495).

## GPT 인계

- 목표: 카카오톡과 디스코드 없이 안드로이드 앱과 웹만으로 마롱이를 쓰게 해요. 지인은 초대 링크로 가입하고, 사람마다 자기 마롱이(이름, 반려동물 캐릭터, 통화 목소리)를 가지며, 친구끼리 서로 이어요. 범위는 동희님 주변 사람이 쓰는 MVP예요. 동희님 2026-11-19 이 설계 스레드: "카톡/디코는 서비스 x. 이제 apk랑 웹(나는 아이폰이라 웹에서 해야해)에서만 할거야"(D92), "초대링크로 ㄱㄱ"(D97), "일단 MVP를 내는거지 지금 서비스를 내는게 아니잔아"(D103), 설계 제안에 "승인"(D104), 목업을 본 뒤 "ㅇㅇ ㄱㄱ 프롬프트 줘 지피티한테시킬게"(D105, 14:13 KST).
- 시작: 이 설계 PR(#54)이 `main`에 합쳐진 뒤 `main` 머리에서 패키지마다 새 브랜치 `codex/unified-u1`\~`codex/unified-u10`. 설계를 쓸 때의 `main`은 `0953b86`이에요. 패키지마다 초안 PR 하나예요.
- 먼저 할 일(TASK-379 앞): 운영 서버의 봇 코드가 `main`과 꼭 같지 않아요. 2026-11-19 04:22 KST에 다시 뜬 코드에서 4개 파일은 PR #53 머리와 같고, `marong/agent.py`·`marong/discord_dm.py`·`marong/llm.py`·`marong/app_chat.py`는 `main`과도 PR #53과도 달라요. 이 4개의 출처를 확인해 `main`에 맞춘 뒤에 시작해요(맞추는 방법이 설계에 닿으면 '설계 질문'으로). 같이 확인할 것 셋: ① 서버 설정 `MARONG_DEEPSEEK_ROOMS`의 값(방 키 앞부분으로 글 답 경로를 골라요. 새 방 `app:<id>`가 지금 글 답과 같은 경로로 가도록 반영 때 `app:`을 넣어요. 값은 출력하지 않아요) ② 카카오 프로세스(`run.py`)가 서버에서 아직 도는지(기억 정리 루프를 누가 돌리는지가 달라져요, 명세 3.4) ③ 앱 버전: 저장소의 값은 0.2.2·코드 5이고 0.2.3·0.2.4의 버전 올림은 커밋되지 않았어요. 릴리스된 0.2.4와 저장소의 차이를 먼저 찾아 맞춰요.
- 읽을 것: [기능 명세](../04-functional-spec/unified.md)의 SPEC-370\~396과 상세 절, [계약](../../api/unified.openapi.yaml)의 API-211\~242, [마이그레이션 020](../../marong/migrations/020_unified.sql)·[통화 008](../../marong/call/migrations/008_unified.sql)의 TBL-164\~172와 바뀌는 칸, [화면 상태](../08-screens/unified.md)의 SCR-163\~174와 바뀌는 화면, [시험 계획](../12-qa/unified.md)의 TC-430\~495. 캐릭터 만들기는 반려동물 명세 [pet.md](../04-functional-spec/pet.md)의 SPEC-316\~325를 결제 조건만 빼고 그대로 따르므로 그 절도 읽어요. 배경은 [설계 제안](../unified-app.md)이고, 제안과 단계 문서가 다르면 단계 문서가 맞아요. 화면은 얼려 둔 토큰 103개([design/base.tokens.json](../../design/base.tokens.json))와 지금 `chat.css`의 부품만 써요(방향은 반려동물 A안과 지금 글 대화 화면, D105).
- 화면 모양: [목업 기록](../../design/unified-mockup.md)과 캔버스 [마롱이 통합 앱 목업](https://claude.ai/artifact/GXVep4QepAUdFhH6gDmLb3)의 대지 17장, 부품 클래스 [unified-mockup.css](../../design/unified-mockup.css). 문구와 상태의 원본은 화면 정의예요.
- 이미 된 것: 설계만이에요(01\~08, 10과 12 시험 계획). 마이그레이션 두 파일은 초안이에요. 2026-11-19에 임시 Postgres 16.2(`pgserver`, 합성 행)에서 두 번 적용해 확인 50개가 통과했고(14:28 KST, 검토에서 나온 고침을 넣은 뒤)([표 문서 8절](../05-erd/unified.md)), 운영 DB에는 적용하지 않았어요. 가져다 쓸 코드: `main`의 `marong/pet/`(반려동물 핵심 함수)와 PR #47(`codex/pet-create`, 합치지 않음)의 만들기 계산 함수·어댑터예요. 글 답의 모델·도구 반복은 PR #52로 이미 LangGraph예요. 통화 서버의 코드는 `tools/vertex_live/`에 있어요(`server.py`, `live_session.py`, `call_memory.py`, `call_instruction.md`, `static/`). `marong/call/`에는 스키마·마이그레이션·얼굴 그림만 있어요. 전체 통화 예산 코드(SPEC-174, `budget_exhausted`)는 `main`에 없고 PR #41(`codex/diary-call-cost`)에 있어요.
- 순서: U1(TASK-379 → 380 → 381 → 382 → (383, 384, 385, 386))이 끝나야 나머지를 시작해요. U2(TASK-387 → 388) 다음에 U3(TASK-389 → 390 → (391, 393) → 392)이에요. U4\~U8은 U1 뒤에 시작해요. 패키지끼리는 따로 PR이지만 같은 코드를 만지는 작업은 이 순서로 해요. 통화 서버의 통화 시작 경로(`tools/vertex_live/server.py`·`live_session.py`): TASK-410의 PR #41 부분 → 395 → 394 → 401 → 406의 통화 부분. 글 답(`marong/agent.py`): 387 → 388 → 402 → 396 → 397 → 403 → 404. 그 밖은 U4(395 → 394), U5(396 → 397), U6(398, 399 → 400, 401), U7(402, 405, 397 뒤에 403 → 404), U8(406)이에요. PR #41이 아직 `main`에 없으면 통화 서버를 만지는 브랜치를 TASK-410을 한 뒤의 `codex/diary-call-cost` 머리에서 만들고 PR 설명에 그렇게 적어요. U9(407, 408)는 U2·U3·U4·U5의 화면이 있은 뒤, U10(409, 410)은 맨 끝이에요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node(`npm test`, Playwright), Java 21과 Gradle(영문 경로 사본), 안드로이드 에뮬레이터. 모델은 가짜(`tests/fakes.py`)로 돌려요. 진짜 모델을 부르는 시험은 셋이에요: 캐릭터 만들기 한 번 분량(1달러 이하[추정]), 통화 대기 소리 확인, 캐릭터 금지선 15번(TC-453, 명세 3.5). 통화 쇼핑의 시간 측정 10번(TASK-399)도 실제 호출이에요. 시험 데이터는 합성 데이터만 쓰고, 친구 대화 원문·이름과 묶인 기억·사진을 넣지 않아요.
- 반영: 서버 반영을 해요. 순서는 [설계 제안 15절](../unified-app.md#15-적용과-되돌리기)의 11단계 그대로예요. ① 백업 ② 마이그레이션 020과 통화 008(더하기만, 두 번 돌려도 됨) ③ 앱 서버를 새 서비스로(`MARONG_AUTH=both`, `MARONG_LOOPS_HOME=bot`) ④ 동희님 `link` 링크 ⑤ 현경님 `link` 링크 ⑥ 먼저 연락 설정을 `discord_dm_links`에서 `contact_settings`로 한 번 더 복사한 뒤 글 대화 주소와 작업 루프를 앱 서버로(`MARONG_LOOPS_HOME=app`) ⑦ 앱·웹 경로에서 Access를 빼고 관리자 화면만 남김(`MARONG_AUTH=session`) ⑧ U2\~U8을 설정값으로 하나씩 켬 ⑨ 앱 0.3.0 ⑩ 지인에게 `join` 링크 ⑪ 디스코드 봇·음성 중계를 멈추고 꺼 둠. 새 비밀 설정 셋(`MARONG_SESSION_SECRET`, `MARONG_INTERNAL_SECRET`, `MARONG_ADMIN_EMAIL_SHA256`)은 서버에서 만들어 서버의 비밀 설정에만 두고 값을 출력하지 않아요. 관리자 이메일 해시는 지금 `call.caller_logins`에서 동희님 친구 행에 묶인 값을 써요. 켜고 끄는 설정은 `MARONG_AUTH`, `MARONG_LOOPS_HOME`, `MARONG_CHARACTER`, `MARONG_FRIENDS`, `MARONG_CALL_SHOP`, `MARONG_CALL_WAIT_SOUND`, `MARONG_TURN_PLAN`, `MARONG_DAILY_UNITS`(비우면 세기만)이고 나머지 값은 기능 명세의 설정 절에 있어요. 서버의 `prompt.md`는 덮어쓰지 않고 서버 파일과 비교해 합쳐요. 앱은 0.3.0, 패키지 `com.corthexhq.marong`, 기존 릴리스 키, versionCode는 서버 릴리스의 최신보다 큰 값이에요(2026-11-18 기록의 최신은 0.2.4·코드 7이라 8 이상, 빌드 전에 `app-release status`로 확인).
- 하면 안 되는 것: 가입 고지·동의·나이 확인, 결제·티켓 판매, 계정별 프롬프트 나누기, 지인 대화를 기록 시트에서 가리기, 글 답을 유료 공식 API로 옮기기(모두 서비스 때 볼 일, D99\~D103). 이메일이 같다고 계정을 자동으로 잇기(REQ-433). 기존 방의 대화·기억을 복사하거나 옮기기(REQ-453). 반려동물 캐릭터에 19금 절 넣기(D91). 초대 토큰·로그인 토큰·기기 코드의 원문을 DB나 로그에 남기기(REQ-435). 디스코드 봇·음성 중계의 코드·서비스·데이터 지우기(멈추고 꺼 두기만). 새 디자인 토큰 만들기. 반려동물 part의 화면(SCR-140\~162)·흐름(FL-150\~168)·표(TBL-140\~163) 고치기. 현경님 폰에서 직접 본 것이 아닌데 설치·로그인을 완료로 적기.
- 겹치는 파일: `marong/agent.py`·`marong/app_chat.py`·`marong/llm.py`는 PR #53(글 대화 추적)과, `marong/proactive.py`·`marong/schedules.py`·`marong/app_delivery.py`는 PR #41(일기·통화 비용)·PR #46(성향 3단계)과 겹쳐요. PR #41은 통화 서버도 크게 고쳐요(`tools/vertex_live/server.py`·`live_session.py`·`call_memory.py`·`static/app.js`, `run_discord.py`에 일기 루프). U1의 TASK-382·384, U4, U6이 같은 파일을 만져요. PR #53이 먼저 합쳐지고 U1이 그 위에서 시작하고, U1 바로 뒤에 TASK-410으로 PR #41을 맞춘 다음 통화 서버 작업을 하는 순서를 추천해요. PR #46은 그 뒤 아무 때나 TASK-410으로 맞춰요. `docs/07-sitemap/sitemap.yaml`과 `.corthex/`는 설계 스레드만 써요([README](README.md#겹치는-파일)).
- 사람 확인: [설계 제안 16절](../unified-app.md#16-실기기-확인-기준)의 가\~마(동희님 아이폰 웹, 현경님 폰 앱, 지인 폰 새 가입, 두 계정의 친구 맺기, 통화 대기 소리)예요. 시험 계획에서는 '실기기'로 표시한 TC예요. Cloudflare Access 정책을 바꾸는 ⑦과 디스코드를 끄는 ⑪은 하기 전에 동희님께 한 번 알려요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-430\~495 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 그리고 디스코드 봇과 음성 중계를 끈 채로 하루 동안 글 답·먼저 말 걸기·일정 알림·통화가 도는 것(TC-495).
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_unified_schema.py && .venv/bin/python tests/test_unified_auth.py   # U1: TC-430~443
.venv/bin/python tests/test_app_chat.py && .venv/bin/python tests/test_proactive.py && .venv/bin/python tests/test_schedules.py   # 기존 시험(디스코드 없이도 통과)
for f in tools/vertex_live/test_*.py; do .venv/bin/python "$f" || exit 1; done   # 통화 서버 시험(.cjs 시험은 node로)
(cd apps/android && npm ci && npm test && npm run test:browser && npm run sync)   # 화면 상태. Playwright가 없으면 브라우저 시험이 건너뛴 채 통과하니, 건너뛰지 않았는지 출력에서 보고 PR에 적어요
(cd apps/android/android && ./gradlew testDebugUnitTest lintDebug assembleDebug)   # 앱 단위 시험과 디버그 빌드(npm ci와 sync 뒤에). 배포용 0.3.0은 릴리스 키로 assembleRelease(apps/android/README.md)
```

기존 시험 가운데 `tests/test_app_chat.py`의 `no_dm` 403을 기대하는 시험은 TASK-382에서 고쳐요(그 조건이 없어져요). 그 밖의 기존 시험은 그대로 통과해야 해요.

새 시험 파일 이름(`tests/test_unified_*.py`)은 추천이고 GPT가 바꿔도 돼요. 바꾸면 시험 계획의 '어디서' 칸에 적어요.

## 작업

- 담당: 모두 GPT예요. 빌드·서명·서버 반영도 GPT가 알아서 해요(D65). 실기기 확인은 동희님이 폰을 부탁하고 같이 봐요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 약 41.5일이에요.
- 패키지: U1 계정과 방(TASK-379\~386), U2 내 마롱이(387\~388), U3 캐릭터(389\~393), U4 목소리와 동시 통화(394\~395), U5 친구(396\~397), U6 통화 개선(398\~401), U7 글 답 도구(402\~405), U8 사용량(406), U9 웹과 앱(407\~408), U10 정리(409\~410).

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-379 | 마이그레이션 020(새 표 9개, `rooms.owner_friend_id`, `friendships`의 `state`·`requested_by`·`requested_at`·`responded_at`·`close_a`·`close_b`, `schedules.source`의 `app`, 기존 데이터 채우기)과 통화 008(권한)을 `pgserver`에서 돌려 확인하고 `schema.sql`·`tests/pg.py`에 반영. 초안은 임시 Postgres에서 확인했어요(표 문서 8절). 이 작업은 그 확인을 저장소 시험으로 옮겨요. 틀린 곳이 나오면 AGENTS.md '계약과 다를 때'를 따라요(동작이 안 바뀌는 차이는 고치고 PR의 '계약 손봄'에, 표 모양이 바뀌어야 하면 멈추고 '설계 질문'에) | SPEC-373, SPEC-375 | TBL-164\~172, `marong/migrations/020_unified.sql`, `marong/call/migrations/008_unified.sql`, `marong/schema.sql` | 없음 | GPT | 1 | 빈 DB와 합성 데이터가 든 DB에서 두 번 돌려도 통과. 채우기 뒤 기존 1:1 방의 주인, 먼저 연락 설정, `close_a`·`close_b`가 맞음. 옛 코드의 기존 시험 전부 통과 |
| TASK-380 | 초대 링크(만들기·상태 보기·쓰기), 로그인 쿠키(만들기·연장·끊기·쓰기 요청의 Origin 확인), 기기 추가 코드(만들기·쓰기·시도 제한). 토큰과 코드는 해시만 저장 | SPEC-370, SPEC-371, SPEC-372 | API-211\~215, TBL-164\~166, 새 모듈 `marong/app_session.py`(로그인 확인 공통 함수도 여기, 명세 3.2), `marong/app_chat.py` | TASK-379 | GPT | 2 | TC-430\~437 통과. API-211\~215가 나열한 응답마다 시험 통과, 응답이 계약 스키마에 맞음 |
| TASK-381 | 가입 때 만드는 것: `join`이면 친구 행·프로필(친구 코드)·먼저 연락 설정·방 `app:<friend_id>`(주인 칸)·사람 행·통화 계정·방의 통화 기억 보호 행(`call.kakao_guards`)을 한 트랜잭션으로, `link`·`relogin`이면 정한 친구 행에 프로필과 로그인만 | SPEC-373 | API-212, TBL-165·167·168, `marong.rooms`, `call.callers` | TASK-380 | GPT | 1 | TC-438 통과(중간 실패 때 아무 행도 안 남음, `link`는 정한 친구 행에만 이어짐) |
| TASK-382 | 로그인 확인 공통 함수 하나를 앱 서버(`_who`)와 통화 서버가 같이 씀. `MARONG_AUTH=access\|both\|session`, 로그인이 없으면 화면은 SCR-164로, API는 401 `login_required`. 디스코드 DM 연결 조건(`no_dm`)을 뺌. 통화 서버는 `identity()`·`principal`을 바꾸고 `owner` 키를 `friend:<id>`로, `POST /auth`와 `marong_live` 쿠키 경로는 `session`에서 끔. 기존 API의 오류 코드 이름(`unauthenticated`·`invalid_request`)은 그대로 둠 | SPEC-374 | API-101\~106·141과 통화 서버 API의 인증, `marong/access.py`, `marong/app_chat.py`, `marong/app_session.py`, `tools/vertex_live/server.py`·`call_memory.py`, `tests/test_app_chat.py`(`no_dm` 시험) | TASK-381 | GPT | 1.5 | TC-439\~441 통과. 세 설정값마다 Access만·둘 다·쿠키만 통과하는 시험 |
| TASK-383 | 방 주인으로 읽기: 답할 때 읽는 방 고르기(`_reply_rooms`)와 임베딩·요약·기억 읽기를 `rooms.owner_friend_id` 조건으로 | SPEC-375 | `marong/agent.py`, `marong/memory.py`, `marong/embed.py`, `marong/store.py`, `marong/discord_store.py`(세 함수를 덮어쓴 곳) | TASK-382 | GPT | 1 | TC-442·443 통과(새 사람의 답에 자기 방의 기억만, 기존 두 계정의 읽기 결과가 바꾸기 전과 같음) |
| TASK-384 | 앱 서버 진입점: 디스코드 클라이언트 없이 글 대화 서버와 작업 루프(먼저 말 걸기, 일정 알림, 구글 동기화, 기억 정리)를 띄움. 루프는 `MARONG_LOOPS_HOME=bot\|app`인 쪽에서만 돌고 루프마다 DB 잠금으로 겹침을 막음. `app`으로 바꾸기 직전에 먼저 연락 설정을 `discord_dm_links`에서 `contact_settings`로 다시 복사하는 명령을 둠. 새 경로는 비동기로. `run_discord.py`에서 가져올 것(글 답 경로 설정, 캐시 데우기 루프, `/google/` 페이지 서버, 방 잠금)은 명세 3.4에 있어요 | SPEC-376 | 새 파일 `run_app.py`, `run_discord.py`(루프를 시작하는 곳, `MARONG_LOOPS_HOME`을 읽게), `marong/discord_dm.py`, 새 서비스 파일 `deploy/marong-app.service` | TASK-382 | GPT | 2 | TC-444·445 통과(앱 서버만으로 글 답·루프가 돎, 루프가 두 곳에서 겹쳐 돌지 않음) |
| TASK-385 | 보내기 경로: 앱 알림 → 없으면 방에 남김. 디스코드 분기와 일정 알림의 채널 조건을 빼고, 먼저 말 걸기 설정과 상태를 `contact_settings`에서 읽고 씀. 통화의 글로 보내기(SPEC-239)도 이 경로로. 받을 기기가 없어도 약속 전화의 벨 행을 만들고 방에 약속 말을 남김(명세 3.8). 디스코드 값으로 짠 곳의 목록은 명세 3.3 끝에 있어요 | SPEC-383 | TBL-168, `marong/app_delivery.py`, `marong/proactive.py`, `marong/schedules.py`, `marong/discord_dm.py`, `marong/discord_store.py`, `marong/app_chat.py`, `marong/topic_store.py`, `tools/admin.py`, `tools/report.py` | TASK-384 | GPT | 1.5 | TC-446\~448 통과. `tests/test_proactive.py`·`tests/test_schedules.py`가 디스코드 값 없이 통과 |
| TASK-386 | 가입·로그인·관리자 화면과 관리자 API(초대 링크 만들기·목록, 회원 목록과 아직 연결하지 않은 기존 계정 `unlinked`, 로그인 끊기, 티켓 넣기). 관리자 경로는 Access 뒤이고 이메일 해시가 `MARONG_ADMIN_EMAIL_SHA256`과 같아야 함(허용 목록의 다른 사람은 403) | SPEC-370, SPEC-395 | SCR-163·164·169, API-235\~237·240·241, `marong/app_chat_static/` | TASK-381 | GPT | 2 | TC-449 통과. 관리자 API가 나열한 응답마다 시험 통과, Access 없이 관리자 경로는 거절 |
| TASK-387 | 프로필 API(켜진 기능 `features`, 구글 연결 상태 `google`, 울리는 약속 전화 `pendingRing` 포함)와 '내 마롱이' 화면, 마롱이 이름을 프롬프트의 캐릭터 구간·화면 머리말·알림 본문·통화 호출어에 반영. 글 대화 메뉴에 '내 마롱이'·'친구' 들어가는 곳 | SPEC-377 | API-216·217, SCR-165, SCR-107·109·112, TBL-167, `marong/agent.py`, `marong/fcm.py`(알림 제목 상수 `TITLE`), `marong/app_push.py` | TASK-382 | GPT | 2 | TC-450\~452 통과 |
| TASK-388 | 프롬프트의 19금 절에 시작·끝 표시를 넣고, 쓰는 캐릭터가 반려동물일 때만 그 절을 뺌. 그 밖의 계정은 프롬프트가 바꾸기 전과 글자까지 같음 | SPEC-377 | `prompt.md`(저장소 루트), `marong/agent.py` | TASK-387 | GPT | 0.5 | TC-453 통과(기본 마롱이 계정의 프롬프트가 바꾸기 전과 같음을 비교하는 시험 포함) |
| TASK-389 | PR #47의 만들기 계산 함수·어댑터와 `marong/pet/`의 필요한 함수를 `marong/character/`로 옮기고 주인 키를 `friend_id`로 바꿈. 결제 조건은 가져오지 않음 | SPEC-378 | 새 패키지 `marong/character/` | TASK-379 | GPT | 1 | 옮긴 함수의 기존 시험이 새 위치에서 통과 |
| TASK-390 | 캐릭터 만들기 작업과 API: 사진 검사, 특징표, 미리 보기 1장, 후보 4장(다시 만들기 2번), 고르기와 표정 6장, 이름 짓기, 보관 목록(3개), 그림 내려주기. 작업은 비동기 일꾼이 돌림 | SPEC-378 | API-219\~226·229·242, TBL-169\~171, `MARONG_CHARACTER_DIR` | TASK-389, TASK-382 | GPT | 3 | TC-454\~459 통과(가짜 모델). API가 나열한 응답마다 시험 통과 |
| TASK-391 | 입혀 보기(저장하지 않는 고정 견본), 적용(`character_id`와 `bot_name`을 한 번에), 기본으로 되돌리기, 지우기(쓰던 캐릭터면 기본으로) | SPEC-379 | API-227·228·238, TBL-167·169 | TASK-390, TASK-387 | GPT | 1 | TC-460\~462 통과 |
| TASK-392 | 캐릭터 화면: 만들기(사진)·특징표·미리 보기·후보·이름 짓기와 입혀 보기. 글 대화 머리말과 통화 중 화면의 얼굴 | SPEC-378, SPEC-379 | SCR-166, SCR-170\~174, SCR-107·002, `marong/app_chat_static/`, `tools/vertex_live/static/` | TASK-391 | GPT | 2 | TC-463 통과. 낮·밤 테마와 360px 폭에서 넘치지 않음 |
| TASK-393 | 그림 예산: 이번 달 작업 비용 합이 `MARONG_IMAGE_MONTHLY_USD`의 80%면 관리자에게 한 번 알리고 100%면 새 만들기·그리기를 거절 | SPEC-380 | TBL-171, API-219·223·224 | TASK-390 | GPT | 0.5 | TC-464 통과 |
| TASK-394 | 사람별 통화 목소리: 목록 API, 견본 소리 파일, 고르기 화면, 통화 시작 때 `friend_profiles.voice`를 읽고 목록 밖 값이면 기본 | SPEC-385 | API-217·218, SCR-167, TBL-167, `tools/vertex_live/server.py`·`live_session.py` | TASK-387, TASK-395 | GPT | 1.5 | TC-465\~467 통과 |
| TASK-395 | 동시 통화: 전역 하나 대신 사람마다 하나와 서버 전체 `MARONG_CALL_MAX`(기본 3). 거절은 웹소켓 메시지 `call_busy`(지금 있음)·`calls_full`(새로). 통화 하나를 전제한 전역 값 넷(`active`, `active_session`, `resume_state`, `diagnostics`)을 사람별로 나눔(명세 3.9) | SPEC-386 | 통화 시작 API-107(웹소켓), SCR-001, `tools/vertex_live/server.py`·`live_session.py`·`static/app.js` | TASK-382 | GPT | 1 | TC-468 통과 |
| TASK-396 | 친구: 친구 코드로 요청, 수락·거절, 가까운 사이(둘 다 켰을 때만), 끊기, 공유 켬·끔, 화면. 관리자 명령 `admin friendship … close`도 `close_a`·`close_b`를 같이 고치게 함. `friendships`를 읽는 지금 쿼리 둘(`tools/vertex_live/call_memory.py`의 통화 시작 때 넣는 기억 읽기, `marong/store.py`의 친구 둘레 읽기)에 `state = 'accepted'` 조건을 넣음 | SPEC-381 | API-230\~233·239·217, SCR-168, `marong.friendships` | TASK-387 | GPT | 2 | TC-469\~472 통과. API가 나열한 응답마다 시험 통과. 기다리는 요청만 있는 쌍의 공유 기억이 통화 기억과 글 답 맥락에 들어가지 않는 시험 통과 |
| TASK-397 | 관계를 맥락에: 글 대화의 사전 조회와 통화 시작 때 넣는 기억에 친구 목록(이름, 관계, 가까운 사이 여부)을 넣음 | SPEC-382 | `marong/agent.py`, `marong/store.py`, `tools/vertex_live/call_memory.py` | TASK-396 | GPT | 1 | TC-473·474 통과 |
| TASK-398 | 통화 지시문 고침: 앞뒤가 안 맞는 단어는 한 번 되묻기, 정정 받으면 바로 고치기, 친구가 꺼낸 화제 잇기, 능력 소개 문구 | SPEC-387 | `tools/vertex_live/call_instruction.md`와 그 시험 | TASK-382 | GPT | 0.5 | TC-475·476 통과(합성 대본) |
| TASK-399 | 통화 쇼핑 도구: 앱 서버에 내부 경로 `POST /internal/shop-read`(127.0.0.1만, 비밀 머리말)를 만들고 통화 도구 `shop_read`가 그 경로를 부름. 글 대화의 쇼핑 읽기는 부를 수 있는 함수가 아니라 Claude 호출 안의 서버 도구라서예요(명세 3.10). 통화 한 번에 3번, 시간 제한 20초, 실패하면 "못 찾았어". 실제 호출로 10번 측정해서 PR에 적음 | SPEC-388 | `marong/shopping.py`, `run_app.py`, `tools/vertex_live/live_session.py`, `MARONG_CALL_SHOP`, `MARONG_INTERNAL_SECRET` | TASK-384 | GPT | 1 | TC-477 통과 |
| TASK-400 | 도구 대기 소리: 도구가 돌거나 응답을 기다린 지 0.8초 뒤부터 반복 효과음, 마롱이 소리가 시작되면 바로 멈춤. 클라이언트에서 냄 | SPEC-389 | SCR-002#waiting, `tools/vertex_live/static/`(효과음 파일은 `server.py`의 정적 파일 허용 목록에도 더함), `MARONG_CALL_WAIT_SOUND` | TASK-399 | GPT | 1 | TC-478·479 통과 |
| TASK-401 | 사람별 통화 상한: 통화 시작 전에 그 사람의 이번 달 합을 `MARONG_CALL_PERSON_MONTHLY_USD`와 비교(비어 있으면 없음). 전체 월 150달러 규칙은 PR #41의 코드 그대로(달 기준도 그 코드의 UTC 달). 거절은 메시지 `budget_exhausted` | SPEC-390 | 통화 시작 API-107, `tools/vertex_live/`(PR #41의 `call_cost.py`) | TASK-382, TASK-410(PR #41이 맞춰진 뒤), TASK-395 | GPT | 0.5 | TC-480 통과 |
| TASK-402 | 답 하나의 상한(모델 호출 6번, 도구 실행 8번, 넘으면 지금까지 결과로 답함)과 실행 전 확인(이번 답에 준 도구만, 일정 취소는 이번에 보여 준 번호만) | SPEC-393 | `marong/chat_tool_graph.py`, `marong/agent.py` | TASK-382 | GPT | 1 | TC-481\~483 통과 |
| TASK-403 | 사전 조회 동시 읽기: 일정, 구글 캘린더, 최근 대화, 기억 검색, 친구 목록(TASK-397)을 한꺼번에, 읽기마다 시간 제한, 하나가 실패해도 나머지로 답함 | SPEC-392 | `marong/agent.py` | TASK-382, TASK-397 | GPT | 1 | TC-484 통과 |
| TASK-404 | 턴 계획: `MARONG_TURN_PLAN=off\|shadow\|prefetch`. 처음은 `shadow`(기록만). 합성 말 60개로 의도·사전 조회 범위의 정확도를 측정해 PR에 적음. 실패하면 지금 방식으로 | SPEC-391 | `marong/agent.py`, 추적 기록 | TASK-403 | GPT | 1.5 | TC-485·486 통과. 측정 결과 표가 PR에 있음 |
| TASK-405 | `schedule_add` 도구 설명과 시스템 프롬프트에 겹쳐 적힌 규칙을 한 곳으로 모음 | SPEC-393 | `marong/schedules.py`, `prompt.md`(저장소 루트) | TASK-402 | GPT | 0.5 | `tests/test_schedules.py` 통과, 도구 정의 글자 수가 줄어든 값을 PR에 적음 |
| TASK-406 | 사용량: 답·통화·그림·검색·쇼핑 읽기가 끝날 때 `usage_daily`에 더함(하루는 04:00 KST). `MARONG_DAILY_UNITS`가 있을 때만 한도, 넘으면 티켓에서 빼고 티켓이 0이면 거절(글 보내기는 429 `daily_limit`, 통화 시작은 메시지 `daily_limit`과 통화 홈 상태의 `blockedReason`). 통화 쪽은 통화 서버가 사용량을 더하는 같은 트랜잭션에서 뺌 | SPEC-394 | API-234·237·216, TBL-172·167, SCR-165·001 | TASK-387 | GPT | 1.5 | TC-487\~489 통과 |
| TASK-407 | 웹: 홈 화면 추가용 설정 파일과 아이콘, 로그인한 브라우저에 앱과 같은 페이지, 웹을 열었을 때 밀린 연락과 약속 전화 받기 버튼(프로필 응답의 `pendingRing`), 내 마롱이 화면의 구글 캘린더 연결·끊기(`/google/start`가 로그인 쿠키로 열리게 하고 `POST /google/disconnect`를 더함, SPEC-384) | SPEC-384, SPEC-396, SPEC-383 | SCR-165·107, `marong/app_chat_static/`, `marong/google_calendar.py`(`/google/` 페이지) | TASK-387 | GPT | 1.5 | TC-490·491 통과 |
| TASK-408 | 앱 0.3.0: Access 로그인 처리를 빼고 로그인 쿠키 유지, 글 대화 창에서 사진 고르기 동작, 알림 제목과 앱에 고정된 벨·통화 알림 글(`strings.xml`)의 마롱이 이름. 저장소의 버전은 0.2.2·코드 5라서 릴리스된 0.2.4와의 차이를 먼저 맞춤. 빌드·서명·`app-release publish` | SPEC-371, SPEC-377 | `apps/android/`, API-141·142 | TASK-386, TASK-392 | GPT | 2 | TC-492\~494 통과. 서명 APK의 크기·SHA-256 기록, 릴리스 API가 0.3.0을 줌 |
| TASK-409 | 정리: 디스코드 봇과 음성 중계 서비스를 멈추고 꺼 둠(지우지 않음, 되돌리기 스크립트 먼저). `README.md`, 화면 문구, 모델에게 주는 글(`DM_SYSTEM`, 구글 연결을 물었을 때의 답, 일정 도구 설명)에 남은 카카오톡·디스코드 안내를 지금 경로로 고침(뜻은 그대로, 경로를 가리키는 단어만). `docs/`의 설계 문서는 고치지 않고 고칠 곳 목록을 PR의 '설계 질문'에 적음(설계 스레드가 고침) | SPEC-376, SPEC-383 | 서버 서비스, `README.md`, `marong/discord_dm.py`, `marong/schedules.py`, `marong/google_calendar.py` | TASK-384, TASK-385, TASK-408 | GPT | 1 | TC-495 통과(디스코드 없이 하루 동안 글 답·먼저 말 걸기·일정 알림·통화) |
| TASK-410 | PR #41(일기·통화 비용)과 PR #46(성향 3단계)의 디스코드 DM 연결 조건을 로그인 확인 공통 함수로 바꿔 `main`에 맞춤. PR #41은 U1 바로 뒤에(통화 서버 작업 앞), PR #46은 그 뒤 아무 때나 | SPEC-374 | 두 PR의 브랜치 | TASK-382 | GPT | 1 | 두 PR의 시험이 `main` 위에서 통과 |

## 확인

- 명세 SPEC-370\~396마다 작업이 있어요: 370(TASK-380·386), 371(380·408), 372(380), 373(379·381), 374(382·410), 375(379·383), 376(384·409), 377(387·388·408), 378(389·390·392), 379(391·392), 380(393), 381(396), 382(397), 383(385·407·409), 384(407), 385(394), 386(395), 387(398), 388(399), 389(400), 390(401), 391(404), 392(403), 393(402·405), 394(406), 395(386), 396(407).
- API-211\~242를 만지는 작업(TASK-380·381·386·387·390·391·394·396·406)은 계약의 모든 응답에 시험이 있어야 끝나요.
- 의존에 고리가 없어요. 번호가 더 큰 작업에 기대는 것은 TASK-394(395 뒤)와 TASK-401(410의 PR #41 부분 뒤)뿐이고, TASK-410은 TASK-382에만 기대요.
- 표 TBL-164\~172마다 만지는 작업이 있어요: 164\~166(TASK-380), 165·167·168(381), 168(385), 167(387·391·394·406), 169\~171(390), 172(406).
- 화면 SCR-163\~174마다 작업이 있어요: 163·164·169(TASK-386), 165(387), 166·170\~174(392), 167(394), 168(396).

## 검토에서 고친 것(2026-11-19)

2026-11-19 14시대 KST에 동희님이 "지금까지 작업은 다 잘되고 있는건지도 검토 한번 해주고"라고 하셔서, 설계 문서를 세 가지 관점으로 다시 봤어요(요구사항에서 시험까지의 이음, 표와 API 계약, 인계 절과 실제 코드 `main` `0953b86`). 사실로 확인한 것만 고쳤어요.

실제 코드와 달랐던 것:

- 통화 서버 코드의 위치를 `marong/call/`로 적었어요. 실제는 `tools/vertex_live/`예요. 작업 표의 '만지는 곳'을 고쳤어요.
- 통화 쇼핑이 "글 대화의 읽기 함수를 부른다"고 적었는데 그런 함수가 없어요(Claude 호출 안의 서버 도구예요). 앱 서버의 내부 경로를 부르는 방식으로 바꿨어요(SPEC-388, TASK-399).
- 전체 통화 예산 코드가 `main`에 있다고 전제했는데 PR #41에만 있어요. 사람별 상한(TASK-401)을 그 뒤로 옮기고 순서를 적었어요.
- 통화 서버의 상태 응답에 약속 전화 값이 있다고 적었는데 없어요. 프로필 응답의 `pendingRing`과, 기기가 없는 사람의 벨 행을 더했어요(SPEC-383).
- 통화 시작의 거절을 HTTP 상태(409·503·429)로 적었는데 통화 시작은 웹소켓이라 화면이 읽지 못해요. 메시지로 바꿨어요(SPEC-386·390·394).
- 통화 서버의 로그인 확인 함수 이름과 동작(`identity()`, 초대 쿠키 `marong_live`, `enabled`의 쓰임), 통화 하나를 전제한 전역 값 넷을 바로 적었어요(SPEC-374, 386).
- 루프를 시작하는 곳은 `run_discord.py`예요. 새 진입점이 가져와야 할 것(캐시 데우기 루프, `/google/` 페이지 서버, 글 답 경로 설정, 방 잠금)과 디스코드 값으로 짠 파일 목록을 더했어요(명세 3.3, 3.4).
- 관리자 확인: 지금 Access 확인은 허용 이메일 목록만 봐서 목록의 누구나 통과해요. 관리자 경로에 이메일 해시 확인을 더했어요(SPEC-395).
- `friendships`를 읽는 지금 쿼리가 상태를 안 봐서, 요청만 보내도 상대의 공유 기억이 넘어갈 수 있었어요. TASK-396의 끝 조건에 넣었어요.
- 구글 연결: 끊기 페이지가 없고 연결 시작은 디스코드 DM 명령이 만든 값이 있어야 열려요. 쿠키로 열리게 하고 끊기 요청을 더했어요(SPEC-384).
- 파일 이름과 값: `prompt.md`는 저장소 루트에 있고, 알림 제목은 `marong/fcm.py`의 상수이며, 저장소의 앱 버전은 0.2.2·코드 5예요. 새 모듈 이름은 `run_app.py`와 `marong/app_session.py`로 맞췄어요.
- 시험 명령이 그대로는 돌지 않았어요(폴더 이동이 겹침, `npm ci`와 `sync` 빠짐, Playwright가 없으면 건너뛴 채 통과). 고쳤어요.

문서끼리 어긋났던 것:

- 관리자가 `link` 링크의 대상을 고를 목록이 없었어요(회원 목록은 프로필이 있는 사람만 줌). API-236에 `unlinked`를 더했어요.
- 가입 때 넣는 `contact_settings` 행이 표의 제약과 어긋났어요(명세는 비운다고, 표는 비울 수 없다고). 서버 기본값을 넣는 것으로 맞췄어요.
- 표를 고친 것: `friendships.requested_at`, 한 사람에 안 쓴 기기 추가 코드 하나의 고유 색인, `schedules.source`의 `app`([표 문서](../05-erd/unified.md)).
- 계약을 고친 것: 프로필 예시가 스키마와 안 맞던 것, 입혀 보기 예시가 명세의 고정 대사와 다르던 것, 사진 오류의 400·413·503 나눔(`check_unavailable` 더함), 표정 작업이 끝나면 지우는 것(올린 사진만), `sheet` 단계 규칙.
- 화면을 고친 것: 미리 보기에서 특징표로 돌아가는 경로, 통화할 수 없는 계정 상태를 지운 것, 공유 스위치의 자리(SCR-168), 사진 형식 글.
- 시험을 고친 것: 틀린 코드 5번의 경계(TC-437), 턴 계획 시험이 모델을 전제한 것(TC-485·486), 사전 조회 읽기 수(TC-484), 능력 소개(TC-476), 그림 예산 알림(TC-464), 금지선의 실제 모델 15번(TC-453).
- 값을 맞춘 것: 기본 목소리(Sulafat), 턴 계획 기본값, 아이폰 로그인 확인(사흘 뒤), 통화 예산의 달(UTC).

고치지 않고 남긴 것:

- 초대 링크와 보낸 친구 요청을 거두는 요청은 이번 범위에 없어요(칸만 있어요).
- 기기 추가 코드는 6자리이고 틀린 횟수를 앱 서버 메모리에서 주소별로만 세요. 지금 쓰는 사람 수에서는 그대로 둬요.
- 통화 계약 파일(`api/call-live.openapi.yaml`)과 글 대화 계약 파일의 고침은 구현 PR에서 해요(TASK-395, 401, 406).
- 통화 쇼핑의 20초와 내부 경로는 측정하지 않은 새 제안이에요. TASK-399가 측정해서 알려요.

## 설계 질문 답(2026-11-19)

GPT가 PR #55·#59·#64에 적은 설계 질문의 답이에요(설계 스레드, 2026-11-19 17시대 KST). 동희님이 정한 방향을 바꾸는 것은 없어요.

| 질문(어디서) | 답 | 고친 문서 | GPT가 할 일 |
| --- | --- | --- | --- |
| `link` 초대 링크의 대상: 계약(API-235)은 프로필이 없는 친구만, 명세(SPEC-370)와 화면(SCR-169)은 프로필이 있는 친구도(PR #55, #64) | 명세가 맞아요. `link`는 기존 친구면 되고 프로필 유무를 보지 않아요. Access로 들어온 기존 친구는 첫 요청 때 프로필 행이 생기므로(명세 3.2), 반영 ④·⑤ 때 동희님과 현경님에게 이미 프로필 행이 있을 수 있어요. 쓸 때는 빠진 행만 만들어요 | 계약 API-235의 설명 | API-235의 400 검사에서 `link`의 프로필 유무 조건을 빼고, 관리자 화면의 `link` 고르기에 `members`도 넣어요. `tests/test_unified_auth.py`에 프로필이 있는 친구의 `link` 링크 만들기·쓰기 확인을 더해요(TC-443과 같은 파일군) |
| 같은 날 보낸 친구 요청 수를 서버가 다시 떠도 남기려면 요청 기록 표가 필요함(PR #59, #64) | 표를 더하지 않아요. 하루 10번은 보낸 사람 기준으로 앱 서버 메모리에서 세고, 다시 뜨면 0부터예요(명세 4절의 기본값 표). 지금 쓰는 사람 수에서는 그걸로 충분해요 | 명세 SPEC-381의 예외 칸에 한 줄 | 없어요(지금 구현 그대로) |
| 통화에서 글로 보내는 도구(TASK-257)가 `main`에 없음(PR #55) | TASK-257은 성향 part의 작업이고 아직 시작 전이에요. 통합 앱은 통화 글 outbox 행이 앱 방에 저장되는 것까지만 맡아요(SPEC-383). 합성 행으로 확인한 것으로 충분해요 | 없음 | 없어요 |
| 기존 디스코드 화면·통화·설치 문서의 경로 안내(PR #64) | 설계 스레드가 반영 ⑪(디스코드를 끔) 때 `docs/`의 해당 문서를 고쳐요. 그 전에는 지금 안내가 맞아요 | 아직 안 고침 | 없어요 |

## 11단계 진행

GPT가 TASK마다 상태·커밋·확인한 것을 적어요(AGENTS.md '구현을 시작할 때' 6).

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-379 | DB 시험 통과 | `bc0a7f5` | KO 격리 pgserver에서 빈 DB와 합성 행 DB에 020·008을 각각 두 번 적용. 권한·방 주인·먼저 연락 상태·기억 원본 유지 확인. |
| TASK-380 | API 구현·격리 시험 | `9b8930e` | API-211~215의 초대·세션·기기 코드 구현. 관리자 경로와 프로필 API를 포함한 전체 흐름은 후속 시험 대상으로 남음. |
| TASK-381 | 격리 시험 통과 | `9b8930e` | 새 계정 동시 가입과 호출자 행 쓰기 실패 시 트랜잭션 전체 롤백. 기존 방의 대화 유지 확인. |
| TASK-382 | 앱 API·통화 인증 격리 시험 | `9b8930e` | 세 인증 모드로 앱 API 확인. 통화 역할에서 같은 세션으로 합성 웹소켓 연결·연장·거절 확인. 로그인 화면과 실기기는 후속 시험 대상으로 남음. |
| TASK-383 | 기억 조회 격리 시험 | `9b8930e` | 두 계정의 방·요약·메모·검색 격리 확인. 합성 기존 두 계정의 조회 결과가 기존 저장소와 일치. |
| TASK-384 | 앱 서버와 작업 루프 격리 시험 | `d8f1dad` | 디스코드 설정 없이 합성 답 저장. bot 모드에서는 앱 작업 루프 0개. Postgres 잠금 경합과 종료 후 다른 작업의 잠금 획득 확인. 두 앱 프로세스와 전체 작업 루프를 합친 시험은 남음. |
| TASK-385 | 앱 알림과 방 저장 격리 시험 | `d8f1dad` | 가짜 FCM 선톡·일정 알림 각 1개. 웹 계정의 선톡·일정·약속 전화 메시지와 기기 0대 벨 생성 확인. 통화 발신 도구 연결과 웹의 벨 받기 표시는 후속 범위. 싱가포르 격리 `9d6d2d0`에서 지정 계정의 기존 선톡 일정·무응답·자정·중복 방지 확인. Windows Playwright `af3ebe8`에서 미확인 앱 선톡 표시, 계정별 읽은 위치, 최신 글 이동 확인. |
| TASK-386 | 관리 API와 가입·로그인 화면 구현 | `d8f1dad` | 합성 계정으로 관리자 권한·초대 상태·티켓·세션과 기기 코드 취소 시험. 브라우저 상태 전체와 실기기 확인은 남음. 싱가포르 격리 `6d86f9a`에서 기존 프로필 연결 링크 발급·사용, 프로필과 티켓 보존, 재사용 거절 확인. |
| TASK-387 | 프로필 API와 내 마롱이 화면 구현 | `d0a3f8c` | KO 격리에서 이름 변경·공통 프롬프트 유지·약속 전화 만료 확인. 실기기와 통화 중 사용자별 이름 시험은 남음. |
| TASK-388 | 캐릭터 답변 제한 시험 | `ba9ab8f` (#66 초안) | 싱가포르 실제 모델 15개 질문을 두 차례 시험. 건강 답에서 약 언급이 반복돼 TC-453 실패. 출시 대기. |
| TASK-389 | 템플릿과 생성 어댑터 연결 | `a67b69e` | 재사용한 몸 템플릿·마스크 5종의 일치 확인. 합성 업로드의 얼굴 가림과 렌더러로 원본 미전달을 확인. |
| TASK-390 | 캐릭터 API와 실제 그림 시험 | `1f357b5` (#66 초안) | 싱가포르 실제 모델로 미리 보기 1장·후보 4장·표정 6장 생성. 두 시도 합계 0.606848달러. 합성 API에서 이름과 준비 상태 확인. 실기기 확인 전. |
| TASK-391 | 입혀 보기와 적용 격리 시험 | `a67b69e` | 두 계정의 캐릭터 읽기 격리, 입혀 보기·적용·기본 복귀·보관 해제 확인. 실제 기억 맥락 비교 대기. |
| TASK-392 | 캐릭터 화면과 정상 흐름 시험 | `a0726db` | Windows Playwright와 싱가포르 합성 서버 FL-172·173 통과. 합성 사진, 이름과 표정, 미리 보기 두 탭, 적용과 복귀 검증. 화면 상태 전수 및 실기기 확인 전. |
| TASK-393 | 그림 예산 부분 시험 | `48c4269` | 관리자 화면 80% 표시와 100%에서 새 만들기·후보 거절, 기존 후보 고르기 허용. 경고 중복·다음 달·미리 보기 거절 전수 대기. |
| TASK-394 | 계정별 목소리 합성 시험 | `9e3b38b` | 현재 통화의 목소리는 연결 중 고정하고 이후 통화에 변경 반영. 목록 밖은 Sulafat. 견본 듣기와 기기 시험 대기. |
| TASK-395 | 동시 통화 격리 시험 | `9e3b38b` | 가짜 연결 3개와 네 번째 거절, 같은 계정 중복 거절, 진단값 분리 확인. 두 실기기 동시 통화 대기. |
| TASK-396 | 친구 API·화면 구현, 격리 시험 | `70de918` | KO 합성 DB에서 요청·수락·거절·동의·끊기·당일 한도 확인. 재시작 후 같은 상대 재요청 횟수 복구와 브라우저 전체 상태 확인은 대기. |
| TASK-397 | 관계 조회 격리 시험 | `70de918` | KO 합성 DB에서 글·통화 관계 조회가 수락한 관계만 반환하고 공유를 끄면 메모가 빠짐. 모델 호출 연결 시험은 대기. |
| TASK-398 | 지시문 조립 시험 | `2814a63` | 통화 지시문 기존 규칙과 변경 지시를 KO 격리에서 검증. 실기기 대본은 대기. |
| TASK-399 | 내부 호출 합성 시험 | `d7af8ce` | 내부 경로 인증·상품 결과·통화 및 일일 횟수 확인. 실호출 10회는 대기. 싱가포르 실호출 10회에서 20초 이내 9회, 중앙값 8.349초, 검증 상품 0건. 공개 상품 지정 실통화에서도 실패해 설계 질문에 기록. |
| TASK-400 | 브라우저 대기음 구현 | `2814a63` | 대기 켬·끔 신호와 통화 재생 연결을 검증. 실제 음향 겹침 측정은 대기. 싱가포르 `8fa96da`에서 가짜 공급자 회귀 시험과 실제 통화 대기 신호 5.345초, 음성 이전 종료를 확인. 폰 음향 확인 대기. |
| TASK-401 | 개인 통화 예산 격리 시험 | `2814a63` | 두 합성 계정·두 UTC 월의 집계와 경계 금액을 검증. 기존 전체 예산·PCM 전환 시험 통과. |
| TASK-402 | 그래프 합성 시험 | `5a8b0a2` | 한 답 6번째 모델 호출에 마지막 도구 결과만 전달, 8회 뒤 실행 중단 확인. 미제공 도구와 미표시 일정 번호 거절 확인. |
| TASK-403 | 사전 조회 구현 및 회귀 시험 | `5a8b0a2` | 일정·캘린더·대화·친구 조회 동시 시작. 기억 검색은 대화 ID와 요약 ID를 받은 뒤 시작. 각 제한 및 누락 종류를 기록. |
| TASK-404 | 분류 규칙 및 운영 기록 확인 | `4707815` | 싱가포르 합성 의도 60/60·날짜 범위 10/10, 중앙값 0.006ms·최대 2.038ms. 운영 shadow 기록 0건이라 shadow 유지. |
| TASK-405 | 일정 도구 설명 정리 | `44bdc5a` | 설명 413자에서 211자로 축약, 공통 일정 지시 중복 제거. 일정 회귀 107개 통과. |
| TASK-406 | 사용량 API·차감 격리 시험 | `25523ee` | KO 합성 DB에서 한국 시각 04시 경계, 글 답 2회·통화 90초·그림 1장 87단위, 계정 격리, 동시 티켓 차감과 글·웹소켓 거절 확인. 화면·실기기 시험은 대기. Windows Playwright `3ea352f`에서 티켓 지급 후 쓰던 글이 남고 발송 가능 확인. |
| TASK-407 | 홈 화면 및 구글 연결 격리 시험 | `4cc5717` | KO 합성 쿠키 로그인·구글 시작·취소·끊기, 매니페스트와 아이콘 확인. 아이폰과 실제 구글은 대기. |
| TASK-408 | 노트북 서명 후보 빌드 | `4cc5717` | 0.3.0 코드 8 기존 릴리스 인증서 일치, Java 단위 시험·lint·디버그 및 릴리스 빌드 통과. 운영 배포와 기기 시험 대기. |
| TASK-409 | 앱·웹 및 일정 안내 변경 | `4707815` | Windows 브라우저 42개 통과. 싱가포르 격리 일정 107개·캘린더 116개·앱 채팅 376개 통과. 운영 디스코드 서비스 3개 정지 확인. 24시간 관찰과 실기기 확인 전. |
| TASK-410 | 비용과 기억 이전 코드 통합 시험 | `1c82598` | PR #41과 #46을 통합 스택에 맞춰 비용·출처 격리·기억 작업 예약·채팅 기록·통화 지시문 시험을 확인. 두 초안의 병합과 운영 반영 대기. |
