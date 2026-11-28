# 기본 마롱이에게 입히기 작업 목록(10단계 WBS, pet-app 기능 변경 1)

2026-11-28 작성(Claude, 항목 253). 입력: 도메인 [pet-app.md 9절](../01-domain/pet-app.md#9-기능-변경-1-기본-마롱이에게-입히기2026-11-28-d192)(D192), 요구사항 REQ-690\~697과 [기능 변경 목록 1](../02-prd/pet-app.md#기본-마롱이-입히기-기능-변경-목록-1), 흐름 FL-189·190·192, 명세 SPEC-570\~575와 [3.14](../04-functional-spec/pet-app.md#314-기본-마롱이-차림spec-570575-기능-변경-1), 표 [마이그레이션 025](../../marong/migrations/025_marong_outfit.sql)(TBL-190, TBL-176·179 바꿈), 계약 API-330(`api/pet-app.openapi.yaml`)과 API-216의 `marongOutfit`(`api/unified.openapi.yaml`), 화면 [pet-app.md 12절](../08-screens/pet-app.md#12-기능-변경-1-기본-마롱이에게-입히기2026-11-28-d192-제안), 목업 [marong-wear-mockup.md](../../design/marong-wear-mockup.md).

상태: 2026-11-28 10 단계 체크포인트 통과(D193, 오랑이 답 '추천안 모두 승인', 요청 `msg_d615ed1cdc0e`). 시작 조건은 셋이에요: ① 사용자님이 목업을 확인함(M1\~M3, D194 모두 추천대로) ② 도메인 질문 1\~4(D194 모두 추천대로)와 기능 변경 목록 1(D193)의 답 ③ 이 설계 PR이 `main`에 합쳐짐. ①②는 됐고 ③만 남았어요. 셋이 되면 마롱이가 구현 작업자를 따로 시작해요.

## 결정 D196

2026-11-28 체크포인트 통과: 사용자님 승인 근거는 2026-11-23·27 위임 말씀과 오랑이의 '추천안 승인'(`msg_780be6374ad9`)이에요. SPEC-574의 기존 등록 거절을 대신해 등록·상점·반려동물은 기존대로 두고 기본 마롱이 레이어가 없는 아이템만 기본 마롱이 차림에서 제외해요. 상점 상세와 보관함의 안내 '이 옷은 아직 마롱이한테 맞는 모양이 없어.'는 마롱이 결정(승인 범위 안, `msg_6e7b834de1c8`)이에요. D193 1-5의 기본 마롱이 레이어 등록 필수 부분을 대체하며 옷 4개 제작 결정은 유지해요.

## 결정 D197

2026-11-28 옷 네 벌 생성 1회 승인: 비용은 사용자님의 항목 253 `e4485` 승인, 운영 설정 사용 방법은 사용자님의 주말 위임(11-28 토 '너가 다른애들 승인을 하던 말던 해라', 월요일 09시까지 오랑이)과 오랑이 답 '허용(추천안 승인)'(`msg_9ae444047205`)에 따릅니다. 마롱이가 서울 인증 부재 시 그리지 않도록 인계한 안전 조건을 이번 한 번에 한해 바꿨어요(`msg_96fbcba0c62f`). 운영 앱 설정의 이미지 인증은 운영 서버 임시 폴더에서만 사용하고, 키는 출력·복사·저장하지 않아요. 운영 DB·파일·서비스는 읽기만 하며, 네 아이템 각각 최대 두 번 호출하고 결과 그림만 가져온 뒤 임시 폴더를 지워요. 사용 모델은 저장소 가격표의 이미지 모델이며 호출 수와 비용은 실행 후 기록해요.

실행 결과: 첫 네 번은 0.062316달러, 캐릭터가 함께 그려져 쓸 수 없었던 조끼의 단일 재시도는 0.015639달러였어요. 합계 5회·0.077955달러이고 사용량 없는 추정 호출은 0회예요. 네 결과를 서울로 가져와 위치를 맞췄어요. 첫 임시 폴더는 결과 파일 소유권 때문에 자동 정리가 실패해 승인된 같은 폴더만 권한을 사용해 지웠고, 재시도 폴더도 지운 뒤 해당 이름의 폴더가 0개임을 확인했어요. 운영 서비스·DB는 바꾸지 않았어요.


## 결정 D198

2026-11-28 마롱이 결정, 승인 명세 정합(오랑이 지침: 승인된 결정끼리 충돌을 푸는 정정은 진행 후 기록, `msg_cebb772c469d`). 그림은 시작할 때 고정한 차림으로 그린 것으로 봐요. 그 뒤 친구가 정상적으로 다른 차림으로 바꾸어도, 고정 차림의 각 아이템이 받은 상태이고 상점에서 내려가지 않았으며 레이어의 자리·파일 해시가 유효하면 성공 그림을 유지해요. 고정 아이템을 내리거나 받지 않은 상태가 되거나 그 레이어가 없어지거나 바뀌면 그 결과는 사용하지 않아요. 기본 마롱이와 반려동물의 일기·반응·장면 그림에 같은 기준을 적용해요. 반응은 SPEC-572·422의 대상 아이템을 벗거나 캐릭터를 바꾸면 반응을 건너뛰는 규칙도 그대로예요. 이 결정은 SPEC-573의 그리는 때 차림과 D196의 유효 레이어를 함께 적용해요.

## 결정 D199

2026-11-28 마롱이 정정(`msg_ab491592a003`): D193의 스위치 0 기존 동작 보존을 적용해요. 해시 기록이 없는 기존 반려동물 작업·완료 장면은 main 방식으로 처리하고, 고정 차림 검사는 해시 기록이 있는 새 작업에만 적용해요. 스위치 0에서 반려동물 그림과 일기는 기존 아이템 내림 처리·호출 수를 유지해요. 통화 화두도 대기 없이 같은 완료 그림 검사를 거쳐요. 승인된 TASK-608의 반려동물 반응 작업 재사용은 그대로예요.

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
| TASK-600 | 착용 아이템 10개의 `marong.png`(1024 투명)를 3.14 자동 맞춤으로 만들고, 옷 4개(`oat-sweater`·`blue-raincoat`·`forest-vest`·`apricot-apron`)만 그림 방식 B로 다시 그려 같은 상자에 맞춤(D194 M2). 모자 4개·목도리 2개는 자동 맞춤 그대로. `items.json`의 `files`에 `marong.png`를 더하고, 등록과 별개로 `marong` 자리 상자를 검사해 기본 마롱이 착용 가능 여부를 정함(D196). 레이어를 만드는 도구는 `tools/` 아래 새 파일(제품 쪽), 상자 값은 3.14 그대로 | SPEC-574, 3.14 | `marong/decor/v1/`, `marong/decor.py`, `tools/` 새 도구 | 없음 | GPT | 1 | TC-760, TC-541(그대로 통과, 48개). 다시 그린 아이템과 비용을 PR에 적음 |
| TASK-601 | 마이그레이션 025와 시험 DB 순서(`tests/pg.py`에 025 적용 함수) | TBL-190, TBL-176·179 바꿈 | `marong/migrations/025_marong_outfit.sql`(초안 그대로 쓰거나 고친 점을 PR에), `tests/pg.py`, 새 `tests/test_marong_outfit_schema.py` | 없음 | GPT | 0.5 | TC-770 |
| TASK-602 | 바꾸는 친구는 세션으로만 정함(SPEC-570). 스위치 `MARONG_DEFAULT_WEAR`, API-330, 보관함 API-254의 기본 마롱이 `outfit`, 프로필 API-216의 `marongOutfit`·`features.defaultWear`. D196의 `marongWearable`과 레이어 오류 거절. 차림 읽기 함수 하나가 캐릭터와 기본 마롱이를 갈라 읽음 | SPEC-570, 571 | `marong/pet_app_settings.py`, `marong/app_decor.py`, `marong/app_profile.py` | TASK-600, TASK-601 | GPT | 1 | TC-761, TC-762, TC-763, TC-771. API-330이 나열한 응답마다 시험 통과 |
| TASK-603 | 앱 화면: 글 대화 머리말·말풍선·입력 중 얼굴(SCR-107), 내 마롱이의 얼굴·'꾸미기' 줄·캐릭터 목록(SCR-165), 아이템 보기 미리 보기와 '입혀 볼래'(SCR-182), 보관함 입히기(SCR-183)에 기본 마롱이 차림. D196의 레이어 부재 안내와 단추 숨김. 스위치가 꺼지면 지금 #default-marong 그대로 | SPEC-571, 08 12절 | `marong/app_chat_static/chat.js`·`decor.js`·`unified.js`(와 css) | TASK-602 | GPT | 1 | TC-764, TC-765, TC-546(스위치 0에서 그대로 통과) |
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
| TASK-600 | 구현 완료 | `66282bb`, `3164cd1`, `171a7b9` | 모자·목도리 6개와 다시 그린 옷 4개를 맞춤. 10개 자리 상자·D196 등록·착용 분리·BUG-139 회귀 시험 통과. 비용 D197 |
| TASK-601 | 완료 | `0f35eff`, `20b2818` | TC-770 임시 Postgres에서 025 반복 적용·권한·제약·기존 claim 위험·되돌리기 순서와 그림 차림 기록 유지 확인 |
| TASK-602 | 완료 | `66282bb`, `c973da0` | TC-761~763·771과 무효 차림의 프로필 API 확인 |
| TASK-603 | 완료 | `66282bb`, `20b2818` | TC-764·765·546, 360·430px 낮·밤과 받기·입히기·오류·404 브라우저 확인 |
| TASK-604 | 완료 | `cae804c`, `20b2818` | TC-766 얼굴 21개·360·430px·낮밤·2·4px·움직임 줄이기·404·스위치 꺼짐 확인. 실제 폰은 반영 뒤 |
| TASK-605 | 완료 | `66282bb`, `20b2818`, `0e0d654` | TC-767·772 게이트·전달 실패·동시 작업과 전달·중단·늦은 완료·실패 비용 및 D198 고정 차림 확인 |
| TASK-606 | 완료 | `66282bb`, `20b2818`, `0e0d654` | TC-768 빈 지시 호환·밤 작업·다시 그리기·D198 차림 변경과 비용 보존 확인 |
| TASK-607 | 보류 | | 사용자 승인 뒤 반영. 이번 작업에서는 운영 반영하지 않음 |
| TASK-608 | 완료 | `66282bb`, `20b2818`, `0e0d654` | TC-773 스위치 0에서 게이트·전달 실패·185초 겹친 그림·동시 전달·중단·실패 비용과 D198 고정 차림 확인 |
