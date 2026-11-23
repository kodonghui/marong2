# 마롱이 관리 페이지 다시 만들기 작업 목록(10단계 WBS)

2026-11-23 새벽 KST 작성(Claude 마롱이 봇). 입력: 도메인 [admin.md](../01-domain/admin.md)(TERM-240·241, D132·D133), 요구사항 [admin.md](../02-prd/admin.md)(REQ-570\~585와 기능 변경 목록 1\~12·2-1\~2-12), 흐름 [FL-200](../03-user-flow/FL-200-admin-overview.md)·[FL-201](../03-user-flow/FL-201-admin-app-version.md), 기능 명세 [admin.md](../04-functional-spec/admin.md)(SPEC-450\~458), 표 [05-erd/admin.md](../05-erd/admin.md)(새 통화 함수 하나), 계약 [admin.openapi.yaml](../../api/admin.openapi.yaml) 0.1.0-draft(API-280·281), 사이트맵 [sitemap.yaml](../07-sitemap/sitemap.yaml)(SCR-169 바뀜, SCR-200\~204), 화면 상태 [08-screens/admin.md](../08-screens/admin.md), 시험 계획 [12-qa/admin.md](../12-qa/admin.md)(TC-620\~641).

상태: 2026-11-23 체크포인트 통과(D135, 근거는 [도메인 9절](../01-domain/admin.md#9-결정과-체크포인트2026-11-23)). 승인된 항목을 바꾸는 열두 곳은 '바꿈'(D136, 이 설계 PR에서 고침), 질문 2는 '더함'(D137), 질문 3은 '미룸'(D138, 2026-12-23에 마롱이가 다시 봄)이에요.
노트북 폭 기능 변경(2026-11-23, D140): 넓은 배치(08 화면 정의 1.1절, SPEC-458)를 TASK-492\~498의 끝 조건과 TASK-501에 더했어요. 같은 날 체크포인트를 통과했어요(D141. [요구사항의 기능 변경 목록 2](../02-prd/admin.md#노트북-폭-기능-변경-목록-2)는 줄마다 '바꿈' D142, REQ-585는 Should D143, SCR-201 왼쪽 회원 줄은 넣음 D144).

## GPT 인계

- 목표: 관리 페이지(`/chat/admin/`)를 화면 여섯(개요, 회원, 초대 링크, 앱 버전, 비용, 아이템)과 탭 줄로 다시 만들어요. 개요 맨 위에 손볼 일(주의 항목)을 모아요. 동희님 말(2026-11-22 23시대 KST, 오랑이 전달, D132): "야 어드민 페이지 처음부터 다시만들자고 해 아예 /corthex로".
- 시작: 이 설계 PR이 `main`에 합쳐진 뒤(체크포인트와 질문의 답은 2026-11-23, D135\~D139), `main` 머리에서 새 브랜치 `codex/admin-rebuild`. 초안 PR 하나예요. 언제 GPT를 시작할지는 동희님이 정해요(2026-11-22 동희님 "지피티 아껴 이번달은", 오랑이 전달). 앱 버전 화면(TASK-496)은 앱 업데이트 기능 변경의 TASK-480(API-267, 구현 PR #105)이 구현·반영된 뒤예요(그 설계 PR #101은 2026-11-23 `main`에 합쳐짐). 그 전에는 나머지를 먼저 해도 돼요.
- 읽을 것: [기능 명세](../04-functional-spec/admin.md)의 1절(공통 규칙 1\~8), SPEC-450\~458, 3.1\~3.7절. [계약](../../api/admin.openapi.yaml)의 API-280·281, 지금 계약 [unified.openapi.yaml](../../api/unified.openapi.yaml)의 API-235\~243(바뀌지 않음), PR #101의 `api/app-update.openapi.yaml` API-267(읽기만, 형식은 PR #101이 정함). [표 문서](../05-erd/admin.md) 3절(함수), [화면 상태](../08-screens/admin.md)(넓은 폭은 1.1절), [시험 계획](../12-qa/admin.md)의 TC-620\~641. 이 밖의 문서는 읽지 않아도 돼요.
- 화면 모양: [와이어프레임](../../design/admin-wireframe.html)은 상태와 문구를 보는 용이에요(회색, 지어낸 값). 실제 화면은 지금 `unified.css`·`chat.css`의 부품과 얼린 토큰(`design/base.tokens.json`, D67)만 써요. 새 토큰은 없어요(09단계). 관리 화면의 대지는 TASK-501에서 Claude가 그려요. 대지가 없어도 와이어프레임과 지금 부품으로 시작해도 돼요. 노트북 폭(1024px 이상)의 칸 나눔은 08 화면 정의 1.1절과 와이어프레임의 1280·1440px 칸이에요(D140).
- 이미 된 것: 설계 문서뿐이에요. 코드, 마이그레이션 파일, DB는 아무것도 바꾸지 않았어요. 통화 마이그레이션 011은 [표 문서 3절](../05-erd/admin.md#3-함수-정의task-490이-만들-마이그레이션의-내용)의 윤곽만 있고 본문은 `tools/vertex_live/call_cost.py`의 `MONTH`를 옮겨 만들어요.
- 순서: TASK-490 → TASK-491 → TASK-492 → (TASK-493, TASK-494, TASK-495, TASK-497) → TASK-496(TASK-480 뒤) → TASK-498(D137) → TASK-499 → TASK-500. 괄호 안은 서로 다른 화면이라 같이 해도 돼요. TASK-501(대지)은 Claude 일이고 아무 때나 해요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node와 Playwright(화면, 360·430px와 노트북 1280·1440px, 낮·밤. 나뉘는 폭 시험은 768·1023·1024px도, D140 2-11). 모델·결제·FCM은 부르지 않아요. 통화 비용 합은 `tools/vertex_live/test_call_cost.py`처럼 합성 행으로 만들어요. 시험 데이터는 합성 데이터만이에요('시험친구 가'·'시험친구 나').
- 반영: 서버 반영을 해요(TASK-500). ① DB와 바뀌는 파일 백업, 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-admin/`에 먼저 둠 ② 통화 마이그레이션 011(마이그레이션 관리자 역할로, 두 번 돌려도 됨) ③ 앱 서버 파일(`marong/app_admin.py`, `marong/app_chat.py`, `marong/app_chat_static/admin.*`·`admin-items.*`·`unified.css`) ④ 진행 중 통화가 없을 때 앱 서버만 재시작(통화 서버는 바뀌지 않음) ⑤ 확인: 동희님 Access로 화면 경로 일곱이 200, Access 없는 요청이 403, API-280이 200이고 `callMonth`가 null이 아님(값은 출력하지 않고 null 여부만), 로그 5분 오류 없음. 켜고 끄는 설정은 두지 않아요: 읽기 화면과 지금 API 그대로의 명령뿐이라 반영만으로 친구 쪽 동작이 바뀌지 않아요. 되돌리기는 파일을 되돌리고 앱 서버 재시작이에요(함수는 남겨도 해가 없음).
- 하면 안 되는 것: API-267, `history.json`, `app_update_events`(TBL-182)의 형식을 이 패키지에서 바꾸거나 따로 읽기(앱 칸은 API-267을 만드는 서버 함수의 결과만). 앱 버전 화면에 올리기·멈추기·다시 켜기 단추(REQ-578). 이름으로 폰과 회원을 맞추기(`friendId`만, 명세 3.5). 사람이 쓴 글을 `innerHTML`로 넣기, 인라인 스크립트, CSP 바꾸기(명세 1절 8). 앱 서버 역할에 통화 비용 표 읽기 권한 주기(합은 `call.month_budget`과 `call.friend_month_usd`로만). 통화 서버가 새 함수를 쓰게 바꾸기. 응답이나 로그에 대화 글·기억·사진·설치 ID·FID·토큰·이메일·초대 링크 주소(만들 때 한 번만 빼고) 넣기(REQ-580). 이미 적용된 마이그레이션 파일(통화 009 등) 고치기(바꿀 것은 011의 `ALTER FUNCTION`으로). 운영 관리 화면의 스크린샷이나 화면 글을 저장소·PR·GitHub 댓글에 올리기(PR에는 합성 데이터 e2e 스크린샷만, TC-637·639). 셸 명령을 화면으로 옮기기(REQ-584 미룸, D138). 새 디자인 토큰. 기능 변경 목록 1\~12로 이 설계 PR이 고친 승인 문서 줄(D136)을 다른 뜻으로 고치기.
- 겹치는 파일: `marong/app_admin.py`(PR #101의 TASK-480이 API-267을 같은 파일에 더함), `marong/app_chat.py`(경로), `marong/app_chat_static/admin.js`·`admin.html`·`admin-items.js`·`admin-items.html`, `docs/07-sitemap/sitemap.yaml`·`sitemap.md`(PR #101도 고침), `tests/pg.py`(적용 함수). 먼저 합친 쪽에 맞춰요. 통화 마이그레이션 번호 011은 이 패키지예요(2026-11-23에 `main`·PR #100·PR #101에서 가장 큰 번호가 010).
- 사람 확인: TC-639(반영 뒤 동희님이 아이폰과 노트북에서 화면 여섯을 열어 봄). 운영 화면 스크린샷은 Orca 항목 댓글로만 전해요. 실제 폰 기기 시험은 없어요(관리 화면은 웹만).
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-620\~638·640·641 통과(TC-635·636은 D137로 들어감, TC-640·641은 노트북 폭 D140 2-11. 결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TC-639의 서버 쪽 확인. TC-640·641(넓은 배치)은 REQ-585(Should) 몫이라, 넓은 배치가 늦어지면 마롱이가 동희님께 여쭤 그 부분만 새 TASK(TASK-502\~519 범위)로 떼어 내고 TASK-499·500을 이어 갈 수 있어요. 떼어 내기 전에는 끝 조건이에요.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드가 답해요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_admin.py                              # TC-620~625·631·632·634(api 쪽)·635 (새 파일, 이름은 바꿔도 됨)
.venv/bin/python tests/test_unified_auth.py && .venv/bin/python tests/test_decor.py && .venv/bin/python tests/test_scene_picture.py   # 지금 관리자 시험
.venv/bin/python tests/test_usage_limit.py                        # 한도·초대 링크 날짜(바뀌지 않아야 함)
for f in tools/vertex_live/test_*.py; do .venv/bin/python "$f" || exit 1; done   # 통화 서버 시험(test_call_cost.py, 바뀌지 않아야 함)
(cd apps/android && npm ci && npm test && npm run test:browser)  # 화면 TC-626~630·633·634(e2e 쪽)·636~638·640·641. Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인해요
```

## 작업

- 담당: TASK-501만 Claude, 나머지는 모두 GPT예요. 서버 반영도 GPT가 해요(D65, AGENTS.md).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 8일이에요(GPT 7.5일, Claude 0.5일. TASK-498 빼면 7.5일). 2026-11-23 노트북 폭(D140)으로 TASK-492·494·501이 0.25일씩 늘었어요. 전에 적은 '약 6.5일'은 표의 합(7.25일)과 달라서 같이 고쳤어요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-490 | 통화 마이그레이션 `011_admin_month.sql`: 함수 `call.month_budget(p_start, p_end)`(표 문서 3절의 SQL: `SECURITY DEFINER`, `SET search_path = pg_catalog, pg_temp`, 본문 `BEGIN ATOMIC`, 표는 모두 `call.`을 붙임. 본문은 `call_cost.MONTH`의 식 그대로이고 다른 곳은 `%s::timestamptz` 캐스트를 뺀 `limits`와 마지막 `SELECT`뿐. 예산은 `monthly_budget_usd` 없으면 150), `REVOKE … FROM PUBLIC`, `GRANT EXECUTE … TO marong`, 그리고 009의 `call.friend_month_usd`에 `ALTER FUNCTION … SET search_path = pg_catalog, pg_temp`(009 파일은 고치지 않음). `tests/pg.py`에 적용 함수(예: `apply_admin()`, 통화 010 뒤) | SPEC-457 | `marong/call/migrations/011_admin_month.sql`, `tests/pg.py` | 없음 | GPT | 0.5 | TC-631·632 통과(`pg_temp` 가로채기 시험 포함). 두 번 적용해도 오류 없음 |
| TASK-491 | 개요 API-280 `GET /chat/admin/api/overview`: 다섯 부분(통화, 그림, 앱, 사용량, 초대 링크 만료 수)을 연결 하나에서 차례로 읽고(동시 실행 없음, 연결은 2초까지 기다리고 못 받으면 503) 부분마다 짧은 트랜잭션과 `SET LOCAL statement_timeout = '1s'`로 1초 제한(명세 3.2 '읽는 차례와 시간 제한'), 실패한 부분만 null(만료 수는 그 주의 항목만 빠짐)과 로그 한 줄, 주의 항목 여섯 종류(명세 3.3의 조건·차례·`level`·`value`·`target`), 돈 값은 소수 둘째 자리 문자열, `Cache-Control: no-store`. 그림 칸은 API-266의 서버 함수, 앱 칸은 API-267의 서버 함수(없으면 null). 두 함수가 연결을 스스로 받으면 개요의 연결을 넘겨받게 나눔(응답 모양 그대로) | SPEC-451, SPEC-457 | API-280, `marong/app_admin.py`, `marong/app_chat.py`(경로) | TASK-490 | GPT | 1 | TC-622\~625 통과. API-280이 나열한 응답(200·403·500·503)마다 시험 통과 |
| TASK-492 | 관리 페이지 틀과 탭 줄: 화면 경로 여섯(명세 3.1)이 같은 틀을 주고 `admin.js`가 경로마다 그리는 함수를 나눔(한 페이지 앱 라우터 없음), 끝 `/`는 301, 모르는 하위 경로와 숫자가 아닌 `friendId`는 404, 탭 줄은 진짜 링크와 `aria-current`, 탭 줄 안에서만 가로로 밀림. 아이템 페이지(SCR-186)에 같은 탭 줄만 더함. 공통 상태(공통#forbidden·#error·#stale·#not-found, #stale은 60초 넘게 숨겨진 뒤만). 한 화면의 API는 차례로 부름(명세 1절 9). 넓은 폭 틀(08 1.1절: 1024px부터 본문 최대 1200px와 칸 격자, 1023px 이하는 한 줄 기둥 그대로, D140 2-3) | SPEC-450, SPEC-458 | SCR-169\~204·186의 틀, `marong/app_admin.py`, `marong/app_chat_static/admin.html`·`admin.js`·`admin-items.html`·`admin-items.js`·`unified.css` | TASK-491 | GPT | 1 | TC-620·621·637·638·640 통과 |
| TASK-493 | 개요 화면(SCR-169): 주의 항목 줄(08의 문구 표), 숫자 카드 다섯, 카드·줄을 누르면 `target`, 부분 실패 카드 '지금 못 불러왔어요', 올린 버전 없음. 지금 SCR-169의 초대·회원·그림 비용 칸은 새 화면으로 옮겨서 이 화면에는 없음(08 6절 대응표) | SPEC-451, SPEC-458 | SCR-169, `admin.js` | TASK-492 | GPT | 0.5 | TC-626 통과. TC-641의 SCR-169 칸(두 칸) 통과(D140 2-4) |
| TASK-494 | 회원 목록(SCR-200)과 회원 한 사람(SCR-201): API-236을 그대로 읽음, 한도 문구는 usage-limit 08과 같은 글자, 한도 바꾸기(API-243)·티켓(API-237)·로그인 끊기(확인 줄 뒤 API-241, 두 번 눌러도 한 번)·다시 로그인 링크, '이 사람의 폰'(API-267에서 `friendId`가 같은 폰만, 20대 상한 안내, 실패면 그 그룹만). 넓은 폭에서 SCR-201 왼쪽 회원 줄(같은 API-236 응답, 지금 사람에 `aria-current`, 한도 저장·티켓 넣기 뒤 그 줄도 바뀜, SPEC-458) | SPEC-452, SPEC-453, SPEC-458 | SCR-200, SCR-201, `admin.js` | TASK-492 | GPT | 1.25 | TC-627·628 통과. TC-641의 SCR-200·201 칸(SCR-201 왼쪽 회원 줄 포함) 통과(D140 2-5) |
| TASK-495 | 초대 링크(SCR-202): 새 링크 만들기(지금 칸 그대로, 질의 `?kind=…&friend=…`로 미리 고름, 틀린 질의는 무시), 칩 '열림'·'전체', 상태와 날짜 이름표(usage-limit 3.4 그대로), 빈 상태 둘 | SPEC-454, SPEC-458 | SCR-202, `admin.js` | TASK-492 | GPT | 0.5 | TC-629 통과. TC-641의 SCR-202 칸 통과(D140 2-6) |
| TASK-496 | 앱 버전(SCR-203): API-267 하나만 읽음, 맨 위 최신·멈춤 띠, 폰 줄(뒤처진 폰 먼저, 이름이 같은 다른 친구는 번호를 붙임)과 펼치기(명세 3.6의 문구, `friendId`가 같은 받아 감), 버전 기록, 조각 `#friend={friendId}`, 상한 안내(20·200·100), 모르는 값은 이름 그대로, 릴리스 노트는 `textContent`로만. 단추 없음 | SPEC-456, SPEC-458 | SCR-203, `admin.js` | TASK-492, 앱 업데이트 TASK-480 반영 | GPT | 0.75 | TC-630·634 통과(PR #101의 API-267 예시 `behind`·`empty`로). TC-641의 SCR-203 칸 통과(D140 2-7) |
| TASK-497 | 비용(SCR-204): 통화 그룹(API-280 `callMonth`, 막대와 상태 이름), 사람마다 통화(API-236 `callMonthUsd` 큰 차례, '—', 누르면 SCR-201), 그림 그룹(API-266 종류 넷과 예산 비율). 세 그룹은 따로 실패 | SPEC-457, SPEC-458 | SCR-204, `admin.js` | TASK-491, TASK-492 | GPT | 0.5 | TC-633 통과. TC-641의 SCR-204 칸 통과(D140 2-8) |
| TASK-498 | 초대 링크 거두기 API-281과 화면(확인 줄, '거두기'·'그만두기', #revoked-now, #invite-closed). UPDATE 하나(명세 SPEC-455, 앱 시계 `sessions.now()`, 안 바뀌면 404 → 거둠 200 → 409 차례), 같은 요청은 200 그대로, 쓴·기간 지난 링크는 409, 로그 `admin_invite_revoke`. 질문 2의 답 '더함'(D137) | SPEC-455, SPEC-458 | API-281, SCR-202, `marong/app_admin.py`, `admin.js` | TASK-495 | GPT | 0.5 | TC-635·636 통과. API-281이 나열한 응답(200·403·404·409·500·503)마다 시험 통과. TC-641의 SCR-202 거두기 상태 칸 통과(D140 2-9) |
| TASK-499 | 기존 문서 맞추기: 기능 변경 목록 1\~12는 이 설계 PR에서 고쳤어요(D136, 2026-11-23, 줄마다 'D136 1-x'). 구현 PR에서는 구현한 화면·상태 이름이 그 줄과 다를 때만 그 줄을 맞춰요(새 설계를 쓰지 않음) | SPEC-450\~457, 기능 변경 목록 | `docs/01-domain/unified.md`, `docs/02-prd/unified.md`, `docs/03-user-flow/FL-169`\~`FL-171`·`FL-177`·`FL-179`·`FL-192`, `docs/04-functional-spec/unified.md`·`usage-limit.md`·`pet-app.md`, `docs/08-screens/unified.md`·`usage-limit.md`·`pet-app.md`, `docs/07-sitemap/sitemap.*` | TASK-493\~497 | GPT | 0.5 | 맞춘 줄이 있으면 PR 설명에 있음. `git grep -n "SCR-169"`로 남은 옛 설명이 D136과 맞음 |
| TASK-500 | 서버 반영(GPT 인계의 '반영' ①\~⑤)과 되돌리기 준비 | SPEC-450\~457 | 운영 DB(통화 함수 하나), 앱 서버 | TASK-499 | GPT | 0.5 | TC-639의 서버 쪽 확인 통과. 백업·되돌리기 경로와 확인 결과(null 여부·상태 코드만)가 PR 설명에 있음 |
| TASK-501 | 관리 화면 대지: 공통 캔버스에 SCR-169#attention, SCR-201#normal, SCR-203#device-open, SCR-204#normal을 360px와 노트북 1280px(08 1.1절의 넓은 배치) 낮·밤으로, 지금 `unified.css` 부품과 얼린 토큰만으로 그림(새 토큰 없음, D140 2-10) | SCR-169, SCR-201, SCR-203, SCR-204 | 공통 목업 캔버스(claude.ai) | 없음 | Claude | 0.5 | 동희님이 방향을 봄. 새 토큰이 없음(`tokens.py` 색 검사) |

## 확인

- 모든 TASK가 SPEC이나 화면을 하나 이상 가리키고, SPEC-450\~458이 모두 TASK를 가져요(450: 492·499·500, 451: 491·493, 452·453: 494, 454: 495, 455: 498, 456: 496, 457: 490·491·497, 458: 492\~498).
- 끝 조건마다 시험이나 확인할 수 있는 결과가 있어요.
- 순서가 TASK ID와 같고 고리가 없어요(TASK-496은 앱 업데이트의 TASK-480에도 기대요).
- 열린 질문: 없어요. 2026-11-23 체크포인트에서 답했어요(D135\~D139). REQ-584(셸 명령을 화면으로)는 2026-12-23에 마롱이가 다시 보고, 그때 넣기로 하면 새 TASK를 이 범위(TASK-502\~519)에 더해요. 노트북 폭 기능 변경(D140)의 질문도 2026-11-23에 답했어요(D141\~D144).
- 확인하지 못한 것: 운영 서버의 `call.settings`에 `monthly_budget_usd` 행이 있는지(없으면 150), 지금 관리 화면을 동희님이 쓰는 폭(D140으로 노트북에서도 보신다는 것은 알게 됨. 화면 크기와 확대 비율은 모름). 반영 ⑤에서 GPT가 null 여부와 상태 코드만 확인해요.

## 11단계 진행

아직 없어요.
