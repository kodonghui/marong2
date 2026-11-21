# 반려동물 캐릭터(통합 앱 안) 작업 목록(10단계 WBS)

2026-11-21 17시대 KST 작성(Claude). 입력: 도메인 [pet-app.md](../01-domain/pet-app.md)(CTX-030·031, TERM-210\~218, 바뀌는 CTX-027·001·002·007·009·020), 요구사항 [pet-app.md](../02-prd/pet-app.md)(REQ-500\~546·550\~552), 흐름 [FL-185\~192](../03-user-flow/), 기능 명세 [pet-app.md](../04-functional-spec/pet-app.md)(SPEC-406\~429, AI-40\~43, 바뀌는 AI-30·31), 표 [022_pet_app.sql](../../marong/migrations/022_pet_app.sql)(TBL-175\~181, 설명 [05-erd/pet-app.md](../05-erd/pet-app.md)), 계약 [pet-app.openapi.yaml](../../api/pet-app.openapi.yaml) 0.1.0-draft(API-250\~266, 바뀌는 API-216·217·110), 화면 상태 [08-screens/pet-app.md](../08-screens/pet-app.md)(SCR-180\~186, 바뀌는 SCR-174·165·166·107·109·002·113·115·169), 목업 [pet-app-mockup.md](../../design/pet-app-mockup.md), 시험 계획 [12-qa/pet-app.md](../12-qa/pet-app.md)(TC-510\~560).

## GPT 인계

- 목표: 반려동물 캐릭터를 쓰는 친구에게 그 아이가 1인칭으로 말하고(D111), 그림 화두·그림일기·아이템 반응을 그 아이로 매번 새로 그리고(D112), 0원 상점에서 받은 모자·옷·목도리를 입히고 일기장 배경·속지·글꼴·스티커를 꾸며요(D113·D114). 그 밖의 기능은 기본 마롱이와 같아요(D116). 캐릭터를 만들 때 정면 그림에 그 아이 사진을 보여 줘서 닮게 그려요(D120). 동희님 2026-11-21 말씀: "선톡 전 전화 알림 등 모든 기능은 같아"(15시대, 이 스레드), "야 그냥 만들지 말고 /corthex로 만들어"(15:35 KST, 프로젝트 채팅), "그림 월 예산은 아직 두지 마 그냥 무제한. 지금 mvp 만드는거라고"(16:36 KST, D119), 결정 카드 '사진도 보여 주기(C)'(16:48 KST, D120). 결정 원문과 자리는 [도메인 문서 머리의 결정 표](../01-domain/pet-app.md)예요.
- 시작: 이 설계 PR이 `main`에 합쳐진 뒤 `main` 머리에서. 설계를 쓸 때의 `main`은 `135e303`이에요(통화 연결 고치기 PR #82까지). 초안 PR 넷으로 나눠요: ① `codex/pet-app-base`(TASK-420·421·427) ② `codex/pet-app-voice`(TASK-422\~426) ③ `codex/pet-app-scenes`(TASK-428\~433) ④ `codex/pet-app-decor`(TASK-434\~442). 앞 PR이 합쳐진 뒤 그 `main`에서 다음 PR을 시작해요. ③의 일기 장면(TASK-431)이 ②의 `diaries.character_id`(TASK-425)를 쓰니 순서는 ① → ② → ③ → ④예요. 다만 ③의 TASK-428·429는 ②를 기다리지 않고 시작해도 돼요.
- 읽을 것: [기능 명세](../04-functional-spec/pet-app.md)의 1절(공통 규칙·스위치·설정값), SPEC-406\~429, 3.1\~3.13절, [계약](../../api/pet-app.openapi.yaml)의 API-250\~266과 머리 설명의 '이 파일 밖에서 바뀌는 것' 1\~4(통합 앱 계약 API-216·217, 일기 계약 API-110), [마이그레이션 022](../../marong/migrations/022_pet_app.sql), [화면 상태](../08-screens/pet-app.md)의 SCR-180\~186과 9절, [시험 계획](../12-qa/pet-app.md)의 TC-510\~560. 이 밖의 문서는 읽지 않아도 돼요.
- 화면 모양: 저장소의 정적 목업 [`design/pet-app-mockup.html`](../../design/pet-app-mockup.html)(기록 [pet-app-mockup.md](../../design/pet-app-mockup.md))이 SCR-180\~186의 주요 상태를 360·430px로 그려요. 실제 화면은 지금 `unified.css`·`chat.css`·일기장 `diary.css`의 부품과 얼린 토큰 103개만 써요. 새 토큰은 없어요. 목업의 아이템 그림은 자리 표시 그림이에요.
- 이미 된 것: 설계와 마이그레이션 022예요. 2026-11-21에 버리는 Postgres(`pgserver`, 합성 행)에서 020·021(통화 008~010 포함) 뒤에 022를 두 번 적용하고 제약 거절 21가지, 목소리 백필, 권한을 확인했어요([표 문서](../05-erd/pet-app.md)). 운영 DB에는 적용하지 않았어요. 코드는 아무것도 바꾸지 않았어요. 같은 날 그림 모델로 고양이 한 마리를 그려 본 결과가 명세 3.3·3.13의 숫자와 지시 글이에요(시험 그림과 영상은 저장소 밖에 있어요. 시험에 쓰지 않아요).
- 순서: TASK-420 → 421 → 427(PR ①) → 422 → 423 → 424 → 425 → 426(PR ②) → 428 → 429 → (430, 431, 432) → 433(PR ③) → 434 → 435 → (436, 437) → 438 → 439 → (440, 441) → 442(PR ④) → 443 → 444. 괄호 안은 서로 다른 파일이라 같이 해도 돼요. 반영(TASK-443)은 PR이 합쳐질 때마다 같은 절차로 해요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node와 Playwright(화면). 시험 데이터는 합성 데이터만이고, 사진은 CC0(퍼블릭 도메인) 강아지·고양이 사진만 써요(출처와 라이선스를 PR 설명에 적음). 진짜 모델은 아래 넷에서만 불러요. 나머지는 모두 목(mock)이에요.
  - TASK-426 금지선 시험: 지금 글 답 모델, 25번, 상한 1달러
  - TASK-433 닮음 시험: 비전 모델과 `gpt-image-2.5-flare`, 캐릭터 2마리와 장면 30장, 상한 3달러
  - TASK-435 아이템 그림: 같은 그림 모델, 상한 10달러[새 제안]
  - TASK-444 P95 재기: 운영 서버에서 장면 그림 20장, 상한 1달러
  - 키는 지금 서버·노트북의 비공개 설정에 있는 것을 쓰고 값을 출력하지 않아요. 상한에 닿으면 멈추고 PR 설명에 적어요.
- 반영: 서버 반영을 해요(TASK-443). 11/15 상시 반영 허락('만들어지는대로 계속 넣어')에 들어가요. PR마다 ① 지금 서버 파일의 해시를 `main`과 비교, DB와 바뀌는 파일 백업, 되돌리기 스크립트를 서버 `~/marong-deploy/<날짜>-pet-app-<PR>/`에 먼저 둠 ② (첫 PR만) 마이그레이션 021이 들어가 있는지 보고(`friend_profiles.usage_unlimited` 칸), 없으면 사람별 사용 한도 패키지의 절차를 따라 먼저 넣은 뒤 022(마이그레이션 관리자 역할, 두 번 돌려도 됨) ③ 앱 서버 파일, 통화 서버 파일(TASK-424·430·438이 바꾸면) ④ (첫 PR만) 앱 서버 설정 `MARONG_DIARY_IMAGE_BUDGET_USD=unlimited`(D119. 값은 출력하지 않고 '설정됨'만), 새 스위치 셋은 `0` ⑤ 대화·통화가 없을 때만 재시작 ⑥ 로그 5분 오류 확인과 TC-556 ⑦ 스위치는 하나씩 켜고 켤 때마다 로그 5분: `MARONG_DECOR=1`은 TC-538\~555 통과와 아이템 폴더가 들어간 뒤, `MARONG_SCENE_PICTURES=1`은 TC-537 통과 뒤, `MARONG_PET_VOICE=1`은 TC-453(PR #66)과 TC-522 통과 뒤예요. TASK-427(정면 그림에 사진)은 스위치가 없어서 반영하면 그 뒤에 새로 만드는 캐릭터부터 바뀌어요. 앱(APK)은 바꾸지 않아요.
- 하면 안 되는 것: 결제·충전·잔액·뽑기, 값이 0원이 아닌 아이템 올리기(D113, REQ-527·531). 지난 장면 그림을 다시 쓰거나 같은 장면을 캐시하기(REQ-512). 장면·표정 그림 요청에 사진, 친구·아이 이름, 대화 글 넣기, 정면 그림 요청에 처리 전 원본 사진 넣기(REQ-514·551). 그림 월 예산을 새로 두기(D119). 기본 마롱이에게 옷 입히기(질문 A, 기본값 '반려동물 캐릭터만'). 추억 모드(D121, 답 대기). 관리자 화면에서 그림 파일 받기. 바깥 CDN 글꼴, 새 디자인 토큰. 보류 중인 반려동물 공개 서비스 part(SCR-140\~162, TBL-140\~163, SPEC-332\~336) 고치기. 정해 둔 시험 전에 스위치 켜기. 이미 만든 캐릭터를 다시 그리기(사진이 지워져 있어요. 닮게 하려면 친구가 새로 만들어요).
- 겹치는 파일: `marong/app_profile.py`, `marong/app_admin.py`, `marong/app_chat.py`, `marong/unified_prompt.py`, `marong/unified_store.py`, `marong/unified_delivery.py`, `marong/app_session.py`, `run_app.py`, `marong/character/*`, `marong/diary.py`·`diary_models.py`·`diary_worker.py`·`app_diary.py`, `marong/app_chat_static/chat.js`·`profile.js`·`admin.js`·`character.js`·`diary/diary.js`·`diary/diary.css`, `tools/vertex_live/server.py`·`static/app.js`, `tests/pg.py`. 사람별 사용 한도(`codex/usage-limit`, `app_profile.py`·`app_admin.py`·`admin.js`·`profile.js`·`chat.js`·`tests/pg.py`)와 통화 연결 고치기(`codex/call-connect-*`, `tools/vertex_live/`)가 겹쳐요. 먼저 합친 쪽에 맞춰요. 마이그레이션 번호는 021이 사람별 사용 한도, 022가 이 패키지예요.
- 사람 확인: TC-537의 비교 그림(PR 설명에 붙임), 반영 뒤 TC-558\~560(동희님 아이폰 웹과 현경님 갤럭시 앱에서 얼굴 위 레이어·스티커·글꼴, 동희님이 자기 고양이 사진으로 새 캐릭터를 만들어 닮았는지, 아이 1인칭 대화). 현경님 폰은 동희님이 부탁해요.
- 끝 조건: 모든 TASK의 끝 조건 시험 통과, TC-510\~557 통과(결과를 시험 계획의 '결과' 칸에 어디서·어느 커밋으로), 아래 명령이 모두 통과, 반영 뒤 TC-556의 서버 쪽 확인과 TC-557 숫자.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드가 답해요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_pet_app_schema.py      # TC-510~512 (새 파일, 이름은 바꿔도 됨)
.venv/bin/python tests/test_pet_app.py             # API·작업 TC (새 파일, 나눠도 됨)
for t in test_unified_character test_unified_profile test_unified_usage test_unified_auth test_diary test_diary_worker test_app_diary test_topic_pictures test_topics test_proactive test_app_ring; do .venv/bin/python "tests/$t.py" || exit 1; done   # 기존 시험
for f in tools/vertex_live/test_*.py; do .venv/bin/python "$f" || exit 1; done   # 통화 서버 시험
(cd apps/android && npm ci && npm test && npm run test:browser)  # 화면 e2e. Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인해요
```

## 작업

- 담당: 모두 GPT예요. 서버 반영도 GPT가 해요(D65, AGENTS.md).
- 크기: 사람이 하는 일 기준의 대략값(일)이에요. 합은 약 31.5일이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-420 | 마이그레이션 022를 시험 DB에 넣기: `tests/pg.py`에 적용 함수(예: `apply_pet_app()`, 020·021 뒤. 사람별 사용 한도의 `apply_usage_limit()`가 아직 없으면 021 파일을 직접 적용)를 더하고, 표 문서의 확인(두 번 적용, `voice_source` 백필, 제약 거절, 지우기 권한 없음)을 저장소 시험으로 옮겨요 | SPEC-409, 408, 410, 417\~424, 428 | TBL-175\~181, 바뀌는 TBL-169·105와 `friend_profiles`·`topic_sends`·`app_rings`, `marong/migrations/022_pet_app.sql`, `tests/pg.py` | 없음 | GPT | 1 | TC-510\~512 통과. 기존 `tests/test_unified_*.py` 통과 |
| TASK-421 | 기능 스위치와 설정값(명세 1절 10의 표)을 한 곳에서 읽기. 프로필 API-216에 `features.decor`, `character.template`·`outfit`(이 TASK에서는 세 자리 모두 null)·`introMissing`을 더해요. 스위치가 모두 꺼져 있으면 응답과 동작이 지금과 같아요 | SPEC-409, 421 | API-216, `marong/app_profile.py`, 설정 읽는 곳 | TASK-420 | GPT | 0.5 | TC-513 통과. API-216 응답이 통합 앱 계약 스키마에 맞음 |
| TASK-427 | 캐릭터 정면 그림에 아이 사진(D120): AI-30 출력 스키마에 `bestPhoto`·`petBox`를 더하고 범위를 확인해 `characters.photo_pick`에 둠(특징표 `traits`와 API-222는 그대로), `preview`·`candidates` 단계에서 그 사진을 10% 넓혀 잘라 긴 변 1024px PNG로(메타데이터 없음, `asyncio.to_thread`), AI-31 정면 요청의 참조 이미지를 사진·템플릿·화풍 순서로, 지시 글을 3.13 `pet-artwork-v2`로, 표정 지시를 3.13 표정 틀로. 표정 끝에 사진을 지울 때 `photo_pick`도 비움. 틀린 상자는 사진 전체와 로그 `pet_box_fallback` | SPEC-428, 429 | AI-30, AI-31, `marong/character/vision.py`·`traits.py`·`artwork.py`·`worker.py`·`photos.py`·`records.py` | TASK-420 | GPT | 1.5 | TC-523\~525 통과. `tests/test_unified_character.py`·`tests/test_pet_core.py` 통과 |
| TASK-422 | 아이 소개 API-250·251(칸 규칙과 글 정리, `intro_at`), 처음 저장할 때 추천 목소리(명세 3.2, `MARONG_VOICE_RECOMMEND`), 목소리 고르기 API-217이 `voice_source = 'chosen'`을 같이 적음 | SPEC-409, 407 | API-250, API-251, API-217, `marong/app_profile.py`(또는 새 모듈), `marong/app_chat.py`(경로 더하기) | TASK-421 | GPT | 1 | TC-514\~516 통과. API-250·251이 나열한 응답마다 시험 통과 |
| TASK-423 | 아이 소개 화면(SCR-180)과 흐름: 이름 짓기(SCR-174) → 아이 소개 → 입혀 보기(SCR-166), 내 마롱이(SCR-165)의 '아이 소개'·'꾸미기' 줄과 안내 띠, 입혀 보기의 작은 글 바꿈(화면 정의 9절) | SPEC-409, 407 | SCR-180, SCR-174, SCR-165, SCR-166, `marong/app_chat_static/character.html`·`character.js`·`profile.js` | TASK-422 | GPT | 1 | TC-517 통과. 낮·밤 테마와 360px 폭에서 넘치지 않음 |
| TASK-424 | 1인칭 구간(명세 3.1): `character_section`이 반려동물이고 `MARONG_PET_VOICE=1`일 때 줄 2·4·5를 바꾸고 600자 규칙을 지켜요. 구간이 그 친구의 모든 말 만들기(글 답, 선톡, 그림 화두 글, 일정 알림 글)에 붙는지 확인하고, 통화는 지금 이름 한 줄만 붙는 `tools/vertex_live/server.py`의 `setup`이 같은 구간을 붙이게 바꿔요(세션 조회 `find_session`이 캐릭터 칸을 함께 돌려줌)[사실: 2026-11-21 코드에서 통화 지시문에는 `bot_name` 한 줄만 붙음]. 기본 마롱이와 스위치 꺼짐은 글·통화 모두 지금과 바이트까지 같아요 | SPEC-406 | AI-40, `marong/unified_prompt.py`, `marong/unified_store.py`, `marong/app_session.py`, `run_app.py`, `tools/vertex_live/server.py` | TASK-421 | GPT | 1.5 | TC-518\~520 통과. `tools/vertex_live/test_unified_calls.py` 통과 |
| TASK-425 | 아이가 쓰는 그림일기 글: 일기를 쓰기 시작할 때 `diaries.character_id`를 적고, 반려동물이면 `pet-diary-v1`(명세 3.6) 지시로 써요. 일기 한 날 API-110에 `writer` | SPEC-408 | AI-41, API-110, `marong/diary_models.py`·`diary_worker.py`·`app_diary.py` | TASK-424 | GPT | 1 | TC-521 통과. `tests/test_diary_worker.py`·`tests/test_app_diary.py` 통과 |
| TASK-426 | 실제 모델 미통과 | `95914c4` | 첫 건강 질문의 답이 정해진 안내와 달라 중단했어요. 예상 비용 USD 0.000956. 스위치는 0으로 유지해요. |
| TASK-428 | 장면 그림 그리기 공통 함수(예: `marong/scene_picture.py`의 `draw`): 참조 이미지 2장(명세 3.3), 지시 글(3.4, 이름·대화 없음, `Marong` 바꿈, `SUBJECT` 6단어 이하), `MARONG_SCENE_MODEL`·`low`·크기, 받은 바이트 검사(지금 `diary_models`의 검사와 같은 방식), 거절·오류·90초 규칙, 부름마다 비용 | SPEC-410, 412 | AI-42, 새 모듈, `marong/diary_models.py`(검사 함수를 같이 쓰면) | TASK-421 | GPT | 1.5 | TC-526·527 통과 |
| TASK-429 | 장면 그림 작업 루프(앱 서버 안, 동시에 2개, 10분 임대, 다시 뜨면 임대 지난 줄을 `queued`로), 비용 세기와 예산 없음(SPEC-414: `diary.image_budget`가 `unlimited`를 받고 `drawing_allowed_in`이 합을 읽지 않고 허락, 틀린 값은 지금처럼 5), 사용량 그림 수(SPEC-415), 그림 읽기 API-262 | SPEC-410, 414, 415, 416 | TBL-176, API-262, 새 모듈, `marong/diary.py`, `marong/usage.py`(그림 수 함수 부르기만), `run_app.py`(루프 시작) | TASK-428 | GPT | 1.5 | TC-528\~531 통과. API-262가 나열한 응답마다 시험 통과 |
| TASK-430 | 그림 화두에 장면 그림(명세 3.5): `AppProactive._send`·`_hello`의 두 곳, 메시지 `meta.scene`, 선 전화의 30분 전 미리 그리기와 `app_rings.scene_picture_id`, REQ-281·282 뒤 글, 그림 세트에 `petScene`(31장을 보고 마롱이만의 장면을 거짓으로. 고른 목록과 이유를 PR에 적음), 글 대화 화면의 그림 주소 검사(`topicPicture`)와 통화 화면의 `TOPIC_RE`에 `/chat/api/scenes/{id}` 모양 더하기 | SPEC-411, 416 | SCR-107, SCR-002, `marong/unified_delivery.py`, `marong/topics.py`·`topic_store.py`, `marong/topics/v1/topics.json`, `marong/app_chat_static/chat.js`, `tools/vertex_live/static/app.js` | TASK-429 | GPT | 2 | TC-532·533 통과. `tests/test_topic_pictures.py`·`test_topics.py`·`test_proactive.py`·`test_app_ring.py` 통과 |
| TASK-431 | 일기 장면 그림: `DiaryWorker._draw`의 그리는 부름을 SPEC-410으로(참조는 그 캐릭터의 `front`와 마음 날씨 표정), 다시 그리기 같은 아이, 그림 없는 날 SCR-113#no-drawing, SCR-115 글, 보관 해제한 캐릭터면 다시 그리기 버튼 없음 | SPEC-413 | AI-42, SCR-113, SCR-115, `marong/diary_worker.py`, `marong/app_chat_static/diary/diary.js` | TASK-429, TASK-425 | GPT | 1.5 | TC-534·535 통과. `tests/test_diary_worker.py` 통과 |
| TASK-432 | 관리자 그림 비용 API-266과 관리자 첫 화면(SCR-169)의 '이번 달 그림 비용' 줄 | SPEC-427, 414 | API-266, SCR-169, `marong/app_admin.py`, `marong/app_chat_static/admin.js` | TASK-429 | GPT | 0.5 | TC-536 통과. API-266이 나열한 응답마다 시험 통과 |
| TASK-433 | 실제 모델 미통과 | `92aacf4` | 공개 사진으로 4회 시험했어요. 마지막 시험은 푸들의 표정과 고양이 특징표에서 탈락했어요. 장면 0/30, 전체 예상 비용 USD 0.436192. |
| TASK-434 | 아이템 목록 폴더 읽기와 검사(명세 3.9: 파일, 형식·크기, 레이어 자리 상자 밖 불투명 5% 이하, 대장 줄, 글꼴 라이선스, `priceKrw = 0`), 처음 넣기(SPEC-426, 두 번 해도 줄 그대로, 걸린 것은 `new`와 로그 `decor_seed_skip`), 파일 내려 주기 API-257(목록에 적힌 파일만) | SPEC-417, 425, 426 | TBL-175, API-257, 새 모듈(예: `marong/decor.py`), 시험용 작은 합성 폴더(`tests/fixtures/` 아래) | TASK-421 | GPT | 1.5 | TC-538\~540 통과. API-257이 나열한 응답마다 시험 통과 |
| TASK-435 | 처음 아이템 48개를 `marong/decor/v1/`에 넣기: 처음 셋(지금 일기장 배경, 속지 `manuscript`, 글꼴 Gaegu = 지금 `diary/Gaegu-Regular.woff2`와 `Gaegu-OFL.txt`)과 모자 4·옷 4·목도리 2·배경 6·속지 4·글꼴 5·스티커 20. 입는 아이템은 투명 배경으로 한 장 그린 뒤 템플릿 5종의 `slots` 자리 상자에 맞춰 레이어를 만들고, 맞지 않는 템플릿만 그 템플릿을 참조로 다시 그려요[새 제안]. 화풍은 그림 세트 화풍(`marong/topics/v1`)에 맞춰요. 글꼴 후보는 아래 '확인'의 표예요. `items.json`(영어 `prompt` 포함)과 `licenses.csv`를 채우고 글꼴마다 OFL 원문을 폴더에 둬요 | SPEC-425, 426 | `marong/decor/v1/` | TASK-434 | GPT | 3 | TC-541 통과(48개 모두 검사 통과), 그림 비용 10달러 이하. 글꼴 `woff2` 크기와 일기장 첫 화면 시간을 PR에 적음 |
| TASK-436 | 관리자 아이템 API-263\~265와 화면 SCR-186, 관리자 첫 화면의 '아이템' 줄 | SPEC-417 | API-263\~265, SCR-186, SCR-169, `marong/app_admin.py`, `marong/app_chat_static/admin.js`·새 `admin-items` 페이지 | TASK-434 | GPT | 1 | TC-542·543 통과. 세 API가 나열한 응답마다 시험 통과 |
| TASK-437 | 상점·받기·보관함 API-252\~254와 화면 SCR-181\~183, 글 대화 메뉴(SCR-109)의 '상점'·'보관함' 줄 | SPEC-418, 419 | API-252\~254, TBL-177, SCR-181\~183, SCR-109, `marong/app_chat.py`, 새 페이지(`shop`·`closet`) | TASK-434 | GPT | 2 | TC-544\~546 통과. 세 API가 나열한 응답마다 시험 통과 |
| TASK-438 | 차림 바꾸기 API-255(한 트랜잭션, `outfit_firsts`, 여러 자리면 앞 하나만 반응)와 얼굴 위 레이어: API-216 `character.outfit`의 `layerUrl`, 글 대화 머리말·말풍선 얼굴(SCR-107), 통화 얼굴(SCR-002), 보관함·아이템 보기 미리 보기를 몸→목→머리 순서로 겹침 | SPEC-420, 421 | API-255, API-216, TBL-178, TBL-179, SCR-107, SCR-002, SCR-182, SCR-183, `marong/app_chat_static/chat.js`·`unified.js`, `tools/vertex_live/static/app.js` | TASK-437 | GPT | 1.5 | TC-547·548 통과. API-255가 나열한 응답마다 시험 통과 |
| TASK-439 | 아이템 반응 선톡(명세 3.11): 선톡 루프가 `waiting` 줄을 먼저 보고 게이트를 지키며, 장면 그림(용도 `reaction`)과 반응 한 줄(AI-43)로 보내고, 못 그리면 `excited`에 레이어를 겹친 그림(`fallback` 참, 비용 0), 글 실패면 정해 둔 줄 | SPEC-422 | AI-43, TBL-179, TBL-176, `marong/unified_delivery.py`, 장면 그림 모듈 | TASK-438, TASK-429 | GPT | 1.5 | TC-549 통과. `tests/test_proactive.py` 통과 |
| TASK-440 | 일기장 꾸밈 API-258·259와 화면 SCR-184, 일기장 한 날(SCR-113·116·117)이 배경·속지·글꼴(`@font-face`, `font-display: swap`)을 그 값으로 그림. 줄이 없으면 지금 모습 그대로 | SPEC-423 | API-258, API-259, TBL-180, SCR-184, SCR-113, `marong/app_diary.py`, `marong/app_chat_static/diary/diary.js`·`diary.css` | TASK-437 | GPT | 1.5 | TC-550·551 통과. 두 API가 나열한 응답마다 시험 통과 |
| TASK-441 | 스티커 API-260·261(한 트랜잭션, 일기 줄 잠그고 10개 세기, `removed_at`)과 화면 SCR-185(끌기, 두 손가락, 모서리 손잡이, 떼기, 움직임 줄이기), SCR-113의 스티커 그리기 | SPEC-424 | API-260, API-261, TBL-181, SCR-185, SCR-113, `marong/app_diary.py`, `marong/app_chat_static/diary/diary.js` | TASK-437 | GPT | 2 | TC-552\~555 통과. 두 API가 나열한 응답마다 시험 통과 |
| TASK-442 | 기존 문서 맞추기(명세 3.7 표): 통합 앱 명세(SPEC-377·379·385와 3.5·3.7), 반려동물 명세(SPEC-318·324와 SPEC-332\~336 보류 줄), 일기 명세(쓰기·그리기·예산), 선 전화 명세('서버는 그림을 그리지 않음')의 그 행에 '바뀜 → pet-app.md SPEC-…' 표시, README의 새 설정값 설명. 새 설계를 쓰지 않고 3.7이 적은 내용만 옮겨요 | SPEC-406\~429 | 위 문서, `README.md` | TASK-441 | GPT | 0.5 | 3.7 표의 행마다 고친 곳이 PR 설명에 있음. `git grep -n "MARONG_SCENE_PICTURES"`가 README에 있음 |
| TASK-443 | 서버 반영(GPT 인계의 '반영' ①\~⑦)과 되돌리기 준비. PR이 합쳐질 때마다 같은 절차 | SPEC-406\~429 | 운영 DB, 앱 서버, 통화 서버 | PR마다 그 PR의 마지막 TASK | GPT | 1 | TC-556의 서버 쪽 확인 통과. 백업·되돌리기 경로, 켠 스위치와 시각, 확인 숫자(개수만)가 PR 설명에 있음 |
| TASK-444 | REQ-521 P95 재기: `MARONG_SCENE_PICTURES=1` 뒤 운영 서버에서 장면 그림 작업 5개를 동시에 두고 20장의 맡긴 때부터 저장까지 시간을 재요. 시험용 장면 그림은 동희님 계정의 시험 캐릭터로 그리고 친구에게 보내지 않아요 | SPEC-410 | 운영 앱 서버(읽기와 시험 작업만) | TASK-443 | GPT | 0.5 | TC-557 통과(P95 90초 이하), 비용 1달러 이하. 숫자를 시험 계획 결과 칸에 적음 |

## 확인

- 모든 TASK가 SPEC을 하나 이상 가리키고, SPEC-406\~429가 모두 TASK를 가져요: 406(424·426), 407(422·423), 408(425), 409(422·423), 410(428·429·433·444), 411(430), 412(428), 413(431), 414(429·432), 415(429), 416(429·430), 417(434·436), 418(437), 419(437), 420(438), 421(421·438), 422(439), 423(440), 424(441), 425(434·435), 426(434·435), 427(432), 428(427·433), 429(427·433). 442·443은 모두를 가리켜요.
- 끝 조건마다 시험이나 확인할 수 있는 결과가 있어요.
- 순서가 TASK ID 순서와 다른 곳은 TASK-427 하나예요(D120이 나중에 더해져 번호가 뒤지만 PR ①에 들어가요). 고리는 없어요.
- 글꼴 후보(TASK-435): 2026-11-21 KST Claude가 `google/fonts` 저장소 `main`의 `ofl/<이름>/OFL.txt`를 받아 첫 줄을 읽었어요[사실]. 모두 SIL Open Font License 1.1이에요. 나눔손글씨 펜은 예약 글꼴 이름(Reserved Font Name)이 있어서 글자를 줄인(subset) 파일을 그 이름으로 쓸 수 없어요. 그래서 후보에서 뺐어요. 파일 크기와 한글 글자 수는 [확인 안 함]이에요. TASK-435에서 받을 때 다시 확인하고 OFL 원문을 폴더에 둬요.

| 순서 | 글꼴 | 저작권 줄(OFL.txt 첫 줄) | 예약 이름 |
| --- | --- | --- | --- |
| 처음 아이템 | Gaegu | Copyright 2018 The Gaegu Project Authors | 없음(지금 일기장 글꼴, 저장소에 OFL 원문 있음) |
| 1 | Gamja Flower | Copyright (c) YoonDesign Inc. | 없음 |
| 2 | Hi Melody | Copyright (c) YoonDesign Inc. | 없음 |
| 3 | Poor Story | Copyright (c) YoonDesign Inc. | 없음 |
| 4 | Yeon Sung | Copyright 2018 The BM YEONSUNG Project Authors | 없음 |
| 5 | Cute Font | Copyright 2018 The Cute Font Project Authors | 없음 |
| 예비 | Single Day | Copyright 2015 DXKorea Inc. | 없음 |

- 열린 질문: 질문 A(기본 마롱이도 입을까)는 체크포인트를 건너뛰어 기본값 '반려동물 캐릭터만'으로 진행해요(명세 6절). 추억 모드(D121)는 답이 오면 SPEC 430번, TASK 445번부터 더해요. 운영 서버의 지금 `MARONG_DIARY_IMAGE_BUDGET_USD` 값은 [확인 안 함]이고 반영 ④에서 `unlimited`로 둬요.

## 11단계 진행

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-420 | 로컬 시험 통과 | `59eb313` | 임시 PostgreSQL에서 021과 통화 009·010 이후 022를 두 번 적용했어요. 기존 행 백필, 제약 조건 및 두 서버 역할의 접근 권한을 확인했어요. |
| TASK-421 | 프로필·설정 시험 통과 | `6d63d98` | 기본 프로필과 적용한 캐릭터의 옷 세 자리, 템플릿, 소개 여부, 기능 설정을 확인했어요. 꾸미기 API의 비활성 응답은 해당 API 구현 후 확인해요. |
| TASK-427 | 로컬 시험 통과 | `a84082c` | 두 합성 사진 중 지정한 사진을 자른 PNG가 정면 요청의 첫 참조로 들어갔어요. 특징표 수정 시 선택이 유지되고 파일을 잃으면 재업로드할 수 있어요. 표정 요청에는 정면 그림만 들어갔고 완료 시 사진과 선택이 지워졌어요. |
| TASK-422 | 로컬 시험 통과 | `679bea5` | 아이 소개 조회·저장, 로그인과 Origin, 입력 검증, 추천과 직접 선택한 목소리의 우선순위를 확인했어요. |
| TASK-423 | 브라우저 시험 통과 | `a06a26e` | 360px 낮·밤 화면에서 아이 소개 저장·건너뛰기, 추천 목소리 표시, 수정 후 프로필 복귀를 확인했어요. |
| TASK-424 | 로컬 시험 일부 통과 | `ccb07b5`, `2d5f487` | 1인칭 구간과 기본 지시문 보존을 확인했어요. 일정 알림은 현재 고정 문구를 사용하며 모델 요청 경로가 없어요. |
| TASK-425 | 로컬 시험 통과 | `c314d77` | 일기를 쓴 캐릭터 고정, 부름의 지시문 버전, API-110의 작성자와 보관 상태를 확인했어요. |
| TASK-426 | 실제 모델 미통과 | `95914c4` | 첫 건강 질문의 답이 정해진 안내와 달라 중단했어요. 예상 비용 USD 0.000956. 스위치는 0으로 유지해요. |
| TASK-428 | 로컬 시험 통과 | `ef2af27` | 참조 이미지 두 장, 반려동물 이름의 제외, 응답 검증 및 재시도 비용 합계를 확인했어요. |
| TASK-429 | 로컬 시험 통과 | `7b3fbd9` | 두 건씩 임대, 만료된 작업 회수, 사용량 기록, 로그인 계정의 그림 조회와 다른 계정 차단을 확인했어요. |
| TASK-430 | 로컬 회귀 시험 통과 | `38e2e9c` | 화두 시각 30분 전 작업의 재등록 방지와 기존 화두·선톡·벨 회귀 시험을 확인했어요. 실제 앱 화두 카드는 운영 확인 전이에요. |
| TASK-431 | 로컬 회귀 시험 통과 | `46cb159` | 기존 일기 작업·조회 회귀 시험이 통과했어요. 실제 그림 모델과 일기 화면의 실기기 확인은 대기예요. |
| TASK-432 | 로컬 시험 통과 | `0c1dc47` | 한국 시각 월 합계와 무제한 일기 예산, 캐릭터 예산 비율 및 관리자 접근 차단을 확인했어요. |
| TASK-433 | 실제 모델 미통과 | `92aacf4` | 공개 사진으로 4회 시험했어요. 마지막 시험은 푸들의 표정과 고양이 특징표에서 탈락했어요. 장면 0/30, 전체 예상 비용 USD 0.436192. |
| TASK-434 | 대기 | | |
| TASK-435 | 대기 | | |
| TASK-436 | 대기 | | |
| TASK-437 | 대기 | | |
| TASK-438 | 대기 | | |
| TASK-439 | 대기 | | |
| TASK-440 | 대기 | | |
| TASK-441 | 대기 | | |
| TASK-442 | 대기 | | |
| TASK-443 | 대기 | | |
| TASK-444 | 대기 | | |
