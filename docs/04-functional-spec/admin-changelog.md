# 관리 페이지 업데이트 내역: 기능 명세(기능 변경 4)

상태: 초안(proposed), 2026-11-24 KST, Claude. 체크포인트 전이에요. 이 문서의 행은 모두 proposed예요. 승인된 [관리 페이지 명세](admin.md)의 SPEC-450과 3.1 표가 바뀌는 곳은 [요구사항의 기능 변경 목록 4](../02-prd/admin-changelog.md#기능-변경-목록-4승인된-항목이-바뀌는-곳)의 4-5·4-6에서 따로 물어요. 답을 받기 전에는 admin.md를 고치지 않았어요.
입력: [요구사항](../02-prd/admin-changelog.md) REQ-620\~625와 시작 값, [흐름](../03-user-flow/) FL-215·216, [도메인](../01-domain/admin-changelog.md) TERM-270·271, 승인된 [관리 페이지 명세](admin.md) 1절 공통 규칙과 SPEC-450·458, 앱 업데이트 명세의 버전 기록(TERM-222, `history.json`), [AGENTS.md](../../AGENTS.md) '서버 반영', `deploy/ovh.sh`(`app-release` 명령), `marong/app_chat_static/unified.js`(`node`, `link`, `request`, `shortDate`), `main` `1a29477`(같은 날 기능 변경 3이 합쳐진 `23549d6` 위로 다시 올림).
뒤 단계: 05 바뀜 없음(표 없음), 06 [`api/admin.openapi.yaml`](../../api/admin.openapi.yaml)의 API-300, 07 SCR-220, 08 [admin-changelog.md](../08-screens/admin-changelog.md), 10 TASK-540\~545, 12 TC-700\~713가 이 SPEC 번호를 따라가요.
표시: [사실] 코드·기록에서 확인, [새 제안] Claude가 새로 정한 숫자·문구·이름, [추정] 근거 있는 짐작.
ID 번호: SPEC-500\~504(잡아 둔 범위 SPEC-500\~509).

## 1. 공통 규칙

관리 페이지 명세 [1절](admin.md#1-공통-규칙) 1\~9를 그대로 따라요(관리자 확인, `no-store`, 개인 정보 없음, 360px, `textContent`, 차례로 부르기). 더하는 것만 적어요.

1. 업데이트 내역은 저장소 파일이에요. 저장소 폴더 `marong/changelog/`에 반영 단위(TERM-271)마다 JSON 파일 하나를 두고, 운영에서는 앱 서버 코드 자리의 같은 폴더(`/opt/marong-app/marong/changelog/`)에 같은 파일이 있어요[새 제안]. 앱 서버는 이 폴더를 읽기만 해요. 쓰기 API와 쓰기 화면은 없어요.
2. 저장소가 공개예요[사실: 2026-11-24 `gh repo view` `visibility: PUBLIC`]. 그래서 내역 파일의 모든 글은 누구나 읽을 수 있다고 보고 써요. 대화 내용, 실제 친구 이름, 이메일, 설치 ID, FCM 설치 ID, 키·토큰, 전화번호를 쓰지 않아요. 실제 사람은 '친구', 운영자는 '관리자'라고 적어요(REQ-625).
3. 날짜는 한국 시각 날짜(`YYYY-MM-DD`)예요. 운영 서버 시계는 UTC라서[사실: AGENTS.md] 반영 기록의 시각을 한국 시각으로 바꾼 날짜를 적어요. 시각(시:분)은 적지 않아요. 반영 전에 써야 해서예요(SPEC-503).
4. 로그: 새로 남기는 줄은 `admin_changes file=<파일 이름> result=invalid reason=<json|schema|name|too_big|privacy|duplicate>`(읽지 못한 파일 하나마다)와 `admin_changes result=missing_dir`(폴더가 없을 때)뿐이에요. 파일 이름은 `^[A-Za-z0-9._-]{1,80}$`에 맞을 때만 그대로, 아니면 `file=?`예요. 글 내용은 남기지 않아요[새 제안].
5. 근거 링크는 공개 저장소 주소예요: `PR #<번호>` → `https://github.com/kodonghui/marong2/pull/<번호>`, 커밋 → `https://github.com/kodonghui/marong2/commit/<해시>`. 주소는 서버가 만들어 응답에 넣어요(화면이 주소를 짓지 않음)[새 제안].

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-500 | 내역 파일 형식과 저장소 시험 | REQ-620, REQ-621, REQ-623, REQ-625, TERM-271 | 저장소 폴더 `marong/changelog/` | 반영 단위 하나가 파일 하나예요: `marong/changelog/<id>.json`(UTF-8, 32KB 이하). 모양과 규칙은 3.1이에요. 검사는 `marong/admin_changes.py`의 함수 둘이에요: 파일 하나를 보는 `validate_unit`(형식·길이·값·개인 정보 패턴)과, 폴더의 `*.json`마다 `validate_unit`을 부르고 폴더 전체를 보는 `load_units`(파일 이름과 `id`가 다르면 `name`, 앱 단위의 `versionCode`가 겹치면 둘 다 `duplicate`). 저장소 시험(`tests/test_changelog.py`)과 API-300(SPEC-501)이 `load_units`를 같이 써요. 저장소 시험은 더해서 앱 단위의 버전 이름·코드가 `tools/app_release.py`의 `PAST_RELEASES`에 있으면 그 값과 같은지 봐요(`PAST_RELEASES`는 0.3.2까지라서, 지난 내역의 0.3.3·0.3.4는 SPEC-504의 받아들임 조건이 봐요). `.json`이 아닌 파일(예: `README.md`)은 읽지 않아요 | 형식이 틀린 파일 → 저장소 시험이 그 파일 이름과 이유(3.1의 이유 이름)를 적고 실패<br>`versionCode`가 같은 앱 단위가 둘(버전 이름은 파일 이름이라 겹칠 수 없음) → 둘 다 실패(`duplicate`)<br>`PAST_RELEASES`에 없는 새 버전 → 시험은 통과하고, 게시 뒤 맞춰 보기(SPEC-503)가 봐요 | Given 3.1의 예시 파일, Then 통과<br>Given 3.1 '틀린 예' 표의 파일 열하나, Then 각각 그 이유로 실패<br>Given `app-0.3.2.json`의 `versionCode` 11, Then 실패(`PAST_RELEASES`는 10)<br>Given 글에 `friend@example.com`·UUID·22자 토큰·`010-1234-5678`·`http`, Then 각각 `privacy`로 실패 | proposed |
| SPEC-501 | 업데이트 내역 읽기(API-300) | REQ-620, REQ-621, REQ-625, FL-215 | 관리자(admin 1절 1) | `GET /chat/admin/api/changes` → 200 `{units, skipped}`(3.2의 모양). 요청마다 폴더의 `*.json`을 모두 읽고(캐시 없음), SPEC-500의 `load_units`로 읽어(파일마다 검사와 폴더 검사) 통과한 단위만 3.3의 차례로 줘요. 단위마다 근거를 주소와 함께(1절 5), 항목의 `evidence`가 비면 단위의 근거를 넣어 줘요. 읽지 못한 파일은 빼고 그 수를 `skipped`에 세요. 파일 읽기는 이벤트 루프를 막지 않게 스레드에서 해요(`asyncio.to_thread`). 쿼리 값은 없어요(영역 거르기는 화면이 해요) | 관리자 아님 → 403 `not_allowed`<br>폴더가 없음 → 200 `{units: [], skipped: 0}`, 로그 `result=missing_dir`<br>파일 하나가 깨짐·32KB 넘음·형식 틀림·개인 정보 패턴 → 그 파일만 빼고 `skipped` +1, 로그 한 줄(1절 4). 응답은 200<br>`versionCode`가 같은 앱 단위가 둘 → 둘 다 빼고 `skipped` +2(`duplicate`). 파일 이름과 `id`가 다른 파일은 `name`으로 빠지니 `id` 겹침은 생기지 않아요<br>폴더를 열 수 없음(권한) → 500 `internal` | Given 시험 폴더(서버 단위 셋, 앱 단위 하나, 깨진 파일 하나), When API-300, Then 200, `units` 넷이 3.3의 차례, `skipped` 1, 로그 한 줄<br>Given 폴더 없음, Then 200 빈 목록<br>Given 관리자 아님, Then 403<br>Given 응답 전체, Then `Cache-Control: no-store`, 이메일·설치 ID·토큰 패턴이 없음<br>Given 파일 300개(각 3KB), Then 응답 500ms 안(앱 서버와 같은 기계) | proposed |
| SPEC-502 | 업데이트 내역 화면(SCR-220) | REQ-620, REQ-621, REQ-622, REQ-581, REQ-585, FL-215 | 관리자. 관리 페이지 틀(SPEC-450, 4-5로 일곱째 화면이 됨) | 경로 `/chat/admin/changes`. 탭 줄 끝 '업데이트 내역'에 `aria-current="page"`. 화면은 API-300 하나만 불러요. 맨 위 제목과 한 줄 설명, 영역 칩 일곱(전체·앱·웹·통화·대화·관리·카톡·디스코드, 기본 전체, `aria-pressed`). 그 아래 반영 단위마다 그룹(새것부터): 머리 `<h2>` '반영일 · 단위 이름', 그 아래 작은 줄 '서버 반영' 또는 '앱 0.3.4(12)'와 근거 링크, 지난 기록에서 채운 단위면 '지난 기록에서 채움' 표. 그룹 아래 항목 표(3.4): 칸은 구분 · 영역 · 항목 · 변경 전 · 변경 후 · 근거. 폭 1023px까지는 항목 한 줄이 카드 하나(첫 줄 구분·영역·항목, 둘째 줄 변경 전과 변경 후 두 칸, 셋째 줄 근거), 1024px부터는 한 줄에 칸 여섯의 표예요. 같은 HTML(`<table>`)이고 CSS만 달라요. 칩을 누르면 같은 응답을 화면에서 거르고(서버를 다시 부르지 않음) 항목이 없는 그룹은 숨겨요. 근거 링크는 새 창(`target="_blank" rel="noopener noreferrer"`). 모든 글은 `textContent`로 넣어요 | 403 → 공통#forbidden<br>500·네트워크 실패 → 공통#error('다시 해 볼게요'는 API-300 다시)<br>`units` 빈 목록이고 `skipped` 0 → #empty<br>`units` 빈 목록이고 `skipped` 1 이상 → #unreadable(파일은 있는데 모두 검사에 걸림. #empty로 보이면 고장이 숨어요)<br>`skipped` 1 이상 → 맨 위 회색 줄(#skipped), 나머지는 그대로(#filter-empty에서도 그 줄은 남음)<br>골라진 영역에 항목 0 → #filter-empty<br>`deployedOn` null(지난 기록) → 머리의 날짜 자리에 단위 이름의 날짜와 '반영일 기록 없음'(#no-date)<br>글이 100자·항목 40자 → 칸 안에서 줄바꿈(#long)<br>글에 `<img src=x onerror=…>` → 글자 그대로 보이고 실행·요청 없음 | Given API-300 예시(3.2), Then 그룹 둘, 첫 그룹 머리 '11월 24일 · 관리 페이지 다시 만들기', 항목 줄의 칸이 3.4 차례<br>Given 칩 '통화', Then 영역이 통화인 항목만, 다른 그룹은 숨김, 요청 수 1 그대로<br>Given 360·430px, Then 카드 배치이고 `scrollWidth` ≤ 화면 폭, 처음 그린 뒤 지금 탭이 탭 줄 안에 보임(4-7이 '바꿈'일 때)<br>Given 1024·1280·1440px, Then 표 배치이고 칸 여섯이 한 줄, 가로 넘침 없음, 탭 일곱이 탭 줄 안에서 밀리지 않음<br>Given 화면 읽기 프로그램, Then 각 칸을 그 머리(변경 전 등)와 함께 읽음(명시한 ARIA 역할, 3.4) | proposed |
| SPEC-503 | 반영 때 내역 쓰기·복사·맞춰 보기·되돌리기 | REQ-623, REQ-625, FL-216 | 반영하는 쪽(GPT). 4-10\~4-12가 '바꿈'으로 답을 받음 | 3.5의 차례예요. ① 친구나 관리자가 알아챌 변화가 있는 반영이면, 반영 전에 그 PR(구현 PR이나 반영 기록 PR)에 `marong/changelog/<id>.json`을 더해요. `id`는 서버면 이 PR에서 `<반영할 날>-<이름>`으로 정하고, 반영 때 반영 폴더를 그 이름으로 만들어요(`~/marong-deploy/<id>/`, `mktemp`면 `<id>.XXXXXXXX`). 앱이면 `app-<버전 이름>`. `deployedOn`은 반영할 날(한국 시각). ② 저장소 시험(SPEC-500)이 통과하고 Claude가 PR 리뷰에서 글을 봐요(개인 정보, PR과 맞는지, 친구가 읽을 말인지). ③ 반영 때 재시작 뒤에 `bash deploy/ovh.sh changelog put <파일>`이 서버에서 같은 검사 함수로 파일을 다시 보고, `~/marong-deploy/`에서 이름이 `<id>` 또는 `<id>.<임의 글자 8자>`인 반영 폴더를 딱 하나 찾아(앱 단위는 `~/marong-deploy/<id>/`를 만들어 씀) 그 폴더에 파일·sha256·복사한 시각(UTC)을 남기고, `/opt/marong-app/marong/changelog/<id>.json`으로 복사해요(root 소유, 0644). 재시작은 필요 없어요(API-300이 요청마다 읽음). ④ `bash deploy/ovh.sh changelog check <id>`가 맞춰 봐요: 서버 단위는 `deployedOn`이 `put`이 남긴 복사 시각의 한국 날짜와 같은지(`put`은 재시작 바로 뒤에 해요. 서비스 시작 시각은 다른 반영이나 다시 시작으로 바뀌고 서비스가 여럿이라 쓰지 않아요), 앱 단위는 `history.json`의 그 버전 이름 줄(코드, 게시 시각의 한국 날짜)과 같은지, 그리고 서버 파일과 저장소 파일의 sha256이 같은지. 결과를 반영 기록 PR에 적어요. ⑤ 되돌리기 스크립트가 그 단위의 파일만 지워요 | 보이는 변화가 없는 반영(로그·추적·시험·문서·백업만) → 파일을 만들지 않고 반영 기록 PR에 '업데이트 내역 없음(보이는 변화 없음)'<br>`check`가 다름(자정을 넘겨 반영함 등) → PR에서 `deployedOn`을 고치고 `put`을 다시(같은 파일 덮어씀)<br>`put`이 찾은 반영 폴더가 없거나 둘 이상 → 복사하지 않고 끝<br>그 반영 폴더에 다른 `id`의 `changelog.json`이 이미 있음 → 복사하지 않고 끝. 같은 날 같은 이름의 다른 반영이면 PR에서 `id` 끝에 `-2`<br>같은 반영을 다시 함(같은 폴더, 같은 `id`) → `put`을 다시 하면 같은 자리를 덮어써요<br>`put`의 검사 실패 → 복사하지 않고 끝(서버 폴더 그대로)<br>스위치를 켜야 보이는 기능 → 스위치를 켜는 반영의 단위에 적어요(스위치 0으로 올린 반영은 '업데이트 내역 없음') | Given 시험 파일, 임시 반영 폴더, 가짜 `history.json`, When `put` 뒤 `check`, Then 맞으면 `ok`, 복사 시각의 한국 날짜가 하루 다르면 `mismatch deployedOn`과 0 아닌 종료 코드<br>Given 반영 폴더가 없음 또는 둘, When `put`, Then 복사 0번, 0 아닌 종료 코드<br>Given 앱 단위 `app-0.3.5`(코드 13)와 `history.json`에 0.3.5가 코드 13, Then `ok`. 코드 14면 `mismatch versionCode`<br>Given 형식이 틀린 파일, When `put`, Then 복사 0번, 0 아닌 종료 코드<br>Given 되돌리기, Then 그 단위 파일만 없어지고 다른 파일 수는 그대로 | proposed |
| SPEC-504 | 지난 내역 채우기 | REQ-624, REQ-625 | 지난 내역 초안([admin-changelog-backfill.md](../10-wbs/admin-changelog-backfill.md), Claude) | 초안의 반영 단위를 파일로 옮겨요(TASK-543, GPT). 모든 단위가 `backfilled: true`. 3.6의 규칙: 근거(PR·커밋)가 없는 줄은 만들지 않음, 반영 기록이 없으면 `deployedOn` null, 변경 전을 PR이 적지 않았으면 '기록 없음', 되돌린 PR·운영에 나가지 않은 PR은 줄 없음, 보이는 변화가 없는 반영 폴더는 초안의 '단위 없는 반영 폴더' 표에만. 옮길 때 뜻을 바꾸지 않아요. 고쳐야 하면 PR 설명의 '설계 질문'에 적어요 | 초안의 글이 길이 제한을 넘음 → 옮기지 않고 '설계 질문'<br>초안과 운영 기록이 다름(예: 반영일) → 운영 기록을 따르고 '계약 손봄' 줄에 적음 | Given 옮긴 폴더, Then 단위 수와 항목 수가 초안 표의 합계와 같음, 모든 단위에 근거가 하나 이상, 저장소 시험 통과<br>Given 옮긴 앱 단위 여덟(0.2.2\~0.3.4), Then 버전 이름·코드·반영일이 초안 1절의 '앱 버전'·'반영일' 칸(운영 `history.json`에서 옮긴 값)과 같음<br>Given PR #7·#8, Then 단위 없음 | proposed |

## 3. 세부 규칙

### 3.1 내역 파일 모양

```json
{
  "format": 1,
  "id": "20261124-admin",
  "kind": "server",
  "title": "관리 페이지 다시 만들기",
  "deployedOn": "2026-11-24",
  "app": null,
  "backfilled": true,
  "evidence": ["PR #116", "PR #117", "PR #121"],
  "items": [
    {
      "type": "improved",
      "area": "admin",
      "title": "관리 페이지 화면 나누기",
      "before": "관리자 화면 하나에 초대 링크·회원·비용이 함께 있었어요",
      "after": "개요·회원·초대 링크·앱 버전·비용·아이템 여섯 탭으로 나눠 봐요",
      "evidence": []
    }
  ]
}
```

| 칸 | 규칙 | 틀리면 이유 이름 |
| --- | --- | --- |
| `format` | 숫자 1 | `schema` |
| `id` | 서버: `^[0-9]{8}-[a-z0-9][a-z0-9-]{0,39}$`(반영 폴더 이름과 같음. 반영 폴더를 이 이름으로 만들고, `mktemp`가 붙인 뒤의 `.XXXXXXXX`는 빼고 봐요). 반영 폴더가 없던 지난 반영은 `<PR을 합친 한국 날짜>-pr<번호>`. 앱: `^app-(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`. 파일 이름(`.json` 뺀 것)과 같아야 해요 | `name` |
| `kind` | `server` 또는 `app`. `app`이면 `id`가 `app-`로 시작하고 `app`이 있어야 해요. `server`면 `app`이 null | `schema` |
| `title` | 1\~40자, 앞뒤 빈칸 없음, 줄바꿈·제어 문자 없음 | `schema` |
| `deployedOn` | `YYYY-MM-DD`(한국 시각) 또는 null. null은 `backfilled: true`이고 `kind: server`일 때만 | `schema` |
| `app` | `{"versionName": "0.3.4", "versionCode": 12}`. `versionName`이 `id`의 뒤와 같음, `versionCode`는 1 이상 정수 | `schema` |
| `backfilled` | 참·거짓 | `schema` |
| `evidence` | 1\~10개. 하나하나가 `^PR #[1-9][0-9]{0,4}$` 또는 `^[0-9a-f]{7,40}$`, 겹치지 않음 | `schema` |
| `items` | 1\~30개 | `schema` |
| `items[].type` | `added`(추가) · `improved`(개선) · `fixed`(수정) · `removed`(제거) | `schema` |
| `items[].area` | `app`(앱) · `web`(웹) · `call`(통화) · `chat`(대화) · `admin`(관리) · `legacy`(카톡·디스코드) | `schema` |
| `items[].title` | 1\~40자 | `schema` |
| `items[].before` | 1\~100자. `added`면 '없음'. '기록 없음'은 `backfilled: true`일 때만 | `schema` |
| `items[].after` | 1\~100자. `removed`면 '없음'. '기록 없음'은 `backfilled: true`일 때만 | `schema` |
| `items[].evidence` | 0\~5개, 단위의 `evidence`와 같은 형식. 비면 단위의 근거를 따라요 | `schema` |
| 그 밖 | 모르는 칸이 있으면 틀림(나중에 칸을 더하면 `format`을 올려요). 파일 32KB 넘음 → `too_big`. JSON이 아님·UTF-8이 아님 → `json` | |
| 개인 정보 패턴 | 글 칸(`title`, `items[].title`·`before`·`after`)에 이것이 있으면 틀림: `@`, `http`, UUID(`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`), 영문·숫자·`_`·`-`가 20자 넘게 이어진 글(FCM 설치 ID·토큰·키), 전화번호(`01[016789]-?[0-9]{3,4}-?[0-9]{4}`) | `privacy` |

글자 수는 유니코드 글자 하나를 1로 세요(파이썬 `len`). 사람 이름은 패턴으로 막을 수 없어서 Claude 리뷰가 봐요(SPEC-503 ②).

틀린 예(TC-701에서 하나씩 써요): 파일 이름과 `id`가 다름, `format` 2, `kind: app`인데 `app` null, 앱 `id`의 버전과 `versionName`이 다름, `title` 41자, `before` 101자, `added`인데 `before`가 '없음'이 아님, `removed`인데 `after`가 '없음'이 아님, `backfilled: false`인데 '기록 없음', `backfilled: false`인데 `deployedOn` null, `evidence` 빈 목록.

### 3.2 API-300 응답 모양

```json
{
  "units": [
    {
      "id": "20261124-admin",
      "kind": "server",
      "title": "관리 페이지 다시 만들기",
      "deployedOn": "2026-11-24",
      "sortOn": "2026-11-24",
      "app": null,
      "backfilled": true,
      "evidence": [{"label": "PR #116", "url": "https://github.com/kodonghui/marong2/pull/116"}],
      "items": [
        {"type": "improved", "area": "admin", "title": "관리 페이지 화면 나누기",
         "before": "관리자 화면 하나에 초대 링크·회원·비용이 함께 있었어요",
         "after": "개요·회원·초대 링크·앱 버전·비용·아이템 여섯 탭으로 나눠 봐요",
         "evidence": [{"label": "PR #116", "url": "https://github.com/kodonghui/marong2/pull/116"}]}
      ]
    },
    {
      "id": "20261026-pr1",
      "kind": "server",
      "title": "카톡: 1:1 얘기 나누기와 연달아 온 말",
      "deployedOn": null,
      "sortOn": "2026-10-26",
      "app": null,
      "backfilled": true,
      "evidence": [{"label": "PR #1", "url": "https://github.com/kodonghui/marong2/pull/1"}],
      "items": [
        {"type": "improved", "area": "legacy", "title": "1:1에서 한 얘기 나누기",
         "before": "한 친구가 1:1에서 한 얘기를 다른 친구의 1:1에서 마롱이가 몰랐어요(요약이 쌓일 때만 메모를 만듦)",
         "after": "1:1에서 한 얘기를 바로 공유해서 다른 친구와의 대화에서도 알아요",
         "evidence": [{"label": "PR #1", "url": "https://github.com/kodonghui/marong2/pull/1"}]}
      ]
    }
  ],
  "skipped": 0
}
```

- `sortOn`은 서버가 채워요: `deployedOn`이 있으면 그 값, null이면 `id` 앞 여덟 자리의 날짜예요. 화면은 #no-date에서 이 날짜를 보여요.
- 응답에는 파일에 있는 것만 있어요. 친구·계정·폰 정보를 읽거나 섞지 않아요.

### 3.3 차례

1. `sortOn`이 늦은 것부터.
2. 같은 날이면 단위 근거(`evidence`)의 가장 큰 PR 번호가 큰 것부터. PR은 합친 차례로 번호가 붙고 반영은 대개 합친 차례라서, 시각 없이도 같은 날의 반영 차례에 가까워요. 근거가 커밋뿐이면 0으로 봐요.
3. 그래도 같으면 `id`의 거꾸로 차례(문자 차례).
4. 단위 안의 항목은 파일에 적힌 차례 그대로예요(쓴 사람이 중요한 것부터 써요).

지난 내역으로 측정한 결과(반영 폴더의 바뀐 시각과 비교): 2026-11-24의 다섯 단위는 실제 차례와 같고, `id` 차례만 쓰면 맨 나중 반영(`20261124-bug-124`)이 넷째로 가요. 2026-11-15·22는 PR 번호 차례도 실제 차례와 몇 줄 달라요(오래된 PR을 나중에 반영한 날). 정확한 차례가 필요하면 반영 뒤에 시각을 적어야 해서, 반영 전에 쓰는 지금 절차와 맞지 않아 받아들였어요[새 제안].

### 3.4 화면 칸과 이름

| 칸 | 폰(1023px까지) | 넓은 폭(1024px부터) | 값 → 보이는 글 |
| --- | --- | --- | --- |
| 구분 | 카드 첫 줄 맨 앞 표(작은 글자, 테두리) | 첫째 칸 72px | `added` 추가, `improved` 개선, `fixed` 수정, `removed` 제거 |
| 영역 | 카드 첫 줄, 구분 뒤 회색 글 | 둘째 칸 104px | `app` 앱, `web` 웹, `call` 통화, `chat` 대화, `admin` 관리, `legacy` 카톡·디스코드 |
| 항목 | 카드 첫 줄, 굵은 글 | 셋째 칸 22% | 그대로 |
| 변경 전 | 카드 둘째 줄 왼쪽 칸, 위에 작은 이름 '변경 전', 회색 글 | 넷째 칸(남은 폭의 반) | 그대로. '없음'·'기록 없음'은 회색 기울임 |
| 변경 후 | 카드 둘째 줄 오른쪽 칸, 위에 작은 이름 '변경 후', 기본 글 | 다섯째 칸(남은 폭의 반) | 그대로 |
| 근거 | 카드 셋째 줄, 작은 이름 '근거' 뒤에 작은 링크를 '·'로 이음 | 여섯째 칸 112px | `label` 글, `url` 링크 |

- 표는 `<table>`이고 폰에서 CSS로 줄을 카드로 바꿔요. 그러면 몇몇 브라우저가 표의 뜻을 잃어서, `table`·`row`·`columnheader`·`cell` 역할을 HTML에 직접 적어요. 폰에서 칸 머리(`<thead>`)는 보이지 않게만 숨기고(화면 읽기 프로그램은 읽음), 칸의 작은 이름('변경 전' 등)은 CSS `::before`가 아니라 HTML 글로 둬요.
- 넓은 폭은 `table-layout: fixed`이고 긴 글은 칸 안에서 줄바꿈해요(`overflow-wrap: anywhere`). 표의 폭은 본문 폭 그대로예요(admin 08 1.1절의 '한 칸').
- 색은 지금 토큰만 써요(새 토큰 없음): 추가 `--accent`, 개선 `--star`, 수정 `--muted`, 제거 `--danger`. 색만으로 구분하지 않고 늘 글자로도 적어요.

### 3.5 반영 차례(AGENTS.md '서버 반영'에 한 단계)

| 차례 | 하는 일 | 누가 | 남는 것 |
| --- | --- | --- | --- |
| 1 | 보이는 변화가 있는지 정함. 없으면 반영 기록 PR에 '업데이트 내역 없음(보이는 변화 없음)' 쓰고 끝 | 반영하는 쪽 | PR 설명 한 줄 |
| 2 | 반영 전에 PR에 `marong/changelog/<id>.json` 더함. 서버 `id`는 `<반영할 날>-<이름>`, `deployedOn`은 반영할 날 | 반영하는 쪽 | 파일 |
| 3 | 저장소 시험 통과, Claude 리뷰 | 반영하는 쪽, Claude | PR 리뷰 댓글 |
| 4 | 백업 → 마이그레이션 → 파일 → 재시작(지금 차례 그대로). 반영 폴더는 `id` 이름으로 만듦 | 반영하는 쪽 | 반영 폴더 |
| 5 | `deploy/ovh.sh changelog put <파일>` | 반영하는 쪽 | 서버 파일, 반영 폴더의 `changelog.json`·`changelog.sha256` |
| 6 | 로그 5분 오류 확인(지금 그대로), 그리고 `deploy/ovh.sh changelog check <id>` | 반영하는 쪽 | 반영 기록 PR의 결과 줄 |
| 7 | 되돌릴 때 되돌리기 스크립트가 `changelog.json`의 그 단위 파일도 지움 | 반영하는 쪽 | |

- 앱 릴리스도 같아요: 2에서 `app-<버전 이름>.json`, 4 대신 `deploy/ovh.sh app-release publish`, 6에서 `check`가 `history.json`과 맞춰 봐요.
- `put`·`check`는 노트북에서 돌고 ssh 별칭으로 서버에 닿아요(지금 `deploy/ovh.sh`의 `on_server`와 같음)[사실]. 서버에서 파일을 검사할 때는 앱 서버의 파이썬과 저장소의 같은 검사 함수를 써요.

### 3.6 지난 내역 규칙

1. 근거 차례: 반영 기록(PR 설명의 '서버 반영'·'운영 반영' 절, 반영 기록 PR #118·#121·#122·#124·#126), 운영 반영 폴더 이름과 시각(읽기만), `history.json`(앱), PR 제목과 설명, BUG 문서. 위가 아래와 다르면 위를 따라요.
2. 반영일: 반영 기록의 재시작·게시 시각을 한국 날짜로. 기록이 없으면 null(합친 날을 반영일로 쓰지 않아요).
3. 단위: 반영 폴더 하나 = 단위 하나(보이는 변화가 있을 때). 폴더가 없던 시기(2026-11-15 전과 그날 폴더 없는 반영)는 PR 하나 = 단위 하나(`<합친 날>-pr<번호>`). 스위치를 0으로 올린 반영은 단위가 없고, 스위치를 켠 반영이 단위예요.
4. 글: PR이 적은 말만 옮겨요. 변경 전을 PR이 적지 않았으면 '기록 없음'. 사람은 '친구'·'관리자', 대화 예시는 옮기지 않고 기능 이름과 동작으로만.
5. 앱: `history.json`에 있는 0.2.2부터 앱 단위예요. 그 전 앱(0.1·0.2.0·0.2.1, 손으로 깐 버전)의 바뀜은 같은 때의 서버 단위에 영역 '앱' 항목으로 적어요.
6. 단위가 되지 않은 반영 폴더는 초안의 표에 이름과 이유(내부, 스위치 0, 같은 반영 다시, 근거 PR 없음)를 남겨요.

## 4. 추적

| 요구사항 | 흐름 | 명세 | API | 화면 | 작업 | 시험 |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-620 | FL-215 | SPEC-501, 502, (SPEC-450 4-5) | API-300 | SCR-220 | TASK-541, 542, 545 | TC-704, 705, 707, 710, 713 |
| REQ-621 | FL-215 | SPEC-500, 502 | API-300 | SCR-220 | TASK-540, 542 | TC-700, 701, 704, 707 |
| REQ-622 | FL-215 | SPEC-502 | | SCR-220 | TASK-542 | TC-708, 713 |
| REQ-623 | FL-216 | SPEC-503 | | | TASK-544, 545 | TC-702, 711 |
| REQ-624 | | SPEC-504 | | | TASK-543 | TC-712 |
| REQ-625 | FL-216 | SPEC-500, 501 | API-300 | | TASK-540, 541 | TC-703, 706 |
| REQ-581·585(승인) | | SPEC-502 | | SCR-220 | TASK-542 | TC-709, 713 |

## 5. 열린 것

- 같은 날 안의 차례(3.3의 2)가 반영한 차례와 다를 수 있어요. 시각 칸을 더하면 반영 뒤에 파일을 다시 고쳐야 해서 뺐어요. 불편하면 `format` 2에서 `deployedAt`을 더하는 것을 다시 봐요.
- 파일이 1000개를 넘으면(하루 한 번 반영으로 약 3년) 응답이 1MB를 넘을 수 있어요[추정]. 그때 쪽 나누기(최근 n개)를 다시 봐요.
- 친구에게 보이는 업데이트 소식, 푸시 알림, 관리 페이지에서 쓰기는 범위 밖이에요(02 7절).
