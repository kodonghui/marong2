# 앱 자동 업데이트 작업 목록(10단계 WBS, CTX-021)

2026-11-17 13시대 KST 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [app-update.md](../04-functional-spec/app-update.md)(SPEC-284\~302), 계약 [app-update.openapi.yaml](../../api/app-update.openapi.yaml)(API-141, API-142), 화면 상태 [app-update.md](../08-screens/app-update.md)(SCR-109, SCR-130), 시험 계획 [12-qa/app-update.md](../12-qa/app-update.md)(TC-200\~229).

## GPT 인계

- 목표: 서버에 새 APK를 올리면 친구 폰의 마롱이 앱이 스스로 받아, 같은 키로 서명됐는지 확인하고, 안드로이드 12 이상에서는 묻지 않고 깔게 해요. 그래서 0.2.2가 손으로 까는 마지막 버전이 돼요(현경님 폰은 지금 0.2.1). 동희님 2026-11-17 12:18 KST 이 스레드 "좀 자동 업데이트 되게 못하나"(D40, [도메인 설계](../01-domain/app-update.md)).
- 시작: 브랜치 `claude/project-thread-jbvi9w` 커밋 `__START__`에서 새 브랜치 `codex/app-self-update`. PR #27이 `main`에 합쳐졌으면 `main`에서 시작해요.
- 읽을 것: [기능 명세](../04-functional-spec/app-update.md)의 SPEC-284\~302와 3절(릴리스 폴더, 도구 명령, 알림 글, 앱 상태 키), [계약](../../api/app-update.openapi.yaml)의 API-141·142, [화면 상태](../08-screens/app-update.md)의 SCR-109#update-on·#update-off·#update-none과 SCR-130#shown·#locked·#none, [시험 계획](../12-qa/app-update.md)의 TC-200\~229. 목업은 공통 목업 캔버스의 SCR-109·SCR-130 대지예요(화면 공통 기준은 PR #25의 `design/README.md`). 바탕 코드: `marong/app_chat.py`(`_who`, 라우트), `apps/android/android/app/src/main/java/com/corthexhq/marong/`의 `MarongPushPlugin`·`Channels`·`MarongMessagingService`·`MainActivity`·`ChatActivity`·`CallService`·`Ring`, `apps/android/test/`의 `app-config.test.cjs`·`chat-page.e2e.cjs`·`support/emulator-site.cjs`, `deploy/ovh.sh`. 이 밖의 문서는 읽지 않아도 돼요.
- 이미 된 것: 설계만이에요(01\~10과 12 시험 계획). 이 기능의 코드는 없어요. 같은 브랜치에 0.2.2의 다른 변경(선 전화·그림 화두, CTX-020)이 있고, 그 서버 쪽은 2026-11-17 01:24 KST에 반영됐어요. 앱 쪽은 에뮬레이터 확인까지 됐고 서명 APK만 남았어요([call-first.md](call-first.md) TASK-176).
- 순서: TASK-179 → (TASK-180, TASK-181) → TASK-182. TASK-183은 따로. TASK-184 → (TASK-185, TASK-186, TASK-188) → TASK-187 → TASK-189 → TASK-190. 서버 반영 TASK-191은 TASK-179\~183 뒤. TASK-192는 TASK-190·191 뒤, 그다음 TASK-193.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node(`npm test`, Playwright), Java 21과 Gradle(영문 경로 사본), 안드로이드 에뮬레이터(안드로이드 12 이상, 가능하면 16). 진짜 모델·유료 API는 쓰지 않아요. FCM도 진짜가 필요 없어요(시험 사이트).
- 반영: 서버는 TASK-191. 마이그레이션 없음. 파일은 `marong/app_chat.py`, `marong/app_release.py`, `marong/app_chat_static/chat.js`·`chat.css`, `tools/app_release.py`. 릴리스 폴더 `/var/lib/marong/app-releases`(소유 `marong`, 0750)를 만들어요. 따로 켜고 끄는 설정은 두지 않아요: 릴리스를 올리기 전엔 API-141이 204라 아무 일도 없고, 멈춤은 `app-release pause`예요. 재시작은 `marong-discord` 서비스(글 대화 서버가 디스코드 봇 안에 있음). 되돌리기는 서버 `~/marong-deploy/<날짜>-app-update/`. 앱은 0.2.2(versionCode 5) 그대로이고, 선 전화(CTX-020)와 한 APK로 빌드·서명해요. 서명은 `GPT(동희님 노트북)`(TASK-192).
- 하면 안 되는 것: 새 라이브러리(WorkManager, OkHttp 등) 더하기. 커밋된 versionCode 바꾸기(시험용 6은 커밋하지 않는 빌드 값으로만). 앱이 넘겨주기(3xx)를 따라가거나, 앱 주소 밖에서 받거나, 앱 버전 밖의 기기 정보를 보내기(REQ-315, REQ-316). APK를 Git에 넣기. 시험용 APK를 실제 서버 릴리스로 올리기(실제 릴리스는 TASK-192의 0.2.2와 TASK-193의 0.2.3뿐). Access 설정 바꾸기.
- 겹치는 파일: `apps/android/`는 선 전화 0.2.2와 같은 브랜치라 겹침이 없어요. `.corthex/stages.json`은 PR #25와 겹쳐요([README](README.md#겹치는-파일)). `marong/app_chat.py`·`chat.js`는 지금 다른 패키지가 고치지 않아요.
- 사람 확인: TC-228·229(현경님 폰, 동희님이 부탁). 0.2.2를 깔 때 아래 '설치 안내 한 줄'을 현경님께 전해요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-200\~227 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 그리고 아래 명령이 모두 통과. 실제 서버의 API-141이 0.2.2를 줌(TASK-192).
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.

```bash
.venv/bin/python tests/test_app_update.py            # 서버: TC-200~212
cd apps/android && npm test && npm run test:browser  # 앱 설정 TC-226, 글 대화 메뉴 TC-225
cd apps/android/android && ./gradlew testDebugUnitTest lintDebug assembleDebug   # 앱 논리 TC-213~219
```

확인 질문 세 개(01 단계 8절)는 추천안으로 구현해요: ① 설치는 통화·벨이 없고 앱 창이 화면에 없을 때만(REQ-319, SPEC-294) ② 처음 허용은 글 대화 메뉴의 줄과 '켜기', 그리고 0.2.2 설치 안내 한 줄(REQ-325, SPEC-300) ③ 설치 뒤 알림 없음(REQ-324). 동희님이 다른 답을 주면 설계 스레드가 명세를 먼저 고치고 알려요.

0.2.2 설치 안내 한 줄(TASK-192): "깔고 나서 글 대화 메뉴의 '자동 업데이트'에서 '켜기'를 눌러 '이 출처 허용'을 켜 줘. 그러면 다음부터는 저절로 깔려."

## 작업

- 담당: 모두 GPT예요. 서명은 서명 키가 있는 동희님 노트북에서만 할 수 있어서 TASK-192는 `GPT(동희님 노트북)`이에요. 실제 폰 확인(TASK-193)은 현경님 폰을 부탁하는 동희님과 같이 해요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-179 | 릴리스 폴더 읽기 `marong/app_release.py`: `MARONG_APP_RELEASES_DIR`(없으면 `/var/lib/marong/app-releases`)의 `release.json`을 3.1 형식으로 검사하고 APK 파일 존재·크기·`paused`를 보고 최신 릴리스 또는 없음을 돌려줌. 틀리면 로그 `app_release invalid` 한 줄(같은 내용 10분에 한 번) | SPEC-284 | 릴리스 폴더(3.1) | 없음 | GPT | 0.25 | TC-200 통과 |
| TASK-180 | 글 대화 서버 라우트 두 개: `GET /chat/api/app/release`(API-141), `GET /chat/app/{file}`(API-142). Access·허용 목록 확인은 `_who`와 같되 DM 확인은 빼요. `Cache-Control: no-store`, APK는 나눠 읽어 보내고 `Content-Length`, 로그 `app_release apk sent code=<버전 코드>` | SPEC-285, SPEC-286 | API-141, API-142, `marong/app_chat.py` | TASK-179 | GPT | 0.5 | API-141의 200·204·401·403·500·503과 API-142의 200·401·403·404·500·503마다 시험 통과(TC-201\~208), 응답이 계약 스키마에 맞음 |
| TASK-181 | 서버 도구 `tools/app_release.py`: `publish --apk --package --version-code --version-name`(검사 ①\~③, 크기·SHA-256 계산, 파일 이름 `marong-<버전 이름>-<버전 코드>.apk`, `release.json`은 임시 파일에 쓰고 이름 바꾸기, `paused` 지움, 최근 APK 3개만 남김, 거절은 종료 코드 2), `status`, `pause`, `resume` | SPEC-287, SPEC-288 | 릴리스 폴더(3.1, 3.2) | TASK-179 | GPT | 0.5 | TC-209\~212 통과 |
| TASK-182 | 노트북 명령 `bash deploy/ovh.sh app-release publish <APK>`·`status`·`pause`·`resume`: `output-metadata.json`에서 패키지·버전 코드·버전 이름·`outputFile`을 읽어(이름이 다르면 거절) APK와 함께 서버 임시 폴더로 보내고 서버 도구를 `marong` 사용자로 불러요 | SPEC-287, SPEC-288 | `deploy/ovh.sh` | TASK-181 | GPT | 0.25 | `bash -n deploy/ovh.sh` 통과, 메타데이터 읽기를 시험용 `output-metadata.json`(정상·이름 다름·파일 없음)으로 확인(TC-210의 노트북 쪽) |
| TASK-183 | 글 대화 메뉴(SCR-109)의 '자동 업데이트' 줄: `MarongPush.state().installUpdates`가 있을 때만, 켜짐·꺼짐+'켜기', `resumed`에서 다시 읽기. 문구는 화면 정의 그대로 | SPEC-300, SCR-109#update-on, #update-off, #update-none | `marong/app_chat_static/chat.js`, `chat.css` | 없음 | GPT | 0.5 | TC-225 통과, 낮·밤 테마와 360px 폭에서 줄이 넘치지 않음 |
| TASK-184 | 앱 논리 `AppUpdate.java`(안드로이드 API에 기대지 않는 부분): 6시간 규칙, 응답 해석(칸 검사, `url` 규칙), 응답 코드별 처리, 실패 세기(3번), 받은 파일 검사 ①②④와 인증서 SHA-256 집합 비교, 조용한 때 판단, 설치 결과 상태별 처리, `marong_update` 키(3.4) | SPEC-289\~294, SPEC-297 | 앱 | 없음 | GPT | 1 | `AppUpdateTest.java`에서 TC-213\~219 통과 |
| TASK-185 | 확인 작업 `AppUpdateJob.java`(JobService, 네트워크 필요): 묻기(쿠키 `CookieManager`, 사용자 에이전트 `MarongApp/<버전 이름>`, `Accept`, 넘겨주기 안 따라감, 연결 15초·읽기 30초), 받기(캐시 `update/marong-<버전 코드>.apk.part` → `.apk`, 크기 넘으면 멈춤), 검사(`getPackageArchiveInfo`), 조용하지 않으면 15분 뒤 다시, 조용하면 `PackageInstaller` 세션(안드로이드 12 이상 `USER_ACTION_NOT_REQUIRED`) | SPEC-289\~292, SPEC-294, SPEC-295 | API-141, API-142, 앱 | TASK-184 | GPT | 1 | 에뮬레이터 TC-220·222·223·224 통과(TASK-190) |
| TASK-186 | 결과와 업데이트 뒤 `AppUpdateReceiver.java`: 설치 결과(성공 → 정리, 사용자 확인 → 알림 SCR-130 버전마다 한 번, 실패 → 실패 1번), `MY_PACKAGE_REPLACED`(채널 다시 만들기, 하루 한 번 작업 다시 잡기, 기록 정리). `Channels.java`에 채널 `marong_update` '앱 업데이트'(중요도 낮음), 알림 id 301, 글은 3.3 | SPEC-296\~298, SCR-130#shown, #locked, #none | 앱 | TASK-184 | GPT | 0.5 | 에뮬레이터 TC-220·221 통과 |
| TASK-187 | 확인 계기: `MainActivity`·`ChatActivity`가 화면에 나올 때, `MarongMessagingService`가 데이터 메시지를 받을 때 작업을 잡고, 처음 실행·업데이트 뒤 하루 한 번 작업을 잡아요 | SPEC-289 | 앱 | TASK-185 | GPT | 0.25 | 에뮬레이터에서 세 계기마다 서버(시험 사이트)에 API-141 요청이 한 번, 6시간 안의 두 번째 계기는 요청 없음 |
| TASK-188 | 앱 연결: `MarongPushPlugin.state()`에 `installUpdates`(안드로이드 8 이상 `canRequestPackageInstalls()`), `openInstallSettings()`(`ACTION_MANAGE_UNKNOWN_APP_SOURCES`, 없으면 앱 정보 화면). 기기 보고(API-105)는 바꾸지 않아요 | SPEC-301 | 앱, SCR-109 | 없음 | GPT | 0.25 | 에뮬레이터에서 '켜기'가 설정을 열고, 돌아오면 줄이 '켜짐'(TC-225의 앱 쪽) |
| TASK-189 | 매니페스트: 권한 `REQUEST_INSTALL_PACKAGES`·`UPDATE_PACKAGES_WITHOUT_USER_ACTION`, `AppUpdateJob`(`BIND_JOB_SERVICE`, 내보내지 않음), `AppUpdateReceiver`(내보내지 않음, `MY_PACKAGE_REPLACED`). `app-config.test.cjs`의 권한 목록(TC-133)을 13개로 | SPEC-299 | 앱 | TASK-185, TASK-186 | GPT | 0.25 | TC-226 통과, `lintDebug` 오류 0 |
| TASK-190 | 에뮬레이터 시험: 시험 사이트(`test/support/emulator-site.cjs`)에 API-141·142를 더하고, 같은 디버그 키로 만든 버전 코드 5와 6(6은 커밋하지 않는 빌드 값) 두 APK로 업데이트를 돌려요 | SPEC-289\~298 | 앱, 시험 사이트 | TASK-185\~189 | GPT | 1 | TC-220\~224 통과, 결과(안드로이드 버전, 커밋, 걸린 시간)를 시험 계획에 적음 |
| TASK-191 | 서버 반영: 봇 파일(`marong/app_chat.py`, `marong/app_release.py`, `marong/app_chat_static/chat.js`·`chat.css`, `tools/app_release.py`), 릴리스 폴더(소유 `marong`, 0750), 백업·되돌리기 스크립트, 조용할 때 재시작 | SPEC-302 | 서버 | TASK-179\~183 | GPT | 0.25 | 반영 뒤 실제 주소의 API-141이 204(릴리스 없음), 로그 오류 0, 되돌리기 스크립트를 한 번 읽어 확인 |
| TASK-192 | 0.2.2 서명·설치: 동희님 노트북에서 릴리스 APK 빌드·서명(서명 키는 노트북에만), `app-release publish`로 0.2.2를 기준 릴리스로 올림, 현경님 폰에 손으로 한 번 설치하는 안내(위 '설치 안내 한 줄' 포함). CTX-020의 TASK-176(서명 APK)도 여기서 끝나요 | SPEC-287, SPEC-299 | 노트북, 서버, 폰 | TASK-190, TASK-191 | GPT(동희님 노트북) | 0.25 | 서명 APK의 크기·SHA-256 기록, API-141이 0.2.2(버전 코드 5)를 줌, 현경님 폰에 0.2.2가 깔리고 글 대화 메뉴가 '자동 업데이트: 켜짐' |
| TASK-193 | 실제 폰 확인: 다음 버전(0.2.3, 버전 코드 6)을 올려 현경님 폰이 확인 창 없이 바뀌는지, 삼성 자동 차단·잠자는 앱에서의 동작 | REQ-320, 기능 명세 7절 | 폰 | TASK-192 | GPT(동희님이 폰 확인) | 이틀 관찰 | TC-228·229 결과 기록. 안 되면 버그와 대안(사용자 확인 알림으로 동작함)을 기록 |

## 확인

- Must 명세(SPEC-284\~299, 301, 302)마다 작업이 있어요. SPEC-300(proposed)은 TASK-183이에요.
- API-141·142를 만지는 작업(TASK-180)은 계약의 모든 응답에 시험이 있어야 끝나요.
- 의존에 고리가 없어요. 모든 작업이 번호가 더 작은 작업에만 기대요(서버 179→180·181→182, 183 따로, 179\~183→191, 앱 184→185·186·188→187→189→190, 190·191→192→193).

## 11단계 진행

GPT가 TASK마다 상태·커밋·확인한 것을 적어요(AGENTS.md '구현을 시작할 때' 6).

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-179\~193 | 시작 전 | | |
