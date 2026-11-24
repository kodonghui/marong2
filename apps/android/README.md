# 마롱이 안드로이드 앱

웹 통화(`https://marong.corthex-hq.com`)를 그대로 여는 Capacitor 앱이에요. 화면을 끄거나 다른 앱을 써도 통화가 이어지고, 알림에서 끊을 수 있어요. 0.2.0부터 마롱이의 선톡·일정 알림을 앱 알림으로 받고, 약속한 시간에 마롱이가 거는 전화가 폰처럼 울려요. 0.2.1부터 글 대화는 통화와 따로 된 창에서 열려서 통화 중에 열어도 통화가 이어져요. 0.2.2부터 마롱이가 약속 없이 먼저 거는 전화(선 전화)도 울리고, 알림과 벨 화면에 '마롱이가 먼저 걸었어요'와 화두 한 줄이 나와요([call-first.md](../../docs/04-functional-spec/call-first.md) SPEC-267). 설계·명세·시험 결과는 [docs/android-app.md](../../docs/android-app.md)(1단계), [docs/app-chat.md](../../docs/app-chat.md)(2단계), [docs/app-ring.md](../../docs/app-ring.md)(3단계)에 있어요.

| 파일 | 하는 일 |
| --- | --- |
| `capacitor.config.json` | 앱 이름·패키지·통화 주소·상태 표시줄 기본값 |
| `www/error.html` | 통화 주소를 못 열 때의 화면(SCR-102) |
| `android/app/src/main/assets/marong_page.js` | 통화 주소에만 넣는 페이지 스크립트: 통화 시작·끝, 마이크 거절, 테마를 앱에 알리고, 이 폰을 서버에 보고하고(기기 보고), 약속 전화를 저절로 받고, 앱 통화 화면의 '글로도 이야기하기'를 숨겨요(0.2.1) |
| `android/app/src/main/java/com/corthexhq/marong/` | 통화 창(`MainActivity`)과 글 대화 창(`ChatActivity`, 0.2.1), 두 창의 웹뷰 처리와 이동 규칙(`MarongWindowPlugin`, `AppWindows`), 통화 유지 서비스·알림, 주소 규칙, FCM 받기(`MarongMessagingService`), 알림 채널, 벨 알림·벨 화면(`Ring`, `RingActivity`, 0.2.2부터 선 전화 글), 앱 연결(`MarongCall`, `MarongPush`) |
| `test/` | 페이지 스크립트·앱 설정 단위 시험, 실제 통화 화면·글 대화 화면 브라우저 시험, 목(mock) 통화 서버(`node test/support/call-site.cjs 8787`로 1단계 에뮬레이터 시험에도 써요), 목 글 대화 서버, 둘을 한 주소로 묶은 2·3단계 에뮬레이터 시험용 목 서버(`node test/support/emulator-site.cjs 8787 fid.txt`) |

```sh
npm ci
npm run sync
npm test
npm run test:browser   # Playwright가 있을 때
cp /키/폴더/google-services.json android/app/   # 빌드 때만
cd android && MARONG_KEYSTORE_PROPERTIES=/키/폴더/keystore.properties ./gradlew testDebugUnitTest assembleRelease lintDebug
rm app/google-services.json
```

서명 키와 `google-services.json`은 Git에 넣지 않아요. 자세한 내용은 문서 9절을 봐 주세요.

### 0.2.2 서명 준비

선 전화와 자동 업데이트가 들어간 APK의 패키지는 `com.corthexhq.marong`, 버전 코드는 5예요.
노트북의 운영용 `google-services.json`을 `android/app/`에 둔 상태에서 `npm ci`와 `npm run sync`를 실행해요.
서명 준비만 할 때는 `MARONG_KEYSTORE_PROPERTIES`를 비운 뒤 `android/`에서 `./gradlew assembleRelease`를 실행해요.
서명할 때는 위 빌드 명령에 노트북의 키 설정 경로를 지정해요. 게시할 때는 서명된 APK와 Gradle의
`output-metadata.json`을 같은 폴더에 두고 저장소에서 `bash deploy/ovh.sh app-release publish <APK>`를 실행해요.
릴리스 PR에 `marong/changelog/app-<버전 이름>.json`을 추가해요. 게시 뒤 저장소에서 `bash deploy/ovh.sh changelog put marong/changelog/app-<버전 이름>.json`과 `bash deploy/ovh.sh changelog check app-<버전 이름>`을 실행해 `history.json`의 버전 이름·코드·게시 날짜와 대조해요([SPEC-500·503](../../docs/04-functional-spec/admin-changelog.md#2-기능-표)).

깔고 나서 글 대화 메뉴의 ‘자동 업데이트’에서 ‘켜기’를 눌러 ‘이 출처 허용’을 켜 줘. 그러면 다음부터는 저절로 깔려.
