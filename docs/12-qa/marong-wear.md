# 기본 마롱이에게 입히기: 시험 계획(12단계, pet-app 기능 변경 1)

상태: 2026-11-28 작성(Claude, 항목 253). 2026-11-28 12 단계 체크포인트 통과(D193). 아직 돌리지 않았어요. 시험을 쓰고 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)). 작업은 [작업 목록](../10-wbs/marong-wear.md)이에요. 사용자님 도메인 질문 1\~4의 답에 따라 TC-767·768을 고치거나 빼요.
입력: [기능 명세](../04-functional-spec/pet-app.md) SPEC-570\~574의 받아들임 조건과 3.14, 요구사항 REQ-690\~697, 흐름 FL-189·190·192, 화면 [pet-app.md 12절](../08-screens/pet-app.md#12-기능-변경-1-기본-마롱이에게-입히기2026-11-28-d192-제안), 계약 API-330·API-254·API-216.

돌리는 법(`Runs as`)과 시험 데이터는 [반려동물 캐릭터 시험 계획](pet-app.md)과 같아요. 사람은 '시험친구 가'(기본 마롱이)·'시험친구 나'(반려동물 캐릭터 '콩이'). 아이템은 실제 목록 폴더의 착용 아이템 id를 써요(예: `berry-beanie`, `oat-sweater`, `chestnut-scarf`). 두 스위치는 `MARONG_DECOR=1`, `MARONG_DEFAULT_WEAR=1`이에요(따로 적지 않으면).

| ID | Case | From | Runs as | Data | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-760 | 착용 아이템마다 기본 마롱이 레이어가 있고 자리 상자 안 | SPEC-574, REQ-529, 3.14 | unit(`tests/test_decor.py`) | 실제 `marong/decor/v1/` | 목록 검사를 돌림. `marong.png`를 뺀 합성 폴더로 한 번 더 | 착용 아이템 10개 모두 `marong.png`가 1024×1024 RGBA, 자리 상자 밖 불투명 5% 이하, 48개 검사 통과. 뺀 폴더는 `missing: ["layer:marong"]`이고 API-264가 409 `item_invalid` | |
| TC-761 | 기본 마롱이 차림 바꾸기 | SPEC-570, REQ-690, REQ-693, API-330#200, API-330#400, API-330#401, API-330#403, API-330#404, API-330#409, API-330#413 | api(`tests/test_decor.py`) | 시험친구 가가 `berry-beanie`만 받음 | ① `{head: berry-beanie, body: null, neck: null}` ② 같은 것 다시 ③ 벗고 다시 입힘 ④ 받지 않은 `oat-sweater` ⑤ 모자를 `body`에 ⑥ Origin 다름 ⑦ 로그인 없음 ⑧ 본문 17KB ⑨ 반려동물 캐릭터를 적용한 채 ① | ① 200, `layerUrl`이 `/chat/decor/v1/berry-beanie/marong.png`, `marong_outfits` 1줄, `outfit_firsts`에 `character_id`가 빈 줄 1개 ②③ 200, `outfit_firsts` 그대로 ④ 409 `not_owned` ⑤ 400 `invalid_input`, `errors`에 `body`·`wrong_kind`(D190) ⑥ 403 `cross_site` ⑦ 401 ⑧ 413 ⑨ 200이고 그 캐릭터의 `outfits`는 그대로 | |
| TC-762 | 프로필과 보관함이 기본 마롱이 차림을 줌 | SPEC-571, REQ-692, API-216#200, API-254#200 | api(`tests/test_decor.py`, `tests/test_unified_profile.py`) | TC-761 ① 뒤 | API-216, API-254를 부름. 반려동물 캐릭터를 적용하고 다시 부름. 기본 마롱이로 돌아와 다시 부름 | 처음: `character` null, `marongOutfit.head.id = berry-beanie`, `features.defaultWear` 참, 보관함 `characterId` null이고 `outfit.head`가 같음. 캐릭터 적용 중: `marongOutfit` 없음, 보관함 `outfit`은 그 캐릭터 차림. 돌아오면 처음과 같음(REQ-693) | |
| TC-763 | 스위치를 끄면 지금 그대로 | REQ-697, SPEC-570, SPEC-571, 1절 5 | api(`tests/test_decor.py`) | TC-761 ① 뒤, `MARONG_DEFAULT_WEAR=0`으로 다시 띄움. 또 `MARONG_DECOR=0`으로 | API-330, API-216, API-254, 반응 선톡 차례 | API-330 404 `not_found`, `marongOutfit` 없음, `features.defaultWear` 거짓, 보관함 기본 마롱이 `outfit` null, 반응 줄을 새로 만들지 않음. `marong_outfits` 줄은 남음 | |
| TC-764 | 글 대화·내 마롱이 화면의 기본 마롱이 차림 | SPEC-571, REQ-692, SCR-107, SCR-165 | browser(`apps/android/test/pet-decor.e2e.cjs`) | 합성 API 응답, 360·430px, 낮·밤 | 글 대화를 열고 메시지·입력 중 표시를 띄움. 내 마롱이를 엶 | 머리말·말풍선·입력 중 얼굴에 레이어 요소가 몸→목→머리 순서로 있음. 내 마롱이에 '꾸미기' 줄(값 '모자·옷·목도리' 가운데 입은 것, 없으면 '아직 안 입음')과 얼굴 레이어. 레이어 주소가 404면 얼굴만. 가로 넘침 없음 | |
| TC-765 | 아이템 보기·보관함에서 기본 마롱이 입히기 | SPEC-570, SPEC-571, REQ-690, REQ-691, SCR-182#wearable, SCR-182#owned, SCR-182#error, SCR-183#wear, SCR-183#wear-empty, SCR-183#saving, SCR-183#error, FL-189, FL-190 | browser(`apps/android/test/pet-decor.e2e.cjs`) | 합성 API 응답, 360·430px, 낮·밤 | 아이템 보기에서 미리 보기를 보고 받기 → '입혀 볼래'. 보관함에서 다른 모자를 누르고, 같은 것을 다시 누름. API-330이 409·500을 주는 경우 | 미리 보기는 지금 차림에서 그 자리만 바뀐 모습과 '마롱이가 입으면 이렇게 돼'. '입혀 볼래' 뒤 보관함과 띠 '마롱이가 {아이템} 입었어!'. 누르면 입고 다시 누르면 벗음. 409면 미리 보기를 되돌리고 '아직 안 받은 거야'. 스위치 0이면 SCR-182·183#default-marong(지금 TC-546 그대로) | |
| TC-766 | 통화 화면 얼굴 모든 그림에 같은 레이어 | SPEC-571, REQ-692, SCR-001, SCR-002, 3.14 | browser(`tools/vertex_live/` 새 `test_marong_wear.cjs`) | 합성 프로필(`marongOutfit` 세 자리) | 통화 홈을 띄우고, 느낌 `laugh`·talk 칸·깜빡임·쉬기로 얼굴을 바꿈. 움직임 줄이기 켬 | 얼굴 `src`가 바뀌어도 레이어 요소 3개와 주소가 그대로, 얼굴과 레이어가 같은 상자라 튀기 때 위치 차이 0px. 움직임 줄이기면 레이어도 멈춤. 레이어 404면 얼굴만 | |
| TC-767 | 기본 마롱이 반응 선톡 | SPEC-572, REQ-694, REQ-537, AI-43 | job(`tests/test_proactive.py`, `tests/test_scene_picture.py`) | TC-761 ①, 가짜 그림·글 모델, 시험 시계 | ① 3분 뒤 차례, 게이트 열림 ② 그 사이 반려동물 캐릭터 적용 ③ 그림 모델 실패 ④ 게이트 막힘 두 번 ⑤ 같은 아이템 두 번째 첫 착용 시도 | ① 선톡 1번, `meta.reaction = berry-beanie`, `meta.scene` 있음, 그림 요청의 참조 이미지가 마롱이 얼굴 `01-neutral`·`02-big-laugh`, 지시 글에 털모자 `prompt`, 친구 이름·대화 글 없음, `scene_pictures.character_id` 비고 `prompt_version = scene-marong-v1` ② `skipped`, 선톡 없음 ③ 겹친 그림(`05-excited` 위), `fallback` 참, 비용 0 ④ `blocked` ⑤ 줄 그대로 | |
| TC-768 | 기본 마롱이 일기 그림의 차림 줄과 그림 화두 | SPEC-573, REQ-695, REQ-696 | job(`tests/test_diary_worker.py`, `tests/test_proactive.py`) | 털모자 차림의 시험친구 가, 가짜 그림 모델 | 밤 작업이 일기 그림을 그림. 다시 그리기. 차림을 벗고 다시. 그림 화두 차례 | 지시 글에 "The little white character is wearing: a raspberry red knitted beanie with a cream pom-pom."이 생김새 줄 뒤에 있음. 차림이 없으면 지금 `draw_prompt`와 바이트까지 같음. 그림 화두는 `meta.topic`이고 그림 모델 부름 0번 | |
| TC-769 | 반영 뒤 운영과 실제 폰 | REQ-692, REQ-697, SCR-107, SCR-002, SCR-183 | server, device | 사용자님 계정 | 반영(TASK-607) 뒤 스위치 0에서 로그 5분과 화면이 그대로인지, 1로 켠 뒤 사용자님이 폰에서 보관함으로 마롱이에게 모자를 씌우고 글 대화·통화 화면을 봄 | 스위치 0에서 운영 그대로(오류 0). 켠 뒤 글 대화 머리말·통화 얼굴에 모자, 3분 뒤 반응 선톡 1번(게이트 열림일 때). 운영 화면 사진은 Orca 항목 댓글로만 | |
| TC-770 | 025 두 번 적용과 거절 | TBL-190, TBL-176·179 바꿈, SPEC-570, SPEC-572 | api(`tests/test_marong_outfit_schema.py`) | 022·023까지 적용한 빈 DB | 025를 두 번 적용. `marong` 역할로 넣기·고치기·지우기, 같은 친구 두 번째 줄, 없는 아이템, 같은 기본 마롱이 첫 착용 두 번, 캐릭터 없는 화두 장면 그림. `marong_call` 역할로 새 표 읽기 | 두 번 적용 통과, 넣기·고치기 됨, 지우기·두 번째 줄·없는 아이템·같은 첫 착용·캐릭터 없는 화두는 거절, 통화 서버 계정은 새 표를 못 읽음. 지금 표의 줄은 그대로(2026-11-28 설계 때 수동 확인과 같은 11가지) | |

남은 번호: TC-771\~789는 비워 둬요.

## 요구사항마다 시험

| 요구사항 | 시험 |
| --- | --- |
| REQ-690 | TC-761, TC-765 |
| REQ-691 | TC-765 |
| REQ-692 | TC-762, TC-764, TC-766, TC-769 |
| REQ-693 | TC-761 ⑨, TC-762 |
| REQ-694 | TC-767 |
| REQ-695 | TC-768 |
| REQ-696 | TC-768 |
| REQ-697 | TC-763, TC-769 |
| REQ-529(바뀜) | TC-760 |
