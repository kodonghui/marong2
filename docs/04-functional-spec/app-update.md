# 마롱이 앱 자동 업데이트: 기능 명세

상태: 초안(2026-11-17 13시대 KST, Claude, corthex 0.12.1). 명세 동결 전이에요. 확인 질문 1\~3(요구사항 '열린 질문')은 D63(2026-11-17 15:15 KST)으로 추천안대로 정해졌어요.
입력: [요구사항](../02-prd/app-update.md) REQ-306\~326, [사용자 흐름](../03-user-flow/) FL-146\~148, [도메인](../01-domain/app-update.md)의 CTX-021·TERM-092\~100, 앱 설계([docs/android-app.md](../android-app.md)), 글 대화 설계([docs/app-chat.md](../app-chat.md))의 SPEC-110(글 대화 서버)과 SCR-109.
뒤 단계: 05 단계는 DB 표 없이 서버 폴더(3.1), 06 API는 `api/app-update.openapi.yaml`, 08 화면 상태는 `docs/08-screens/app-update.md`가 이 SPEC 번호를 따라가요.

## 1. 모든 행에 공통인 규칙

- 어디서 도나: 서버 쪽은 디스코드 DM 봇 프로세스 안의 글 대화 서버(`marong/app_chat.py`, aiohttp, `127.0.0.1`, 터널이 `^/chat(/|$)`만 보냄)에 주소 두 개를 더하고, 릴리스 폴더 읽기는 새 모듈 `marong/app_release.py`에 둬요. 올리기 도구는 서버의 `tools/app_release.py`이고 노트북에서는 `bash deploy/ovh.sh app-release …`로 불러요. 앱 쪽은 새 클래스 `AppUpdate`(규칙, 안드로이드 없이 JVM 시험), `AppUpdateJob`(받기·설치), `AppUpdateReceiver`(설치 결과와 업데이트 뒤)예요 [사실: `marong/app_chat.py`, `deploy/ovh.sh`, `apps/android`, 2026-11-17 읽음].
- 스위치: 서버는 글 대화 서버가 켜져 있으면(`MARONG_APP_CHAT=1`, SPEC-110) 늘 두 주소를 열어요. 릴리스 폴더에 릴리스가 없거나 멈춤 표시가 있으면 '새 버전 없음'이라 앱은 아무것도 받지 않아요(REQ-307). 따로 켜는 설정은 두지 않아요.
- 버전: 비교는 버전 코드(정수)로만 해요. 버전 이름은 사람이 보는 글이에요(TERM-094, TERM-095).
- 시각: 저장은 UTC 밀리초(앱)·ISO 8601 UTC(서버)예요.
- 로그: 서버는 `app_release` 줄에 버전 코드·버전 이름·결과만 남기고 친구 이름·이메일·기기 id는 남기지 않아요(REQ-312). 앱 로그(`MarongUpdate`)도 버전과 결과만이고, 쿠키·주소의 질의 글은 남기지 않아요.
- 확실도 표시: [사실] 문서나 코드에서 확인, [추정] 근거 있는 짐작, [확인 필요] 실기기나 실제 계정에서 봐야 함.

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-284 | 릴리스 폴더 읽기(서버) | REQ-306, REQ-307 | API-141·142 요청마다 | 릴리스 폴더(3.1)의 `release.json`을 읽어요. 칸이 모두 맞고(3.1의 형식), 그 APK 파일이 있고 크기가 같으며, `paused` 파일이 없을 때만 '최신 릴리스'예요. 요청마다 읽어서 올리거나 멈춘 뒤 봇을 다시 시작하지 않아도 돼요 | 폴더·파일 없음 → 릴리스 없음<br>JSON이 틀리거나 칸이 틀림, APK 없음·크기 다름 → 릴리스 없음, 로그 `app_release invalid` 한 줄(같은 내용이면 10분에 한 번) | 시험: 정상·없음·멈춤·틀린 JSON·크기 다름 다섯 경우에서 맞는 결과 | active |
| SPEC-285 | 최신 릴리스 알려 주기(API-141) | REQ-306, REQ-307, REQ-312, FL-147 | Access로 확인된 친구(글 대화의 `_who`와 같은 Access·허용 목록 확인. 디스코드 DM 연결 확인은 빼요: 업데이트는 DM과 상관없음) | `GET /chat/api/app/release` → 최신 릴리스가 있으면 200 `{"versionCode", "versionName", "size", "sha256", "url"}`, `url`은 `/chat/app/<파일 이름>`이에요. 없으면 204(본문 없음). `Cache-Control: no-store` | Access 없음 → 401 `unauthenticated`, 허용 목록에 없거나 꺼진 친구 → 403 `not_allowed`, Access 키·DB에 닿지 않음 → 503 `db_unavailable`(글 대화와 같음)<br>폴더를 읽다 오류 → 204, 로그 | 시험: 200 본문 칸과 값, 204, 401·403 | active |
| SPEC-286 | APK 내보내기(API-142) | REQ-308, REQ-312, FL-147 | Access로 확인된 친구(SPEC-285와 같은 확인) | `GET /chat/app/{file}` → `file`이 지금 최신 릴리스의 파일 이름과 같을 때만 그 APK를 `application/vnd.android.package-archive`로 내보내요(파일을 나눠 읽어 보냄, `Content-Length`, `Cache-Control: no-store`). 로그 `app_release apk sent code=<버전 코드>` | 이름 형식(`marong-<버전 이름>-<버전 코드>.apk`)이 아님, 최신이 아님, 멈춤, 릴리스 없음 → 404 `no_release`<br>`..`·`/`가 든 이름 → 404<br>401·403·503은 SPEC-285와 같음 | 시험: 최신 파일 200·바이트 같음, 옛 파일·다른 이름·경로 넘기 404 | active |
| SPEC-287 | 새 버전 올리기(도구) | REQ-309, REQ-310, FL-146 | 노트북에서 서명한 APK와 같은 폴더의 `output-metadata.json`(Gradle이 씀) | 노트북: `bash deploy/ovh.sh app-release publish <APK 경로>`가 메타데이터에서 패키지 이름·버전 코드·버전 이름을 읽어 APK와 함께 서버 임시 폴더로 보내고 서버 도구를 불러요. 서버: `tools/app_release.py publish --apk … --package … --version-code … --version-name …`가 ① 패키지 이름이 `com.corthexhq.marong`인지 ② APK가 zip이고 `AndroidManifest.xml`과 `META-INF/`의 서명 파일이 있는지 ③ 버전 코드가 지금 `release.json`의 버전 코드보다 큰지 보고, 크기와 SHA-256을 계산해 APK를 `marong-<버전 이름>-<버전 코드>.apk`로 넣은 뒤 `release.json`을 임시 파일에 쓰고 이름을 바꿔 한 번에 바꿔요. 멈춤 표시(`paused`)가 있으면 지워요. 끝나면 새 릴리스의 버전·크기·SHA-256을 보여 줘요 | ①\~③ 하나라도 아님 → 거절, 서버 폴더 그대로, 이유를 보여 줌(종료 코드 2)<br>메타데이터 없음 → 노트북에서 거절<br>옛 APK 파일은 지우지 않고 최근 3개만 남겨요 | 시험: 정상 올리기 뒤 API-141이 새 값, 같은·낮은 버전 코드 거절, 다른 패키지 거절, zip이 아님 거절, 멈춤이 풀림, 네 번째 올리기에서 가장 옛 파일이 지워짐 | active |
| SPEC-288 | 멈추기·다시 켜기·상태(도구) | REQ-311, FL-146 | 서버 | `app_release.py pause`는 `paused` 파일을 만들고, `resume`은 지워요. `status`는 최신 릴리스(버전 코드·이름·크기·SHA-256 앞 16자·올린 때)와 멈춤 여부를 보여 줘요. 노트북에서는 `bash deploy/ovh.sh app-release pause|resume|status` | 릴리스가 없을 때 `pause`·`resume`도 성공(표시만 바꿈) | 시험: 멈춤이면 API-141 204, 다시 켜면 200 | active |
| SPEC-289 | 확인 차례(앱) | REQ-313, FL-147 | 앱이 깔려 있음 | 이때 확인 작업(`AppUpdateJob`, JobScheduler, 네트워크 필요)을 잡아요. ① 앱 창(MainActivity, ChatActivity)이 화면에 나올 때 ② FCM 데이터 메시지가 앱의 수신 콜백에 들어왔을 때(예: 벨). 백그라운드 선톡처럼 알림과 데이터가 함께 든 메시지는 알림함으로 가고, 알림을 눌러 창이 열릴 때 ①을 따름 ③ 하루 한 번 되풀이 작업(24시간, 위 둘 때와 업데이트 뒤에 다시 잡음). 작업은 마지막 확인에서 6시간이 지나지 않았으면 묻지 않고 끝나요(받아 둔 파일이 있으면 SPEC-294로 감) | JobScheduler가 거절 → 다음 차례에 다시. 안드로이드가 작업을 늦추는 것(절전)은 그대로 둠 | JVM 시험: 6시간 규칙(5시간 59분 아니오, 6시간 예, 시계가 뒤로 감이면 예) | active |
| SPEC-290 | 최신 릴리스 묻기(앱) | REQ-313, REQ-315, REQ-316, FL-147 | SPEC-289에서 6시간이 지남 | 앱 주소(`capacitor.config.json`의 `server.url`)에 `/chat/api/app/release`를 붙여 GET해요. 웹뷰가 가진 그 주소의 쿠키(`CookieManager`)를 `Cookie`로 보내고, 다른 헤더는 사용자 에이전트(`MarongApp/<버전 이름>`)와 `Accept`뿐이에요. 넘겨주기(3xx)는 따라가지 않아요. 시간 제한 연결 15초·읽기 30초. 응답을 받으면(200·204) 마지막 확인 시각을 적어요 | 3xx(로그인이 끝남), 401·403 → 이번엔 끝, 실패로 세지 않음, 로그 `update_check signed_out`<br>그 밖의 오류·시간 초과 → 이번엔 끝, 확인 시각을 적지 않음<br>200인데 칸이 틀림(정수 아님, SHA-256이 64자 16진수 아님, `url`이 `/chat/app/`로 시작하지 않거나 `..`·`//`·`?`가 있음) → 없는 것으로 봄 | JVM 시험: 응답 해석(정상, 틀린 칸들, 다른 호스트 주소 거절) | active |
| SPEC-291 | APK 받기(앱) | REQ-314, REQ-315, REQ-318, FL-147 | SPEC-290의 버전 코드가 지금 앱보다 크고, 그 버전의 실패가 3번 미만 | 앱 주소 + `url`에서 쿠키를 붙여 받아 앱 캐시 폴더 `update/marong-<버전 코드>.apk.part`에 쓰고, 다 받으면 `.apk`로 이름을 바꿔요. 같은 버전 코드의 `.apk`가 이미 있고 SPEC-292를 통과했으면 다시 받지 않아요. 받는 중 크기가 릴리스 `size`를 넘으면 멈춰요. 받기 전에 그 버전이 아닌 옛 파일은 지워요 | 받기 실패·시간 초과·크기 넘침 → `.part` 지움, 실패 1번(SPEC-293) | 에뮬레이터: 5MB APK를 받음, 같은 버전을 두 번 받지 않음 | active |
| SPEC-292 | 받은 파일 확인(앱) | REQ-317, FL-147 | SPEC-291이 끝남 | 모두 맞아야 해요. ① 파일 크기가 `size`와 같음 ② SHA-256(16진수 소문자)이 `sha256`과 같음 ③ `PackageManager.getPackageArchiveInfo`로 읽은 패키지 이름이 이 앱과 같음 ④ 그 버전 코드가 지금 앱보다 크고 릴리스의 `versionCode`와 같음 ⑤ 그 서명 인증서 목록(안드로이드 9 이상 `GET_SIGNING_CERTIFICATES`, 그 아래 `GET_SIGNATURES`)의 SHA-256 집합이 지금 깔린 앱의 것과 같음 | 하나라도 아님 → 파일 지움, 실패 1번, 로그 `update_verify fail=<번호>` | JVM 시험: ①②④ 규칙과 인증서 모음 비교. 에뮬레이터: 다른 키로 서명한 APK를 거절 | active |
| SPEC-293 | 실패 세기(앱) | REQ-318 | SPEC-291·292·297의 실패 | 앱 설정(`SharedPreferences` `marong_update`)에 버전 코드별 실패 횟수를 적어요. 3번이면 그 버전 코드는 받지 않아요. 더 큰 버전 코드가 오면 옛 기록을 지워요 | | JVM 시험: 3번째 실패 뒤 같은 버전 건너뜀, 새 버전이면 다시 받음 | active |
| SPEC-294 | 조용한 때 판단과 미루기(앱) | REQ-319, FL-147 | 확인을 통과한 파일이 있음 | 통화 알림 101·벨 알림 201이 없고, 사용자가 볼 수 있는 이 앱의 창이 없을 때만 설치해요. 앱의 Activity 창을 자신을 연 작업에 관계없이 확인해요. 화면이 꺼졌거나 잠금 화면이 일반 앱 창을 가린 상태에서는 일반 창을 표시 중으로 세지 않아요. 잠금 위에 표시되는 벨 창과 통화·벨 알림은 계속 확인해요. 설치 전과 커밋 직전에 확인해요. 조용하지 않으면 네트워크 없는 14분 예비 작업에 더해 Android가 보관하는 비정밀 절전 허용 알람을 2분 뒤 요청해요. 알람은 설치 전용 작업을 예약하고, 후보가 남아 있으면 다음 알람을 5분 뒤 요청해요. 설치 작업에서 계속 조용하지 않으면 APK를 다시 읽기 전에 끝내요. 앱 창이 내려가거나 통화·벨이 끝날 때는 UI 스레드 밖에서 빠른 설치를 요청하고 필요하면 900ms 뒤 재확인해요 | 예비 작업 등록의 성공 여부와 무관하게 빠른 설치와 알람을 사용할 수 있어요. OS가 알람·작업 실행을 늦출 수 있어요. 설치 요청·후보 폐기 때 알람을 정리하고 OS가 중단한 일반 예비 작업은 기존 15분 선형 백오프를 사용해요 | Android 16: 사용 중 이전 버전 유지, 마지막 조건 해제 뒤 앱을 열거나 설치 작업을 강제로 실행하지 않고 15분 안에 설치 완료(TC-222, BUG-112). 앱 프로세스 회수와 잠금도 확인해요 | active |
| SPEC-295 | 설치 요청(앱) | REQ-320, FL-147 | SPEC-294가 조용함 | `PackageInstaller` 세션(`MODE_FULL_INSTALL`, `setAppPackageName`)을 만들고 안드로이드 12 이상이면 `setRequireUserAction(USER_ACTION_NOT_REQUIRED)`를 걸어요. 파일을 세션에 쓰고, 결과를 `AppUpdateReceiver`로 받는 브로드캐스트 `PendingIntent`로 커밋해요. 같은 버전의 세션이 이미 있으면 그 세션을 버리고 새로 만들어요 | 세션을 만들거나 쓰다 오류 → 세션 버림, 실패 1번 | 에뮬레이터(안드로이드 16): 설치 허용을 켠 상태에서 확인 창 없이 설치됨 | active |
| SPEC-296 | 사용자 확인 알림(앱) | REQ-321, FL-148 | SPEC-297이 `STATUS_PENDING_USER_ACTION`을 받음 | 이 버전 코드로 알림을 띄운 적이 없으면 알림 SCR-130(새 채널 `marong_update` '앱 업데이트', 중요도 낮음, 3.3의 글)을 띄워요. 누르면 안드로이드가 준 확인 화면(`EXTRA_INTENT`)이 열려요. 띄운 버전 코드를 적어요 | 알림 권한이 꺼짐 → 띄우지 않음(로그만). 다음 확인 차례에 설치를 다시 요청 | 에뮬레이터: 설치 허용을 끈 상태에서 알림 한 번, 누르면 허용 설정 → 업데이트 확인 창 | active |
| SPEC-297 | 설치 결과 받기(앱) | REQ-318, REQ-321, REQ-324 | 설치 세션의 결과 브로드캐스트 | `STATUS_SUCCESS` → 받아 둔 파일과 실패 기록을 지움, 알림 없음(REQ-324). `STATUS_PENDING_USER_ACTION` → SPEC-296. 그 밖의 실패 → 파일 지움, 실패 1번, 로그 `update_install fail=<상태 번호>` | 결과가 오기 전에 앱이 바뀌면 SPEC-298이 정리 | JVM 시험: 상태 번호별 처리 | active |
| SPEC-298 | 업데이트 뒤 다시 맞추기(앱) | REQ-322, REQ-323 | 새 버전이 깔림(`ACTION_MY_PACKAGE_REPLACED`) | 알림 채널을 다시 만들고(`Channels.ensure`), 하루 한 번 확인 작업을 다시 잡고, 받아 둔 파일·띄운 알림 기록·지금 버전 이하의 실패 기록을 지워요. 로그인 쿠키, 알림·벨 설정, FCM 설치 id는 건드리지 않아요(업데이트 설치는 앱 데이터를 그대로 둠) | | 에뮬레이터: 업데이트 뒤 글 대화가 로그인 없이 열리고 벨 시험이 울림 | active |
| SPEC-299 | 앱 매니페스트 | REQ-316, REQ-320 | 빌드 | 권한 `REQUEST_INSTALL_PACKAGES`와 `UPDATE_PACKAGES_WITHOUT_USER_ACTION`을 더해요. `AppUpdateJob`(`BIND_JOB_SERVICE`, 내보내지 않음), `AppUpdateReceiver`(내보내지 않음, `MY_PACKAGE_REPLACED`)를 더해요. 버전은 0.2.2(버전 코드 5) 그대로예요(이 기능은 아직 어느 폰에도 깔리지 않은 0.2.2에 넣음) | | `npm test`의 합친 권한 목록 시험(TC-133)을 13개로 고침 | active |
| SPEC-300 | 글 대화 메뉴의 자동 업데이트 줄 | REQ-325, REQ-326, FL-148 | 글 대화 메뉴(SCR-109)를 엶 | 앱 연결 `MarongPush.state()`에 `installUpdates`(true·false, 안드로이드 8 미만이면 줄 없음)가 있을 때만 '자동 업데이트' 줄을 보여요. true면 '자동 업데이트: 켜짐', false면 '자동 업데이트: 꺼짐 · 켜 두면 새 버전이 저절로 깔려'와 '켜기' 단추예요. '켜기'는 `MarongPush.openInstallSettings()`를 불러요. 설정에서 돌아오면(`resumed`) 다시 읽어요 | 옛 앱(0.2.1)·브라우저 → 줄 없음(REQ-326) | 브라우저 시험: 세 경우(없음, 켜짐, 꺼짐)와 단추 | active |
| SPEC-301 | 앱 연결 더하기 | REQ-325 | | `MarongPush.state()`에 `installUpdates`(`PackageManager.canRequestPackageInstalls()`, 안드로이드 8 이상)를 더하고, `openInstallSettings()`(`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`, 이 앱 패키지)를 더해요. 서버 기기 보고(API-105)는 바꾸지 않아요 | 설정 화면이 없는 폰 → 앱 정보 화면(지금 `open()`과 같음) | JVM 시험 없음(안드로이드 API), 에뮬레이터에서 단추가 설정을 엶 | active |
| SPEC-302 | 서버 반영 | REQ-306, REQ-308 | 구현·반영은 GPT 몫(동희님 2026-11-17 12:38 "구현은 지피티 시킬거임"). 반영 규칙은 상시 허락(2026-11-15 19:58 "만들어지는대로 계속 넣어")과 같아요 | 봇 파일(`marong/app_chat.py`, `marong/app_release.py`, `marong/app_chat_static/chat.js`, `tools/app_release.py`)을 반영하고 릴리스 폴더를 만들어요(소유 `marong`, 0750). 봇 재시작은 조용할 때(최근 5분 친구 말 없음, 진행 중 통화 0). 되돌리기 스크립트를 함께 둬요 | | 반영 뒤 API-141이 204(릴리스 없음), 로그 오류 0 | active |

## 3. 자세한 규칙

### 3.1 릴리스 폴더

- 위치: 서버 설정 `MARONG_APP_RELEASES_DIR`, 없으면 `/var/lib/marong/app-releases`. 봇 사용자 `marong`만 쓰고 읽어요.
- `release.json`:

```json
{
  "format": 1,
  "package": "com.corthexhq.marong",
  "versionCode": 6,
  "versionName": "0.2.3",
  "file": "marong-0.2.3-6.apk",
  "size": 5040000,
  "sha256": "64자 16진수 소문자",
  "publishedAt": "2026-11-17T05:00:00Z"
}
```

- 형식: `format`은 1, `package`는 `com.corthexhq.marong`, `versionCode`는 1 이상 2100000000 이하 정수(안드로이드의 최댓값), `versionName`은 `^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$`, `file`은 `marong-<versionName>-<versionCode>.apk`와 똑같음, `size`는 1 이상 정수(200MB 이하), `sha256`은 `^[0-9a-f]{64}$`.
- `paused`: 내용 없는 파일. 있으면 멈춤이에요.
- APK 파일은 최근 3개만 남아요(SPEC-287).

### 3.2 올리기 도구

| 명령(노트북) | 서버에서 하는 일 | 결과 |
| --- | --- | --- |
| `bash deploy/ovh.sh app-release publish <APK>` | APK·메타데이터를 임시 폴더로 보내고 `app_release.py publish` | 새 릴리스 한 줄, 또는 거절 이유 |
| `bash deploy/ovh.sh app-release status` | `app_release.py status` | 최신 릴리스와 멈춤 여부 |
| `bash deploy/ovh.sh app-release pause` / `resume` | `paused` 만들기·지우기 | 멈춤·다시 켬 |

`output-metadata.json`은 Gradle이 APK 옆에 쓰는 파일이에요(`applicationId`, `elements[0].versionCode`, `versionName`, `outputFile`). `outputFile`이 받은 APK 이름과 다르면 거절해요.

### 3.3 알림 글(SCR-130)

- 채널: `marong_update`, 이름 '앱 업데이트', 설명 '마롱이 앱 새 버전을 깔 때 확인이 필요하면 알려 줘요.', 중요도 낮음(소리 없음).
- 제목: '마롱이 앱 새 버전이 있어요', 본문: '눌러서 업데이트해 줘. (<버전 이름>)'. 잠금 화면에는 제목만(`VISIBILITY_PRIVATE`와 공개 버전 '마롱이 앱 새 버전').
- 누르면 사라져요(`autoCancel`). 알림 id 301.

### 3.4 앱 업데이트 상태(`SharedPreferences` `marong_update`)

| 키 | 뜻 |
| --- | --- |
| `checkedAt` | 마지막으로 서버 답(200·204)을 받은 때 |
| `fail.<버전 코드>` | 그 버전의 실패 횟수 |
| `notified` | 사용자 확인 알림을 띄운 마지막 버전 코드 |
| `release` | 받고 확인한 파일의 버전 코드, 크기, SHA-256(설치를 미루는 동안) |

## 4. 경우의 종류

| 상태 | 무엇이 보이나 | 다음 |
| --- | --- | --- |
| 새 버전 없음(204, 같은 버전) | 아무것도 없음 | 다음 확인 차례 |
| 로그인이 끝남(3xx·401·403) | 아무것도 없음 | 앱을 열어 로그인하면 그 뒤 확인 |
| 받는 중·확인 중 | 아무것도 없음 | SPEC-292 |
| 확인 실패 | 아무것도 없음(로그) | 3번까지 다시, 그 뒤 새 버전까지 쉼 |
| 받았고 조용하지 않음 | 아무것도 없음 | 마지막 보류 조건이 풀리면 빠른 설치, 14분 예비 작업 |
| 설치됨 | 다음에 열면 새 버전, 알림 없음 | 업데이트 뒤 다시 맞추기 |
| 사용자 확인 필요 | 알림 SCR-130(버전마다 한 번) | 누르면 안드로이드 확인 창 |
| 사용자가 취소 | 아무것도 없음 | 다음 확인 차례에 설치를 다시 요청(알림 없이) |

## 5. AI 호출

없음.

## 6. 요구사항 없이 생긴 동작

- 옛 APK를 최근 3개만 남기기(SPEC-287): 디스크를 아끼려는 새 제안이에요. 앱은 최신만 받으니 옛 파일은 기록용이에요.
- 설치 예비 작업(SPEC-294): 14분 작업 기한과 별도로 OS가 보관하는 비정밀 알람을 사용해 앱 프로세스가 회수된 뒤에도 재시도할 수 있어요. 2분으로 설정해 15분 시험 기준 안에 Android의 실행 지연과 설치에 여유를 둬요. [Android 알람 예약](https://developer.android.com/develop/background-work/services/alarms), [Android 전원 관리 제한](https://developer.android.com/topic/performance/power/power-details#resource-limits)
- 0.2.2 안에 넣기(SPEC-299): 0.2.2는 서명 전이고 어느 폰에도 없어서 버전 코드를 올리지 않아요.

## 7. 실기기·실계정에서 확인할 것

- 현경님 폰의 안드로이드 버전과, 설치 허용을 켠 뒤 확인 창 없이 설치되는지 [확인 필요].
- 삼성 '자동 차단'이 켜진 폰에서의 동작 [확인 필요].
- 절전에 들어간 앱에서 하루 한 번 작업이 실제로 도는지(삼성 '잠자는 앱') [확인 필요].
- Access 로그인이 끝난 뒤 쿠키 없이 묻는 요청이 3xx로 오는지 [추정: 지금 글 대화가 같은 경우를 opaque 응답으로 다룸].
