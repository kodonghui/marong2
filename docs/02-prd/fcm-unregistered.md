# FCM 등록 해제 판단: 요구사항

상태: 2026-11-24 체크포인트 통과(D181\~D185, 승인한 사람 사용자님, [01 도메인 8.1절](../01-domain/fcm-unregistered.md#81-체크포인트-답2026-11-24)). 새 요구사항은 active예요. 요청·기준선·바뀐 승인 항목·체크포인트 답은 [01 도메인](../01-domain/fcm-unregistered.md)에 있어요.
입력: [01 도메인](../01-domain/fcm-unregistered.md)의 5.1 규칙과 TERM-280, 승인 요구사항 REQ-111·112·118([app-chat.md](../app-chat.md)), REQ-124·130([app-ring.md](../app-ring.md)), REQ-282([call-first.md](call-first.md)), REQ-553·556([app-update.md](app-update.md)), PR #127로 더해진 REQ-587(admin).
ID 번호: REQ-630·631(이 패키지 범위 630\~639, [10 WBS 안내](../10-wbs/README.md#id-범위)).

## 출처 표기

| 표기 | 뜻 |
| --- | --- |
| D180 | 사용자님 2026-11-24 KST, 마롱이 항목 96 답(마롱이 봇이 이 작업에 넘김). 질문 "구글이 '등록 해제'라고 확실히 답할 때만 폰을 지움으로 바꿀까요?"에 "바꿔 줘(기능 변경 진행)" |
| 보고서 | 마롱이 조사 보고서 'FCM 400 분류 조사'(2026-11-24 16시대 KST). 추천안 1: HTTP 404이면서 FCM 상세 코드가 `UNREGISTERED`일 때만 `gone`, 400과 등록 해제가 확인되지 않는 404는 보내기 실패로 기록하고 FID 보존, 403은 `auth` |
| FCM 문서 | Firebase [FCM 오류 코드](https://firebase.google.com/docs/cloud-messaging/error-codes)와 [등록 관리](https://firebase.google.com/docs/cloud-messaging/manage-tokens)(2026-11-24 확인) |
| 기존 | 승인된 REQ-118(로그에 메시지 글·기기 식별자·이메일 없음), SPEC-117·126·131·430 |
| 새 제안 | 이 설계에서 Claude가 정한 것. 체크포인트 질문 2·3([01 도메인 8절](../01-domain/fcm-unregistered.md#8-체크포인트-질문)) |

## 요구사항

우선순위: Must(없으면 내보내지 않음), Should(첫 버전에 넣음, 늦어지면 뒤로), Could(되면 좋음). 상태: active, proposed(답 대기), deferred.

| ID | Requirement | Type | Priority | Context | Source | Status |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-630 | FCM이 보내기에 등록 해제 답(TERM-280: HTTP 404와 FCM 상세 코드 `UNREGISTERED`)을 주면 시스템은 그 폰의 FID를 지워야 하고, 그 밖의 거절(HTTP 400, 등록 해제가 확인되지 않은 404, 401·403, 429·5xx)에는 FID를 지키고 그 보내기를 실패로 처리해야 한다. 글 알림, 벨, 업데이트 메시지 모두 같다. | functional | Must | CTX-020, CTX-021 | D180, 보고서, FCM 문서 | active(D181, D183) |
| REQ-631 | FCM이 보내기를 거절해 그 보내기가 등록 해제나 실패로 끝나면, 시스템은 그 보내기마다 로그 한 줄에 메시지 종류, HTTP 상태, FCM 상위 상태, FCM 상세 코드, 틀린 칸 이름, 결과를 남겨야 한다. 키·권한 거절(401·403)은 지금처럼 1시간에 한 번 경고로 남기되 FCM 상세 코드를 더해야 한다. 어느 로그에도 메시지 글·FID·토큰·FCM 오류 메시지는 남기지 않아야 한다. | non-functional | Should | CTX-020, CTX-021 | 보고서(원인을 알 수 없었음), 기존(REQ-118), 새 제안(칸 이름, 질문 3) | active(D181, D184) |

## 승인 요구사항과의 관계

| 승인 REQ | 이 변경에서 | 이유 |
| --- | --- | --- |
| REQ-111·112(알림 받을 기기, 실패면 다른 경로) | 바뀌지 않아요 | '알림 받을 기기'의 조건(FID 있음 등)과 실패 때 다른 경로는 그대로예요. 400 뒤에도 FID가 남아 그 폰은 계속 알림 받을 기기예요. 보내기가 실패하면 지금처럼 다른 경로로 가요 |
| REQ-118(로그에 메시지 글·기기 식별자·이메일 없음) | 바뀌지 않아요 | REQ-631이 같은 금지를 지켜요. 새로 남기는 칸은 HTTP 상태와 FCM 코드·칸 이름이에요 |
| REQ-124·130(벨 보내기, 벨에 일정 내용 없음) | 바뀌지 않아요 | 벨 메시지와 받을 기기 조건이 그대로예요 |
| REQ-282(선 전화 벨을 아무 기기도 못 받으면 그림 화두 글) | 바뀌지 않아요 | 400이면 그 기기의 벨이 `failed`라 지금처럼 '모두 거절'에 들어가요 |
| REQ-553·556(업데이트 메시지, 업데이트 기록) | 바뀌지 않아요 | 보낼 폰 고르기와 기록 종류가 그대로예요. 400이 410 대신 500으로 적히는 것은 SPEC-430·8.5의 글이라 7절 F-3·F-4로 여쭤요 |
| REQ-587(앱 지워진 폰, PR #127) | 글은 그대로, 들어오는 폰이 줄어요 | "FCM이 폰의 설치를 더는 모른다고 답한 뒤"가 등록 해제 답만을 뜻하게 돼요. 뜻을 적은 TERM-242·시작 값·SPEC-460은 7절 G-1·G-3·G-4 |

## 겹침·모순 검사

- REQ-630과 REQ-587: REQ-587의 '앱 지워진 폰'은 REQ-630이 FID를 지운 폰이에요. 모순은 아니고 들어오는 폰이 줄어요(메시지 형식 오류로 '앱 지워짐'이 되던 폰이 빠짐).
- REQ-630과 REQ-112(모든 기기에서 실패하면 다른 경로): 400 뒤 FID를 지키면 다음 보내기도 그 폰을 다시 시도해요. 실패 때 다른 경로는 그대로라 친구가 말을 놓치지 않아요(통합 앱에서는 방에 남음, SPEC-383).
- REQ-631과 REQ-118·SPEC-126: SPEC-126은 '결과 이름과 개수만'이라 칸 이름을 남기려면 그 글을 넓혀야 해요(7절 F-7, 질문 3).
- REQ-630과 SPEC-430의 3번 시도: 400이 `failed`가 되면 업데이트 메시지는 10분 간격으로 3번까지 다시 가요. 3번이 넘지 않아 새 규칙은 필요 없어요(질문 2).

## 빠진 것 찾기

비교한 목록: FCM 오류 코드 표(`UNSPECIFIED_ERROR`, `INVALID_ARGUMENT`, `UNREGISTERED`, `SENDER_ID_MISMATCH`, `QUOTA_EXCEEDED`, `UNAVAILABLE`, `INTERNAL`, `THIRD_PARTY_AUTH_ERROR`), FID를 지우는 코드 세 곳(`AppPush._send`, `AppUpdatePush._send`, 진단 도구), 조사 보고서의 선택지 둘.

- 넣음: `UNREGISTERED`(지움), `INVALID_ARGUMENT`(지우지 않음), `SENDER_ID_MISMATCH`(403)·`THIRD_PARTY_AUTH_ERROR`(401)(둘 다 `auth` 그대로), `QUOTA_EXCEEDED`(429)·`UNAVAILABLE`(503)·`INTERNAL`(500)(다시 보내기 그대로), `UNSPECIFIED_ERROR`(상태에 따라 지금 규칙, 지우지 않음).
- 넣지 않음: 조사 보고서 선택지 2(근거가 있는 400도 지움). [01 도메인 5.5](../01-domain/fcm-unregistered.md#55-범위-밖)
