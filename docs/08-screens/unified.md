# 통합 앱(MVP) 화면(08 화면 상태)

상태: 초안(2026-11-19 11시대 KST, Claude). 아직 만들지 않았어요. 설계 승인은 2026-11-19 10:15 KST 설계 스레드의 동희님 "승인"(D104)이에요.
입력: [사이트맵](../07-sitemap/sitemap.yaml) SCR-163\~174, [설계 제안](../unified-app.md) 5\~13절과 14절(REQ-430\~483, FL-169\~178, SPEC-370\~396), API 계약 `api/unified.openapi.yaml` API-211\~242, 도메인 CTX-026\~029와 용어 TERM-173\~198. 캐릭터 만들기 화면(SCR-170\~174)은 [반려동물 화면](pet.md) SCR-142\~146에서 결제를 빼고 주인을 로그인한 사람으로 바꿔 새 번호로 적었어요. SCR-140\~162는 고치지 않아요.
기준: 토큰과 부품은 [`design/README.md`](../../design/README.md)를 따라요. 얼려 둔 토큰 103개(`design/base.tokens.json`, D67)만 쓰고 새 토큰은 더하지 않아요.
와이어프레임: 아직 그리지 않았어요. 이 문서의 상태 표가 그릴 목록이에요. 목업(09단계)은 대지 17장을 그렸어요: [목업 기록](../../design/unified-mockup.md), 캔버스 [마롱이 통합 앱 목업](https://claude.ai/artifact/GXVep4QepAUdFhH6gDmLb3).

범위는 동희님 주변 사람이 쓰는 MVP예요(D103). 안내문, 동의, 나이 확인, 결제, 사람별 기능 제한 화면은 없어요.

| 번호 | 화면 | 주소 | 절 |
| --- | --- | --- | --- |
| SCR-163 | 가입 | `/chat/join/:token` | [2](#scr-163-가입) |
| SCR-164 | 로그인 | `/chat/login` | [3](#scr-164-로그인) |
| SCR-165 | 내 마롱이 | `/chat/me` | [4](#scr-165-내-마롱이) |
| SCR-166 | 입혀 보기 | `/chat/character/:id/try` | [5](#scr-166-입혀-보기) |
| SCR-167 | 목소리 고르기 | `/chat/me/voice` | [6](#scr-167-목소리-고르기) |
| SCR-168 | 친구 | `/chat/friends` | [7](#scr-168-친구) |
| SCR-169 | 관리자 | `/chat/admin/` | [8](#scr-169-관리자) |
| SCR-170 | 캐릭터 만들기(사진) | `/chat/character/new` | [9](#scr-170-캐릭터-만들기사진) |
| SCR-171 | 특징표 고치기 | `/chat/character/:id/traits` | [10](#scr-171-특징표-고치기) |
| SCR-172 | 미리 보기 | `/chat/character/:id/preview` | [11](#scr-172-미리-보기) |
| SCR-173 | 후보 고르기 | `/chat/character/:id/candidates` | [12](#scr-173-후보-고르기) |
| SCR-174 | 이름 짓기 | `/chat/character/:id/name` | [13](#scr-174-이름-짓기) |

14절은 웹(아이폰 사파리)에서 다른 것, 15절은 있는 화면(SCR-001·002·107·109·112·113·119·120\~122)에서 바뀌는 곳이에요.

## 1. 공통 규칙

모든 화면에 쓰여요. 화면 절에는 이 규칙과 다른 것만 적어요. [08 화면 정의 README](README.md)의 통화·`/chat/` 공통 규칙 가운데 테마와 폭 규칙은 그대로 따라요.

- 문(로그인): 가입(SCR-163)·로그인(SCR-164)·관리자(SCR-169)를 뺀 화면은 로그인 쿠키 `marong_session`이 있는 기기에서만 열려요. 어느 API든 401 `login_required`가 오면 쓰던 글과 지금 주소를 `sessionStorage`에 남기고 로그인(SCR-164)으로 가요. 로그인하면 그 주소로 돌아와 글을 칸에 다시 넣고 지워요. 화면 절의 상태 표에는 401을 따로 적지 않아요.
- 관리자(SCR-169)는 Cloudflare Access 뒤예요(REQ-438). 로그인 쿠키를 쓰지 않아요.
- 글: 반말이고 마롱이 말투예요(REQ-021, 있는 `/chat/` 화면과 같음). 짧게 쓰고 사람을 탓하지 않아요. 관리자 화면만 동희님이 보는 화면이라 '-요'로 끝나는 꾸밈없는 글이에요.
- 마롱이 이름: 화면에 보이는 마롱이 이름은 그 사람의 `botName`(API-216)이에요. 아래 문구의 `{이름}` 자리예요. 조사는 이름 끝 글자의 받침에 맞춰 화면이 골라요(이랑·랑, 이가·가, 을·를, 이야·야). 로그인 전 화면(SCR-163의 가입 전, SCR-164)은 기본 이름 '마롱이'예요. `{내 이름}`은 가입 때 넣은 이름(`friendName`), `{친구 이름}`은 친구 목록의 이름이에요.
- 얼굴: 쓰는 캐릭터가 있으면 그 캐릭터의 정면 그림(API-242 `front`), 없으면 기본 마롱이 얼굴(01)이에요. 그림은 꾸밈이라 `alt=""`이고 이름은 글로 따로 읽혀요.
- 폭: 세로 휴대폰 360\~430px. 넓은 화면은 글 대화처럼 가운데 폰 틀(`backdrop`, `panel-shadow`)이에요.
- 머리: 왼쪽 돌아가는 버튼(`size.touch-min` 48px, 글 '글 대화' 또는 '내 마롱이'), 가운데 제목(굵게), 아래 `line` 1px(`border-width.thin`). 앱 창의 뒤로 가기는 창을 닫으니까 머리 버튼이 돌아가는 경로예요.
- 토큰: 버튼 테두리·띠·확인 줄은 `radius.sm`, 카드는 `radius.md`, 칩은 `radius.full`, 누르는 칸은 `size.touch-min` 이상, 얼굴 원은 `size.avatar`·`size.face-home`·`size.face-call`, 고른 것의 테두리는 `accent`, 오류 메시지는 `danger`, 작은 글은 `font-size.caption`·`text-muted`예요. 테마는 한국 시각 08:00\~20:00 직전 군밤 크림(`color.b`), 그 밖 밤하늘(`color.a`)이에요.
- 400 `invalid_input`: 그 칸 아래 '다시 한번 확인해 줄래?'와 그 칸의 규칙 한 줄. 쓴 값은 남겨요.
- 403 `cross_site`: 그 동작 옆 '이 화면에서 다시 해 줘'. 저절로 다시 보내지 않아요.
- 404 `not_found`(남의 것, 없는 것, 지운 것): 안내 화면 '찾지 못했어'와 '내 마롱이로'(SCR-165).
- `default`(500 포함)·네트워크 없음·시간 넘김(10초): 불러오기는 안내 화면 '잠깐 문제가 생겼어. 다시 해 볼래?'와 '다시 해 볼게', 추적 id(`traceId`, `font-size.caption`). 쓰기는 값을 응답 전으로 되돌리고 그 동작 옆에 같은 말과 '다시 해 볼게'. 화면 절의 #error가 이 규칙이에요.
- 반복: 요청이 도는 동안 그 버튼·칩 그룹을 막아요.
- 긴 일(202): 그리기와 사진 살펴보기는 만들기 작업(TERM-185)으로 돌아요. 화면은 API-221을 2초마다 다시 부르고 30초 뒤부터는 5초마다 불러요. 화면을 닫아도 작업은 이어지고, 다시 열면 서버의 단계(`stage`)에 맞는 화면으로 가요. 앱은 작업이 끝나면 앱 알림(SCR-108)을 받고, 웹은 알림이 없어요(14절).
- 그림: `<img>`는 응답 번호를 읽지 못해요. 그림 실패는 회색 칸과 '그림 다시 보기'예요.
- 지금 값: 페이지가 다시 보일 때(`visibilitychange`, 앱으로 돌아옴) 그 화면의 읽기 API를 다시 불러요. 쓰던 칸은 덮어쓰지 않아요.
- 사람이 쓴 글(이름, 메모, 특징표의 글)은 `textContent`로만 넣어요.
- 움직임 줄이기: 띠·칩·그리는 중 움직임을 끄고 바로 바꿔요.

## SCR-163 가입

Purpose: 초대 링크를 연 사람이 이름을 넣어 가입하거나(`join`), 기존 계정을 이 기기에 잇거나(`link`), 다시 로그인해요(`relogin`). 끝나면 앱 받기와 기기 추가 코드를 보여 줘요. (FL-169, FL-170, FL-171)

| Data | Source |
| --- | --- |
| 링크 종류(`kind`)와 상태 | API-211 |
| 이 기기가 이미 로그인돼 있는지(내 이름) | API-216(401이면 로그인 전) |
| 가입·연결 결과(내 이름, 마롱이 이름) | API-212 |
| 기기 추가 코드와 끝나는 때 | API-214 |
| 앱 받기 주소(안드로이드) | API-141(app-update 계약) |

| Action | Result | Failure |
| --- | --- | --- |
| 이름 넣기(`join`만, 1\~12자) | 화면이 앞뒤 공백을 빼고 길이를 먼저 막음 | 400 → #invalid |
| '시작하기'(`join`) · '이어 가기'(`link`, `relogin`) | API-212 → 201과 로그인 쿠키 → #done | 아래 상태 |
| 글 대화로 가기 | SCR-107 | 없음 |
| 앱 받기(안드로이드 브라우저에서만 보임) | API-141의 `url`로 APK 받기 | 릴리스 없음(204) → 버튼 대신 '앱은 곧 준비돼' |
| 기기 추가 코드 만들기 | API-214 → 201 → #code | 429 → #code-limit |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-163#loading | 얼굴 자리 빈 원과 글·버튼 자리 회색 | |
| SCR-163#normal | 기본 마롱이 얼굴(01), '안녕! 나는 마롱이야. 뭐라고 부르면 돼?', 이름 칸(1\~12자, 글자 수), '시작하기'(이름이 있어야 켜짐) | API-211#200(`kind=join`, `state=open`) |
| SCR-163#link | 얼굴, '다시 만나서 반가워! 이 기기에서도 이어서 얘기하자'와 '이어 가기'. 이름 칸 없음 | API-211#200(`kind=link`) |
| SCR-163#relogin | 얼굴, '다시 들어오는 거구나. 바로 이어 줄게'와 '이어 가기'. 이름 칸 없음 | API-211#200(`kind=relogin`) |
| SCR-163#signed-in | 이미 로그인된 기기에서 링크를 열었을 때. 얼굴, '이 기기는 이미 {내 이름}(으)로 들어와 있어'와 '글 대화로 가기'(주 버튼), '이 링크로 다시 들어가기'(누르면 링크 종류에 맞는 위 상태로) | API-211#200, API-216#200 |
| SCR-163#submitting | 버튼 꺼짐과 '준비하는 중이야…' | |
| SCR-163#invalid | 이름 칸 아래 '이름은 1\~12자로 적어 줘', 쓴 값 남김 | API-212#400(`invalid_input`) |
| SCR-163#used | 걱정하는 얼굴(13), '이 링크는 이미 썼어. 링크를 보내 준 사람한테 새 링크를 부탁해 줘'와 '로그인하러 가기'(SCR-164) | API-211#410(`invite_used`), API-212#410(`invite_used`) |
| SCR-163#expired | 걱정하는 얼굴(13), '이 링크는 기간(7일)이 지났어. 링크를 보내 준 사람한테 새 링크를 부탁해 줘' | API-211#410(`invite_expired`), API-212#410(`invite_expired`) |
| SCR-163#not-found | 걱정하는 얼굴(13), '이 링크는 찾지 못했어. 주소를 다시 확인해 줄래?' | API-211#404(`invite_not_found`), API-212#404(`invite_not_found`) |
| SCR-163#done | '{내 이름}, 반가워! 이제 {이름}이랑 얘기할 수 있어', 주 버튼 '글 대화로 가기', 카드 '앱에서도 쓰기': '앱 받기'(안드로이드)와 '기기 추가 코드 만들기'. 아이폰 사파리는 앱 받기 대신 14절의 '홈 화면에 추가' 안내 | API-212#201, API-141#200 |
| SCR-163#code | 큰 숫자 6자리, '앱 첫 화면에 이 숫자를 넣어 줘. 10분 동안 한 번만 쓸 수 있어', 남은 시간, '새 코드 만들기' | API-214#201 |
| SCR-163#code-expired | 숫자가 흐려지고(`opacity.faded`) '시간이 지났어. 새 코드를 만들어 줘' | (화면이 `expiresAt`으로 판단) |
| SCR-163#code-limit | '코드를 여러 번 만들었어. 조금 있다가 다시 해 줘'(한 시간에 5개), 만들기 버튼 꺼짐 | API-214#429(`too_many_codes`) |
| SCR-163#error | 공통 규칙. 쓴 이름은 남김 | API-211#default, API-212#403(`cross_site`), API-212#default, API-214#default, API-141#default |

비어 있음은 없어요(링크가 없으면 #not-found). 오래된 데이터: '시작하기'를 누르는 사이 링크가 쓰였거나 지났으면 API-212의 410으로 #used·#expired가 돼요.

## SCR-164 로그인

Purpose: 로그인이 없는 기기에서 기기 추가 코드를 넣어 로그인해요. 코드가 없는 사람에게는 초대 링크가 필요하다고 알려요. 앱의 첫 화면이에요. (FL-171)

| Data | Source |
| --- | --- |
| 이미 로그인된 기기인지 | API-216 |
| 로그인 결과 | API-213 |

| Action | Result | Failure |
| --- | --- | --- |
| 숫자 6자리 넣기(`inputmode="numeric"`, `autocomplete="one-time-code"`) | 여섯 번째 숫자가 들어가면 '들어가기'가 켜짐 | 숫자가 아닌 글자는 받지 않음 |
| 들어가기 | API-213 → 200과 로그인 쿠키 → 남겨 둔 주소(없으면 SCR-107) | 아래 상태 |
| '코드가 없어?' 펴기 | 안내 두 줄이 펴짐(#help) | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-164#loading | 얼굴 자리 빈 원과 숫자 칸 자리 회색 | |
| SCR-164#normal | 기본 마롱이 얼굴(01), '다시 만나서 반가워! 기기 추가 코드를 넣어 줘', 숫자 칸 여섯 개, '들어가기', 접힌 줄 '코드가 없어?' | API-216#401(`login_required`) |
| SCR-164#from-expired | #normal 위에 한 줄 '로그인이 풀렸어. 다시 들어와 줘'. 로그인하면 보던 화면으로 돌아감 | (다른 화면이 401 `login_required`로 보냄) |
| SCR-164#help | '이미 쓰고 있는 기기의 내 마롱이에서 코드를 만들 수 있어'와 '쓰는 기기가 없으면 초대 링크를 보내 준 사람한테 다시 로그인 링크를 부탁해 줘' | |
| SCR-164#submitting | 칸과 버튼 꺼짐, '확인하는 중이야…' | |
| SCR-164#wrong | 칸을 비우고 '코드가 맞지 않거나 시간이 지났어. 다시 확인해 줄래?' | API-213#401(`code_wrong`) |
| SCR-164#invalid | '숫자 6자리를 넣어 줘' | API-213#400(`invalid_input`) |
| SCR-164#blocked | 걱정하는 얼굴(13), '여러 번 틀려서 잠깐 쉬어 갈게. N분 뒤에 다시 해 줘', 칸과 버튼 꺼짐. `Retry-After`로 남은 시간을 세고 끝나면 #normal | API-213#429(`too_many_tries`) |
| SCR-164#signed-in | 화면을 보이지 않고 남겨 둔 주소(없으면 SCR-107)로 감 | API-216#200 |
| SCR-164#error | 공통 규칙 | API-213#403(`cross_site`), API-213#default, API-216#default |

비어 있음과 오래된 데이터는 없어요. 틀린 횟수는 화면에 보이지 않아요(다섯 번 틀린 뒤의 시도부터 #blocked).

## SCR-165 내 마롱이

Purpose: 자기 마롱이의 이름, 쓰는 캐릭터, 보관한 캐릭터, 통화 목소리를 보고 바꾸고, 기기 추가 코드를 만들고, 오늘 쓴 양을 봐요. (FL-171, FL-173, FL-174, FL-177)

| Data | Source |
| --- | --- |
| 내 이름, 마롱이 이름, 쓰는 캐릭터(이름·종류·얼굴), 목소리, 오늘 쓴 양 | API-216 |
| 캐릭터 목록(보관한 것, 만들던 것)과 상한 3 | API-229 |
| 캐릭터 얼굴 그림 | API-242 |
| 목소리 이름표 | API-218 |
| 오늘 쓴 양(글 답 수, 통화 시간, 그림 수, 사용 단위, 한도, 티켓) | API-234 |
| 기기 추가 코드와 끝나는 때 | API-214 |

| Action | Result | Failure |
| --- | --- | --- |
| 이름 바꾸기 | 이름 줄을 누르면 칸이 열림(1\~12자) → '바꾸기' → API-217 `{botName}` → 200, 이 화면과 글 대화·통화 머리말이 새 이름 | 400 → #name-invalid |
| 통화 목소리 줄 | SCR-167 | 없음 |
| 보관한 캐릭터 카드 누르기 | SCR-166(입혀 보기) | 없음 |
| 만들던 캐릭터 카드 누르기 | 그 단계 화면(SCR-170\~174) | 없음 |
| 새 캐릭터 만들기 | SCR-170 | 3개면 버튼 꺼짐(#full) |
| 기본 마롱이로 돌아가기(캐릭터를 쓰는 중일 때) | 확인 줄 '기본 마롱이로 돌아갈까? 대화랑 기억은 그대로야' → API-228 `{characterId: null}` → 200 → #reverted | 공통 규칙 |
| 캐릭터 지우기(카드의 ⋯) | 확인 줄 '지우면 되돌릴 수 없어. 지울까?' → API-238 → 204. 쓰던 캐릭터면 기본 마롱이로 돌아감 | 409 → #delete-busy |
| 기기 추가 코드 만들기 | API-214 → 201 → #code | 429 → #code-limit |
| 구글 캘린더 줄 | 연결 안 됨이면 `/google/start`로 가요(로그인 쿠키로 열림, SPEC-384). 연결됨이면 '끊기'를 누르고 확인 줄에서 한 번 더 눌러 `POST /google/disconnect`를 보내요. 끝나면 글 대화 방에 한 줄이 남음 | 그 페이지의 규칙. 끊기 실패는 그 줄 옆에 공통 오류 말 |
| 친구 줄 | SCR-168 | 없음 |
| 로그아웃 | 확인 줄 '이 기기에서 나갈까?' → API-215 → 204 → SCR-164 | 공통 규칙 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-165#loading | 얼굴 원과 줄 여섯 개 자리에 회색 | |
| SCR-165#normal | 위 카드: 얼굴(`size.face-home`), 마롱이 이름(굵게)과 '이름 바꾸기'. 줄 '통화 목소리 · {목소리 이름표}'. 그룹 '캐릭터': 기본 마롱이 카드와 보관한 캐릭터 카드, '새 캐릭터 만들기'. 그룹 '다른 기기에서도 쓰기': '기기 추가 코드 만들기'. 그룹 '오늘 쓴 양'. 줄 '친구', '구글 캘린더'. 맨 아래 '로그아웃' | API-216#200, API-229#200, API-218#200, API-234#200 |
| SCR-165#default-character | 기본 마롱이 카드에 '쓰는 중'. 캐릭터가 하나도 없으면 그 아래 '사진으로 강아지나 고양이 캐릭터를 만들 수 있어' | API-216#200(`character=null`), API-229#200(`characters` 빈 목록) |
| SCR-165#wearing | 쓰는 캐릭터 카드에 '쓰는 중', 기본 마롱이 카드에 '기본 마롱이로 돌아가기' | API-216#200(`character` 있음) |
| SCR-165#making | 만들던 캐릭터 카드에 '만드는 중이야 · 이어서 하기'. 작업이 도는 중이면 '그리는 중이야' | API-229#200(`status=draft`) |
| SCR-165#full | '새 캐릭터 만들기'가 꺼지고 '캐릭터는 3개까지 둘 수 있어. 하나를 지우면 새로 만들 수 있어' | API-229#200(`characters` 3개), API-219#409(`too_many_characters`) |
| SCR-165#name-edit | 이름 칸이 열리고 글자 수(예: 3/12), '바꾸기'·'그만두기' | |
| SCR-165#name-saving | 칸과 버튼 꺼짐 | |
| SCR-165#name-invalid | 칸 아래 '이름은 1\~12자로 적어 줘', 쓴 값 남김 | API-217#400(`invalid_input`) |
| SCR-165#name-saved | 띠 '이제 {이름}라고 불러 줘!'(3초), 머리말과 카드가 새 이름 | API-217#200 |
| SCR-165#reverted | 띠 '기본 마롱이로 돌아왔어. 대화랑 기억은 그대로야'. 이름은 응답의 `botName` 그대로 보임 | API-228#200 |
| SCR-165#deleted | 그 카드가 사라지고 띠 '지웠어' | API-238#204 |
| SCR-165#delete-busy | 그 카드 아래 '지금 그리는 중이라 지울 수 없어. 끝나고 다시 해 줘' | API-238#409(`job_running`) |
| SCR-165#code | 큰 숫자 6자리, '다른 기기의 로그인 화면에 이 숫자를 넣어 줘. 10분 동안 한 번만 쓸 수 있어', 남은 시간, '새 코드 만들기' | API-214#201 |
| SCR-165#code-expired | 숫자가 흐려지고 '시간이 지났어. 새 코드를 만들어 줘' | (화면이 `expiresAt`으로 판단) |
| SCR-165#code-limit | '코드를 여러 번 만들었어. 조금 있다가 다시 해 줘', 만들기 버튼 꺼짐 | API-214#429(`too_many_codes`) |
| SCR-165#usage | 바뀜 → [usage-limit.md](usage-limit.md) SCR-165. '내 사용량'에서 현재 사용량, 하루 한도, 티켓, 이번 달 통화를 보여요. | API-234#200 |
| SCR-165#usage-limit | 숫자 아래 막대(`units`/`limit`)와 '오늘 320 / 1000', 티켓이 있으면 '티켓 3장' | API-234#200(`limit` 있음) |
| SCR-165#usage-over | 막대가 가득 차고 '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져'. 티켓이 있으면 '오늘 양을 넘어서 티켓으로 이어 가는 중이야(티켓 3장)' | API-234#200(`units`가 `limit` 이상) |
| SCR-165#usage-error | '오늘 쓴 양' 그룹만 '지금은 못 불러왔어'와 '다시 해 볼게'. 다른 줄은 그대로 씀 | API-234#default |
| SCR-165#web-ios | 아이폰 사파리에서만 '다른 기기에서도 쓰기' 그룹 위에 한 줄(14절) | (화면이 UA와 `display-mode`로 판단) |
| SCR-165#error | 공통 규칙 | API-216#default, API-229#default, API-218#default, API-217#403(`cross_site`), API-217#default, API-228#403(`cross_site`), API-228#default, API-238#403(`cross_site`), API-238#404(`not_found`), API-238#default, API-214#default, API-215#403(`cross_site`), API-215#default |

비어 있음은 #default-character가 맡아요. 오래된 데이터: 다른 기기에서 바꾼 이름·캐릭터는 화면이 다시 보일 때 다시 읽어 맞춰요. 숫자 예시는 지어낸 값이에요.

## SCR-166 입혀 보기

Purpose: 만든 캐릭터를 적용하기 전에 글 대화 화면과 통화 화면에 입힌 모습을 보고, 적용하거나 나중으로 미뤄요. 미리 보기는 아무것도 저장하지 않아요. (FL-173)

| Data | Source |
| --- | --- |
| 입힌 이름, 얼굴 그림, 견본 대화, 통화 첫마디 | API-227 |
| 얼굴 그림 | API-242 |
| 지금 쓰는 캐릭터 | API-216 |

| Action | Result | Failure |
| --- | --- | --- |
| '대화'·'통화' 탭 | 미리 보기 틀이 바뀜(#chat, #call) | 없음 |
| 표정 누르기(#call) | 얼굴이 그 표정으로 바뀜 | 없음 |
| 이 모습으로 할래(적용) | API-228 `{characterId}` → 200 → SCR-107과 #applied 띠 | 409 → #not-ready |
| 나중에 할래 | SCR-165(캐릭터는 보관됨) | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-166#loading | 탭 둘과 미리 보기 틀 자리에 회색 | |
| SCR-166#chat | 위 띠 '미리 보기야. 아직 바뀐 건 없어'. 글 대화 모양의 틀: 머리말에 캐릭터 이름과 얼굴, 견본 말풍선(`chatSample`, 정해 둔 견본 말). 아래 '이 모습으로 할래'와 '나중에 할래', 작은 글 '바꿔도 대화랑 기억은 그대로야. 먼저 보내는 그림 얘기는 글로만 와' | API-227#200 |
| SCR-166#call | 통화 화면 모양의 틀: 얼굴 원(`size.face-call`, 표정 `smile`), 통화 첫마디(`callLine`) 한 줄, 표정 여섯 장 작은 줄. 소리는 나지 않고 작은 글 '목소리는 통화 목소리에서 골라' | API-227#200 |
| SCR-166#applying | 버튼 꺼짐과 '바꾸는 중이야…' | |
| SCR-166#applied | 글 대화(SCR-107)로 가고 띠 '이제 {이름}로 바뀌었어! 대화랑 기억은 그대로야' | API-228#200 |
| SCR-166#wearing | 적용 버튼 대신 '지금 쓰는 중이야'와 '내 마롱이로' | API-216#200(`character.id`가 같음) |
| SCR-166#not-ready | '아직 다 만들지 못한 캐릭터야. 이어서 만들어 줄래?'와 '이어서 만들기'(그 단계 화면) | API-227#409(`not_ready`), API-228#409(`not_ready`) |
| SCR-166#error | 공통 규칙 | API-227#404(`not_found`), API-227#default, API-228#403(`cross_site`), API-228#404(`not_found`), API-228#default, API-216#default |

비어 있음은 없어요(다 만든 캐릭터에서만 열려요, 아니면 #not-ready). 오래된 데이터: 다른 기기에서 지운 캐릭터면 404로 공통 규칙이에요.

## SCR-167 목소리 고르기

Purpose: 통화 목소리 목록에서 견본을 듣고 하나를 골라요. 고른 목소리는 다음 통화부터 쓰여요. (FL-174)

| Data | Source |
| --- | --- |
| 목소리 목록(이름, 이름표, 견본 주소, 기본 여부) | API-218 |
| 지금 고른 목소리 | API-216 |

| Action | Result | Failure |
| --- | --- | --- |
| 견본 듣기(줄의 ▶) | `<audio>`로 그 줄의 견본을 틀고(한 번에 하나) 다시 누르면 멈춤 | 소리 실패 → #sample-error |
| 줄 고르기(라디오) | API-217 `{voice}` → 200 → #saved | 400 `voice_unknown` → #unknown |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-167#loading | 줄 여덟 개 자리에 회색 | |
| SCR-167#normal | 줄마다 이름표, ▶, 고른 줄에 ✓(`role="radio"`, `aria-checked`). 기본 목소리 줄에 '기본'. 위에 '{이름}의 통화 목소리를 골라 줘' | API-218#200, API-216#200 |
| SCR-167#playing | 그 줄의 ▶가 ■로 바뀌고 다 틀면 돌아옴. 다른 줄을 틀면 앞 소리는 멈춤 | |
| SCR-167#no-sample | 그 줄의 ▶가 꺼지고 작은 글 '견본은 아직 없어'. 고를 수는 있음 | API-218#200(`sampleUrl=null`) |
| SCR-167#single | 줄이 하나이고 아래 '지금은 목소리가 하나야. 더 생기면 여기서 고를 수 있어' | API-218#200(`voices` 1개) |
| SCR-167#saving | 줄 그룹이 막힘 | |
| SCR-167#saved | 띠 '다음 통화부터 이 목소리야'(3초). 통화 중이어도 그 통화는 바뀌지 않음 | API-217#200 |
| SCR-167#unknown | 고르기 전 값으로 되돌리고 목록을 다시 부름. '그 목소리는 지금 고를 수 없어. 다른 걸 골라 줄래?' | API-217#400(`voice_unknown`) |
| SCR-167#sample-error | 그 줄 아래 '지금은 견본을 못 틀었어' | (`<audio>` 오류) |
| SCR-167#error | 공통 규칙 | API-218#default, API-216#default, API-217#400(`invalid_input`), API-217#403(`cross_site`), API-217#default |

비어 있음은 #single이 맡아요(목록에는 기본 목소리가 늘 있어요, REQ-467). 오래된 데이터: 목록에서 빠진 목소리를 고르면 #unknown이에요.

## SCR-168 친구

Purpose: 내 친구 코드를 보여 주고, 상대의 코드로 요청을 보내고, 받은 요청에 답하고, 가까운 사이와 공유를 바꾸고, 친구를 끊어요. (FL-175)

| Data | Source |
| --- | --- |
| 친구 목록(이름, 가까운 사이, 내가 켠 값), 받은 요청, 보낸 요청 | API-230 |
| 내 친구 코드, 공유 켬·끔 | API-216 |

| Action | Result | Failure |
| --- | --- | --- |
| 내 코드 복사 | 클립보드에 넣고 '복사했어' | 복사 실패 → '코드를 길게 눌러 복사해 줘' |
| 요청 보내기(코드 6자, 화면이 대문자로 바꾸고 모양을 먼저 확인) | API-231 → 201 → #outgoing | 아래 상태 |
| 받은 요청의 '수락'·'거절' | API-232 `{action}` → 200 → #accepted, #declined | 404 → #gone |
| '가까운 사이' 스위치(친구 줄) | API-233 `{close}` → 200 → #close-mine 또는 #close | 공통 규칙, 스위치는 되돌림 |
| 친구 끊기(친구 줄의 ⋯) | 확인 줄(#ending-confirm) → API-239 → 204 → #ended | 공통 규칙 |
| '내 얘기 나누기' 스위치 | API-217 `{share}` → 200 | 공통 규칙, 스위치는 되돌림 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-168#loading | 코드 카드와 목록 줄 자리에 회색 | |
| SCR-168#normal | 카드 '내 친구 코드': 큰 글자 6자와 '복사'. 칸 '친구 코드로 요청 보내기'와 '보내기'. 그룹 '받은 요청', '친구'(이름과 가까운 사이 스위치), '보낸 요청'. 맨 아래 스위치 '내 얘기 나누기'와 작은 글 '{이름}가 친구들한테 내 가벼운 근황을 얘기해도 돼' | API-230#200, API-216#200 |
| SCR-168#empty | 친구도 요청도 없으면 '아직 친구가 없어. 친구 코드를 서로 알려 주면 {이름}가 둘 다 아는 친구가 돼' | API-230#200(목록 셋이 모두 비어 있음) |
| SCR-168#incoming | 받은 요청 줄 '{친구 이름}가 친구 요청을 보냈어'와 '수락'·'거절' | API-230#200(`incoming`) |
| SCR-168#outgoing | 보낸 요청 줄 '{친구 이름}한테 요청을 보냈어. 수락을 기다리는 중이야'. 코드 칸은 비움 | API-231#201, API-230#200(`outgoing`) |
| SCR-168#sending | 코드 칸과 '보내기' 꺼짐 | |
| SCR-168#code-invalid | 칸 아래 '친구 코드는 글자와 숫자 6자야. 다시 확인해 줄래?' | API-231#400(`invalid_input`) |
| SCR-168#self | 칸 아래 '이건 내 코드야. 친구의 코드를 넣어 줘' | API-231#400(`self_request`) |
| SCR-168#code-not-found | 칸 아래 '이 코드를 가진 친구를 찾지 못했어. 코드를 다시 확인해 줄래?' | API-231#404(`code_not_found`) |
| SCR-168#already | 칸 아래 '이미 친구야!' | API-231#409(`already_friends`) |
| SCR-168#request-exists | 칸 아래 '이미 요청이 오가는 중이야. 받은 요청이나 보낸 요청을 봐 줘' | API-231#409(`request_exists`) |
| SCR-168#request-limit | 칸 아래 '오늘은 요청을 많이 보냈어(하루 10번). 내일 다시 해 줘', '보내기' 꺼짐 | API-231#429(`request_limit`) |
| SCR-168#accepted | 요청 줄이 친구 목록으로 옮겨지고 띠 '{친구 이름}랑 친구가 됐어! 이제 {이름}가 둘 다 아는 친구로 얘기해' | API-232#200 |
| SCR-168#declined | 요청 줄이 사라지고 띠 '거절했어' | API-232#200 |
| SCR-168#gone | 띠 '이 요청은 이제 없어'와 목록 다시 불러오기 | API-232#404(`not_found`) |
| SCR-168#close-mine | 그 줄 아래 '나는 켰어. {친구 이름}도 켜면 가까운 사이가 돼' | API-233#200(`closeMine=true`, `close=false`), API-230#200 |
| SCR-168#close | 그 줄에 '가까운 사이' 표시와 '요즘 지내는 얘기까지 나눠' | API-233#200(`close=true`), API-230#200 |
| SCR-168#ending-confirm | 확인 줄 '{친구 이름}랑 친구를 끊을까? {이름}가 더는 서로의 얘기를 하지 않아'와 '끊기'·'그만두기' | |
| SCR-168#ended | 그 줄이 사라지고 띠 '친구를 끊었어' | API-239#204 |
| SCR-168#share-off | '내 얘기 나누기'가 꺼져 있고 목록 위 띠 '지금은 내 얘기를 친구들한테 하지 않아' | API-216#200(`share=false`), API-217#200 |
| SCR-168#error | 공통 규칙 | API-230#default, API-216#default, API-231#403(`cross_site`), API-231#default, API-232#400(`invalid_input`), API-232#403(`cross_site`), API-232#default, API-233#400(`invalid_input`), API-233#403(`cross_site`), API-233#404(`not_found`), API-233#default, API-239#403(`cross_site`), API-239#404(`not_found`), API-239#default, API-217#403(`cross_site`), API-217#default |

오래된 데이터: 상대가 수락·거절·끊기를 하면 화면이 다시 보일 때 다시 읽어 맞추고, 그 사이에 누른 요청은 #gone이 돼요.

## SCR-169 관리자

초대 링크 날짜와 가입한 사람의 한도 표시 및 변경. 바뀜 → [usage-limit.md](usage-limit.md) SCR-169.

Purpose: 동희님이 초대 링크를 만들고, 가입한 사람과 로그인 수·오늘 쓴 양을 보고, 로그인을 끊고, 티켓을 넣어요. Cloudflare Access 뒤에 있어요. (FL-169, FL-170, FL-171, FL-177)

| Data | Source |
| --- | --- |
| 초대 링크 목록(종류, 메모, 상태, 끝나는 때, 쓴 사람). 토큰과 주소는 없음 | API-240 |
| 가입한 사람 목록(이름, 마롱이 이름, 로그인 수, 마지막으로 쓴 때, 티켓, 오늘 쓴 양) | API-236(`members`) |
| 아직 연결하지 않은 기존 계정(이름만, `link` 링크를 만들 때 고르는 목록) | API-236(`unlinked`) |
| 새 링크의 주소와 끝나는 때(한 번만) | API-235 |
| 티켓 잔액 | API-237 |

| Action | Result | Failure |
| --- | --- | --- |
| 초대 링크 만들기 | 종류 칩(`join` 새 사람 · `link` 기존 계정 연결 · `relogin` 다시 로그인), `link`는 아직 연결하지 않은 기존 계정(`unlinked`)과 가입한 사람(`members`)에서, `relogin`은 가입한 사람(`members`)에서 고르기, 메모(40자, 선택) → API-235 → 201 → #created | 400 → #invite-invalid, 404 → #member-missing |
| 주소 복사 | 클립보드에 넣고 '복사했어요' | 복사 실패 → 주소 글자를 골라 둠 |
| 로그인 끊기(사람 줄) | 확인 줄(#revoke-confirm) → API-241 → 204 → #revoked | 공통 규칙 |
| 티켓 넣기(사람 줄, 1\~1000) | API-237 `{add}` → 200 → #ticket-added | 400 → #ticket-invalid |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-169#loading | 그룹 둘(초대 링크, 가입한 사람)의 줄 자리에 회색 | |
| SCR-169#normal | 그룹 '초대 링크': '새 링크 만들기'와 목록(줄마다 종류, 메모, 상태 '열림'·'씀(쓴 사람)'·'기간 지남', 끝나는 때). 그룹 '가입한 사람': 줄마다 이름, 마롱이 이름, 로그인 수, 마지막으로 쓴 때, 오늘 쓴 양, 티켓, '로그인 끊기'·'티켓 넣기' | API-240#200, API-236#200 |
| SCR-169#invites-empty | 초대 링크 그룹에 '만든 초대 링크가 없어요' | API-240#200(`invites` 빈 목록) |
| SCR-169#members-empty | 가입한 사람 그룹에 '아직 가입한 사람이 없어요' | API-236#200(`members` 빈 목록) |
| SCR-169#creating | 만들기 칸이 열림: 종류 칩, 사람 고르기(`link`·`relogin`), 메모, '만들기' | |
| SCR-169#created | 새 주소와 '복사', '이 주소는 지금만 보여요. 복사해서 직접 전해 주세요', 끝나는 때. 칸을 닫으면 주소는 다시 볼 수 없음 | API-235#201 |
| SCR-169#invite-invalid | 그 칸 아래 '입력을 확인해 주세요'(예: `link`인데 사람을 고르지 않음, 메모 40자 넘음) | API-235#400(`invalid_input`) |
| SCR-169#member-missing | '그 사람을 찾을 수 없어요. 목록을 다시 불러올게요' | API-235#404(`not_found`) |
| SCR-169#revoke-confirm | 확인 줄 '이 사람의 모든 기기 로그인을 끊어요. 다시 들어오려면 다시 로그인 링크가 필요해요'와 '끊기'·'그만두기' | |
| SCR-169#revoked | 그 줄의 로그인 수가 0이 되고 띠 '로그인을 끊었어요' | API-241#204 |
| SCR-169#ticket | 숫자 칸(1\~1000)과 '넣기' | |
| SCR-169#ticket-invalid | 칸 아래 '1부터 1000까지 넣어 주세요' | API-237#400(`invalid_input`) |
| SCR-169#ticket-added | 그 줄의 티켓이 새 잔액이 되고 띠 '티켓을 넣었어요' | API-237#200 |
| SCR-169#error | 공통 규칙('잠깐 문제가 생겼어요. 다시 해 볼까요?') | API-240#default, API-236#default, API-235#403(`cross_site`), API-235#default, API-241#403(`cross_site`), API-241#404(`not_found`), API-241#default, API-237#403(`cross_site`), API-237#404(`not_found`), API-237#default |

권한: Access를 지나지 못한 사람에게는 Cloudflare의 로그인 화면이 보이고 이 화면은 열리지 않아요. 대화 글, 기억, 초대 토큰, 로그인 토큰은 이 화면에 없어요. 오래된 데이터: 링크가 쓰였는지와 로그인 수는 화면이 다시 보일 때 다시 읽어요.

## SCR-170 캐릭터 만들기(사진)

Purpose: 강아지인지 고양이인지 고르고 사진 1\~3장을 올려 캐릭터 만들기를 시작해요. SCR-142에서 살아 있는 아이·추억 고르기, 국외 이전 동의, 결제 안내를 뺐어요. (FL-172)

| Data | Source |
| --- | --- |
| 캐릭터 수(상한 3)와 만들던 캐릭터 | API-229 |
| 새 캐릭터(id, 단계 `photos`) | API-219 |

| Action | Result | Failure |
| --- | --- | --- |
| '강아지'·'고양이' 고르기 | 칩 하나가 골라짐(`kind` `dog`·`cat`). 고르기 전에는 사진 칸이 흐림 | 없음 |
| 사진 고르기 | `<input type="file" accept="image/*" multiple>`, 3장까지. 화면이 긴 변 1600px, JPEG 0.9로 다시 그려(EXIF가 빠짐) 칸에 보여 줌 | 4장째는 받지 않고 '사진은 3장까지야' |
| 사진 빼기(칸의 ×) | 그 칸이 비어요 | 없음 |
| 올리기 | API-219 `{kind}` → 201 → API-220(multipart) → 202 → SCR-171. 사진 올리기만 실패하면 같은 캐릭터 id로 API-220만 다시 불러요 | 아래 상태 |
| 이어서 하기(만들던 캐릭터 카드) | 그 단계 화면. 단계가 `photos`면 이 화면에서 그 id로 API-220 | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-170#loading | 칩 둘과 사진 칸 셋 자리에 회색 | |
| SCR-170#normal | 질문 '누구를 그려 줄까?'와 칩 둘, 사진 칸 셋(첫 칸에 '정면 얼굴'), 안내 '정면 얼굴, 귀와 무늬가 보이는 사진, 전신 한 장이면 가장 닮아'와 '사람이 같이 찍혔으면 얼굴은 가려서 써. 원본 사진은 저장하지 않아', '올리기'(칩과 사진 한 장이 있어야 켜짐) | API-229#200 |
| SCR-170#in-progress | #normal 맨 위에 카드 '만들던 캐릭터가 있어. 이어서 할래?' | API-229#200(`status=draft`) |
| SCR-170#selected | 고른 사진이 칸에 들어가고 ×가 붙음 | |
| SCR-170#uploading | 올리는 막대와 '사진을 올리는 중이야', 버튼 꺼짐 | |
| SCR-170#photo-error | 그 사진 칸에 `danger` 테두리와 '2번째 사진을 열 수 없어. JPEG·PNG·WebP, 8MB 이하로 다시 골라 줄래?' 다른 사진은 남음 | API-220#400(`photo_invalid`) |
| SCR-170#check-down | '지금은 사진을 살펴볼 수가 없어. 조금 있다가 다시 올려 줘'와 '다시 올리기'. 고른 사진은 남음 | API-220#503(`check_unavailable`) |
| SCR-170#too-large | '사진이 너무 커. 다른 사진으로 골라 줄래?' | API-220#413 |
| SCR-170#limit | 사진 칸 대신 '캐릭터는 3개까지 둘 수 있어. 하나를 지우면 새로 만들 수 있어'와 '내 마롱이로' | API-229#200(`characters` 3개), API-219#409(`too_many_characters`) |
| SCR-170#budget | '이번 달 그림은 여기까지야. 다음 달에 다시 만들 수 있어', '올리기' 꺼짐 | API-219#409(`image_budget`) |
| SCR-170#busy | 이미 사진을 살펴보는 중이면 SCR-171#analyzing으로 감 | API-220#409(`job_running`) |
| SCR-170#stale | 사진 단계가 지난 캐릭터면 API-221을 다시 불러 맞는 단계 화면으로 감 | API-220#409(`wrong_stage`) |
| SCR-170#error | 공통 규칙. 고른 사진은 칸에 남김 | API-229#default, API-219#400(`invalid_input`), API-219#403(`cross_site`), API-219#default, API-220#403(`cross_site`), API-220#404(`not_found`), API-220#default |

비어 있음은 #normal의 빈 사진 칸이에요. 오래된 데이터는 없어요(올리면 서버가 다시 셈).

## SCR-171 특징표 고치기

Purpose: 서버가 사진에서 만든 특징표(종·털 색·무늬·귀·눈·체격·털 길이)를 고치고, 몸 템플릿과 말투 한 줄을 정해 확정해요. SCR-143과 같고, 몸 템플릿 고르기와 말투 한 줄이 늘었어요. (FL-172)

| Data | Source |
| --- | --- |
| 단계, 특징표, 몸 템플릿, 말투, 작업 상태와 실패 이유 | API-221 |

| Action | Result | Failure |
| --- | --- | --- |
| 칸 고치기 | 칩을 누르거나 글을 쓰면 화면의 값만 바뀜. 서버에는 확정할 때 한 번에 보냄 | 화면이 길이를 먼저 막음 |
| 몸 템플릿 고르기 | 칩 다섯(작은 강아지 `dog_small`, 큰 강아지 `dog_large`, 허리가 긴 강아지 `dog_long`, 고양이 `cat`, 둥근 고양이 `cat_round`). 서버가 고른 값이 먼저 골라져 있음 | 없음 |
| 말투 한 줄(선택, 60자) | 예: '느긋하고 애교가 많아' | 없음 |
| 이대로 그려 줘 | API-222 `{traits, template, tone}` → 200(단계 `preview`) → SCR-172 | 400 → #invalid, 409 → #stale, #analyzing |
| 사진 다시 고르기(#refused, #failed) | SCR-170 | 없음 |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-171#analyzing | '사진을 살펴보는 중이야. 30초쯤 걸려'와 작은 움직임. 2초마다 API-221 | API-220#202, API-221#200(`stage=photos`, `job.step=traits`, `job.state` `queued`·`running`), API-222#409(`job_running`) |
| SCR-171#loading | 칸 제목 열한 줄과 칩 자리에 회색 | |
| SCR-171#normal | 칸마다 이름과 값: 종(강아지·고양이), 품종 추정(30자), 털 색 1\~3개(칩 8개), 무늬(칩 7개)와 무늬 설명(60자, '사진에서 보는 방향으로 적어 줘'), 귀 모양, 눈 색, 체격, 털 길이, 특징(60자), 몸 템플릿, 말투 한 줄. 아래 '이대로 그려 줘' | API-221#200(`stage=traits`, 또는 `stage=preview`이고 주소에 `edit=1`) |
| SCR-171#saving | 버튼 꺼짐과 '저장하는 중이야…' | |
| SCR-171#invalid | 그 칸 아래 '다시 한번 확인해 줄래?'와 그 칸의 규칙, 쓴 값 남김 | API-222#400(`invalid_input`) |
| SCR-171#refused | '강아지나 고양이를 찾지 못했어. 한 아이만 잘 보이는 사진으로 다시 골라 줄래?'와 '사진 다시 고르기' | API-221#200(`job.state=failed`, `job.error` `model_refused`·`check_failed`) |
| SCR-171#failed | '사진을 살펴보다가 멈췄어. 조금 있다가 다시 해 볼래?'와 '사진 다시 고르기' | API-221#200(`job.state=failed`, `job.error` `model_error`·`timeout`) |
| SCR-171#budget | '이번 달 그림은 여기까지야. 다음 달에 이어서 만들 수 있어. 지금까지 한 건 그대로 둘게' | API-221#200(`job.state=failed`, `job.error=budget`) |
| SCR-171#stale | 다른 단계면 그 단계 화면으로 감. 미리 보기 단계에서 '특징표 다시 고칠래'로 온 경우(`edit=1`)는 #normal이에요 | API-221#200(`stage`가 `photos`·`traits`가 아니고, `preview`이면서 `edit=1`인 경우도 아님), API-222#409(`wrong_stage`) |
| SCR-171#error | 공통 규칙. 고친 값은 화면에 남김 | API-221#404(`not_found`), API-221#default, API-222#403(`cross_site`), API-222#404(`not_found`), API-222#default |

비어 있음은 #analyzing이 맡아요(특징표가 아직 없음).

## SCR-172 미리 보기

Purpose: 미리 보기 한 장으로 닮았는지 보고, 마음에 들면 후보 4장 그리기로 넘어가요. SCR-144에서 결제·만들기권·본인인증·하루 3장 제한·30일 뒤 지움을 뺐어요. (FL-172)

| Data | Source |
| --- | --- |
| 단계, 미리 보기 그림이 있는지, 작업 상태와 실패 이유 | API-221 |
| 미리 보기 그림 | API-242(`preview`) |

| Action | Result | Failure |
| --- | --- | --- |
| 미리 보기 그려 줘 · 다시 그려 줘 | API-223 → 202 → #drawing | 409 `image_budget` → #budget, `job_running` → #drawing, `wrong_stage` → #stale |
| 특징표 다시 고칠래 | SCR-171(주소에 `edit=1`) | 없음 |
| 후보 그려 줘(미리 보기가 있을 때) | API-224 → 202 → SCR-173#drawing | 409 `image_budget` → #budget, `job_running` → SCR-173#drawing, `wrong_stage` → #stale |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-172#loading | 정사각 그림 칸과 버튼 자리에 회색 | |
| SCR-172#ready | 빈 그림 칸에 '먼저 한 장만 그려서 닮았는지 볼게'와 '미리 보기 그려 줘' | API-221#200(`stage=preview`, `images.preview` 없음) |
| SCR-172#drawing | 그림 칸에 '그리는 중이야. 1분쯤 걸려. 화면을 닫아도 돼'와 움직임. 2초마다 API-221 | API-223#202, API-223#409(`job_running`), API-221#200(`job.step=preview`, `job.state` `queued`·`running`) |
| SCR-172#normal | 미리 보기 그림(1:1), '닮았어? 이 모습으로 후보 4장을 그려 줄게', '후보 그려 줘', '다시 그려 줘', '특징표 다시 고칠래' | API-221#200(`stage=preview`, `images.preview` 있음) |
| SCR-172#preview-failed | '미리 보기를 그리지 못했어. 다시 해 볼래?'와 '다시 그려 줘' | API-221#200(`job.step=preview`, `job.state=failed`, `job.error` `model_error`·`model_refused`·`timeout`·`check_failed`) |
| SCR-172#budget | '이번 달 그림은 여기까지야. 다음 달에 이어서 만들 수 있어. 지금까지 한 건 그대로 둘게', 그리기 버튼 꺼짐 | API-223#409(`image_budget`), API-224#409(`image_budget`), API-221#200(`job.error=budget`) |
| SCR-172#stale | 후보 단계 뒤면 그 단계 화면으로 감 | API-221#200(`stage`가 `preview`가 아님), API-223#409(`wrong_stage`), API-224#409(`wrong_stage`) |
| SCR-172#error | 공통 규칙 | API-221#404(`not_found`), API-221#default, API-223#403(`cross_site`), API-223#404(`not_found`), API-223#default, API-224#403(`cross_site`), API-224#404(`not_found`), API-224#default |

비어 있음은 #ready가 맡아요.

## SCR-173 후보 고르기

Purpose: 그림 후보 4장 가운데 하나를 정면 그림으로 고르고, 표정 여섯 장이 그려지는 동안 기다려요. SCR-145에서 결제 취소·주문 내역·운영자 처리·웹 푸시를 뺐어요. (FL-172)

| Data | Source |
| --- | --- |
| 단계, 후보 그림 자리(`candidate_1`\~`candidate_4`), 남은 다시 그리기, 작업 상태와 실패 이유 | API-221 |
| 후보 그림 | API-242 |

| Action | Result | Failure |
| --- | --- | --- |
| 후보 누르기 | 그 후보가 골라짐(테두리 `accent`와 ✓). 한 번 더 누르면 크게 보기 | 없음 |
| 이 그림으로 할래 | API-225 `{slot}` → 202 → #sheet | 400 → #invalid, 409 `wrong_stage` → #stale, `job_running` → #sheet |
| 다시 그려 줘 | 확인 줄(#redraw-confirm) → API-224 → 202 → #drawing-more | 409 `no_regen_left` → #limit, `image_budget` → #budget, `job_running` → #drawing-more |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-173#loading | 2×2 그림 칸 자리에 회색 | |
| SCR-173#drawing | '후보 4장을 그리는 중이야. 몇 분 걸려. 화면을 닫아도 돼'와 움직임. 앱에서는 '다 되면 알림으로 알려 줄게'가 한 줄 더 보임. 5초마다 API-221 | API-224#202, API-221#200(`stage=candidates`, `job.step=candidates`, `job.state` `queued`·`running`) |
| SCR-173#normal | 후보 2×2, '이 그림으로 할래'(고르면 켜짐), '다시 그려 줘 · 2번 남음' | API-221#200(`stage=candidates`, 후보 그림 4장) |
| SCR-173#picked | 고른 후보에 테두리와 ✓, '이 그림으로 할래'가 켜짐 | |
| SCR-173#redraw-confirm | 확인 줄 '다시 그리면 지금 후보 4장은 새 그림으로 바뀌어. 다시 그릴까?'와 '다시 그려 줘'·'그만두기' | |
| SCR-173#drawing-more | 후보 칸 네 개가 그리는 중으로 바뀌고 '새로 그리는 중이야' | API-224#202, API-224#409(`job_running`) |
| SCR-173#limit | '다시 그려 줘'가 꺼지고 '다시 그리기는 다 썼어. 이 중에서 골라 줘' | API-221#200(`regenLeft=0`), API-224#409(`no_regen_left`) |
| SCR-173#budget | '이번 달 그림은 여기까지야. 지금 후보에서 고르거나 다음 달에 이어서 해 줘', '다시 그려 줘' 꺼짐 | API-224#409(`image_budget`), API-221#200(`job.error=budget`) |
| SCR-173#sheet | 고른 그림을 크게 두고 '표정 여섯 장을 그리는 중이야. 다 되면 이름을 지어 줘'. 5초마다 API-221, 끝나면 SCR-174 | API-225#202, API-225#409(`job_running`), API-221#200(`stage=sheet`) |
| SCR-173#failed | '후보를 그리지 못했어. 다시 해 볼래?'와 '다시 그려 줘' | API-221#200(`job.step=candidates`, `job.state=failed`, `job.error` `model_error`·`model_refused`·`timeout`·`check_failed`) |
| SCR-173#sheet-failed | '표정을 그리다가 멈췄어. 다시 해 볼래?'와 '다시 해 볼게'(같은 후보로 API-225) | API-221#200(`job.step=sheet`, `job.state=failed`) |
| SCR-173#invalid | '후보를 다시 골라 줄래?' | API-225#400(`invalid_input`) |
| SCR-173#stale | 단계가 `name`이면 SCR-174, `done`이면 SCR-166, 그 앞 단계면 그 화면으로 감 | API-221#200(`stage`), API-225#409(`wrong_stage`), API-224#409(`wrong_stage`) |
| SCR-173#error | 공통 규칙 | API-221#404(`not_found`), API-221#default, API-224#403(`cross_site`), API-224#404(`not_found`), API-224#default, API-225#403(`cross_site`), API-225#404(`not_found`), API-225#default |

비어 있음은 #drawing이 맡아요.

## SCR-174 이름 짓기

Purpose: 다 그린 캐릭터의 정면 그림과 표정 여섯 장을 보고 이름을 지어요. 끝나면 입혀 보기로 가요. SCR-146에서 아이 소개 칸 네 줄과 첫 인사를 뺐어요(말투 한 줄은 SCR-171에서 정해요). (FL-172)

| Data | Source |
| --- | --- |
| 단계, 정면 그림과 표정 그림 자리 | API-221 |
| 정면 그림(`front`)과 표정 그림 여섯 장 | API-242 |

| Action | Result | Failure |
| --- | --- | --- |
| 이름 넣기(1\~12자) | 화면이 앞뒤 공백을 빼고 길이를 먼저 막음 | 400 → #invalid |
| 다 됐어 | API-226 `{name}` → 200(캐릭터 `ready`) → SCR-166 | 409 → #stale |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-174#loading | 정면 그림 칸과 이름 칸 자리에 회색 | |
| SCR-174#normal | 정면 그림, 표정 여섯 장 작은 줄, '이름을 지어 줘', 이름 칸(글자 수), 작은 글 '적용하면 이 이름이 마롱이 이름이 돼', '다 됐어'(이름이 있어야 켜짐). 'AI가 만든 캐릭터' 띠는 없어요(D91) | API-221#200(`stage=name`) |
| SCR-174#saving | 버튼 꺼짐과 '마무리하는 중이야…' | |
| SCR-174#invalid | 칸 아래 '이름은 1\~12자로 적어 줘', 쓴 값 남김 | API-226#400(`invalid_input`) |
| SCR-174#stale | 단계가 `done`이면 SCR-166, 그 밖은 맞는 단계 화면으로 감 | API-221#200(`stage`가 `name`이 아님), API-226#409(`wrong_stage`) |
| SCR-174#error | 공통 규칙. 쓴 이름은 남김 | API-221#404(`not_found`), API-221#default, API-226#403(`cross_site`), API-226#404(`not_found`), API-226#default |

비어 있음은 없어요: 이 화면은 표정 그림이 다 있을 때만 열려요(아니면 #stale).

## 14. 웹(아이폰 사파리)에서 다른 것

앱과 웹은 같은 페이지예요(SPEC-396). 웹에서 가입, 글 대화, 통화, 성향 화면, 캐릭터·이름·목소리 설정, 친구, 구글 캘린더 연결이 돼요(REQ-460). 다른 것만 적어요.

| 항목 | 안드로이드 앱 | 웹(아이폰 사파리, 다른 브라우저) | 근거 |
| --- | --- | --- | --- |
| 알림 | 앱 알림(SCR-108), 제목은 그 사람의 마롱이 이름 | 없어요. 먼저 한 말은 방에 남고 글 대화를 열면 안 읽은 말로 보여요(15절 SCR-107#unread) | REQ-462, D92 |
| 전화 벨 | 벨 화면(SCR-110)과 전화 알림(SCR-111) | 없어요. 약속 시각 앞뒤에 글 대화를 열면 '받기' 띠가 보여요(15절 SCR-107#ring-pending) | REQ-464 |
| 통화 | 화면을 꺼도 이어짐 | 화면을 켜 둔 동안만 이어져요. 다른 앱으로 가면 끊길 수 있어요 | 제안 10절 |
| 만들기 작업이 끝남 | 앱 알림 | 알림 없음. 다시 열면 그 단계 화면 | 공통 규칙 '긴 일' |
| 자동 업데이트 줄(SCR-109) | 보임 | 숨김 | REQ-326 |
| 앱 받기(SCR-163#done) | 해당 없음(앱에서는 가입 링크를 열지 않음) | 안드로이드 브라우저에만 보이고 아이폰에는 없어요 | 제안 5절 |
| 홈 화면에 추가 | 해당 없음 | 내 마롱이(SCR-165#web-ios)와 가입 뒤(SCR-163#done)에 한 줄: '아이폰에서는 공유 버튼을 누르고 홈 화면에 추가를 고르면 앱처럼 열 수 있어. 알림과 전화 벨은 안드로이드 앱에서만 와'. 홈 화면에서 연 경우(`display-mode: standalone`)에는 둘째 문장만 보여요 | REQ-461 |
| 사진 고르기(SCR-170) | 앱 0.3.0에서 동작을 확인(TASK-408) | 사파리의 사진 고르기. HEIC도 화면이 JPEG로 다시 그려 보내고, 못 그리면 SCR-170#photo-error | SPEC-378 |
| 로그인 유지 | 쿠키 90일, 쓸 때마다 늘어남 | 같음. 아이폰 사파리에서 실제로 얼마나 유지되는지는 실기기에서 봐요([12 시험](../12-qa/unified.md) 기기 확인 '가') | REQ-434 |

서비스 워커와 웹 푸시는 넣지 않아요(SPEC-396).

## 15. 다른 화면에서 바뀌는 곳

모든 화면: 로그인이 없으면(401 `login_required`) Access 로그인으로 새로 불러오는 대신 로그인(SCR-164)으로 가요. 통화 중에 로그인이 풀리면 지금 규칙처럼 통화는 끊지 않고, 끝난 뒤 '다시 들어가기'가 SCR-164로 가요.

| 화면 | 바뀌는 것 | 근거 |
| --- | --- | --- |
| SCR-107 글 대화([app-chat.md](../app-chat.md)) | 머리말의 '마롱이' 글이 `botName`, 머리말과 마롱이 말풍선 옆 얼굴이 쓰는 캐릭터의 정면 그림(없으면 지금 얼굴)이에요. 열 때와 화면이 다시 보일 때 API-216을 한 번 불러요. 빈 목록 글은 '{이름}한테 먼저 말 걸어 볼래?'예요 | REQ-441, SPEC-377 |
| SCR-107 글 대화 | 상태가 늘어요: #unread, #ring-pending, #daily-limit(아래 표). '쓸 수 없는 계정'(`not_allowed`)과 디스코드 DM 연결 안내(`no_dm`) 상태는 없어져요 | FL-176, FL-177, REQ-439 |
| SCR-109 알림 상태(글 대화 메뉴) | 줄 '내 마롱이'(SCR-165)와 '친구'(SCR-168)가 늘어요. 머리 버튼은 지금 네 개(전화·알림·일기장·나)로 360px 한 줄이 차서 메뉴에 둬요. 알림이 꺼졌거나 오래 안 연 폰의 글은 '디스코드로 받는 중' 대신 '알림이 꺼져 있어. 먼저 한 말은 여기 남겨 둘게'이고, 브라우저는 '알림은 안드로이드 앱에서 받을 수 있어. 여기서는 열었을 때 밀린 말을 보여 줄게'예요 | FL-176, SPEC-383, D92 |
| SCR-112 글 대화 창(앱) | 화면은 웹 소유라 SCR-107을 그대로 따라요. 창 안의 Access 로그인 화면 대신 로그인(SCR-164)이 창 안에 떠요(앱 0.3.0) | TASK-408 |
| SCR-108·111 앱 알림·전화 알림 | 제목 '마롱이'가 그 사람의 `botName`이에요. 알림 채널 이름('마롱이 톡', '마롱이 전화')과 앱 이름은 그대로예요 | REQ-441 |
| SCR-001 통화 홈([SCR-001.md](SCR-001.md)) | 인사 줄이 '{내 이름}, {이름}한테 전화할래?', 얼굴이 쓰는 캐릭터의 정면 그림(없으면 지금 얼굴)이에요. 상태가 늘어요: #call-busy, #calls-full, #daily-limit(아래 표). #permission의 403 '이 계정으로는 마롱이랑 통화할 수 없어'는 그대로 있어요(통화 계정이 꺼진 사람, SPEC-374) | SPEC-386, SPEC-394 |
| SCR-002 통화 중([SCR-002.md](SCR-002.md)) | 글의 '마롱이'가 `botName`이에요('{이름}한테 거는 중…'). 캐릭터를 쓰면 얼굴이 그 캐릭터의 표정 여섯 장이고(아래 표정 표), 기본 마롱이는 지금 21장 그대로예요. 상태 #waiting이 늘어요(아래 표) | FL-178, SPEC-389, 제안 7절 |
| SCR-113 일기장 한 날, SCR-119 듣기 시험 | #permission의 `no_dm` 안내('디스코드 DM에서 마롱이한테 먼저 말 걸어 줘')와 403 `not_allowed` 안내가 없어져요. 401은 SCR-164로 가요. 아침 일기 말의 주소는 글 대화에만 붙어요(디스코드 DM 없음) | REQ-439, TASK-410 |
| SCR-120\~122 성향 맞춤 | 문 규칙의 Access 확인과 `call.callers`로 친구를 찾는 부분이 로그인 확인 공통 함수(SPEC-374)로 바뀌어요. 403 `not_allowed` 안내가 없어지고 401은 SCR-164로 가요. SCR-122의 들은 곳 글(`discord_dm`, `kakao_dm` 등)은 지난 기억에 남아 있어서 그대로 보여요 | REQ-439, TASK-410 |

늘어나는 상태:

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-107#unread | 앱 기기가 없는 동안 방에 남은 말 위에 줄 '여기부터 안 읽은 말이야'가 보이고 그 줄로 스크롤돼요. 맨 아래로 가는 버튼이 있어요 | API-102#200(`readUpTo` 뒤에 마롱이 말이 있음) |
| SCR-107#ring-pending | 웹에서 약속 전화 시각 앞뒤에 열면 머리 아래 띠 '{이름}가 전화하기로 한 시간이야'와 '받기'(통화 화면을 `ring` 값과 함께 열어요, SCR-002). `pendingRing.until`이 지나면 띠가 사라져요 | API-216#200(`pendingRing`이 있음) |
| SCR-107#daily-limit | 입력 칸 위 띠 '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져'와 '내 마롱이에서 보기'(SCR-165). 쓴 글은 칸에 남고 보내기는 꺼져요. 한도 설정이 없으면 이 상태는 나오지 않아요 | API-103#429(`daily_limit`) |
| SCR-001#call-busy | 얼굴 01, '다른 기기에서 {이름}랑 통화 중이야. 그 통화를 끝내고 다시 걸어 줘'와 '다시 해 볼게' | API-107#101(메시지 `call_busy`) |
| SCR-001#calls-full | 걱정하는 얼굴(13), '지금은 전화가 꽉 찼어. 조금 있다가 다시 걸어 줘'와 '다시 해 볼게' | API-107#101(메시지 `calls_full`) |
| SCR-001#daily-limit | 슬픈 얼굴(06), '오늘 쓸 수 있는 양을 다 썼어. 새벽 4시에 다시 채워져'. 통화 버튼 막힘 | API-124#200(`blockedReason=daily_limit`), API-107#101(메시지 `daily_limit`) |
| SCR-002#waiting | 도구가 돌거나 답을 기다린 지 0.8초가 지나면 작은 효과음이 되풀이되고, 얼굴은 생각하는 얼굴(04, 캐릭터는 `surprised`), 얼굴 아래 '찾아보는 중…'과 점 세 개가 보여요. 마롱이 목소리가 시작되면 소리가 바로 멈추고 #talking이 돼요. 목소리와 겹치지 않아요. 못 찾으면 마롱이가 말로 알려 주고 화면 글은 없어요. 끊기는 늘 눌러요 | (통화 연결의 도구 시작·끝 신호, SPEC-389) |

SCR-002의 표정 표(캐릭터를 쓸 때, 새 제안): 거는 중·말하는 중·듣는 중은 `smile`, 기쁜 느낌은 `excited`, 쉬는 중은 `sleepy`, 생각·대기·다시 잇는 중은 `surprised`, 슬픈 느낌과 오류는 `sad`, 토라진 느낌은 `pout`이에요. 캐릭터는 입 움직임 그림이 없어서 말할 때는 얼굴 둘레의 링만 움직여요. 선 전화의 그림 카드(SCR-002#topic-card)는 기본 마롱이 그림이라 캐릭터를 쓰는 사람에게는 뜨지 않아요(제안 7절).

사람별 통화 상한(SPEC-390)에 닿으면 지금 있는 SCR-001#budget을 그대로 보여요.

## 16. 경우의 종류

| 종류 | 화면이 보여 주는 것 |
| --- | --- |
| 접근 | 로그인이 없으면 SCR-164로 갔다가 돌아옴(공통 규칙). 남의 캐릭터·친구·요청은 모두 404 화면. 관리자는 Access 뒤(SCR-169) |
| 입력 | 칸 아래 글과 쓴 값 유지(SCR-163#invalid, SCR-164#invalid, SCR-165#name-invalid, SCR-168#code-invalid, SCR-169#invite-invalid·#ticket-invalid, SCR-171#invalid, SCR-174#invalid) |
| 대상 | 없는·쓴·지난 초대 링크(SCR-163#not-found·#used·#expired), 없는 친구 코드(SCR-168#code-not-found), 사라진 요청(SCR-168#gone), 지운 캐릭터는 '찾지 못했어' |
| 상태 변화 | 만들기 단계는 서버 상태로 화면을 바꿈(SCR-170\~174#stale), 다 만들지 않은 캐릭터의 적용(SCR-166#not-ready), 적용·되돌리기(SCR-166#applied, SCR-165#reverted) |
| 반복 | 버튼이 응답까지 꺼짐. 같은 초대 링크의 두 번째 사용은 SCR-163#used, 같은 쌍의 두 번째 요청은 SCR-168#request-exists·#already |
| 동시 | 작업이 도는 중의 쓰기(`job_running`)는 그리는 중 상태로 맞춤(SCR-170#busy, SCR-171#analyzing, SCR-172·173#drawing, SCR-165#delete-busy). 다른 기기의 통화는 SCR-001#call-busy, 서버가 꽉 차면 SCR-001#calls-full |
| 한도 | 캐릭터 3개(SCR-165#full, SCR-170#limit), 다시 그리기 2번(SCR-173#limit), 그림 월 예산(SCR-170\~173#budget), 기기 코드 한 시간 5개(#code-limit), 틀린 코드 5번(SCR-164#blocked), 친구 요청 하루 10번(SCR-168#request-limit), 하루 사용량(SCR-165#usage-over, SCR-107#daily-limit, SCR-001#daily-limit) |
| 바깥 서비스 | 그림·비전 모델 실패(SCR-171#refused·#failed, SCR-172#preview-failed, SCR-173#failed·#sheet-failed), 견본 소리 실패(SCR-167#sample-error), 통화 도구 대기(SCR-002#waiting). 나머지 화면은 그대로 써요 |
| 데이터 노출 | 초대 주소는 만든 때 한 번만(SCR-169#created), 목록에는 토큰이 없음. 관리자 화면에 대화 글·기억 없음. 친구 화면에는 이름과 관계만 있고 상대의 친구 코드는 없음. 오류 메시지에는 `traceId`만 |
| 비어 있음과 끊긴 답 | 캐릭터 없음(SCR-165#default-character), 친구 없음(SCR-168#empty), 초대·가입한 사람 없음(SCR-169#invites-empty·#members-empty), 견본 없음(SCR-167#no-sample), 사용량만 실패(SCR-165#usage-error). 흐르는 답은 없어요 |
| 화면 상태 | 위 상태마다 360px·430px 와이어프레임을 그려야 해요. 아직 그리지 않았어요 |
| AI 답 | 입혀 보기의 말은 정해 둔 견본이라 모델을 부르지 않아요(SCR-166). 모델이 그린 그림과 읽은 특징표의 실패는 '바깥 서비스' 줄의 상태예요 |

## 17. 열린 것과 정한 것

- 09 목업은 2026-11-19에 대지 17장을 그렸어요([목업 기록](../../design/unified-mockup.md)). 새 토큰 없이 지금 글 대화 화면과 반려동물 A안의 부품만 써요. 와이어프레임은 그리지 않았고, 목업에 없는 상태는 이 정의대로 만들어 구현된 화면(TC-449, TC-463)에서 봐요.
- 통화 시작(API-107)은 웹소켓이라 브라우저가 HTTP 상태 번호를 읽지 못해요. 그래서 통화 시작의 거절(`call_busy`, `calls_full`, `daily_limit`, `budget_exhausted`)은 연결을 받은 뒤 오는 메시지 `{type: "<코드>"}`이고, 화면은 그 메시지를 받으면 통화 홈으로 돌아가 위 상태를 그려요. `daily_limit`은 통화 홈 상태 응답(API-124)의 `blockedReason`으로도 와서 걸기 전에 버튼을 막아요. 계약 [unified.openapi.yaml](../../api/unified.openapi.yaml)의 머리말이 그렇게 적었고, 통화 계약 파일의 고침은 구현 PR(TASK-395, TASK-406)에서 해요.
- SCR-002#waiting은 통화 서버가 지금 상태를 보내는 연결로 주는 `{type: "wait", on: true|false}`를 따라요(기능 명세 3.10). SCR-107#ring-pending은 앱 서버의 프로필 응답(API-216)의 `pendingRing`을 따라요(기능 명세 3.8). 통화 서버의 상태 응답에는 벨 값이 없어요.
- 캐릭터 그룹과 친구 줄을 숨길 값은 프로필 응답(API-216)의 `features.character`·`features.friends`예요. `features.character`가 꺼져 있어도 쓰는 캐릭터의 얼굴과 이름은 그대로 그려요.
- 미리 보기 단계에서 특징표를 다시 고치는 경로(SCR-172 '특징표 다시 고칠래')는 API-222가 `traits`와 `preview` 단계에서 모두 받아요.
- 구글 캘린더 줄(SCR-165)은 프로필 응답의 `google`(`connected`·`not_connected`·`off`)을 따라요. `off`면 줄을 그리지 않아요.
- 로그인된 기기에서 초대 링크를 열면 SCR-163이 상태 #signed-in을 그려요: "이 기기는 이미 {이름}(으)로 들어와 있어"와 '글 대화로 가기', '이 링크로 다시 들어가기'. 뒤의 것을 눌러야 API-212를 불러요. 링크를 열기만 해서는 쓴 것으로 치지 않아요.
- 목소리 목록 8개는 동희님이 듣기 시험(SCR-119)으로 고른 뒤 정해져요. 그 전에는 SCR-167#single이에요.
