# 대화 이어 주기 작업 목록(10단계 WBS)

## GPT 인계

2026-11-24 작성(Claude, 초안). **아직 시작하지 않아요.** 체크포인트 질문 1\~8([01 도메인 8절](../01-domain/continuity.md#8-체크포인트-질문))과 바뀌는 승인 항목 C-1\~C-8([7절](../01-domain/continuity.md#7-바뀌는-승인-항목항목마다-따로-여쭤요))에 동희님 답이 오고, 이 설계 PR이 `main`에 합쳐지면 [README 작업 패키지 표](README.md#작업-패키지)에서 '시작 가능'으로 바꿔요. 구현·반영은 GPT, 설계와 기록은 Claude예요([AGENTS.md](../../AGENTS.md)).

- 목표: 통화를 다시 걸거나 글 대화 뒤 통화하면 마롱이가 방금 하던 얘기를 이어 가고, 통화 뒤 글에서도 방금 통화를 알아요. 지난 자료에는 말한 사람과 '어제 오후 9시' 같은 때가 붙어요. 원문은 [02 요구사항 출처 표기](../02-prd/continuity.md#출처-표기)의 원문1\~3이에요.
- 시작: 이 설계가 합쳐진 `main` 머리에서 새 브랜치 `codex/continuity`. TASK-520(실제 모델 확인)만 먼저 `codex/continuity-spike`로 따로 해도 돼요.
- 읽을 것: 이 문서 밖은 아래 파일과 ID만 읽어요.
  - 명세: [04 기능 명세](../04-functional-spec/continuity.md)의 SPEC-480\~488, 3절(무엇을 얼마나, 넣는 방법, 시각 표기, 글 블록, 카드, 프라이버시, 비용, 받아들임 조건, 기억 시험 대본), 4절(AI 호출 바뀜).
  - 흐름: [FL-210](../03-user-flow/FL-210-continue-conversation-call.md), [FL-211](../03-user-flow/FL-211-call-to-text.md).
  - 시험: [12 시험 계획](../12-qa/continuity.md)의 TC-670\~686.
  - 지금 승인 명세 중 닿는 곳: [spec.md](../04-functional-spec/spec.md)의 SPEC-004·017·024와 3.1, [call-cost.md](../04-functional-spec/call-cost.md)의 SPEC-182. 체크포인트에서 바뀐 문장은 Claude가 TASK-533에서 고쳐 두어요.
- 이미 된 것: 코드는 아무것도 바꾸지 않았어요. 표·API·화면 바뀜이 없어서 마이그레이션도 없어요. 단가와 줄 번호는 `main` `a39fef4`에서 읽었어요.
- 순서:
  1. TASK-520(실제 모델 확인). 결과에 따라 SPEC-481을 B(초기 대화 기록) 그대로 하거나 A(지시문 글)로 내려가요. A로 내려가면 PR '설계 질문'에 적고 Claude 답을 기다리지 않고 A로 이어가요(SPEC-481 예외에 이미 있는 방법)
  2. TASK-521과 TASK-528(같이 해도 됨)
  3. TASK-522
  4. TASK-523, TASK-524, TASK-526(같이 해도 됨)
  5. TASK-525(질문 4·5의 답에 따라), TASK-527(질문 3의 답에 따라)
  6. TASK-529
  7. TASK-530
  8. TASK-531(서버 반영: `off` → `shadow` → `on`)
  9. TASK-532
- 시험 환경: AGENTS.md와 같아요(Python 3.12, `pgserver`). Gemini Live·Anthropic·정리 모델은 가짜예요.
  - 진짜 모델은 TASK-520(Vertex Gemini Live, 연결 20번 이하, 한 번 1분 이하)과 TASK-530(기억 시험, 질문 7의 답 한도 안, 추천 60분·3달러)에서만 불러요. 소리는 지어낸 문장으로 만든 소리만 써요.
  - 운영 DB를 읽지 않아요. 기억 시험은 합성 자료만 써요(REQ-200).
- 반영:
  - 표 바뀜이 없어서 마이그레이션은 없어요.
  - 설정 `MARONG_CONTINUITY`(`off`·`shadow`·`on`)를 systemd drop-in `Environment=`로 넣어요. 같은 이름이 `/etc/marong-discord/config`에 있으면 그쪽이 이겨요.
  - 바뀌는 서비스: 통화 서버 사용자 유닛 `marong-vertex-live`(작업 폴더 `~/marong-deploy/20261119-unified-cutover.*/voice-runtime/tools/vertex_live`, [call-connect.md](call-connect.md#gpt-인계)와 같음), 정리기 사용자 유닛 `marong-voice-memory`, 글 대화 `marong-app`과 `marong-discord`(카카오 `marong`이 돌고 있으면 그것도). 반영 전 각 작업 폴더 해시를 `main`과 비교해요.
  - 순서: 파일 백업 → 파일 → 대화·통화가 없을 때 재시작(`off`) → 로그 5분 → `shadow` 하루 → 기록 확인 → `on`. 되돌리기는 `MARONG_CONTINUITY=off`로 바로, 파일 되돌리기 스크립트는 서버 `~/marong-deploy/<날짜>-continuity/`에 먼저 두고 경로를 PR에 적어요.
  - 통화 서버에 `MARONG_FRIENDS=1`을 켜는 것은 질문 4의 답이 '이름·관계만, 켬'일 때만이에요.
- 하면 안 되는 것:
  - 다시 잇기 핸들을 DB에 저장하지 않아요(고르지 않은 안 C, [04 3.7](../04-functional-spec/continuity.md#37-고르지-않은-안)).
  - 직전 대화를 고를 때 따로 모델을 부르지 않아요(안 E).
  - 로그·진단·PR에 대화 글, 친구 이름, 이메일을 넣지 않아요. 개수·글자 수·ms·결과 이름만이에요.
  - 다른 친구·단체방·디스코드 서버 채널의 말을 직전 대화에 넣지 않아요.
  - 통화 압축 설정(8,192 → 4,096)과 다시 잇기 유효 시간(600초)을 바꾸지 않아요. 바꿔야 하면 '설계 질문'에 적어요.
  - `/opt/marong/prompt.md`를 덮어쓰지 않아요(이 패키지는 글 대화 지시문을 바꾸지 않아요. '# 방금 통화'는 `# 지금 상황` 블록 안이에요).
- 겹치는 파일:
  - `tools/vertex_live/call_memory.py`, `tools/vertex_live/organizer.py`, `tools/vertex_live/live_session.py`: 같은 때 다른 Claude 작업이 SPEC-004 시각·SPEC-017 짧은 통화 고장을 고치고 있어요(2026-11-24). 먼저 합쳐진 쪽 뒤에 맞춰요.
  - `tools/vertex_live/server.py`: 통화 연결 고치기(BUG-108\~111)는 합쳐졌어요. 그 뒤 연결 순서(`connect_timing`)를 지켜요.
  - `marong/store.py`, `marong/agent.py`: 2026-11-24 현재 이 둘을 고치는 열린 PR은 없어요(PR #117은 관리 화면).
- 사람 확인: TC-682(말한 사람·때를 사람이 들어 봄), TC-686(실제 폰에서 끊었다 다시 걸기). 현경님 폰은 동희님이 부탁해요.
- 끝 조건:
  - 모든 TASK의 끝 조건 시험이 통과해요.
  - `off`에서 지금 시험이 그대로 통과해요: `tools/vertex_live/test_*.py`, `tests/test_*.py` 가운데 `call_context`·통화 기억을 쓰는 것.
  - [04 3.9 받아들임 조건](../04-functional-spec/continuity.md#39-받아들임-조건)의 숫자를 '11단계 진행'에 적어요.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

- 번호: TASK-520\~533. 이 패키지 범위는 TASK-520\~539예요([README](README.md#id-범위)).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-520 | 실제 모델 확인: Vertex `gemini-3.8-live`에 `historyConfig.initialHistoryInClientContent`가 받아지는지, 같은 역할 턴이 이어져도 되는지, 기록 뒤 인사 신호로 첫마디가 나오는지, 첫마디가 방금 얘기를 잇는지, 첫 소리 ms, 턴마다 `usageMetadata.promptTokenCount`(맥락을 턴마다 다시 세는지), 압축이 걸리는 때. 합성 기록 6턴·20턴 두 가지 | SPEC-481, REQ-608, 01 도메인 5.4 | `tools/vertex_live/`의 시험 스크립트 하나(새 파일, 반영하지 않음) | 없음 | GPT | 0.5 | 결과 표(항목마다 됨·안 됨·값)가 '11단계 진행'에 있음. 안 되면 A로 내려간다고 PR '설계 질문'에 적음 |
| TASK-521 | 상대 시각 표기 함수 `marong/relative_time.py`(3.3의 표, 한국 자정, '밤 12시'·'낮 12시', 미래 시각은 '방금') | SPEC-484 | 새 파일 | 없음 | GPT | 0.25 | TC-670 통과 |
| TASK-522 | 직전 대화 고르기 `marong/continuity.py`: 글(`marong.messages`)과 끝난 통화 자막(`call.transcript_report`)을 지금 seed 범위·숨김·뺀 자료·잊기 조건으로 읽어 한 시간 줄로, 30분 빈틈으로 대화 나누기, 방금 대화 20턴·2,000자·한 턴 300자, 한 줄 대화 3개·1,500자, `unanswered`, 신호 글 빼기, 1초 상한 | SPEC-480 | 새 파일, 통화 서버와 앱 서버가 함께 import | TASK-521 | GPT | 1 | TC-671·672 통과(`pgserver`, 지어낸 대화) |
| TASK-523 | 통화 서버 넣기: 첫 구간에서 고른 기록을 통화 메모리에 두기, setup에 `historyConfig`, `setupComplete` 뒤 `clientContent`(여는·바뀌는 곳·닫는 `[알림]` 턴, `turnComplete: true`) → 인사 신호, 핸들 없이 다시 여는 구간에 같은 기록, `setup_rejected` 때 한 번 `historyConfig` 없이 다시 열고 `previous_conversation` 글로 | SPEC-481 | `server.py`, `live_session.py` | TASK-520, TASK-522 | GPT | 1 | TC-673·683·684 통과(`off` 스냅숏이 지금과 글자까지 같음은 TC-673) |
| TASK-524 | 통화 기억 블록 모양: 항목마다 `when`, 턴에 `who`, `kakao_recent` → `recent_conversations`, 초기 대화 기록으로 보낸 턴 빼기, 앞 안내 글의 '통화 시작 시각' 줄 | SPEC-482 | `call_memory.py`의 `seed`, `server.py`의 seed 앞 글 | TASK-521, TASK-522 | GPT | 0.5 | TC-677 통과, `off`면 seed JSON이 지금과 같음(TC-673) |
| TASK-525 | 통화 지시문 '먼저 꺼내지 않기' 줄, 친구 목록 이름·관계만(지금 계정과 통합 계정 둘 다), 통화 서버 `MARONG_FRIENDS=1` 준비 | SPEC-485 | `call_instruction.md`, `call_memory.py`의 친구 읽기 | TASK-524 | GPT | 0.25 | TC-680의 가짜 모델 부분 통과. 질문 4·5의 답이 다르면 그 답대로 하고 PR에 적음 |
| TASK-526 | 글 대화 '# 방금 통화': `call_context`와 같은 트랜잭션에서 30분 안 끝난 통화의 마지막 20턴, `# 지금 상황`의 '# 최근 통화' 앞, 카드·기억 항목에 때, `kakao_guards` 그대로 | SPEC-483 | `marong/store.py`의 `call_context`, `marong/agent.py`의 '# 최근 통화' | TASK-521, TASK-522 | GPT | 0.5 | TC-676 통과, 지금 글 대화 시험 통과 |
| TASK-527 | 통화 카드 근거 확인: 정리 호출에 줄 id, SPEC-017 모양과 항목마다 `turn_ids`, 서버 근거 확인, 요약 실패 때 지금 방식, `tools/vertex_live/README.md:37` 문장 고침 | SPEC-486 | `organizer.py`, `tools/vertex_live/README.md` | 없음 | GPT | 0.75 | TC-679 통과. 질문 3에서 '인용만'이면 이 TASK는 `removed` |
| TASK-528 | 켜고 끄기와 기록: `MARONG_CONTINUITY` 읽기(연결·답·정리마다), 모르는 값은 `off`, 진단 `d['continuity']`와 로그 `continuity_pick`(개수·ms·결과만) | SPEC-487 | `server.py`, `live_session.py`, `marong/continuity.py`, `organizer.py`, `marong/store.py` | 없음 | GPT | 0.25 | TC-681 통과 |
| TASK-529 | 기억 시험 대본 둘: `--script previous|date`, `--mode on|off`, 합성 소리 `bench/previous.json`·`bench/date.json`, 가짜 시계, 맞힘 비율·첫 턴 토큰·첫 소리 ms·1분당 비용 보고 | SPEC-488 | `memory_bench.py`, `bench/` | TASK-523, TASK-524 | GPT | 0.75 | TC-685 통과(가짜 연결로 맞힘 100%·0%, `off`면 기록 없음) |
| TASK-530 | 실제 모델 측정: 기억 시험 `previous`·`date`를 `on`·`off` 각 5번, 첫 소리·토큰은 10번씩. 3.9 표의 숫자를 셈. 비용이 1.10배를 넘으면 10턴·1,000자로 줄여 다시 | REQ-608, REQ-609, SPEC-488 | 없음(측정) | TASK-529 | GPT | 0.5 | TC-674·675·678·680의 실제 모델 부분을 돌려 3.9 표의 일곱 줄 값과 쓴 비용이 '11단계 진행'에 있음. 조건을 못 넘으면 반영하지 않고 PR '설계 질문'에 적음 |
| TASK-531 | 서버 반영: 해시 비교, 파일 백업, 파일, 대화·통화가 없을 때 네 서비스 재시작(`off`), 로그 5분, `shadow` 하루(`continuity_pick` 개수 확인), `on`, 확인 통화 두 번(끊었다 30분 안에 다시 걸기), 되돌리기 스크립트 | SPEC-480\~487 | 서버 | TASK-530 | GPT | 0.5 | 로그 오류 0, `shadow` 하루 기록의 결과별 개수, `on` 뒤 확인 통화 진단에 `continuity.result='ok'`, 되돌리기 경로가 PR에 있음 |
| TASK-532 | PR 설명과 '11단계 진행' 표 | SPEC-480\~488 | 없음 | TASK-520\~531 | GPT | 0.25 | TASK마다 상태·커밋·확인한 것이 있음 |
| TASK-533 | 설계 쪽 마무리: 체크포인트 답대로 승인 문서 고치기(spec.md SPEC-004·017·024와 3.1, requirements.md REQ-022, unified.md SPEC-382, call-cost.md SPEC-182), 단계 기록, README 표 '시작 가능' | C-1\~C-8 | `docs/` | 체크포인트 답 | Claude | 0.25 | 바뀐 승인 문장마다 답한 말과 자리가 적혀 있음 |

## 11단계 진행

각 TASK의 구현, 검사, 배포 상태를 기록해요.

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-520 | 시작 전 | | |
| TASK-521 | 시작 전 | | |
| TASK-522 | 시작 전 | | |
| TASK-523 | 시작 전 | | |
| TASK-524 | 시작 전 | | |
| TASK-525 | 시작 전 | | |
| TASK-526 | 시작 전 | | |
| TASK-527 | 시작 전 | | |
| TASK-528 | 시작 전 | | |
| TASK-529 | 시작 전 | | |
| TASK-530 | 시작 전 | | |
| TASK-531 | 시작 전 | | |
| TASK-532 | 시작 전 | | |
| TASK-533 | 시작 전 | | |
