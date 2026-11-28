# 마롱이 화면 공통 기준

마롱이의 모든 화면(통화 웹, 앱, 글 대화, 일기장, 듣기 시험, 성향 맞춤, 앱 업데이트)이 같이 쓰는 토큰, 부품, 화면 번호, 목업 자리를 한 곳에 모은 문서예요. 2026-11-17 12:36 KST 동희님이 프로젝트 채팅에서 "다른애들도 목업 만들고 해야할거야. 걔들이랑 합쳐서 작업해야할거같아 / 너가 오케스트레이션 잘 해봐"라고 해서 만들었고, 12:38 "모든 작업에 대해 설계만 여기서 하고, 구현은 지피티 시킬거임"에 따라 GPT가 화면을 만들 때 읽는 기준이기도 해요.

이 문서와 토큰 파일은 '마롱이의 일기 설계하기' 스레드(PR #25)가 고쳐요. 다른 스레드는 7절대로 보내 주면 돼요.

## 0. 무엇이 맞는가

1. 화면 정의: `docs/08-screens/*.md`, [`docs/android-app.md`](../docs/android-app.md), [`docs/app-chat.md`](../docs/app-chat.md), [`docs/app-ring.md`](../docs/app-ring.md). 글, 상태, 동작의 원본이에요.
2. 토큰: [`base.tokens.json`](base.tokens.json)(DTCG 2025.10). 색·크기·간격 값의 원본이에요.
3. 이 문서: 부품, 토큰과 CSS 변수 이름표, 화면 번호표.
4. 목업 캔버스 [마롱이 화면 설계](https://claude.ai/artifact/CC154gunovJS3tqa8XkpZ9)(비공개, 공유받은 사람만): 모양을 보는 곳이에요. 대지의 글과 날짜는 예시 데이터예요.

서로 다르면 1 > 2 > 3 > 4 순서로 맞아요.

## 1. 테마

- 한국 시각 08:00부터 20:00 직전까지 `color.b` '군밤 크림', 나머지는 `color.a` '밤하늘'이에요. 화면을 연 채 경계 시각을 지나거나 앱으로 돌아와도 통화와 쓰던 글을 유지하고 색만 바꿔요.
- 코드에서는 `:root`가 밤하늘, `:root[data-theme="chestnut"]`가 군밤 크림이에요(`marong/app_chat_static/chat.css`, `tools/vertex_live/static/style.css`). 새 화면도 같은 방식을 써요.
- 대지는 테마 하나씩 그려요. 구현은 두 테마 모두예요.

## 2. 두 가지 모양

| 모양 | 쓰는 화면 | 바탕·글 | 글꼴 |
| --- | --- | --- | --- |
| 앱 모양 | 통화 웹 SCR-001\~005, 앱·글 대화 SCR-101\~112, 듣기 시험 SCR-119, 성향 맞춤 SCR-120\~, 앱 업데이트 SCR-130\~, 일기장의 머리·띠·안내 화면 | `bg`·`surface`·`surface-2`, 글 `text`·`text-muted`, 주 버튼 `accent` | `font.body` |
| 종이 모양 | 일기장 SCR-113\~118의 일기 종이, 원고지, 달력, 아래에서 올라오는 칸 | `diary-paper`, 줄 `diary-grid`, 글 `diary-ink`, 도장 `diary-stamp`, 테두리 `diary-frame` | `font.diary`(Gaegu, 앱 서버가 내려줌) |

새 화면은 앱 모양이 기본이에요. 종이 모양은 일기장 안에서만 써요.

## 3. 토큰과 CSS 변수 이름

이미 있는 화면 CSS는 자기 이름(`--page`, `--raised`…)을 써요. 이름은 그대로 두고 값만 토큰에서 와요. 새 화면은 아래 이름표의 이름을 써요.

| 토큰(테마별 `color.a.*`·`color.b.*`) | CSS 변수 | 쓰는 곳 |
| --- | --- | --- |
| `bg` | `--page` | 화면 바탕 |
| `surface` | `--surface` | 말풍선, 입력 칸, 카드 |
| `surface-2` | `--raised` | 띠, 눌린 바탕, 상태 칸 |
| `text` / `text-muted` | `--text` / `--muted` | 글 / 작은 글 |
| `accent` / `on-accent` | `--accent` / `--on-accent` | 주 버튼과 그 위 글, 글 버튼 |
| `star` | `--star` | 초점 테두리(3px), 별 표시 |
| `line` | `--line` | 구분선, 머리 아래 줄, 꺼진 버튼 테두리 |
| `danger` | `--danger` | 못 보낸 말 테두리, '다시 보내기' |
| `input-border` | `--input-border` | 글 입력 칸 테두리 |
| `hint` | `--hint` | 입력 칸 안내 글 |
| `backdrop` / `panel-shadow` | `--backdrop` / `--panel-shadow` | 넓은 화면의 폰 틀 뒤 빛과 그림자, 그림 화두 카드 그림자 |
| `face-disc` | 글 대화 `--face-base`, 통화 `--face-light` | 얼굴 그림의 둥근 바탕 |
| `hangup` / `on-hangup` | `--hangup` / `--on-hangup` | 통화 끊기 버튼(통화 화면만) |
| `diary-paper`, `diary-grid`, `diary-ink`, `diary-ink-muted`, `diary-stamp`, `diary-frame`, `diary-shadow` | `--diary-paper` … `--diary-shadow`(새) | 일기장 종이 모양 |
| `scrim` | `--scrim`(새) | 아래에서 올라오는 칸 뒤 가림막 |
| `color.diary-weather.*`(두 테마 같음) | `--weather-sun` … `--weather-rainbow`(새) | 마음 날씨 아이콘 |
| `accent-soft`(군밤 크림만) | 없음 | 지금 쓰는 곳 없어요 |

색이 아닌 토큰은 `--<묶음>-<이름>`이에요(`size.touch-min` → `--size-touch-min`, `space.md` → `--space-md`, `font-size.diary-body` → `--font-size-diary-body`). `font.body`는 `:root`의 `font-family`예요.

통화 화면 CSS 안에만 있는 장식 값(`--face-edge`, `--face-shadow`, `--ring*`, `--call-shadow`, `--muted-button`, `--on-muted-button`, `--footnote`)과 이미 있는 화면의 px 값(통화 버튼 84px 등)은 토큰이 아니에요. 그 화면 정의가 바뀌지 않으면 그대로 둬요. 새 화면은 토큰에 있는 값만 써요.

2026-11-17에 고친 것: 목업과 실제 화면이 같은 값을 쓰도록 `color.a.line`, `color.a.on-accent`, `color.a.on-hangup`, `font.body`를 화면 CSS 값으로 맞추고, 화면 CSS에만 있던 `danger`, `input-border`, `hint`, `backdrop`, `panel-shadow`, `face-disc`(두 테마)와 `color.b.star`를 더했어요. 선 전화·그림 화두(CTX-020, PR #27)의 `size.topic-picture`(240px)도 같은 글자로 넣었어요. 토큰은 87개에서 101개가 됐고, 일기 대지 72장은 새 값으로 다시 만들었어요. 밤하늘의 끊기 버튼 위 글(`on-hangup` on `hangup`)은 대비 3.47이라 아이콘과 굵은 큰 글에만 맞아요(이미 쓰는 화면 그대로).

2026-11-17 오후(성향 맞춤 화면을 합치며): 글 대화 말풍선을 새 화면도 다시 쓰니까 `chat.css`의 말풍선 값 `font-size.bubble`(15px)과 `radius.bubble`(18px)을 더해 103개가 됐어요. 성향 목업이 `chat.css`에서 그대로 가져온 다른 두 값은 토큰을 더하지 않고 이렇게 맞춰요: 작은 모서리 12px은 새 페이지(SCR-120\~122)에서 글 버튼·띠는 `radius.sm`, 칩은 `radius.full`이고, 글 대화 안(SCR-123)은 이미 있는 화면이라 `chat.css` 값 그대로예요. 약속 문장 17px은 `font-size.body`(16px)를 굵게(600) 써요. 한 단계 차이의 새 글 크기를 늘리지 않으려고요.

**토큰을 얼렸어요(2026-11-17 17:27:13 KST, 프로젝트 채팅, 동희님 "아니 얼마나 더 남았어 설계? 나한테 확인하는 단계만 남은거야? 모두 승인이야", D67).** `base.tokens.json`의 103개를 지금 값 그대로 써요. 반려동물 서비스는 방향 A(D72)라 새 토큰이 없어요. 이제 값을 바꾸려면 설계 PR과 동희님 확인이 따로 필요해요. 아래는 얼리기 전의 기록이에요. 토큰 얼리기(09단계 체크포인트)는 전체 목업 번들로 한 번 받아요. 얼리기 전까지 바뀌는 값은 이 문서의 이 절에 적어요. 2026-11-17 14:37 KST 동희님 "다른 스레드에서 앞으로 나올 화면설계 있나? 있으면 기다리고"에 따라, 반려동물 서비스 화면(일기장 꾸미기·글씨체·옷 입히기)까지 합친 뒤에 여쭤요. 반려동물은 2026-11-17 16:33 KST에 A(마롱이 앱 모양)로 정해져(D72) 새 토큰이 없어요([pet-candidates.md](pet-candidates.md)). 성향 맞춤 1\~4단계 화면은 이미 합친 SCR-120\~123이 전부예요(성향 스레드 14:39 확인, 새 토큰 없음). 그때까지 토큰은 바뀔 수 있어요.

## 4. 부품

일기 대지를 만든 스크립트(프로젝트 파일 `marong-diary-mockup-20261116/build_diary.py`)의 부품이고, 모든 값이 토큰 변수예요. 다른 화면도 같은 부품을 먼저 써요.

### 앱 모양

| 부품 | 모양 | 토큰 |
| --- | --- | --- |
| 머리 | 48px 버튼이 들어가는 줄(위아래 4px), 가운데 제목(굵게), 아래 `line` 1px. 일기장은 왼쪽 '글 대화'(앱 창 안에서 돌아가는 경로), 오른쪽 달력·더 보기. 칸은 왼쪽 '닫기' | `size.touch-min`, `font-size.body`, `border-width.thin` |
| 주 버튼 | 높이 52px, 둥근 모서리 16px, `accent` 바탕. 꺼지면 바탕 없이 `line` 테두리와 `text-muted` 글 | `size.button`, `radius.md`, `space.lg` |
| 두 번째 버튼 | 높이 48px, `accent` 2px 테두리, 바탕 없음 | `size.touch-min`, `border-width.thick` |
| 글 버튼 | 높이 48px, 테두리 없음, `accent` 글('다시 해 볼게', '다시 보내기') | `size.touch-min`, `radius.sm` |
| 아이콘 버튼 | 48px 원, 아이콘 24px, `aria-label` | `size.touch-min`, `size.icon` |
| 띠 | `surface-2` 바탕 한 줄 + 오른쪽 글 버튼. 503 "잠깐 문제가 생겼어. 조금 있다가 다시 해 줘" | `space.sm`·`space.md` |
| 작은 줄 | 가운데 `caption`, `text-muted` | `font-size.caption` |
| 알림 조각 | 아래에 뜨는 `text` 바탕·`bg` 글 상자 | `radius.md` |
| 안내 화면 | 가운데 얼굴(152px, `face-disc` 바탕) + 제목 + 글 + 버튼 + 추적 id(`caption`). 빈 상태·권한·오류 | `size.face-small`, `font-size.title` |
| 마롱이 얼굴 | 통화 중 248px, 통화 홈 200px, 끝난 화면·안내 152px. 쓰임은 [`marong-face/README.md`](marong-face/README.md), 그림은 꾸밈이라 `alt=""` | `size.face-*` |
| 그림 화두 카드·말풍선 | 통화 중 얼굴 원 자리에 그림 15초, 글 대화 말 위 그림 240px(CTX-020, `design/call-first-candidates.md`) | `size.topic-picture`, `size.face-call`, `panel-shadow` |
| 메뉴 상태 줄 | 글 대화 메뉴(SCR-109)의 '알림'·'약속 전화'·'자동 업데이트' 줄. 줄 글 + 필요할 때 '켜기'류 두 번째 버튼(누르는 높이 44px 이상, 원본은 `chat.css`) | `surface`, `line` |
| 말풍선 | 마롱이 말은 왼쪽 위 모서리 4px·나머지 18px, `surface` 바탕, `line` 테두리, 글 15px·줄 간격 1.65. 내 말은 오른쪽 위 4px, `surface-2` 바탕(원본 `chat.css` `.bubble`). 새 화면에서 마롱이 답을 보일 때도 같은 모양(SCR-121) | `font-size.bubble`, `radius.bubble` |
| 고르기 칩 그룹 | 한 그룹이 `role="radiogroup"`, 칩마다 `role="radio"`, 높이 48px, 끝까지 둥근 모서리. 고른 칩은 `accent` 바탕·`on-accent` 글과 ✓, 글로도 '골랐어'가 읽혀요. 친구 약속(SCR-120)과 글 대화 안 고르기 카드(SCR-123)가 같은 칩이에요 | `size.touch-min`, `radius.full` |
| 글 대화 머리 오른쪽 버튼 | 전화·알림에 일기장(SCR-113, API-108의 `enabled`가 참이거나 `date`가 있을 때만)과 나(SCR-120, API-127이 200일 때만, `aria-label` "친구 약속")가 더해져요. 같은 줄의 지금 버튼과 같은 크기(`chat.css` 44px)로 맞추고, 48px로 올리는 건 글 대화 전체를 바꿀 때 함께 해요. 네 개(사이 6px)여도 360px 한 줄 | `size.icon` |
| 듣기 시험 | "3 / 10"과 문장 점, 소리 줄(▶·■, 흐른 시간 막대), 점수 버튼 48px 다섯 개 한 줄, '마롱이 같다' | `size.touch-min`, `radius.full` |

### 종이 모양(일기장)

| 부품 | 모양 | 토큰 |
| --- | --- | --- |
| 종이 | `diary-paper` 바탕, 모서리 8px, 그림자 `diary-shadow` | `radius.sm`, `space.sm` |
| 양식 줄 | 날짜 줄과 '제목' 줄, `diary-grid` 2px 줄, 손글씨 | `font-size.diary-small`, `font-size.diary-title` |
| 마음 날씨 | 손그림 동그라미 안 아이콘, 고른 것은 `diary-stamp` 동그라미 | `color.diary-weather.*`, `size.icon` |
| 그림 틀 | `diary-frame` 2px 테두리. 그림을 못 받으면 기본 그림(틀 + 얼굴 01 + 별 두 개) | `border-width.thick`, `size.face-small` |
| 원고지 | 한 칸 한 글자, 칸 최소 32px, 칸 수 ⌊(폭 − 32px) ÷ 32px⌋(360px 10칸, 430px 12칸), `aria-hidden`이고 읽기용 문단은 따로 | `size.diary-cell`, `font-size.diary-body`, `border-width.thin` |
| 도장 | 76px 원 도장과 도장 자리 | `size.diary-stamp`, `diary-stamp` |
| 아래에서 올라오는 칸 | 고치기·다시 그리기. 위 모서리 24px, 뒤에 `scrim` | `radius.lg`, `scrim` |
| 줄 친 글 칸 | 친구가 쓰는 칸, 오류는 `diary-stamp` 글 | `diary-frame`, `size.diary-cell` |
| 달력 칸 | 한 칸 최소 64px, 일기 있는 날 날씨 아이콘, 고른 날 동그라미 | `size.control` |
| 숨긴 일기 줄·고르는 칩·내 모습 카드 | 목록 줄, 둥근 칩(48px), 카드 | `radius.full`, `size.touch-min` |

## 5. 화면 번호표

| 번호 | 화면 | 정의 | 목업 | 맥락 |
| --- | --- | --- | --- | --- |
| SCR-001\~005 | 통화 홈, 통화 중, 지난 통화, 통화 상세, 마롱이 기억 | `docs/08-screens/SCR-001`\~`005.md` | 통화 캔버스 [마롱이 통화 화면 설계](https://claude.ai/artifact/FDFCuk2xc8JE8SCUuh7hL2). SCR-001#budget과 SCR-002 그림 카드는 공통 캔버스 | 통화 |
| SCR-101\~106 | 앱 통화 화면, 연결 못 함, Access 로그인, 통화 중 알림, 마이크 안내, 아이콘 | `docs/android-app.md` | 없음(앱 0.2에서 만듦) | 앱 |
| SCR-107\~109, 112 | 글 대화, 앱 알림, 알림 상태(글 대화 메뉴), 글 대화 창 | `docs/app-chat.md`. CTX-020 상태는 `docs/08-screens/call-first.md`, CTX-021 줄은 `docs/08-screens/app-update.md` | 공통 캔버스(그림 말풍선, 자동 업데이트 줄) | 글 대화 |
| SCR-110\~111 | 벨 화면, 전화 알림 | `docs/app-ring.md`, `docs/08-screens/call-first.md` | 공통 캔버스(먼저 건 전화) | 앱 벨 |
| SCR-113\~118 | 일기장 한 날, 말로 고치기, 다시 그리기, 달력, 숨긴 일기, 내 모습 카드 | `docs/08-screens/SCR-113`\~`118.md` | 공통 캔버스 'A · SCR-11x' | 일기(CTX-007) |
| SCR-119 | 듣기 시험 | `docs/08-screens/SCR-119.md` | 공통 캔버스 | 통화 비용 |
| SCR-120\~122 | 친구 약속, 맞춤형 지침, 마롱이가 기억하는 나 | PR #30 `docs/08-screens/SCR-120`\~`122.md`, `persona.md` | 공통 캔버스 '성향 맞춤' A·B(방향 고르기 전, 추천 A) | 성향 맞춤(CTX-008·011) |
| SCR-123 | 글 대화 안 고르기 카드(SCR-107 메시지 안 부품이라 사이트맵에 없음) | PR #30 `docs/08-screens/SCR-123.md` | 같은 줄 | 성향 맞춤(CTX-008) |
| SCR-124\~129 | 성향 맞춤 몫으로 남김(선톡·부탁 화면이 필요해지면) | | | CTX-008\~ |
| SCR-130 | 앱 새 버전 알림(안드로이드가 그림) | `docs/08-screens/app-update.md` | 공통 캔버스 참고 한 장 | 앱 업데이트(CTX-021) |
| SCR-131\~139 | 앱 업데이트 몫으로 남김 | | | CTX-021 |
| SCR-140\~162 | 반려동물 서비스: 홈, 가입, 아이 만들기 다섯(사진·특징표·미리 보기와 결제·후보·이름), 아이 화면, 통화, 일기장, 일기 한 장, 다시 그리기, 옷 입히기, 아이 설정, 작별 의식, 충전, 신고, 상점, 아이템 보기, 내 정보, 한도와 구독, 주문 내역, 결제 확인 | `docs/08-screens/pet.md` | 공통 캔버스 '반려동물' A(D72로 A, [pet-candidates.md](pet-candidates.md)) | 반려동물 서비스(CTX-022\~025, 다른 도메인의 공개 서비스) |
| SCR-163\~174 | 통합 앱(MVP): 가입, 로그인, 내 마롱이, 입혀 보기, 목소리 고르기, 친구, 관리자, 캐릭터 만들기 다섯(사진·특징표·미리 보기·후보·이름). SCR-163\~169는 반려동물 서비스 몫이던 번호를 넘겨받았어요 | `docs/08-screens/unified.md` | 캔버스 [마롱이 통합 앱 목업](https://claude.ai/artifact/GXVep4QepAUdFhH6gDmLb3) 17장([unified-mockup.md](unified-mockup.md)) | 통합 앱(CTX-026\~029) |
| SCR-175\~179 | 비움(pet-app이 같은 날의 다른 설계와 겹치지 않게 간격을 두고 180부터 잡았어요) | | | |
| SCR-180\~186 | 반려동물 캐릭터 앱 안(pet-app): 아이 소개, 상점, 아이템 보기, 보관함, 일기장 꾸미기, 스티커 붙이기, 관리자 아이템 | `docs/08-screens/pet-app.md` | 캔버스 [마롱이 반려동물 앱 안 목업](https://claude.ai/artifact/SvoMoaLwcvq5XoBQxT2uVd) 13장([pet-app-mockup.md](pet-app-mockup.md)) | 반려동물 캐릭터 앱 안(CTX-030\~031) |
| SCR-187\~194 | pet-app 몫으로 남김(추억 모드 등) | | | 반려동물 캐릭터 앱 안 |
| SCR-195\~ | 다음 범위. 쓰기 전에 설계 스레드에 받아요 | | | |

앱 쪽 번호(SCR-101\~112)는 07 사이트맵(`docs/07-sitemap/sitemap.yaml`)이 아니라 위 앱 문서에 적혀 있어요. 사이트맵의 화면은 통화 웹과 `/chat/` 아래 화면이에요.

## 6. 목업 캔버스

- 한 캔버스 [마롱이 화면 설계](https://claude.ai/artifact/CC154gunovJS3tqa8XkpZ9)에 맥락별로 줄을 나눠 올려요: 일기 A(72장), 통화 비용 #budget, 선 전화·그림 화두(CTX-020), 앱 자동 업데이트(CTX-021), 성향 맞춤(CTX-008·011, A·B 두 줄), 반려동물 서비스(CTX-022\~025, A·B 두 줄). 고르지 않은 후보와 비교 기록은 맨 아래예요.
- 대지 파일 이름: 일기 `A1xx-<상태>`(SCR-113\~119, `Main`·`A-*`도 일기 A), 통화 비용 `A001-budget`, 선 전화 `C020-<SCR>-<상태>-<day|night>-<폭>`(23장, 고르지 않은 B 4장은 `C020-B-*`), 앱 업데이트 `C021-109-update-<on|off>-*`(4장)과 `C021-130-notification`(참고 한 장), 성향 맞춤 `C008-<A|B>-<SCR>-<상태>-<day|night>`(12장, 방향 고르기 전이라 A·B 모두 검토 대상), 반려동물 `C022-<A|B>-<SCR>-<상태>-<테마>`(10장, A는 `day|night`, B는 `light|dark`. D72로 A, 고르지 않은 B 5장은 맨 아래). 2026-11-17 캔버스 버전 18에서 대지 130장이에요.
- 대지 제목은 `SCR-번호#상태 · 테마 · 폭`이에요. 폭은 360px을 기본으로, 줄바꿈이 달라지는 화면은 430px도 그려요.
- 성향 맞춤 목업은 그 스레드가 토큰 값으로 HTML을 그려 360px 폭 전체 길이로 찍은 그림이라 그대로 올렸어요(프로젝트 파일 `persona-mockup-20261117/`, 후보와 추천은 PR #30 `design/persona-candidates.md`).
- 반려동물 목업은 이 스레드가 토큰 값으로 HTML을 그려 360px 폭 전체 길이로 찍었어요(프로젝트 파일 `marong-pet-mockup-20261117/`, 후보와 추천은 [pet-candidates.md](pet-candidates.md)). 2026-11-17 16:33 KST에 A로 정해져(D72) B의 새 색은 넣지 않아요.
- 선 전화 목업은 그 스레드가 실제 화면 CSS를 띄워 찍은 그림이라 그대로 올렸어요(원본 [그 목업](https://claude.ai/artifact/UQYxaGXQ72wGRSWv5YuU8x), 프로젝트 파일 `marong-call-first-mockup-20261116/`).
- 통합 앱(MVP) 목업은 캔버스를 따로 써요: [마롱이 통합 앱 목업](https://claude.ai/artifact/GXVep4QepAUdFhH6gDmLb3), 대지 `C026-<SCR>-<상태>-<day|night>` 17장(2026-11-19). 대지가 실제 HTML이고 부품 클래스는 [unified-mockup.css](unified-mockup.css) 한 벌이에요. 기록은 [unified-mockup.md](unified-mockup.md)예요.
- 반려동물 캐릭터 앱 안(pet-app) 목업도 캔버스를 따로 써요: [마롱이 반려동물 앱 안 목업](https://claude.ai/artifact/SvoMoaLwcvq5XoBQxT2uVd), 대지 `C027-<SCR>-<상태>-<day|night>` 13장(2026-11-21). `unified-mockup.css` 위에 [pet-app-mockup.css](pet-app-mockup.css)를 더 불러요. 아이템 그림은 [pet-app-mockup/](pet-app-mockup/)의 자리 표시 그림이에요. 기록은 [pet-app-mockup.md](pet-app-mockup.md)예요.
- 기본 마롱이 옷 입히기(pet-app 기능 변경 1, 2026-11-28) 목업: [마롱이 옷 입히기 목업](https://claude.ai/artifact/AyzwChfUqjEUCccgPEfn7A), 대지 `W-<SCR>-<상태>-<day|night>` 13장. 두 CSS를 그대로 불러요. 모자·옷·목도리는 운영 아이템 레이어를 마롱이에게 자동으로 맞춘 그림이에요. 기록과 그림 방식 비교는 [marong-wear-mockup.md](marong-wear-mockup.md)예요.

## 7. 다른 스레드가 화면을 더할 때

1. 번호는 자기 범위에서 써요(5절). 화면 정의(08)는 자기 PR의 `docs/08-screens/`에 써요.
2. 새 토큰이 필요하면 이 스레드에 이름, 두 테마 값, 쓰는 곳, 대비를 보내요. 토큰 파일은 이 스레드만 고쳐요. 두 PR이 같은 토큰을 따로 고치면 병합 때 겹치니까요.
3. 목업은 2·4절의 모양과 부품으로 만들어요. 그림(png·webp)이나 HTML을 프로젝트 파일 `/mnt/project-files/<폴더>/`에 두고 이 스레드에 알려 주면 캔버스에 같은 규칙으로 올려요.
4. 방향 고르기(09 첫 체크포인트)는 맥락마다 그 스레드가 동희님께 받아요. 토큰 얼리기는 전체 목업 번들로 한 번 받아요.

## 8. GPT가 화면을 만들 때

- 읽는 순서: 그 화면의 정의 → 이 문서 1\~4절 → 캔버스의 그 화면 대지 → 06 API(`api/`) → 그 맥락의 10 WBS 'GPT 인계' 절.
- 지킬 것: 토큰에 없는 색·크기를 새로 만들지 않아요(필요하면 설계 쪽에 물어요). 이미 있는 CSS 변수 이름을 그대로 써요. 대지의 글은 예시이고 문구 원본은 화면 정의예요. 얼굴·그림은 `alt=""`이고 상태는 늘 글로도 보여요. 움직임 줄이기를 따라요.
- 끝났는지 보기: 정의의 상태마다 360px·430px, 두 테마로 띄워 대지와 견줘요. 누르는 곳 44px 이상, 글 대비 4.5:1 이상(큰 글·아이콘 3:1)이에요.
