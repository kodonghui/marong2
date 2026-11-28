# 기본 마롱이에게 입히기 작업 목록(10단계 WBS, pet-app 기능 변경 1)

2026-11-28 작성(Claude, 항목 253). 입력: 도메인 [pet-app.md 9절](../01-domain/pet-app.md#9-기능-변경-1-기본-마롱이에게-입히기2026-11-28-d192)(D192), 요구사항 REQ-690\~697과 [기능 변경 목록 1](../02-prd/pet-app.md#기본-마롱이-입히기-기능-변경-목록-1), 흐름 FL-189·190·192, 명세 SPEC-570\~575와 [3.14](../04-functional-spec/pet-app.md#314-기본-마롱이-차림spec-570575-기능-변경-1), 표 [마이그레이션 025](../../marong/migrations/025_marong_outfit.sql)(TBL-190, TBL-176·179 바꿈), 계약 API-330(`api/pet-app.openapi.yaml`)과 API-216의 `marongOutfit`(`api/unified.openapi.yaml`), 화면 [pet-app.md 12절](../08-screens/pet-app.md#12-기능-변경-1-기본-마롱이에게-입히기2026-11-28-d192-제안), 목업 [marong-wear-mockup.md](../../design/marong-wear-mockup.md).

상태: 2026-11-28 10 단계 체크포인트 통과(D193, 오랑이 답 '추천안 모두 승인', 요청 `msg_d615ed1cdc0e`). 시작 조건은 셋이에요: ① 사용자님이 목업을 확인함(M1\~M3, D194 모두 추천대로) ② 도메인 질문 1\~4(D194 모두 추천대로)와 기능 변경 목록 1(D193)의 답 ③ 이 설계 PR이 `main`에 합쳐짐. ①②는 됐고 ③만 남았어요. 셋이 되면 마롱이가 구현 작업자를 따로 시작해요.

## GPT 인계

- 목표: 기본 마롱이를 쓰는 사람도 상점에서 받은 모자·옷·목도리를 마롱이에게 입혀요. 차림은 친구마다 하나이고 글 대화·통화·내 마롱이·상점 미리 보기·보관함의 마롱이 얼굴 그림 모두에 겹쳐요. 처음 입히면 그 차림으로 그린 그림과 함께 반응 선톡을 한 번 하고, 일기 그림 지시에 차림이 들어가요. 사용자님 말(2026-11-28 KST): "야 이거 왜 마롱이는 못입혀", 결정 '기본 마롱이에게도 입히기(목업부터)'(D192).
- 시작: 이 설계 PR이 `main`에 합쳐지고 마롱이가 지시하면 `main` 머리에서 새 브랜치 `codex/marong-wear`. 초안 PR 하나예요.
- 읽을 것: 명세 SPEC-570\~575와 3.14, 1절 5의 `MARONG_DEFAULT_WEAR` 줄. 비교로 SPEC-420\~422(반려동물 차림·얼굴·반응, 지금 코드와 같음). 계약 API-330, `Closet`, `WornOutfit`, 프로필 `marongOutfit`·`features.defaultWear`. 마이그레이션 025와 [05 pet-app.md 8절](../05-erd/pet-app.md#8-기능-변경-1-기본-마롱이-차림마이그레이션-025-2026-11-28-제안). 화면 12절과 목업. 이 밖의 문서는 읽지 않아도 돼요.
- 이미 된 것: 설계 문서, 마이그레이션 025 초안(2026-11-28 `pgserver`에서 두 번 적용과 거절 확인, 시험 코드는 아님), 목업 전용 레이어 맞춤 스크립트 [`design/marong-wear-mockup/fit-layers.py`](../../design/marong-wear-mockup/fit-layers.py)(제품 경로에 두지 않음. TASK-600은 같은 상자 값으로 제품 쪽 도구를 따로 만들어요). 코드·DB·서버는 바꾸지 않았어요.
- 순서: TASK-600 → TASK-601 → TASK-602 → (TASK-603, TASK-604, TASK-605, TASK-606 서로 따로) → TASK-608(TASK-605 뒤) → TASK-607(반영). TASK-608은 이미 운영 중인 반려동물 경로를 고치는 것이라(D195) 스위치 밖이에요.
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md), Node와 Playwright(360·430px, 낮·밤). 그림 모델과 글 모델은 가짜예요. TASK-600에서 그림 방식 B로 다시 그리는 아이템만 진짜 그림 모델을 불러도 돼요(상한 1달러, 실제 비용을 PR에 적음).
- 반영: 서버 반영을 해요(TASK-607). 마롱이가 사용자님 승인을 받은 뒤에만 해요. 마이그레이션 025, 파일(`marong/decor/v1/*/marong.png`, `items.json`, 앱 서버 코드, 통화 화면 `tools/vertex_live/static/app.js`), drop-in이나 설정 파일의 `MARONG_DEFAULT_WEAR=1`(처음엔 0으로 넣고 확인 뒤 1), 재시작은 대화·통화가 없을 때 `marong-app`과 통화 서버. 되돌리기는 SPEC-575 순서예요: ① `MARONG_DEFAULT_WEAR=0`으로 재시작(새 코드 그대로) ② 확인 SQL(SPEC-575)이 0이 될 때까지 기다림(최대 10분) ③ 그 뒤에만 코드를 되돌림. 표와 줄은 남겨요. 되돌리기 스크립트(`~/marong-deploy/<날짜>-marong-wear/`)는 ②가 0이 아니면 ③으로 가지 않고 멈춰요. 업데이트 내역 `marong/changelog/<반영 폴더 이름>.json`을 반영 전에 더해요(친구가 알아채는 변화).
- 하면 안 되는 것: `outfits`(TBL-178)의 키나 칸 바꾸기(기본 마롱이는 TBL-190). 기본 마롱이의 그림 화두를 새로 그리기(REQ-695, 질문 3의 답이 ②가 아니면). 얼굴 그림(`marong/call/static/face/v1/`)을 바꾸거나 `v2`로 옮기기. 장면 그림 지시 글에 친구 이름·대화 글 넣기. 반응 선톡을 선톡 게이트 밖에서 보내기. 운영 DB에 시험 줄 넣기.
- 겹치는 파일: `marong/app_decor.py`, `marong/app_profile.py`, `marong/decor.py`, `marong/decor_reactions.py`, `marong/scene_picture.py`, `marong/scene_worker.py`, `marong/diary_models.py`, `marong/app_chat_static/chat.js`·`decor.js`·`unified.js`, `tools/vertex_live/static/app.js`, `tests/test_decor.py`, `tests/test_proactive.py`, `tests/test_scene_picture.py`, `tests/test_diary_worker.py`, `apps/android/test/pet-decor.e2e.cjs`, `tests/pg.py`. 2026-11-28 열린 구현 PR(#122·#133·#137·#139·#146) 가운데 이 파일들을 고치는 것은 없어요(PR #139는 `tests/pg.py`를 고칠 수 있으니 합칠 때 순서를 봐요). BUG-129(열림)의 기본 마롱이 상태 기대는 기능 변경 목록 1-19대로 `MARONG_DEFAULT_WEAR=0` 조건을 붙여요.
- 사람 확인: TC-769(반영 뒤 사용자님 폰에서 글 대화·통화·보관함). 현경님 폰은 사용자님이 부탁해요.
- 끝 조건: TASK-600\~606·608의 끝 조건 시험 통과, 아래 명령이 모두 통과, 반영 뒤 TC-769의 서버 쪽 확인.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적어요. 문구가 비어 있는 곳은 지어 넣지 말고 거기 적어요.

```bash
# 저장소 루트에서. 윈도우에서는 .venv/Scripts/python (AGENTS.md)
.venv/bin/python tests/test_decor.py            # TC-760~763, 그 전 TC-538~555(그대로 통과)
.venv/bin/python tests/test_marong_outfit_schema.py   # TC-770 (새 파일)
.venv/bin/python tests/test_unified_profile.py  # TC-762의 프로필 쪽
.venv/bin/python tests/test_proactive.py && .venv/bin/python tests/test_scene_picture.py   # TC-767
.venv/bin/python tests/test_diary_worker.py && .venv/bin/python tests/test_diary.py      # TC-768
(cd apps/android && npm ci && npm test && npm run test:browser)   # TC-764·765. Playwright가 없으면 건너뛴 채 통과하니 출력에서 확인
node tools/vertex_live/test_fallback.cjs        # 통화 화면 시험 묶음(TC-766은 새 .cjs 시험으로 더함)
```

## 작업

| TASK | 할 일 | 명세 | 고치는 곳 | 앞 작업 | Owner | 일(날) | 끝 조건 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-600 | 착용 아이템 10개의 `marong.png`(1024 투명)를 3.14 자동 맞춤으로 만들고, 옷 4개(`oat-sweater`·`blue-raincoat`·`forest-vest`·`apricot-apron`)만 그림 방식 B로 다시 그려 같은 상자에 맞춤(D194 M2). 모자 4개·목도리 2개는 자동 맞춤 그대로. `items.json`의 `files`에 `marong.png`를 더하고, 목록 검사(3.9)에 여섯 번째 틀 `marong`의 자리 상자를 더함. 레이어를 만드는 도구는 `tools/` 아래 새 파일(제품 쪽), 상자 값은 3.14 그대로 | SPEC-574, 3.14 | `marong/decor/v1/`, `marong/decor.py`, `tools/` 새 도구 | 없음 | GPT | 1 | TC-760, TC-541(그대로 통과, 48개). 다시 그린 아이템과 비용을 PR에 적음 |
| TASK-601 | 마이그레이션 025와 시험 DB 순서(`tests/pg.py`에 025 적용 함수) | TBL-190, TBL-176·179 바꿈 | `marong/migrations/025_marong_outfit.sql`(초안 그대로 쓰거나 고친 점을 PR에), `tests/pg.py`, 새 `tests/test_marong_outfit_schema.py` | 없음 | GPT | 0.5 | TC-770 |
| TASK-602 | 바꾸는 친구는 세션으로만 정함(SPEC-570). 스위치 `MARONG_DEFAULT_WEAR`, API-330, 보관함 API-254의 기본 마롱이 `outfit`, 프로필 API-216의 `marongOutfit`·`features.defaultWear`. 차림 읽기 함수 하나가 캐릭터와 기본 마롱이를 갈라 읽음 | SPEC-570, 571 | `marong/pet_app_settings.py`, `marong/app_decor.py`, `marong/app_profile.py` | TASK-600, TASK-601 | GPT | 1 | TC-761, TC-762, TC-763, TC-771. API-330이 나열한 응답마다 시험 통과 |
| TASK-603 | 앱 화면: 글 대화 머리말·말풍선·입력 중 얼굴(SCR-107), 내 마롱이의 얼굴·'꾸미기' 줄·캐릭터 목록(SCR-165), 아이템 보기 미리 보기와 '입혀 볼래'(SCR-182), 보관함 입히기(SCR-183)에 기본 마롱이 차림. 스위치가 꺼지면 지금 #default-marong 그대로 | SPEC-571, 08 12절 | `marong/app_chat_static/chat.js`·`decor.js`·`unified.js`(와 css) | TASK-602 | GPT | 1 | TC-764, TC-765, TC-546(스위치 0에서 그대로 통과) |
| TASK-604 | 통화 화면: 기본 마롱이 얼굴 모든 그림에 레이어(지금 `refreshProfile`이 `character.outfit`만 읽음 → `marongOutfit`도). 얼굴 `src`만 바뀌고 레이어는 그대로, 튀기는 상자 전체 | SPEC-571, 3.14 | `tools/vertex_live/static/app.js`(와 css) | TASK-602 | GPT | 0.5 | TC-766 |
| TASK-605 | 그림 작업은 첫 착용 하나에 하나(명세 3.15: `scene_job_id`, 만들기·연결 한 트랜잭션, 작업 줄과 겹친 그림 줄 분리). 스위치 0이면 기본 마롱이 대기 줄을 비우고(`waiting` → `skipped`, `queued` → `failed`/`disabled`, 그림 모델 부름 없음), 다시 켤 때 1시간 넘게 지난 `waiting`은 `skipped`(SPEC-575). 기본 마롱이 반응 선톡: 첫 착용 줄(`character_id` 비움)을 선톡 루프가 보고, 그때 기본 마롱이를 쓰는지 확인, 장면 그림 대상 기본 마롱이(참조 `01-neutral`·`02-big-laugh`, 지시 `scene-marong-v1`), 실패면 `05-excited` 겹친 그림 | SPEC-572, 575, 3.14 | `marong/decor_reactions.py`, `marong/scene_picture.py`, `marong/scene_worker.py` | TASK-602 | GPT | 1 | TC-767, TC-772, `tests/test_proactive.py` 통과 |
| TASK-606 | 기본 마롱이 일기 그림 지시에 차림 줄(밤 작업과 다시 그리기). 차림이 없으면 지시 글이 바이트까지 같음 | SPEC-573 | `marong/diary_models.py`, `marong/diary_worker.py` | TASK-602 | GPT | 0.5 | TC-768 |
| TASK-608 | 반려동물 반응 선톡의 그림 작업 다시 쓰기: 첫 착용 하나에 그림 작업 하나(명세 3.15). TASK-605와 같은 함수로 두 경로를 함께 고침. 스위치와 상관없이 반려동물 경로에 걸림 | SPEC-422(D195 손봄) | `marong/decor_reactions.py`, `marong/unified_delivery.py` | TASK-605 | GPT | 0.5 | TC-773, `tests/test_proactive.py` 통과 |
| TASK-607 | 서버 반영(승인 뒤): 해시 비교, 백업, 025, 파일, 스위치 0으로 재시작해 운영 그대로인지 보고 1로 켬, 업데이트 내역, 로그 5분. 되돌리기 스크립트는 SPEC-575 순서(끄기 → 확인 SQL 0 → 코드)를 지키고 0이 아니면 멈춤 | REQ-697, SPEC-575 | 서버 `ko-family`(서울에서는 Tailscale 주소), 되돌리기 스크립트 `~/marong-deploy/<날짜>-marong-wear/` | TASK-600\~606, TASK-608 | GPT | 0.5 | TC-769의 서버 쪽 |

합: 6일 남짓(한 사람 기준). TASK-603·604·605·606은 같이 해도 돼요.

## 확인

- 운영 사실(2026-11-28 KST, 읽기만): 앱 서버 프로세스 `MARONG_DECOR=1`, `MARONG_SCENE_PICTURES=1`, `MARONG_PET_VOICE=1`, `MARONG_CHARACTER=0`. `characters` 2줄, `outfits` 0줄, `decor_owned` 3줄, 올린 아이템 48개. `MARONG_DEFAULT_WEAR`는 아직 없어요.
- 그림 맞춤(2026-11-28, 저장소 그림을 잼): 얼굴 21장의 몸 테두리가 같아서 레이어 한 장이 모두에 맞아요(명세 3.14).

## 11단계 진행

| TASK | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-600 | 진행 중 | | TC-760 선행 시험 실패 확인, 모자·목도리 6개 자동 맞춤. 옷 4개 생성은 인증 대기 |
| TASK-601 | 완료 | `0f35eff` | TC-770 임시 Postgres에서 025 반복 적용·권한·제약·기존 claim 위험·되돌리기 순서 확인 |
| TASK-602 | 진행 중 | | API·프로필·보관함 핵심 시험 통과, 전체 응답 검증 중 |
| TASK-603 | 진행 중 | | 프로필·보관함 브라우저 일부 사례 통과, 전체 화면 확인 중 |
| TASK-604 | 진행 중 | | 통화 기본 차림 브라우저 일부 사례 통과, 21개 표정 확인 중 |
| TASK-605 | 진행 중 | | 작업 공유·비우기·겹친 그림 일부 사례 통과, 전체 선톡 경로 확인 중 |
| TASK-606 | 진행 중 | | 차림 지시의 빈 값 호환 확인, 밤 작업·다시 그리기 검증 중 |
| TASK-607 | 보류 | | 사용자 승인 뒤 반영. 이번 작업에서는 운영 반영하지 않음 |
| TASK-608 | 진행 중 | | 동시 작업·트랜잭션 중단·전달 그림 일치 일부 사례 통과, 전체 검증 중 |
