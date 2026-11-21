# 통화 연결 속도와 무음 고치기 작업 목록(10단계 WBS, BUG-108~111)

## GPT 인계

2026-11-21 16시대 KST 작성, 16:5x KST에 앱 0.3.1(스피커·통화 볼륨, TASK-472\~474)을 맨 앞에 더함(Claude, corthex 0.12.x). 구현·반영·앱 서명은 GPT, 설계와 기록은 Claude예요([AGENTS.md](../../AGENTS.md)).

- 목표: 앱 통화에서 마롱이 목소리가 이어폰 없이도 스피커로 크게 들리게 하고(가장 급함), 벨을 받은 뒤 첫 목소리까지 빨리, 목소리가 꼭 들리게 해요. 동희님 원문은 [12 QA 출처 표기](../12-qa/call-connect.md#출처-표기)의 원문1·원문3·원문4·원문5예요.
- 시작: 이 설계가 합쳐진 `main` 머리에서 새 브랜치 세 개를 만들어요.
  - `codex/call-audio-speaker`: TASK-472\~474, 앱 0.3.1(versionCode 9). 가장 먼저, 다른 브랜치를 기다리지 않아요.
  - `codex/call-connect-web`: TASK-460\~466, 통화 서버와 화면.
  - `codex/call-connect-app`: TASK-467\~468, 앱 0.3.2(versionCode 10). `codex/call-connect-web`과 0.3.1이 합쳐진 뒤 시작해요.
- 읽을 것: 이 문서 밖은 아래 파일과 ID만 읽어요.
  - 고장: [12 QA](../12-qa/call-connect.md)의 BUG-108\~111과 TC-570\~595.
  - 명세: [기능 명세](../04-functional-spec/call-connect.md)의 SPEC-400\~405와 3절(시각 기록 칸, 정적 파일 목록, 재생 진단 칸, 출력 장치, 고르지 않은 안).
  - 표: [통화 마이그레이션 010_call_connect.sql](../../marong/call/migrations/010_call_connect.sql)(TBL-004의 새 칸, `call.transport_events.reason`의 `rtc_silent`).
  - 계약: [call-live.openapi.yaml](../../api/call-live.openapi.yaml) 0.2.0-draft. API-107의 `hold`와 새 메시지 `LiveTiming`·`LiveAudioReady`·`LivePlayback`, API-246(정적 파일).
  - 화면 상태: [08-screens/call-connect.md](../08-screens/call-connect.md). 새 문구는 없어요.
- 이미 된 것:
  - 마이그레이션 010은 Claude가 임시 Postgres(pgserver)에서 통합 앱(020·통화 008)과 사용 한도(021·통화 009) 마이그레이션 뒤에 두 번 적용했어요. 확인 11개가 통과했어요. 운영 DB에는 넣지 않았어요.
  - 코드는 아직 아무것도 바꾸지 않았어요.
- 순서:
  1. TASK-472(앱 0.3.1 스피커·통화 볼륨)
  2. TASK-473(앱 0.3.1 서명·게시). 여기까지 끝나면 동희님께 업데이트를 받으라고 알려요(Claude가 함)
  3. TASK-474(실제 폰 기록)
  4. TASK-460
  5. TASK-461과 TASK-462(같이 해도 됨)
  6. TASK-463
  7. TASK-464와 TASK-465(같이 해도 됨)
  8. TASK-466(서버 반영)
  9. TASK-467
  10. TASK-468(앱 0.3.2 게시)
  11. TASK-469(실제 폰)
  12. TASK-470
- 시험 환경: AGENTS.md와 같아요(Python 3.12, `pgserver`, Node, Java 21). Gemini·LiveKit·FCM은 가짜예요.
  - 진짜 모델은 TASK-466 반영 뒤 확인 통화 두 번까지만 불러요. 웹 화면에서 가짜 마이크 소리로 걸고, 한 번에 1분 이하예요. 그 밖의 유료 API는 부르지 않아요.
- 반영:
  - 1차(TASK-466)는 통화 서버만이에요.
    - 실제로 도는 코드는 사용자 유닛 `marong-vertex-live`의 작업 폴더(`~/marong-deploy/20261119-unified-cutover.*/voice-runtime/tools/vertex_live`)예요. `/opt/marong-app`이 아니에요. 반영 전에 그 폴더의 해시를 `main`과 비교해요.
    - 순서는 이렇게 해요.
      1. DB 백업
      2. 통화 마이그레이션 010(관리자)
      3. 파일
      4. 통화가 없을 때 `marong-vertex-live` 재시작
      5. 로그 5분 확인
    - 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-call-connect/`에 먼저 두고 경로를 PR에 적어요.
    - 새 설정은 없어요. 붙잡기는 화면이 `hold=1`을 보낼 때만 돌아서, 옛 화면에는 영향이 없어요.
  - 앱 0.3.1(TASK-473, versionCode 9)과 0.3.2(TASK-468, versionCode 10)는 같은 인증서로 동희님 노트북에서 서명하고(D65), 앱 스스로 업데이트 경로로 게시해요. 게시는 서버 반영 상시 허락(2026-11-15) 안이에요. 0.3.1은 서버 코드를 바꾸지 않아요.
- 하면 안 되는 것:
  - 벨 서버 규칙(벨 줄, FCM 벨 메시지, 받을 창 5분)을 바꾸지 않아요.
  - 디스코드 음성 중계(`entrypoint='discord'`)를 건드리지 않아요.
  - 통화 지시문·목소리·`live_tuning`을 바꾸지 않아요.
  - 벨이 울릴 때 서버가 Gemini를 미리 열지 않아요(고르지 않은 안, [요구사항](../02-prd/call-connect.md)).
  - 시각 기록·재생 진단·로그에 대화 글, 이름, 주소, 토큰, 기기 id를 넣지 않아요.
- 겹치는 파일: `apps/android/`는 0.3.1(`codex/call-audio-speaker`)과 0.3.2(`codex/call-connect-app`)가 차례로 고쳐요. 0.3.2는 0.3.1이 합쳐진 뒤 시작해요. `tools/vertex_live/server.py`·`static/app.js`는 사람별 사용 한도(`codex/usage-limit`, [usage-limit.md](usage-limit.md#gpt-인계))와 열린 브랜치 `codex/character-trait-schema`(PR #66)도 고쳐요. 먼저 합쳐지는 쪽 뒤에 맞춰요. 통화 마이그레이션 번호는 009가 사람별 사용 한도, 010이 이 패키지예요. `apps/android/`를 고치는 다른 열린 작업은 2026-11-21 현재 없어요.
- 사람 확인: TC-594·588(앱 0.3.1), TC-587(앱 0.3.2). 현경님 폰은 동희님이 부탁해요.
- 끝 조건:
  - 모든 TASK의 끝 조건 시험이 통과해요.
  - 지금 시험이 그대로 통과해요. 목록은 [12 QA 6절](../12-qa/call-connect.md#6-회귀-시험고친-뒤-gpt가-돌림) 아래에 있어요.
  - 1차 반영 뒤 확인 통화의 `connect_timing`·`playback`이 운영 DB에 저장돼요.
  - TC-587의 P95를 '11단계 진행'에 적어요.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

- 번호: TASK-460\~474. 이 패키지 범위는 TASK-460\~479예요([README](README.md#id-범위)).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-460 | 저장소: 구간을 `opening`으로 넣고 `setupComplete`에서 `open`·`provider_ready_at=clock_timestamp()`, 새 통화 첫 구간 `start`(이어 받은 통화는 `reconnect`, 갈아타기 `handoff` 그대로), Gemini 연결 실패면 `start_failed`로 닫기, `connect_timing`·`playback` 저장 함수, 소리 경로 기록에 `rtc_silent` | SPEC-400, SPEC-404, BUG-110 | TBL-004, `call.transport_events`, `call_memory.py`, `live_session.py` | 없음(010 있음) | GPT | 0.5 | `pgserver`(통화 001\~010)에서 TC-572 통과, 지금 `tools/vertex_live/test_*.py` 통과 |
| TASK-461 | 서버 메시지: `timing`(4KB, 칸 검사, 한 번), `audio_ready`, `playback`(칸 검사, 마지막 값), 서버 표시 5개, `hold=1` 첫마디 붙잡기 3,000ms, WebRTC 짝은 쌓인 소리가 없는 턴 사이에서만 붙이기, PCM 바꾸기 이유에 `rtc_silent` | SPEC-400, SPEC-402, SPEC-404 | API-107, TBL-004 | TASK-460 | GPT | 1 | TC-570·571·577·582 통과, TC-578의 서버 쪽(한 턴 안에 두 경로 없음) 통과, `test_ring.py` 통과 |
| TASK-462 | 정적 파일: 내용 해시 버전, `index.html`에 `?v=`와 `data-assets`, 버전이 맞을 때만 1년 캐시, `data-theme`를 한국 시각으로, `livekit-client.js`를 `async`로 빼고 `rtc-client.js`가 기다리기 | SPEC-401 | API-246, `server.py`, `static/index.html`, `static/rtc-client.js`, `static/app.js` | 없음 | GPT | 0.5 | TC-573·574·575 통과, CSP 머리 그대로 |
| TASK-463 | 화면 동시 시작: `begin`의 세 분기(워크릿·마이크, WebRTC, `/live?hold=1`), `audio_ready`, `/status`·프로필 동시 | SPEC-402 | `static/app.js`, `static/rtc-client.js` | TASK-461, TASK-462 | GPT | 1 | TC-576·578·579 통과, 마이크 거절·마이크 없음·WebRTC 실패 지금 문구 그대로 |
| TASK-464 | 화면 시각 기록: 3.1 표시와 `timing` 보내기, `window.__marongApp.answerRing(id, answeredAt)`·`prepareCall()` 함수(앱 0.3.1이 부름) | SPEC-400, SPEC-403(화면 쪽) | `static/app.js`, API-107 | TASK-463 | GPT | 0.5 | TC-570의 화면 쪽, TC-589 통과, 앱 0.3.0 흐름(`?ring=` 주소)이 그대로 됨 |
| TASK-465 | 화면 재생 확인: 500ms 확인, `play()`·`startAudio()` 한 번 다시, 2,000ms면 `rtc_silent`로 PCM, `canPlaybackAudio` 처리, `playback` 메시지 | SPEC-404 | `static/rtc-client.js`, `static/app.js`, API-107 | TASK-461 | GPT | 1 | TC-580·581·582·583 통과 |
| TASK-466 | 1차 서버 반영: 해시 비교, DB 백업, 통화 마이그레이션 010, 파일, 통화 없을 때 재시작, 로그 5분, 되돌리기 스크립트, 확인 통화 두 번 | SPEC-400\~402, SPEC-404 | 서버 | TASK-460\~465 | GPT | 0.5 | 로그 오류 0, 확인 통화 두 줄에 `mode='start'`·`connect_timing`·`playback`, 정적 파일 머리가 TC-573과 같음, 되돌리기 경로가 PR에 있음 |
| TASK-467 | 앱 0.3.2: 받기에서 `evaluateJavascript`로 `answerRing`(통화 화면이 떠 있을 때), 꺼져 있었으면 벨 주소 한 번만, 벨 때 `prepareCall`, 버전 0.3.2(versionCode 10) | SPEC-403 | `apps/android/`(`MainActivity`, `Ring`, `CallService`, `marong_page.js`) | TASK-464, TASK-473 | GPT | 1 | TC-584·585 통과, TC-586·590\~593 그대로 통과, `npm test`, `./gradlew testDebugUnitTest lintDebug`, `call-ring.e2e.cjs` 통과 |
| TASK-468 | 앱 0.3.2 서명·게시: 같은 인증서, 앱 스스로 업데이트 경로로 게시, 0.3.1 → 0.3.2 덮어 깔기 확인(에뮬레이터) | SPEC-403 | 앱 릴리스 | TASK-466, TASK-467 | GPT | 0.5 | 서명 APK의 크기·SHA-256·인증서를 '11단계 진행'에 적음, 서버 로그에 `code=10` 내려받기 |
| TASK-469 | 실제 폰 확인 준비와 기록: 약속 벨 10번(잠금 5, 쓰는 중 5)과 출력 장치 네 가지, DB의 `connect_timing`으로 P95 셈 | SPEC-403, SPEC-404, SPEC-405, REQ-491, TC-587, TC-588 | 서버 읽기 | TASK-468 | GPT(사람 확인은 동희님·현경님) | 0.5 | TC-587·588 결과와 P95가 '11단계 진행'에 있음. 사람이 들어 보기 전에는 '기기 확인 전' |
| TASK-470 | PR 설명과 '11단계 진행' 표 | SPEC-400, SPEC-401, SPEC-402, SPEC-403, SPEC-404, SPEC-405 | 없음 | TASK-460\~469, TASK-472\~474 | GPT | 0.25 | TASK마다 상태·커밋·확인한 것이 있음 |
| TASK-471 | 설계 쪽 마무리: 단계 기록, Notion 행, 동희님 보고(NEXUS는 하지 않음, 동희님 2026-11-21 16:47 KST) | SPEC-400, SPEC-401, SPEC-402, SPEC-403, SPEC-404, SPEC-405 | 없음 | TASK-470 | Claude | 0.25 | 보고에 P95와 남은 것이 있음 |
| TASK-472 | 앱 0.3.1: 새 `CallAudio`(장치 고르기는 시험하기 쉬운 순수 함수로), `MarongCallPlugin`의 통화 시작·끝(`setCallActive`)에서 통화 모드·스피커 기본·다시 고르기(통화당 3번)·통화 볼륨 하한 60%와 되돌리기·볼륨 버튼·앱 시작 때 남은 값 되돌리기, 화면 함수 `audioRoute`가 있으면 진단 넘기기, 버전 0.3.1(versionCode 9) | SPEC-405 | `apps/android/`(`MarongCallPlugin`, 새 `CallAudio`, `MainActivity`, `build.gradle`) | 없음 | GPT | 0.5 | TC-586·590·591·592·593·595 통과, `npm test`, `./gradlew testDebugUnitTest lintDebug`, `call-ring.e2e.cjs` 통과 |
| TASK-473 | 앱 0.3.1 서명·게시: 같은 인증서, 앱 스스로 업데이트 경로로 게시, 0.3.0 → 0.3.1 덮어 깔기와 통화 한 번(에뮬레이터, 가짜 마이크 소리) | SPEC-405 | 앱 릴리스 | TASK-472 | GPT | 0.25 | 서명 APK의 크기·SHA-256·인증서를 '11단계 진행'에 적음, 서버의 업데이트 확인이 0.3.0 기기에 `code=9`를 알려 줌 |
| TASK-474 | 앱 0.3.1 실제 폰 기록: 동희님이 들어 본 결과(TC-594)와 그 통화의 진단 `device`·`voiceVolume`(TASK-465 반영 뒤라면 DB `playback`, 그 전이면 '진단 없음'으로) | SPEC-405, REQ-494, REQ-498, TC-594 | 서버 읽기 | TASK-473 | GPT(사람 확인은 동희님·현경님) | 0.25 | TC-594 결과가 '11단계 진행'에 있음. 사람이 들어 보기 전에는 '기기 확인 전' |

## 11단계 진행

아직 시작 전이에요. GPT가 TASK마다 상태·커밋·확인한 것을 적어요.

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-460 | 시작 전 | | |
| TASK-461 | 시작 전 | | |
| TASK-462 | 시작 전 | | |
| TASK-463 | 시작 전 | | |
| TASK-464 | 시작 전 | | |
| TASK-465 | 시작 전 | | |
| TASK-466 | 시작 전 | | |
| TASK-467 | 시작 전 | | |
| TASK-468 | 시작 전 | | |
| TASK-469 | 시작 전 | | |
| TASK-470 | 시작 전 | | |
| TASK-471 | 시작 전 | | |
| TASK-472 | 시작 전 | | |
| TASK-473 | 시작 전 | | |
| TASK-474 | 시작 전 | | |
