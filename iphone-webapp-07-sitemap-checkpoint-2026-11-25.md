# 아이폰 홈 화면 웹앱 알림 07단계 사이트맵 체크포인트

2026-11-25 KST · 마롱이 Orca 항목 143 · 07 구조 검토 대기

[사이트맵 YAML 초안](docs/07-sitemap/iphone-home-webapp-notifications.draft.sitemap.yaml) · [트리·목록·분기와 흐름 대조](docs/07-sitemap/iphone-home-webapp-notifications-draft.md)

## 승인과 기준

| 근거 | 확인 |
| --- | --- |
| 사용자님 직접 선택 | 2026-11-25 03:22:31 KST, 항목 143 e2412의 “홈 화면 웹앱 알림을 눌러 받기”. |
| 03·04 고정 범위 | 03 흐름 승인 `msg_3a78868b4953`(요청 `msg_afe6359e84ec`)의 [FL-220~228 아홉 파일 해시](iphone-webapp-03-flow-checkpoint-2026-11-25.md#흐름-파일과-sha-256)를 대조했습니다. 04 승인 `msg_317849c06b32`(요청 `msg_bb0b74fef89f`)의 [SPEC-520~554](docs/04-functional-spec/iphone-home-webapp-notifications-draft.md)는 SHA-256 `46ce7fe76e4488747d18f4b53d9ed3ebbd9e4b53d9744c2106f560c238a1f917`입니다. |
| 06 고정 | 항목 143 e2454의 세 파일을 승인한 오랑이 위임 답변 `msg_584efefb54af`(요청 `msg_bc212ccc60f8`)를 확인했습니다. [OpenAPI](api/iphone-home-webapp-notifications.version-candidate.openapi.yaml) `d638efdaf90077fc38a61fa10242ce2f05ba379637e492561cf814b7c8e4fdf8`, [사람용 계약](docs/06-api/iphone-home-webapp-notifications-version-candidate.md) `1c901c2ee430f12784c09edd227bacdf2f2f86458eb8ff4e557d6e77f755df05`, [검토 메모](iphone-webapp-06-version-candidate-2026-11-25.md) `069475e5ad66acab9cea71b7110b01436ba037b9678e176dbb0980210a4c8808`가 승인 SHA-256과 같습니다. SCR 연결은 별도 07 초안의 사용자 흐름 대조표에 남겼습니다. |
| 저장소와 단계 | 원격 main과 시작 HEAD는 `c82e3b18f05d56c7d332681c4d3b3e85d43fec32`입니다. [프로젝트 07 설정](.corthex/project.json)에서 원본은 `docs/07-sitemap/sitemap.yaml`, 원본 우선, 사람용 문서는 `sitemap.md`입니다. 두 원본을 보존하고 영향 범위만 담은 YAML과 그 세 보기를 로컬 초안으로 만들었습니다. [작업 규칙](AGENTS.md) · [기존 사이트맵](docs/07-sitemap/sitemap.yaml) |
| SCR 범위 | main에 있는 최댓값은 SCR-220이며 관리 변경이 SCR-220~229를 예약했습니다. 열린 PR #122·#133·#137의 추가 행과 로컬 origin 브랜치 참조에서 SCR-230과 iOS 알림 표면의 중복을 발견하지 못했습니다. [ID 범위](docs/10-wbs/README.md#id-범위) |
| 07 검토 파일 | [YAML 초안](docs/07-sitemap/iphone-home-webapp-notifications.draft.sitemap.yaml) SHA-256 `45de23588d8edad49a7d67ca9601ea30114e0c57676c11b5a1d6e60e5f7ec193`, [생성 보기](docs/07-sitemap/iphone-home-webapp-notifications-draft.md) SHA-256 `901679eb082e19db7ed76dac25f21f6cee7284c44a58b6c1d292aecd3d97bb85`. 이 메모의 해시는 Orca 인계에 함께 적습니다. |

## 화면 재사용과 변경 범위

| 화면 | 승인된 원문과 동작 | 07 제안과 이유 |
| --- | --- | --- |
| SCR-165 내 마롱이 · SCR-163 가입 | SCR-165#web-ios와 SCR-163#done의 설치 안내에 “알림과 전화 벨은 안드로이드 앱에서만 와”가 있습니다. 기존 설치 주소와 아이콘은 SPEC-396·REQ-461입니다. | SCR-165의 기존 설치 안내 자리에서 일반 Safari의 홈 화면 추가를 안내하고, 지원되는 설치의 기기 로그인부터 그 설치의 권한·구독 관리를 표시합니다. 기존 가입 성공 안내는 플랫폼 범위만 조정합니다. 별도 설정 주소보다 기존 `/chat/me`가 설치 지원 여부와 상태를 한 곳에서 다룹니다. SPEC-520~530·554, API-310~313. [기존 설치 안내](docs/08-screens/unified.md#14-웹아이폰-사파리에서-다른-것) |
| SCR-107 글 대화 · SCR-109 메뉴 · SCR-164 로그인 | 기존 SCR-107#unread는 방에 남은 글, SCR-107#ring-pending은 직접 글 대화에 들어온 사용자의 받기 띠입니다. 기존 인증 복귀는 SCR-164를 사용합니다. | 고정된 `/chat/#notice=<대상 참조>`를 SCR-107의 진입으로 사용합니다. 조회와 접근 거절·오프라인은 같은 화면 상태입니다. 미인증은 SCR-164로, 로그인 후 현재 계정으로 다시 검증합니다. 일반 Safari·직접 진입의 기존 받기 띠와 메뉴는 기존 흐름을 사용합니다. SPEC-539~545·552, API-314. [기존 상태 정의](docs/08-screens/unified.md#15-다른-화면에서-바뀌는-곳) |
| SCR-001 통화 홈 · SCR-002 통화 중 | 승인 FL-225는 받기 화면과 명시적 일반 통화 선택을 SCR-001, 통화 연결을 SCR-002에 묶습니다. 기존 휴대폰 화면은 SCR-001의 다른 기기 통화 안내와 SCR-002의 재연결을 사용합니다. | 인증·대상 확인 뒤 SCR-001에 유효 대기·미수락 만료·이미 수락·응답 불가를 상태로 표시합니다. 탭은 조회, 별도 받기만 API-315, 만료 뒤 사용자가 선택한 일반 발신은 API-317의 별도 모드입니다. 같은 클라이언트만 기존 통화에 돌아갑니다. 상태별 새 페이지는 필요하지 않습니다. SPEC-545~551. [승인 FL-225](docs/03-user-flow/FL-225-iphone-answer-call-notification-draft.md) · [기존 통화 홈](docs/08-screens/SCR-001.md) · [기존 통화 중](docs/08-screens/SCR-002.md) |
| SCR-101·108·110·111·112·130 Android | Android 코드 12의 기존 앱 창·글 알림·벨·전화 알림·업데이트 경로입니다. API-107은 기존 웹소켓 응답을 사용합니다. | SCR-101에서 다른 클라이언트가 동일 약속 전화를 먼저 유효 수락한 경우에만 기존 `call_busy`를 적용합니다. 수신 자격과 앱 업데이트, 일반·미수락 만료·직접 통화와 기존 응답 형식은 회귀 항목입니다. 기존 화면 수와 주소는 같습니다. SPEC-553 및 06 Q3. [기존 Android 약속 전화](docs/app-ring.md) · [기존 통화 계약](api/call-live.openapi.yaml) |
| SCR-230 홈 화면 웹앱 알림 | 기존 사이트맵의 앱 알림 SCR-108·111은 Android 시스템에서 표시됩니다. 홈 화면 웹앱의 알림은 e2412와 SPEC-532~538·543에서 승인된 진입입니다. | iOS 시스템에 표시되는 한 표면을 새 ID로 제안합니다. 글·일정과 약속 전화는 표시 유형으로 관리합니다. 표면 식별자 `ios:notification/webpush`에 제품 HTTP 경로는 없습니다. iOS 허용과 설치별 자격을 적용하고 시스템에 먼저 표시된 알림의 탭은 항상 현재 계정에서 확인합니다. |

기존 SCR 13개 중 5개는 변경 초안, 8개는 재사용입니다. iOS 알림 표면 1개가 추가되어 07 영향 범위는 14개입니다. 기존 이름·부모·경로·수명주기를 유지했습니다. SCR-230의 `active`는 후보 사이트맵에 포함된 수명주기 상태입니다. 실제 기기 제공 범위는 후속 시험에서 정합니다. 오래된 사이트맵에는 일부 Google Access 표기가 남아 있습니다. YAML의 `sourceAccess`는 그 표기를 보존하며, 초안의 `access`는 06의 기기 로그인과 대상·설치 조건을 해당 흐름에 적용합니다. OS 공유 메뉴·홈 화면 아이콘·권한 팝업·잠금 화면 자체는 플랫폼이 제공하며, 사용자가 보는 단계는 해당 SCR의 진입 또는 상태로 연결했습니다.

### 통화 화면의 경로 확인

기존 사이트맵에서 SCR-001은 `/`, SCR-002는 `/call`로 표현됩니다. 현재 소스의 통화 서버는 `/`에서 통화 문서를 주고 `/live`로 연결합니다. `/call`을 새 HTTP 이동 대상으로 두는 근거는 확인되지 않았습니다. 홈 화면 웹앱 manifest의 시작 주소와 범위는 `/chat/`입니다. 따라서 알림의 실제 진입 주소는 고정 API 계약의 `/chat/#notice=<대상 참조>`를 사용하고, 그 뒤 SCR-001·002의 논리적 화면 전환을 제안합니다. 새 경로·Safari 창 전환은 이 초안에서 정하지 않았습니다. 08에서 기존 설치·현재 창과 클라이언트를 유지하는 화면 전환을 설계하고, 12에서 잠금·앱 전환 뒤 같은 통화 ID와 양방향 오디오를 확인합니다. 이를 위해 새 독립 경로나 범위 변경이 필요해지면 기존 기준과 대안을 별도 검토합니다. [현재 manifest](marong/app_chat_static/manifest.webmanifest) · [현재 통화 서버](tools/vertex_live/server.py) · [06 알림 진입 계약](docs/06-api/iphone-home-webapp-notifications-version-candidate.md#알림-대상과-통화-결과)

## 검증과 08 인계

- 9개 고정 FL의 135개 노드를 대조했습니다. 사용자에게 보이는 78개를 SCR에 연결했고, 그중 13개는 OS 맥락을 표시했습니다. 나머지 57개는 내부 판정 또는 별도 화면을 열지 않는 흐름입니다. 기존 FL에 이미 적힌 SCR 연결 17곳을 보존했습니다.
- YAML 중복 키와 SCR·경로 중복, 원래 부모·수명주기, 접근 조건, 진입점에서의 도달성 및 전이 30개를 검사했습니다. SPEC 35개와 고정 API 8개의 연결, 알림 탭·명시적 받기·만료 뒤 일반 통화·Android 거절의 전이를 각각 대조했습니다. YAML 생성 트리·목록·분기에는 각 화면을 한 번씩 넣었습니다.
- 로컬 링크 35개와 앵커 5개, YAML에서 다시 생성한 보기의 바이트 일치를 확인했습니다. Mermaid 11.12.0 파서와 CORTHEX 다이어그램 검사에서 통과했고 용어 지적은 0건입니다.
- 08은 기존 SCR의 알림 설정과 구독 상태, 대상 확인 중·접근 거절·오프라인, 만료·이미 수락·시작 실패·재연결 상태의 표시와 초점 이동을 정의합니다. 실기기의 권한 흐름, 잠금 후 진입, 닫은 알림의 재도착, Android 양쪽 수락 경쟁, 같은 통화 복구와 오디오는 12의 별도 검증입니다.

07 체크포인트의 대상은 SCR-230과 기존 화면의 재사용 구조입니다. 별도 사용자 동작 승인 후보는 현재 발견하지 못했습니다.
