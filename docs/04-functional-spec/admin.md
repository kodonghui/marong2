# 마롱이 관리 페이지 다시 만들기: 기능 명세

상태: 2026-11-23 체크포인트 통과(D135, 근거는 [도메인 9절](../01-domain/admin.md#9-결정과-체크포인트2026-11-23)). 이 문서의 행은 모두 active예요(SPEC-455는 D137로 더함). SPEC-458(넓은 폭 배치)은 2026-11-23 노트북 폭 기능 변경(D140)으로 더했고 같은 날 체크포인트를 통과해 active예요(D141, SCR-201 왼쪽 회원 줄은 D144). 구현·서버 반영은 GPT가 해요(D60). 처음 초안은 같은 날 새벽 KST, Claude 마롱이 봇.
기능 변경 3(2026-11-24, D145·D146, 체크포인트 전): SPEC-459(꾸미기 꺼짐 안내)와 SPEC-460(앱 지워진 폰)을 proposed로 더하고, SPEC-453·456과 3.2·3.3·3.5·3.6에서 바뀌는 글에 '기능 변경 3-x 제안'을 붙여 고쳤어요([기능 변경 목록 3](../02-prd/admin.md#꾸미기-꺼짐-안내와-앱-지워진-폰-기능-변경-목록-3)). 답을 받기 전까지 그 글은 승인된 글 그대로예요.
입력: [요구사항](../02-prd/admin.md) REQ-570\~587과 기능 변경 목록 1\~12·2-1\~2-12·3-1\~3-14, [사용자 흐름](../03-user-flow/) FL-200·201, [도메인](../01-domain/admin.md)의 TERM-240·241, 통합 앱 명세 [unified.md](unified.md)의 1절·SPEC-370·380·395, 사람별 사용 한도 [usage-limit.md](usage-limit.md)의 SPEC-398과 3.4·3.5, 반려동물 앱 안 [pet-app.md](pet-app.md)의 SPEC-417·427, 앱 업데이트 기능 변경(PR #101 `3de1c79`)의 SPEC-438과 8.6(API-267). 코드 `marong/app_admin.py`, `marong/app_session.py`, `tools/vertex_live/call_cost.py`, `marong/call/migrations/009_usage_limit.sql`(`main` `7b0c6e1`).
뒤 단계: 05는 새 통화 함수 하나(`marong/call/migrations/011_admin_month.sql`, 표 없음), 06은 `api/admin.openapi.yaml`의 API-280·281, 08은 SCR-169(바뀜)·200\~204·186과 넓은 폭 1.1절, 10은 TASK-490\~501, 12는 TC-620\~641이 이 SPEC 번호를 따라가요. 기능 변경 3은 06 API-267 `removedAt`(app-update 계약 0.3.0-draft)과 API-280 칸 설명, 08 SCR-186#decor-off·SCR-201#app-removed·SCR-203#app-removed, 10 TASK-502\~505, 12 TC-653\~657이 따라가요(05는 바뀜 없음: TBL-101 `dropped_at`이 이미 있음).
표시: [사실] 코드·기록에서 확인, [새 제안] Claude가 새로 정한 숫자·문구·이름(D133), [추정] 근거 있는 짐작, [확인 안 함] 아직 보지 않은 것.
ID 번호: SPEC-450\~460(459·460은 기능 변경 3 제안).

## 1. 공통 규칙

통합 앱 명세 [1절](unified.md#1-공통-규칙)을 그대로 따라요(응답 모양, 오류 코드, 로그, 시각, 비동기). 더하는 것만 적어요.

1. 관리자 확인: `/chat/admin/` 아래의 모든 화면 경로와 API는 지금의 `require_admin`을 먼저 지나요. Cloudflare Access JWT(`Cf-Access-Jwt-Assertion`)를 서버가 다시 확인하고, 그 이메일의 SHA-256이 `MARONG_ADMIN_EMAIL_SHA256`과 같아야 해요(`hmac.compare_digest`). 아니면 403 `not_allowed`예요(401을 쓰지 않음, API-267과 같음). 로그인 쿠키는 보지 않아요[사실].
2. 쓰기(POST·PUT)는 지금처럼 같은 주소에서 온 요청만 받아요(`Origin`, 다르면 403 `cross_site`)[사실]. 읽기(GET)는 `Cache-Control: no-store`예요.
3. 새 API는 화면에 필요한 숫자만 줘요. 대화 글, 기억, 사진, 설치 ID, FCM 설치 ID, 로그인 토큰, 초대 링크 토큰과 주소(만든 때 한 번만 주는 API-235는 그대로), 이메일을 싣지 않아요(REQ-580).
4. 돈 값은 API에서 소수 둘째 자리까지의 문자열이에요(예: `"121.40"`, usage-limit 1절 4와 같음). 비율은 0 이상의 정수 퍼센트예요(내림). API-266은 지금 모양(숫자) 그대로 읽어요.
5. 시각: 통화 비용의 '이번 달'은 UTC 달(통화 비용 표 기준), 그림 비용의 '이번 달'은 한국 시각 달력 달(API-266)이에요[사실]. 화면은 두 달 이름을 따로 적어요. 오늘 사용량의 하루는 한국 시각 04:00에 바뀌어요[사실].
6. 로그: 새로 남기는 줄은 `admin_overview part=<call|images|app|usage|invites> result=failed`(한 부분을 못 읽었을 때)와 `admin_invite_revoke invite=<id> result=<revoked|closed|missing>`뿐이에요. 이름, 메모, 금액은 남기지 않아요[새 제안].
7. 모든 화면은 폭 360px와 430px에서 페이지가 가로로 넘치지 않아요(REQ-581). 탭 줄이 폭보다 길면 탭 줄 안에서만 옆으로 밀려요.
8. 사람이 쓴 글(릴리스 노트, 친구 이름, 마롱이 이름, 초대 메모)은 `textContent`로만 화면에 넣어요. `innerHTML`을 쓰지 않고, 페이지의 CSP `script-src 'self'`(지금 `marong/app_chat.py`의 응답 헤더)[사실]를 그대로 둬요. 인라인 스크립트와 `style` 속성 대신 `admin.js`와 `unified.css`만 써요(PR #101 API-267 계약 0.2.0 설명 9와 같음)[새 제안].
9. 한 화면이 API를 여럿 부르면 동시에 부르지 않고 차례로 불러요(앞 응답을 받은 뒤 다음, 앞 요청이 실패해도 다음은 불러요). 앱 서버의 DB 연결 풀은 4개(`max_size=4`, `marong/store.py` 146줄)이고 친구 대화·기억과 같이 써요[사실]. 그래서 관리 페이지 한 탭은 한 번에 DB 연결을 하나만 써요(API-280 안에서도 3.2의 '읽는 차례와 시간 제한')[새 제안].

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-450 | 관리 페이지 틀과 탭 줄 | REQ-570, REQ-571, REQ-581, REQ-438(D136 1-2로 바뀜), FL-200 | Access를 지난 관리자(1절 1) | 서버가 3.1의 화면 경로 여섯(`/chat/admin/`, `/members`, `/members/{friendId}`, `/invites`, `/app`, `/costs`)에 같은 관리 페이지 틀(`unified_page("admin")`)을 주고, 화면 스크립트가 경로를 읽어 그 화면을 그려요. 아이템(`/chat/admin/items`, SCR-186)은 지금 페이지(`admin-items`) 그대로이고 같은 탭 줄을 위에 둬요. 탭 줄은 3.1의 여섯 칸이고 진짜 링크(`<a href>`)예요. 지금 화면의 탭에 `aria-current="page"`. 탭을 누르면 그 경로로 이동하고(새로 고침해도 같은 화면), 브라우저의 뒤로 가기가 앞 화면으로 가요 | Access 없음·관리자 아님 → 모든 화면 경로 403(지금 `page()`와 같음)<br>3.1에 없는 하위 경로(예: `/chat/admin/foo`) → 404<br>`/members/{friendId}`의 `friendId`가 1\~2^63-1 정수가 아님 → 404<br>화면 스크립트를 못 받음 → 브라우저 기본 오류(서버는 그대로) | Given 관리자, When 여섯 경로와 `/chat/admin/items`를 각각 엶, Then 200 HTML이고 탭 줄이 있고 지금 탭만 `aria-current`<br>Given Access 증명이 없는 요청, When 일곱 경로, Then 모두 403<br>Given `/chat/admin/foo`, `/chat/admin/members/abc`, Then 404<br>Given 360px 화면, Then 페이지 가로 스크롤 없음(탭 줄 안에서만 밀림) | active |
| SPEC-451 | 개요와 주의 항목(API-280) | REQ-572, REQ-573, REQ-451, FL-200 | 관리자 | `GET /chat/admin/api/overview` → 200(3.2의 모양): 회원 수와 프로필 없는 친구 수, 오늘 사용 합(글 답·통화 초·그림·사용 단위, 프로필이 있는 친구의 오늘 행 합), 이번 달 통화(SPEC-457의 함수로 합과 월 예산, 비율과 상태), 이번 달 그림 비용(API-266과 같은 서버 함수의 결과에서 합과 예산이 있는 종류의 비율), 앱 버전 요약(API-267과 같은 서버 함수의 결과에서 최신 릴리스·멈춤·폰 수·뒤처진 폰 수), 주의 항목 목록(3.3의 규칙, 정한 차례). 다섯 부분(통화, 그림, 앱, 사용량, 초대 링크 만료 수)은 따로 읽고 부분마다 1초 제한이에요. 부분을 동시에 읽지 않고 연결 하나에서 차례로 읽어요(3.2의 '읽는 차례와 시간 제한'). 초대 링크 만료 수는 응답 칸이 없고 주의 항목 `invite_expiring`에만 써요. 회원 수와 프로필 없는 친구 수(`unlinked_friend`)는 첫 쿼리라 따로 두지 않아요(못 읽으면 503). 화면(SCR-169)은 주의 항목을 맨 위에 한 줄씩, 그 아래 숫자 카드 다섯을 그리고, 줄과 카드를 누르면 3.3의 `target` 화면으로 가요 | 관리자 아님 → 403 `not_allowed`<br>DB에 닿지 않음(회원 수를 못 읽음), 연결을 2초 안에 받지 못함(풀이 다 쓰임) → 503 `db_unavailable`<br>통화·그림·앱·사용량 가운데 한 부분이 실패·1초 넘음 → 그 부분만 `null`, 로그 `admin_overview part=… result=failed`, 응답은 200이고 주의 항목은 읽은 부분으로만 계산.<br>초대 링크 만료 수가 실패·1초 넘음 → `invite_expiring` 줄만 빠지고 로그 `part=invites`, 응답은 200. 화면은 그 카드에 '지금 못 불러왔어요'<br>API-267의 서버 함수가 아직 구현·반영되지 않음(PR #101의 TASK-480 전) → `app`이 `null`(화면은 그 카드에 '지금 못 불러왔어요') | Given 시험 자료(회원 3, 프로필 없는 친구 1, 오늘 단위 합 420, 통화 합 121.40·예산 150, 캐릭터 그림 17/20달러, 최신 0.3.3을 30시간 전에 올림, 0.3.2에 머문 폰 1, 23시간 뒤 만료되는 열린 링크 1), When API-280, Then 숫자가 그대로이고 `attention`이 `call_budget`(`value` 80), `image_budget`(85), `app_behind`(1), `invite_expiring`(1), `unlinked_friend`(1) 다섯 줄이고 3.3의 차례<br>Given 손볼 일 없음, Then `attention` 빈 목록, 화면 '지금 손볼 일 없어요'<br>Given 통화 함수가 2초 걸림, Then 200이고 `callMonth` null, 다른 부분은 값이 있음<br>Given 다섯 부분이 모두 2초 걸림, Then 8초 안에 200이고 네 칸 null과 `invite_expiring` 없음, 개요가 한 번에 쓴 DB 연결은 하나<br>Given 응답 전체, Then 설치 ID·FID·이메일·토큰이 없고 주의 항목에 친구 이름이 없음(개수만) | active |
| SPEC-452 | 회원 목록(SCR-200) | REQ-574, FL-200, FL-177 | 관리자 | 화면이 API-236을 그대로 읽어요(바뀌지 않음). 맨 위 줄에 기본 한도(`defaults`, usage-limit SCR-169#normal의 '기본 한도 · …' 문구 그대로). 가입한 사람(`members`)은 한 사람 한 줄: 이름, 마롱이 이름, '한도 · 무제한/기본/직접(…)'(usage-limit 3.4·3.5 문구 그대로), 오늘 사용 단위, 티켓, 마지막 사용(짧은 날짜). 줄을 누르면 `/chat/admin/members/{friendId}`. 프로필이 없는 기존 친구(`unlinked`)는 아래 그룹 '아직 잇지 않은 기존 친구'에 이름과 '잇기 링크 만들기'(→ `/chat/admin/invites?kind=link&friend={friendId}`) | API-236 실패 → 공통 오류 줄과 '다시 해 볼게요'<br>`members`·`unlinked` 둘 다 빈 목록 → '아직 가입한 사람이 없어요'(SCR-169#members-empty 문구) | Given 무제한·기본·직접 회원 셋과 프로필 없는 친구 하나, Then 줄 셋과 아래 그룹 한 줄, 한도 문구가 usage-limit 08과 한 글자도 다르지 않음<br>Given 줄 누름, Then 그 사람의 SCR-201 경로 | active |
| SPEC-453 | 회원 한 사람(SCR-201) | REQ-575, REQ-582, REQ-487, REQ-482, FL-179, FL-177, FL-171 | 관리자, 경로의 `friendId` | 화면이 API-236을 읽어 그 `friendId`의 줄을 골라 그려요(새 API 없음): 이름·마롱이 이름, 계정 한도와 유효 한도, 오늘 사용량(글 답·통화 분·그림·단위), 티켓, 로그인 수와 마지막 사용, 이번 달 통화 비용(달러). 명령은 지금 API 그대로예요: 한도 바꾸기(API-243, usage-limit 3.5와 SCR-169#limits-* 문구), 티켓 넣기(API-237, 1\~1000), 로그인 끊기(확인 줄 뒤 API-241), '다시 로그인 링크 만들기'(→ `/chat/admin/invites?kind=relogin&friend={friendId}`). 아래 '이 사람의 폰'은 API-267을 따로 불러 `devices[].friendId`가 이 `friendId`인 폰 줄(버전, 뒤처짐, 마지막 보고, 3.5. 기능 변경 3-13 제안: 앱 지워진 폰은 뒤처짐 자리에 '앱 지워짐', SPEC-460)을 보이고, '앱 버전에서 보기'(→ `/chat/admin/app#friend={friendId}`, 조각이라 서버로 가지 않음)를 둬요 | `friendId`가 `members`에 없음(프로필 없음 포함) → '그 사람을 찾을 수 없어요'와 회원 목록 링크(SCR-201#missing)<br>API-243·237의 400·404·403·503 → usage-limit·unified 08의 그 상태 문구 그대로<br>로그인 끊기에서 '그만두기' → 아무 요청도 가지 않음<br>로그인 끊기를 두 번 누름(확인 뒤 응답 전) → 단추를 막아 요청 한 번. 이미 끊긴 사람(`sessions` 0)에게 다시 → 204(API-241은 같은 결과)<br>API-267 실패·없음 → '이 사람의 폰'만 '지금 못 불러왔어요'(나머지는 그대로)<br>그 `friendId`의 폰이 20줄(API-267의 친구마다 상한) → 줄 아래 '최근 보고한 20대만 보여요'<br>`devices`가 200줄(모두 상한)이면 이 사람의 폰이 빠졌을 수 있어서, 폰이 0대여도 '90일 안에 보고한 폰이 없어요' 대신 '폰이 많아 일부만 보여요'와 '앱 버전에서 보기' | Given 직접(하루 200) 회원, When 한도를 무제한으로 저장, Then API-243 200이고 화면 '한도 · 무제한'과 띠 '한도를 바꿨어요'<br>Given 티켓 0, When 5 넣기, Then API-237 200, '티켓 5장'<br>Given 로그인 끊기 → '그만두기', Then API-241 요청 0번. '끊기', Then 1번이고 로그인 수 0<br>Given 없는 `friendId` 999, Then #missing<br>Given API-267에 `friendId` 7의 폰 2대(0.3.2 뒤처짐, 0.3.3), Then 7의 화면에 폰 줄 둘. Given 이름이 같은 다른 회원 9의 폰 1대, Then 7의 화면에 그 폰이 섞이지 않음. Given 7의 폰 20줄, Then 줄 20개와 '최근 보고한 20대만 보여요'. Given `devices` 200줄에 7의 폰 0대, Then '폰이 많아 일부만 보여요' | active |
| SPEC-454 | 초대 링크(SCR-202) | REQ-576, REQ-430, REQ-431, REQ-433, FL-169, FL-170, FL-171 | 관리자 | 화면이 API-240(목록)과 API-236(`link`·`relogin`에서 고를 사람)을 읽어요. 위에 '새 링크 만들기'(지금 SCR-169#creating·#created 그대로: 종류 칩, 사람 고르기, 메모 40자, 만들기, 주소 한 번만, 복사). 질의 `?kind=link|relogin&friend={id}`가 있으면 칸이 열린 채 그 종류와 사람이 골라져 있어요. 목록은 칩 '열림'(기본)·'전체'로 거르고, 줄마다 '종류 · 메모', 상태, 날짜 이름표(usage-limit 3.4: '만든 때 · 만료(며칠 남음)', '만든 때 · 쓴 때', '만든 때 · 만료됨', '만든 때 · 거둔 때'). 거두기(SPEC-455)가 승인되면 열린 줄에 '거두기' | API-235의 400·404·403 → 지금 SCR-169#invite-invalid·#member-missing·#error 문구<br>질의의 `friend`가 목록에 없음·`kind`가 둘 밖 → 질의를 무시하고 칸을 닫은 채 엶<br>열린 링크 0개(칩 '열림') → '열린 초대 링크가 없어요'. 전체 0개 → '만든 초대 링크가 없어요'(SCR-169#invites-empty)<br>목록은 API-240대로 최근 100개까지 | Given 넷(열림·씀·기간 지남·거둠), Then 칩 '열림'에 한 줄, '전체'에 넷이고 이름표가 usage-limit 08과 같음<br>Given `?kind=relogin&friend=2`, Then 칸이 열리고 종류 relogin, 사람 2가 골라짐<br>Given `?kind=join&friend=2`, Then 칸이 닫힘 | active |
| SPEC-455 | 초대 링크 거두기(API-281) | REQ-583, FL-200 | 관리자, 같은 주소의 요청. 질문 2의 답 '더함'(D137, 2026-11-23) | `POST /chat/admin/api/invites/{inviteId}/revoke` → UPDATE 하나: `revoked_at = $2` WHERE `id = $1 AND used_at IS NULL AND revoked_at IS NULL AND expires_at > $2`. `$2`는 앱 시계 `sessions.now()`예요(목록 API-240과 가입의 `_check_invite`가 쓰는 시계와 같음, DB의 `now()`를 쓰지 않음)[사실: `marong/app_admin.py`]. 줄이 바뀌지 않으면 그 id를 다시 읽어 이 차례로 정해요: 없음 → 404, `revoked_at`이 있음 → 200 그대로(기간이 그 뒤에 지났어도), 그 밖(쓴 링크·기간 지남) → 409. 줄이 바뀌면 200 `{invite}`(API-240 줄 모양, `state: revoked`, `revokedAt`). 화면은 확인 줄 '이 링크를 거둬요. 받은 사람이 열어도 쓸 수 없어요'와 '거두기'·'그만두기' 뒤에 불러요. 가입·잇기·다시 로그인은 지금도 `revoked_at`을 보고 거절해요(`_check_invite`)[사실] | 관리자 아님 → 403 `not_allowed`. 다른 Origin → 403 `cross_site`<br>`inviteId`가 정수가 아님·없음 → 404 `not_found`<br>이미 거둔 링크 → 200이고 그대로(같은 결과, `revokedAt`이 바뀌지 않음)<br>쓴 링크·기간 지난 링크 → 409 `invite_closed`, 바뀌지 않음<br>같은 링크로 가입이 동시에 → 가입은 그 줄을 `FOR UPDATE`로 잡아서 둘 가운데 먼저 끝난 쪽만 이겨요. 가입이 먼저면 거두기가 409, 거두기가 먼저면 가입이 지금의 '거둔 링크' 오류<br>DB에 닿지 않음 → 503 `db_unavailable` | Given 열린 링크, When 거두기, Then 200 `state: revoked`이고 그 토큰으로 가입하면 지금의 거둔 링크 오류<br>Given 같은 요청 두 번, Then 둘 다 200이고 `revokedAt`이 처음 값<br>Given 쓴 링크·기간 지난 링크, Then 409 `invite_closed`<br>Given 다른 Origin, Then 403 `cross_site`이고 행이 그대로<br>Given 가입과 거두기를 동시에(시험 잠금), Then 하나만 성공 | active(D137) |
| SPEC-456 | 앱 버전(SCR-203, API-267 읽기) | REQ-577, REQ-578, REQ-573, FL-201 | 관리자. PR #101의 API-267이 반영됨 | 화면이 API-267 하나만 불러요(쓰기 없음). 맨 위: 최신 릴리스(버전 이름, 올린 때)와 `paused`면 띠 '업데이트 멈춤 중 · 폰이 새로 받지 않아요'. '폰' 그룹: `devices` 한 대 한 줄(친구 이름과 폰 순번 '시험친구 가 · 폰 1', 앱 버전, 뒤처지면 '뒤처짐' 표(기능 변경 3-12 제안: 앱 지워진 폰은 그 자리에 '앱 지워짐' 회색 표, SPEC-460), 마지막 보고 짧은 날짜, 알림 권한이 꺼지면 '알림 꺼짐'). `friendId`가 다른데 이름이 같은 친구가 있으면 이름 뒤에 번호를 붙여요('시험친구 가(7) · 폰 1'). 줄을 누르면 펼쳐져 `events`를 새것부터 3.6의 문구로 한 줄씩, 그리고 `friendId`가 같은 `fetches` 칸의 줄('받아 감 0.3.3(11) · 시각')을 함께. 뒤처진 폰이 먼저, 그다음 API 차례(기능 변경 3-12 제안: 뒤처진 폰 → 그 밖 → 앱 지워진 폰, 무리 안은 API 차례). '버전 기록' 그룹: `releases`를 새것부터 한 줄씩(올림: 버전·올린 때·릴리스 노트, 기록에서 채운 줄은 '기록에서 채움' 표, 멈춤·다시 켬은 그 때만). 주소 조각 `#friend={friendId}`가 있으면 그 `friendId`의 첫 폰 줄로 스크롤하고 펼쳐요(API-236을 읽지 않음, REQ-578). 상한(친구마다 20대, 모두 200대, 받아 감 100명)에 닿으면 3.5의 안내 글을 보여요. 릴리스 노트는 `textContent`로만 넣어요(1절 8) | 관리자 아님 → 403(화면 공통)<br>API-267 503·실패 → 오류 줄과 '다시 해 볼게요'<br>`latest` null이고 `releases` 빈 목록 → '아직 올린 버전이 없어요'<br>`devices` 빈 목록 → '90일 안에 보고한 폰이 없어요'<br>모르는 `kind`·`state` 값(API-267이 늘어남) → 줄을 숨기지 않고 값 이름 그대로 한 줄(화면이 깨지지 않음)<br>릴리스 노트가 300자 → 줄바꿈해 모두 보임<br>릴리스 노트에 `<b>`나 `<script>` 같은 글이 있음 → 글자 그대로 보이고 실행되지 않음<br>조각의 `friendId`가 숫자가 아니거나 없는 번호 → 맨 위 그대로 | Given API-267 예시 `behind`(PR #101), Then 맨 위 0.3.3, 폰 줄 '시험친구 가 · 폰 1 · 0.3.2 · 뒤처짐'(예시 이름은 D139로 합성), 펼치면 '조용할 때 기다림 0.3.3(11)', '받음', '보냄 1번째', '받아 감' 순서, 버전 기록 두 줄 가운데 0.3.2에 '기록에서 채움'<br>Given `paused: true`, Then 띠가 보이고 단추는 없음<br>Given 모르는 상태 `foo`, Then 'foo' 한 줄<br>Given 화면 전체, Then 설치 ID·FID·APK 파일 이름이 없음(API-267에 없음)<br>Given 릴리스 노트 `<img src=x onerror=alert(1)>`, Then 그 글자가 그대로 한 줄이고 요청·실행 없음<br>Given `#friend=7`, Then 7의 첫 폰 줄이 펼쳐짐<br>Given `devices` 200줄, Then '폰이 많아 200대까지만 보여요' | active |
| SPEC-457 | 비용(SCR-204)과 통화 월 예산 함수 | REQ-579, REQ-572, REQ-520, REQ-451, FL-200 | 관리자. 통화 마이그레이션 011이 적용됨 | 새 함수 `call.month_budget(p_start, p_end)`(3.4)가 이번 UTC 달의 통화 비용 합과 월 예산(`call.settings`의 `monthly_budget_usd`, 없으면 150)을 줘요. API-280의 `callMonth`가 이것을 써요. 비용 화면은 세 그룹이에요. ① '통화 · 2026년 11월(UTC)': 합 / 예산과 비율 막대(80% 이상 `warn`, 100% 이상 `danger` 색), 상태 이름(정상·80% 넘음·다 씀·120% 넘음) ② '사람마다 통화': API-236의 `callMonthUsd`를 큰 차례로, 줄을 누르면 SCR-201 ③ '그림 · 2026년 11월': API-266의 종류별 넷(일기·화두·반응·캐릭터)과, 예산이 있는 종류의 '쓴 값 / 한도(비율)' | 함수 실패·1초 넘음 → ①만 '지금 못 불러왔어요'(API-280 `callMonth` null)<br>월 예산이 0 이하 → 생기지 않아요: `call.settings`의 `monthly_budget_usd`는 DB 제약으로 0보다 크고 10000 이하예요[사실: `marong/call/schema.sql`의 settings CHECK]. 그래도 0 이하를 읽으면 실패와 같게 `callMonth` null과 로그<br>API-236의 `callMonthUsd`가 null → ②의 그 줄 '—'(SCR-169#call-month-unknown 문구)<br>API-266 실패 → ③만 오류 줄 | Given TC-498과 같은 합성 통화 자료, When 함수, Then 합이 같은 자료의 `call_cost.MonthlyCost.report(at, fresh=True)` `total`과 같음(소수 넷째 자리까지, `fresh=True`로 30초 캐시를 건너뜀)<br>Given `monthly_budget_usd` 행 없음, Then 예산 150<br>Given 합 121.40, Then API-280 `percent` 80, `state` `warn`, 화면 '121.40 / 150.00 · 80%'<br>Given `marong` 역할, Then 함수 실행은 되고 `call.live_usage` 읽기는 권한 오류(지금 그대로) | active |
| SPEC-458 | 넓은 폭 배치(노트북) | REQ-585, REQ-581, REQ-571, D140 | 관리자, 화면 폭 1024px 이상(CSS px) | 관리 페이지 틀(SPEC-450)이 CSS 미디어 질의 하나(`min-width: 1024px`)로 넓은 배치가 돼요: 본문 최대 1200px 가운데, 좌우 여백 32px 이상(본문 폭은 스크롤 막대를 뺀 보이는 폭에서 64px를 뺀 값과 1200px 중 작은 값), 칸 사이 24px(얼린 토큰 `space.xl`·`space.lg`)[새 제안]. 화면마다 칸은 08 화면 정의 1.1절의 표예요(SCR-169 같은 폭 두 칸, SCR-200·201 왼쪽 360px와 오른쪽, SCR-202 왼쪽 360px와 오른쪽, SCR-203 맨 위와 3:2 두 칸, SCR-204 같은 폭 세 칸, SCR-186 한 칸 표). HTML 차례는 폰과 같고 CSS 격자(grid)로 자리만 정해요(폭마다 HTML을 따로 만들거나 `order`로 차례를 바꾸지 않음). 넓은 폭에서만 SCR-201이 왼쪽에 회원 줄을 그려요: 이 화면이 이미 읽은 API-236 응답의 `members`를 SCR-200과 같은 줄 글로, 지금 `friendId`의 줄에 `aria-current="page"`, 줄은 `/chat/admin/members/{friendId}` 링크(페이지를 새로 받음, 3.1). 한도 저장(API-243 200)과 티켓 넣기(API-237 200) 뒤에는 오른쪽과 함께 왼쪽 그 사람 줄의 한도·티켓 글도 같은 응답 값으로 바꿔요. 화면 폭이 바뀌면(창 크기 조절, 태블릿 돌리기) 다시 읽지 않고 CSS만 바뀌어서 열린 칸과 적던 글이 그대로예요 | 1023px 이하 → 지금 한 줄 기둥 그대로(넓은 배치 규칙이 닿지 않음)<br>SCR-201에서 API-236 실패 → 왼쪽 목록도 없이 공통#error(지금 그대로)<br>SCR-201의 `friendId`가 `members`에 없음 → 왼쪽 목록은 보이고 골라진 줄 없음, 오른쪽 #missing<br>회원이 많아 왼쪽 목록이 오른쪽보다 길어짐 → 페이지가 아래로 길어질 뿐 칸이 겹치지 않음(왼쪽 칸만 따로 스크롤하지 않음)<br>이름 12자·메모 40자·릴리스 노트 300자 → 칸 안에서 줄바꿈하고 칸 밖으로 나가지 않음 | Given 1280px와 1440px, When 화면 일곱의 가장 긴 상태를 엶, Then 08 1.1절의 칸 배치이고 `document.documentElement.scrollWidth`가 화면 폭 이하, 칸끼리 겹치지 않음<br>Given 1023px, Then 한 줄 기둥(본문 720px 이하). Given 1024px, Then 넓은 배치<br>Given 360·430px, Then TC-637과 같은 결과(배치가 바뀌지 않음)<br>Given 1280px의 SCR-201(`friendId` 7), Then 왼쪽 회원 줄 수가 API-236 `members`와 같고 7의 줄만 `aria-current="page"`, 요청은 API-236 한 번과 API-267 한 번뿐(지금과 같음)<br>Given 1280px에서 한도를 저장, Then 오른쪽 '한도 · …'와 왼쪽 그 사람 줄이 같은 값<br>Given 1280px, When Tab 키로 끝까지 옮김, Then 차례가 360px와 같음(SCR-201만 탭 줄 바로 뒤에 왼쪽 회원 줄이 더해짐) | active(D141, D144) |
| SPEC-459 | 꾸미기 꺼짐 안내(SCR-186#decor-off) | REQ-586, FL-192, pet-app REQ-523 | 관리자, 꾸미기가 꺼진 서버(`MARONG_DECOR`가 `1`이 아님, 지금 운영) | 아이템 화면(`/chat/admin/items`)은 지금처럼 200 HTML이고 위에 탭 줄이 있어요(BUG-124 고침, TC-652). 화면 스크립트(`admin-items.js`)가 API-263을 불러 404를 받으면 오류 줄 대신 안내 '꾸미기가 꺼져 있어요' 한 줄만 그려요(SCR-186#decor-off). 이때 오류 줄('아이템을 불러오지 못했어요'와 추적 id), '다시 보기' 단추, 아이템 목록과 올리기·내리기 단추가 없어요. 새 API와 새 설정 읽기는 없어요: API-263은 카탈로그가 없을 때 관리자 확인보다 먼저 404 `not_found`를 주고, 카탈로그는 꾸미기가 켜진 서버에서만 읽어요[사실: `marong/app_admin.py` `decor_items`, `marong/app_decor.py` `require_catalog`]. 꾸미기를 켜는 단추는 두지 않아요(서버 설정, pet-app REQ-523) | 꾸미기가 켜진 서버 → 지금 그대로(#normal·#empty·#error)<br>API-263이 404 말고 실패(403·500·503·네트워크·10초 넘음) → 지금의 #error(오류 줄과 '다시 보기')<br>관리자 아님 → 화면 경로가 403(지금 그대로, API-263까지 가지 않음)<br>서버에서 꾸미기를 켠 뒤 → 화면을 다시 열면 지금의 목록(화면은 꺼짐을 기억하지 않음)<br>API-264·265는 꺼진 서버에서 부를 단추가 없어 불리지 않아요(불리면 지금처럼 404) | Given 카탈로그가 없는 서버(`MARONG_DECOR=0`), When 관리자가 `/chat/admin/items`를 엶, Then 200 HTML, 탭 '아이템'에 `aria-current="page"`, 본문에 '꾸미기가 꺼져 있어요' 한 줄, '아이템을 불러오지 못했어요'와 '다시 보기'가 없고 API-263 요청은 한 번<br>Given 꾸미기가 켜진 서버에서 API-263이 500(시험 가짜), Then 지금의 #error와 '다시 보기'<br>Given 꾸미기가 켜진 서버, Then 아이템 목록이 지금과 같음<br>Given 360px, Then 페이지 가로 넘침 없음 | proposed(D145, 기능 변경 3) |
| SPEC-460 | 앱 지워진 폰(API-267 `removedAt`, SCR-203·201) | REQ-587, REQ-577, REQ-572, REQ-573, FL-201 | 관리자. PR #101의 API-267 | 서버(`admin_app_devices`)가 폰 줄마다 TBL-101의 `dropped_at`을 함께 읽어 API-267 `devices[]`에 `removedAt`(ISO 8601 UTC, 없으면 `null`)을 실어요. `behind`는 `removedAt`이 `null`이고 앱 버전이 최신 릴리스보다 낮을 때만 참이에요(app-update SPEC-438 바뀜, 목록 3-6). 개요(API-280 `app.behind`), 주의 항목 `app_behind`(3.3의 4), 화면의 '뒤처짐' 표가 모두 이 `behind` 하나를 써서, 앱 지워진 폰은 어디서도 뒤처진 폰으로 세지 않아요. API-280 `app.devices`는 `removedAt`이 `null`인 폰 수예요(3.2). SCR-203: 그 폰 줄은 '뒤처짐' 자리에 '앱 지워짐'(회색 표), 줄 차례는 뒤처진 폰 → 그 밖 → 앱 지워진 폰(무리 안은 API 차례), 펼치면 맨 위 '앱 지워짐 · {시각}'(3.6) 다음에 `events`. SCR-201 '이 사람의 폰': '폰 2 · 0.2.4 · 앱 지워짐 · 마지막 보고 …', 줄 차례는 API 차례. 폰 줄을 숨기거나 지우지 않아요. 그 폰이 다시 기기 보고를 하면(`app_device_put`이 `dropped_at`을 비움) 다음 읽기부터 보통 줄이에요 | 앱 지워진 폰의 버전이 최신과 같음 → '앱 지워짐'만(뒤처짐 없음)<br>`latest`가 `null` → `behind`는 모두 거짓(지금 그대로), '앱 지워짐'은 보임<br>90일 안에 보고한 폰이 모두 앱 지워진 폰 → `app.devices` 0, `app.behind` 0, `app_behind` 줄 없음. SCR-203 폰 그룹에는 그 줄들이 보임('90일 안에 보고한 폰이 없어요'가 아님)<br>같은 폰에 앱을 다시 설치함 → 설치 ID가 새로 생겨 새 폰 줄이 생기고, 옛 줄은 '앱 지워짐'으로 남았다가 마지막 보고 90일 뒤 빠져요[사실: TBL-101은 설치마다 한 줄]<br>FCM의 일시 오류(429·500·502·503·504)나 인증 오류(401·403) → 지운 폰이 아님(지금 `drop_fid` 조건 그대로)[사실: `marong/fcm.py`]<br>응답에 `removedAt` 칸이 없음(반영 전 서버) → 화면은 `null`로 읽어 보통 줄<br>상한(친구마다 20대, 모두 200대)은 앱 지워진 폰도 세요(지금 그대로) | Given 시험친구 가(`friendId` 7)의 폰 둘(폰 1 0.3.2, 폰 2 0.2.4이고 `dropped_at` 있음), 최신 0.3.3을 30시간 전에 올림, When API-267, Then 폰 1 `behind: true`·`removedAt: null`, 폰 2 `behind: false`·`removedAt`이 그 시각<br>When API-280, Then `app.devices` 1, `app.behind` 1, `attention`의 `app_behind` `value` 1<br>Then SCR-203 줄 차례가 폰 1(뒤처짐) → 폰 2(앱 지워짐), 폰 2 줄에 '뒤처짐'이 없고 펼치면 맨 위 '앱 지워짐 · {시각}'<br>Then SCR-201(7)에 '폰 2 · 0.2.4 · 앱 지워짐'<br>Given 폰 2가 다시 기기 보고(API-105), Then 다음 API-267에서 `removedAt: null`·`behind: true`, API-280 `app.behind` 2<br>Given 응답 전체, Then 설치 ID·FID가 없음<br>Given 업데이트 메시지 대상(`app_update_targets`), Then 폰 2는 지금처럼 빠짐(SPEC-430 그대로) | proposed(D146, 기능 변경 3) |

## 3. 세부 규칙

### 3.1 화면 경로와 탭 줄

| 탭 | 화면 | 경로 | 읽는 API |
| --- | --- | --- | --- |
| 개요 | SCR-169(바뀜) | `/chat/admin/` | API-280 |
| 회원 | SCR-200, 한 사람 SCR-201 | `/chat/admin/members`, `/chat/admin/members/{friendId}` | API-236(+ 한 사람은 API-267) |
| 초대 링크 | SCR-202 | `/chat/admin/invites` | API-240, API-236 |
| 앱 버전 | SCR-203 | `/chat/admin/app` | API-267 |
| 비용 | SCR-204 | `/chat/admin/costs` | API-280, API-236, API-266 |
| 아이템 | SCR-186(그대로) | `/chat/admin/items` | API-263\~265 |

- 지금 경로 `/chat/admin/`은 그대로 열려요(즐겨찾기가 깨지지 않음). 끝에 `/`가 붙은 하위 경로(예: `/chat/admin/members/`)는 `/` 없는 경로로 넘겨줘요(301).
- 읽기 비용(일부러 받아들인 것): 비용 화면은 통화 칸을 얻으려고 API-280 전체를 부르고 그림 종류별 줄은 API-266을 따로 불러서, 그림 합을 두 번 계산해요. 회원 한 사람 화면은 API-236 전체(회원마다 `call.friend_month_usd`)와 API-267 전체를 받아 한 사람만 골라요. 관리자는 한 사람이고 회원은 지인 몇 명이라 한 번에 수십 ms 안쪽이라고 봐요[추정]. 회원이 50명을 넘거나 화면이 1초를 넘기면 API-280에 `?parts=call`과 한 사람 읽기를 더하는 것을 다시 봐요. 비용 화면은 API-280 → API-236 → API-266을, 회원 한 사람 화면은 API-236 → API-267을 차례로 불러요(1절 9). 처음 그리는 시간은 응답 시간의 합이 되지만, 관리 페이지가 한 번에 쓰는 DB 연결은 하나예요.
- 화면 스크립트는 한 파일(`admin.js`)에서 경로마다 그리는 함수를 나눠요. 화면 사이에서는 페이지를 새로 받아요(한 페이지 앱의 라우터를 만들지 않음)[새 제안]. 공통 부품은 지금 `unified.js`의 것(`node`, `button`, `request`, `signal`, `shortDate`)을 써요[사실].

### 3.2 API-280 응답 모양

```json
{
  "members": {"count": 3, "unlinked": 1},
  "usageToday": {"day": "2026-11-23", "chatTurns": 41, "callSeconds": 1260, "images": 2, "units": 420},
  "callMonth": {"month": "2026-11", "spentUsd": "121.40", "budgetUsd": "150.00", "percent": 80, "state": "warn"},
  "images": {"month": "2026-11", "totalUsd": "21.10", "budgetPercent": 85},
  "app": {"latest": {"versionName": "0.3.3", "versionCode": 11, "publishedAt": "2026-11-24T05:00:00Z"},
          "paused": false, "devices": 2, "behind": 1},
  "attention": [
    {"kind": "call_budget", "level": "warn", "value": 80, "target": "/chat/admin/costs"}
  ]
}
```

- `callMonth.state`: `ok`(80% 밑), `warn`(80% 이상), `exhausted`(100% 이상), `hard_stop`(120% 이상). 문턱은 `call_cost.STATE`와 같아요[사실]. 예산은 DB 제약으로 늘 0보다 커서 '예산 꺼짐' 상태는 두지 않아요(SPEC-457 예외).
- `images.budgetPercent`: API-266의 `budgets` 가운데 null이 아닌 것의 가장 큰 `ratio`를 퍼센트로 내림. 예산이 모두 null이면 null. 어느 예산인지는 싣지 않아서, 주의 항목 문구는 종류를 말하지 않고 비용 화면에서 종류를 봐요(08).
- `app`: API-267을 만드는 서버 함수의 결과에서만 셈(버전 기록 파일과 TBL-182를 따로 읽지 않음). `devices`는 그 결과의 폰 수, `behind`는 `behind`가 참인 폰 수.
  - 기능 변경 3-10 제안: `devices`는 앱 지워진 폰(`removedAt`이 있는 폰, TERM-242)을 뺀 폰 수예요. 개요 카드 '폰 n대 중 m대 뒤처짐'의 n이에요.
  - 기능 변경 3-9 제안: `behind`는 식이 그대로예요. API-267의 `behind`가 앱 지워진 폰에서 늘 거짓이라(SPEC-460) 앱 지워진 폰은 m에 들지 않아요.
- `callMonth`, `images`, `app`, `usageToday`는 실패하면 각각 `null`이에요(SPEC-451).

읽는 차례와 시간 제한[새 제안]:

- 서버는 풀에서 연결 하나를 2초까지 기다려 받아요. 못 받으면 503 `db_unavailable`이에요. 친구 요청이 연결을 다 쓰는 동안에는 관리 화면이 물러나요.
- 그 연결 하나에서 회원 수 → 통화 → 그림 → 앱 → 사용량 → 초대 링크 만료 수를 차례로 읽어요. 동시에 읽지 않아요(`asyncio.gather` 같은 동시 실행을 쓰지 않음). 그림·앱 부분이 부르는 API-266·API-267의 서버 함수가 연결을 스스로 받는 모양이면, 개요가 받은 연결을 넘겨받게 나눠요(두 API의 응답 모양은 그대로).
- 부분마다 짧은 트랜잭션 하나를 열고 `SET LOCAL statement_timeout = '1s'`로 읽어요. 다섯 부분을 한 트랜잭션에 넣으면 한 부분의 시간 초과가 트랜잭션 전체를 깨뜨려 다음 부분을 읽지 못해서, 부분마다 트랜잭션을 끝내요(`SET LOCAL`은 그 트랜잭션이 끝나면 풀려요). DB 밖의 일(앱 부분의 릴리스 파일 읽기)까지 합쳐 한 부분 전체를 1초로 끊어요. 회원 수도 같은 방식으로 1초예요(넘으면 503).
- 가장 늦을 때: 연결 기다림 2초 + 회원 수 1초 + 다섯 부분 5초 = 8초예요. 화면 요청의 제한 시간(`unified.js`의 `request`, 10초)[사실] 안이라 그동안 화면은 SCR-169#loading이고, 10초를 넘기면 공통#error예요. 보통은 부분마다 수십 ms라고 봐요[추정].

### 3.3 주의 항목

서버가 이 차례로 계산해요. 한 종류는 한 줄이고 `value`는 그 줄에 들어갈 숫자 하나예요. 문구는 08 화면 정의가 정해요.

| 차례 | `kind` | 조건 | `level` | `value` | `target` |
| --- | --- | --- | --- | --- | --- |
| 1 | `call_budget` | `callMonth.state`가 `warn`·`exhausted`·`hard_stop` | `exhausted`·`hard_stop`이면 `danger`, 아니면 `warn` | `percent` | `/chat/admin/costs` |
| 2 | `image_budget` | `images.budgetPercent`가 80 이상 | 100 이상이면 `danger`, 아니면 `warn` | `budgetPercent` | `/chat/admin/costs` |
| 3 | `app_paused` | `app.paused`가 참 | `warn` | 없음 | `/chat/admin/app` |
| 4 | `app_behind` | 뒤처진 폰 가운데 마지막 `state` 줄이 `needs_confirm`·`failed`인 폰, 또는 `app.latest.publishedAt`에서 24시간이 지난 폰이 1대 이상(멈춤이면 세지 않음) | `needs_confirm`·`failed`가 있으면 `danger`, 아니면 `warn` | 그 폰 수 | `/chat/admin/app` |
| 5 | `invite_expiring` | 열린 초대 링크 가운데 `expires_at`이 지금부터 24시간 안 | `warn` | 그 링크 수 | `/chat/admin/invites` |
| 6 | `unlinked_friend` | 프로필이 없는 기존 친구가 1명 이상 | `warn` | 그 수 | `/chat/admin/members` |

- 친구 이름은 주의 항목에 넣지 않아요(개수만). 화면에서 누르면 그 화면에서 이름을 봐요.
- 24시간과 80%는 새 제안·기존 문턱이에요(02 '시작 값').
- 기능 변경 3-9 제안: ④의 '뒤처진 폰'은 API-267의 `behind`가 참인 폰이라 앱 지워진 폰(TERM-242)은 들지 않아요(SPEC-460). 조건의 식은 그대로예요.

### 3.4 통화 월 예산 함수(통화 마이그레이션 011)

```text
call.month_budget(p_start timestamptz, p_end timestamptz)
  RETURNS TABLE(spent_usd numeric, budget_usd numeric)
  LANGUAGE sql STABLE SECURITY DEFINER, SET search_path = pg_catalog, pg_temp, 본문 BEGIN ATOMIC
  spent_usd = tools/vertex_live/call_cost.py의 MONTH 쿼리의 total과 같은 식
              (turns의 live + estimates + searches의 search_usd + organizer의 organize)
  budget_usd = call.settings의 monthly_budget_usd(숫자), 없으면 150
  REVOKE ALL FROM PUBLIC; GRANT EXECUTE TO marong
  같은 마이그레이션: call.friend_month_usd(009)의 search_path만 pg_catalog, pg_temp로(ALTER FUNCTION)
```

- 앱 서버는 `SELECT * FROM call.month_budget(%s, %s)`를 UTC 달의 경계(`marong.usage.month_bounds`)로 1초 제한 안에서 불러요. 통화 비용 표 읽기 권한은 지금처럼 없어요.
- 식이 통화 서버의 `MONTH`와 두 곳에 있어요. 같은 자료에서 두 값이 같은지 시험(TC-631)으로 지켜요. 통화 서버가 이 함수를 쓰게 바꾸는 일은 이 part의 범위 밖이에요[추정: 같게 두는 쪽이 통화 서버를 건드리지 않아 안전].
- 굳히기(`SECURITY DEFINER`): `search_path` 끝에 `pg_temp`를 적어요. 적지 않으면 Postgres가 표·타입 이름을 부르는 세션의 임시 스키마에서 먼저 찾아서, `marong` 역할이 만든 임시 도메인(CHECK 안에 자기 함수)이 함수 주인 권한으로 돌 수 있어요[사실]. 본문의 표는 모두 `call.`을 붙이고, `MONTH`의 `%s::timestamptz` 캐스트는 인자가 이미 `timestamptz`라 빼요(남는 캐스트는 키워드 타입 `bigint`·`numeric`뿐). 본문은 `BEGIN ATOMIC`이라 이름이 만들 때 정해져요(Postgres 14 이상, 운영은 16). 그래서 '식은 그대로'의 예외는 캐스트를 뺀 `limits` 한 줄과 마지막 `SELECT`예요([표 문서 3절](../05-erd/admin.md), 시험 TC-632).
- 이 함수는 `call.budget_events`에 쓰지 않아요(읽기만). 80·100·120% 이벤트는 지금처럼 통화 서버가 남겨요.

### 3.5 회원과 폰을 맞추는 규칙

API-267의 `devices[]`와 `fetches[]`에는 친구 이름 `friend`와 친구 ID `friendId`가 있고, `friendId`는 회원 API(API-236)의 `friendId`와 같은 번호예요(PR #101 커밋 `b54547d`, 2026-11-23 보안 검토 반영, SPEC-438)[사실: `main` `15889ff`, PR #101은 2026-11-23 합쳐짐]. 그래서 화면은:

1. 사람은 `friendId`로만 맞춰요. 회원 한 사람 화면(SCR-201)은 `devices[].friendId`가 경로의 `friendId`와 같은 폰만 보여요. 이름은 보이기만 하고 맞추는 데 쓰지 않아요(이름은 겹치거나 바뀔 수 있음).
2. 앱 버전 화면(SCR-203)은 API-236을 읽지 않아요(REQ-578). 폰 줄과 받아 감 칸은 `friendId`로 서로 맞추고, 주소 조각 `#friend={friendId}`로 그 친구의 첫 폰 줄을 찾아요. `friendId`가 다른데 이름이 같은 친구가 둘 이상이면 이름 뒤에 번호를 붙여요('시험친구 가(7)').
3. 상한(PR #101 SPEC-438): `devices`는 친구마다 가장 최근에 보고한 20대, 모두 200대까지, `fetches`는 100명까지예요. 화면은 상한에 닿은 것을 숨기지 않고 알려요: 그 친구의 폰이 20줄이면 '이 사람은 최근 보고한 20대만 보여요'(SCR-201은 '최근 보고한 20대만 보여요'), SCR-201에서 `devices`가 200줄이면 그 사람의 폰이 빠졌을 수 있어서 '폰이 많아 일부만 보여요'(폰 0대여도 '없어요'라고 하지 않음), `devices`가 200줄이면 '폰이 많아 200대까지만 보여요', `fetches`가 100칸이면 '받아 간 사람이 많아 100명까지만 보여요'. 폰 순번 `phone`은 그 친구의 보이는 20대 가운데 처음 등록한 차례(1\~20)라서, 오래된 폰이 빠지면 순번이 바뀔 수 있어요. 개요(API-280)의 앱 칸('폰 n대 중 m대 뒤처짐')도 같은 서버 함수의 결과라 이 상한 안의 폰만 세요.
4. API-267의 형식은 이 part에서 바꾸지 않아요. 위는 PR #101이 정한 칸을 읽는 규칙이에요. 기능 변경 3-8 제안: 기능 변경 3만 `devices[]`에 `removedAt` 한 칸을 더하고 `behind`의 뜻을 좁혀요(SPEC-460, app-update SPEC-438). 그 밖의 형식은 PR #101 그대로예요.
5. 기기 등록(API-105)의 새 폰 상한: 그 친구에게 30일 안에 보고한 폰이 이미 20대이고 새 installId면 409 `too_many_devices`로 거절해요. PR #101이 제안했고 2026-11-23 그 체크포인트에서 승인됐어요(D134, PR #101 기능 명세 8.9, 커밋 `ef2b83a`)[사실: `main` `15889ff`]. 이 part는 그 동작을 정하지도 옮겨 적지도 않아요. 거절된 폰은 줄이 만들어지지 않아 API-267과 관리 화면에 나오지 않아요.

### 3.6 업데이트 기록 줄의 문구

| API-267 줄 | 문구 |
| --- | --- |
| `kind: pushed`, `attempt` n | '보냄 {versionName 또는 코드}({versionCode}) · {n}번째 · {시각}' |
| `kind: push_failed`, `status` | '보내기 실패({status}) · {n}번째 · {시각}' |
| `kind: state`, `state: downloaded` | '받음 · {시각}' |
| `state: waiting_quiet` | '조용할 때 기다림 · {시각}' |
| `state: needs_confirm` | '확인 창 기다림 · 앱을 열어 지금 설치를 눌러야 해요 · {시각}' |
| `state: failed`, `status` | '설치 실패({status}) · {시각}' |
| `kind: installed`, `appVersion` | '설치됨 {appVersion} · {시각}' |
| `fetches[].items[]` | '받아 감 ({versionCode}) · {시각}' |
| `removedAt`(기능 변경 3-12 제안, SPEC-460) | '앱 지워짐 · {시각}'(펼친 줄의 맨 위, `events`보다 먼저) |

`{시각}`은 한국 시각의 짧은 모양(지금 `shortDate`)이에요. 버전 이름은 `releases`에서 같은 `versionCode`를 찾아 붙이고, 없으면 코드만 써요.

### 3.7 바뀌는 기존 명세

[요구사항의 기능 변경 목록](../02-prd/admin.md#승인된-항목이-바뀌는-곳기능-변경-목록) 3·4·7·11번(SPEC-380의 표시, SPEC-395의 화면 짜임, SPEC-398의 화면 자리, SPEC-427의 화면 자리)이에요. 동희님이 2026-11-23 체크포인트에서 모두 '바꿈'으로 답하셔서(D136) 이 설계 PR에서 그 문서의 행을 고치고 'D136 1-x' 표시를 더했어요. 구현 PR(TASK-499)은 구현한 이름이 그 줄과 다를 때만 맞춰요.

기능 변경 3(2026-11-24, 체크포인트 전): [기능 변경 목록 3](../02-prd/admin.md#꾸미기-꺼짐-안내와-앱-지워진-폰-기능-변경-목록-3)의 3-1·3-4(pet-app 08 SCR-186 상태 표, pet-app 04 1절 5)와 3-6(app-update SPEC-438·8.6)은 이 설계 PR에서 그 문서에 제안으로 고쳤어요. 줄마다 답을 받고, '그대로'로 답한 줄은 합치기 전에 되돌려요. 3-5(BUG-124 기록)는 열린 PR #126이 같은 파일을 고쳐서 이 PR에서 고치지 않아요.

## 4. 추적

| REQ | FL | SPEC |
| --- | --- | --- |
| REQ-570 | FL-200 | SPEC-450 |
| REQ-571 | FL-200 | SPEC-450 |
| REQ-572 | FL-200 | SPEC-451, SPEC-457, SPEC-460(제안) |
| REQ-573 | FL-200, FL-201 | SPEC-451, SPEC-456, SPEC-460(제안) |
| REQ-574 | FL-200 | SPEC-452 |
| REQ-575 | FL-200 | SPEC-453 |
| REQ-576 | FL-200 | SPEC-454 |
| REQ-577 | FL-201 | SPEC-456, SPEC-460(제안) |
| REQ-578 | FL-201 | SPEC-456 |
| REQ-579 | FL-200 | SPEC-457 |
| REQ-580(비기능) | 모두 | 1절 3, SPEC-451·456의 받아들임 조건. 12에서 시험 |
| REQ-581(비기능) | 모두 | 1절 7, SPEC-450, SPEC-458(1023px 이하는 그대로). 12에서 시험 |
| REQ-585(비기능, D140) | 모두(흐름의 칸은 바뀌지 않음) | SPEC-458. 12에서 시험 |
| REQ-582 | FL-200 | SPEC-453 |
| REQ-583 | FL-200 | SPEC-455 |
| REQ-584(미룸, D138) | 없음 | 없음 |
| REQ-586(제안, D145) | FL-192 | SPEC-459 |
| REQ-587(제안, D146) | FL-201 | SPEC-460 |

- 모든 SPEC 행이 REQ를 하나 이상 가리키고, Must 기능 REQ(570·571·572·574·575·576·577·579·582)는 모두 SPEC 행이 있어요. 기능 변경 3의 Should REQ-586·587(제안)은 SPEC-459·460이에요.
- 요구사항이 없는 동작: 없음. 경로 끝 `/`의 301(3.1)은 REQ-570을 지키려는 구현 규칙이에요.
- AI 모델을 부르는 동작: 없음.
