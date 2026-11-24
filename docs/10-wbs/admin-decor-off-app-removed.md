# 관리 페이지 기능 변경 3: 꾸미기 꺼짐 안내와 앱 지워진 폰 작업 목록(10단계 WBS)

2026-11-24 작성(Claude, Orca 마롱이 항목 3). 입력: 도메인 [admin.md 9.4절](../01-domain/admin.md#94-기능-변경-3-꾸미기-꺼짐-안내와-앱-지워진-폰)(TERM-242, D145·D146), 요구사항 [admin.md](../02-prd/admin.md)(REQ-586·587과 [기능 변경 목록 3](../02-prd/admin.md#꾸미기-꺼짐-안내와-앱-지워진-폰-기능-변경-목록-3)), 흐름 [FL-192](../03-user-flow/FL-192-admin-items.md)·[FL-201](../03-user-flow/FL-201-admin-app-version.md), 기능 명세 [admin.md](../04-functional-spec/admin.md)(SPEC-459·460, 바뀌는 SPEC-453·456과 3.2·3.3·3.5·3.6), [app-update.md](../04-functional-spec/app-update.md)(SPEC-438·8.6), [pet-app.md](../04-functional-spec/pet-app.md)(1절 5), 계약 [app-update.openapi.yaml](../../api/app-update.openapi.yaml) 0.3.0-draft(API-267 `removedAt`)·[admin.openapi.yaml](../../api/admin.openapi.yaml) 0.2.0-draft(API-280 칸 설명), 화면 상태 [08-screens/admin.md](../08-screens/admin.md)(SCR-201#app-removed, SCR-203#app-removed, 9절)·[08-screens/pet-app.md](../08-screens/pet-app.md)(SCR-186#decor-off), 시험 계획 [12-qa/admin.md](../12-qa/admin.md) ⑧(TC-653\~659).

상태: 2026-11-24 체크포인트 통과(D147\~D149·D160\~D163, 질문 0\~6 모두 추천안, 승인한 사람 사용자님, [도메인 9.4절](../01-domain/admin.md#94-기능-변경-3-꾸미기-꺼짐-안내와-앱-지워진-폰)). 승인된 글이 바뀌는 곳 3-1\~3-14는 줄마다 '바꿈'(D148)이라 아래 TASK는 그대로이고, 답에 덧붙인 시험 TC-658(다른 이유의 404, D149)과 TC-659(뒤처짐을 세는 네 곳이 같은 값, D160)를 끝 조건에 더했어요. 관리 페이지 다시 만들기의 [작업 목록](admin.md)(TASK-490\~501)은 바뀌지 않아요.

## GPT 인계

- 목표: ① 꾸미기가 꺼진 서버(지금 운영)에서 관리 페이지의 아이템 화면(SCR-186)이 오류 줄과 '다시 보기' 대신 '꾸미기가 꺼져 있어요'를 보여요(D145, REQ-586, SPEC-459). ② 앱 지워진 폰(TERM-242)을 앱 버전 화면(SCR-203)과 회원 한 사람의 폰(SCR-201)에 '앱 지워짐'으로 보이고, 뒤처진 폰(개요의 수, 주의 항목 `app_behind`, '뒤처짐' 표)에서 빼요(D146, REQ-587, SPEC-460). 동희님 답(사용자님, 마롱이 항목 3, 2026-11-24 KST): "'꾸미기가 꺼져 있어요' 안내로 바꾸기", "'앱 지워짐'으로 표시하고 뒤처짐에서 빼기".
- 시작: 이 설계 PR(#127)이 `main`에 합쳐지고 마롱이가 지시하면, `main` 머리에서 새 브랜치 `codex/admin-decor-off-app-removed`. 초안 PR 하나예요. 관리 페이지 다시 만들기 구현(PR #116·#117)은 이미 `main`에 있어서 그 위에서 시작해요. 체크포인트 답은 모두 추천안이라(D147\~D149·D160\~D163) 목록 3-1\~3-14의 바뀐 글을 모두 구현해요. 구현 PR 병합과 운영 반영(TASK-505)은 체크포인트 위임에 들지 않아서 마롱이가 사용자님께 여쭤 승인받은 뒤에 해요.
- 읽을 것: [기능 명세](../04-functional-spec/admin.md)의 SPEC-459·460, 3.2의 `app` 줄, 3.3의 마지막 줄, 3.6의 `removedAt` 줄. [app-update 기능 명세](../04-functional-spec/app-update.md) 8.6의 `removedAt` 줄. 계약 `api/app-update.openapi.yaml`의 API-267(`AdminAppDevice`, 예시 `removed`)과 `api/admin.openapi.yaml` API-280의 `app`. [화면 상태](../08-screens/admin.md)의 SCR-201#app-removed·SCR-203#app-removed·9절, [pet-app 화면 상태](../08-screens/pet-app.md)의 SCR-186#decor-off. [시험 계획](../12-qa/admin.md) ⑧의 TC-653\~659. 이 밖의 문서는 읽지 않아도 돼요.
- 화면 모양: [와이어프레임](../../design/admin-wireframe.html)의 SCR-186#decor-off, SCR-201#app-removed, SCR-203#app-removed 칸이에요(회색, 지어낸 값). '앱 지워짐' 표는 지금 부품의 흐린 글(회색)이고 새 토큰은 없어요(D67).
- 이미 된 것: 설계 문서뿐이에요. 코드, DB, 서버는 바꾸지 않았어요. 표는 바뀌지 않아요: TBL-101 `marong.app_devices`의 `dropped_at`은 이미 있고 `drop_fid`가 채우며 `app_device_put`이 비워요[사실: `marong/app_store.py`]. 업데이트 메시지 대상(`app_update_targets`·`app_update_claim`)은 이미 `dropped_at`이 있는 폰을 빼서 바꾸지 않아요(SPEC-430).
- 순서: TASK-502와 TASK-503은 서로 따로 해도 돼요. TASK-504는 TASK-503 뒤, TASK-505(반영)는 모두 끝난 뒤예요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node와 Playwright(360·430px와 노트북 1280px, 낮·밤). 모델·결제·FCM은 부르지 않아요. 앱 지워진 폰은 시험 DB에 `dropped_at`을 직접 넣거나 가짜 FCM이 `gone`을 답하게 해서 만들어요. 시험 데이터는 합성 데이터만이에요('시험친구 가', `friendId` 7).
- 반영: 서버 반영을 해요(TASK-505). 마롱이가 사용자님께 여쭤 승인받은 뒤에만 해요(체크포인트 위임 밖, 2026-11-24). ⓪ 반영 전 서버의 바뀌는 파일 해시를 `main`과 비교해요(AGENTS.md '서버 반영'). 다르면 덮어쓰지 말고 멈춰 PR에 무엇이 다른지(파일 이름과 해시만) 적어요 ① 바뀌는 파일 백업과 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-admin-removed/`에 먼저 둠 ② 앱 서버 파일(`marong/app_store.py`, `marong/app_admin.py`, `marong/app_chat_static/admin.js`·`admin-items.js`, 고쳤으면 `unified.css`) ③ 진행 중 대화·통화가 없을 때 앱 서버만 재시작 ④ 확인: 동희님 Access로 `/chat/admin/items` 200과 API-263 404(운영은 꾸미기가 꺼짐)이고 `Content-Type`이 `application/problem+json`, 본문 `code`가 `not_found`(앱이 준 404, D149·TC-658), API-267 200이고 폰 줄마다 `removedAt` 칸이 있음, API-280 200이고 `app`이 null이 아님, 로그 5분 오류 없음. 값은 출력하지 않고 상태 코드·칸 있음·null 여부·개수만 적어요. DB 마이그레이션은 없어요. 켜고 끄는 설정은 두지 않아요(D163, 체크포인트 질문 6의 답 '두지 않음'): AGENTS.md는 새 기능을 drop-in의 `Environment=` 설정으로 넣으라고 하지만, 이 변경은 관리자만 보는 읽기 화면의 글과 수만 바꾸고 친구 쪽 동작은 그대로라서 관리 페이지 다시 만들기 TASK-500(D135 승인)과 같은 판단이에요. 그 규칙과 다른 선택이라는 것과 이유는 결정 기록 D163에 있어요. 되돌리기는 파일을 되돌리고 앱 서버 재시작이에요.
- 하면 안 되는 것: API-267의 형식을 `removedAt` 한 칸과 `behind`의 조건 밖으로 바꾸기(그 밖은 PR #101 그대로, 기능 변경 목록 3-8). 앱 지워진 폰 줄을 숨기거나 DB에서 지우기, `dropped_at`을 고치기. 앱 지워진 폰을 새 폰 상한(D134, API-105의 30일 안 20대)에서 빼기. 업데이트 메시지 대상(SPEC-430) 바꾸기. 아이템 화면에 꾸미기를 켜는 단추나 서버 설정 읽기 API 더하기(꺼짐은 API-263의 404로만 알아요). 응답이나 로그에 설치 ID·FID·이메일 넣기(REQ-580). 사람이 쓴 글을 `innerHTML`로 넣기. 운영 관리 화면의 스크린샷이나 화면 글을 저장소·PR·GitHub 댓글에 올리기(PR에는 합성 데이터 e2e 스크린샷만). 새 디자인 토큰. 이 설계 PR이 고친 승인 문서 줄(D148)을 다른 뜻으로 고치기.
- 겹치는 파일: `marong/app_admin.py`, `marong/app_store.py`, `marong/app_chat_static/admin.js`·`admin-items.js`, `tests/test_admin.py`, `tests/test_app_update_push.py`, `apps/android/test/admin.e2e.cjs`. 지금 열린 구현 PR 가운데 이 파일을 고치는 것은 없어요(2026-11-24, 열린 PR #121·#122·#124·#126은 기록 문서만). 대화 이어 주기(`codex/continuity`)의 파일(`tools/vertex_live/`, `marong/store.py`, `marong/agent.py`)과는 겹치지 않아요. 먼저 합친 쪽에 맞춰요.
- 사람 확인: TC-657(반영 뒤 동희님이 아이템 화면과 앱 버전 화면을 열어 봄). 운영 화면 스크린샷은 Orca 항목 댓글로만 전해요.
- 끝 조건: TASK-502\~504의 끝 조건 시험 통과, TC-653\~656·658·659 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TC-657의 서버 쪽 확인.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드가 답해요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_admin.py              # TC-652(그대로 통과), TC-654, TC-658·659의 api 쪽, TC-622~625(그대로 통과)
.venv/bin/python tests/test_app_update_push.py    # TC-653, TC-613(그대로 통과, 예시 behind에 removedAt: null)
.venv/bin/python tests/test_app_update.py && .venv/bin/python tests/test_app_update_events.py && .venv/bin/python tests/test_decor.py   # 바뀌지 않아야 함
(cd apps/android && npm ci && npm test && npm run test:browser)  # TC-655·656, TC-658·659의 화면 쪽과 TC-626·628·630(그대로 통과). Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인해요
```

## 작업

- 담당: 모두 GPT예요. 서버 반영도 GPT가 해요(D65, AGENTS.md).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 1.5일이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-502 | 아이템 화면 꾸미기 꺼짐 안내: `admin-items.js`의 `load()`가 API-263의 404를 받으면 오류 줄을 비우고 목록 자리에 '꾸미기가 꺼져 있어요' 한 줄만 그림('다시 보기' 단추 없음). 404 밖의 실패(403·500·503·네트워크·제한 시간)는 지금처럼 오류 줄과 '다시 보기'. 꾸미기가 켜진 서버의 목록·빈 목록은 그대로 | SPEC-459, SCR-186#decor-off | `marong/app_chat_static/admin-items.js`, `apps/android/test/admin.e2e.cjs`(또는 `pet-decor.e2e.cjs`), `tests/test_admin.py`(TC-658의 api 쪽) | 없음 | GPT | 0.25 | TC-656·658 통과. TC-652 그대로 통과 |
| TASK-503 | 서버: `admin_app_devices`가 `dropped_at`을 함께 읽고(거르는 조건·차례·상한은 그대로), API-267 폰 줄에 `removedAt`(ISO 8601 UTC, 없으면 `null`)을 실음. `behind`는 `removedAt`이 `null`이고 버전이 최신보다 낮을 때만 참. API-280 `app.devices`는 `removedAt`이 `null`인 폰 수. `app.behind`와 주의 항목 `app_behind`는 같은 `behind`를 써서 식을 바꾸지 않음 | SPEC-460, SPEC-438(바뀜), 명세 3.2·3.3 | API-267, API-280, `marong/app_store.py`, `marong/app_admin.py`, `tests/test_app_update_push.py`, `tests/test_admin.py` | 없음 | GPT | 0.5 | TC-653·654와 TC-659의 api 쪽 통과. TC-613·622\~625 그대로 통과. API-267 응답이 계약 0.3.0 `AdminAppDevice`(필수 칸 아홉)와 맞음 |
| TASK-504 | 화면: SCR-203 폰 줄은 `removedAt`이 있으면 '뒤처짐' 자리에 '앱 지워짐'(회색 표), 줄 차례는 뒤처진 폰 → 그 밖 → 앱 지워진 폰(무리 안은 API 차례), 펼치면 맨 위 '앱 지워짐 · {시각}'(명세 3.6) 다음에 지금 기록 줄. SCR-201 '이 사람의 폰' 줄도 '앱 지워짐'(차례는 API 그대로). 응답에 `removedAt` 칸이 없으면 `null`로 읽음 | SPEC-460, SPEC-453·456(바뀜), SCR-201#app-removed, SCR-203#app-removed | `marong/app_chat_static/admin.js`, (회색 표에 지금 클래스가 없으면) `unified.css`, `apps/android/test/admin.e2e.cjs` | TASK-503 | GPT | 0.5 | TC-655와 TC-659의 화면 쪽 통과. TC-626·628·630 그대로 통과 |
| TASK-505 | 서버 반영(GPT 인계의 '반영' ⓪\~④, ⓪은 서버 파일 해시와 `main` 비교)과 되돌리기 준비. 반영 뒤 BUG-124 기록(`docs/12-qa/BUG-124-admin-items-html.md`, PR #126이 합쳐진 뒤)에 '기능 변경 3으로 꾸미기가 꺼진 서버의 아이템 화면은 SCR-186#decor-off' 한 줄을 더함(기능 변경 목록 3-5) | SPEC-459, SPEC-460 | 앱 서버 | TASK-502\~504 | GPT | 0.25 | 사용자님 승인(마롱이가 여쭘)을 받은 뒤 반영. TC-657의 서버 쪽 확인 통과(API-263 404가 앱의 `not_found`인지 포함). 해시 비교 결과, 백업·되돌리기 경로와 확인 결과(상태 코드·칸 있음·null 여부·개수만)가 PR 설명에 있음 |

## 확인

- 모든 TASK가 SPEC이나 화면을 가리키고, SPEC-459는 TASK-502·505, SPEC-460은 TASK-503·504·505가 가져요.
- 끝 조건마다 시험이나 확인할 수 있는 결과가 있어요. 순서에 고리가 없어요.
- 열린 질문: 없어요. 체크포인트 답(D147\~D149·D160\~D163)이 모두 추천안이라 TASK는 그대로이고, 덧붙임으로 TC-658·659를 끝 조건에 더했어요.
- 확인하지 못한 것: 운영 서버에 지금 앱 지워진 폰이 몇 대 있는지(설계 중에는 운영 DB를 읽지 않았어요. '11-22에 지워진 설치'는 마롱이 항목 3의 관찰이에요). 반영 ④에서 GPT가 개수만 적어요.

## 11단계 진행

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-502 | 구현 완료 | `708f201` | TC-652·656·658 통과. 합성 화면에서 404 안내와 그 밖의 오류·재시도를 확인했어요. |
| TASK-503 | 구현 완료 | `708f201` | TC-613·622\~625·653·654·659의 API 시험 통과. 기기 재보고, 응답의 필수 필드 9개, 개요 집계를 확인했어요. |
| TASK-504 | 구현 완료 | `708f201` | TC-626·628·630·655·659의 Chromium 시험 통과. 360·430·1280px 낮·밤에서 확인했어요. |
| TASK-505 | 대기 | | 병합 및 운영 반영 지시 후 TC-657과 BUG-124 기록을 진행해요. |
