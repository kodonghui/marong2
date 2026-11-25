# 아이폰 홈 화면 웹앱 알림 09단계 목업 방향 체크포인트

2026-11-25 KST · 마롱이 Orca 항목 143 · 방향 승인 대기

[HTML 미리보기](design/iphone-home-webapp-notifications-candidates/index.html) · [상태별 미리보기](#상태별-미리보기) · [검증 결과](#검증-결과)

## 비교와 추천

| 후보 | 배치 | 검토 결과 |
| --- | --- | --- |
| **A · 카드 안 동작 (추천)** | 상태 설명 바로 아래에 버튼. 설치별 알림 동의, 접근 불가 복귀, 받기·일반 통화·결과 확인을 해당 안내와 함께 읽습니다. | 알림 탭 뒤 사용자가 방금 확인한 상태와 할 수 있는 동작을 함께 볼 수 있습니다. 특히 미수락 만료나 수락 결과 미확인처럼 다음 행동이 달라지는 화면에서 가까이 있습니다. 상태 문구의 길이에 따라 화면 사이 버튼의 높이는 달라질 수 있습니다. |
| **B · 하단 동작** | 같은 버튼을 화면 하단의 동작 영역에 둡니다. 화면이 길어지면 영역도 아래로 이어집니다. | 받기·끊기 등 한 손으로 자주 누르는 동작의 위치를 쉽게 찾을 수 있습니다. 접근 불가나 만료 설명을 읽은 뒤 하단 버튼까지 다시 시선을 옮깁니다. |

**A를 추천합니다.** 진입 직후에는 약속 전화의 수락 가능 여부나 접근 결과를 먼저 읽게 됩니다. 필요한 동작을 그 결과에 붙이는 편이 명시적 수락이나 별도 일반 통화 선택을 이해하기 쉽습니다. 양쪽의 상태 제목·본문·조작 순서·활성 조건은 같습니다. 방향을 선택하면 그 안을 검토용 화면에 적용하고 별도 09 고정 체크포인트에서 확인합니다.

- 대표 10개는 A/B를 같은 폭과 테마에서 나란히 비교합니다. 공용 상태 33개와 기존 통화·마이크 거절 연결 2개는 한 번씩 표시합니다. 기존 화면 연결 예시는 바뀌는 영역과 상태의 연속성을 보여 줍니다. [고정 08 화면 인덱스](docs/08-screens/iphone-home-webapp-notifications/README.md)
- 기존 마롱이 밤하늘(`color.a`)과 군밤 크림(`color.b`), `font.body`, 간격·버튼 크기·초점 색을 사용합니다. 통화 표정은 기존 `01-neutral.webp`와 `13-concerned.webp`를 씁니다. 너비와 세로 캔버스는 목업에서 비교하기 위한 크기입니다. 테마 스위치는 검토용입니다. 실제 테마 시각과 통화 상태 유지는 기존 디자인 계약을 따릅니다. 사용한 신규 토큰은 0개입니다. [기존 디자인 규칙](design/README.md#1-테마) · [동결 토큰](design/base.tokens.json)
- 모의 조작은 HTML 상단 **알림과 통화 흐름 체험**에서 사례를 고른 뒤 **시스템 알림 보기 → 알림 탭 → 합성 응답 적용** 순서로 진행합니다. 결과 확인 등 추가 요청도 **합성 응답 적용**으로 진행합니다. 로그인 예시에는 합성 숫자 `123456`을 씁니다. 미리보기의 네트워크 요청과 실제 알림·녹음은 0건입니다.

## 승인 근거와 원본

| 결정 또는 기준 | 증거 |
| --- | --- |
| 수신 방식 | 항목 143 e2412 사용자님 직접 선택 “홈 화면 웹앱 알림을 눌러 받기”. |
| 08 화면과 09 검증 조건 | 항목 143 e2465, 오랑이 위임 승인 `msg_3750576310ca` 및 요청 `msg_1d7c3fd2b2e6`. 43개 상태 및 기존 연결, SCR-109 안내와 진입, 최초 제목 초점·결과 확인 및 재연결 중 기존 초점, 마이크 거절 때 수락 0건을 적용했습니다. 방향 A/B는 선택 대기입니다. |
| 기준 커밋 | 원격 main과 격리 작업 공간 HEAD `c82e3b18f05d56c7d332681c4d3b3e85d43fec32`. [작업 규칙](AGENTS.md) · [단계 설정](.corthex/project.json) |
| 화면 정의 인덱스 | `f97a94278b79f2e44d887461e16afa117fa2fc511c94e38fa26adfe8946e4599`. [08 화면 정의 인덱스](docs/08-screens/iphone-home-webapp-notifications/README.md) |
| 와이어프레임 | `a438de2f9c975a7a1581a7bfbc2bbe6fb5e27d43f2c41dcfb71c10e86b7fa631`. [08 와이어프레임](docs/08-screens/wireframes-iphone-home-webapp-notifications.draft.html) |
| 08 메모와 화면별 파일 | 메모 `425c5dcb17e3b2237d1ffa81703de169546414e4ce543a5329e8ceda8ad48ea0`. 메모의 인덱스·화면별 문서 9개·와이어프레임 11개 SHA-256 전체 일치. [08 메모의 원본 해시](iphone-webapp-08-screen-checkpoint-2026-11-25.md#출력-파일-해시) |
| 토큰 기준 | `b1059ba5ad65ded788c49d69cd5a57062f721863f79363aa274c26fcd65cad0f`. [기존 토큰 파일](design/base.tokens.json) |

## 대표 조작과 상태 구분

| 상황 | 화면과 조건 |
| --- | --- |
| 일반 Safari에서 설치 정보 확인 | SCR-109에 “아이폰에서는 홈 화면에 추가한 뒤 내 마롱이에서 이 기기의 알림을 확인할 수 있어.”를 적용했습니다. 기존 **내 마롱이**가 SCR-165로 이어집니다. Safari 공유 메뉴와 iOS 권한 팝업은 시스템이 제어합니다. 기존 Android는 08 인덱스의 기존 화면 연결을 사용합니다. [SCR-109](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md#ios-menu-copy) · [SCR-165](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md) |
| 설치별 설정 | 웹앱에서 **알림 켜기**를 선택한 뒤 상태를 확인합니다. 허용·거절·등록 필요·철회·만료·오프라인은 별개 상태입니다. 이 기기에서 설정을 바꿉니다. [설정 상태](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#변경-상태) |
| iOS 알림과 최초 진입 | SCR-230은 iOS가 제어하는 잠금 및 시스템 알림 표면입니다. 목업의 알림 탭은 대상 조회를 시작하며 최초 확인 제목에 초점을 둡니다. 글 대화로 이동할 때도 조회 후 올바른 방을 사용합니다. 잠금 화면에는 대화 원문을 넣지 않습니다. [SCR-230](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md) · [SCR-107](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md) |
| 접근 불가 | 타 계정·존재하지 않는 대상 등 승인 계약에서 같은 404로 정의한 조건은 “이 알림을 열 수 없어”와 기존 글 대화 돌아가기를 표시합니다. 대상의 원문, 계정, 식별자를 추가로 표시하지 않습니다. [접근 불가 상태](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-denied) |
| 연결 미확인 | 초기 진입의 연결 미확인은 SCR-107, 통화 준비 결과를 확인할 수 없을 때는 SCR-002입니다. SCR-002의 **연결 확인**은 기존 연결만 확인합니다. [진입 연결 미확인](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-unavailable) · [통화 연결 미확인](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-call-check) |
| 유효한 받기와 마이크 거절 | 탭으로 대상만 확인합니다. **받기**를 눌렀을 때 현재 마이크 준비를 확인하고, 거절이면 기존 SCR-002#mic-denied로 이어지며 수락 요청은 0건입니다. 허용 후에만 합성 수락을 시작합니다. [받기](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-ready) · [기존 마이크 거절](docs/08-screens/SCR-002.md) |
| 로그인 도중 또는 받기 직전 미수락 만료 | 다시 로그인하거나 버튼을 눌렀을 때 서버 확인 결과로 만료를 표시합니다. 일반 통화는 만료 제목과 안내를 읽은 뒤 사용자가 **일반 통화**를 별도로 눌러 시작합니다. [로그인 화면](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md#notice-login) · [만료](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-expired) |
| 다른 기기의 선행 수락 | “이미 받은 전화야”와 글 대화 복귀를 표시합니다. 기기 신원, 일반 통화 및 수락 버튼은 표시하지 않습니다. [이미 수락](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-answered) |
| 받기 응답 유실 | **결과 확인**에서 시작합니다. 응답을 기다리는 동안 동일 조작과 초점을 유지합니다. 합성 결과에서 이미 성공한 수락이 확인되면 기존 통화로 복귀합니다. 결과 확인의 재조작이나 재연결은 새 수락을 만들어 내지 않습니다. [결과 미확인](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result) |
| 같은 통화에 재연결 | 기존 통화 조작의 초점을 유지하면서 진행을 읽게 합니다. 목업은 합성 통화 ID로 같은 연결을 검증했습니다. 잠금·앱 전환·망 전환 뒤 같은 실제 통화 ID와 양방향 오디오는 실제 기기 검사 대상입니다. [재연결](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-reconnecting) |

## 검증 결과

Chromium 158.0.8127.37, Playwright WebKit 26.6을 Windows에서 로컬 파일로 실행했습니다. 각 엔진에서 폭 2개 × 테마 2개 × 승인 상태 43개를 검사했습니다. 조합별 승인 프레임은 53개(A/B 20개와 공용 33개)이며, 기존 연결 프레임은 별도 2개입니다. 총 승인 프레임 424개와 기존 연결 16개를 렌더링했습니다.

| 폭·테마 | 최소 터치 대상 | 최소 텍스트 대비 | 최소 조작 경계 대비 | 최소 초점 대비 | 본문 최대 줄 수 Chromium / WebKit |
| --- | ---: | ---: | ---: | ---: | ---: |
| 360px · 밤하늘 | 48×48px | 6.80:1 | 6.80:1 | 10.79:1 | 4 / 4 |
| 360px · 군밤 크림 | 48×48px | 6.03:1 | 6.08:1 | 6.27:1 | 4 / 4 |
| 430px · 밤하늘 | 48×48px | 6.80:1 | 6.80:1 | 10.79:1 | 4 / 3 |
| 430px · 군밤 크림 | 48×48px | 6.03:1 | 6.08:1 | 6.27:1 | 4 / 3 |

- `getBoundingClientRect`로 목업의 정확한 폭과 터치 대상 두 축을 확인했습니다. 상태 제목·본문·버튼·입력 등 제품 영역의 텍스트와 활성 조작 테두리, 초점 표시의 계산 색을 측정했습니다. 화면 경계를 넘은 텍스트·요소 0건, 실제 360px·430px 브라우저 폭 표본의 가로 넘침 0건, 사용한 얼굴 파일 로드 실패 0건이었습니다. 글꼴의 실제 선택과 줄바꿈은 Windows 브라우저의 결과입니다.
- 엔진별 13개 합성 조작 검사에서 최초 진입 제목 초점, A/B의 요청 중 기존 조작과 초점 유지, 결과 중복 조작 차단과 결과 확인 뒤 기존 합성 통화, 재연결 전후 기존 초점을 확인했습니다. 유효한 수락, 마이크 거절에서 수락 0건, 재로그인 도중 및 받기 직전 만료, 다른 기기의 선행 수락, 일반 통화의 명시 선택, 세 가지 글 알림의 방 진입, 접근·연결 미확인의 분리, 메뉴의 정확한 문구와 설치별 설정 조작을 확인했습니다.
- 고정 화면 ID·문구·조작, 문서 링크 132개와 앵커 104개, 상대 자산 경로를 검사했습니다. 승인 상태 43개와 기존 연결 2개의 딥 링크를 Chromium에서 열어 해당 상태에 도착했습니다. CORTHEX 토큰 검사에서 CSS 색 리터럴 24개 중 토큰 밖 색 0개였습니다. `term-check.py` 용어 검사와 JavaScript 구문 검사를 통과했습니다.
- Chromium 이미지에서 네 조합의 알림 꺼짐·접근 불가·유효한 받기·미수락 만료·받기 결과 미확인·재연결을 확인했습니다. 360px에는 iOS 시스템 약속 전화 알림을 추가했습니다. [360px 군밤 크림](design/iphone-home-webapp-notifications-candidates/preview-360-chestnut.png) · [360px 밤하늘](design/iphone-home-webapp-notifications-candidates/preview-360-night.png) · [430px 군밤 크림](design/iphone-home-webapp-notifications-candidates/preview-430-chestnut.png) · [430px 밤하늘](design/iphone-home-webapp-notifications-candidates/preview-430-night.png)

## 남은 기기 확인

- iOS의 설치·알림·마이크 권한, 홈 화면 웹앱 열기와 실제 잠금 해제 경로, VoiceOver에서 최초 제목과 유지되는 조작의 읽기 순서를 확인합니다.
- 실제 전달과 닫은 알림의 재도착, 설치별 단일 표시, 잠금 화면 원문 미표시를 일반 Web Push와 검증 후보인 선언형 폴백 각각에서 확인합니다.
- 실제 약속 전화의 아이폰·Android 동시 수락과 최초 연결, iPhone 잠금·앱 전환·망 전환 뒤 같은 통화 ID와 양방향 오디오를 검사합니다. Safari 일반 탭과 기존 Android는 08에서 정한 회귀 범위를 사용합니다. [고정 06 계약](iphone-webapp-06-version-candidate-2026-11-25.md) · [08 회귀·실기기 조건](iphone-webapp-08-screen-checkpoint-2026-11-25.md#검증-범위)

## 상태별 미리보기

상태 링크의 기본 폭은 360px, 기본 테마는 밤하늘입니다. 페이지 위에서 바꿀 수 있습니다.

| 08 상태 | 표시 | 미리보기 |
| --- | --- | --- |
| [SCR-001#notice-ring-ready](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-ready) | A/B | [약속 전화가 와 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-ready) |
| [SCR-001#notice-ring-accepting](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-accepting) | 공용 | [전화 받는 중](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-accepting) |
| [SCR-001#notice-ring-expired](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-expired) | A/B | [약속 전화 시간이 지났어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-expired) |
| [SCR-001#notice-ring-answered](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-answered) | A/B | [이미 받은 전화야](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-answered) |
| [SCR-001#notice-ring-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-unavailable) | 공용 | [지금은 이 전화를 받을 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-unavailable) |
| [SCR-001#notice-ring-result](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result) | A/B | [전화 받기 결과를 확인해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-result) |
| [SCR-001#notice-ring-result-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-result-loading) | 공용 | [받기 결과 확인 중](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-result-loading) |
| [SCR-001#notice-ring-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-denied) | 공용 | [이 알림을 열 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-denied) |
| [SCR-001#notice-ring-offline](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-offline) | 공용 | [지금 전화 상태를 확인할 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-offline) |
| [SCR-001#notice-ring-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-rate-limited) | 공용 | [잠시 뒤 다시 확인해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-ring-rate-limited) |
| [SCR-001#notice-call-ended](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-call-ended) | 공용 | [통화가 끝났어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-001-notice-call-ended) |
| [SCR-002#notice-connecting](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-connecting) | 공용 | [통화 연결을 준비하고 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-002-notice-connecting) |
| [SCR-002#notice-reconnecting](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-reconnecting) | A/B | [같은 통화에 다시 연결 중이야](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-002-notice-reconnecting) |
| [SCR-002#notice-call-check](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md#notice-call-check) | 공용 | [지금 통화 연결을 확인할 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-002-notice-call-check) |
| [SCR-107#notice-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-loading) | 공용 | [알림을 확인하고 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-107-notice-loading) |
| [SCR-107#notice-room](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-room) | 공용 | [글 대화](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-107-notice-room) |
| [SCR-107#notice-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-denied) | A/B | [이 알림을 열 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-107-notice-denied) |
| [SCR-107#notice-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-unavailable) | A/B | [아직 알림을 확인할 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-107-notice-unavailable) |
| [SCR-107#notice-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md#notice-rate-limited) | 공용 | [잠시 뒤 알림을 확인해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-107-notice-rate-limited) |
| [SCR-109#ios-menu-copy](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md#ios-menu-copy) | 공용 | [알림 안내](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-109-ios-menu-copy) |
| [SCR-163#ios-join-done](docs/08-screens/iphone-home-webapp-notifications/SCR-163.md#ios-join-done) | 공용 | [가입됐어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-163-ios-join-done) |
| [SCR-164#notice-login](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md#notice-login) | 공용 | [로그인한 뒤 알림을 확인할게](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-164-notice-login) |
| [SCR-164#notification-settings-login](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md#notification-settings-login) | 공용 | [알림 설정을 보려면 로그인해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-164-notification-settings-login) |
| [SCR-165#ios-guide](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#ios-guide) | A/B | [홈 화면에 추가](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-ios-guide) |
| [SCR-165#notify-loading](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-loading) | 공용 | [알림 설정 확인 중](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-loading) |
| [SCR-165#notify-unsupported](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-unsupported) | 공용 | [이 기기에서는 알림을 켤 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-unsupported) |
| [SCR-165#notify-off](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-off) | A/B | [이 기기 알림이 꺼져 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-off) |
| [SCR-165#notify-register](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-register) | 공용 | [알림 등록이 필요해](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-register) |
| [SCR-165#notify-denied](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-denied) | 공용 | [기기에서 알림이 꺼져 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-denied) |
| [SCR-165#notify-active](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-active) | A/B | [이 기기에서 알림을 받을 수 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-active) |
| [SCR-165#notify-saving](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-saving) | 공용 | [변경한 알림 설정을 확인 중이야](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-saving) |
| [SCR-165#notify-revoked](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-revoked) | 공용 | [이 기기에서 알림을 껐어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-revoked) |
| [SCR-165#notify-expired](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-expired) | 공용 | [알림을 다시 등록해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-expired) |
| [SCR-165#notify-conflict](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-conflict) | 공용 | [알림 설정이 바뀌었어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-conflict) |
| [SCR-165#notify-input-error](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-input-error) | 공용 | [알림 설정을 확인하지 못했어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-input-error) |
| [SCR-165#notify-blocked](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-blocked) | 공용 | [여기에서 알림 설정을 열 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-blocked) |
| [SCR-165#notify-rate-limited](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-rate-limited) | 공용 | [잠시 뒤 알림 설정을 확인해 줘](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-rate-limited) |
| [SCR-165#notify-unavailable](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md#notify-unavailable) | 공용 | [지금 알림 상태를 확인할 수 없어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-165-notify-unavailable) |
| [SCR-230#notice-reply](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-reply) | 공용 | [마롱이](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-230-notice-reply) |
| [SCR-230#notice-proactive](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-proactive) | 공용 | [마롱이](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-230-notice-proactive) |
| [SCR-230#notice-schedule](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-schedule) | 공용 | [마롱이](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-230-notice-schedule) |
| [SCR-230#notice-ring](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-ring) | 공용 | [마롱이](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-230-notice-ring) |
| [SCR-230#notice-locked](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md#notice-locked) | 공용 | [잠금 해제 뒤 열 수 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-230-notice-locked) |
| [SCR-002#talking](docs/08-screens/SCR-002.md) | 기존 화면 연결 | [통화 중이야](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-002-talking) |
| [SCR-002#mic-denied](docs/08-screens/SCR-002.md) | 기존 화면 연결 | [마이크를 허용해야 통화할 수 있어](design/iphone-home-webapp-notifications-candidates/index.html?width=360&theme=night#scr-002-mic-denied) |

## 파일별 SHA-256

| 파일 | SHA-256 |
| --- | --- |
| [fixtures.js](design/iphone-home-webapp-notifications-candidates/fixtures.js) | `4d01a8704e35a175ef86aa3ed5d710a240e804a5e740c967f4e0732cf015028e` |
| [index.html](design/iphone-home-webapp-notifications-candidates/index.html) | `8cc52c850cd447d48dbb5ceccc13a050cb77a9602bb3e1613867eb1931ecb8b9` |
| [preview-360-chestnut.png](design/iphone-home-webapp-notifications-candidates/preview-360-chestnut.png) | `370b46171590911bb3882b2fe4f78b4ba6fecd33a67df3e6441d67a8531f7b9f` |
| [preview-360-night.png](design/iphone-home-webapp-notifications-candidates/preview-360-night.png) | `c14b3d417f6a8886849b1a44ac2d2d4cc765c64cd76a82f670482d6a39c01f09` |
| [preview-430-chestnut.png](design/iphone-home-webapp-notifications-candidates/preview-430-chestnut.png) | `ab36dcf1faa5da126215ab5603b1c46bba28193db63b8f9ecf078db33d08eb1c` |
| [preview-430-night.png](design/iphone-home-webapp-notifications-candidates/preview-430-night.png) | `37a55727a248bb01ac9edb4d8587270871d18f2b50adba88ed522ddbd419dd71` |
| [preview.css](design/iphone-home-webapp-notifications-candidates/preview.css) | `772b26ee6d63949114c372c623454a835c6ec8a05a294081eb792df4117c5c24` |
| [preview.js](design/iphone-home-webapp-notifications-candidates/preview.js) | `006bc76716feeb81e83e303f3de085b83f59b723152fa2aac8fcbd0d3eae462f` |
| [tokens.css](design/iphone-home-webapp-notifications-candidates/tokens.css) | `58b82a98efa1384452731c927a8b86e9c6b92415d2458f1d744406beff8a1ad5` |

체크포인트 메모 자체의 SHA-256은 Orca 완료 기록에서 확인할 수 있습니다.
