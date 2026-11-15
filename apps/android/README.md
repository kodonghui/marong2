# 마롱이 안드로이드 앱

웹 통화(`https://marong.corthex-hq.com`)를 그대로 여는 Capacitor 앱이에요. 화면을 끄거나 다른 앱을 써도 통화가 이어지고, 알림에서 끊을 수 있어요. 0.2.0부터 마롱이의 선톡·일정 알림을 앱 알림으로 받고, 약속한 시간에 마롱이가 거는 전화가 폰처럼 울려요. 설계·명세·시험 결과는 [docs/android-app.md](../../docs/android-app.md)(1단계), [docs/app-chat.md](../../docs/app-chat.md)(2단계), [docs/app-ring.md](../../docs/app-ring.md)(3단계)에 있어요.

| 파일 | 하는 일 |
| --- | --- |
| `capacitor.config.json` | 앱 이름·패키지·통화 주소·상태 표시줄 기본값 |
| `www/error.html` | 통화 주소를 못 열 때의 화면(SCR-102) |
| `android/app/src/main/assets/marong_page.js` | 통화 주소에만 넣는 페이지 스크립트: 통화 시작·끝, 마이크 거절, 테마를 앱에 알리고, 이 폰을 서버에 보고하고(기기 보고), 약속 전화를 저절로 받아요 |
| `android/app/src/main/java/com/corthexhq/marong/` | 통화 유지 서비스·알림, 주소 규칙, 웹뷰 처리, FCM 받기(`MarongMessagingService`), 알림 채널, 벨 알림·벨 화면(`Ring`, `RingActivity`), 앱 연결(`MarongCall`, `MarongPush`) |
| `test/` | 페이지 스크립트·앱 설정 단위 시험, 실제 통화 화면·글 대화 화면 브라우저 시험, 대역 통화 서버(`node test/support/call-site.cjs 8787`로 에뮬레이터 시험에도 써요)와 대역 글 대화 서버 |

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
