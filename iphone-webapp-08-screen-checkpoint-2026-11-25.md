# 아이폰 홈 화면 웹앱 알림 08단계 화면 상태 체크포인트

2026-11-25 KST · 마롱이 Orca 항목 143 · 08 초안 검토 대기

[화면별 정의와 API 응답 대조표](docs/08-screens/iphone-home-webapp-notifications/README.md) · [360px·430px 와이어프레임](docs/08-screens/wireframes-iphone-home-webapp-notifications.draft.html)

## 승인과 기준

| 근거 | 확인 |
| --- | --- |
| 사용자님 선택 | 항목 143 e2412의 “홈 화면 웹앱 알림을 눌러 받기”. |
| 06 기준 | 위임 답변 `msg_584efefb54af`(요청 `msg_bc212ccc60f8`, 항목 143 e2454)의 API-310~317과 사람용 계약·메모를 보존했습니다. [06 버전 고정 메모와 해시](iphone-webapp-06-version-candidate-2026-11-25.md#승인-기록과-파일-해시) |
| 07 기준 | 위임 답변 `msg_a6b81d9b9bed`(요청 `msg_f541a38b8a1b`, 항목 143 e2462). [사이트맵 YAML](docs/07-sitemap/iphone-home-webapp-notifications.draft.sitemap.yaml) `45de23588d8edad49a7d67ca9601ea30114e0c57676c11b5a1d6e60e5f7ec193`, [생성 보기](docs/07-sitemap/iphone-home-webapp-notifications-draft.md) `901679eb082e19db7ed76dac25f21f6cee7284c44a58b6c1d292aecd3d97bb85`, [검토 메모](iphone-webapp-07-sitemap-checkpoint-2026-11-25.md) `f0406bc4eef5fadff34d9a7d4c315b6840af0c7887083a37d8f85e5c17c33c50`이 승인 SHA-256과 일치했습니다. |
| 저장소·설계 계약 | 원격 main과 HEAD `c82e3b18f05d56c7d332681c4d3b3e85d43fec32`. 08의 원본은 `docs/08-screens/`이며 이번 초안은 기존 화면 정의와 구분된 하위 폴더에 둡니다. 프로젝트 기준은 세로 360px·430px입니다. [작업 규칙](AGENTS.md) · [프로젝트 설정](.corthex/project.json) · [기존 화면 기준](docs/08-screens/README.md) |

## 승인된 흐름 적용

- **설치와 수신** — SCR-165에서 일반 Safari 설치 안내와 홈 화면 웹앱의 설치별 허용·구독을 구분했습니다. Safari 공유 메뉴·OS 권한 팝업·잠금 해제는 플랫폼 동작입니다. SCR-230은 일반 알림 유형과 앱의 진입만 정의합니다. 기존 아이콘은 `/chat/`로 열립니다.
- **글과 인증** — SCR-107에서 `/chat/#notice`의 대상 참조를 조회합니다. 다른 계정·없는 대상·삭제·검증 실패의 404는 한 상태로 표시합니다. 확인 중과 오프라인을 분리하고, 로그인 필요 때만 기존 SCR-164로 갔다가 현재 계정에서 재확인합니다. 알림을 누른 것만으로 방에 쓰거나 통화하지 않습니다.
- **수락과 복귀** — SCR-001에서 유효한 받기, 미수락 만료, 선행 수락, 수락 응답 유실을 구분합니다. 만료 안내 뒤 일반 통화는 별도 선택입니다. SCR-002로의 전환은 기존 웹앱 창 안의 논리 화면 전환입니다. `/call`을 새 HTTP 경로로 배정하지 않습니다. 결과가 불확실하면 같은 클라이언트의 결과부터 확인합니다.
- **기존 환경** — 일반 Safari의 가입·글·직접 약속 전화와 기존 Android의 알림·벨·거절·업데이트를 원본 상태에 연결했습니다. Android에서 다른 클라이언트가 동일 약속 전화를 먼저 유효 수락한 때는 승인된 기존 `call_busy`를 씁니다.

## 별도 승인 후보

07은 SCR-109 글 대화 메뉴를 재사용하기로 했습니다. 기존 화면 정의에는 “알림은 마롱이 앱에서 받을 수 있어”가 있고, 현재 브라우저용 구현은 “알림은 안드로이드 앱에서 받을 수 있어. 여기서는 열었을 때 밀린 말을 보여 줄게.”라고 표시합니다. 홈 화면 웹앱에도 이 문구가 남으면 승인된 설치별 알림 설정과 충돌합니다. [기존 화면 정의](docs/app-chat.md#7-화면-0708) · [현재 문구](marong/app_chat_static/chat.js)

**추천**은 기존 메뉴·조작의 설명만 홈 화면 추가와 SCR-165의 설치별 확인을 안내하도록 수정하는 것입니다. 대안은 아이폰 메뉴에서 알림 안내 줄을 빼고 안내를 SCR-165에만 두는 것입니다. [SCR-109 별도 검토 후보](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md#ios-menu-copy)

## 검증 범위

| 검사 | 결과 |
| --- | --- |
| 명세 및 API | 07에서 확인한 SCR 14개를 변경·재사용에 연결했습니다. 고정 API-310~317의 HTTP 예시·오류, 웹소켓 응답·프레임 100개를 상태에 연결했습니다. 404 통합, 315 응답 유실, 316 화면 유지 및 화면 문서의 상태 ID와 HTML 프레임을 검사했습니다. |
| 문서 | 06·07과 04 고정 파일, 승인된 흐름 아홉 개의 해시와 로컬 링크 212개·앵커 168개를 대조했습니다. 와이어프레임을 상태 정의에서 다시 생성해 동일함을 확인했습니다. Mermaid 11.12.0 파서 및 CORTHEX 다이어그램 검사와 용어 검사를 통과했습니다. |
| 실제 로컬 렌더 | Windows의 Chromium 158 및 Playwright WebKit 26.6에서 **360px와 430px 각각 43개 상태**를 렌더링했습니다. 43개에는 별도 검토 SCR-109 한 개가 포함됩니다. 가로 넘침 0건, 가장 작은 조작 영역 44px, 텍스트 최소 대비 8.37:1, 조작 경계 최소 대비 4.22:1입니다. 긴 한국어 설명은 양쪽 폭에서 최대 4줄이며 말줄임을 쓰지 않습니다. 알림 설정의 최초 확인과 완료 패널 높이가 같고, 제목을 초점 대상으로 사용할 수 있음을 확인했습니다. |
| Chromium에서 본 표본 | 360px·430px 각각의 홈 화면 추가, 안전한 접근 불가, 약속 전화 만료, 받기 결과 미확인, 같은 통화 재연결 중, iOS 잠금 표면의 6개 상태를 확인했습니다. |
| 실제 기기 검증 대기 | iOS 권한·알림과 닫힌 알림 재도착의 단일 표시, 로그인 귀환에서의 VoiceOver 초점 이동, Android·웹앱 양쪽 선착순 수락 및 첫 양방향 연결, 잠금·앱 전환·망 전환 뒤 같은 통화 ID와 양방향 오디오가 남아 있습니다. |

## 출력 파일 해시

| 로컬 파일 | SHA-256 |
| --- | --- |
| [README.md](docs/08-screens/iphone-home-webapp-notifications/README.md) | `f97a94278b79f2e44d887461e16afa117fa2fc511c94e38fa26adfe8946e4599` |
| [SCR-001.md](docs/08-screens/iphone-home-webapp-notifications/SCR-001.md) | `9e9749f21af0052c9cfcac62bfaba5df406765365c815d4d0100db7a868472df` |
| [SCR-002.md](docs/08-screens/iphone-home-webapp-notifications/SCR-002.md) | `c058f6ac6589aaf9dfe4a64a2d18c248b9df88983c7610904e2da5e716ffaaf8` |
| [SCR-101.md](docs/08-screens/iphone-home-webapp-notifications/SCR-101.md) | `6e4f8811c115af87c1c6aa035d1810b689038fbe41bb724686d2fac37a171aeb` |
| [SCR-107.md](docs/08-screens/iphone-home-webapp-notifications/SCR-107.md) | `5b26e7a7d709ddedfefb1a0ac0abdda050bfe277f4b9b2afd98d97911ddb4108` |
| [SCR-109.md](docs/08-screens/iphone-home-webapp-notifications/SCR-109.md) | `d1c396d0e13bd33d80714759661ed756dd4db24a328ab1468d94c9b8be6c850a` |
| [SCR-163.md](docs/08-screens/iphone-home-webapp-notifications/SCR-163.md) | `ab4535bb70b641f31db5bdd59c0eb1f90d8459eb5f5ed33cd6869f793ae39590` |
| [SCR-164.md](docs/08-screens/iphone-home-webapp-notifications/SCR-164.md) | `a618e65019afccc6fca3018f959f2f683d25a7de8c24b70ee32b303e3674c63a` |
| [SCR-165.md](docs/08-screens/iphone-home-webapp-notifications/SCR-165.md) | `69d95a7921419c2b2011b4077ad099514a5835c832976c5edef5fe7e68853f37` |
| [SCR-230.md](docs/08-screens/iphone-home-webapp-notifications/SCR-230.md) | `66fe1265e448d92598848d01cbae94d73d19f747c2242d529ae8d5e6eedc52d0` |
| [wireframes-iphone-home-webapp-notifications.draft.html](docs/08-screens/wireframes-iphone-home-webapp-notifications.draft.html) | `a438de2f9c975a7a1581a7bfbc2bbe6fb5e27d43f2c41dcfb71c10e86b7fa631` |

이 메모의 SHA-256은 Orca 인계에 함께 기록합니다. 검토 범위는 08 상태·응답·와이어프레임이며, 별도 문구 후보의 승인과 09 목업은 후속입니다.
