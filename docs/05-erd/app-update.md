# 마롱이 앱 자동 업데이트: DB 표

상태: 초안(2026-11-22 KST, Claude 마롱이 봇, 기능 변경. 2026-11-23 코드 검토 반영, PR #101 코멘트). 마이그레이션은 파일로만 있고 서버 DB에는 적용하지 않았어요. 적용은 구현 뒤 서버 반영(SPEC-442 ①)이에요.
원본: [`marong/migrations/023_app_update_events.sql`](../../marong/migrations/023_app_update_events.sql). 이 그림은 그 파일에서 손으로 옮긴 것이고, 다르면 SQL이 맞아요.
입력: [기능 명세](../04-functional-spec/app-update.md#8-2026-11-22-기능-변경-게시-즉시-업데이트와-업데이트-상태) SPEC-430\~438, [도메인](../01-domain/app-update.md) CTX-021, TERM-219\~224, 결정 D126(05 단계에 새 표).
사람 보기: GitHub의 Mermaid 그림으로 봐요. 이 변경의 검토와 체크포인트는 Orca 마롱이 항목 2와 설계 PR #101에서 해요(동희님 2026-11-22, [도메인 9.3](../01-domain/app-update.md#93-결정)).
API 계약: [`api/app-chat.openapi.yaml`](../../api/app-chat.openapi.yaml)의 API-105(`update` 칸), [`api/app-update.openapi.yaml`](../../api/app-update.openapi.yaml)의 API-267.

## 1. 바뀌는 것

2026-11-17 설계에서 이 부분의 05 단계는 '건너뜀(DB 표 없음, 릴리스 폴더만)'이었어요. 2026-11-22 동희님이 "1\~5 모두 바꿈"(Orca 마롱이 항목 2, e17)으로 4번 제안 'app-update의 05 ERD에 새 표 app_update_events를 더할까요?'를 바꾸기로 해서(D126) 표 하나를 더해요. 있는 표는 바꾸지 않아요.

| TBL | 표 | 하는 일 | 명세 |
| --- | --- | --- | --- |
| TBL-182 | `marong.app_update_events` | 업데이트 기록(TERM-223). 한 일마다 한 줄을 더하기만 해요. 종류 다섯: 업데이트 데이터 메시지 보내기를 잡음(`pushed`, 보내기 전에 남김)·보내지 못함(`push_failed`), 폰이 보고한 업데이트 상태(`state`, 설치됨 밖의 넷), 보고한 앱 버전이 올라감(`installed`, 설치됨의 유일한 기록), 친구가 APK를 받아 감(`fetched`). 칸은 친구(그 일이 있던 때의 친구), 폰(설치 ID, `fetched`만 비움), 버전 코드, 앱 버전(`installed`만), 업데이트 상태, 번호, 시도 번호(`pushed`·`push_failed`만), 때 | SPEC-430, 434, 435, 438 |

표가 없는 것: 릴리스 노트(TERM-221)와 버전 기록(TERM-222)은 릴리스 폴더의 `history.json`(SPEC-437, 형식은 [04 8.3](../04-functional-spec/app-update.md#83-버전-기록-historyjson))에 있어요. 최신 릴리스는 지금처럼 `release.json`이에요. 업데이트 배너(TERM-224)는 화면 상태예요.

```mermaid
erDiagram
  friends ||--o{ app_devices : "앱을 깐 폰(TBL-101)"
  friends ||--o{ app_update_events : "업데이트 기록"
  app_devices |o--o{ app_update_events : "그 폰의 기록(fetched는 폰 없음)"
  app_devices {
    uuid install_id PK
    bigint friend_id FK
    text fid "보낼 곳. 비면 보내지 않음"
    text app_version "뒤처졌는지 비교"
    timestamptz seen_at "30일 안이면 보낼 폰"
  }
  app_update_events {
    bigint id PK
    text kind "pushed, push_failed, state, installed, fetched"
    bigint friend_id FK "그 일이 있던 때의 친구"
    uuid install_id FK "fetched만 비움"
    integer version_code
    text app_version "installed만"
    text state "state만. installed 밖의 네 값"
    smallint status "push_failed, state=failed만"
    smallint attempt "pushed, push_failed만. 시도 번호 1-3"
    timestamptz at
  }
```

## 2. 종류마다 채우는 칸

DB 제약 `app_update_events_kind_check`가 이 표와 다른 줄을 막아요. 제약의 조건은 모두 `IS NULL`·`IS NOT NULL`로 짜거나 비교 앞에 `IS NOT NULL`을 둬서 NULL이 되지 않아요. Postgres는 결과가 NULL인 CHECK를 통과시켜서, 예를 들어 `status IN (401, 410, 500)`만 두면 `status`가 빈 `push_failed` 줄이 들어가요.

| 종류 | 설치 ID | 버전 코드 | 앱 버전 | 업데이트 상태 | 번호 | 시도 번호 | 누가 쓰나 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pushed` | 있음 | 있음 | 비움 | 비움 | 비움 | 1\~3 | SPEC-430(보내기 전에) |
| `push_failed` | 있음 | 있음 | 비움 | 비움 | 401·410·500 | 실패한 시도 | SPEC-430(보내기가 실패한 뒤) |
| `state` | 있음 | 있음 | 비움 | `installed` 밖의 넷 | `failed`일 때만 1\~999 | 비움 | SPEC-434 |
| `installed` | 있음 | 알면 | 있음 | 비움 | 비움 | 비움 | SPEC-435(API-105) |
| `fetched` | 비움 | 있음 | 비움 | 비움 | 비움 | 비움 | SPEC-435(API-142) |

규칙(도메인의 규칙을 DB가 지키는 곳):

- 한 폰·버전·시도에 업데이트 데이터 메시지는 많아야 한 번(REQ-553): 감시가 보내기 전에 `pushed` 줄을 먼저 더하고, 유일 인덱스 `app_update_events_push_attempt`(설치 ID, 버전 코드, 시도 번호, 종류. `pushed`·`push_failed` 줄만)가 한 줄만 받아요. 줄을 더하지 못하면 보내지 않아서, 봇이 다시 시작하거나 기록 쓰기가 실패해도 두 번 보내지 않아요. 보낸 뒤 실패를 적기 전에 멈추면 그 시도는 보낸 것으로 쳐요(SPEC-430). 시도는 3번까지예요.
- 설치됨은 한 곳에만(SPEC-435): `state` 칸에 `installed`가 없고, `installed` 줄은 유일 인덱스 `app_update_events_installed_once`(설치 ID, 앱 버전)로 한 폰·앱 버전에 한 줄이에요. 웹 페이지 보고와 앱의 `installed` 보고가 둘 다 새 버전을 실어 와도 한 줄이에요.
- 친구가 바뀐 폰(SPEC-438): `friend_id`는 그 일이 있던 때의 친구예요. TBL-101의 `friend_id`는 폰이 다른 친구로 다시 로그인하면 바뀌어요(기기 보고의 `ON CONFLICT (install_id) DO UPDATE SET friend_id = …`, `marong/app_store.py`). 그래서 관리자 읽기는 폰의 줄 가운데 `friend_id`가 지금 친구와 같은 줄만 보여 주고, 앞 친구 때의 줄은 지우지 않고 표에 남겨요. 감시의 한 번 규칙은 설치 ID로만 봐요(같은 폰, 같은 FCM 설치 ID라 친구가 바뀌어도 다시 보내지 않음).
- 기록은 더하기만(REQ-556): 봇 계정 `marong`에 `SELECT`, `INSERT`만 줘요. 고치기·지우기 권한이 없어요.
- 기기 식별자 밖의 개인 정보 없음(REQ-312, REQ-559): FID, 이메일, 이름, 릴리스 노트, 대화 글을 넣는 칸이 없어요. 관리자 읽기(API-267)는 설치 ID도 주지 않고 친구 이름과 폰 순번으로 바꿔 줘요.

## 3. 읽는 곳과 인덱스

| 읽기 | 인덱스 |
| --- | --- |
| 감시: 그 폰·버전의 마지막 시도와 그 시도의 `push_failed`, 보내기 전에 `pushed` 잡기(SPEC-430) | `app_update_events_push_attempt`(유일, `pushed`·`push_failed`만) |
| 기기 보고: 설치됨 한 줄(SPEC-435) | `app_update_events_installed_once`(유일, `installed`만) |
| 관리자 읽기: 폰마다 최근 20줄, 지금 친구의 줄만(SPEC-438) | `app_update_events_device_idx`(설치 ID, 때 내림차순) |
| 관리자 읽기: 친구마다 90일 안의 APK 받아 감 20줄(SPEC-438) | `app_update_events_fetched_idx`(친구, 때 내림차순. `fetched` 줄만 읽어서 `WHERE kind = 'fetched'` 부분 인덱스) |

폰이 둘이고 릴리스마다 열 줄 안팎이라 표가 작아요. 지우기와 보관 규칙은 두지 않았어요(새 제안. 한 해에 몇천 줄이 넘으면 다시 봐요).

## 4. 권한

| 역할 | 할 수 있는 것 | 근거 |
| --- | --- | --- |
| `marong`(봇, 글 대화 서버) | 읽기·더하기 | SPEC-430, 434, 435, 438 |
| `marong_call`(통화 서버) | 없음 | 통화는 업데이트 기록을 쓰지 않아요 |
| `PUBLIC` | 없음 | |

## 5. 검사(2026-11-22 KST, Claude)

- `pglast`(Postgres 파서 libpg_query)로 마이그레이션의 9문장이 모두 파싱됨. 통과.
- 2026-11-23 코드 검토 반영 뒤 다시: `pglast`로 10문장(BEGIN, SET 둘, CREATE TABLE, 인덱스 넷, GRANT, COMMIT)이 모두 파싱됨. 통과.
- 빈 DB에 014·023을 적용하는 시험, 두 번 적용, 제약 위반 줄 거절, 권한 시험은 이 작업 환경에 Postgres가 없어 하지 않았어요. TASK-475의 끝 조건이에요(TC-608).

## 6. 되돌리기

표를 더하기만 해서, 반영 뒤 문제가 있으면 코드만 앞 버전으로 되돌려도 돼요(앞 코드는 이 표를 읽지 않음). DB까지 되돌려야 할 때만 백업 뒤 `DROP TABLE marong.app_update_events`를 해요. 그러면 업데이트 기록이 사라져요.
