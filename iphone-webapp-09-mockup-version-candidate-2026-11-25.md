# 아이폰 홈 화면 웹앱 알림 09단계 목업 고정 후보

2026-11-25 KST · 마롱이 Orca 항목 143 · A 배치 승인 · 파일 해시 승인 대기

[HTML 미리보기](design/iphone-home-webapp-notifications-version-candidate/index.html) · [화면별 링크](#화면별-링크) · [검증 결과](#검증-결과) · [파일별 SHA-256](#파일별-sha-256)

## 승인과 기준

| 근거 | 대조 결과 |
| --- | --- |
| 사용자님 직접 선택 | 항목 143 e2412의 “홈 화면 웹앱 알림을 눌러 받기”. |
| 08 화면 승인 | 항목 143 e2465와 위임 답변 `msg_3750576310ca`(요청 `msg_1d7c3fd2b2e6`). 승인 인덱스 `f97a94278b79f2e44d887461e16afa117fa2fc511c94e38fa26adfe8946e4599`, 와이어프레임 `a438de2f9c975a7a1581a7bfbc2bbe6fb5e27d43f2c41dcfb71c10e86b7fa631`, 08 메모 `425c5dcb17e3b2237d1ffa81703de169546414e4ce543a5329e8ceda8ad48ea0`과 그 메모의 화면별 SHA-256을 대조했습니다. [화면 정의](docs/08-screens/iphone-home-webapp-notifications/README.md) · [08 원본 해시](iphone-webapp-08-screen-checkpoint-2026-11-25.md#출력-파일-해시) |
| 09 방향 승인 | 항목 143 e2479와 오랑이 위임 답변 `msg_9ec5ad3b11a6`(요청 `msg_d7b980559a46`). “사용자님이 위임한 09단계 목업 방향은 추천 A로 승인해요.” 변경 화면의 동작을 상태 설명 바로 아래에 배치했습니다. |
| 비교 후보 보존 | 비교 메모 `cced10aa53317f97d0d536e61cdfc0cb539392173ef3bb0d748b049d65516f17`, e2479의 `iphone-webapp-09-mockup-review.zip` `430b6fbdf17e3606d12c029fa004269129e80c9a3e093fd7402422aa4d3c17c7`. 원본 후보 9개는 비교 메모와 같고 ZIP 파일 29개는 로컬의 해당 파일과 바이트가 같습니다. [09 비교 메모 및 원본 파일](iphone-webapp-09-mockup-checkpoint-2026-11-25.md#파일별-sha-256) |
| 저장소 기준 | 격리 작업 공간 HEAD와 원격 main `c82e3b18f05d56c7d332681c4d3b3e85d43fec32`. [AGENTS.md](AGENTS.md) · [09 단계 설정](.corthex/project.json) |
| 동결 토큰 | `design/base.tokens.json` `b1059ba5ad65ded788c49d69cd5a57062f721863f79363aa274c26fcd65cad0f`. 밤하늘(`color.a`)·군밤 크림(`color.b`), 글꼴·간격·조작 크기·초점 색을 사용했습니다. 새 토큰 0개. [토큰 원본](design/base.tokens.json) · [디자인 규칙](design/README.md#1-테마) |

## 열어서 확인하기

로컬 브라우저에서 [index.html](design/iphone-home-webapp-notifications-version-candidate/index.html)을 열고 **화면 상태**, **폭**, **테마**를 선택합니다. 같은 디렉터리의 `preview.css`, `tokens.css`, `fixtures.js`, `preview.js`, `assets/01-neutral.webp`, `assets/13-concerned.webp`가 렌더링에 필요합니다. 얼굴 파일 2개는 저장소의 기존 자산과 바이트가 같습니다. 테마 선택과 시뮬레이션 버튼은 검토용입니다. 화면 정의와 검증 기록 링크를 열 때는 저장소 경로를 유지합니다.

| 확인할 흐름 | 미리보기 조작과 기대 결과 |
| --- | --- |
| 지원·설정·메뉴 | SCR-109 문구는 “아이폰에서는 홈 화면에 추가한 뒤 내 마롱이에서 이 기기의 알림을 확인할 수 있어.”입니다. **내 마롱이**가 기존 SCR-165로 이어집니다. 일반 Safari의 설치 안내와 홈 화면 웹앱의 설치별 권한·등록·철회 상태를 각 상태로 확인할 수 있습니다. iOS 권한 팝업은 시스템이 표시합니다. [SCR-109](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md#ios-menu-copy) · [SCR-165 설정 상태](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#변경-상태) |
| 최초 진입과 접근 제한 | **알림과 통화 흐름 체험 → 사례 선택 → 시스템 알림 보기 → 알림 탭**. iOS 제어 영역인 SCR-230이 앱으로 이어지는 예시입니다. 알림에 대화 원문을 넣지 않습니다. 앱의 최초 확인 제목에 초점이 이동하고 **합성 응답 적용**에서 대상 조회 결과로 이어집니다. 접근 불가와 연결 미확인은 따로 표시합니다. 접근 불가에서 **글 대화로**는 알림 참조를 정리하고 기존 SCR-107 화면 정의 링크로 돌아갑니다. 검증된 글·선톡·일정 알림만 해당 방을 여는 예시를 표시합니다. [접근 불가](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-denied) · [연결 미확인](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-unavailable) · [iOS 알림](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md) |
| 유효한 받기·마이크 거절 | ‘유효한 약속 전화’는 별도 **받기**를 눌러 대기하고 합성 응답으로 연결합니다. ‘마이크 권한 거절’은 **받기**를 눌러도 수락 요청 0건이며 기존 SCR-002#mic-denied로 이어집니다. **다시 해 볼게**로 이전 화면을 다시 확인합니다. [받기](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-ready) · [기존 통화 상태](docs/08-screens/SCR-002.md) |
| 미수락 만료·선행 수락 | ‘재로그인 중 미수락 만료’는 로그인 예시 코드 `123456`을 입력하고 대상 재확인 뒤 만료를 봅니다. ‘받기 직전 미수락 만료’는 받기 응답에서 만료를 봅니다. 두 경우 모두 만료 확인 뒤 **일반 통화**를 직접 선택할 수 있습니다. ‘다른 기기의 선행 수락’은 이미 처리된 상태와 글 대화 복귀를 표시합니다. [미수락 만료](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-expired) · [이미 수락](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-answered) |
| 응답 유실과 재연결 | ‘받기 응답 유실’에서 **받기 → 합성 응답 적용 → 결과 확인**. 확인 중 기존 버튼의 위치와 초점을 유지합니다. 합성 응답을 두 번 적용하면 처음 수락한 합성 통화로 이어집니다. **끊기**에 초점을 둔 상태에서 연결 단절을 재현하면 통화 조작과 같은 합성 통화 ID를 유지합니다. 기존 음소거 상태도 복귀 뒤 유지합니다. [받기 결과 확인](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result) · [통화 재연결](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-reconnecting) |
| 기존 화면 연결과 닫기 | 연결 준비의 **닫기**는 준비 중인 연결을 취소하고 기존 글 대화 진입을 안내합니다. 통화를 종료한 뒤의 **다시 걸기**는 기존 발신의 별도 선택입니다. 미수락 만료에서의 **일반 통화**와 구분해 합성 조작을 확인했습니다. 로그인은 SCR-164의 기기 코드 흐름, 가입은 SCR-163의 기존 글 대화 진입을 참조합니다. [기존 통화 홈](docs/08-screens/SCR-001.md) · [로그인 복귀](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md) · [가입 성공](docs/08-screens/iphone-home-webapp-notifications/SCR-163.md) |

## 검증 결과

Windows 로컬 Chromium 158.0.8127.37과 Playwright WebKit 26.6에서 각각 360px·430px, 밤하늘·군밤 크림의 4개 조합을 실행했습니다. 조합마다 승인 상태 43개와 기존 연결 2개를 각각 하나의 프레임으로 렌더링했습니다. 8개 조합에서 승인 프레임 344개와 기존 연결 프레임 16개가 통과했습니다.

| 폭·테마 | 최소 터치 대상 | 최소 텍스트 대비 | 최소 조작 경계 대비 | 최소 초점 대비 | 본문 최대 줄 수 Chromium / WebKit |
| --- | ---: | ---: | ---: | ---: | ---: |
| 360px · 밤하늘 | 48×48px | 6.80:1 | 6.80:1 | 10.79:1 | 4 / 4 |
| 360px · 군밤 크림 | 48×48px | 6.03:1 | 6.49:1 | 6.75:1 | 4 / 4 |
| 430px · 밤하늘 | 48×48px | 6.80:1 | 6.80:1 | 10.79:1 | 4 / 3 |
| 430px · 군밤 크림 | 48×48px | 6.03:1 | 6.49:1 | 6.75:1 | 4 / 3 |

각 프레임의 CSS 폭과 터치 크기, 제품 영역의 가시 텍스트·활성 버튼 경계·초점 표시 색을 측정했습니다. 두 폭에서 가로 넘침·잘린 텍스트·얼굴 이미지 로드 실패는 각각 0건입니다. 한글 본문 최대 줄 수는 각 브라우저가 실제 렌더링한 값입니다. CORTHEX 토큰 검사에서 CSS 색 리터럴 24개 전부 동결 토큰과 일치했습니다. JavaScript 구문 검사와 한국어 `term-check.py`를 통과했습니다. 메모 링크 143개와 앵커 104개를 검사했으며, Chromium에서 상태별 링크 45개를 열어 각각의 대상에 도착했습니다.

엔진별 합성 조작 15개에서 최초 제목 초점, 결과 확인과 재연결 중 기존 초점 유지, 마이크 거절의 수락 요청 0건, 명시적인 일반 통화, 동일한 합성 통화 복귀를 다시 확인했습니다. 접근 불가에서 보호 데이터 비표시, 준비 취소, 기존 다시 걸기와 알림 전용 일반 통화의 구분도 확인했습니다. 렌더링과 합성 조작에서 외부 요청은 0건이었습니다.

두 엔진·두 폭·두 테마의 스크린샷을 조합별로 남겼습니다. 각 이미지에는 홈 화면 추가, 알림 꺼짐, 로그인 복귀, 접근 불가·연결 미확인, 시스템 알림, 유효한 받기·미수락 만료·선행 수락·결과 미확인, 마이크 거절, 재연결의 12개 프레임이 있습니다.

| 폭·테마 | Chromium | WebKit |
| --- | --- | --- |
| 360px · 밤하늘 | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-360-night.png) | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-360-night.png) |
| 360px · 군밤 크림 | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-360-chestnut.png) | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-360-chestnut.png) |
| 430px · 밤하늘 | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-430-night.png) | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-430-night.png) |
| 430px · 군밤 크림 | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-430-chestnut.png) | [이미지](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-430-chestnut.png) |

## 후속 실기기 확인

- iPhone의 홈 화면 설치, 실제 권한 팝업과 마이크 허용, 잠금 알림의 원문 비표시, 잠금 해제와 재로그인, VoiceOver 최초 제목·조작의 읽기 순서를 확인합니다.
- 실제 웹 푸시의 수신과 닫은 뒤 재도착, 일반 Web Push와 선언형 폴백의 설치별 중복 표시 여부를 확인합니다.
- iPhone과 Android의 약속 전화 양방향 선착순 수락, 잠금·앱 전환·망 전환 뒤 실제 동일 통화 ID와 양방향 오디오를 확인합니다. 일반 Safari의 기존 글·직접 통화와 Android의 벨·거절·글·일정 알림·APK 업데이트도 후속 회귀 시험에 포함합니다. [06 계약](iphone-webapp-06-version-candidate-2026-11-25.md) · [08 회귀 범위](iphone-webapp-08-screen-checkpoint-2026-11-25.md#검증-범위) · [기존 재연결 검증](docs/12-qa/BUG-114-web-call-reconnect.md)

## 화면별 링크

상태 링크는 360px·밤하늘로 열립니다. HTML의 선택기에서 다른 폭과 테마로 바꿀 수 있습니다. 여기에서 08 정의와 09 미리보기를 연결하며 08 원본 파일은 보존했습니다.

| 08 상태 | 표시 | 미리보기 |
| --- | --- | --- |
| [SCR-001#notice-ring-ready](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-ready) | 카드 안 동작 | [약속 전화가 와 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-ready) |
| [SCR-001#notice-ring-accepting](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-accepting) | 카드 안 동작 | [전화 받는 중](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-accepting) |
| [SCR-001#notice-ring-expired](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-expired) | 카드 안 동작 | [약속 전화 시간이 지났어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-expired) |
| [SCR-001#notice-ring-answered](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-answered) | 카드 안 동작 | [이미 받은 전화야](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-answered) |
| [SCR-001#notice-ring-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-unavailable) | 카드 안 동작 | [지금은 이 전화를 받을 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-unavailable) |
| [SCR-001#notice-ring-result](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result) | 카드 안 동작 | [전화 받기 결과를 확인해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-result) |
| [SCR-001#notice-ring-result-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result-loading) | 카드 안 동작 | [받기 결과 확인 중](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-result-loading) |
| [SCR-001#notice-ring-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-denied) | 카드 안 동작 | [이 알림을 열 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-denied) |
| [SCR-001#notice-ring-offline](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-offline) | 카드 안 동작 | [지금 전화 상태를 확인할 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-offline) |
| [SCR-001#notice-ring-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-rate-limited) | 카드 안 동작 | [잠시 뒤 다시 확인해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-ring-rate-limited) |
| [SCR-001#notice-call-ended](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-call-ended) | 카드 안 동작 | [통화가 끝났어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-001-notice-call-ended) |
| [SCR-002#notice-connecting](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-connecting) | 카드 안 동작 | [통화 연결을 준비하고 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-002-notice-connecting) |
| [SCR-002#notice-reconnecting](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-reconnecting) | 카드 안 동작 | [같은 통화에 다시 연결 중이야](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-002-notice-reconnecting) |
| [SCR-002#notice-call-check](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-call-check) | 카드 안 동작 | [지금 통화 연결을 확인할 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-002-notice-call-check) |
| [SCR-107#notice-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-loading) | 상태 안내 | [알림을 확인하고 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-107-notice-loading) |
| [SCR-107#notice-room](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-room) | 카드 안 동작 | [글 대화](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-107-notice-room) |
| [SCR-107#notice-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-denied) | 카드 안 동작 | [이 알림을 열 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-107-notice-denied) |
| [SCR-107#notice-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-unavailable) | 카드 안 동작 | [아직 알림을 확인할 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-107-notice-unavailable) |
| [SCR-107#notice-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-rate-limited) | 카드 안 동작 | [잠시 뒤 알림을 확인해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-107-notice-rate-limited) |
| [SCR-109#ios-menu-copy](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md#ios-menu-copy) | 카드 안 동작 | [알림 안내](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-109-ios-menu-copy) |
| [SCR-163#ios-join-done](docs/08-screens/iphone-home-webapp-notifications/SCR-163.md#ios-join-done) | 카드 안 동작 | [가입됐어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-163-ios-join-done) |
| [SCR-164#notice-login](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md#notice-login) | 카드 안 동작 | [로그인한 뒤 알림을 확인할게](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-164-notice-login) |
| [SCR-164#notification-settings-login](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md#notification-settings-login) | 카드 안 동작 | [알림 설정을 보려면 로그인해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-164-notification-settings-login) |
| [SCR-165#ios-guide](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#ios-guide) | 카드 안 동작 | [홈 화면에 추가](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-ios-guide) |
| [SCR-165#notify-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-loading) | 상태 안내 | [알림 설정 확인 중](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-loading) |
| [SCR-165#notify-unsupported](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-unsupported) | 카드 안 동작 | [이 기기에서는 알림을 켤 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-unsupported) |
| [SCR-165#notify-off](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-off) | 카드 안 동작 | [이 기기 알림이 꺼져 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-off) |
| [SCR-165#notify-register](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-register) | 카드 안 동작 | [알림 등록이 필요해](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-register) |
| [SCR-165#notify-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-denied) | 카드 안 동작 | [기기에서 알림이 꺼져 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-denied) |
| [SCR-165#notify-active](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-active) | 카드 안 동작 | [이 기기에서 알림을 받을 수 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-active) |
| [SCR-165#notify-saving](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-saving) | 카드 안 동작 | [변경한 알림 설정을 확인 중이야](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-saving) |
| [SCR-165#notify-revoked](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-revoked) | 카드 안 동작 | [이 기기에서 알림을 껐어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-revoked) |
| [SCR-165#notify-expired](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-expired) | 카드 안 동작 | [알림을 다시 등록해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-expired) |
| [SCR-165#notify-conflict](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-conflict) | 카드 안 동작 | [알림 설정이 바뀌었어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-conflict) |
| [SCR-165#notify-input-error](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-input-error) | 카드 안 동작 | [알림 설정을 확인하지 못했어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-input-error) |
| [SCR-165#notify-blocked](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-blocked) | 카드 안 동작 | [여기에서 알림 설정을 열 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-blocked) |
| [SCR-165#notify-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-rate-limited) | 카드 안 동작 | [잠시 뒤 알림 설정을 확인해 줘](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-rate-limited) |
| [SCR-165#notify-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-unavailable) | 카드 안 동작 | [지금 알림 상태를 확인할 수 없어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-165-notify-unavailable) |
| [SCR-230#notice-reply](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-reply) | iOS 시스템 | [마롱이](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-230-notice-reply) |
| [SCR-230#notice-proactive](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-proactive) | iOS 시스템 | [마롱이](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-230-notice-proactive) |
| [SCR-230#notice-schedule](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-schedule) | iOS 시스템 | [마롱이](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-230-notice-schedule) |
| [SCR-230#notice-ring](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-ring) | iOS 시스템 | [마롱이](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-230-notice-ring) |
| [SCR-230#notice-locked](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-locked) | iOS 시스템 | [잠금 해제 뒤 열 수 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-230-notice-locked) |
| [SCR-002#talking](docs/08-screens/SCR-002.md) | 기존 화면 연결 | [통화 중이야](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-002-talking) |
| [SCR-002#mic-denied](docs/08-screens/SCR-002.md) | 기존 화면 연결 | [마이크를 허용해야 통화할 수 있어](design/iphone-home-webapp-notifications-version-candidate/index.html?width=360&theme=night#scr-002-mic-denied) |

[SCR-101 Android 기존 호출 처리](docs/08-screens/iphone-home-webapp-notifications/SCR-101.md)는 후속 회귀 참조입니다.

## 파일별 SHA-256

| 파일 | SHA-256 |
| --- | --- |
| [01-neutral.webp](design/iphone-home-webapp-notifications-version-candidate/assets/01-neutral.webp) | `08f201eb9f98a406cdd0b3604aac70901ea92039cd95c6fd58b16a149713e171` |
| [13-concerned.webp](design/iphone-home-webapp-notifications-version-candidate/assets/13-concerned.webp) | `43a9d66c3f656c0eb1ada12f08f1c7e3d7b9534a99c412bb60cbdc59bb143b50` |
| [chromium-360-chestnut.png](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-360-chestnut.png) | `7cdbcb89bba3e50282eebc5c08eb6d77e0a91e6c018b3ed3204100830ce68b5c` |
| [chromium-360-night.png](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-360-night.png) | `c8f7183227d9514fbdfb934a2b97a391065859b35168b0e3f97106c3ac7bf3d5` |
| [chromium-430-chestnut.png](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-430-chestnut.png) | `d4ed27da9df21f5affaeec8d595106133943ea68439bc1d676ecaac500a30c64` |
| [chromium-430-night.png](design/iphone-home-webapp-notifications-version-candidate/captures/chromium-430-night.png) | `db621902d2bcb3de31d05fec3f2506ccc6c011e9d7e5976314b46da4dc96fc73` |
| [webkit-360-chestnut.png](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-360-chestnut.png) | `4081566a1e6dc59375a1dcb424e26922121c6b53fff8185d7bc624e75cc734a5` |
| [webkit-360-night.png](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-360-night.png) | `fcba1ac261f73a910731b4f513f18f320bf32b85432160e718615bceedfc9908` |
| [webkit-430-chestnut.png](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-430-chestnut.png) | `1d9822ea970904e1b3f3a3024fa3c0f49ec0fdd226f590e613ad3f9c2fab1441` |
| [webkit-430-night.png](design/iphone-home-webapp-notifications-version-candidate/captures/webkit-430-night.png) | `85fc978887f114584674e25939be649fd3fef6f23602110ed949bca117d3246d` |
| [fixtures.js](design/iphone-home-webapp-notifications-version-candidate/fixtures.js) | `4d01a8704e35a175ef86aa3ed5d710a240e804a5e740c967f4e0732cf015028e` |
| [index.html](design/iphone-home-webapp-notifications-version-candidate/index.html) | `b69626e650a73cf6a95330007a8d1ff6903b73723e8a0e4696c23caf4cc0404f` |
| [preview.css](design/iphone-home-webapp-notifications-version-candidate/preview.css) | `d6a84292a729a44b02b79602505c93142c485298c5c20dfda113e5d81be83fcd` |
| [preview.js](design/iphone-home-webapp-notifications-version-candidate/preview.js) | `3d5f00c3b2c9a6a143b80c3b7a2aefc08e44e7c48c464fe2747d4ad6fa21934b` |
| [tokens.css](design/iphone-home-webapp-notifications-version-candidate/tokens.css) | `58b82a98efa1384452731c927a8b86e9c6b92415d2458f1d744406beff8a1ad5` |

이 메모의 SHA-256은 Orca 완료 기록에서 확인할 수 있습니다. 파일 해시 고정은 별도 체크포인트에서 결정합니다.
