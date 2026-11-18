# 성향 맞춤·선톡·부탁·친구 기억 1~4단계 작업 목록(10단계 WBS)

2026-11-17 15시대 KST 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [persona.md](../04-functional-spec/persona.md)의 SPEC-192~242와 AI-13~19, 요구사항 [persona.md](../02-prd/persona.md)의 REQ-213~259, 표 [05-erd/persona.md](../05-erd/persona.md)와 마이그레이션 `marong/migrations/019_persona.sql`(TBL-115~124·127~134), API 계약 [api/persona.openapi.yaml](../../api/persona.openapi.yaml)(API-127~136)과 글 대화 계약 0.4.0의 `Message.card`, 화면 정의 [08-screens/persona.md](../08-screens/persona.md)와 SCR-120~123, 시험 계획 [12-qa/persona.md](../12-qa/persona.md)의 TC-256~289·330~378. 0단계 고침은 [persona-stage0.md](persona-stage0.md)에 따로 있어요.

## GPT 인계

- 목표: 친구마다 원하는 대하는 방식(친구 약속·맞춤형 지침·친구 규칙)을 모든 방과 통화에서 지키고, 부탁은 할 수 있는 일로 해 주거나 대안을 주고, 위기 때 같은 질문을 되풀이하지 않고, 지난 대화를 기억해서 선톡하고, 지친 친구에게서 이야기를 끌어내요. 동희님 원문(2026-11-16 이 스레드 첫 요청): "'나는 이런 친구가 필요해' 같은 과정", "뭐 좀 해달라고하면 해 줘", "선톡도 … 예전 대화내역을 기반으로", "이야기 하고싶은거를 이끌어내는것도 종종 필요", "랭그래프로". D24(2026-11-17 12:24 KST '바로 고치고 전부 설계'), D25(12:2x KST 맞춤형 지침과 완화책 다섯 가지 "모두 승인"), D60(12:37 KST "구현은 gpt 시킬거야"). 원문 자리는 [docs/02-prd/persona.md](../02-prd/persona.md#출처-표기)
- **시작 가능**(2026-11-17 16시대 KST). 시작 조건 셋이 모두 됐어요: (1) 구현 전 2차 논의는 D63(2026-11-17 15:15 KST 결정 카드 '추천대로 모두 정하기', 아래 '시작 전에 정할 것')으로 끝 (2) 0단계 `codex/persona-stage0`가 `main`에 합쳐짐(PR #31, `04b3b13`) (3) 이 설계 문서가 `main`에 합쳐짐(PR #30 → PR #25 → PR #33, `5a317f9`). [README](README.md#작업-패키지) 표도 '시작 가능'으로 고쳤어요
- 시작: 단계마다 `main` 머리에서 새 브랜치. 순서와 브랜치는 1단계 `codex/persona-stage1`(TASK-211~229) → 3단계 `codex/persona-stage3`(TASK-230~243) → 2단계 `codex/persona-stage2`(TASK-244~252) → 4단계 `codex/persona-stage4`(TASK-253~259). 앞 단계 PR이 합쳐진 뒤 다음 단계를 시작해요
- 읽을 것: 기능 명세 1절 6~13번(1~4단계 공통 규칙), 그 단계의 SPEC 행과 3절의 해당 소절, 4절의 AI 항목. 표는 `019_persona.sql`과 05 문서의 3·6절. API는 `api/persona.openapi.yaml`과 `api/app-chat.openapi.yaml`의 `Message.card`. 화면은 `docs/08-screens/persona.md`와 SCR-120~123, 목업 방향은 `design/persona-candidates.md`의 '결정' 줄. 시험은 `docs/12-qa/persona.md`의 그 단계 TC. 그 밖의 문서는 ID로 가리킬 때만
- 이미 된 것: 코드 없음. 마이그레이션 019는 초안이에요(pgserver에 적용해 81개 시험을 돌린 설계 확인용, 서버에는 넣지 않음). 계약은 OpenAPI 검사 통과, 화면은 회색 와이어프레임과 목업만 있어요
- 순서: 아래 TASK 표의 번호 순서. 같은 단계 안에서 `Depends on`이 끝난 작업은 같이 해도 돼요. 3단계를 2단계 앞에 둔 이유: 2단계 게이트의 기억형 후보(열린 고리·돌봄 안부)가 3단계 친구 기억에서 나와서, 2단계를 먼저 켜면 기억 기반 선톡이 비어요(명세 6절 '단계 차이'). 순서는 D63에서 이대로 두기로 했어요
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md '시험'), LangGraph 시험은 지금 통화 정리기 시험처럼 pgserver 위 `AsyncPostgresSaver`. 화면 시험은 Playwright(Chromium, 360·430px). 카카오·디스코드·FCM·모델은 가짜예요. 진짜 모델을 부르는 시험(레드팀 TC-369~375, 기억 시험지 TC-347)은 단계마다 1만 원 안에서 테스트용 키로 돌려요(D63 ⑧). 돌리기 전에 셈한 값을 PR에 적고, 1만 원을 넘을 것 같으면 돌리기 전에 PR 설명의 '설계 질문'으로 여쭤요
- 반영: 단계마다 함. 동희님 상시 반영 허락(2026-11-15 19:58 KST "만들어지는대로 계속 넣어", 조건: 백업·대화와 통화가 없을 때 재시작·되돌리기 스크립트)으로 해요. 마이그레이션 019는 1단계 반영 때 한 번(빈 표, 기능 꺼짐). 기능은 설정으로 켜요(명세 공통 12): 1단계 `MARONG_FRIEND_CARD=on`, `MARONG_SAFETY=on`과 검사 1단계 항목, 3단계 `MARONG_FRIEND_MEMORY=shadow` → 동희님이 숫자를 보고 `on`, 2단계 `MARONG_PROACTIVE_GRAPH=shadow` 3일 → 동희님이 숫자를 보고 `on`(SPEC-221), 4단계 `MARONG_TALK_GRAPH=on`. 다시 시작: `marong-discord`, 카카오 봇이 서버에서 돌면 그것도, 통화를 고친 단계는 통화 서비스. 되돌리기: 서버 `~/marong-deploy/<날짜>-persona-stage<N>/`에 원래 파일 사본과 `rollback.sh`(파일을 되돌리고 설정을 끄고 다시 시작). 019의 표는 되돌릴 때 지우지 않아요(데이터·백업 지우기는 동희님 말이 있을 때만)
- 하면 안 되는 것: 친구 대화 원문·이름과 묶인 기억·사진을 시험 데이터와 PR에 넣기(지어낸 이름과 대본만), 위기 상태·몸·식단 신호를 동희님 보고·`requests`에 넣기(SPEC-211), 친구 말로 선톡을 동희님 값보다 높게 올리기(줄이기·끄기와 동희님 값까지 되돌리기만 바로, 그 위는 `ask_owner`, SPEC-202), 먼저 전화를 SPEC-277의 정해진 말이 아닌 말로 켜기, 봇 역할(`marong`)에 DELETE 권한 주기(잊기는 `forget_embeddings()` 하나만, D63 ①), 통화 자막을 봇이 읽게 하기(통화 기억은 통화 정리기가 만듦, D63 ②), 0단계 상한(하루 3번·8~22시) 바꾸기, `/opt/marong/prompt.md` 덮어쓰기(지시문 순서를 바꿀 때 3-way 합치기)
- 겹치는 파일: `marong/agent.py`, `marong/proactive.py`, `marong/style.py`, `marong/discord_dm.py`는 0단계와 겹쳐요(0단계를 먼저 합치고 그 위에서). `marong/app_chat.py`, `marong/app_chat_static/chat.js`·`index.html`·`chat.css`, `marong/agent.py`, `tools/report.py`, 통화 서버 지시문(`tools/vertex_live/server.py`, `call_instruction.md`)은 일기 패키지(PR #25)와 겹쳐요. 먼저 합친 쪽에 맞추고, 글 대화 머리 버튼은 전화·알림·일기장·나 순서예요. `tools/vertex_live/organizer.py`는 일기·통화 비용 패키지와 겹쳐요. `docs/07-sitemap/sitemap.yaml`과 `design/base.tokens.json`은 고치지 않아요(설계 스레드가 씀)
- 사람 확인: 단계마다 반영 7일 뒤 숫자(TC-289·348·360·368), 2·3단계 그림자 숫자를 보고 `on` 결정(동희님), 실제 폰 TC-377(동희님, 현경님 폰은 동희님이 부탁)
- 끝 조건: 그 단계 TASK의 끝 조건 시험이 모두 통과하고 지금 시험 전체가 통과(TC-288·378). API를 건드린 작업은 그 operation이 나열한 응답마다 API 시험이 통과. 반영 뒤 5분 로그에 Traceback·ERROR 0, 되돌리기 스크립트가 서버에 있음
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드('마롱 설계를 NEXUS 기준으로 잇기', 마롱이 설계 담당)가 답해요. 문구가 정의에 없으면 지어 넣지 말고 여기에 남겨요

### 시작 전에 정할 것(2차 논의, D63으로 정함)

2026-11-17 15:15:23 KST 결정 카드 '남은 설계 결정 17개를 추천대로 정할까요?'에서 동희님이 '추천대로 모두 정하기'를 골랐어요(D63, [README](README.md#결정)). 아래 '정한 것'이 구현 기준이에요.

| 무엇 | 걸리는 작업 | 정한 것(D63) |
| --- | --- | --- |
| 05 표 8절 1: 잊은 말의 검색 벡터를 함수 `forget_embeddings()`로 지울지, 지우지 않고 모든 검색이 `forget_marks`를 뺄지 | TASK-211, 234 | 함수(벡터가 디스크에 남지 않음). 봇 '지우기 없음' 원칙의 첫 예외 |
| 05 표 8절 2: 통화 기억을 통화 정리기가 만들지, 봇에게 자막 보기를 줄지 | TASK-237 | 통화 정리기(지금 '봇은 자막을 못 읽음' 경계 유지) |
| 05 표 8절 3: `send_text`가 봇의 '보냄'을 몇 초 기다릴지 | TASK-257 | 5초, 넘으면 "지금은 못 보냈어" |
| 명세 6절의 숫자 출발값(첫 질문 문구, 선호 신호 3번·2일, 지침 500자, 규칙 20개, 게이트 기준 5 등)과 [새 제안] 칸 글 | 1~4단계 전체 | 명세대로 시작하고 7일 숫자로 고침 |
| 09 목업 방향(SCR-120~123 A/B) | TASK-226, 240 | 네 화면 모두 A(`design/persona-candidates.md`). SCR-121은 저장 뒤 이해한 내용 카드가 화면 밖이면 그 카드까지 내려 줌 |
| 친구가 스스로 줄인 선톡을 동희님 값까지 되돌리기 | TASK-219 | 바로 되돌림. 동희님 값보다 올리는 것만 `ask_owner`(SPEC-202) |
| 단계 순서 1 → 3 → 2 → 4 | 브랜치 순서 | 이 문서대로 |
| 진짜 모델 시험의 비용 상한(레드팀 7개 × 3번, 기억 시험지) | TC-347, 369~375 | 단계마다 1만 원 안에서 GPT가 돌림. 넘을 것 같을 때만 돌리기 전에 여쭘 |

## 작업 표

- 번호: TASK-211~259(이 패키지 몫 200~259의 나머지). 번호 순서가 구현 순서예요(1 → 3 → 2 → 4단계).
- 담당: 모두 GPT예요. 크기는 사람이 하는 일 기준의 대략값(일)이에요.

### 1단계: 친구 약속·기능 목록·위기 절차·보내기 전 검사(`codex/persona-stage1`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-211 | 마이그레이션 019 적용 순서·역할 권한·유니크 인덱스 확인(2차 논의 결과를 019에 먼저 반영) | 공통 6·11, ERD 3·6절 | `marong/migrations/019_persona.sql`, TBL-115~124·127~134, `tests/test_persona_schema.py`(새) | 없음 | GPT | 0.5 | TC-256 통과 |
| TASK-212 | 친구 약속 저장 모듈: 약속·친구 규칙·맞춤형 지침·선호 신호 읽고 쓰기, 친구 단위 잠금, 같은 요청 id는 결과 하나, 약속 문장 틀(3.9), 다른 친구 것 거절 | SPEC-192·194·198·202, 공통 8·9·11 | `marong/friend_card.py`(새), TBL-115~118 | TASK-211 | GPT | 1 | TC-278 통과, TC-257의 문장 틀 체크 통과 |
| TASK-213 | AI 호출 기록과 도구 호출 기록, 로그 규칙(글 없이 이름·개수·id) | 공통 10, ERD 4절 | `marong/friend_card.py`, TBL-133·134 | TASK-211 | GPT | 0.5 | TC-279 통과 |
| TASK-214 | 고르기 카드 공통(만들기·닫기·`replaced`·`expired`, 친구·종류마다 하나)과 첫 질문 세 개, 24시간 무응답 기본 약속, 채널마다 답 받기(디스코드 단추, 카톡 번호, 칸 글로 답함, 앱 카드) | SPEC-192, FL-124 | `marong/friend_card.py`, `marong/agent.py`, `marong/discord_dm.py`, `marong/kakao.py`, TBL-119 | TASK-212, 213 | GPT | 1.5 | TC-257·258 통과 |
| TASK-215 | 약속 초안(AI-13): 반영 때 한 번 도는 작업, `evidence` 2 미만은 `unknown`, 초안 카드와 맞아·고칠래 | SPEC-193, AI-13, FL-125 | `marong/friend_card.py`, `marong/agent.py`, TBL-115·119·133 | TASK-214 | GPT | 1 | TC-259 통과 |
| TASK-216 | 말로 고치기(모델 도구 `card_update`)·지금 바람 24시간·선호 신호와 바꾸기 제안·힘든 얘기 신호(3.11)와 지지 방식 묻기 | SPEC-195·196·197, FL-126·127·129 | `marong/friend_card.py`, `marong/agent.py`, TBL-115·118·119·134 | TASK-214 | GPT | 1.5 | TC-261·262·263 통과 |
| TASK-217 | 친구 규칙 더하기(말·도구·API)와 맞춤형 지침 적기·이해(AI-14)·지우기 | SPEC-198·199·200, AI-14, FL-126·128 | `marong/friend_card.py`, `marong/agent.py`, TBL-116·117·133 | TASK-212, 213 | GPT | 1.5 | TC-264·265 통과 |
| TASK-218 | 지시문 순서(3.10): 고정 지침 → 친구 약속·친구 규칙 → 맞춤형 지침(1:1만) → 지금 상황, 단체방 규칙, 한 대화 안에서 글이 같음(캐시) | SPEC-194·200·201, FL-136 | `marong/agent.py`(`/opt/marong/prompt.md`는 3-way) | TASK-212, 217 | GPT | 1 | TC-260(글 방 부분)·266·267 통과 |
| TASK-219 | 선톡·먼저 전화 줄이기·끄기(바로), 동희님 값까지 되돌리기는 바로, 그 위로 올리기는 `ask_owner`, 먼저 전화 다시 켜기는 SPEC-277의 정해진 말만 | SPEC-202, FL-126 | `marong/friend_card.py`, `marong/proactive.py`, `marong/discord_dm.py` | TASK-212 | GPT | 0.5 | TC-268 통과 |
| TASK-220 | 기능 목록 한 곳: 글 답·선톡·통화의 도구 정의와 '할 수 있는 일' 줄을 목록에서 만듦, 못 하는 부탁에 대안, 지켜볼 수 없는 부탁 | SPEC-203·204·205, FL-130 | `marong/capabilities.py`(새), `marong/agent.py`, `tools/vertex_live/server.py` | TASK-211 | GPT | 1 | TC-269·270 통과 |
| TASK-221 | 위기 판정(모델 앞, AI-18), 위기 상태, 같은 안전 질문 다시 안 함, 109 한 번, 위기 동안 선톡 멈춤과 돌봄 안부, 동희님 보고에서 빼기 | SPEC-206~209·211, AI-18, FL-131·133 | `marong/safety.py`(새), `marong/agent.py`, `marong/proactive.py`, `tools/report.py`, TBL-120 | TASK-213 | GPT | 2 | TC-271·272·273·275 통과 |
| TASK-222 | 몸·식단 위험 신호(7일 걱정 상태, 도움 받을 곳 한 줄 한 번) | SPEC-210, FL-132 | `marong/safety.py`, TBL-120 | TASK-221 | GPT | 0.5 | TC-274 통과 |
| TASK-223 | 보내기 전 검사 1단계 항목(3.15)과 다시 쓰기(AI-17), 항목별 대체 | SPEC-212, AI-17, FL-133·136·138 | `marong/style.py`, `marong/agent.py`, `marong/proactive.py` | TASK-212, 213 | GPT | 1.5 | TC-276 통과, `tests/test_dm_help.py`의 `style_checks` 그대로 통과 |
| TASK-224 | 통화 지시문 1단계 줄: 친구 약속·친구 규칙·맞춤형 지침·위기 상태('이미 물어봄') | SPEC-194·201·207·242, FL-139·131 | `tools/vertex_live/server.py`, `tools/vertex_live/call_instruction.md` | TASK-218, 221 | GPT | 1 | TC-277·260(통화 부분) 통과, `tools/vertex_live/test_instruction.py` 통과 |
| TASK-225 | 글 대화 API: API-127~133·136과 글 대화 계약 0.4.0의 `Message.card`(API-102·104), 오류 13개 코드, Origin·Access 검사 | API-127~133·136, API-102·104, SPEC-192~200·202 | `marong/app_chat.py`, `tests/test_persona_api.py`(새) | TASK-214, 216, 217 | GPT | 2 | TC-280~284 통과(나열한 응답마다) |
| TASK-226 | 화면: SCR-120 친구 약속, SCR-121 맞춤형 지침, SCR-123 고르기 카드, SCR-107 머리 '나' 버튼(09 결정 방향) | SCR-120·121·123, SCR-107 | `marong/app_chat_static/`(새 `persona/` 페이지, `chat.js`·`index.html`·`chat.css`) | TASK-225 | GPT | 2.5 | TC-285·286·287 통과(360·430px, 밤하늘·군밤 크림) |
| TASK-227 | 1단계 전체 시험·로그 검사·초안 PR(TASK·SPEC ID, 돌린 시험과 결과, 고친 기대값과 이유, 돌리지 못한 것) | SPEC-192~212 | 없음 | TASK-211~226 | GPT | 0.5 | TC-288 통과, PR에 파일별 통과 수 |
| TASK-228 | 1단계 반영: 서버 해시를 `main`과 비교, 백업, 되돌리기 스크립트, 019, 파일, 설정 켜기, 대화·통화가 없을 때 다시 시작, 로그 5분 | SPEC-192~212 | 서버 | TASK-227 | GPT | 0.5 | TC-289의 되돌리기 마른 실행 통과, 5분 로그 오류 0 |
| TASK-229 | 1단계 7일 숫자(명세 5절 표, 숫자만)와 '11단계 진행' 표 | REQ-213~233, 명세 5절 | PR 댓글 | TASK-228 | GPT | 0.25 | TC-289의 숫자가 PR 댓글에 있음 |

### 3단계: 친구 기억(`codex/persona-stage3`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-230 | 정리 작업 예약(친구 말 60초 멎음, 통화 끝남)·임대 10분·다시 예약, 기억 정리 그래프 뼈대(`memory:` 스레드, 상태엔 id만) | SPEC-224, FL-134 | `marong/graphs/memory.py`(새), `marong/agent.py`, TBL-127 | TASK-229 | GPT | 1.5 | TC-330 통과 |
| TASK-231 | 기억 연산 뽑기(AI-16)와 코드 확인 1~7(모양·인용·근거·범위·작업 토큰), 출처 칸 | SPEC-225·227, AI-16 | `marong/graphs/memory.py`, `marong/friend_memory.py`(새), TBL-123·124·127·133 | TASK-230 | GPT | 2 | TC-331·333 통과 |
| TASK-232 | 바뀐 값은 대체, 열린 고리 열기·닫기·만료 | SPEC-226·228 | `marong/friend_memory.py`, TBL-123·124 | TASK-231 | GPT | 1 | TC-332·334 통과 |
| TASK-233 | 민감 기억 허락 카드(`memory_ok`, 무응답 24시간 뒤 1:1로만 기억) | SPEC-231, FL-134 | `marong/friend_memory.py`, `marong/friend_card.py`, TBL-119·123 | TASK-231 | GPT | 1 | TC-338 통과 |
| TASK-234 | 잊기 줄기(3.20): 항목·고리·임베딩·원문 '잊음'·요약과 메모 숨김 뒤 다시 쓰기(AI-19), 요청 키 하나 결과, 모델 도구 `memory_forget` | SPEC-230, AI-19, FL-135 | `marong/friend_memory.py`, `marong/memory.py`, `marong/agent.py`, TBL-123·124·128·129, `forget_embeddings()` | TASK-232 | GPT | 2.5 | TC-336·337 통과 |
| TASK-235 | 무엇을 기억하는지 답하기(모델 도구 `memory_list`, 날짜·채널과 함께) | SPEC-229, FL-135 | `marong/friend_memory.py`, `marong/agent.py`, TBL-134 | TASK-232 | GPT | 0.5 | TC-335 통과 |
| TASK-236 | 지시문에 고정 요약(고정 지침 뒤)과 찾은 기억(이번 턴만, DB 메시지에 안 남김), 여럿이 있는 방의 기억 범위 | SPEC-232·233, FL-136 | `marong/agent.py`, `marong/friend_memory.py` | TASK-232, 234 | GPT | 1.5 | TC-339·340 통과 |
| TASK-237 | 통화 정리도 친구 기억으로(2차 논의 결과대로, 추천은 통화 정리기가 만듦) | SPEC-235, FL-134 | `tools/vertex_live/organizer.py`, `marong/friend_memory.py`(통화 서버 사본) | TASK-231 | GPT | 1.5 | TC-341 통과, `tools/vertex_live/test_organizer_reconnect.py` 통과 |
| TASK-238 | 통화 지시문 잊기 줄과 `recall`이 친구 기억을 찾음 | SPEC-242, FL-139 | `tools/vertex_live/server.py`, `tools/vertex_live/memory_tools.py`, `call_instruction.md` | TASK-234, 237 | GPT | 1 | TC-342 통과, `tools/vertex_live/test_memory_bridge.py` 통과 |
| TASK-239 | API-134·135와 API-136의 `memory_ok` 종류 | API-134·135·136, SPEC-230·231·234 | `marong/app_chat.py`, `tests/test_persona_api.py` | TASK-233, 234 | GPT | 1 | TC-343·344·345 통과(나열한 응답마다) |
| TASK-240 | 화면 SCR-122 마롱이가 기억하는 나(09 결정 방향)와 SCR-120의 줄 | SCR-122, SPEC-234 | `marong/app_chat_static/persona/` | TASK-239 | GPT | 1.5 | TC-346 통과 |
| TASK-241 | 그림자 모드 비교와 한국어 기억 시험지(지어낸 대본) | REQ-242·259, SPEC-224~235 | `tests/memory_eval/`(새, 대본만) | TASK-236 | GPT | 1 | TC-347 통과(진짜 모델 부분은 동희님이 비용을 정한 뒤) |
| TASK-242 | 3단계 전체 시험·초안 PR | SPEC-224~235·242 | 없음 | TASK-230~241 | GPT | 0.5 | TC-378 통과(3단계 줄) |
| TASK-243 | 3단계 반영(`shadow`), 숫자를 보고 동희님이 `on`, 7일 숫자 | SPEC-224~235·242 | 서버, PR 댓글 | TASK-242 | GPT | 0.5 | TC-348 통과 |

### 2단계: 선톡 게이트(`codex/persona-stage2`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-244 | 선톡 후보 모으기(열린 고리·돌봄 안부·일정·관심사·그림 화두·일상)와 민감 기억 빼기 | SPEC-213·217, FL-133 | `marong/graphs/proactive.py`(새), `marong/friend_memory.py` | TASK-243 | GPT | 1.5 | TC-349·350 통과 |
| TASK-245 | 게이트 점수와 안 보냄, 기억형 하루 1번, 같은 일 한 번 | SPEC-214·215·216 | `marong/graphs/proactive.py`, TBL-121 | TASK-244 | GPT | 1 | TC-351·352 통과 |
| TASK-246 | 게이트 선톡 쓰기(AI-15), 잠금 화면 등급과 꺼낼 얘기(24시간) | SPEC-218, AI-15 | `marong/graphs/proactive.py`, `marong/agent.py`, TBL-121·122·133 | TASK-245 | GPT | 1.5 | TC-353·354 통과 |
| TASK-247 | 선톡 결과 기록과 2·24시간 안 답 여부 | SPEC-219 | `marong/graphs/proactive.py`, `marong/agent.py`, TBL-121 | TASK-245 | GPT | 0.5 | TC-355 통과 |
| TASK-248 | 기운 단계 계산(3.11)과 피곤·작별한 날 선톡 멈춤 | SPEC-220, FL-129 | `marong/friend_card.py`, `marong/graphs/proactive.py` | TASK-245 | GPT | 0.5 | TC-356 통과 |
| TASK-249 | 선톡 그래프 실행(1분 확인, 0단계 칸 잡기 위), 다시 시작해도 한 번만 보냄, 그림자 모드, 백오프와 그림 화두 간격 하나로 | SPEC-221·222·223 | `marong/graphs/proactive.py`, `marong/proactive.py`, `marong/discord_dm.py` | TASK-246, 247, 248 | GPT | 2 | TC-357·358·359 통과 |
| TASK-250 | 2단계 전체 시험·초안 PR | SPEC-213~223 | 없음 | TASK-244~249 | GPT | 0.5 | TC-378 통과(2단계 줄) |
| TASK-251 | 2단계 반영(`shadow` 3일), 그림자 숫자를 PR 댓글로 | SPEC-221 | 서버, PR 댓글 | TASK-250 | GPT | 0.5 | TC-357의 서버 부분 통과, 되돌리기 마른 실행 통과 |
| TASK-252 | 동희님이 `on`을 정하면 켜고 7일 숫자 | REQ-234~242, 명세 5절 | 서버, PR 댓글 | TASK-251 | GPT | 0.25 | TC-360 통과 |

### 4단계: 이야기 끌어내기·남은 부탁·통화(`codex/persona-stage4`)

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-253 | 기운 단계에 맞춘 답(짧게, 열린 질문 없이, 고르기 쉬운 말) | SPEC-236, FL-129 | `marong/agent.py`, `marong/style.py` | TASK-252 | GPT | 0.5 | TC-361 통과 |
| TASK-254 | 대화 턴 그래프(`talk:` 스레드): 위기 판정 → 지시문 → 모델(도구) → 검사 → 보내기 → 이벤트, 부탁 확인에서 `interrupt`와 다른 채널에서 이어 가기, 그래프 오류 때 지금 경로, 밤 전화 확인 카드(`call_confirm`) | SPEC-241, FL-136·138 | `marong/graphs/talk.py`(새), `marong/agent.py` | TASK-253 | GPT | 3 | TC-366 통과 |
| TASK-255 | 조건 연락(모델 도구 `watch_add`·`watch_fire`, 기한·만료, 친구마다 3개) | SPEC-237, FL-137 | `marong/favors.py`(새), `marong/agent.py`, TBL-130·134 | TASK-254 | GPT | 1.5 | TC-362 통과 |
| TASK-256 | 전하기(`relay_add`·`relay_reply`, 전하기 확인 카드, 하루 3개, 받은 친구가 '전해 줘'라고 할 때만 답이 감) | SPEC-238, FL-138 | `marong/favors.py`, `marong/agent.py`, TBL-119·131·134 | TASK-254 | GPT | 1.5 | TC-363·367 통과 |
| TASK-257 | 통화에서 글로 보내기(`send_text`, 통화 서버가 줄을 넣고 봇이 D18 경로로 보냄, 기다리는 시간은 2차 논의 결과) | SPEC-239, FL-139 | `tools/vertex_live/server.py`, `marong/favors.py`, TBL-132 | TASK-254 | GPT | 1 | TC-364 통과 |
| TASK-258 | 통화 화제 목록(열린 고리·마롱이 일상·양자택일)과 대화 이끌기 줄 | SPEC-240, FL-139 | `tools/vertex_live/server.py`, `call_instruction.md` | TASK-254 | GPT | 0.5 | TC-365 통과 |
| TASK-259 | 4단계 전체 시험·초안 PR·반영·7일 숫자 | SPEC-236~241 | 서버, PR 댓글 | TASK-253~258 | GPT | 1 | TC-378(4단계 줄)·368 통과 |

## 11단계 진행

GPT가 TASK마다 채워요.

| 작업 | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-211 | 시험 통과 | `2c9e6c2` | 2026-11-17 격리 pgserver PostgreSQL. 018까지와 통화 스키마 적용 후 019 두 번 실행, 18개 표 권한 144개, 열린 카드 유니크, 지정 벡터만 제거 확인(TC-256). |
| TASK-212 | 구현·부분 검증 | `8a51c72`, `4869b59` | 저장·친구 잠금·발화자·인용·재호출 검사. 지지·조언·솔직함 54가지 문장 조합 확인. |
| TASK-213 | 구현·부분 검증 | `4869b59`, `238620e` | 지침·위기 판정·다시 쓰기 호출과 도구 결과의 숫자 기록. 실제 공급자 사용량·비용 기록 대조는 남음. |
| TASK-214 | 구현·부분 검증 | `8a51c72`, `4869b59` | 카톡 번호·칸 글, 앱 API·카드, 디스코드 단추 처리. 24시간 기본값과 전달 성공 뒤 안내 기록. 실제 채널 단추 전체 경로 추가 확인 필요. |
| TASK-215 | 구현·부분 검증 | `6793024` | 요약·메모만 읽는 초안 도구, 근거 2 미만 기본값, 초안 답과 재호출. 전송 오류 한 번 재시도·잘못된 응답 재시도 없음 확인. 실제 일회 작업 대기. |
| TASK-216 | 구현·부분 검증 | `4869b59`, `6793024` | 지금 바람 24시간, 지지 방식 말 답, 날짜별 신호·제안 하나·동시 선택·받아들임·신호 닫기. 피곤·밤·짧은 답에서 미루기 확인. 제안 거절·만료 전체 경우 추가 검증 필요. |
| TASK-217 | 구현·부분 검증 | `4869b59`, `d713e57` | 규칙과 지침 API·말 명령·지우기, 꼭 지킬 것 옮기기·정확한 인용 검사. 다른 친구 지침 저장 거부와 맞춤형 지침의 기능 변경 거절을 확인. |
| TASK-218 | 구현·부분 검증 | `8a51c72`, `238620e` | 1:1 지침과 규칙, 단체방 규칙, 지침 30분 캐시와 지움 즉시 반영을 가짜 자료로 확인. 서버 지시문 3-way는 반영 단계. |
| TASK-219 | 구현·부분 검증 | `d713e57` | 선톡 줄이기·끄기·관리자 값까지 복구, 먼저 전화 끄기. 디스코드 정해진 말도 친구 약속에 연결. 실제 여러 입구 확인 대기. |
| TASK-220 | 구현·부분 검증 | `8a51c72` | 기능 목록에서 글·통화 안내 생성. 기능 요청은 등록된 꺼진 기능과 원문 인용 확인 뒤 요청 종류와 기능만 저장. |
| TASK-221 | 구현·부분 검증 | `4869b59`, `238620e` | 최근 30분 같은 친구·방만 판정, 상태 공유·109 한 번·선톡 중단·다음 날 돌봄 안부·실패 복구·평소 대화 뒤 닫기. 보고 제외와 실제 모델 추가 검증 필요. |
| TASK-222 | 구현·부분 검증 | `4869b59` | 몸·식단 신호와 7일 상태, 도움 줄 한 번·만료 확인. 신호 목록 전체와 실제 모델 시험 대기. |
| TASK-223 | 구현·부분 검증 | `238620e` | 답·선톡 검사, 다시 쓰기 한 번·8초 기한·날짜 보존·항목별 대체. 7초 남으면 재호출 없음, 선톡 대체는 보내지 않음. |
| TASK-224 | 구현·가짜 통화 시험 | `6bc44c4` | 통화 역할 권한으로 약속·규칙·지침 조회, 완료 자막만 상태 반영, 재접속 때 이미 한 질문·109 안내 중복 방지. 실제 통화 알림 탐침 대기. |
| TASK-225 | 구현·부분 검증 | `d713e57` | 8개 API 작업의 401·403·503·500, 쓰기 Origin 거절, 카드·지침·규칙 입력과 한도 시험. 모든 계약 예시 모양과 카드 종류 전체 검증은 남음. |
| TASK-226 | 구현·부분 검증 | `78a3b11` | Chromium 360·430px·두 테마에서 약속 상태 4개, 카드 재시도·권한·입력 보존·다른 기기 변경·5초 읽기 복구 확인. 글 대화 21개 통과. 전체 화면 상태 대조는 남음. |
| TASK-227 | 회귀 통과·종합 검증 대기 | `6bc44c4`, `78a3b11` | Python 전체 45개 파일 독립 실행 통과. Windows Chromium 글 대화 21개·통화 미디어 6개 통과. 실제 모델·모든 계약 조합과 설계 질문은 각 TASK·TC에 남김. |
| TASK-228 | 대기 | — | TASK-227 종합 검증과 선행 병합 대기. 운영 성향 설정과 DB는 바꾸지 않음. |
| TASK-229 | 대기 | — | 1단계 반영 뒤 7일 집계. 0단계 TC-254 예약은 기존 PR #31 일정. |
| TASK-230 | 구현·격리 시험 | 1558c67 | TC-330. 글 60초 대기, 임대 회수와 중복 방지, 글 봇의 작업자 시작, PostgreSQL 체크포인트에서 ID만 확인. |
| TASK-231 | 구현·가짜 모델 검증 | 1435464 | TC-331·333. 발화자·인용·방·작업 토큰과 출처 검증. 설정 모델, 연결 오류 재시도와 TBL-133 토큰·결과 기록 확인. 실제 모델 대기. |
| TASK-232 | 작업 브랜치 가짜 모델 검증 | 3915fad | TC-332·334. 같은 방의 기억 대체, 열린 고리 중복·한국 시각 만료 확인. |
| TASK-233 | 시작 전 | | |
| TASK-234 | 저장 트랜잭션·텍스트 조회 검증 | 53da78e·d2ede83·15c97da | 같은 근거의 항목·고리·벡터 제거, 원문 표시, 재색인 차단과 중복 처리. 요약·메모 숨김과 재작성 10분 간격, 세 번 실패 후 숨김·비움. 통화 원문과 여러 친구의 요약은 가짜 모델에도 보내지 않음. 실제 모델·체크포인트·API와 다른 소비처는 대기. |
| TASK-235 | 격리 시험 | 2fe9cae | TC-335. 본인 출처 확인, 방 단위 조회, 단체방에서 인용 제외와 숫자 감사 기록. |
| TASK-236 | 시작 전 | | |
| TASK-237 | 구현·가짜 모델 검증 | 1435464 | TC-341. 통화 정리기 실패 뒤에도 자막이 있으면 별도 작업으로 열린 고리 저장. 봇 역할은 통화 자막 SELECT 거절. 실제 모델과 운영 반영 대기. |
| TASK-238 | 시작 전 | | |
| TASK-239 | 일부 구현·격리 시험 | 8349fa0 | API-134와 TC-343을 확인. API-135와 API-136의 기억 허락은 TASK-233·234 뒤. |
| TASK-240 | 시작 전 | | |
| TASK-241 | 시작 전 | | |
| TASK-242 | 시작 전 | | |
| TASK-243 | 시작 전 | | |
| TASK-244 | 시작 전 | | |
| TASK-245 | 시작 전 | | |
| TASK-246 | 시작 전 | | |
| TASK-247 | 시작 전 | | |
| TASK-248 | 시작 전 | | |
| TASK-249 | 시작 전 | | |
| TASK-250 | 시작 전 | | |
| TASK-251 | 시작 전 | | |
| TASK-252 | 시작 전 | | |
| TASK-253 | 시작 전 | | |
| TASK-254 | 시작 전 | | |
| TASK-255 | 시작 전 | | |
| TASK-256 | 시작 전 | | |
| TASK-257 | 시작 전 | | |
| TASK-258 | 시작 전 | | |
| TASK-259 | 시작 전 | | |

## 검사

- SPEC-192~242의 모든 행(Must와 Should)에 작업이 있어요.
- 작업마다 담당 한 명(GPT)과 남이 돌려 볼 수 있는 끝 조건(TC ID)이 있어요.
- API를 건드리는 작업(TASK-225·239, 카드 종류를 더하는 TASK-233·254·256)은 그 operation이 나열한 응답마다 시험이 있어야 끝이에요(TC-280~284·343~345·367).
- 의존 관계에 되돌아오는 고리가 없어요. 모든 작업이 번호가 더 작은 작업에만 기대요.
- 숫자는 아래 명령 출력에서 옮겼어요(2026-11-17 KST): SPEC 행 51개 모두 작업 있음, 작업 49개, 고리 0.
