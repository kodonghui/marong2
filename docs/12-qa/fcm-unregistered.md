# FCM 등록 해제 판단: 시험 계획(12단계)

상태: 2026-11-24 체크포인트 통과(D181\~D185, [01 도메인 8.1절](../01-domain/fcm-unregistered.md#81-체크포인트-답2026-11-24)). 질문 2·4의 반대 논거는 TC-727·728로 지켜봐요(D183·D185). 아직 아무 시험도 돌리지 않았어요. 시험을 쓰고 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)).
입력: [기능 명세](../04-functional-spec/fcm-unregistered.md) SPEC-510\~512의 받아들임 조건과 3.1·3.2·3.3 표, [요구사항](../02-prd/fcm-unregistered.md) REQ-630·631, [작업 목록](../10-wbs/fcm-unregistered.md) TASK-550\~555, 승인 TC-126([app-chat.md](../app-chat.md) 9절).
번호: TC-720\~728(이 패키지 범위 720\~739).

## 공통 조건

- FCM은 가짜 HTTP(`httpx.MockTransport`)만 써요. 진짜 FCM에 시험 메시지를 보내지 않아요. OAuth도 지금 TC-126 시험의 가짜를 그대로 써요.
- FID는 `"f" * 20`처럼 지어낸 값만, 친구는 '시험친구 가'만 써요. 운영 DB의 기기 줄을 시험 자료로 쓰지 않아요.
- 'Runs as'의 뜻: `unit`은 DB 없는 시험, `db`는 `pgserver`에 마이그레이션을 모두 넣은 진짜 Postgres와 진짜 `AppStore`, `ops`는 운영에서 하는 확인(읽기와 로그).
- 로그·결과 기록에는 개수와 결과 이름만 적어요.

## 1. 답 나누기와 로그(TASK-550·551)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-720 | FCM 답 나누기 | SPEC-510, REQ-630, TERM-280 | unit(`tests/test_app_chat.py`) | 04 3.1 표의 가짜 답 열 개(1\~10), 메시지 `notice(…, "proactive", …)`와 `app_update(…)` | 답마다 `FCM.send()`를 한 번 부르고 결과와 FCM 보내기 요청(`messages:send` 주소로 간 요청, OAuth 토큰 요청은 빼고) 수를 셈 | 1·10 `gone`, 2\~8 `failed`, 9 `auth`. 1\~9는 보내기 요청이 한 번(다시 보내지 않음), 10은 두 번(1초 기다림 한 번). 업데이트 메시지로 10을 보내면 503에서 `failed`(보내기 안에서 다시 보내지 않음, 지금 그대로) | |
| TC-126(바뀜, 01 도메인 7절 F-6) | FCM 응답별 처리 | SPEC-117, SPEC-510 | unit(`tests/test_app_chat.py`) | 지금 시험 그대로 | 200, 토큰 다시 씀, 429 `Retry-After`, 503 세 번, 10초 넘는 기다림, 시간 초과 세 번, 401, 403 두 번, OAuth 거절 | 지금 기대값 그대로. 404·400 두 줄은 TC-720으로 옮기고, 400 줄의 기대값은 `failed` | |
| TC-721 | 거절 로그 한 줄 | SPEC-511, REQ-631, REQ-118, D184 | unit(`tests/test_app_chat.py`, 로그 잡기, 가짜 시계) | TC-720의 답, 가짜 답 `error.message`에 지어낸 글 '시험오류글', `fieldViolations[].description`에 '시험설명글', 알림 글 '시험알림글', FID `"f" * 20`, 가짜 OAuth 토큰. 따로: 상세 코드가 소문자 `unregistered`, 칸 이름 100자, 503 뒤 시간 초과, `Retry-After: 30`인 429, 503 뒤 예산 끝 | 답마다 보내고 `marong.fcm` 로그를 모음. 9(403)는 같은 시간 안에 두 번 보냄 | 200에는 줄 없음. 1\~8마다 `fcm_send_status` 한 줄이고 칸이 04 3.2와 같음(예: 5는 `kind=proactive http=400 status=INVALID_ARGUMENT code=- field=message.android.ttl result=failed`). 9는 `fcm_send_status`가 없고 `fcm_auth_failed status=403 code=SENDER_ID_MISMATCH`가 두 번 보내도 한 번. 10은 줄 하나(`http=404`). 503 세 번 뒤 실패, 503 뒤 시간 초과, 503 뒤 예산 끝은 줄 하나씩(`http=503 … result=failed`), 503 뒤 시간 초과에는 `fcm_send_error`도 있음. `Retry-After: 30`인 429는 줄 하나(`http=429 … result=failed`). 소문자 코드와 100자 칸 이름은 `other`. `fcm_send_status`·`fcm_auth_failed`·`fcm_send_error`를 포함한 로그 전체에 '시험오류글', '시험설명글', '시험알림글', FID, OAuth 토큰이 없음(D184). 시간 초과만으로 끝난 실패에는 이 줄이 없고 `fcm_send_error`가 있음 | |

## 2. 보내는 곳마다(TASK-552)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-722 | 글 알림 | SPEC-512, REQ-630 | db(`tests/test_app_chat.py`) | 시험친구 가의 알림 받을 폰 둘(폰 1, 폰 2, FID 지어냄), 진짜 `FCM`과 가짜 HTTP, `AppPush` | ① 두 폰 모두 3.1의 5(400 형식 오류)로 답하게 하고 `notify(…, "proactive", …)` ② 폰 1은 3.1의 1(등록 해제), 폰 2는 200으로 답하게 하고 다시 `notify` ③ 3.1의 2(상세 없는 404)로 폰 2에 `notify` | ① 결과 (0, 2), 두 폰 `fid` 그대로·`dropped_at` 비어 있음, 로그 `fcm_send kind=proactive devices=2 ok=0 gone=0 auth=0 failed=2` ② 결과 (1, 2), 폰 1 `fid` 비움·`dropped_at` 채움, 폰 2 그대로 ③ 폰 2 `fid` 그대로 | |
| TC-723 | 벨과 선 전화 | SPEC-512, REQ-630, REQ-282, SPEC-266 | db(`tests/test_app_chat.py` 또는 선 전화 시험 파일) | 벨 받을 폰 하나(벨 채널 켜짐, 0.2.2 이상) | ① 3.1의 5(400)로 답하게 하고 약속 전화 벨과 선 전화 걸기 ② 3.1의 1(등록 해제)로 답하게 하고 선 전화 걸기 | ① `ring` 결과 0, `fid` 그대로·`dropped_at` 비어 있음. 선 전화는 벨 줄 `failed`이고 지금처럼 그림 화두 글로 넘어감(그림 화두가 꺼져 있으면 보통 선톡) ② 같은 넘어감, `fid` 비움·`dropped_at` 채움 | |
| TC-724 | 업데이트 보내기 | SPEC-512, SPEC-430, REQ-630 | db(`tests/test_app_update_push.py`, 가짜 시계) | 뒤처진 폰 둘(30일 안 보고, FID 있음), 새 릴리스 하나, 진짜 `FCM`과 가짜 HTTP | 폰 1은 늘 3.1의 5(400), 폰 2는 3.1의 1(등록 해제)로 답하게 하고 차례 1을 돌린 뒤 차례 2·3·4. 차례마다 가짜 시계를 10분 넘기고, 다시 보낼 대상은 DB 시각(`now()`)으로 고르므로 `push_failed` 줄의 `at`도 11분 앞으로 당겨요(지금 `tests/test_app_update_push.py`의 TC-600과 같은 방법) | 폰 1: `push_failed` 500이 시도 1·2·3에 하나씩, 차례 4에는 보내지 않음, `fid` 그대로·`dropped_at` 비어 있음. 폰 2: `push_failed` 410 시도 1 하나, `fid` 비움·`dropped_at` 채움, 차례 2부터 대상에 없음. 로그에 폰 1의 `fcm_send_status kind=app_update http=400 …` 세 줄 | |

## 3. 반영과 관찰(TASK-553·554)

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-725 | 반영한 서버 확인 | SPEC-510, SPEC-511 | ops | 운영 `marong-app` | ① 반영 전 `/opt/marong-app/marong/fcm.py` 해시가 `main` `1a29477`과 같은지 ② 반영 뒤 해시가 합친 커밋과 같은지 ③ 재시작 뒤 5분 로그 ④ 재시작 뒤 첫 FCM 보내기의 `fcm_send` 줄(자연히 생긴 것, 일부러 보내지 않음) | ①② 같음. ③ Traceback 없음, `fcm_send_error`가 반영 전 5분보다 늘지 않음. ④ 줄이 있고, `gone`이나 `failed`가 있으면 원인 줄이 짝으로 있음: HTTP 답이 있었으면 `fcm_send_status`, 시간 초과·연결 오류만이면 `fcm_send_error`. `auth`면 `fcm_auth_failed`(1시간 한 번이라 짝이 없을 수 있음). 개수만 PR에 적음 | |
| TC-726 | 7일 관찰 | REQ-631, SPEC-511, REQ-630 | ops | 반영 뒤 7일 저널(`marong-app.service`), `marong.app_devices` | `fcm_send_status` 줄을 `http`·`code`·`result`별로 셈. 같은 기간 새로 채워진 `dropped_at` 수를 SELECT `count(*)`로 셈 | 새 `dropped_at` 수가 `http=404 code=UNREGISTERED result=gone` 줄 수보다 크지 않음(`drop_fid`는 보낸 FID가 그 줄과 같을 때만 지우니 작을 수 있음). `result=gone`인 줄은 모두 `http=404 code=UNREGISTERED`. 개수 표를 '11단계 진행'에 적음. 400이 같은 폰에 되풀이되면 '설계 질문'에 적음(설치 ID·FID 없이 개수만) | |
| TC-727 | 정말 틀린 FID가 계속 실패하는지 | REQ-630, REQ-631, SPEC-511, D183(질문 2의 반대 논거) | ops | 반영 뒤 7일 저널(`marong-app.service`), `marong.app_update_events` | ① `fcm_send_status` 줄 가운데 `http=400`을 날짜·`kind`·`code`별로 셈 ② 같은 기간 업데이트 기록에서 같은 폰·같은 버전 코드의 `push_failed`(`status` 500)가 시도 3까지 간 폰 수를 SELECT `count(*)`로 셈(폰을 가르는 값은 SQL 안에서만 쓰고 출력하지 않음) | 개수 표를 '11단계 진행'에 적음. `http=400` 줄이 7일 내내 날마다 있거나 ②가 1 이상이면, 정말 틀린 FID가 계속 실패하는 신호로 보고 '설계 질문'에 개수만 적어요. 이 설계 스레드가 FID를 지울 조건을 다시 여쭤요(01 도메인 5.4 첫 줄, 04 3.4) | |
| TC-728 | 등록 만료로 '앱 지워짐'이 잘못 보인 폰 | REQ-630, admin TERM-242, D185(질문 4의 반대 논거) | ops | 반영 뒤 7일, `marong.app_update_events`, `marong.app_devices` | 업데이트 기록의 `push_failed`(`status` 410, 등록 해제 답) 가운데 반영 뒤 생긴 줄을 같은 `install_id`의 지금 기기 줄과 SQL 안에서 이어, `dropped_at`이 비어 있고 `seen_at`이 그 410보다 늦은 폰 수를 SELECT `count(*)`로 셈 | 개수를 '11단계 진행'에 적음. 같은 설치 ID로 다시 보고한 폰은 앱(과 앱 데이터)을 지우지 않은 폰이라(앱을 다시 깔면 설치 ID가 새로 생김, admin SPEC-460) '앱 지워짐'이 잠시 잘못 보인 경우예요. 1 이상이면 '설계 질문'에 개수만 적고 문구('앱 지워짐', D146·D185)를 다시 여쭤요. 글 알림·벨의 등록 해제는 기록 표가 없어 이 시험으로 세지 못해요 | |

## 범위 확인

| SPEC·REQ | TC |
| --- | --- |
| SPEC-510 | TC-720, TC-126(바뀜), TC-725 |
| SPEC-511 | TC-721, TC-725, TC-726, TC-727 |
| SPEC-512 | TC-722, TC-723, TC-724 |
| REQ-630 | TC-720, TC-722, TC-723, TC-724, TC-726, TC-727, TC-728 |
| REQ-631 | TC-721, TC-726, TC-727 |

- 체크포인트 답의 반대 논거 둘은 TC-727(D183, 정말 틀린 FID)과 TC-728(D185, 등록 만료)로 지켜봐요.
- 모든 SPEC 행의 받아들임 조건이 TC에 있어요. 04 3.1 표의 열 줄은 TC-720, 3.2 표는 TC-721, 3.3 표의 줄 넷은 TC-722\~724에 있어요.
- 다른 패키지의 지금 시험은 회귀로 그대로 돌려요: `tests/test_app_chat.py` 전체, `tests/test_app_update_push.py`(TC-599·600은 가짜 FCM이 결과 이름을 바로 돌려줘 이 변경과 상관없이 그대로 통과해야 함), 선 전화·벨을 쓰는 `tests/` 시험. 목록은 [README.md '시험(노트북)'](../../README.md)에 있어요.
