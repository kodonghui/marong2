# 마롱이 앱 자동 업데이트: 기능 명세

상태: 초안(2026-11-17 13시대 KST, Claude, corthex 0.12.1). 명세 동결 전이에요. 확인 질문 1\~3(요구사항 '열린 질문')은 D63(2026-11-17 15:15 KST)으로 추천안대로 정해졌어요.
기능 변경(2026-11-22, Claude 마롱이 봇): 게시 즉시 업데이트·업데이트 상태 보고·릴리스 노트·업데이트 UX. 바뀐 행은 SPEC-287·296·298·301·302와 3.1·3.2·3.4·7절이고 새 행은 [8절](#8-2026-11-22-기능-변경-게시-즉시-업데이트와-업데이트-상태)의 SPEC-430\~443이에요. SPEC-289·294와 4·6절은 버그 수정 PR #100(TC-222)이 같은 줄을 고치던 중이라 처음엔 8절(8.1, 8.8)에만 적었고, 두 PR이 합쳐진 뒤 2026-11-23에 행과 4·6절로 옮겼어요(TASK-488). 결정은 [도메인 9절](../01-domain/app-update.md#9-기능-변경2026-11-22-게시-즉시-업데이트와-업데이트-상태)의 D122\~D131과 D134예요. 2026-11-23 보안 검토로 승인된 SPEC-115(기기 등록, API-105)를 바꾸는 것 하나를 8.9에 더했고 D134로 승인됐어요. 체크포인트는 2026-11-23에 통과했어요([도메인 9.6](../01-domain/app-update.md#96-체크포인트2026-11-23)). 이 기능은 0.3.4(버전 코드 12)로 2026-11-23 16:41:32 KST에 게시됐어요(PR #110·#111·#112). 0.3.3(버전 코드 11)은 TC-222 고침만 담아 먼저 나간 릴리스예요(PR #106).
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
| SPEC-287 | 새 버전 올리기(도구) | REQ-309, REQ-310, REQ-557, REQ-558, FL-146 | 노트북에서 서명한 APK와 같은 폴더의 `output-metadata.json`(Gradle이 씀), 릴리스 노트(2026-11-22부터, SPEC-436) | 노트북: `bash deploy/ovh.sh app-release publish <APK 경로> --notes "<릴리스 노트>"`가 메타데이터에서 패키지 이름·버전 코드·버전 이름을 읽어 APK와 함께 서버 임시 폴더로 보내고 서버 도구를 불러요. 서버: `tools/app_release.py publish --apk … --package … --version-code … --version-name …`가 ① 패키지 이름이 `com.corthexhq.marong`인지 ② APK가 zip이고 `AndroidManifest.xml`과 `META-INF/`의 서명 파일이 있는지 ③ 버전 코드가 지금 `release.json`의 버전 코드보다 큰지 보고, 크기와 SHA-256을 계산해 APK를 `marong-<버전 이름>-<버전 코드>.apk`로 넣은 뒤 `release.json`을 임시 파일에 쓰고 이름을 바꿔 한 번에 바꿔요. 멈춤 표시(`paused`)가 있으면 지워요. 끝나면 새 릴리스의 버전·크기·SHA-256을 보여 줘요. 2026-11-22부터: ④ 릴리스 노트가 SPEC-436의 형식에 맞는지도 보고, `release.json`을 바꾸기 전에 같은 잠금 안에서 버전 기록(`history.json`, SPEC-437)에 한 줄을 써요(D127) | ①\~④ 하나라도 아님 → 거절, 서버 폴더 그대로, 이유를 보여 줌(종료 코드 2)<br>메타데이터 없음 → 노트북에서 거절<br>옛 APK 파일은 지우지 않고 최근 3개만 남겨요. 버전 기록의 줄은 지우지 않아요 | 시험: 정상 올리기 뒤 API-141이 새 값, 같은·낮은 버전 코드 거절, 다른 패키지 거절, zip이 아님 거절, 멈춤이 풀림, 네 번째 올리기에서 가장 옛 파일이 지워짐, 릴리스 노트 없음 거절과 버전 기록 한 줄(TC-611) | active |
| SPEC-288 | 멈추기·다시 켜기·상태(도구) | REQ-311, FL-146 | 서버 | `app_release.py pause`는 `paused` 파일을 만들고, `resume`은 지워요. `status`는 최신 릴리스(버전 코드·이름·크기·SHA-256 앞 16자·올린 때)와 멈춤 여부를 보여 줘요. 노트북에서는 `bash deploy/ovh.sh app-release pause|resume|status` | 릴리스가 없을 때 `pause`·`resume`도 성공(표시만 바꿈) | 시험: 멈춤이면 API-141 204, 다시 켜면 200 | active |
| SPEC-289 | 확인 차례(앱) | REQ-313, FL-147 | 앱이 깔려 있음 | 이때 확인 작업(`AppUpdateJob`, JobScheduler, 네트워크 필요)을 잡아요. ① 앱 창(MainActivity, ChatActivity)이 화면에 나올 때 ② FCM 데이터 메시지가 앱의 수신 콜백에 들어왔을 때(예: 벨). 백그라운드 선톡처럼 알림과 데이터가 함께 든 메시지는 알림함으로 가고, 알림을 눌러 창이 열릴 때 ①을 따름 ③ 하루 한 번 되풀이 작업(24시간, 위 둘 때와 업데이트 뒤에 다시 잡음) ④ 업데이트 데이터 메시지가 지금보다 높은 버전 코드를 알림 → 6시간 규칙 없이 SPEC-432(10분에 한 번까지, 2026-11-22부터, D123). 같거나 낮은 버전이거나 10분 안이면 ②로 가요(SPEC-432). ①\~③의 작업은 마지막 확인에서 6시간이 지나지 않았으면 묻지 않고 끝나요(받아 둔 파일이 있으면 SPEC-294로 감) | JobScheduler가 거절 → 다음 차례에 다시. 안드로이드가 작업을 늦추는 것(절전)은 그대로 둠 | JVM 시험: 6시간 규칙(5시간 59분 아니오, 6시간 예, 시계가 뒤로 감이면 예). ④는 SPEC-432의 10분 규칙 시험(TC-603) | active |
| SPEC-290 | 최신 릴리스 묻기(앱) | REQ-313, REQ-315, REQ-316, FL-147 | SPEC-289에서 6시간이 지남 | 앱 주소(`capacitor.config.json`의 `server.url`)에 `/chat/api/app/release`를 붙여 GET해요. 웹뷰가 가진 그 주소의 쿠키(`CookieManager`)를 `Cookie`로 보내고, 다른 헤더는 사용자 에이전트(`MarongApp/<버전 이름>`)와 `Accept`뿐이에요. 넘겨주기(3xx)는 따라가지 않아요. 시간 제한 연결 15초·읽기 30초. 응답을 받으면(200·204) 마지막 확인 시각을 적어요 | 3xx(로그인이 끝남), 401·403 → 이번엔 끝, 실패로 세지 않음, 로그 `update_check signed_out`<br>그 밖의 오류·시간 초과 → 이번엔 끝, 확인 시각을 적지 않음<br>200인데 칸이 틀림(정수 아님, SHA-256이 64자 16진수 아님, `url`이 `/chat/app/`로 시작하지 않거나 `..`·`//`·`?`가 있음) → 없는 것으로 봄 | JVM 시험: 응답 해석(정상, 틀린 칸들, 다른 호스트 주소 거절) | active |
| SPEC-291 | APK 받기(앱) | REQ-314, REQ-315, REQ-318, FL-147 | SPEC-290의 버전 코드가 지금 앱보다 크고, 그 버전의 실패가 3번 미만 | 앱 주소 + `url`에서 쿠키를 붙여 받아 앱 캐시 폴더 `update/marong-<버전 코드>.apk.part`에 쓰고, 다 받으면 `.apk`로 이름을 바꿔요. 같은 버전 코드의 `.apk`가 이미 있고 SPEC-292를 통과했으면 다시 받지 않아요. 받는 중 크기가 릴리스 `size`를 넘으면 멈춰요. 받기 전에 그 버전이 아닌 옛 파일은 지워요 | 받기 실패·시간 초과·크기 넘침 → `.part` 지움, 실패 1번(SPEC-293) | 에뮬레이터: 5MB APK를 받음, 같은 버전을 두 번 받지 않음 | active |
| SPEC-292 | 받은 파일 확인(앱) | REQ-317, FL-147 | SPEC-291이 끝남 | 모두 맞아야 해요. ① 파일 크기가 `size`와 같음 ② SHA-256(16진수 소문자)이 `sha256`과 같음 ③ `PackageManager.getPackageArchiveInfo`로 읽은 패키지 이름이 이 앱과 같음 ④ 그 버전 코드가 지금 앱보다 크고 릴리스의 `versionCode`와 같음 ⑤ 그 서명 인증서 목록(안드로이드 9 이상 `GET_SIGNING_CERTIFICATES`, 그 아래 `GET_SIGNATURES`)의 SHA-256 집합이 지금 깔린 앱의 것과 같음 | 하나라도 아님 → 파일 지움, 실패 1번, 로그 `update_verify fail=<번호>` | JVM 시험: ①②④ 규칙과 인증서 모음 비교. 에뮬레이터: 다른 키로 서명한 APK를 거절 | active |
| SPEC-293 | 실패 세기(앱) | REQ-318 | SPEC-291·292·297의 실패 | 앱 설정(`SharedPreferences` `marong_update`)에 버전 코드별 실패 횟수를 적어요. 3번이면 그 버전 코드는 받지 않아요. 더 큰 버전 코드가 오면 옛 기록을 지워요 | | JVM 시험: 3번째 실패 뒤 같은 버전 건너뜀, 새 버전이면 다시 받음 | active |
| SPEC-294 | 조용한 때 판단과 미루기(앱) | REQ-319, FL-147 | 확인을 통과한 파일이 있음 | 진행 중인 통화·통화 서비스·벨이 없고, 사용자가 볼 수 있는 이 앱의 창이 없을 때만 설치해요. 알림 101을 숨기거나 지워도 활성 통화와 서비스가 설치를 막아요. 앱의 Activity 창을 자신을 연 작업에 관계없이 확인해요. 화면이 꺼졌거나 잠금 화면이 일반 앱 창을 가린 상태에서는 일반 창을 표시 중으로 세지 않아요. 잠금 위에 표시되는 앱 창과 통화·벨 알림은 계속 확인해요. 설치 준비 전과 커밋 직전에 확인해요. 커밋의 마지막 확인은 앱 메인 스레드에서 후보 잠금 안의 설치 요청과 함께 처리해요. 조용하지 않으면 네트워크 없는 14분 예비 작업에 더해 Android가 보관하는 비정밀 절전 허용 알람을 2분 뒤 요청해요. 조용할 때 알람은 설치 전용 작업을 예약하고, 후보가 남아 있으면 5분 뒤 다시 확인할 알람을 남겨요. 조용하지 않으면 작업 2215를 예약하지 않고 다음 알람을 2분 뒤 요청해요. 사용이 끝날 때 잡히는 빠른 작업과 별도로, 이미 등록한 알람은 프로세스가 회수돼도 Android에서 대기해요. 설치 작업에서 계속 조용하지 않으면 APK를 다시 읽기 전에 끝내요. 앱 창이 내려가거나 통화·벨이 끝날 때는 UI 스레드 밖에서 빠른 설치를 요청하고 필요하면 900ms 뒤 재확인해요. '지금 설치'를 누른 때는 SPEC-441이에요(앱 창 조건을 보지 않는 예외, 2026-11-22부터, D128) | 예비 작업 등록의 성공 여부와 무관하게 빠른 설치와 알람을 사용할 수 있어요. OS가 알람·작업 실행을 늦출 수 있어요. 설치 요청·후보 폐기 때 알람을 정리하고 OS가 중단한 일반 예비 작업은 기존 15분 선형 백오프를 사용해요 | Android 16: 사용 중 이전 버전 유지, 마지막 조건 해제 뒤 앱을 열거나 설치 작업을 강제로 실행하지 않고 15분 안에 설치 완료(TC-222, BUG-112). 앱 프로세스 회수와 잠금도 확인해요 | active |
| SPEC-295 | 설치 요청(앱) | REQ-320, FL-147 | SPEC-294가 조용함 | `PackageInstaller` 세션(`MODE_FULL_INSTALL`, `setAppPackageName`)을 만들고 안드로이드 12 이상이면 `setRequireUserAction(USER_ACTION_NOT_REQUIRED)`를 걸어요. 파일을 세션에 쓰고, 결과를 `AppUpdateReceiver`로 받는 브로드캐스트 `PendingIntent`로 커밋해요. 같은 버전의 세션이 이미 있으면 그 세션을 버리고 새로 만들어요 | 세션을 만들거나 쓰다 오류 → 세션 버림, 실패 1번 | 에뮬레이터(안드로이드 16): 설치 허용을 켠 상태에서 확인 창 없이 설치됨 | active |
| SPEC-296 | 사용자 확인 알림(앱) | REQ-321, FL-148 | SPEC-297이 `STATUS_PENDING_USER_ACTION`을 받음 | 이 버전 코드로 알림을 띄운 적이 없으면 알림 SCR-130(새 채널 `marong_update` '앱 업데이트', 중요도 낮음, 3.3의 글)을 띄워요. 누르면 안드로이드가 준 확인 화면(`EXTRA_INTENT`)이 열려요. 띄운 버전 코드를 적어요. 2026-11-22부터: 알림과 함께 통화 홈과 글 대화의 업데이트 배너(SPEC-439, SPEC-443)도 받아 둔 파일이 있는 동안 늘 보여요(D129, 글 대화는 D131). 알림은 지금처럼 버전마다 한 번이에요 | 알림 권한이 꺼짐 → 띄우지 않음(로그만). 배너는 보임. 다음 확인 차례에 설치를 다시 요청 | 에뮬레이터: 설치 허용을 끈 상태에서 알림 한 번, 누르면 허용 설정 → 업데이트 확인 창 | active |
| SPEC-297 | 설치 결과 받기(앱) | REQ-318, REQ-321, REQ-324 | 설치 세션의 결과 브로드캐스트 | `STATUS_SUCCESS` → 받아 둔 파일과 실패 기록을 지움, 알림 없음(REQ-324). `STATUS_PENDING_USER_ACTION` → SPEC-296. 그 밖의 실패 → 파일 지움, 실패 1번, 로그 `update_install fail=<상태 번호>` | 결과가 오기 전에 앱이 바뀌면 SPEC-298이 정리 | JVM 시험: 상태 번호별 처리 | active |
| SPEC-298 | 업데이트 뒤 다시 맞추기(앱) | REQ-322, REQ-323 | 새 버전이 깔림(`ACTION_MY_PACKAGE_REPLACED`) | 알림 채널을 다시 만들고(`Channels.ensure`), 하루 한 번 확인 작업을 다시 잡고, 받아 둔 파일·띄운 알림 기록·지금 버전 이하의 실패 기록을 지워요. 로그인 쿠키, 알림·벨 설정, FCM 설치 id는 건드리지 않아요(업데이트 설치는 앱 데이터를 그대로 둠). 2026-11-22부터: 업데이트 상태 `installed`를 보고해요(SPEC-433, 앱 화면을 열지 않아도, D125) | 보고가 실패해도 다시 맞추기는 끝까지 함. 보고는 SPEC-433의 다시 보내기로 | 에뮬레이터: 업데이트 뒤 글 대화가 로그인 없이 열리고 벨 시험이 울림 | active |
| SPEC-299 | 앱 매니페스트 | REQ-316, REQ-320 | 빌드 | 권한 `REQUEST_INSTALL_PACKAGES`와 `UPDATE_PACKAGES_WITHOUT_USER_ACTION`을 더해요. `AppUpdateJob`(`BIND_JOB_SERVICE`, 내보내지 않음), `AppUpdateReceiver`(내보내지 않음, `MY_PACKAGE_REPLACED`)를 더해요. 버전은 0.2.2(버전 코드 5) 그대로예요(이 기능은 아직 어느 폰에도 깔리지 않은 0.2.2에 넣음) | | `npm test`의 합친 권한 목록 시험(TC-133)을 13개로 고침 | active |
| SPEC-300 | 글 대화 메뉴의 자동 업데이트 줄 | REQ-325, REQ-326, FL-148 | 글 대화 메뉴(SCR-109)를 엶 | 앱 연결 `MarongPush.state()`에 `installUpdates`(true·false, 안드로이드 8 미만이면 줄 없음)가 있을 때만 '자동 업데이트' 줄을 보여요. true면 '자동 업데이트: 켜짐', false면 '자동 업데이트: 꺼짐 · 켜 두면 새 버전이 저절로 깔려'와 '켜기' 단추예요. '켜기'는 `MarongPush.openInstallSettings()`를 불러요. 설정에서 돌아오면(`resumed`) 다시 읽어요 | 옛 앱(0.2.1)·브라우저 → 줄 없음(REQ-326) | 브라우저 시험: 세 경우(없음, 켜짐, 꺼짐)와 단추 | active |
| SPEC-301 | 앱 연결 더하기 | REQ-325 | | `MarongPush.state()`에 `installUpdates`(`PackageManager.canRequestPackageInstalls()`, 안드로이드 8 이상)를 더하고, `openInstallSettings()`(`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES`, 이 앱 패키지)를 더해요. 2026-11-22에 바뀜(D125, 승인된 글 "서버 기기 보고(API-105)는 바꾸지 않아요"): 기기 보고(API-105)에 선택 칸 `update`를 더해 업데이트 상태를 보내요(SPEC-433, SPEC-434). 앱 연결에는 `updateState()`·`installUpdate()`가 늘어요(SPEC-440) | 설정 화면이 없는 폰 → 앱 정보 화면(지금 `open()`과 같음) | JVM 시험 없음(안드로이드 API), 에뮬레이터에서 단추가 설정을 엶 | active |
| SPEC-302 | 서버 반영 | REQ-306, REQ-308 | 구현·반영은 GPT 몫(동희님 2026-11-17 12:38 "구현은 지피티 시킬거임"). 반영 규칙은 상시 허락(2026-11-15 19:58 "만들어지는대로 계속 넣어")과 같아요 | 봇 파일(`marong/app_chat.py`, `marong/app_release.py`, `marong/app_chat_static/chat.js`, `tools/app_release.py`)을 반영하고 릴리스 폴더를 만들어요(소유 `marong`, 0750). 봇 재시작은 조용할 때(최근 5분 친구 말 없음, 진행 중 통화 0). 되돌리기 스크립트를 함께 둬요. 2026-11-22 변경분은 구현·반영을 Codex가 하고, 서버를 앱보다 먼저 반영해요(SPEC-442) | | 반영 뒤 API-141이 204(릴리스 없음), 로그 오류 0 | active |

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
- `release.json`의 형식은 2026-11-22 변경에도 그대로예요(`format` 1). 릴리스 노트는 여기 넣지 않고 버전 기록에만 둬요(API-141과 앱에 가지 않게, REQ-554).
- `history.json`(버전 기록, TERM-222, 2026-11-22 새로): 형식은 8.3절이에요. 줄을 더하기만 하고 지우지 않아요.

### 3.2 올리기 도구

| 명령(노트북) | 서버에서 하는 일 | 결과 |
| --- | --- | --- |
| `bash deploy/ovh.sh app-release publish <APK> --notes "<릴리스 노트>"` | APK·메타데이터·릴리스 노트(`notes.txt`)를 임시 폴더로 보내고 `app_release.py publish --notes-file …`(2026-11-22부터 노트 필수, SPEC-436) | 새 릴리스 한 줄, 또는 거절 이유 |
| `bash deploy/ovh.sh app-release status` | `app_release.py status` | 최신 릴리스와 멈춤 여부 |
| `bash deploy/ovh.sh app-release pause` / `resume` | `paused` 만들기·지우기, 버전 기록에 한 줄(2026-11-22부터) | 멈춤·다시 켬 |
| `bash deploy/ovh.sh app-release history` | `app_release.py history`(2026-11-22 새로) | 버전 기록을 새것부터 |
| `bash deploy/ovh.sh app-release backfill` | `app_release.py backfill`(2026-11-22 새로, 처음 한 번) | 0.2.2\~0.3.2 줄을 `backfilled`로 넣음(SPEC-437) |

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
| `forcedAt` | 업데이트 데이터 메시지로 마지막 확인을 잡은 때(SPEC-432, 10분 규칙). 2026-11-22 새로 |
| `reported` | 서버에 마지막으로 보고한 버전 코드, 업데이트 상태, 상태 번호(SPEC-433, 셋이 모두 같은 것을 두 번 보내지 않게). 2026-11-22 새로 |
| `pendingReport` | 보내지 못한 업데이트 상태(버전 코드, 상태, 번호, 때). 보내면 지움. 2026-11-22 새로 |

## 4. 경우의 종류

| 상태 | 무엇이 보이나 | 다음 |
| --- | --- | --- |
| 새 버전 없음(204, 같은 버전) | 아무것도 없음 | 다음 확인 차례 |
| 업데이트 데이터 메시지를 받음(지금보다 높은 버전 코드, 마지막 강제 확인에서 10분이 지남) | 아무것도 없음 | 6시간 규칙 없이 확인(SPEC-432). 조건에 맞지 않으면 보통 확인 차례(SPEC-289 ②, 6시간 규칙) |
| 로그인이 끝남(3xx·401·403) | 아무것도 없음 | 앱을 열어 로그인하면 그 뒤 확인 |
| 받는 중·확인 중 | 아무것도 없음 | SPEC-292 |
| 확인 실패 | 아무것도 없음(로그) | 3번까지 다시, 그 뒤 새 버전까지 쉼 |
| 받았고 조용하지 않음(앱 창이 보이지 않음) | 아무것도 없음 | 마지막 보류 조건이 풀리면 빠른 설치, 14분 예비 작업 |
| 받았고 조용하지 않음(앱 창이 보임) | 통화 홈·글 대화의 업데이트 배너 '새 버전 준비됨 · 지금 설치'(SPEC-439, SPEC-443). 통화 홈은 통화 중에 띠를 숨겨요(08 SCR-001의 #in-call) | 조용해지면 설치(SPEC-294), 누르면 바로 설치(SPEC-441) |
| 설치됨 | 다음에 열면 새 버전, 알림 없음 | 업데이트 뒤 다시 맞추기 |
| 사용자 확인 필요 | 알림 SCR-130(버전마다 한 번)과 통화 홈·글 대화의 업데이트 배너 | 알림이나 배너를 누르면 안드로이드 확인 창 |
| 사용자가 취소 | 아무것도 없음 | 다음 확인 차례에 설치를 다시 요청(알림 없이) |
| 받아 둔 파일 없음, 자동 업데이트 꺼짐(설치 허용 꺼짐) | 통화 홈·글 대화의 업데이트 배너 '자동 업데이트 꺼짐 · 켜기'와 글 대화 메뉴 줄 | 누르면 안드로이드 설정 |

2026-11-22 기능 변경([8절](#8-2026-11-22-기능-변경-게시-즉시-업데이트와-업데이트-상태))에서 더하거나 바꾼 줄은 '업데이트 데이터 메시지를 받음', '받았고 조용하지 않음(앱 창이 보임)', '사용자 확인 필요', '받아 둔 파일 없음, 자동 업데이트 꺼짐'이에요. 원래 줄 '받았고 조용하지 않음'은 새 줄과 나누려고 '(앱 창이 보이지 않음)'을 붙였어요. 2026-11-23에 8.8에서 옮기면서, 업데이트 데이터 메시지 줄에는 SPEC-432의 조건을, 앱 창이 보이는 줄에는 08 SCR-001의 통화 중 숨김을 적었어요(TASK-488).

## 5. AI 호출

없음.

## 6. 요구사항 없이 생긴 동작

- 옛 APK를 최근 3개만 남기기(SPEC-287): 디스크를 아끼려는 새 제안이에요. 앱은 최신만 받으니 옛 파일은 기록용이에요.
- 설치 예비 작업(SPEC-294): 14분 작업 기한과 별도로 OS가 보관하는 비정밀 알람을 사용해 앱 프로세스가 회수된 뒤에도 재시도할 수 있어요. 2분으로 설정해 15분 시험 기준 안에 Android의 실행 지연과 설치에 여유를 둬요. [Android 알람 예약](https://developer.android.com/develop/background-work/services/alarms), [Android 전원 관리 제한](https://developer.android.com/topic/performance/power/power-details#resource-limits)
- 0.2.2 안에 넣기(SPEC-299): 0.2.2는 서명 전이고 어느 폰에도 없어서 버전 코드를 올리지 않아요.
- 감시 끄기 스위치 `MARONG_APP_UPDATE_PUSH=0`(SPEC-430): 되돌리기용이고 기본은 켜짐이에요. 2026-11-22 기능 변경의 새 제안이에요.
- 업데이트 데이터 메시지 보내기 실패를 3번까지 다시(SPEC-430), 상태 보고 다시 보내기 15분 간격·24시간까지(SPEC-433). 2026-11-22 기능 변경의 새 제안이에요.
- 버전 기록에 멈춤·다시 켜기도 쌓기(SPEC-437): 관리자가 언제 멈췄는지 보게 하려는 거예요. 2026-11-22 기능 변경의 새 제안이에요.
- 상한(2026-11-23 보안 검토, 새 제안): 감시는 친구마다 최근 20대만 고르고 한 차례 100개·동시 4개까지 보내요(SPEC-430). 관리자 읽기는 친구마다 20대·모두 200대·받아 감 100명까지예요(SPEC-438). 업데이트 기록은 버전 기록에 있는 버전만, 같은 상태를 되풀이하지 않고, 친구마다 1시간에 30줄, 받아 감은 친구·버전마다 1시간에 한 줄이고(SPEC-434·435), 1년이 지난 줄은 매달 정리해요(ERD 2절). 숫자는 추측이에요.

위 네 줄은 2026-11-23에 8.8에서 옮겼어요(TASK-488).

## 7. 실기기·실계정에서 확인할 것

- 현경님 폰의 안드로이드 버전과, 설치 허용을 켠 뒤 확인 창 없이 설치되는지 [확인 필요].
- 삼성 '자동 차단'이 켜진 폰에서의 동작 [확인 필요].
- 절전에 들어간 앱에서 하루 한 번 작업이 실제로 도는지(삼성 '잠자는 앱') [확인 필요].
- Access 로그인이 끝난 뒤 쿠키 없이 묻는 요청이 3xx로 오는지 [추정: 지금 글 대화가 같은 경우를 opaque 응답으로 다룸].
- 알림 없는 HIGH 데이터 메시지(SPEC-431)가 삼성 폰에서 몇 초 안에 닿는지, 벨 메시지가 늦어지지 않는지 [확인 필요](TC-614, TC-605).
- 삼성 폰에서 빠른 작업(SPEC-432)이 앱이 잠든 상태에서도 바로 도는지 [확인 필요](TC-615).
- 앱 자바 코드가 보낸 기기 보고(SPEC-433)가 웹 페이지 보고와 똑같이 받아지는지(`Origin`, 쿠키) [확인 필요: 에뮬레이터 TC-606, 실제 폰 TC-616].

## 8. 2026-11-22 기능 변경: 게시 즉시 업데이트와 업데이트 상태

입력: [요구사항](../02-prd/app-update.md#2026-11-22-기능-변경-게시-즉시-업데이트와-업데이트-상태) REQ-553\~561과 바뀐 REQ-313·316·319·321·325, [사용자 흐름](../03-user-flow/) FL-146\~148(바뀜)과 FL-193·194(새로), [도메인 9절](../01-domain/app-update.md#9-기능-변경2026-11-22-게시-즉시-업데이트와-업데이트-상태)의 D122\~D131·D134와 TERM-219\~224. 새 번호는 SPEC-430부터예요(저장소에서 가장 큰 번호 SPEC-429의 다음). 이 문서가 버전 기록(`history.json`), 업데이트 기록(TBL-182 `app_update_events`), 기기 보고의 `update` 칸, 관리자 읽기 API(API-267)의 형식을 정하는 한 곳이에요. 관리 페이지 다시 만들기는 이 형식을 읽기만 해요(오랑이 msg_013bfd28376b).

### 8.1 바뀐 행

| 행 | 바뀐 곳 | 승인된 글(2026-11-17) | 결정 |
| --- | --- | --- | --- |
| SPEC-287 | 릴리스 노트 필수(④), 버전 기록 한 줄 | "노트북: `bash deploy/ovh.sh app-release publish <APK 경로>`가 메타데이터에서 패키지 이름·버전 코드·버전 이름을 읽어 …" (명령에 노트가 없었음) | D127 |
| SPEC-289 | 확인 차례에 ④ '업데이트 데이터 메시지가 지금보다 높은 버전 코드를 알림 → 6시간 규칙 없이 SPEC-432(10분에 한 번까지)'가 늘어요. 2026-11-23에 행 글에 넣었어요(TASK-488) | "② FCM 데이터 메시지(벨)를 받았을 때 … 작업은 마지막 확인에서 6시간이 지나지 않았으면 묻지 않고 끝나요" | D123 |
| SPEC-294 | '지금 설치'를 누른 때만 ③(앱 창이 보임)을 보지 않는 예외를 SPEC-441에 적었어요. 2026-11-23에 행 끝에 SPEC-441을 가리키는 글을 넣었어요(TASK-488) | "조용하다 = ① … ② … ③ 이 앱 프로세스의 중요도가 '보이는 화면'보다 낮음" | D128 |
| SPEC-296 | 알림과 함께 통화 홈·글 대화 배너도 보임 | "이 버전 코드로 알림을 띄운 적이 없으면 알림 SCR-130 … 을 띄워요" | D129, D131 |
| SPEC-298 | 업데이트 뒤 `installed` 보고 | "알림 채널을 다시 만들고 … 로그인 쿠키, 알림·벨 설정, FCM 설치 id는 건드리지 않아요" | D125 |
| SPEC-301 | 기기 보고에 `update` 칸, 앱 연결 둘 더하기 | "서버 기기 보고(API-105)는 바꾸지 않아요" | D125 |
| SPEC-302 | 변경분 반영 순서 | "봇 파일 … 을 반영하고 릴리스 폴더를 만들어요" | D127(Codex 구현은 동희님 상시 방식) |
| SPEC-115(docs/app-chat.md) | 새 폰 상한: 그 친구에게 30일 안에 보고한 폰이 이미 20대이고 이 installId가 그 가운데 없으면 409 `too_many_devices`(8.9). docs/app-chat.md의 행 글을 고쳤어요 | "없으면 만들고(201) 있으면 고치고(200), `seen_at`을 지금으로 적어요"(2026-11-15 D17·D18로 만들고 2026-11-16 반영) | D134 |

- SPEC-289·294 행과 4절 '받았고 조용하지 않음' 줄, 6절 '15분 뒤 다시 보기' 줄(지금은 '설치 예비 작업' 줄)은 버그 수정 PR #100(BUG-112, TC-222 '15분 기준 미충족', Orca 마롱이 항목 4의 Codex 작업)이 함께 고쳤어요. 두 PR이 같은 줄을 고치면 합칠 때 부딪혀서, 이 변경은 처음에 그 줄을 그대로 두고 바뀐 것을 SPEC-432·441과 8.8에 적었어요. PR #100이 '② 데이터 메시지'를 '앱의 수신 콜백에 들어온 데이터 메시지(예: 벨)'로 좁혀 적은 것도 이 변경과 같은 뜻이에요. 이 변경(PR #101)과 PR #100(`5634406`)이 모두 합쳐진 뒤 2026-11-23에 SPEC-289 행에 ④를, SPEC-294 행 끝에 "'지금 설치'를 누른 때는 SPEC-441"을 더하고 8.8을 4·6절로 옮겼어요(TASK-488).
- SPEC-284(릴리스 폴더 읽기)는 바뀌지 않아요. `release.json` 형식이 그대로이고, 감시(SPEC-430)도 같은 읽기를 써요.

### 8.2 기능 표(새 행)

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-430 | 릴리스 감시와 업데이트 데이터 메시지 보내기(서버) | REQ-553, REQ-556, FL-193 | 글 대화 서버와 FCM 보내기가 켜져 있음(지금 푸시와 같은 조건), `MARONG_APP_UPDATE_PUSH`가 `0`이 아님 | 봇 안의 작업 `AppUpdatePush`가 30초마다 SPEC-284의 읽기로 최신 릴리스(버전 코드)와 멈춤 여부를 봐요. ① 그 둘이 바뀌었을 때(새 버전 올림, 다시 켬) ② 봇이 시작할 때 ③ 그 밖에는 10분마다, 보낼 폰을 골라 폰마다 SPEC-431 메시지를 한 번 보내요. 보낼 폰 = TBL-101에서 친구마다 `seen_at`이 가장 최근인 20대 안에서(지금 푸시의 `app_devices()` 20대 상한과 같음) `fid`가 있고, `dropped_at`이 없고, `seen_at`이 30일 안이며, `app_version`(숫자 셋으로 비교)이 릴리스 `versionName`보다 낮은 폰 가운데, TBL-182의 그 `install_id`·버전 코드에 ⓐ `pushed` 줄이 없거나(시도 1) ⓑ 마지막 시도 n의 `pushed`에 같은 시도의 `push_failed`가 있고, n이 3보다 작고, 그 `push_failed`가 10분 전보다 오래된 폰(시도 n+1)이에요. 폰마다 차례로, 보내기 전에 그 시도의 `pushed` 줄(`attempt` n)을 `INSERT … ON CONFLICT DO NOTHING`으로 먼저 잡아요(유일 인덱스 `app_update_events_push_attempt`). 줄이 잡혔을 때만 SPEC-431 메시지를 보내고, 보내기가 실패하면 같은 시도 번호로 `push_failed` 한 줄(SPEC-435). 줄이 잡히지 않으면 다른 차례가 이미 잡은 것이라 보내지 않아요. `pushed`가 있고 같은 시도의 `push_failed`가 없으면 보낸 것으로 쳐요: 보낸 뒤 결과를 적기 전에 봇이 멈춘 드문 경우도 다시 보내지 않고(많아야 한 번), 그 폰은 하루 한 번 확인(SPEC-289 ③)이나 다음 앱 창 열기에서 새 버전을 받아요. 한 차례에 보내는 메시지는 100개까지이고 동시에 4개까지 보내요. 남은 폰은 10분을 기다리지 않고 다음 30초 차례에 이어서 보내요(가짜 폰 줄이 많아도 한 차례가 길어지지 않게, 8.9). 로그는 `app_update push code=<버전 코드> sent=<수> failed=<수> left=<수>` 한 줄(REQ-312) | 릴리스 없음·멈춤 → 보내지 않음<br>FCM `gone` → 그 폰의 FID를 지우고(지금 푸시와 같음) `push_failed`(`status` 410)<br>FCM `auth`·`failed` → `push_failed`(`status` 401·500), 다음 차례에 다시(3번까지)<br>DB에 닿지 않음, `pushed`를 잡는 쓰기가 실패 → 그 폰에 보내지 않음(이번 차례 건너뜀, 로그 한 줄)<br>보내기는 실패했는데 `push_failed` 쓰기도 실패 → 그 시도는 보낸 것으로 쳐서 다시 보내지 않음, 로그 `app_update record failed kind=push_failed`<br>FCM 키가 없음 → 감시를 돌리지 않음(지금 푸시가 꺼진 것과 같음) | 시험(가짜 FCM·가짜 시계): 새 릴리스 뒤 30초 차례에 뒤처진 폰 하나에만 한 번, 같은 버전·30일 넘음·FID 없음·멈춤은 보내지 않음, 봇을 다시 시작해도 다시 보내지 않음, `pushed`를 잡은 뒤 보내기 전에 멈추거나 `push_failed` 쓰기가 실패해도 그 시도를 다시 보내지 않음, 두 감시가 같은 폰·시도를 잡으면 하나만 보냄, 실패 3번(시도 1\~3) 뒤 그만, 폰 줄이 30개인 친구는 최근 20대에만, 뒤처진 폰 150대는 첫 차례 100개와 다음 30초 차례 50개, 동시 보내기 4개 이하(TC-599, TC-600) | active |
| SPEC-431 | 업데이트 데이터 메시지 형식(FCM) | REQ-553, REQ-554 | SPEC-430이 보냄 | `fcm.app_update(fid, version_code)`가 만드는 메시지: `{"fid": <FID>, "data": {"kind": "app_update", "v": "<버전 코드>"}, "android": {"priority": "HIGH", "ttl": "86400s", "collapse_key": "app_update"}}`. `notification` 칸을 넣지 않아요. 넣으면 앱이 백그라운드일 때 안드로이드가 알림만 띄우고 앱 코드(`onMessageReceived`)를 부르지 않아요 [사실: Firebase 'Receive messages in an Android app', 2026-11-22 읽음]. 버전 이름·릴리스 노트·주소·친구 정보는 넣지 않아요 | 24시간 안에 폰에 닿지 않으면 FCM이 버림 → 그 폰은 하루 한 번 확인(SPEC-289 ③)이나 다음 앱 창 열기에서 받음<br>같은 폰에 아직 닿지 않은 업데이트 데이터 메시지가 있으면 `collapse_key`로 마지막 것 하나만 닿음 | 시험: 메시지의 칸이 정확히 이것(`notification` 없음, `data` 칸 둘, `v`는 숫자 글). 에뮬레이터: 앱을 내린 상태에서 알림 없이 `onMessageReceived`가 불림(TC-601) | active |
| SPEC-432 | 업데이트 데이터 메시지로 확인하기(앱) | REQ-313, FL-147 | `MarongMessagingService.onMessageReceived`가 `kind=app_update`를 받음 | `v`가 1 이상 정수이고 지금 앱의 버전 코드보다 크며 마지막 강제 확인(`forcedAt`, 3.4)에서 10분이 지났으면, `forcedAt`을 적고 6시간 규칙 없이 확인 작업을 잡아요: 안드로이드 12 이상은 빠른 작업(`JobInfo.Builder.setExpedited(true)`, 네트워크 필요), 그 아래는 지연 없는 보통 작업(네트워크 필요). 작업은 SPEC-290\~293을 그대로 가고, 받은 뒤 설치는 SPEC-294로 가요. 조건에 맞지 않으면(같거나 낮은 버전, 10분 안) 지금의 확인 차례(SPEC-289 ②, 6시간 규칙)로 가요. 이 메시지로는 알림을 띄우지 않고, 처리한 뒤 바로 끝나요(선톡·벨 처리로 가지 않음) | 빠른 작업이 할당량 때문에 거절됨 → 보통 작업으로 다시 잡음<br>`v`가 숫자가 아니거나 없음 → 무시, 로그 `update_push bad` | JVM 시험: 10분 규칙(9분 59초 아니오, 10분 예, 시계가 뒤로 감이면 예)과 버전 비교(같음·낮음·높음). 에뮬레이터: 앱을 내리고 대기 버킷을 rare로 둔 상태에서 메시지 뒤 1분 안에 받기 시작(TC-603, TC-604) | active |
| SPEC-433 | 업데이트 상태 보고(앱) | REQ-555, REQ-316, FL-194 | 업데이트 상태(TERM-220)가 바뀜, 설치 ID가 있음(앱 창을 한 번 연 폰) | 상태와 때: `downloaded`(SPEC-292 통과), `waiting_quiet`(SPEC-294가 미룸, 그 버전에 한 번), `needs_confirm`(SPEC-297이 `STATUS_PENDING_USER_ACTION`을 받음), `failed`(SPEC-291·292·295·297의 실패, `status`는 8.5의 번호), `installed`(SPEC-298, 새 버전이 처음 깨어남. 서버는 이 보고로 `state` 줄을 남기지 않고, 같은 보고의 앱 버전이 올라간 것으로 `installed` 한 줄만 남겨요, SPEC-435). 앱 자바 코드가 네트워크 조건 작업(`AppUpdateReport`)으로 API-105를 `PUT`해요. 본문은 웹 페이지가 보내는 기기 보고와 같은 네 칸(`fid`, `notifications`, `appVersion`, `ring`, `PushState`에서 읽음)에 `update`(8.4)를 더해요. 헤더는 `Cookie`(웹뷰가 가진 앱 주소의 쿠키), `Origin`(앱 주소의 origin, 서버의 쓰기 확인), `Content-Type: application/json`, `Accept`, 사용자 에이전트(`MarongApp/<버전 이름>`). 넘겨주기(3xx)는 따라가지 않아요. 200·201이면 `reported`(3.4)에 버전 코드·상태·상태 번호를 적고 `pendingReport`를 지워요. 마지막으로 보고한 것과 버전 코드·상태·상태 번호가 모두 같으면 보내지 않아요(같은 버전의 두 번째 `failed`도 번호가 다르면 보냄) | 3xx·401·403(로그인이 끝남) → `pendingReport`로 남김. 다음에 앱 창이 열려 웹 페이지가 기기 보고를 한 뒤 다시 보냄<br>그 밖의 실패·네트워크 없음 → 15분 뒤 네트워크 조건 작업으로 다시, 첫 시도에서 24시간이 지나면 그만(로그 한 줄)<br>400(옛 서버가 `update`를 모름) → 그만, 다시 보내지 않음<br>409 `too_many_devices`(이 폰이 등록되지 않음, 8.9) → 그만, 다시 보내지 않음<br>`ring`을 빼면 서버가 벨 칸을 비워 벨을 못 받는 폰이 되므로(SPEC-139) 늘 넣어요 | JVM 시험: 본문 만들기(네 칸과 `update`), 같은 버전·상태·번호는 두 번 보내지 않고 번호만 다른 `failed`는 보냄, 다시 보내기 규칙. 에뮬레이터: 앱 화면을 열지 않고 `downloaded`·`waiting_quiet`가 `state` 줄로, 설치 뒤 `installed` 한 줄이 업데이트 기록에 남고 벨 칸이 그대로(TC-606) | active |
| SPEC-434 | 기기 보고의 업데이트 상태 받기(서버, API-105) | REQ-555, REQ-556 | API-105 요청(지금과 같은 확인: 로그인한 친구, 앱 `Origin`) | 본문의 선택 칸 `update`(8.4)를 받아요. 칸이 맞으면 기기 보고를 지금처럼 처리한 뒤 TBL-182에 `state` 한 줄을 더해요(SPEC-435). 상태가 `installed`면 `state` 줄을 더하지 않아요: 설치됨은 같은 보고의 `appVersion`이 올라간 것으로 SPEC-435가 `installed` 한 줄만 남겨요(설치됨을 남기는 곳은 하나). 응답은 지금과 같아요. 다음 경우에는 기기 보고와 응답은 그대로 하고 기록만 더하지 않고 로그 `app_update record skipped reason=<이유>` 한 줄을 남겨요(2026-11-23 보안 검토): ① `versionCode`가 버전 기록(8.3)의 `published` 버전 코드가 아님(지금 최신보다 높은 가짜 번호 포함) ② 그 폰·버전 코드의 마지막 `state` 줄과 상태·번호가 같음(같은 보고를 되풀이) ③ 그 친구가 지난 1시간에 API-105로 남긴 업데이트 기록(`state`·`installed`)이 30줄에 닿음(봇 메모리에 친구마다 1시간 창) | `update`가 틀림(모르는 칸, 상태가 다섯 값 밖, `failed`인데 `status` 없음, `failed`가 아닌데 `status` 있음, 버전 코드가 범위 밖, `versionCode`·`status`가 정수가 아님. 참·거짓 값도 정수로 보지 않아요: 파이썬 `type(x) is int`) → 400 `invalid_request`(칸 `update`, `bad_format`), 기기 보고도 하지 않음(지금 규칙과 같이 하나라도 틀리면 모두 거절)<br>`update`가 없음 → 지금과 똑같음(웹 페이지 보고, 옛 앱) | 시험: 정상 `update` 한 줄, `installed`는 `state` 줄 없이 `installed` 한 줄, 틀린 값 다섯 가지와 참·거짓 값 400, 버전 기록에 없는 버전 코드·되풀이 보고·1시간 31번째는 기록 없이 200, `update` 없는 보고는 기록 없음(TC-607) | active |
| SPEC-435 | 업데이트 기록 쓰기(서버) | REQ-556 | SPEC-430, SPEC-434, API-105, API-142 | TBL-182(05 단계)에 한 줄씩 더하기만 해요(고치거나 지우지 않음). `pushed`: SPEC-430이 보내기 전에 잡는 줄(설치 ID, 버전 코드, 시도 번호 1\~3). `push_failed`: 그 시도의 보내기가 실패했을 때(같은 시도 번호, 상태 번호). `state`: SPEC-434가 폰마다(설치 ID, 버전 코드, `installed` 밖의 상태 넷, 번호). `installed`: API-105가 받은 `appVersion`이 그 폰의 이전 `app_version`보다 높고 버전 기록(8.3)의 `published` 버전 이름일 때 한 줄(지금 최신보다 높거나 기록에 없는 버전으로 올라가면 남기지 않음)(설치 ID, 새 앱 버전. 버전 코드는 같은 보고의 `update`가 `installed`면 그 `versionCode`, 아니면 버전 기록에서 그 버전 이름으로 찾고, 없으면 비움). 설치됨을 남기는 곳은 이것 하나예요: 앱의 `installed` 보고(SPEC-298)는 앱 버전을 올려 이 줄을 만들 뿐 `state` 줄을 남기지 않고, 웹 페이지 보고가 먼저 새 버전을 실어 와도 한 폰·앱 버전에 한 줄이에요(유일 인덱스 `app_update_events_installed_once`, `ON CONFLICT DO NOTHING`). `fetched`: API-142가 APK를 끝까지 보냈을 때 친구마다(친구 ID, 버전 코드. 설치 ID는 그 요청에 없어서 비움). 같은 친구·버전 코드의 `fetched` 줄이 1시간 안에 있으면 더하지 않아요. 1년이 지난 줄은 표 소유 역할이 매달 지워요(ERD 2절). 모든 줄의 친구(`friend_id`)는 그 일이 있던 때의 친구예요(폰이 다른 친구로 다시 로그인하면 TBL-101의 친구가 바뀜, SPEC-438) | `pushed`·`push_failed` 쓰기가 실패 → SPEC-430(잡지 못하면 보내지 않음, 결과를 적지 못하면 보낸 것으로 침)<br>`state`·`installed`·`fetched` 쓰기가 실패 → 원래 일(기기 보고 응답, APK 보내기)은 그대로, 로그 `app_update record failed kind=<종류>`. 이 줄들은 보내기 판단에 쓰지 않아요 | 시험: 다섯 종류의 줄과 빈 칸 규칙, 같은 폰·버전·시도의 `pushed` 두 번 거절, 설치 한 번에 `installed` 한 줄(웹 페이지 보고와 앱 보고가 둘 다 새 버전을 실어 와도), 기록에 없는 버전으로 올라가면 `installed` 없음, 같은 친구·버전의 `fetched`는 1시간에 한 줄, 봇 계정이 줄을 지우거나 고칠 수 없음(TC-608) | active |
| SPEC-436 | 릴리스 노트 받기(도구) | REQ-557, FL-146 | `app-release publish` | 노트북 명령은 `--notes "<릴리스 노트>"`를 꼭 받아, 글을 임시 폴더의 `notes.txt`(UTF-8)로 함께 보내요(셸 따옴표 문제를 피하려고 명령 줄로 넘기지 않음). 서버 도구 `publish --notes-file <파일>`은 앞뒤 공백을 지운 글이 1\~300자이고 줄바꿈·제어 문자가 없을 때만 받아요. 노트는 버전 기록(SPEC-437)에만 써요. API-141 응답과 앱, 친구에게는 가지 않아요(REQ-554) | 없음·빈 글·300자 넘음·줄바꿈·제어 문자 → 거절(종료 코드 2), 서버 그대로 | 시험: 노트 없음·빈 글·301자·줄바꿈 거절, 정상 노트가 버전 기록에 그대로(TC-611) | active |
| SPEC-437 | 버전 기록(서버 폴더) | REQ-558, FL-146 | `publish`·`pause`·`resume`·`backfill` | 릴리스 폴더의 `history.json`(8.3)에 더하기만 해요. `publish`는 같은 잠금 안에서 먼저 버전 기록에 `published` 줄(`backfilled: false`)을 쓴 뒤(임시 파일 → 이름 바꾸기) `release.json`을 바꿔요. `release.json` 바꾸기가 실패하면 버전 기록을 앞 내용으로 되돌려요. `pause`·`resume`도 `paused`·`resumed` 줄을 더해요. `backfill`(처음 한 번)은 0.2.2\~0.3.2 가운데 서버에 올린 것을 `backfilled: true`로 넣어요: 버전 코드·이름은 git의 `build.gradle`, 올린 때·크기·SHA-256은 10 WBS 진행 기록과 서버 폴더에 남은 APK에서 알 수 있는 것만, 모르면 `null`, 노트는 그 버전의 WBS·커밋 제목에서 한 줄 | `history.json`이 형식에 맞지 않음 → 올리기·멈추기를 거절(기록을 잃지 않게), 사람이 고침<br>`backfill`을 두 번 → 이미 있는 버전 코드는 건너뜀(바뀌는 것 없음) | 시험: 올리기·멈추기·다시 켜기마다 한 줄, 줄이 지워지지 않음, 실패 때 되돌림, `backfill` 두 번(TC-611, TC-612) | active |
| SPEC-438 | 관리자 읽기(API-267) | REQ-559 | 관리자(관리 페이지와 같은 확인: Access JWT의 이메일 해시가 관리자 것과 같음, SPEC-395) | `GET /chat/admin/api/app-versions` → 200(8.6의 형식): 최신 릴리스와 멈춤 여부, 버전 기록(새것부터, 노트 포함. 서버가 `history.json` 줄의 칸을 옮겨 담고 `file`은 빼요), 90일 안에 보고한 폰마다 친구 이름·친구 ID(`friendId`, 관리 페이지의 회원 API와 같은 번호)·폰 순번·앱 버전·뒤처짐 여부·마지막 보고·알림 권한·최근 업데이트 기록 20줄, 90일 안에 APK를 받아 간 친구마다 그 친구의 받아 감 새것부터 20줄(`fetches`는 친구마다 한 칸이고 그 안의 `items`가 20줄까지). 폰은 친구마다 `seen_at`이 가장 최근인 20대, 모두 200대까지이고(친구 이름, 친구 ID, 폰 순번 차례), 받아 감은 100명까지예요(8.9). 폰 순번은 그 친구의 이 20대 가운데 처음 등록한(`created_at`) 차례 1\~20이에요. 친구 이름은 겹칠 수 있고 친구가 바꿀 수도 있어서(`marong/store.py`가 이름을 고침) 관리 페이지는 친구 ID로 구분해요. 릴리스 노트는 사람이 쓴 글이라 관리 페이지는 `textContent`로만 넣고 `innerHTML`을 쓰지 않으며, 응답 머리말의 CSP `script-src 'self'`(`marong/app_chat.py`의 `HEADERS`)를 그대로 둬요. 폰의 업데이트 기록은 TBL-182 줄 가운데 `friend_id`가 지금 그 폰의 친구(TBL-101 `friend_id`)와 같은 줄만이에요: 폰이 다른 친구로 다시 로그인하면 기기 보고가 TBL-101의 친구를 바꾸고(지금 코드), 앞 친구 때의 줄은 표에 남지만 이 응답에는 나오지 않아요(다른 친구의 기록을 섞지 않음). `Cache-Control: no-store` | 관리자 아님 → 403 `not_allowed`<br>DB에 닿지 않음 → 503 `db_unavailable`<br>버전 기록 파일 없음 → `releases` 빈 목록 | 시험: 관리자 200과 칸, 폰과 받아 감에 친구 ID, 폰 줄이 30개인 친구는 최근 20대만, 받아 감이 친구마다 20줄까지, 다른 친구로 옮긴 폰은 지금 친구 때의 줄만, 버전 기록 줄에 `file` 없음, 관리자 아님 403, 응답에 설치 ID·FID·이메일이 없음(TC-613) | active |
| SPEC-439 | 첫 화면 업데이트 배너(웹, SCR-001) | REQ-560, REQ-561, REQ-321, REQ-325, FL-148 | 통화 홈(SCR-001)이 앱 안에서 열림(`window.__marongApp.version`이 3 이상) | 통화 서버가 내보내는 통화 홈 페이지(`tools/vertex_live/static/app.js`·`index.html`·`style.css`)가 `updateState()`(SPEC-440)와 `deviceState().installUpdates`를 읽어요. ① `ready` → 배너 '새 버전 준비됨 · 지금 설치'(08 SCR-001#update-ready). 누르면 `installUpdate()`(SPEC-441) ② `installing` → '설치하는 중… 앱이 잠깐 닫혀'(#update-installing) ③ 받아 둔 파일이 없고 `installUpdates`가 false → '자동 업데이트 꺼짐 · 켜기'(#update-off), 누르면 `openInstallSettings()` ④ 그 밖 → 배너 없음. 화면이 다시 보일 때(`visibilitychange`)와 앱이 보낸 `marongupdate` 이벤트에 다시 읽어요 | 브라우저·옛 앱(연결 `version` 2 이하) → 배너 없음(REQ-561)<br>`installUpdate()`가 `busy` → 배너 글 '통화 끝나고 깔 수 있어', 단추를 잠시 막음<br>`failed` → '설치하지 못했어. 나중에 다시 해 볼게', 배너는 ①로 남음 | 브라우저 시험(가짜 앱 연결): 네 상태와 단추, 옛 연결이면 배너 없음(TC-609) | active |
| SPEC-440 | 앱 연결 더하기(앱) | REQ-560, REQ-325 | | `MarongPush`에 `updateState()`(`state`는 `none`·`ready`·`installing`, `ready`면 `versionName`도. `ready`는 SPEC-292를 통과한 파일이 있을 때)와 `installUpdate()`(SPEC-441)를 더하고, `window.__marongApp`을 `version: 3`으로 올려 `updateState`, `installUpdate`를 내보내요. 받음·설치 시작·실패 때 열려 있는 두 창(통화 창과 글 대화 창)의 페이지 모두에 `marongupdate` 이벤트를 보내요. 연결은 두 창 모두 같은 페이지 스크립트(`assets/marong_page.js`)가 넣어서, 통화 홈(SPEC-439)과 글 대화(SPEC-443)가 같은 함수를 읽어요 | 옛 페이지는 새 칸을 모름 → 그대로 | 페이지 시험: 연결 `version` 3과 두 함수, 이벤트(TC-609). 에뮬레이터: 글 대화 창에도 이벤트가 닿음(TC-619) | active |
| SPEC-441 | 사용자가 누른 설치(앱) | REQ-319, REQ-560, FL-148 | 받고 확인한 파일이 있음(SPEC-292), 페이지가 `installUpdate()`를 부름 | 통화 알림(101)과 벨 알림(201)이 없으면, SPEC-294의 앱 창 조건(처음 승인된 글의 ③, 앱 창이 보임)을 보지 않고 바로 SPEC-295의 설치 요청을 해요(SPEC-294의 예외, D128). `installing`을 돌려줘요. 결과는 SPEC-297 그대로예요: 설치되면 안드로이드가 앱을 닫고 새 버전이 깔려요. 사용자 확인이 필요하면 앱이 화면에 있으니 알림 대신 안드로이드 확인 창(`EXTRA_INTENT`)을 바로 열어요 | 통화·벨 중 → `busy`, 설치하지 않음<br>받아 둔 파일 없음 → `none`<br>세션 오류 → `failed`, 실패 1번(SPEC-293), 상태 보고 `failed`(SPEC-433) | 에뮬레이터: 앱 창이 떠 있어도 누르면 설치되고 새 버전으로 열림, 통화 중이면 `busy`(TC-610) | active |
| SPEC-442 | 반영 순서(서버 먼저, 앱 나중) | REQ-553, REQ-555 | 구현·반영은 Codex(이 PR에는 코드 없음) | ① 마이그레이션 `023_app_update_events.sql`(TBL-182) 적용 ② 서버 반영: 봇의 SPEC-430·431·434·435·437·438과 도구 SPEC-436, `backfill` 한 번, 통화 서버의 통화 홈 페이지 SPEC-439와 봇의 글 대화 페이지 SPEC-443(옛 앱은 연결 `version` 2라 배너가 없어 먼저 반영해도 됨). 이때부터 API-105가 `update`를 받아요. 옛 서버는 모르는 칸이 든 기기 보고를 통째로 400으로 거절해서(지금 코드), 서버가 늦으면 새 앱의 상태 보고가 남지 않아요 ③ 새 앱(0.3.4 이상, 버전 코드 12, SPEC-432·433·440·441)을 서명해 올려요. 0.3.3(버전 코드 11)은 TC-222 고침만 담아 먼저 나간 릴리스예요(PR #106). 이 버전은 에뮬레이터 시험과 실제 삼성 폰 시험(TC-614\~616)이 모두 통과한 뒤에만 올려요(오랑이 msg_93f811d54b84의 규칙). 0.3.2 이하 폰은 업데이트 데이터 메시지를 받아도 알림 없이 지금 규칙(6시간)대로 확인해요. 이 기능이 없는 0.3.3도 같아요(TC-602) | 서버를 되돌림 → 새 앱의 상태 보고가 400을 받고 그만(SPEC-433). 웹 페이지 기기 보고는 `update`를 보내지 않아 그대로 | 반영 뒤 `update` 없는 API-105가 그대로 200, 감시 시작 로그 한 줄, 0.3.2 폰에 알림이 뜨지 않음(TC-602, TC-617) | active |
| SPEC-443 | 글 대화 업데이트 배너(웹, SCR-107) | REQ-560, REQ-561, REQ-321, REQ-325, FL-148 | 글 대화(SCR-107)가 앱의 글 대화 창(SCR-112) 안에서 열림(`window.__marongApp.version`이 3 이상). 선톡 알림(SCR-108)을 누르면 이 창이 바로 열려요 | 봇이 내보내는 글 대화 페이지(`marong/app_chat_static/chat.js`·`index.html`·`chat.css`)가 SPEC-439와 같은 규칙 ①\~④로 같은 앱 연결(`updateState()`, `deviceState().installUpdates`, `installUpdate()`, `openInstallSettings()`)을 읽고 불러요(D131: 동희님 "둔다 ㄱㄱ"). 상태는 08의 SCR-107#update-* 여섯이고 글과 단추는 SCR-001#update-*와 같아요. 띠는 머리(`.bar`) 바로 아래, 메뉴(SCR-109)와 메시지 목록 위에 두고, 첫 메시지 목록(API-102)을 그리기 전에 정해요. 화면이 다시 보일 때(`visibilitychange`)와 `marongupdate` 이벤트에 다시 읽고, 띠가 생기거나 사라져도 목록은 마지막 말이 보이던 자리를 지켜요 | 브라우저·옛 앱(연결 `version` 2 이하) → 배너 없음(REQ-561)<br>500ms 안에 연결이 답하지 않음 → 배너 없음으로 그리고 다음 `visibilitychange`에 다시<br>통화 중에도 띠는 보임(글 대화에는 통화 단추가 없음). 누르면 `busy` → '통화 끝나고 깔 수 있어'<br>`failed`·`none` → SPEC-439와 같음 | 브라우저 시험(가짜 앱 연결): 여섯 상태와 단추, 옛 연결이면 배너 없음, 띠가 생겨도 마지막 말이 가려지지 않음(TC-618). 에뮬레이터: 선톡 알림을 눌러 연 글 대화 창에서 배너가 보이고 '지금 설치'가 됨(TC-619) | active |

### 8.3 버전 기록 `history.json`

릴리스 폴더(3.1)에 있고 봇 사용자 `marong`만 써요. 줄을 더하기만 해요.

```json
{
  "format": 1,
  "entries": [
    {"kind": "published", "versionCode": 10, "versionName": "0.3.2", "at": "2026-11-22T07:21:00Z",
     "notes": "릴리스 노트 한 줄", "size": null, "sha256": null,
     "file": "marong-0.3.2-10.apk", "backfilled": true},
    {"kind": "published", "versionCode": 11, "versionName": "0.3.3", "at": "2026-11-24T05:00:00Z",
     "notes": "릴리스 노트 한 줄", "size": 5100000, "sha256": "64자 16진수 소문자",
     "file": "marong-0.3.3-11.apk", "backfilled": false},
    {"kind": "paused", "at": "2026-11-23T01:00:00Z"},
    {"kind": "resumed", "at": "2026-11-23T02:00:00Z"}
  ]
}
```

- `kind`: `published`·`paused`·`resumed`. `published`만 버전 칸, `notes`, `size`, `sha256`, `file`, `backfilled`가 있고, `paused`·`resumed`는 `kind`와 `at`뿐이에요.
- `versionCode`·`versionName`·`file`은 3.1과 같은 형식, `at`은 ISO 8601 UTC, `notes`는 1\~300자 한 줄(SPEC-436). `size`·`sha256`은 3.1 형식이거나 `null`(채워 넣은 줄에서 모를 때만). `backfilled`는 `published` 줄마다 늘 있는 참·거짓 값이에요: `backfill`이 채워 넣은 줄은 `true`, `publish`가 쓴 줄은 `false`. API-267도 같은 규칙이에요(8.6).
- 위 예시의 값은 형식 예시예요(실제 0.3.3·0.3.4 릴리스의 값이 아니에요). 채워 넣는 줄의 실제 값은 `backfill`이 기록에서 찾아요.

### 8.4 기기 보고의 `update` 칸(API-105)

```json
{"fid": "…", "notifications": "granted", "appVersion": "0.3.3",
 "ring": {"channel": "enabled", "fullScreen": "granted"},
 "update": {"versionCode": 11, "state": "failed", "status": 3}}
```

- `versionCode`: 업데이트 상태가 가리키는 새 버전의 버전 코드(1\~2100000000). `installed`면 막 깔린 지금 버전이에요.
- `state`: `downloaded`·`waiting_quiet`·`needs_confirm`·`failed`·`installed`(TERM-220). 서버는 `installed` 밖의 넷만 `state` 줄로 남기고, `installed`는 같은 보고의 `appVersion`이 올라간 것으로 `installed` 줄 하나를 남겨요(SPEC-434, SPEC-435).
- `status`: `failed`일 때만, 8.5의 번호(정수 1\~999).
- 원본 계약은 [api/app-chat.openapi.yaml](../../api/app-chat.openapi.yaml)의 `DeviceRequest.update`예요.

### 8.5 실패 번호(`status`)

| 번호 | 뜻 | 어디서 |
| --- | --- | --- |
| 1\~7 | 안드로이드 `PackageInstaller.STATUS_FAILURE`(1)\~`STATUS_FAILURE_INCOMPATIBLE`(7)을 그대로 | SPEC-297 |
| 101 | 받기 실패·시간 초과 | SPEC-291 |
| 102 | 받는 중 크기가 `size`를 넘음 | SPEC-291 |
| 111\~115 | 받은 파일 확인 ①\~⑤ 실패(크기, SHA-256, 패키지 이름, 버전 코드, 서명 인증서) | SPEC-292 |
| 121 | 설치 세션을 만들거나 쓰다 오류 | SPEC-295 |

업데이트 기록의 `push_failed`는 FCM 결과를 410(`gone`)·401(`auth`)·500(`failed`)으로 적어요(SPEC-430). 앱의 번호와 겹치지 않아요.

### 8.6 관리자 읽기 응답(API-267)

```json
{
  "latest": {"versionCode": 11, "versionName": "0.3.3", "publishedAt": "2026-11-24T05:00:00Z"},
  "paused": false,
  "releases": [{"kind": "published", "versionCode": 11, "versionName": "0.3.3", "at": "…", "notes": "…",
                "size": 5100000, "sha256": "…", "backfilled": false}],
  "devices": [{"friend": "현경", "friendId": 7, "phone": 1, "appVersion": "0.3.2", "behind": true, "seenAt": "…",
               "notifications": "granted",
               "events": [{"kind": "pushed", "versionCode": 11, "attempt": 1, "at": "…"},
                          {"kind": "state", "versionCode": 11, "state": "waiting_quiet", "at": "…"}]}],
  "fetches": [{"friend": "현경", "friendId": 7, "items": [{"versionCode": 11, "at": "…"}]}]
}
```

- `phone`은 그 친구의 보이는 폰(최근 보고 20대) 가운데 처음 등록한 차례(1\~20)예요. 설치 ID·FID·이메일은 주지 않아요(REQ-559).
- `friendId`는 친구 ID(관리 페이지의 회원 API `friendId`와 같은 번호)예요. 친구 이름은 겹치거나 바뀔 수 있어서 관리 페이지는 이 번호로 폰과 받아 감을 사람에 맞춰요.
- 상한: `devices`는 친구마다 최근 보고 20대, 모두 200대까지, `fetches`는 100명까지예요(SPEC-438, 8.9).
- 관리 페이지는 `notes`(릴리스 노트)를 `textContent`로만 그려요. `innerHTML`은 쓰지 않고 CSP `script-src 'self'`를 그대로 둬요.
- `releases`는 8.3의 `entries`를 새것부터 옮겨 담은 것이에요. 서버가 칸을 골라 담고 `file`(APK 파일 이름)은 빼요(관리자 화면에 필요 없음). `backfilled`는 8.3과 같이 `published` 줄에 늘 있어요.
- `devices`의 `events`는 그 폰의 새것부터 20줄이고, `friend_id`가 지금 그 폰의 친구와 같은 줄만이에요(SPEC-438). `pushed`·`push_failed`에는 시도 번호 `attempt`(1\~3)가 있어요.
- `fetches`는 90일 안에 APK를 받아 간 친구마다 한 칸(친구 이름 차례)이고, 그 안의 `items`가 그 친구의 90일 안의 받아 감 새것부터 20줄이에요. 받아 간 줄이 없는 친구는 칸이 없어요.
- 원본 계약은 [api/app-update.openapi.yaml](../../api/app-update.openapi.yaml)의 API-267이에요.

### 8.7 요구사항 덮기

| 요구사항 | 흐름 | 명세 |
| --- | --- | --- |
| REQ-553 | FL-193 | SPEC-430, SPEC-431, SPEC-442 |
| REQ-554 | FL-193, FL-146 | SPEC-431, SPEC-436 |
| REQ-555 | FL-147, FL-194 | SPEC-433, SPEC-434, SPEC-298 |
| REQ-556 | FL-193, FL-194 | SPEC-430, SPEC-434, SPEC-435 |
| REQ-557 | FL-146 | SPEC-287, SPEC-436 |
| REQ-558 | FL-146 | SPEC-287, SPEC-437 |
| REQ-559 | FL-194 | SPEC-438 |
| REQ-560 | FL-148 | SPEC-439, SPEC-440, SPEC-441, SPEC-443 |
| REQ-561 | FL-148 | SPEC-439, SPEC-443 |
| REQ-313(바뀜) | FL-147 | SPEC-289, SPEC-432 |
| REQ-316(바뀜) | FL-194 | SPEC-301, SPEC-433 |
| REQ-319(바뀜) | FL-147, FL-148 | SPEC-294, SPEC-441 |
| REQ-321(바뀜) | FL-148 | SPEC-296, SPEC-439, SPEC-443 |
| REQ-325(바뀜) | FL-148 | SPEC-300, SPEC-439, SPEC-443 |

빠진 것: 없어요. 모순: SPEC-294의 앱 창 조건(처음 글의 ③)과 SPEC-441은 8.1처럼 예외로 묶었고, SPEC-294 행 끝에서 SPEC-441을 가리켜요.

### 8.8 경우의 종류와 요구사항 없이 생긴 동작(4·6절로 옮김)

이 기능 변경이 더한 경우의 종류 네 줄은 [4절](#4-경우의-종류) 표로, 요구사항 없이 생긴 동작 네 가지는 [6절](#6-요구사항-없이-생긴-동작)로 옮겼어요(2026-11-23, TASK-488). 버그 수정 PR #100과 같은 줄이라 처음엔 여기에 따로 적었고, 두 PR이 합쳐진 뒤 한 곳에만 두려고 여기서는 지웠어요.

### 8.9 승인된 기기 등록(SPEC-115, API-105)을 바꿈(2026-11-23 보안 검토, D134)

보안 검토(읽기만, 중간 1건)가 찾은 것: 로그인한 친구는 지금도 API-105에 아무 installId나 넣어 폰 줄을 끝없이 만들 수 있어요(`marong/app_store.py`의 `app_device_put`, 상한 없음). 지금 푸시는 `app_devices()`의 `LIMIT 20`으로 친구마다 20대만 보지만, 이 설계의 감시(SPEC-430)와 관리자 읽기(SPEC-438)가 상한 없이 읽으면 가짜 줄 2만 개가 게시 한 번에 FCM 보내기 2만 번과 기록 4만 줄이 되고, 진짜 폰은 1분 안(REQ-553)에 받지 못해요. 감시와 관리자 읽기의 상한은 이 PR의 새 행에 넣었어요(SPEC-430·438). 남는 것은 줄이 쌓이는 입구라서 아래를 제안했고, 2026-11-23 체크포인트에서 승인됐어요(D134).

| 경우 | 전(docs/app-chat.md SPEC-115, 2026-11-15 승인, 2026-11-16 반영) | 바뀐 뒤(D134) |
| --- | --- | --- |
| 새 installId | 늘 만들어요(201). "없으면 만들고(201) 있으면 고치고(200), `seen_at`을 지금으로 적어요" | 그 친구에게 `seen_at`이 30일 안인 폰 줄이 이미 20개이고 이 installId가 그 가운데 없으면 409 `too_many_devices`로 거절하고 줄을 만들지 않아요. 친구마다 잠금(`pg_advisory_xact_lock`) 안에서 세고 더해서 동시 요청으로도 20을 넘지 않아요 |
| 있는 installId | 고쳐요(200) | 그대로 |
| 다른 친구가 쓰던 installId | 지금 친구로 옮겨요 | 옮겨 갈 친구 쪽에서 위 상한을 봐요 |

- 친구에게 보이는 것: 보통은 없어요. 친구마다 지금 폰은 1\~2대라 20대에 닿지 않아요. 거절된 폰은 앱 알림을 받지 못하고, 알림은 다른 폰이나 디스코드로 가요(FID가 없는 폰과 같음). 30일이 지난 폰은 세지 않아서 시간이 지나면 다시 등록돼요.
- 옛 앱: 페이지 스크립트(`assets/marong_page.js`)는 200·201이 아니면 조용히 넘어가고 다음에 페이지가 열릴 때 다시 보내요(사실: 그 파일의 `sendReport`). 409에 화면이 바뀌지 않아요. 새 앱의 업데이트 상태 보고(SPEC-433)는 409에서 그만둬요.
- 다른 방법: 거절 대신 가장 오래된 폰의 FID를 지우는 방법도 있어요. 새 폰은 늘 등록되지만 줄은 계속 쌓여서, 줄을 막는 거절을 추천해요.
- 계약: [api/app-chat.openapi.yaml](../../api/app-chat.openapi.yaml)의 API-105에 409와 오류 코드 `too_many_devices`를 더했어요. 승인된 동작을 바꾸는 것이라 체크포인트에서 따로 여쭸고, 2026-11-23에 승인돼(D134) docs/app-chat.md의 SPEC-115 행을 고쳤어요. 구현은 TASK-479, 시험은 TC-607이에요.
- 결정: [도메인 9.3](../01-domain/app-update.md#93-결정)의 D134. 질문은 [도메인 9.5](../01-domain/app-update.md#95-열린-질문체크포인트-때-여쭤요)의 질문 3이었어요.
