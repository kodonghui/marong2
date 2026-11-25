# 아이폰 홈 화면 웹앱 알림 11단계 진행

학원 Orca 항목 143의 e2485에 대한 e2670 “설계 반영 후 구현 시작”에 따라 진행했습니다. 설계 PR #138은 검토한 head `827c3ca6637e7a03f014043d546c602c1f56743d`에서 병합됐습니다. 구현 기준은 병합 커밋 `9811ad9305ec1c47b41ec85f81d8e111f96628f7`과 [고정 WBS](iphone-home-webapp-notifications.md)입니다. 고정 WBS와 검토 메모의 SHA-256을 보존하기 위해 진행 기록의 위치를 이 파일로 정했습니다.

## 승인된 통화 문서

Orca 항목 143의 e2698을 고정한 위임 답변 `msg_e6b8cd77a95b`(요청 `msg_b878eb1af1aa`)를 적용했습니다. 승인 메모 「아이폰 웹앱 통화 진입과 마이크 권한 변경 검토」의 SHA-256은 `df43513cce5628afa7697b2e3f03c312bf928155fb08df10cdfc127b193aa8c3`입니다.

| 단계 | 적용 범위 |
| --- | --- |
| 06 | API-314·315·317의 경로와 스키마를 사용합니다. 고정 [OpenAPI](../../api/iphone-home-webapp-notifications.version-candidate.openapi.yaml)의 SHA-256은 `d638efdaf90077fc38a61fa10242ce2f05ba379637e492561cf814b7c8e4fdf8`입니다. 새 HTML 문서는 고정 경로 `POST /chat/notice-call`에 출처·현재 세션·설치·활성 구독·대상 판정을 적용합니다. [06 통화 계약](../06-api/iphone-home-webapp-notifications-version-candidate.md) |
| 07 | 알림 탭에서 SCR-107로 들어가고 대상 조회 결과에 따라 같은 창의 통화 문서를 엽니다. 주소의 알림 참조를 먼저 제거하고 통화 문서에는 단기 탐색 식별값만 반환합니다. [07 사이트맵](../07-sitemap/iphone-home-webapp-notifications-draft.md#경로-확인-사항) |
| 08 | SCR-001의 받기·만료·선행 수락·결과 확인, SCR-002의 준비·같은 통화 연결·복귀, SCR-164의 재로그인 후 재조회와 SCR-107의 글 대화 복귀를 적용합니다. [SCR-001](../08-screens/iphone-home-webapp-notifications/SCR-001.md) · [SCR-002](../08-screens/iphone-home-webapp-notifications/SCR-002.md) · [SCR-164](../08-screens/iphone-home-webapp-notifications/SCR-164.md) · [SCR-107](../08-screens/iphone-home-webapp-notifications/SCR-107.md) |
| 09 | 고정 목업의 제목, 버튼 순서·위치, 제목과 복귀 초점, 두 테마의 기준을 사용합니다. [09 기준 화면](../../design/iphone-home-webapp-notifications-version-candidate/index.html) |

탐색 보관 시간은 60초로 적용했고 일치하는 문서에서 한 번 읽고 삭제합니다. 재로그인은 기존 단기 보관을 사용해 대상을 다시 조회합니다. 수락 결과와 재연결 자료는 통화 문서의 메모리에 보관합니다. 일반 채팅과 실패 문서는 마이크를 차단합니다. 통화 문서는 성공·실패 모두 캐시를 금지합니다.

## 작업별 상태

| TASK | 상태 | 구현 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-560 | 구현·검증 | `5da5b6b` | 신규·기존 격리 PostgreSQL의 024 적용·재적용, 승인 SQL의 제약·인덱스·권한, 활성 주소 중복, 세션 삭제 연계 |
| TASK-561 | 구현·검증 | `e6cb25a` | API-310의 다섯 상태, 세션·설치 격리, 출처·오류 응답, 조회 시 구독 변경 없음 |
| TASK-562 | 구현·검증 | `e6cb25a` | API-311의 선택 네 가지, 120초와 세션·설치 바인딩, 발급 시 구독 변경 없음 |
| TASK-563 | 구현·검증 | `e6cb25a` | API-312의 신규 등록·교체·동일 결과 재시도, 활성 주소 경합, 과거 요청 거절, 암호화 봉투 |
| TASK-564 | 구현·검증 | `e6cb25a` | API-313, 같은 동의에서 갱신 뒤 철회, 새 동의 뒤 이전 철회 거절, 보호 재료 제거 |
| TASK-565 | 구현·검증 | `e6cb25a` | 설치 증명이 있는 로그인 전환, 세션 만료, 로그아웃 우선·인계 우선, 부분 쓰기 실패·최대 2초·기한 경계, 통합 인증 회귀 |
| TASK-566 | 구현·검증 | `e6cb25a` | 허용 호스트, DNS 결과를 고정한 TLS 연결의 모의 검증, VAPID·본문 복호화 시험, 201·410·429·503·404·응답 유실·지연 결과 |
| TASK-567 | 구현·자동 시험 | `e6cb25a` | 기존 커밋 ID를 읽는 전달, 선톡·일정 재실행에서 메시지 각 한 건, 적격 웹 설치 둘과 기존 FCM 결과의 분리 |
| TASK-568 | 구현·검증 | `e6cb25a` | API-316의 `recorded`·`cleared`, 동일 설치와 답변에만 적용, 이전 신호 역전·5초 만료·최대 2초 확인 창 |
| TASK-569 | 구현·자동 시험 | `e6cb25a` | 기존 약속 전화 행과 응답 기한, 중복 및 만료 전송 차단, 모의 발송 뒤 구독 상태 보존 |
| TASK-570 | 구현·브라우저 모의 시험 | `e6cb25a` | 기존 manifest·아이콘 보존, 승인 페이로드 처리와 중복 표시 제어, 같은 출처 클릭, 요청 캐시 처리 없음 |
| TASK-571 | 구현·브라우저 모의 시험 | `e6cb25a` | Chromium·WebKit의 360·430px와 두 테마, 일반 Safari 안내, 권한과 구독 상태, 명시 선택, 등록 충돌 후 재조회, 철회 |
| TASK-572 | 구현·검증 | `e6cb25a` | API-314의 다섯 결과, 변조·계정 불일치·삭제·형식·출처·오류 응답, 조회 시 전화 변경 없음 |
| TASK-573 | A·C 구현·자동 시험 | `e6cb25a`, `f75f5a0`, `273f4ba` | SCR-107에서 대상 확인 후 같은 앱 창에 용도별 통화 문서를 엽니다. 비활성 구독의 미수락 만료 안내, 재로그인·설치·대상·선택 확인, HTTP 마이크 정책과 복귀 초점을 확인했습니다. |
| TASK-574 | B·C 구현·자동 시험 | `e6cb25a`, `273f4ba`, `f6f2662`, `8f2957e` | API-315의 원자적 예약·수락에 최초 연결 기한을 기록하고 결과 재확인에서는 보존합니다. 웹·Android 수락 경합의 단일 수락과 종료 뒤 Android 일반 발신을 확인했습니다. |
| TASK-575 | A·B·C 구현·자동 시험 | `45a13f1`, `273f4ba`, `f6f2662`, `940ffd2`, `8f2957e` | API-317의 두 시작 방식과 문서 검증, 준비 실패 시 기존 기한, 동일 통화 복구, 중복 연결·늦은 종료, 모의 WebRTC·PCM 전환을 확인했습니다. |
| TASK-576 | A·B·C 구현·브라우저 모의 시험 | `f75f5a0`, `c87dd7b`, `f6f2662` | 별도 받기와 일반 통화 시작, 마이크 거절, 응답 유실 뒤 같은 결과, 종료 안내 초점과 별도 다시 걸기를 확인했습니다. |
| TASK-577 | A·B·C 자동 회귀 시험 | `273f4ba`, `f6f2662`, `940ffd2`, `8f2957e` | 통화 012와 두 기한, Safari·Android·FCM과 기존 글 대화·약속 전화·재연결을 모의 환경에서 확인했습니다. |

## TASK-575·577 독립 시험

합성 계정·격리 PostgreSQL을 사용한 변경과 실행 커밋은 `45a13f1f0ebfecce73cc48184788c4040fbffeaa`입니다. Windows의 비동기 DB 시험에는 Python 3.12 Selector 이벤트 루프를 사용했습니다.

| 명령 또는 시험 파일 | 결과 |
| --- | --- |
| `tests/test_web_push_subscriptions.py` | 20개 통과. API-317 업그레이드 101 및 실패 응답 6종, 첫 프레임 5초·2048바이트 경계와 중복 키, 실패 프레임 11종. 실패 연결의 통화 할당 방지, 같은 세션·클라이언트의 통화 ID 유지와 다른 연결의 종료 요청 차단. 웹 푸시 활성·비활성에서 기존 Safari·Android·FCM 응답과 경로 비교 |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py` | 4개 파일 통과. 연속 100회 오디오 처리, WebRTC 접근 권한, PCM 전환과 재연결 |
| `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | 4개 파일 통과. 전송 선택, 전환, 연결 감시와 종료 |
| `tests/test_app_ring.py`, `tests/test_app_chat.py` | 기존 약속 전화 75개, 글 대화 454개 확인 항목 통과. FCM 응답·재시도는 모의 전송 |
| `.venv/Scripts/python tests/test_web_push_browser.py` | 4개 통과. Chromium·Playwright WebKit의 일반 브라우저 진입과 알림 설정 |
| `apps/android`에서 `npm test` | 34개 통과. Gradle 빌드 산출물이 필요한 병합 manifest 검사 1개 건너뜀 |
| `node --test apps/android/test/call-ring.e2e.cjs apps/android/test/app-update-banners.e2e.cjs` | 30개 통과. Playwright의 Android 브리지 모의 환경 |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | 23개 통과. 시험에 필요한 `fcntl`을 사용할 수 있는 환경에서 모의 FCM 전송 |

WebRTC 시험은 루프백 HTTP·웹소켓, 서버의 실제 `LiveSession`과 `Bridge` 오디오 큐, 모의 캡처·중계·모델을 연결했습니다. 합성 PCM의 양방향 전달과 같은 통화의 복귀를 확인했습니다. 실제 ICE·Opus 전송과 기기 오디오는 후속 확인 범위입니다.

기존 API-107의 `/live`는 두 설정 모두에서 다른 클라이언트의 동시 연결에 101 뒤 `call_busy` 프레임을 보냈습니다. 기존 OpenAPI에는 409도 기재돼 있으며 통합 인증 계약은 101 뒤 실패 프레임을 명시합니다. 이번 시험은 기존 동작을 확인했고 API-317의 업그레이드 전 409도 별도로 확인했습니다.

## 통화 문서 구현 뒤 자동 시험

실행 커밋은 `f75f5a0f458e50c61315399755b7d85c9b037054`입니다. Windows DB 시험은 Python 3.12의 Selector 이벤트 루프에서 실행했습니다. 브라우저 자동 시험은 루프백 HTTP·웹소켓에서 실제 문서·브라우저 스크립트·작업자를 실행하고, API 응답과 마이크를 모의 처리했습니다. 공급자 전송과 모델을 모의 처리한 서버 시험은 합성 계정과 격리 PostgreSQL을 사용했습니다.

| 명령 또는 시험 파일 | 결과 |
| --- | --- |
| `.venv/Scripts/python tests/test_notice_call_browser.py` | 3개 시험을 Chromium·Playwright WebKit에서 각각 통과. 같은 창의 경로와 Origin·Referer, 허용되지 않은 폼 목적지, 초점, 재로그인과 탐색 불일치, 권한 거절, 마이크 지연 중 만료·선행 수락, 결과 유실, 같은 통화 재연결·종료 확인 |
| `tests/test_web_push_subscriptions.py` | 21개 통과. 문서 성공·실패의 상태·마이크·캐시 정책, API-314·315·317, 격리 DB의 수락·경합·통화 행·재연결, 일반 Safari·Android·FCM 회귀 |
| `.venv/Scripts/python tests/test_web_push_browser.py` | 4개 통과. 기존 설치·설정·알림 탭과 잘못된 진입 |
| `tests/test_unified_auth.py`, `tests/test_app_ring.py`, `tests/test_app_chat.py` | 통합 인증 11개, 기존 약속 전화 75개, 글 대화 및 모의 FCM 454개 확인 항목 통과 |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py` | 4개 파일 통과. 기존 오디오 전송·재연결 회귀 |
| `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | 4개 파일 통과 |
| `apps/android`의 `npm test` 및 `node --test apps/android/test/call-ring.e2e.cjs apps/android/test/app-update-banners.e2e.cjs` | Node 34개, 브라우저 모의 시험 30개 통과. Gradle 빌드 산출물이 필요한 병합 매니페스트 검사 1개 건너뜀 |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | 23개 통과. 모의 FCM 전송 |

iPhone 기기 확인은 앱 창 유지, 알림 탭·잠금 해제·재로그인, 잠금과 망 전환 후 같은 통화 ID, 실제 VoiceOver 초점, 양방향 오디오와 ICE·Opus 전송을 포함합니다. 브라우저 모의 시험은 문서·초점·요청 순서·동일 ID의 근거입니다.

## PR #139 독립 리뷰 후속

리뷰 기준은 `ce2d1aeeff51751861a8fc081340494778772291`, 수정 및 실행 커밋은 `7adad59424085a862abb60001bfb408e94b6ee60`입니다. 격리 DB와 루프백 브라우저에서 수정 전에 예약 소유자 보호, 활성 구독 없는 수락, 재로그인 뒤 만료 안내, 구독 만료 정리에 대한 새 시험이 실패함을 확인했습니다. [독립 리뷰](https://github.com/kodonghui/marong2/pull/139#issuecomment-7158136567)

| 리뷰 | 결과 |
| --- | --- |
| 1 · SPEC-546·550 | 보완. 기존 통화 행의 클라이언트 UUID에 알림 예약과 원래 로그인·설치·클라이언트의 결합을 기록합니다. 첫 연결 전과 일시 단절 중 기존 경로의 다른 클라이언트는 재개하거나 종료할 수 없습니다. 원래 클라이언트 연결·동일 ID 복구·종료와 기존 Safari 발신·HTTP 종료, Android 받기를 확인했습니다. |
| 2 · SPEC-545·546, e2698 | 보완. 통화 문서의 UUID를 현재 세션·설치·동의에 결합합니다. 마이크 준비 뒤 선택 헤더로 읽기 검사를 하고, 변경이 확인되면 오디오를 정리하고 대상 조회로 돌아갑니다. 수락과 같은 결과 복원에서 통화 트랜잭션이 세션과 설치 잠금을 가진 동안 기존 앱 역할이 구독을 확인합니다. 철회와 수락의 두 순서, 같은 동의 갱신, 같은 계정 재로그인 뒤 재등록을 확인했습니다. 공개 요청 본문·응답 스키마를 보존했습니다. |
| 3 · SPEC-547 | 만료 안내 보완. 재로그인 뒤 현재 계정의 미수락 만료를 확인해 마이크 차단 화면에서 표시합니다. 활성 구독일 때 별도 일반 통화 선택과 API-317 재검증을 확인했습니다. 비활성 구독의 만료 안내에서 바로 일반 통화를 여는 조작은 e2698의 통화 문서 마이크 조건과 함께 적용할 별도 계약 결정이 필요해 보류합니다. |
| 4 · SPEC-529 | 보완. 앱 서버의 정리 작업이 60초 간격으로 구독 자체 기한에 도달한 활성 후보의 현재 버전을 잠금 아래 확인하고 만료 상태와 새 버전, 보호 재료 제거를 함께 저장합니다. API-310의 조회, 경합 중 재등록한 버전, 개별 알림·전화 기한, 다른 설치와 Android FCM을 따로 확인했습니다. |

표 모양이나 SQL 마이그레이션, 06·08 승인 사본 및 e2698 메모 바이트는 보존했습니다. 새 연결은 기존 루프백의 앱 서버와 통화 서버 사이에서만 구독을 검사합니다. 별도 앱 포트를 쓰는 운영 구성 확인은 남았습니다. 이번 수정 전의 초안에서 생성한 예약 UUID는 기존 일반 통화 값과 저장 형식이 같아 자동 변환할 수 없습니다. 이번 시험은 새 예약과 기존 일반 통화 행을 사용했습니다. 원래 창의 복구 상태를 완전히 잃은 예약의 회수 조건은 후속 계약 범위입니다.

| 명령 또는 시험 파일 | 결과 |
| --- | --- |
| `tests/test_web_push_schema.py`, `tests/test_web_push_subscriptions.py` | 마이그레이션 2개, 구독·통화·모의 전송 27개 통과. 독립 리뷰에 따른 회귀 6개와 기존 시험에 추가한 점검을 포함합니다. |
| `tests/test_notice_call_browser.py`, `tests/test_web_push_browser.py` | 통화 문서 5개와 기존 알림 4개 통과. Chromium·Playwright WebKit 모의 환경에서 권한 확인 중 세션 변경·철회, 수락 요청 0건, 오디오 정리와 만료 안내를 확인했습니다. |
| `tests/test_unified_auth.py`, `tests/test_app_ring.py`, `tests/test_app_chat.py` | 통합 인증 11개, 기존 약속 전화 75개, 글 대화·모의 FCM 454개 확인 항목 통과. Windows DB 시험은 Python 3.12 Selector 이벤트 루프로 실행했습니다. |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py` 및 `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | Python과 Node 각 4개 파일 통과. 기존 연결·재연결·종료와 모의 오디오 경로를 확인했습니다. |
| `npm test --prefix apps/android`, `node --test apps/android/test/call-ring.e2e.cjs apps/android/test/app-update-banners.e2e.cjs` | Node 34개, 브라우저 모의 시험 30개 통과. Gradle 빌드가 필요한 병합 매니페스트 검사 1개 건너뜀. |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | 모의 FCM 23개 통과. |
| `git diff --check`, Python `compileall`, JavaScript `node --check`, CORTHEX `term-check.py` | 통과. |

## 독립 재검토 뒤 시험 안정화

재검토 기준은 `cf9f3038930a44ec91cad42f761eb9d7f04014a5`, 시험 수정 및 실행 커밋은 `434355a358bec067c1a4c69fbef7b313b71fad89`입니다. [독립 재검토](https://github.com/kodonghui/marong2/pull/139#issuecomment-7158831626)

- 재로그인 만료 시험은 앱 시험 시각을 DB 실행 시각보다 5초 이전으로 설정했을 때 수정 전 `ring_ready`를 반환했습니다. 기한을 고정 시각보다 1마이크로초 뒤와 고정 시각에 각각 맞춰 `ring_ready`와 `ring_expired`의 경계를 확인합니다. 만료 문서의 403·마이크 차단·캐시 금지와 약속 전화 행 보존도 확인합니다.
- 재검토에 기록된 WebKit의 최초 재연결 지연은 수정 전 Chromium·Playwright WebKit에서 직접 6회, 연결·첫 프레임·준비 응답 진단을 붙여 8회 실행하는 동안 재현되지 않았습니다. 당시 지연 원인은 확정할 수 없습니다. 시험은 지정한 루프백 연결을 끊고 다음 연결의 첫 프레임을 받은 뒤 준비 응답을 보냅니다. 준비 응답을 보류한 동안 재연결 화면과 초점을 검사합니다. 불일치한 통화의 거절, 수동 확인, 재연결 중 종료를 각각 확인합니다. 기존 화면 판정 제한 시간은 유지했습니다.

| 실행 명령 또는 시험 | 결과 |
| --- | --- |
| `tests/test_web_push_subscriptions.py` | Windows Python 3.12 Selector 이벤트 루프와 `runpy.run_path`로 4회 실행. 매회 27개 통과 |
| 같은 파일의 `test_review_document_binding_survives_refresh_and_rejects_same_account_relogin` | 앱 시험 시각의 차이를 -5초·0초·+5초로 두고 조건마다 3회 실행. 총 9회 통과 |
| `tests/test_notice_call_browser.py NoticeCallBrowserTests.test_lost_response_exact_retry_reconnect_and_other_device_wins` | 수정 뒤 새 프로세스에서 Chromium·Playwright WebKit 각각 8회 통과 |
| `tests/test_notice_call_browser.py`, `tests/test_web_push_browser.py` | 통화 문서 시험은 두 엔진에서 4회 실행하여 매회 5개 통과. 기존 알림 시험 4개 통과 |
| `git diff --check`, 두 시험 모듈의 `python -m compileall -q`, CORTHEX `term-check.py` | 통과 |

이 커밋의 범위는 시험 안정화입니다. 재연결 결과는 루프백과 모의 오디오 환경의 판정입니다. 이후 위임 승인과 구현은 아래 기록에 연결했습니다.

## 만료 안내의 일반 통화와 문서 권한

구현과 서버 자동 시험은 `273f4ba4c22212f676da63e3ac518f2d3b5f75b9`, 화면 준비 보완과 브라우저 시험은 `c87dd7b095e5a19745919ba422c4d89db4b33389`에서 진행했습니다. e2714의 A·B는 위임 승인 `msg_9c2b8c9e4213`과 요청 `msg_dba0a8a1acab`, C는 승인 `msg_91e4a225a770`과 요청 `msg_26e004008daf`를 따릅니다. A·B 메모의 SHA-256은 `73a71851a6014fdad8e9e503530af3f39df8b88cea2d5e15066d1d903d7e3040`, C 메모는 `d5468a1ffca83d9eb714d6c3ce5e099ec5e1f2e05ca3d064bf6fd4a020068c02`입니다. e2698 메모와 고정 06·08·09·10의 바이트를 보존했습니다. [06 통화 계약](../06-api/iphone-home-webapp-notifications-version-candidate.md) · [07 사이트맵](../07-sitemap/iphone-home-webapp-notifications-draft.md) · [08 만료 안내](../08-screens/iphone-home-webapp-notifications/SCR-001.md#notice-ring-expired) · [08 재연결과 종료](../08-screens/iphone-home-webapp-notifications/SCR-002.md) · [09 기준 화면](../../design/iphone-home-webapp-notifications-version-candidate/index.html)

- **A · TASK-573·575·576, SPEC-547·548.** 만료 안내의 `일반 통화`를 선택하면 현재 세션·설치·대상 참조에 묶인 선택 증명을 같은 창의 `POST /chat/notice-call`에 보냅니다. API-314의 읽기 응답 헤더가 선택 증명을 전달하며 기존 JSON과 조회 동작을 사용합니다. 서버에서 현재 미수락 만료와 선택을 확인한 문서에 마이크를 허용합니다. 문서의 `통화 시작` 뒤 마이크 준비가 성공하면 API-317로 일반 발신을 요청합니다. 통화 생성 잠금 아래 대상을 다시 확인하며 구독 등록과 약속 전화 수락은 발생하지 않습니다.
- **C · TASK-574·575·577, SPEC-545·546·550.** API-315의 새 수락과 결과 확인에는 현재 활성 구독과 수락용 문서가 필요합니다. API-317은 일반 발신 문서의 용도를 직접 확인하고, 알림 발신은 이 검증을 거친 API-315의 연결 토큰과 기존 소유 기록을 확인합니다. 연결 토큰의 검증 버전 변경으로 이전 초안에서 발급된 토큰은 새 코드에서 만료 응답과 동일하게 거절됩니다. API-315·317의 필드와 `not_allowed` 결과를 사용합니다.
- **B · TASK-574·575·576, SPEC-546·550.** A·C 구현 당시에는 `app_rings.answered_at`으로 최초 수락 시각을 확인할 수 있었지만 기존 통화 상태와 모델 구간으로는 첫 연결과 단절 확정 시각을 구분할 수 없었습니다. 이후 e2728의 저장 계약과 구현·시험은 아래에 연결했습니다.

수정 전 기준 `06baba04a8eac0680b9ee5412f9c704ab485a97e`에서 합성 계정의 미발급 ID 수락이 403 판정을 통과하지 못했습니다. 같은 기준의 화면 스크립트로 비활성 구독 재로그인 시험을 실행했을 때 Chromium과 Playwright WebKit 모두 일반 통화 조작을 찾지 못했습니다. 수정 뒤 두 경계와 일반 발신에서 약속 전화 수락·구독 변경 0건을 확인했습니다.

통화 스크립트 응답을 보류한 시험은 `273f4ba`에서 두 엔진 모두 통화 시작을 먼저 활성화해 실패했습니다. `c87dd7b`는 통화 실행기가 연결된 뒤에 받기와 통화 시작을 활성화합니다. 같은 시험에서 스크립트 응답 전후의 버튼 상태와 마이크 거절 시 연결 0건을 확인했습니다.

| 실행 명령 또는 파일 | 결과 |
| --- | --- |
| `tests/test_web_push_subscriptions.py` | `273f4ba`의 격리 PostgreSQL 28개 통과. 같은 계정 재로그인, 미발급·다른 용도·세션·설치·대상 거절, 통화 생성 직전 대상 변경, 수락 결과 재확인, 일반 Safari·Android API-107과 모의 전송을 확인했습니다. |
| `tests/test_web_push_schema.py`, `tests/test_unified_auth.py`, `tests/test_app_ring.py`, `tests/test_app_chat.py` | `273f4ba`에서 마이그레이션 2개, 통합 인증 11개, 약속 전화 75개, 글 대화·모의 FCM 454개 확인 통과. Windows DB 시험은 Python 3.12 Selector 이벤트 루프에서 실행했습니다. |
| `.venv/Scripts/python tests/test_notice_call_browser.py`, `.venv/Scripts/python tests/test_web_push_browser.py` | `c87dd7b`에서 통화 문서 5개와 기존 알림 4개 통과. 두 모의 엔진에서 재로그인, 같은 창과 초점, 별도 일반 통화, 준비 지연, 권한 거절, 연결 결과와 같은 ID 복구를 확인했습니다. |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py` 및 `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | `273f4ba`에서 Python과 Node 각 4개 파일 통과. 루프백과 합성 오디오로 WebRTC·PCM 전달 및 전환을 대조했습니다. |
| `npm test --prefix apps/android` | `273f4ba`에서 34개 통과, Gradle 산출물이 필요한 병합 매니페스트 1개 건너뜀. |
| `node --test --test-concurrency=1 apps/android/test/call-ring.e2e.cjs apps/android/test/app-update-banners.e2e.cjs` | 다른 브라우저·DB 시험과 겹치지 않게 `c87dd7b`에서 실행해 30개 통과. 앞선 두 실행에서 TC-618 배너의 2,950ms 판정이 각각 실패했습니다. 기준 `06baba04`의 해당 시험만 실행했을 때도 통과했습니다. |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | `273f4ba`에서 모의 FCM 23개 통과. |
| `git diff --check`, Python `compileall`, JavaScript `node --check`, CORTHEX `term-check.py` | 통과. |

실제 iPhone의 앱 창 유지, VoiceOver 초점, 잠금·망 전환과 양방향 오디오는 후속 기기 확인 범위입니다. 실제 발송과 운영 반영은 별도 승인 범위입니다.

## 알림 통화 예약과 복구 기한

e2728의 위임 승인 `msg_802e55141477`과 요청 `msg_d8c9254e1536`을 적용했습니다. 승인 기준 PR #139는 `823e5d420f5ed4edd22dcff1df0d73c311a3e4b4`였습니다. 원격 `main`의 `9811ad9305ec1c47b41ec85f81d8e111f96628f7`에서 통화 마이그레이션이 011까지이고 012가 비어 있음을 확인했습니다. [05 보조 계약](../05-erd/iphone-webapp-call-deadline-storage-review.md) · [승인 SQL](../05-erd/012_notice_call_deadlines.draft.sql) · [통화 012](../../marong/call/migrations/012_notice_call_deadlines.sql)

| 승인 원본 | SHA-256 |
| --- | --- |
| `iphone-webapp-call-deadline-storage-review.md` | `032e4471afa27633c76c64fb214606ff53e7e80c8cb8ff9844c27b41f2e826bf` |
| `012_notice_call_deadlines.draft.sql`와 적용 SQL | `96720c13ae0f1dd23b9a45d2035486fc3086001d9a2ac753a3a64f13bd819820` |

`f6f26629af3cdc08b383864d034d1e12c5cef367`에서 통화 012와 두 기한을 구현했고, `940ffd2f6da7709f7867ab93ae7b60d4ef05879b`에서 승인된 복구 진행 중 동일 클라이언트의 중복 연결을 보호했습니다. SQL 두 사본과 승인 메모는 Git에 기록한 바이트까지 대조했습니다. TBL-003의 두 열은 기본값 없이 NULL을 허용합니다. 기존 행의 각 시각에는 NULL을 유지합니다. [06 통화 계약](../06-api/iphone-home-webapp-notifications-version-candidate.md) · [08 재연결과 종료](../08-screens/iphone-home-webapp-notifications/SCR-002.md)

- 첫 120초는 최초 수락 트랜잭션의 `answered_at`부터 계산합니다. 연결 준비가 완료돼 첫 시각을 기록하면 기한을 비웁니다. 준비 실패·철회, 읽기 조회와 같은 수락 결과 확인은 기한을 연장하지 않습니다.
- 첫 연결 뒤 서버가 단절을 확정하면 복구 대기 기한을 120초로 기록합니다. 현재 연결의 소유를 호출자·약속 전화·통화 잠금 아래 확인합니다. 기한 안에 들어온 유효 복구는 준비가 진행되는 동안 보호합니다. 준비가 완료되면 최초 연결 시각을 보존하면서 기한을 비웁니다. 실패한 복구나 늦게 도착한 이전 연결의 종료는 기존 기한을 연장하지 않습니다.
- 웹 통화 서버는 5초 간격으로 기한에 도달한 예약을 정리합니다. 연결 요청에서는 잠금 아래 정확한 경계를 판정합니다. 재시작에서 이미 기록된 기한은 그대로 사용하고, 연결 중이던 기록만 복구 대기로 전환합니다. 012 이전 행의 연결 시각은 추정하지 않습니다. 종료 시 원래 통화 ID와 약속 전화 수락 이력을 보존합니다. 종료 안내의 `다시 걸기`는 별도의 일반 통화를 엽니다.

가상 시계는 격리 PostgreSQL의 예약·복구 판정에만 주입했습니다. 세션과 연결 토큰은 기존 검증을 통과한 합성 계정의 값을 사용했습니다. 두 기한 각각의 직전 1마이크로초, 정확한 경계, 직후 1마이크로초를 검사했습니다. 경합은 호출자 잠금을 실제로 획득한 채 시각을 경계로 이동하거나, 기한 전에 허용된 복구의 모의 모델 준비를 보류해 재현했습니다. 준비 보류 중 중복 연결 시험에서 `f6f2662`의 서버는 기존 복구를 닫았고 `940ffd2`에서는 복구가 같은 통화 ID로 완료됐습니다.

| 실행 명령 또는 파일 | 실행 커밋과 결과 |
| --- | --- |
| `tests/test_web_push_schema.py` | `f6f2662`에서 3개 통과. 빈 DB와 기존 통화 행이 있는 DB에 통화 011 다음 012를 각각 두 번 적용했습니다. 기존 열·행·권한, 두 열의 NULL과 기본값 없음, 통화 역할의 쓰기와 앱 역할의 쓰기 차단을 대조했습니다. |
| `tests/test_web_push_subscriptions.py` | `940ffd2`에서 32개 통과. 가상 시계 네 시험에서 두 경계, 연결 준비 실패, 중복·늦은 종료, 재시작 반복, 경합, 늦은 연결 차단과 API-107 별도 발신을 확인했습니다. A·C의 수락·일반 통화·문서 인증과 기존 Safari·Android·모의 FCM을 포함합니다. |
| `tests/test_unified_auth.py`, `tests/test_app_ring.py`, `tests/test_app_chat.py` | `f6f2662`에서 통합 인증 11개, 약속 전화 75개, 글 대화·모의 FCM 454개 확인 통과. Windows DB 시험은 Python 3.12 Selector 이벤트 루프를 사용했습니다. |
| `tools/vertex_live/test_call_memory_regressions.py`, `test_connect_server.py` | `f6f2662`에서 각각 4개, 5개 통과. |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py`, `test_hangup.py`와 `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | `f6f2662`에서 Python 5개 파일과 Node 4개 파일 통과. 루프백과 합성 오디오, 모의 모델·중계를 사용했습니다. |
| `.venv/Scripts/python tests/test_notice_call_browser.py`, `.venv/Scripts/python tests/test_web_push_browser.py` | `940ffd2`에서 통화 문서 6개와 기존 알림 4개 통과. Chromium과 Playwright WebKit에서 종료 안내 초점과 명시적으로 다시 걸 때만 기존 일반 통화 페이지로 이동하는 것을 확인했습니다. |
| `npm test --prefix apps/android` 및 `node --test --test-concurrency=1 apps/android/test/call-ring.e2e.cjs apps/android/test/app-update-banners.e2e.cjs` | `940ffd2`에서 단위 시험 34개와 브라우저 모의 시험 30개 통과. Gradle 산출물이 필요한 병합 매니페스트 검사 1개 건너뜀. |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | `f6f2662`에서 모의 FCM 23개 통과. |
| `git diff --check`, Python `compileall`, JavaScript `node --check`, CORTHEX `term-check.py` | 통과. |

연결 중복 처리는 기존 단일 웹 통화 서버의 소켓 소유를 사용합니다. 이번 시험은 합성 계정과 루프백 환경의 범위입니다. 운영 DB의 012 적용, iPhone 앱 창·잠금·망 전환·VoiceOver, 실제 알림과 양방향 기기 오디오는 후속 승인과 확인 범위입니다.

## 독립 재검토의 준비 실패와 Android 재진입

재검토 기준은 `2552053ccbcb56c34ced82a1eaa7a92f636556a8`, 지적 1·2의 수정 및 회귀 실행 커밋은 `8f2957ea9d477474bb5b897363df0684c233b698`입니다. Orca 항목 143의 구현 초안 작업과 GitHub의 열린 초안 #139를 대조했습니다. 기존 통화 012 승인 메모·초안 SQL·적용 SQL의 해시를 다시 확인했습니다. 지적 3의 새 창 종료 조회와 권한·화면은 별도 위임 설계 범위입니다. [독립 재검토](https://github.com/kodonghui/marong2/pull/139#issuecomment-7160528408) · [05 보조 계약](../05-erd/iphone-webapp-call-deadline-storage-review.md)

- **지적 1 · TASK-575·576, SPEC-546·550.** 첫 연결이나 복구의 구간 생성 및 준비 전환이 끝난 뒤에 통화 준비를 확정합니다. 수정 전에는 구간 생성·준비 전환 타임아웃을 첫 연결과 복구에 각각 주입한 네 경우 모두 `ready`를 반환하고 원래 기한에 종료하지 않았습니다. 수정 뒤 구간 생성 타임아웃, 준비 전환 타임아웃, 전환된 행 0건을 각각 재현했습니다. 여섯 경우 모두 `db_unavailable`로 종료됐고, 원래 기한이 유지됐으며 가상 시계를 정확한 120초 경계로 옮겼을 때 예약이 종료됐습니다. 기한 전에 허용된 유효 복구와 중복 연결 보호 시험도 통과했습니다.
- **지적 2 · TASK-574·575·577, SPEC-546·550.** 기존 `/live`의 호출자·약속 전화·통화 잠금 아래 연결된 통화가 `ended`이면 Android가 별도 일반 발신을 시작합니다. 수정 전에는 기능을 끈 상태에서 재진입이 연결됐고, 켠 상태에서는 `call_busy`였습니다. 수정 뒤에는 두 설정에서 일반 발신의 새 통화 ID, 원래 수락 시각과 통화 ID 보존, 새 약속 수락, 진행 중인 호출의 `call_busy`를 확인했습니다. 웹·Android 경합의 단일 수락과 웹에서 종료된 약속의 Android 재진입도 검증했습니다.

Windows의 PostgreSQL 시험은 Python 3.12 Selector 이벤트 루프에서 `runpy.run_path`로 실행했습니다. 통화 시험은 합성 계정과 루프백 웹소켓, 모의 모델·오디오를 사용했습니다. FCM 시험은 모의 전송을 사용했습니다.

| 실행 명령 또는 파일 | 결과 |
| --- | --- |
| `tests/test_web_push_subscriptions.py`의 `test_notice_segment_preparation_failure_preserves_pending_deadline`, `test_577_existing_routes_and_android_eligibility_with_web_push_on_and_off` | 기준 `2552053` 소스에서 목표 시험 2개를 실행해 실패 판정 5건을 확인했습니다. 수정 뒤에는 기존 수락 경합과 웹 종료 뒤 일반 발신을 포함한 목표 시험 4개가 통과했습니다. |
| `tests/test_web_push_schema.py`, `tests/test_web_push_subscriptions.py` | `8f2957e`에서 스키마 3개와 구독·통화 33개 통과. |
| `tests/test_unified_auth.py`, `tests/test_app_ring.py`, `tests/test_app_chat.py` | `8f2957e`에서 통합 인증 11개, 약속 전화 75개, 글 대화·모의 FCM 확인 454개 통과. |
| `tools/vertex_live/test_call_memory_regressions.py`, `tools/vertex_live/test_connect_server.py` | `8f2957e`에서 각각 4개와 5개 통과. |
| `tools/vertex_live/test_relay.py`, `test_rtc_api.py`, `test_midcall.py`, `test_web_reconnect.py`, `test_hangup.py`, `test_ring.py`와 `node --test tools/vertex_live/test_transport.cjs tools/vertex_live/test_fallback.cjs tools/vertex_live/test_rtc_watchdog.cjs tools/vertex_live/test_hangup_client.cjs` | `8f2957e`에서 Python 6개 파일과 Node 4개 파일 통과. |
| `.venv/Scripts/python tests/test_notice_call_browser.py`, `.venv/Scripts/python tests/test_web_push_browser.py` | `8f2957e`에서 Chromium·Playwright WebKit의 통화 문서 6개와 웹 알림 4개 통과. |
| `node --test --test-concurrency=1 apps/android/test/app-update-banners.e2e.cjs apps/android/test/call-page.e2e.cjs apps/android/test/call-ring.e2e.cjs apps/android/test/chat-page.e2e.cjs apps/android/test/chat-scroll.e2e.cjs` | `8f2957e`에서 순차 재실행 63개 통과. DB 시험과 겹친 첫 실행은 기존 TC-618 배너 시간 판정 1건 실패, 나머지 62개 통과. |
| Ubuntu WSL Python 3.12의 `tests/test_app_update_push.py` | `8f2957e`에서 모의 FCM 23개 통과. |
| `cap sync android` 후 `gradlew.bat --offline --no-daemon --rerun-tasks :app:processDebugManifest :app:processReleaseManifest :app:testDebugUnitTest :app:lintDebug` | `8f2957e` 작업 공간에서 Java 21·SDK 36·Gradle 8.14.3으로 118개 작업 실행. 디버그·릴리스 병합 매니페스트의 권한 13개 동일, 디버그 단위 45개 통과, Lint 경고 7건. 첫 실행에서 누락된 Capacitor 생성 파일을 동기화하고 다시 실행했습니다. |
| `npm test --prefix apps/android` | `8f2957e`의 새 병합 매니페스트를 사용해 TC-133/226 포함 35개 통과. 건너뜀 0개. |
| `git diff --check`, Python `compileall`, CORTHEX `term-check.py`, 통화 012의 승인·적용 SHA-256 | 통과. |

독립 리뷰의 Android Gradle과 매니페스트 결과는 `2552053`의 검증입니다. 위 Gradle 결과는 수정 커밋 `8f2957e`의 별도 재실행입니다. 단말 오디오와 실제 알림, 운영 반영과 구현 PR 병합은 후속 승인 범위입니다.

## 승인본과 운영 경계

고정 WBS의 SHA-256은 `64653d0df932e8c6a14d1cb20d0cbcf2ebcf8388a2b551118d28ececf66e552e`, 10단계 검토 메모는 `9b5df39b9c6cb3b526e7db9865e5a1945e840deb140b45874d5e873649f67606`입니다. 08 화면 인덱스는 승인 원본과 LF 한 바이트 차이인 병합된 사본을 보존했습니다. 구독 409는 승인된 SCR-165와 OpenAPI의 재조회 상태를 사용합니다.

웹 푸시 설정 `MARONG_WEB_PUSH`의 기본값은 비활성입니다. 구현 PR 병합, 실기기와 실제 발송, 출시와 운영 반영 및 TASK-578~583은 별도 승인 범위입니다.
