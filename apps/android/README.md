# 마롱이 안드로이드 앱

웹 통화(`https://marong.corthex-hq.com`)를 그대로 여는 Capacitor 앱이에요. 화면을 끄거나 다른 앱을 써도 통화가 이어지고, 알림에서 끊을 수 있어요. 설계·명세·시험 결과는 [docs/android-app.md](../../docs/android-app.md)에 있어요.

| 파일 | 하는 일 |
| --- | --- |
| `capacitor.config.json` | 앱 이름·패키지·통화 주소·상태 표시줄 기본값 |
| `www/error.html` | 통화 주소를 못 열 때의 화면(SCR-102) |
| `android/app/src/main/assets/marong_page.js` | 통화 주소에만 넣는 페이지 스크립트: 통화 시작·끝, 마이크 거절, 테마를 앱에 알려요 |
| `android/app/src/main/java/com/corthexhq/marong/` | 통화 유지 서비스·알림, 주소 규칙, 웹뷰 처리 |
| `test/` | 페이지 스크립트 단위 시험과 실제 통화 화면 브라우저 시험 |

```sh
npm ci
npm run sync
npm test
npm run test:browser   # Playwright가 있을 때
cd android && MARONG_KEYSTORE_PROPERTIES=/키/폴더/keystore.properties ./gradlew testDebugUnitTest assembleRelease
```

서명 키는 Git에 넣지 않아요. 자세한 내용은 문서 9절을 봐 주세요.
