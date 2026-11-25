# 아이폰 홈 화면 웹앱 알림 11단계 진행

학원 Orca 항목 143의 e2485에 대한 e2670 “설계 반영 후 구현 시작”에 따라 진행했습니다. 설계 PR #138은 검토한 head `827c3ca6637e7a03f014043d546c602c1f56743d`에서 병합됐습니다. 구현 기준은 병합 커밋 `9811ad9305ec1c47b41ec85f81d8e111f96628f7`과 [고정 WBS](iphone-home-webapp-notifications.md)입니다. 고정 WBS와 검토 메모의 SHA-256을 보존하기 위해 진행 기록의 위치를 이 파일로 정했습니다.

## 설계 질문

SCR-001은 홈 화면 웹앱의 같은 문서에서 전화 상태를 전환하도록 정합니다. 현재 `/chat/`의 `Permissions-Policy`는 마이크를 차단하고, 통화 서버의 `/`는 `X-Frame-Options: DENY`를 반환합니다. 현재 응답과 화면 전환 계약을 적용하면 같은 문서에서 기존 통화 UI로 마이크를 사용할 수 없습니다. TASK-573의 전화 조작과 TASK-576을 진행하려면 웹앱에서만 마이크를 허용하는 응답의 적용 조건 또는 통화 화면 진입 계약을 결정해야 합니다. [SCR-001](../08-screens/iphone-home-webapp-notifications/SCR-001.md)

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
| TASK-573 | 일부 구현 | `e6cb25a` | 참조 제거, 조회·재인증 진입, 접근 불가와 기존 글 대화 연결. 전화 조작과 재인증 전 상태의 전체 브라우저 회귀 대기 |
| TASK-574 | 구현·자동 시험 | `e6cb25a` | API-315와 기존 역할의 원자적 예약·수락, 웹 선행·Android 선행·동시 수락, 기한과 잠금 대기 중 세션 만료, 같은 통화 ID 재확인 |
| TASK-575 | 구현·서버 통합 시험 | `e6cb25a`, `45a13f1` | API-317 업그레이드와 실패 응답, 첫 프레임 검증, 실패 프레임 11종, `ring:true/false`, 같은 통화 ID 재연결과 모의 WebRTC·PCM 전환 |
| TASK-576 | 설계 결정 대기 | — | 같은 웹앱 문서의 마이크 권한과 전화 진입 계약 결정 대기 |
| TASK-577 | 독립 회귀 시험 | `e6cb25a`, `45a13f1` | 웹 푸시 설정 켜짐·꺼짐의 일반 Safari·Android·FCM, 기존 글 대화·약속 전화·재연결·앱 업데이트 회귀. 전화 화면을 연결한 뒤 최종 브라우저 회귀 대기 |

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

## 승인본과 운영 경계

고정 WBS의 SHA-256은 `64653d0df932e8c6a14d1cb20d0cbcf2ebcf8388a2b551118d28ececf66e552e`, 10단계 검토 메모는 `9b5df39b9c6cb3b526e7db9865e5a1945e840deb140b45874d5e873649f67606`입니다. 08 화면 인덱스는 승인 원본과 LF 한 바이트 차이인 병합된 사본을 보존했습니다. 구독 409는 승인된 SCR-165와 OpenAPI의 재조회 상태를 사용합니다.

웹 푸시 설정 `MARONG_WEB_PUSH`의 기본값은 비활성입니다. 구현 PR 병합, 실기기와 실제 발송, 출시와 운영 반영 및 TASK-578~583은 별도 승인 범위입니다.
