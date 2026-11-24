# FCM 등록 해제 판단: 기능 명세

상태: 2026-11-24 체크포인트 통과(D181\~D185, 승인한 사람 사용자님, [01 도메인 8.1절](../01-domain/fcm-unregistered.md#81-체크포인트-답2026-11-24)). 새 행은 active예요. 바뀐 승인 행(SPEC-117·126·131·430, app-update 8.5, PR #127로 바뀐 SPEC-460·438·8.6)은 답(D182)대로 그 문서에서 고쳤고, 바뀌기 전 글은 [01 도메인 7절](../01-domain/fcm-unregistered.md#7-바뀌는-승인-항목항목마다-따로-여쭤요)에 있어요.
입력: [요구사항](../02-prd/fcm-unregistered.md) REQ-630·631, [도메인](../01-domain/fcm-unregistered.md) TERM-280과 4절(지금 동작), 승인 명세 [app-chat.md](../app-chat.md)(SPEC-117·126), [app-ring.md](../app-ring.md)(SPEC-131), [app-update.md](app-update.md)(SPEC-430·435, 8.5), [call-first.md](call-first.md)(SPEC-266), [unified.md](unified.md)(SPEC-383).
기준 코드: `main` `1a29477`(운영 `marong-app` 파일과 해시가 같음, 2026-11-24).
표시: [사실] 코드·공식 문서에서 확인, [새 제안] 이 명세에서 Claude가 정한 것, [추정] 근거 있는 짐작. 예시의 FID·메시지는 모두 지어낸 값이에요.
ID 번호: SPEC-510\~512(이 패키지 범위 510\~519).

## 1. 모든 행에 공통인 규칙

- 바뀌는 코드는 `marong/fcm.py` 하나예요. 결과 이름 넷(`ok`·`gone`·`auth`·`failed`)과 그 이름을 읽는 곳(`AppPush._send`, `AppUpdatePush._send`의 `FAILURE_STATUS`)은 그대로이고, `gone`의 뜻만 좁아져요.
- 보내기 한 번의 10초 예산, 429·500·502·503·504와 연결 오류의 다시 보내기(1초·2초 또는 `Retry-After` 10초까지), 업데이트 메시지는 보내기 안에서 다시 보내지 않음, 401이면 토큰 버림, 키 문제 경고 1시간 한 번은 모두 그대로예요.
- 표·마이그레이션·API·앱·화면은 바뀌지 않아요. 켜고 끄는 설정은 두지 않는 것이 추천이고, AGENTS.md 규칙의 예외라 사용자님 답을 기다려요(질문 5, D186).
- 로그에는 메시지 글, FID, 설치 ID, 이메일, OAuth 토큰, FCM 오류 메시지(`error.message`, `fieldViolations[].description`)을 남기지 않아요(REQ-118).

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-510 | FCM 답 나누기(`FCM.send`) | REQ-630, TERM-280 | 서버에 FCM 키가 있음(SPEC-127) | 보내기 한 번의 마지막 답을 3.1 표대로 나눠요. `gone`은 등록 해제 답(TERM-280)일 때뿐이에요: HTTP 404이고, 본문 `error.details` 목록에 `@type`이 `type.googleapis.com/google.firebase.fcm.v1.FcmError`이며 `errorCode`가 `UNREGISTERED`인 항목이 있음. HTTP 400은 상위 상태·상세 코드와 상관없이 `failed`, 등록 해제가 확인되지 않은 404도 `failed`이고, 둘 다 보내기 안에서 다시 보내지 않아요. 401·403은 지금처럼 `auth`예요. 답 읽기(`_error`)는 상위 상태(`error.status`), FcmError 상세 코드, `google.rpc.BadRequest`의 첫 `fieldViolations[].field`를 돌려줘요(3.2의 로그가 써요) | 본문이 JSON이 아님·`error`가 없음·`details`가 목록이 아님 → 상세 코드 없음(404도 `failed`)<br>HTTP 400인데 FcmError가 `UNREGISTERED` → `failed`(HTTP 상태가 404가 아님)<br>`@type` 없이 `errorCode: UNREGISTERED`만 있음 → `failed`(질문 2는 A, D183)<br>404이고 FcmError `UNREGISTERED`와 다른 상세가 함께 있음 → `gone`<br>403 `SENDER_ID_MISMATCH`·401 `THIRD_PARTY_AUTH_ERROR` → `auth`(그대로, 401이면 토큰 버림)<br>503 뒤 다시 보낸 답이 404 `UNREGISTERED` → `gone`(마지막 답으로 정함)<br>405·413처럼 표에 없는 상태 → `failed`(그대로) | 가짜 HTTP(`httpx.MockTransport`)로 3.1 표의 열 줄을 보내면 결과가 표와 같고, 400·404·401·403 답에는 FCM 보내기 요청(`messages:send` 주소)이 한 번뿐(다시 보내지 않음, OAuth 토큰 요청은 세지 않음). 바뀐 TC-126의 200·429·503·401·403·시간 초과·10초 예산이 그대로 통과(TC-720, TC-126) | active(D181, D183) |
| SPEC-511 | 거절 로그 한 줄 | REQ-631, REQ-118 | SPEC-510 | 보내기 한 번이 `gone`이나 `failed`로 끝났고 그 보내기 동안 FCM 보내기 요청에 HTTP 답을 하나라도 받았으면, 끝날 때 로그 `marong.fcm`에 INFO 한 줄을 남겨요: `fcm_send_status kind=<k> http=<n> status=<s> code=<c> field=<f> result=<r>`(3.2). 칸 값은 그 보내기에서 받은 마지막 HTTP 답의 것이에요. 그 뒤 연결 오류·시간 초과·예산 끝으로 끝나도 같아요. 다시 보낸 중간 답마다 줄을 남기지 않아요. 지금의 `fcm_send_status <코드>` 줄은 이 줄로 바뀌어요. `auth`(401·403)는 이 줄을 남기지 않아요: 키 문제는 모든 보내기가 같은 원인이라, 지금처럼 `fcm_auth_failed` 경고를 1시간에 한 번만 남기고 그 글을 `status=<n> code=<c>`로 해요(값 모양은 3.2와 같음). `fcm_send_error <종류>`(HTTP 답이 없는 실패)는 그대로예요. `AppPush`의 `fcm_send kind=… ok=… gone=… auth=… failed=…`과 `AppUpdatePush`의 `app_update push …` 줄도 그대로예요 | 값이 정해 둔 모양이 아님 → 그 칸은 `other`<br>값이 없음 → `-`<br>`fieldViolations`가 여럿 → 첫 칸만<br>503 뒤 다시 보낸 요청이 시간 초과 → 줄 하나(`http=503 … result=failed`)와 `fcm_send_error`<br>429의 `Retry-After`가 예산을 넘어 기다리지 않고 끝남 → 줄 하나(`http=429`)<br>503 뒤 예산이 끝나 더 보내지 않음 → 줄 하나(`http=503`)<br>HTTP 답을 하나도 받지 못하고 실패(연결 오류·시간 초과만) → 이 줄 없음, 지금 `fcm_send_error` 그대로<br>`auth`(401·403) → 이 줄 없음, `fcm_auth_failed status=<n> code=<c>` 1시간 한 번<br>토큰 받기 실패(`auth`, HTTP 답이 OAuth 쪽) → 이 줄 없음, `fcm_auth_failed` 그대로 | 3.1 표의 1\~8·10은 줄 하나이고 칸 값이 3.2 표와 같음. 9(403)는 이 줄이 없고 `fcm_auth_failed status=403 code=SENDER_ID_MISMATCH` 경고가 1시간에 한 번. 200에는 줄이 없음. 503 세 번 뒤 실패, 503 뒤 시간 초과, 예산을 넘는 `Retry-After`의 429는 줄 하나씩(`http=503`, `http=503`, `http=429`). 로그 전체에 지어낸 FID·OAuth 토큰·알림 글·FCM 오류 메시지가 없음. 소문자 코드나 100자 칸 이름은 `other`(TC-721) | active(D181, D184) |
| SPEC-512 | 보내는 곳마다 처리 | REQ-630 | SPEC-510 | 부르는 코드는 바뀌지 않고 결과 이름대로 지금처럼 해요(3.3 표). 글 알림·벨(`AppPush._send`)은 `gone`일 때만 `drop_fid`를 불러요. 업데이트 보내기(`AppUpdatePush._send`)는 `gone`이면 `push_failed` 410과 `drop_fid`, `auth`·`failed`면 `push_failed` 401·500이고 다음 차례(10분 뒤)에 다시, 3번에서 그만이에요(SPEC-430). 그래서 400과 확인되지 않은 404는 어느 곳에서도 FID를 지우지 않아요 | 모든 벨이 `failed` → 선 전화는 지금처럼 벨 줄 `failed`와 그림 화두 글(SPEC-266, REQ-282)<br>모든 알림이 `failed` → 지금처럼 방에 남기고 `later`(SPEC-383)<br>`drop_fid` 쓰기 실패 → 지금처럼 경고 한 줄(`app_device_drop_failed`·`app_update drop failed`) | 진짜 `FCM` 클래스와 가짜 HTTP, `pgserver`의 진짜 `AppStore`로: 400 → 글 알림·벨·업데이트 모두 FID와 `dropped_at` 그대로, 업데이트는 `push_failed` 500 시도 1\~3 뒤 그만. 404 `UNREGISTERED` → 셋 모두 FID 비움·`dropped_at` 채움, 업데이트는 410 한 번 뒤 대상에서 빠짐(TC-722, TC-723, TC-724) | active(D181) |

## 3. 자세한 규칙

### 3.1 답 나누기

| # | HTTP | 본문(가짜 답의 모양) | 결과 | 보내기 안에서 다시 | 로그 `code` | 지금과 다른가 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 404 | `error.details`에 `{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}` | `gone` | 안 함 | `UNREGISTERED` | 같음 |
| 2 | 404 | `{"error": {"status": "NOT_FOUND"}}`(상세 없음) | `failed` | 안 함 | `-` | 바뀜(지금 `gone`) |
| 3 | 404 | JSON이 아닌 본문(HTML 등) | `failed` | 안 함 | `-` | 바뀜(지금 `gone`) |
| 4 | 400 | `{"error": {"status": "INVALID_ARGUMENT"}}`(상세 없음) | `failed` | 안 함 | `-` | 바뀜(지금 `gone`) |
| 5 | 400 | `details`에 `google.rpc.BadRequest`, `fieldViolations[0].field`가 `message.android.ttl` | `failed` | 안 함 | `-`(`field=message.android.ttl`) | 바뀜(지금 `gone`) |
| 6 | 400 | `details`에 FcmError `INVALID_ARGUMENT` | `failed` | 안 함 | `INVALID_ARGUMENT` | 바뀜(지금 `gone`) |
| 7 | 400 | `details`에 FcmError `UNREGISTERED` | `failed` | 안 함 | `UNREGISTERED` | 바뀜(지금 `gone`) |
| 8 | 404 | `details`에 `@type` 없이 `{"errorCode": "UNREGISTERED"}` | `failed` | 안 함 | `-` | 바뀜(지금 `gone`). 질문 2는 A라서 `failed`(D183) |
| 9 | 403 | `details`에 FcmError `SENDER_ID_MISMATCH` | `auth` | 안 함 | 이 줄 없음. 경고 `fcm_auth_failed status=403 code=SENDER_ID_MISMATCH`(1시간 한 번) | 결과는 같음. 경고 글에 `code` 더함 |
| 10 | 503 → 404 | 처음 503, 다시 보낸 답이 1번 모양 | `gone` | 1초 뒤 한 번 | `UNREGISTERED` | 같음 |

- [사실] 결과 이름을 읽는 곳은 `AppPush._send`, `AppPush._fan_out`(개수 로그), `AppUpdatePush._send`(`FAILURE_STATUS`)와 진단 도구(`tools/fcm_test_send.py`, 출력만)뿐이에요. 넷 모두 고칠 필요가 없어요.
- 400을 보내기 안에서 다시 보내지 않는 이유: 같은 메시지를 같은 대상에 다시 보내도 같은 400이 와요. 지금도 400·404는 다시 보내지 않아요.
- 상세 코드는 FcmError의 것만 써요. `google.rpc.BadRequest`에는 상세 코드가 없고 칸 이름만 있어요. [사실, FCM 문서] 공식 예시의 오류 상세는 메시지 형식 오류에서 `google.rpc.BadRequest`, 등록 오류에서 `FcmError`예요.

### 3.2 로그 줄

모양: `fcm_send_status kind=<k> http=<n> status=<s> code=<c> field=<f> result=<r>`

| 칸 | 값 | 정해 둔 모양(아니면 `other`, 없으면 `-`) |
| --- | --- | --- |
| `kind` | 보낸 메시지의 `data.kind`(`proactive`, `reply`, `reminder`, `missed_call`, `ring`, `app_update` 등) | 소문자와 `_`, 1\~20자 |
| `http` | 그 보내기에서 받은 마지막 HTTP 답의 상태 | 100\~599 정수 |
| `status` | `error.status`(예: `NOT_FOUND`, `INVALID_ARGUMENT`) | 대문자와 `_`, 1\~40자 |
| `code` | FcmError의 `errorCode`(예: `UNREGISTERED`) | 대문자와 `_`, 1\~40자 |
| `field` | `google.rpc.BadRequest`의 첫 `fieldViolations[].field`(예: `message.android.ttl`) | 영문·숫자·`_`·`.`·`[`·`]`, 1\~80자. 칸 이름을 남겨요(D184) |
| `result` | `gone`·`failed` | 둘 가운데 하나(`auth`는 이 줄을 남기지 않음) |

예(지어낸 답): `fcm_send_status kind=app_update http=400 status=INVALID_ARGUMENT code=- field=message.android.ttl result=failed`, `fcm_send_status kind=proactive http=404 status=NOT_FOUND code=UNREGISTERED field=- result=gone`.

- 한 줄은 `gone`·`failed`로 끝난 보내기 한 번(폰 하나)마다예요. 키 문제(`auth`)는 모든 폰에 같은 원인이라 보내기마다 남기지 않고 1시간 한 번 경고만 남겨요(SPEC-117·TC-126의 1시간 한 번 그대로). 친구마다 폰은 20대까지라 한 차례에 많아야 그 수만큼이고, 업데이트 보내기는 한 차례 100개까지예요(SPEC-430).
- 7일 관찰(TC-726)은 이 줄을 `http`·`code`·`result`별로 세기만 해요.

### 3.3 보내는 곳마다 결과

| FCM 답 | 글 알림(`notify`: 선톡·일정·답·부재중·시스템 알림) | 벨(`ring`: 약속 전화·선 전화) | 업데이트 보내기(SPEC-430) |
| --- | --- | --- | --- |
| 등록 해제 답(3.1의 1·10) | 그 폰 실패, FID 비움·`dropped_at` 채움 | 그 폰 벨 실패, FID 비움 | `push_failed` 410, FID 비움, 그 폰은 다음 차례 대상이 아님 |
| 400, 확인되지 않은 404(3.1의 2\~8) | 그 폰 실패, FID 그대로 | 그 폰 벨 실패, FID 그대로 | `push_failed` 500, FID 그대로, 10분 뒤 다시(시도 3에서 그만) |
| 401·403 | 실패(그대로) | 실패(그대로) | `push_failed` 401, 다시(그대로) |
| 모든 폰이 실패 | 방에만 남기고 `later`(SPEC-383) | 선 전화는 그림 화두 글(SPEC-266) | 해당 없음 |

### 3.4 고르지 않은 안

- 400의 상세가 FcmError `INVALID_ARGUMENT`이고 메시지가 유효하다고 볼 근거가 있으면 지움(조사 보고서 선택지 2): '메시지가 유효하다'를 서버가 스스로 보장할 방법이 없어요. FCM 문서도 페이로드가 유효하다고 확신할 때만 쓰라고 해요.
- 새 결과 이름과 업데이트 기록 상태 400(질문 2의 B, D183에서 고르지 않음): 마이그레이션과 승인 행 셋이 더 바뀌어요. 원인은 로그로 알 수 있어서 지금은 두지 않아요.
- 같은 FID가 400을 n번 넘게 받으면 지움: 횟수를 셀 곳(표나 메모리)이 새로 생겨요. 7일 관찰(TC-726)에서 400이 되풀이되는 폰이 보이면 다시 여쭤요.

### 3.5 반영과 되돌리기

- 데이터를 바꾸지 않아요. 이미 `dropped_at`이 채워진 폰은 그대로 두고, 앱을 열어 기기 보고를 하면 지금처럼 풀려요(01 도메인 5.4).
- 반영: DB·파일 백업 뒤 `marong-app.service`의 `/opt/marong-app/marong/fcm.py` 한 파일과 재시작(10 인계, AGENTS.md 순서). 되돌리기: 백업한 `fcm.py`로 바꾸고 재시작.
- 반영 뒤 바뀌는 것: `gone`과 `dropped_at`이 줄고(메시지 형식 오류·상세 없는 404만큼), `failed`가 그만큼 늘어요. 업데이트 기록의 410이 줄고 500이 늘 수 있어요.
