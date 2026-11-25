# 아이폰 홈 화면 웹앱 알림 03단계 사용자 흐름 체크포인트

2026-11-25 KST · 마롱이 Orca 항목 143 · 03단계 흐름 검토 대기

## 승인 근거와 작업 기준

| 항목 | 기록 |
| --- | --- |
| 사용자님 직접 선택 | 2026-11-25 03:22:31 KST, 항목 143 e2412의 “홈 화면 웹앱 알림을 눌러 받기”. |
| 02단계 범위 승인 | 오랑이 위임 답변 `msg_ff93c629ac92`, 요청 `msg_822cfaeef194`. A·B·C 승인에 따라 REQ-640~675의 범위를 이어 받았습니다. [02 범위 기록](iphone-webapp-02-version-candidate-2026-11-25.md#02단계-범위-승인) |
| 02단계 버전 고정 | 오랑이 위임 답변 `msg_0354290a56b2`, 요청 `msg_2c86d111f494`. 승인 대상은 항목 143 e2424의 첨부 파일이며 고정 근거는 e2428에 있습니다. [02 고정 요구사항](docs/02-prd/iphone-home-webapp-notifications-version-candidate.md)의 SHA-256 `18d178fe7325b1e6bf791b1534da8549f330b4b038ce4ac11200fd79bb961d5f`가 승인 값과 일치했습니다. |
| 저장소 기준 | 착수 시 원격 `main`과 작업 폴더 HEAD `c82e3b18f05d56c7d332681c4d3b3e85d43fec32`가 일치했습니다. 기존 FL 최댓값은 216이고 WBS에서 215~219가 예약됐습니다. 열린 PR #122·#133·#137의 추가 행을 대조하고 FL-220~228을 사용했습니다. [WBS ID 범위](docs/10-wbs/README.md#id-범위) |
| 작성 범위 | 프로젝트의 03 원본 경로는 `docs/03-user-flow/`이고 소스가 기준입니다. 이번 흐름 검토는 Orca 항목 143에서 합니다. 기존 승인 파일과 단계 설정은 그대로 보존했습니다. [프로젝트 설정](.corthex/project.json) · [저장소 규칙](AGENTS.md) |

## 흐름 파일과 SHA-256

| 로컬 흐름 초안 | SHA-256 |
| --- | --- |
| [FL-220 아이폰 홈 화면에 추가하고 알림 허용](docs/03-user-flow/FL-220-iphone-webapp-enable-notifications-draft.md) | `a053f52dc9e6e5cb326c27d9324165dd93c81435d2c1cc641358cb507c7311f6` |
| [FL-221 웹 알림 구독 확인·변경·해제](docs/03-user-flow/FL-221-iphone-webapp-manage-subscription-draft.md) | `ccb24684b3bcf8f6d84334096c2a4e63af2e3e6a6fbcb824cd9475923c31909d` |
| [FL-222 새 답변·선톡·일정 알림 받기](docs/03-user-flow/FL-222-iphone-deliver-message-notifications-draft.md) | `9f3dd72b1d26391af0d1cf14feb0a1d0a0a7c19eafe616a5c5a1237ebbb1194f` |
| [FL-223 글 알림을 눌러 해당 방 열기](docs/03-user-flow/FL-223-iphone-open-message-notification-draft.md) | `406b553900fa1795ef91ab3642e886282e7b35a362ac24efb39dcb1d329b9faa` |
| [FL-224 유효한 약속 전화 알림 받기](docs/03-user-flow/FL-224-iphone-deliver-scheduled-call-notification-draft.md) | `9b19f834e4364c90e0d0fdc0c574eab8b5e6e109561d80a83e6d07a0a0e87bbf` |
| [FL-225 홈 화면 웹앱 전화 알림을 눌러 받기](docs/03-user-flow/FL-225-iphone-answer-call-notification-draft.md) | `c0625a0a07ac45847ef46369a8214efe60294b1e3c932d8abe4ef5e9492408c0` |
| [FL-226 잠금이나 앱 전환 뒤 통화로 돌아가기](docs/03-user-flow/FL-226-iphone-resume-call-draft.md) | `a385f3624e7cca30a99d27153ba3525a355e21ca51666fb8500a3e5d38671f38` |
| [FL-227 일반 Safari에서 기존 웹 기능 사용](docs/03-user-flow/FL-227-iphone-safari-use-draft.md) | `06cd8a3f2a54da435b996b457314f37c91fcc2e17dadcaf6ac126e9ad7824ab2` |
| [FL-228 Android에서 기존 알림과 전화 이용](docs/03-user-flow/FL-228-android-notification-regression-draft.md) | `803da5a5a06e1796733ec3bcb71acf6d87873d1926bdfd95b6d5923fd6948cb0` |

## 기존 승인 흐름과의 관계

| 기준 항목 | 이번에 추가한 흐름과 근거 |
| --- | --- |
| FL-176과 SPEC-396 | 기존 “웹에는 푸시 알림과 전화 벨이 없어요.” 중 홈 화면 웹앱의 푸시 범위는 02 승인으로 바뀌었습니다. FL-220·222·223·224가 설치·허용과 수신·탭 진입을 추가합니다. 일반 Safari의 가입·로그인·글 대화·직접 통화는 FL-227에서 회귀 확인합니다. [기존 FL-176](docs/03-user-flow/FL-176-web-inbox.md) · [고정 REQ-640~675](docs/02-prd/iphone-home-webapp-notifications-version-candidate.md#기존-승인-항목과-차이) |
| FL-169·171 | 기존 로그인과 계정 확인을 설치·구독 및 알림 진입에 연결했습니다. 다른 계정으로 로그인했거나 대상이 유효하지 않으면 글과 전화 모두 내용을 열지 않습니다. 로그인 자체와 기기 추가 코드의 기존 계약은 유지합니다. [가입 FL-169](docs/03-user-flow/FL-169-invite-join.md) · [로그인 FL-171](docs/03-user-flow/FL-171-add-device.md) |
| FL-111·SPEC-135·FL-002 | e2412와 02 승인 A·C에 따라 홈 화면 웹앱의 알림 탭은 통화 수락 전에 상태를 확인합니다. FL-225는 잠금 해제 또는 재로그인 중 만료, 받기 직전 만료를 표시합니다. 다른 기기가 먼저 받으면 별도의 처리된 상태를 표시합니다. 일반 통화는 별도 사용자 선택으로 FL-002에 연결합니다. 직접 진입하는 기존 웹과 Android의 벨·수락 흐름은 기존 기준을 사용합니다. [약속 전화](docs/app-ring.md#3-사용자-흐름-03) · [일반 통화 FL-002](docs/03-user-flow/FL-002-call.md) |
| SPEC-383과 Android 기존 전달 | 02 승인 B에 따라 같은 설치에서 해당 답변을 보고 있음이 확인된 경우 그 설치의 답변 푸시만 생략합니다. 웹과 Android는 각자 수신 자격을 확인합니다. 방 기록은 한 건이며, 전화 알림과 다른 적격 설치의 푸시는 별도로 판단합니다. 잠금 화면에는 원문을 표시하지 않습니다. [통합 명세](docs/04-functional-spec/unified.md#38-디스코드-없는-보내기-경로spec-383) |
| FL-004·SPEC-386·BUG-114 | 같은 클라이언트의 복구 가능한 연결은 FL-226에서 같은 통화로 돌아옵니다. 종료된 통화는 기존 다시 걸기를 사용합니다. 일반 Safari와 홈 화면 웹앱의 iPhone 재연결 시험은 Android의 알림·업데이트 회귀와 구분합니다. [기존 재연결 FL-004](docs/03-user-flow/FL-004-reconnect.md) · [BUG-114](docs/12-qa/BUG-114-web-call-reconnect.md) |

기존 승인 원문을 삭제하거나 연기하는 제안은 없습니다. 기존 동작의 범위가 바뀌는 내용은 e2412와 고정 요구사항에서 이미 승인한 홈 화면 웹앱 경로에 해당합니다. 이번 검토에서 별도 제품 범위 질문은 발견되지 않았습니다.

## 문서 검증

- 흐름 9개의 단계 135개·연결 158개를 검사했습니다. 결정 43개마다 라벨이 붙은 분기가 있고, 각 단계는 시작에서 도달할 수 있으며 종료 47개 중 하나로 이어집니다. 만료·다른 기기 선행 수락·명시적 일반 통화 선택과 답변 푸시 생략의 연결을 별도로 검사했습니다.
- 각 단계의 REQ를 02 고정본과 대조했습니다. Must 34개와 Should 2개가 모두 연결됐습니다. 표시한 기존 SCR은 사이트맵에 있습니다. 새 화면 ID는 07 이후에 정합니다.
- 로컬 링크와 앵커 67개, 각 흐름의 SHA-256, FL 번호 충돌 여부를 확인했습니다. CORTHEX Mermaid 린트와 용어 검사에서 지적 0건이었습니다. 이 결과는 흐름 문서의 검증이며 실기기의 수신·통화 결과는 후속 시험에서 확인합니다.

## 03단계 체크포인트

다음 경로를 검토한 뒤 FL-220~228 초안을 03의 기준으로 승인할지 확인합니다.

- **설치·구독** — 미지원·권한 거절·오프라인에서도 일반 Safari의 기존 기능으로 돌아갈 수 있습니다. 철회·로그아웃·영구 무효는 해당 설치 또는 로그인만 새 전송에서 제외합니다.
- **글 알림** — 기기별 허용과 방 한 건을 유지합니다. 해당 답변을 보고 있음이 확인되지 않은 적격 설치에는 전송합니다. 탭한 뒤 현재 계정·방·메시지가 유효할 때만 방이 열립니다.
- **전화 알림과 복귀** — 탭과 받기는 별도 동작입니다. 잠금 해제·재로그인 중 또는 받기 직전 만료, 먼저 수락한 다른 기기, 오프라인, 다른 계정의 경로를 각각 확인합니다. iPhone 통화 복귀는 별도의 실기기 확인 대상입니다.

전송 방식·권한 감지·최소 iOS 버전, 동일 설치와 답변 열람 확인의 기술 조건, 약속 전화의 시간·수락·오류 계약, 기존 화면의 새 상태와 문구는 후속 설계에 남깁니다. 03 초안은 이 기술 항목이나 후속 단계의 승인 근거로 사용되지 않습니다. 실기기 확인과 운영 반영도 별도입니다.
