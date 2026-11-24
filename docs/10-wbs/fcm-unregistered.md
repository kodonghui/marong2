# FCM 등록 해제 판단 작업 목록(10단계 WBS)

## GPT 인계

2026-11-24 작성(Claude). **시작 가능**(2026-11-24 체크포인트 통과): 질문 0\~4와 바뀌는 승인 항목 F-1\~F-7·G-1\~G-6은 모두 추천안으로 승인됐고(D181\~D185), 질문 5는 사용자님 직접 답 "설정 없이 넣어도 됨"(마롱이 항목 96 e1770, 2026-11-24 KST)(D186), 합치기와 운영 반영은 사용자님 말 "반영까지 해"(마롱이 항목 96 e1760, 2026-11-24 KST)(D187)이에요([01 도메인 8.1절](../01-domain/fcm-unregistered.md#81-체크포인트-답2026-11-24)). TASK-555(승인 문서 고침)는 이 설계 PR(#130)에서 끝냈어요. 이 PR이 `main`에 합쳐진 뒤 시작하고, 시작 때는 마롱이 봇이 지시해요.

- 목표: FCM이 등록 해제(HTTP 404와 상세 코드 `UNREGISTERED`)라고 확실히 답할 때만 폰의 FID를 지우고, 400과 등록 해제가 확인되지 않은 404는 보내기 실패로 처리해 FID를 지켜요. `gone`·`failed`로 끝난 보내기마다 원인(HTTP 상태와 FCM 코드)을 로그 한 줄에 남기고, 키 문제 경고(1시간 한 번)에는 FCM 상세 코드를 더해요. 원문은 [02 요구사항 출처 표기](../02-prd/fcm-unregistered.md#출처-표기)의 D180이에요.
- 시작: 이 설계가 합쳐진 `main` 머리에서 새 브랜치 `codex/fcm-unregistered`.
- 읽을 것: 이 문서 밖은 아래 파일과 ID만 읽어요.
  - 명세: [04 기능 명세](../04-functional-spec/fcm-unregistered.md)의 SPEC-510\~512와 3절(답 나누기 표, 로그 줄, 보내는 곳마다 결과).
  - 지금 동작: [01 도메인 4절](../01-domain/fcm-unregistered.md#4-지금-동작-사실).
  - 시험: [12 시험 계획](../12-qa/fcm-unregistered.md)의 TC-720\~728과 바뀐 TC-126.
  - 승인 문서 가운데 닿는 곳: [app-chat.md](../app-chat.md)의 SPEC-117·126, [app-ring.md](../app-ring.md)의 SPEC-131, [app-update.md](../04-functional-spec/app-update.md)의 SPEC-430과 8.5. 답(D182)대로 TASK-555에서 고쳐 뒀어요(줄마다 'D182 F-n').
- 이미 된 것: 코드는 아무것도 바꾸지 않았어요. 표·API·화면 바뀜이 없어서 마이그레이션도 없어요. 운영 `marong-app`의 `marong/fcm.py`·`app_push.py`·`app_update_push.py`는 `main` `1a29477`과 해시가 같아요(2026-11-24 읽기, sha256 앞 16자리 `fcm.py` `03b0c417ebae2a5f`).
- 순서: TASK-555(Claude, 끝) → TASK-550 → TASK-551 → TASK-552 → TASK-553(서버 반영) → TASK-554(7일 뒤).
- 시험 환경: AGENTS.md와 같아요(Python 3.12, `pgserver`). FCM은 가짜 HTTP(`httpx.MockTransport`)만 써요. 진짜 FCM에 시험 메시지를 보내지 않아요. 지금 TC-126 시험(`tests/test_app_chat.py`의 FCM 부분)의 가짜 OAuth·가짜 FCM을 그대로 써요.
- 반영:
  - 서버 `ko-family`, 서비스 `marong-app.service`(실행 `/opt/marong-app/run_app.py`, 작업 폴더 `/opt/marong`). 바뀌는 코드 파일은 `/opt/marong-app/marong/fcm.py` 하나이고, 업데이트 내역 파일 하나가 더해져요(아래).
  - 반영 전 그 파일의 해시를 `main` `1a29477`의 것과 비교해요. 다르면 멈추고 PR에 적어요.
  - 순서: DB·파일 백업 → 파일 → 대화·통화가 없을 때 `marong-app.service` 재시작 → 로그 5분 오류 확인(TC-725). 마이그레이션은 없지만 AGENTS.md 순서대로 DB도 백업해요(반영 뒤 `fid`·`dropped_at`이 바뀌는 줄이 생겨요).
  - 켜고 끄는 설정: 두지 않아요. AGENTS.md '새 기능은 끄고 켜는 설정으로'의 예외이고, 사용자님 직접 답 "설정 없이 넣어도 됨"(마롱이 항목 96 e1770, 2026-11-24 KST)으로 정했어요(D186). 반영하면 바로 바뀌어요.
  - 반영 허락: 사용자님 말 "반영까지 해"(마롱이 항목 96 e1760, 2026-11-24 KST)(D187). TASK-553은 따로 묻지 않고 해요. 대화·통화가 없을 때 재시작하는 규칙은 그대로예요.
  - 되돌리기: 백업한 `fcm.py`로 바꾸고 재시작. 스크립트를 서버 `~/marong-deploy/<날짜>-fcm-unregistered/`에 먼저 두고 경로를 PR에 적어요.
  - `/opt/marong-discord/marong/fcm.py`는 서비스가 꺼져 있고 해시도 달라 건드리지 않아요.
  - 업데이트 내역: 관리자가 알아챌 수 있는 변화예요('앱 지워짐'이 줄고, 업데이트 기록에 '보내기 실패(410)' 대신 500이 남을 수 있음). PR #129로 AGENTS.md에 들어간 '업데이트 내역'대로 구현 PR에 `marong/changelog/<반영 폴더 이름>.json`을 더하고(형식 SPEC-500), 반영 때 그 파일만 `/opt/marong-app/marong/changelog/`에 복사하고 되돌리기 스크립트가 그 파일을 지우게 해요.
- 하면 안 되는 것:
  - `AppPush`·`AppUpdatePush`의 결과 처리(`drop_fid`를 부르는 조건, `FAILURE_STATUS`)를 바꾸지 않아요. 바꿔야 하면 '설계 질문'에 적어요.
  - 업데이트 기록(TBL-182)의 상태 번호를 더하지 않아요(질문 2는 A, D183).
  - 이미 지워진 폰의 `fid`·`dropped_at`을 손으로 고치지 않아요.
  - 로그·PR·시험 자료에 진짜 FID·설치 ID·토큰·이메일·알림 글, FCM 오류 메시지(`error.message`, `description`)을 넣지 않아요.
- 겹치는 파일:
  - `tests/test_app_update_push.py`: 관리 페이지 기능 변경 3의 TASK-503(TC-653)은 PR #131로 `main`에 합쳐졌어요(`125ac44`). TC-724는 그 위에 더해요.
  - `tests/test_app_chat.py`: 2026-11-24 지금 이 파일을 고치는 다른 열린 PR은 없어요.
  - `marong/fcm.py`: 다른 패키지가 고치지 않아요.
- 사람 확인: 없어요. 반영 확인(TC-725)과 7일 관찰(TC-726)은 GPT가 서버 로그와 DB 개수로 해요.
- 끝 조건:
  - 모든 TASK의 끝 조건 시험이 통과해요.
  - 지금 시험이 그대로 통과해요: `tests/test_app_chat.py`(바뀐 TC-126 포함), `tests/test_app_update_push.py`, 선 전화·벨을 쓰는 `tests/` 시험.
  - '11단계 진행'에 TASK마다 상태·커밋·확인한 것을 적고, TC-726의 개수를 적어요.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

- 번호: TASK-550\~555. 이 패키지 범위는 TASK-550\~559예요([README](README.md#id-범위)).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-550 | 답 나누기: `_error()`가 상위 상태, FcmError 상세 코드(`@type` 확인), `google.rpc.BadRequest`의 첫 칸 이름을 돌려주고, `send()`는 04 3.1 표대로(`gone`은 404와 FcmError `UNREGISTERED`뿐, 400과 그 밖의 404는 `failed`, 다시 보내지 않음). 모듈과 `send()`의 설명 글을 새 뜻으로 고침. 지금 TC-126 시험의 400 줄을 바뀐 기대값으로 옮김 | SPEC-510, REQ-630 | `marong/fcm.py`, `tests/test_app_chat.py` | TASK-555 | GPT | 0.25 | TC-720과 바뀐 TC-126 통과 |
| TASK-551 | 거절 로그: 보내기 한 번이 `gone`·`failed`로 끝났고 그동안 HTTP 답을 받았으면 끝날 때 `fcm_send_status` 한 줄(마지막 HTTP 답의 값, 04 3.2의 칸과 모양), 지금 `fcm_send_status <코드>` 줄을 바꿈. `auth`는 줄 없이 `fcm_auth_failed` 경고(1시간 한 번)에 `code` 더함. `field` 칸 넣기(D184) | SPEC-511, REQ-631 | `marong/fcm.py`, `tests/test_app_chat.py` | TASK-550 | GPT | 0.25 | TC-721 통과 |
| TASK-552 | 보내는 곳 셋 시험: 진짜 `FCM` 클래스와 가짜 HTTP, `pgserver`의 진짜 `AppStore`로 글 알림(`notify`), 벨(`ring`과 선 전화가 글로 넘어감), 업데이트 보내기(`AppUpdatePush`, 가짜 시계로 차례 넷). 부르는 코드는 바꾸지 않음 | SPEC-512, REQ-630 | `tests/test_app_chat.py`, `tests/test_app_update_push.py` | TASK-550 | GPT | 0.5 | TC-722, TC-723, TC-724 통과, 끝 조건의 지금 시험 통과 |
| TASK-553 | 서버 반영: 해시 비교, DB·파일 백업, 되돌리기 스크립트, 업데이트 내역 파일(AGENTS.md), `fcm.py` 한 파일, 대화·통화가 없을 때 `marong-app.service` 재시작, 로그 5분 | SPEC-510, SPEC-511 | 운영 `/opt/marong-app/marong/fcm.py`, `marong/changelog/<반영 폴더 이름>.json` | TASK-550, TASK-551, TASK-552(질문 5는 '설정 없이' D186, 반영 허락 D187) | GPT | 0.25 | TC-725 통과, 백업·스크립트 경로가 PR에 있음 |
| TASK-554 | 7일 관찰: 반영 뒤 7일의 `fcm_send_status` 줄을 `http`·`code`·`result`별로 세고, 그동안 새로 채워진 `dropped_at` 수를 SELECT로 셈. 정말 틀린 FID가 계속 실패하는지(TC-727, D183)와 등록 만료로 '앱 지워짐'이 잘못 보인 폰(TC-728, D185)도 셈(개수만) | REQ-631, SPEC-511, REQ-630 | 없음(읽기) | TASK-553 | GPT | 0.15 | TC-726, TC-727, TC-728 결과가 '11단계 진행'에 있음 |
| TASK-555 | 설계 쪽 마무리: 체크포인트 답대로 승인 문서 고치기(F-1\~F-7: app-chat.md SPEC-117·126·TC-126, app-ring.md SPEC-131, app-update.md SPEC-430·8.5, FL-193. G-1\~G-6: admin 01·02·04와 app-update SPEC-438·8.6), 바뀌기 전 글을 각 문서 끝 '바뀐 승인 글'에 남기기, 단계 기록, README '시작 가능' | 01 도메인 7·8절 | `docs/`, `.corthex/stages/fcm-unregistered.json` | 체크포인트 답 | Claude | 0.25 | 바뀐 줄마다 답(D181\~D186) 표시, 용어 검사 통과 |

- 모든 SPEC 행에 작업이 있어요: SPEC-510 TASK-550, SPEC-511 TASK-551, SPEC-512 TASK-552. 반영과 관찰은 TASK-553·554예요.
- 모두 합쳐 약 1.65일이에요.

## 11단계 진행

각 TASK의 구현, 검사, 배포 상태를 기록해요.

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-550 | 완료 | `0b4f16c` | TC-720과 TC-126 통과. 상세 코드 없는 404에서 기존 코드의 오판 재현 |
| TASK-551 | 완료 | `0b4f16c` | TC-721 19개 시나리오 통과. 기존 코드에서 종료 로그 누락 재현 |
| TASK-552 | 완료 | `0b4f16c` | TC-722~724 통과. 앱 채팅 전체 430개 확인, 약속 전화 벨 75개, 선 전화 150개, 업데이트 발송 23개 통과. 읽음·답변 상태 단언은 `main`과 구현 브랜치에서 간헐적으로 실패했고 단독 재실행에서 통과 |
| TASK-553 | 운영 반영 대기 | | TC-725는 PR 리뷰와 병합 뒤 운영 반영 시 실행 |
| TASK-554 | 운영 반영 후 관찰 대기 | | TC-726~728은 TASK-553 완료 후 7일간의 로그·DB 개수로 확인 |
| TASK-555 | 끝(2026-11-24, PR #130) | PR #130 | 승인 원문 열세 곳을 답(D182)대로 고치고 줄마다 'D182 F-n·G-n', 문서 머리말에 바뀌기 전 글의 자리(01 도메인 7절). 질문 5 답(D186)과 반영 허락(D187)을 적고 단계 기록(01\~10·12 `done`)과 README '시작 가능'을 적음. 용어 검사 통과 |
