# 마롱이의 일기·통화 비용 작업 목록(10단계 WBS, CTX-007, CTX-002·006 바꿈)

2026-11-17 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [diary.md](../04-functional-spec/diary.md)(SPEC-150\~168)와 [call-cost.md](../04-functional-spec/call-cost.md)(SPEC-169\~183), 계약 [diary.openapi.yaml](../../api/diary.openapi.yaml)(API-108\~120), [listen-test.openapi.yaml](../../api/listen-test.openapi.yaml)(API-121\~123), [call-live.openapi.yaml](../../api/call-live.openapi.yaml)(API-107, API-124), [discord-relay.openapi.yaml](../../api/discord-relay.openapi.yaml)(API-125, API-126), 표 [016_diary.sql](../../marong/migrations/016_diary.sql)·[017_listen_test.sql](../../marong/migrations/017_listen_test.sql)·[007_call_cost.sql](../../marong/call/migrations/007_call_cost.sql)(TBL-103\~114), 화면 [08-screens](../08-screens/README.md)(SCR-113\~119, SCR-001#budget), 공통 화면 기준 [design/README.md](../../design/README.md), 시험 계획 [12-qa/diary-call-cost.md](../12-qa/diary-call-cost.md)(TC-159\~179).

## GPT 인계

- 목표: 친구가 마롱이와 나눈 하루 얘기(1:1 글 대화와 통화 자막)가 다음 날 아침 마롱이 시점의 그림일기 한 장으로 오고, 친구는 일기장에서 넘겨 보고 말로 고치고 다시 그리고 도장을 찍어요. 함께 통화 비용을 턴마다 세서 월 예산을 넘기 전에 막고, 설정 실험과 듣기 시험으로 통화 값을 줄일 근거를 모아요. 동희님 2026-11-16 15:57 KST 연구 요청과 "설계까지 해보자", 방향 고르기 2026-11-16 21:44 KST 결정 카드 'A 그림일기장'(D22, [도메인 설계](../01-domain/domain.md)).
- 시작 조건: 화면 작업(TASK-152\~155, TASK-158의 SCR-001#budget 화면, TASK-304의 듣기 시험 페이지)은 09 토큰 얼리기 뒤예요. 얼리기는 다른 스레드의 화면이 다 모인 뒤라 늦어질 수 있어요(2026-11-17 14:37 KST 동희님 "있으면 기다리고"). 나머지(봇·서버·API·도구)는 토큰을 쓰지 않아서 PR #25가 합쳐진 뒤 바로 시작해도 돼요.
- 시작: PR #25가 `main`에 합쳐졌으면 `main`에서, 아니면 브랜치 `claude/project-thread-7y5bt4`의 머리(설계 끝 커밋 `3516c86` 이후 문서만 더한 커밋)에 그때의 `main`을 합친 뒤 새 브랜치 `codex/diary-call-cost`. PR #25는 `main` 2a473ae에서 갈라졌어요.
- 읽을 것: 기능 명세 두 개의 1절(공통 규칙), 2절 표의 SPEC-150\~183, 3절(자세한 규칙), 5절(AI-6\~10 호출), 계약 다섯 개의 API-107·108\~126과 `components.x-corthex.errors`, 마이그레이션 세 개, 화면 정의 SCR-113\~119와 SCR-001의 #budget, [design/README.md](../../design/README.md) 1\~4·8절, 시험 계획 TC-159\~179. 목업은 캔버스 [마롱이 화면 설계](https://claude.ai/artifact/CC154gunovJS3tqa8XkpZ9)의 `A1xx-*`·`Main`·`A-*`(일기, SCR-119 포함)와 `A001-budget` 대지예요(비공개라 동희님이 공유해 줘야 열려요. 못 열면 화면 정의와 design/README.md만으로 만들어요). 이 밖의 문서는 읽지 않아도 돼요.
- 용어: 이 목록과 시험 계획의 '버전'은 기능 명세·ERD·계약의 '판'(일기 글의 revision, TBL-107·`revision`)이고, '단어'는 명세의 '낱말'이에요. AI 지침 버전(`diary-v1`)은 따로 적었어요.
- 이미 된 것: 설계(01\~09)와 이 작업 목록·시험 계획만이에요. 마이그레이션 세 개는 초안 SQL이고 어느 DB에도 넣지 않았어요. `docs/05-erd/schema-check-2026-11-16.sql`은 2026-11-16 개발용 Postgres에서 돌려 본 확인 질의예요(믿어도 되는 범위: 표 모양과 제약. 운영 데이터로는 안 돌림). 일기 대지는 `design/base.tokens.json`에서 만든 목업이라 코드가 아니에요.
- 순서: TASK-137(구현 전 실계정 확인, 동희님 준비물 뒤) → TASK-138(마이그레이션) → 일기 봇 쪽 (TASK-139, TASK-140, TASK-142) → TASK-141 → TASK-143 → TASK-144 → TASK-145, 일기 서버 쪽 TASK-146 → (TASK-147, TASK-148, TASK-149, TASK-150) → TASK-151, 화면 TASK-152 → (TASK-153, TASK-154) → TASK-155. 통화 비용은 일기와 따로 TASK-156 → TASK-157 → TASK-158 → (TASK-159, TASK-300) → TASK-301 → (TASK-302, TASK-303), 듣기 시험 TASK-304는 TASK-138·146 뒤. 반영 TASK-305는 모두 뒤, 실제 폰·운영 확인 TASK-306은 마지막.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node(`apps/android`의 `npm test`·`npm run test:browser`, Playwright). 모델은 모두 가짜예요(일기 쓰기·고치기 AI-6·7, 그림 AI-8, 통화 AI-9는 `tests/fakes.py`와 `tools/vertex_live`의 가짜 연결 방식으로). 진짜 모델·유료 API는 TASK-137과 TASK-303(기억 시험, 동희님이 실험 이름을 정해 줄 때)에서만, 그 TASK에 적은 한도 안에서 불러요.
- 반영: TASK-305에서 해요. 봇 DB에 016·017, 통화 DB에 007. 파일은 봇(`marong/app_diary.py`, `marong/app_listen.py`, `marong/diary.py`, `marong/app_chat.py`, `marong/app_chat_static/`, `marong/agent.py`, `run_discord.py`, `tools/admin.py`, `tools/listen_test.py`, `tools/report.py`)과 통화 서버(`tools/vertex_live/`의 바뀐 파일, `tools/discord_voice/`). 켜고 끄기: 일기는 `MARONG_DIARY=1`(기본 꺼짐, 켜도 `diary on`을 한 친구만), 그림 월 예산 `MARONG_DIARY_IMAGE_BUDGET_USD=5`, 통화 예산은 `call.settings`의 `monthly_budget_usd`(지금 150), 설정 실험은 `call-tuning use`로만 바뀌어요(기본 실험은 지금 통화와 같은 값). 재시작은 대화·통화가 없을 때. 되돌리기 스크립트를 먼저 서버 `~/marong-deploy/<날짜>-diary-call-cost/`에 둬요.
- 하면 안 되는 것: 일기 글·제목·장면·고칠 말·하루 모음·그림을 로그·시트·관리 보기에 남기기(REQ-177). 친구 대화 원문을 시험 데이터로 쓰기(지어낸 대화만). 일기를 지우는 경로 만들기(버전과 그림은 쌓기만). 장면 검사(SPEC-154)를 끄는 설정 두기. 새 글꼴·CDN을 밖에서 불러오기(Gaegu는 서버가 직접 내려줌). 토큰에 없는 색·크기를 새로 만들기(design/README.md 3절). 앱(`apps/android/`)과 터널·Access 설정 바꾸기(일기·듣기 주소가 모두 `/chat/` 아래라 필요 없음). 예산 막기를 끄는 설정 두기. `/opt/marong/prompt.md` 덮어쓰기.
- 겹치는 파일: `marong/agent.py`(SPEC-165 도장 한 줄)와 `tools/report.py`(SPEC-181)는 선 전화(PR #27, 2026-11-17 `main` 4c74b02에 합쳐짐)·성향 맞춤과 같이 고쳐요. 성향 0단계(PR #30)도 먼저 합치고 그 위에서 시작해요(docs/10-wbs/README.md '겹치는 파일', PR #29). `marong/app_chat.py`·`chat.js`·`chat.css`는 앱 자동 업데이트(TASK-183)가 메뉴 줄을 더하니 늦게 합치는 쪽이 맞춰요. `tools/vertex_live/live_session.py`·`server.py`는 지금 다른 패키지가 고치지 않아요. `design/base.tokens.json`은 고치지 않고 읽기만 해요.
- 사람 확인: TC-179(갤럭시 앱에서 일기장 P95 2.5초, 원고지 줄바꿈, 아이폰 Safari, 구글 청구서와 `call-cost` 비교, 조용할 때 문을 켰을 때 말 잘림). 일기를 처음 켜는 친구(`diary on`)는 동희님이 정해요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-159\~178 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TASK-305의 읽기 확인.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드('마롱이의 일기 설계하기')가 답해요.

```bash
.venv/bin/python tests/test_diary.py          # 일기 봇 쪽: TC-159~165, TC-171
.venv/bin/python tests/test_app_diary.py      # 일기 API: TC-166~170
.venv/bin/python tests/test_listen.py         # 듣기 시험 API: TC-178
.venv/bin/python tools/vertex_live/test_call_cost.py   # 통화 사용량·비용·예산: TC-173~175, TC-177
.venv/bin/python tools/vertex_live/test_tuning.py      # 설정 실험·조용할 때 문·글로 갈아타기: TC-176
.venv/bin/python tests/test_app_chat.py tests/test_report.py   # 글 대화와 시트가 그대로인지
cd apps/android && npm test && npm run test:browser   # 일기장·듣기 시험·통화 홈 예산 화면: TC-172, TC-174, TC-178
```

확인 질문 세 개(02 일기 요구사항 '열린 질문')는 D63(2026-11-17 15:15 KST)으로 추천안대로 정해졌어요: ① 일기 하루는 한국 시각 04:00에 끊어요(REQ-139) ② 일기 글은 Anthropic 모델(AI-6·7)이 써요 ③ 도장은 1:1 방 답을 만들 때 날짜만 읽어요(SPEC-165).

구현 전 동희님 준비물(TASK-137): 일기 전용 OpenAI 프로젝트·키와 월 한도, 서버 비공개 설정에 키 넣기, 구글 지출 상한 예산(서버 120%인 180달러보다 높게, 예: 200달러).

## 작업

- 담당: 모두 GPT예요. 실제 폰과 운영 확인(TASK-306)은 동희님(현경님 폰은 동희님이 부탁)과 같이 해요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.
- 새 파일 이름(`marong/diary.py`, `marong/app_diary.py`, `marong/app_listen.py`, `tests/test_diary.py` …)은 명세 1절과 이 표의 제안이에요. 더 맞는 자리가 있으면 바꾸고 PR 설명에 적어요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-137 | 구현 전 실계정 확인(명세 7.1 두 개): OpenAI 그림 `/v1/images/edits`가 참고 그림 두 장과 `output_format: webp`를 받는지·사용량 칸·거절 모양, Anthropic 구조화 출력 + effort `xhigh` 걸린 시간(하루 모음 12,000자)·거절 `stop_reason`, Vertex Live `usageMetadata` 칸·오는 때·누적 여부(`probe_live.py`), `audioStreamEnd`, 핸들 없는 새 연결의 `setupComplete` 시간 | SPEC-153, SPEC-155, SPEC-169, SPEC-178, SPEC-179 | 개발 서버, 실제 API | 동희님 준비물 | GPT | 0.5 | 결과(칸 이름, 시간, 오류 모양)를 이 파일 '11단계 진행'에 적고, 명세와 다르면 '설계 질문'. 실제 비용 합 1달러 이하(그림 3장, 글 5번, 통화 3분) |
| TASK-138 | 마이그레이션 넣기: 봇 DB `016_diary.sql`·`017_listen_test.sql`, 통화 DB `007_call_cost.sql`을 pgserver에 두 번 돌려도 같은 결과(멱등)인지, `marong/schema.sql`·`marong/call/schema.sql`에 같은 표를 반영, 단가표 첫 줄(3.2) | SPEC-172, TBL-103\~114 | 마이그레이션, 스키마 | 없음 | GPT | 0.5 | 시험이 빈 DB와 옛 DB(015·006까지 넣은 DB) 모두에 두 번 적용해 오류 0, `docs/05-erd/schema-check-2026-11-16.sql` 결과가 같음 |
| TASK-139 | 일기 켜기·끄기와 관리 명령: `tools/admin.py diary <친구> on`·`off [--now]`·`status`, `diary month [YYYY-MM]`, `diary <친구> run <YYYY-MM-DD>`, `bash deploy/ovh.sh admin diary …` | SPEC-150, SPEC-167, SPEC-168 | TBL-103, TBL-105, TBL-106, TBL-108 | TASK-138 | GPT | 0.75 | TC-159 통과 |
| TASK-140 | 하루 모음: 1:1 방 말(카톡 1:1, 디스코드 DM과 앱 글 대화)과 통화 자막을 일기 하루(04:00\~04:00 KST) 안에서 시간순 줄로, 단체방·공유 메모·일기 제외 요청 빼기, '데이터' 표시로 감싸기, 12,000자 자르기(3.2) | SPEC-152 | `marong/diary.py` | TASK-138 | GPT | 1 | TC-161 통과 |
| TASK-141 | 밤 작업과 일기 줄: `run_discord.py` 안 `MARONG_DIARY=1`일 때 1분마다(앞 회차가 돌면 건너뜀), D+1 04:10\~22:00에 켜진 친구마다 줄 하나, 상태(3.1)와 다시 하기·22:00 마감, 친구 말 40자 미만이면 `skipped` | SPEC-151 | `marong/diary.py`, `run_discord.py`, TBL-105 | TASK-139, TASK-140 | GPT | 1 | TC-160 통과 |
| TASK-142 | 장면 검사(3.3): 영어만, 한글·숫자·전자우편·주소·전화번호 없음, 문장 1\~3개, 400자, 첫 단어 목록, 사람 단어 목록. 순수 함수 | SPEC-154 | `marong/diary.py` | 없음 | GPT | 0.5 | TC-163 통과 |
| TASK-143 | 일기 쓰기(AI-6, 버전 `diary-v1`)와 서버 확인: JSON 스키마, 제목 2\~20자, 글 60\~160자, 마음 날씨 목록, 한글 있음, 장면 1\~400자, 버전 1 저장, AI 기록(TBL-106) | SPEC-153 | `marong/diary.py`, TBL-106, TBL-107 | TASK-141, TASK-142 | GPT | 1 | TC-162 통과(가짜 모델로 범위 안·밖·금지 질문 포함) |
| TASK-144 | 그림 그리기(AI-8)와 그림 월 예산: 3.5 지시문과 내 모습 카드, 받은 그림 확인(머리 바이트 webp·png, 5MB, 가로가 김), 저장(TBL-108), 실패 30분 뒤 한 번 다시, 예산(한국 시각 달, 비용 공식 3.5) 넘으면 기본 그림 | SPEC-155, SPEC-156 | `marong/diary.py`, TBL-106, TBL-108 | TASK-143 | GPT | 1 | TC-164 통과 |
| TASK-145 | 아침 알림: D+1 08:30\~22:00 1분마다, `ready`·숨기지 않음·안 알림·멈추지 않음, '보내는 중'을 먼저 남겨 많아야 한 번, D18 경로(`AppRoutes.say` 종류 `diary` 또는 디스코드 DM), 문장 3.7 | SPEC-157 | `marong/diary.py`, `marong/app_delivery.py`, TBL-105 | TASK-144 | GPT | 0.5 | TC-165 통과 |
| TASK-146 | 일기 읽기 API: `marong/app_diary.py`를 글 대화 서버에 붙이고 `_who`(DM 연결 필요)와 오류 모양을 같이 써요. API-108 최근 날, API-109 달력, API-110 한 날(앞·뒤 날 포함), API-116 숨긴 일기, API-117 그림(`private, immutable`), 나머지는 `no-store` | SPEC-158, SPEC-159, SPEC-163 | API-108, API-109, API-110, API-116, API-117, `marong/app_chat.py` | TASK-138 | GPT | 1 | TC-166 통과(계약에 적힌 응답마다 시험) |
| TASK-147 | 말로 고치기 API-111: `Origin` 확인, `Idempotency-Key`(24시간), 버전 잠금·`stale_revision`, 성공 5번·분당 5번, 하루 모음 다시 만들기, AI-7, 장면 검사, 새 버전 | SPEC-160 | API-111, TBL-107, TBL-109 | TASK-146, TASK-143 | GPT | 1 | TC-167 통과 |
| TASK-148 | 다시 그리기 API-112: 202로 받고 뒤에서 그림, 2번·분당 5번·그림 월 예산, 바꿀 점은 AI-7로 장면만 다시 쓰고 검사 | SPEC-161 | API-112, TBL-108, TBL-109 | TASK-146, TASK-144 | GPT | 0.75 | TC-168 통과 |
| TASK-149 | 마음 날씨·숨기기·도장: API-113(새 버전, 고치기 횟수에 안 셈), API-114(숨기면 넘기기·달력·알림에서 빠짐), API-115(찍은 시각) | SPEC-162, SPEC-163, SPEC-164 | API-113, API-114, API-115, TBL-105, TBL-107 | TASK-146 | GPT | 0.5 | TC-169 통과 |
| TASK-150 | 내 모습 카드: API-118 읽기, API-119 저장(3.6 목록), API-120 비우기 | SPEC-166 | API-118, API-119, API-120, TBL-104 | TASK-146 | GPT | 0.25 | TC-170 통과 |
| TASK-151 | 마롱이가 도장 알기: 1:1 방 답의 '# 지금 상황'에 지난 24시간 도장 한 줄(날짜만) | SPEC-165 | `marong/agent.py` | TASK-149 | GPT | 0.25 | TC-171 통과 |
| TASK-152 | 일기장 한 날 화면 SCR-113: 페이지 `/chat/diary/`·`/chat/diary/YYYY-MM-DD`(같은 HTML·JS·CSS, 봇이 내보냄), 머리('글 대화' 돌아가기·달력·더 보기), 종이·양식 줄·마음 날씨·그림 틀·원고지(칸 수 공식, `aria-hidden` + 읽기용 문단)·도장·넘기기, 상태 28개, 테마 시간 규칙, Gaegu를 서버가 내려줌 | SPEC-158, SPEC-159, SCR-113 | `marong/app_chat_static/diary/`, `marong/app_diary.py` | TASK-146 | GPT | 2 | TC-172의 SCR-113 줄 통과(360·430px, 두 테마), 대지와 견준 사진을 PR에 붙임 |
| TASK-153 | 말로 고치기·다시 그리기 칸 SCR-114·115: 아래에서 올라오는 칸(`#fix`·`#redraw`, 뒤로 가기가 닫음), 남은 횟수, 보내는 중·입력 오류·한도·stale·권한·오류 상태, 쓴 말을 실패해도 남기기 | SPEC-160, SPEC-161, SCR-114, SCR-115 | `marong/app_chat_static/diary/` | TASK-152, TASK-147, TASK-148 | GPT | 1 | TC-172의 SCR-114·115 줄 통과 |
| TASK-154 | 달력·숨긴 일기·내 모습 카드 SCR-116·117·118(`#calendar`·`#hidden`·`#look`, 화면 가득 칸) | SPEC-159, SPEC-163, SPEC-166, SCR-116, SCR-117, SCR-118 | `marong/app_chat_static/diary/` | TASK-152, TASK-149, TASK-150 | GPT | 1 | TC-172의 SCR-116\~118 줄 통과 |
| TASK-155 | 글 대화 머리의 '일기장' 버튼(SCR-107): API-108의 `enabled`가 참이거나 `date`가 있을 때만, `/chat/diary/`로 | SPEC-157, SCR-107 | `marong/app_chat_static/chat.js`·`chat.css` | TASK-152 | GPT | 0.25 | TC-172의 SCR-107 줄 통과, `chat-page.e2e.cjs` 그대로 통과 |
| TASK-156 | 턴 사용량 받기와 저장: 받는 고리에서 `usageMetadata` 숫자 칸만 꺼내 대기열(2,000개)에, 구간마다 저장 일꾼(2초마다·닫힐 때, 한 트랜잭션), (구간, 순번) 한 번만, 받은 시각의 단가 줄(10분 기억), 달러(3.1) | SPEC-169, SPEC-170, SPEC-172 | `tools/vertex_live/live_session.py`, TBL-110, TBL-112, TBL-113 | TASK-138, TASK-137 | GPT | 1 | TC-173 통과 |
| TASK-157 | 이번 달 통화 비용과 예산 상태: 사용량 합 + 추정 구간(분당 `usd_per_minute`) + 검색 초과분 + 정리 토큰(생각 토큰 포함), 30초 기억, 상태 `ok`·`warn`·`exhausted`·`hard_stop`과 처음 넘을 때 기록 | SPEC-171, SPEC-173, SPEC-174 | `tools/vertex_live/call_memory.py` 또는 새 `cost.py`, `organizer.py`, `call.budget_events` | TASK-156 | GPT | 1 | TC-173·174의 계산 줄 통과 |
| TASK-158 | 새 통화 막기: 웹 `/api/me`의 `canCall`·예산 상태(API-124), 새 통화의 `/live`가 연결 뒤 `{"type":"budget_exhausted"}`를 보내고 닫기(API-107#101, 통화 기록·구글 연결 없음), 중계 `/available`·`/live`의 429 `budget_exhausted`(API-125, API-126), 통화 홈 #budget 화면(SCR-001, 끝 문장과 '글 대화' 버튼) | SPEC-174, SCR-001#budget | API-107, API-124, API-125, API-126, `server.py`, `discord_relay.py`, `static/app.js` | TASK-157 | GPT | 1 | TC-174 통과 |
| TASK-159 | 디스코드 예산 안내 말과 120% 끝내기: 음성 봇이 429면 안내 말(`budget-notice.ogg`, 3.7) 한 번 틀고 나감·다시 들어오기 전엔 안 들어감, 통화 중 `hard_stop`이면 마이크 소리 멈추고 인사 지시 한 턴, 늦어도 15초 뒤 끝(`budget_hard_stop`) | SPEC-175, SPEC-176 | `tools/discord_voice/index.mjs`, `live_session.py`, `make_clips.py` | TASK-158 | GPT | 1 | TC-175 통과 |
| TASK-300 | 설정 실험: `call-tuning add`·`use`·`list`(이름마다 한 번 정하면 그대로), 구간을 열 때 지금 실험을 읽어 구글 설정·seed에 쓰고 구간과 사용량에 이름 남기기, 열린 구간은 그대로 | SPEC-177 | TBL-111, `call.settings`, `live_session.py`, `cost_admin.py` | TASK-156 | GPT | 0.75 | TC-176의 실험 줄 통과 |
| TASK-301 | 웹 조용할 때 문(3.4)과 글로 갈아타기(3.5): 20ms RMS 문(앞 300ms, 뒤 1초, 닫을 때 `audioStreamEnd` 한 번), 조용한 틈에 핸들 없는 새 연결·seed·10초 안 `setupComplete`·실패 시 이전 연결 유지 | SPEC-178, SPEC-179 | `live_session.py`, `server.py`, `rtc_transport.py` | TASK-300 | GPT | 1.5 | TC-176의 문·갈아타기 줄 통과 |
| TASK-302 | 관리 명령과 시트: `call-cost [YYYY-MM]`·`--switch`, `call-price add`, `call-tuning …`, `bash deploy/ovh.sh call-admin …`, `call.session_report`와 '통화 세션' 탭 칸 | SPEC-180, SPEC-181 | `tools/vertex_live/cost_admin.py`, `tools/report.py`, `tools/sheet.gs` | TASK-157, TASK-300 | GPT | 0.75 | TC-177 통과 |
| TASK-303 | 통화 중 기억 자동 시험: `memory_bench.py --tuning <이름> [--runs 3]`, 지어낸 대본 소리(`tools/vertex_live/bench/`), 4분·8분 맞힌 비율과 1분당 비용 | SPEC-182 | `tools/vertex_live/memory_bench.py`, `bench/` | TASK-300 | GPT | 1 | TC-178의 기억 시험 줄이 가짜 연결로 통과. 진짜 연결로 돌리는 건 동희님이 실험 이름을 정해 줄 때만(한 번에 10분 안) |
| TASK-304 | 듣기 시험: 문장 10개 고정 파일, `tools/listen_test.py make`(임의 id, 정답표는 서버 파일에만), `marong/app_listen.py`(API-121\~123), 화면 SCR-119 `/chat/listen/` | SPEC-183, SCR-119 | API-121, API-122, API-123, TBL-114, `marong/app_chat_static/listen/` | TASK-138, TASK-146 | GPT | 1.25 | TC-178의 듣기 줄 통과 |
| TASK-305 | 서버 반영: 백업, 마이그레이션 016·017(봇 DB)·007(통화 DB), 파일, 설정(`MARONG_DIARY`는 꺼 둔 채), 대화·통화 없을 때 재시작, 로그 5분 확인, 되돌리기 스크립트 | 명세 1절 | 서버 | TASK-139\~159, TASK-300\~304 | GPT | 0.5 | 반영 뒤 실제 주소의 API-108이 `enabled=false`, `/api/me`에 예산 상태, `call-cost` 출력, 로그 오류 0, 되돌리기 경로를 PR에 적음 |
| TASK-306 | 실제 폰·운영 확인: 동희님이 고른 친구에 `diary on` 뒤 첫 주(명세 7.2), 갤럭시·아이폰(7.3), 통화 첫 2주(call-cost 7.2) | REQ-175, REQ-176, 명세 7절 | 폰, 운영 | TASK-305 | GPT(동희님이 폰·청구서 확인) | 2주 관찰 | TC-179 결과 기록. 다르면 버그로 기록 |

## 확인

- 명세의 행(SPEC-150\~183, 모두 active)마다 작업이 있어요: 150·167·168 → 139, 151 → 141, 152 → 140, 153 → 143, 154 → 142, 155·156 → 144, 157 → 145, 158·159 → 146·152·154, 160 → 147·153, 161 → 148·153, 162·163·164 → 149, 165 → 151, 166 → 150·154, 169·170·172 → 156, 171·173 → 157, 174 → 157·158, 175·176 → 159, 177 → 300, 178·179 → 301, 180·181 → 302, 182 → 303, 183 → 304.
- API를 만지는 작업(TASK-146\~150, 158, 304)은 그 operation이 계약에 적은 응답마다 시험이 통과해야 끝나요(TC-166\~170, 174, 178).
- 화면 SCR-113\~119와 SCR-001#budget, SCR-107의 '일기장' 버튼마다 작업이 있어요(TASK-152\~155, 158, 304).
- 의존에 고리가 없어요. 모든 작업은 번호가 더 작은 작업에만 기대요. TASK-300\~306은 137\~159 다음 번호예요(이 패키지의 TASK 범위 137\~159가 모자라 300\~329에서 이어 씀).

## 11단계 진행

GPT가 TASK마다 상태·커밋·확인한 것을 적어요(AGENTS.md '구현을 시작할 때' 6).

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-137\~159, TASK-300\~306 | 시작 전 | | |
