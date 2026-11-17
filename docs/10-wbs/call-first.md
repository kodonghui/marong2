# 선 전화·그림 화두 작업 목록(10단계 WBS, CTX-020)

## GPT 인계

2026-11-17 13시대 KST 더함(Claude). 동희님 2026-11-17 12:37·12:38 "모든 작업에 대해 설계만 여기서 하고, 구현은 지피티 시킬거임" 뒤의 남은 일이에요. 그 전에 Claude가 구현한 TASK-160\~177의 기록은 아래 표와 '11단계 진행'에 그대로 둬요.

- 목표: 선 전화·그림 화두(CTX-020)의 남은 두 가지, 앱 0.2.2 서명 APK와 실제 폰 확인을 끝내요. 동희님 원문은 [도메인 설계](../01-domain/call-first.md) 머리의 출처 표기에 있어요.
- 시작: 따로 브랜치를 만들지 않아요. 앱 스스로 업데이트 패키지(`codex/app-self-update`, [app-update.md](app-update.md#gpt-인계))의 TASK-192가 이 APK를 같이 만들어요(0.2.2는 CTX-020과 CTX-021을 한 APK로 묶음).
- 읽을 것: 이 파일의 TASK-176 행과 '11단계 진행'의 TASK-176 결과, [화면 상태](../08-screens/call-first.md)의 SCR-110·SCR-111, 아래 '12단계에서 실제로 볼 것'(TC-180\~184). 목업은 [공통 목업 캔버스](https://claude.ai/artifact/CC154gunovJS3tqa8XkpZ9)(2026-11-17 버전 13)의 `C020-` 대지예요(승인된 A안, `C020-B-`로 시작하는 맨 아래 줄은 고르지 않은 B안).
- 이미 된 것: TASK-160\~175·177 끝(Claude). 서버 반영은 2026-11-17 01:24 KST(TASK-177). 앱 코드는 커밋 `6d9f24a`·`2fba258`이고, 그 커밋의 node·JVM 시험과 에뮬레이터 벨 두 번(약속 벨, 선 전화 벨)까지는 믿어도 돼요. 실제 폰은 아직이에요.
- 순서: app-update의 TASK-190(에뮬레이터, 0.2.2 전체) → TASK-192(서명·설치, 이것으로 TASK-176이 끝남) → TC-180\~184.
- 시험 환경: AGENTS.md와 같아요. 진짜 모델·유료 API는 쓰지 않아요.
- 반영: 서버에 새로 넣는 것은 없어요. 앱은 0.2.2(versionCode 5) 한 APK, 서명은 `GPT(동희님 노트북)`.
- 하면 안 되는 것: 선 전화 서버 설정(drop-in `zz-topics.conf`의 `MARONG_TOPICS`)과 0.2.2 미만 기기에 선 전화를 보내지 않는 조건(SPEC-265 ③)을 바꾸지 않아요.
- 겹치는 파일: `apps/android/`는 앱 스스로 업데이트와 같은 브랜치예요.
- 사람 확인: TC-180\~184(아래), 현경님 폰은 동희님이 부탁해요.
- 끝 조건: 서명 APK의 크기·SHA-256을 '11단계 진행'의 TASK-176 칸에 적고, 현경님 폰이 0.2.2이고, TC-180\~184 결과를 적음.
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 이 설계 스레드가 답해요.
- TASK-178(기록과 보고)은 설계 쪽 일이라 Claude가 끝내요.

2026-11-17 00:15 KST 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [call-first.md](../04-functional-spec/call-first.md)(SPEC-260\~283, AI-20\~22), 계약 [call-first.openapi.yaml](../../api/call-first.openapi.yaml)(API-140, `RingPushData`, `LiveReady.topic`)과 [app-chat.openapi.yaml](../../api/app-chat.openapi.yaml) 0.3.0-draft(API-102·104의 `picture`, `kind: hello`), 표 [018_call_first.sql](../../marong/migrations/018_call_first.sql)(TBL-125·126, TBL-102의 `reason`·`topic`), 화면 정의 [08-screens/call-first.md](../08-screens/call-first.md)와 [SCR-002](../08-screens/SCR-002.md)#topic-card, 09 목업 추천 A([call-first-candidates.md](../../design/call-first-candidates.md)).

- 번호: TASK-160부터예요. TASK-137\~159는 다른 설계(마롱이의 일기, PR #25)가 쓸 수 있게 비워 둬요.
- 사람이 보는 곳: 이 파일과 PR #27 설명의 체크 목록, Notion '최근 업데이트'의 이 작업 행이에요. 따로 작업 보드는 만들지 않아요.
- 담당: 코드는 모두 Claude(이 작업 스레드)예요. 앱 서명은 동희님 노트북에서 원격 세션으로 해요(서명 키가 노트북에만 있음). 실제 폰 확인은 12단계에서 현경님·동희님 폰으로 해요.
- 크기: 사람이 하는 일 기준의 대략값(일)이에요.
- 이번 반복의 순서: 저장소 → 판단 → 글 → 선톡에 넣기 → 선 전화 → 못 받음·답·횟수 → 끄기·켜기 말 → 글 대화 → 통화 → 관리 도구 → 그림 세트 → 앱 0.2.2 → 반영.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-160 | 저장소 함수: 화두 기록 만들기(유니크면 없음)·상태 바꾸기·답 정하기, 설정 읽기·쓰기, 마지막 활동 L과 먼저 연락만 나간 날, 그날 `hello` 벨 수, 벨 줄 `hello` 만들기(일정 없음) | SPEC-263, SPEC-264, SPEC-266, SPEC-275, SPEC-276, SPEC-278, SPEC-283 | TBL-125, TBL-126, TBL-102 | 없음(018 있음) | Claude | 0.5 | 시험 DB(마이그레이션 018까지)에서 같은 날 두 번 만들기는 두 번째가 없음, 설정 없는 친구는 기본값, 벨 줄 제약(`reason`·일정) 위반이 없음을 시험으로 확인 |
| TASK-161 | `marong/topics.py` 판단: 그림 세트 목록 읽기(칸 규칙), 화두 시각, 그림 고르기(달·시간·30일), 화두 간격(하루 하나·이틀·7일 세 번), 간격 늘리기 표, 설정 기본값, 선 전화 조건. 판단은 함수 하나(`decide`)에 모음 | SPEC-260, SPEC-261, SPEC-262, SPEC-263, SPEC-264, SPEC-265, SPEC-278 | `marong/topics/v1/topics.json`, TBL-125, TBL-126 | TASK-160 | Claude | 0.5 | 각 SPEC 행의 Given–When–Then 예시가 단위 시험으로 통과(시각은 고정 시계) |
| TASK-162 | 그림 화두 글 만들기: 보통 선톡 부름에 '# 오늘 꺼낼 화두'를 더하고 서버 확인(빈 답·거절·400자·물음표), 실패면 고정 글 | SPEC-271, AI-20 | `marong/agent.py` | TASK-161 | Claude | 0.5 | 모델 정상·시간 넘김·거절·빈 답·400자 넘음·물음표 없음 여섯 경우 시험 통과 |
| TASK-163 | 선톡 차례에 화두 넣기: `DiscordProactive.deliver`가 칸을 잡은 뒤 판단을 불러 그림 화두 글(앱은 미리보기 한 줄, 디스코드는 첫 말에 그림 첨부) 또는 선 전화, 아니면 보통 선톡. 스위치 `MARONG_TOPICS` | SPEC-263, SPEC-272, SPEC-273, SPEC-276, SPEC-280 | API-102(`meta.topic`), TBL-125 | TASK-161, TASK-162 | Claude | 1 | 스위치가 꺼지면 지금 선톡 시험이 그대로 통과. 앱 성공·앱 실패 뒤 디스코드·첨부 실패·둘 다 없음·같은 날 두 번째 차례 시험 통과 |
| TASK-164 | 선 전화 걸기: 벨 줄 `hello`(그림 이름은 그림 화두가 켜졌을 때만), FCM 벨에 `reason`·`line`(약속 전화는 `reason: promise`), 0.2.2 이상 기기만, 모두 거절이면 그림 화두 글로 | SPEC-265, SPEC-266, SPEC-267(서버 쪽) | `RingPushData`, TBL-102, TBL-125 | TASK-160, TASK-163 | Claude | 0.5 | 0.2.2 기기·0.2.1 기기만·FCM 거절·벨 이미 울림·통화 중·6시간 안 벨 시험 통과, 약속 벨 메시지 시험도 그대로 통과 |
| TASK-165 | 선 전화 못 받음: `sweep_rings`에서 `hello` 벨이면 화두 기록 `missed`, 그림 화두 글(모델 없이 3.6) 또는 선 전화용 한마디를 D18 경로로 한 번, 누르면 `/chat/` | SPEC-270 | TBL-102, TBL-125, API-102(`kind: hello`) | TASK-160, TASK-164 | Claude | 0.5 | `hello` 못 받음 → 글 한 번(`meta.hello`, `meta.topic`), 앱 알림 글 "전화했는데 바빴나 봐! 📞", 약속 전화 못 받음은 지금 시험 그대로 통과 |
| TASK-166 | 화두 답 정하기(3시간)와 선톡 하루 최대에 `hello` 벨 더하기 | SPEC-275, SPEC-276 | TBL-125, TBL-102 | TASK-160 | Claude | 0.25 | 친구 말·통화 시작·벨 받음 → `answered`, 3시간 지남 → `none`, `failed`는 그대로, 하루 최대 예시(글 5 + 벨 1 = 6) 시험 통과 |
| TASK-167 | 끄기·켜기 말: DM과 앱 글 대화에서 3.7의 말이면 설정을 바꾸고 정한 답(모델 없이) | SPEC-277 | API-103, TBL-126 | TASK-160 | Claude | 0.5 | 3.7의 말 14개가 설정을 바꾸고 정한 답, 비슷하지만 다른 말은 보통 대화, 저장 실패 답 시험 통과 |
| TASK-168 | 글 대화 서버: API-140 그림 주소(목록에 있는 이름만), 메시지의 `picture`, 종류 `hello` | SPEC-274, API-140, API-102, API-104 | API-140, API-102, API-104 | TASK-161 | Claude | 0.5 | API-140의 200·404·default 응답마다 시험 통과, API-102·104에 `picture`와 `kind: hello` 시험 통과, 계약 검사 통과 |
| TASK-169 | 글 대화 화면: 말풍선 위 그림(240px, 기다리는 칸, 못 받으면 칸 지움), 태그 '먼저 건 전화' | SPEC-274, SCR-107#picture, #picture-loading, #picture-missing, #hello | `marong/app_chat_static/` | TASK-168 | Claude | 0.5 | 브라우저 시험에서 네 상태가 보이고 360·430px에서 가로 넘침 없음 |
| TASK-170 | 통화 서버: 벨 줄의 `reason`·`topic` 읽기, 선 전화 지시문(AI-21), 첫 `ready`의 `topic` | SPEC-268, AI-21 | `/live` `ready`(`LiveReady.topic`), TBL-102 | TASK-160 | Claude | 0.5 | `hello` 벨 받기 → 첫 `ready`에 `topic`, 지시문에 화두 JSON, 다시 연결엔 `topic` 없음, 벨 없음·DB 늦음 → 보통 통화 시험 통과 |
| TASK-171 | 통화 화면: 얼굴 원이 15초 동안 그림으로(제목 칩, 닫기 48px, 움직임 줄이기), 벨 시간이 지났을 때 문구 | SPEC-269, SCR-002#topic-card, SCR-101 | `tools/vertex_live/static/` | TASK-170 | Claude | 0.5 | 브라우저 시험: 보임·15초 뒤 얼굴로·누르면 얼굴로·그림 못 불러오면 안 바뀜, 문구 바뀜 |
| TASK-172 | 관리 도구 `topics`(status, call, pictures, window) | SPEC-279 | TBL-125, TBL-126 | TASK-160 | Claude | 0.25 | 네 명령과 틀린 입력(친구 없음, 시간 형식) 시험 통과 |
| TASK-173 | 로그 정리: 결과 이름·개수·그림 이름만 | SPEC-281 | 봇·통화 서버 로그 | TASK-163\~167 | Claude | 0.25 | 시험 중 남은 로그에 화두 글·친구 말·벨 id·FID가 없음 |
| TASK-174 | 그림 세트 도구 `tools/topic_pictures.py`(draw, sheet, pack) | SPEC-282, AI-22 | 그림 API(서버 밖), `marong/topics/v1/` | 없음 | Claude | 0.5 | 가짜 그림 API로 draw(성공·실패)·pack(512px, 120KB, 목록 칸 규칙) 시험 통과, Git에는 pack 결과만 |
| TASK-175 | 그림 세트 v1: 후보를 그려 검수하고 20장 이상 넣기(털모자 `winter-hat`, 닭꼬치 `chicken-skewer` 포함), 주인공은 가운데 원 안, 미리보기 한 줄 16자 안팎 | SPEC-260, SPEC-282, REQ-268 | `marong/topics/v1/` | TASK-174 | Claude | 0.5 | `reviewed` 20장 이상, 목록 검사 통과, 검수 시트와 버린 후보의 이유가 프로젝트 파일에 있음 |
| TASK-176 | 앱 0.2.2: 벨 메시지의 `reason`·`line`, 벨 화면 둘째·셋째 줄, 전화 알림 글, 채널 설명, 버전 0.2.2(versionCode 5), 서명 APK | SPEC-267, SCR-110, SCR-111 | `RingPushData`, `apps/android/` | TASK-164 | Claude(노트북 원격) | 1 | JVM 시험(`reason`·`line` 규칙) 통과, 같은 인증서로 서명한 0.2.2 APK, 에뮬레이터에서 벨 화면 두 상태 확인 |
| TASK-177 | 전체 시험과 서버 반영: 마이그레이션 018, 파일 반영(백업, 대화·통화 없을 때 재시작, 되돌리기 스크립트), `MARONG_TOPICS=1` | SPEC-280, SPEC-283 | 서버 | TASK-160\~175 | Claude | 0.5 | 전체 시험 통과, 반영 뒤 5분 로그 오류 0, 되돌리기 스크립트가 서버에 있음 |
| TASK-178 | 기록과 보고: PR #27 설명, Notion 행, 프로젝트 메모, 동희님 보고(기본값과 바꾸는 법) | 없음 | 없음 | TASK-177 | Claude | 0.25 | 보고에 PR·Notion·목업 링크와 기본값이 있음 |

## 11단계 진행

2026-11-17 01:35 KST 기록, 01:55 TASK-176 결과 더함(Claude). 브랜치 `claude/project-thread-jbvi9w`, PR #27. '끝'은 끝 조건의 시험이 통과했다는 뜻이고, 11단계 체크포인트(PR 검토와 합치기)는 아직이에요. 시험은 로컬 Postgres 16 + pgvector와 가짜 모델·FCM·디스코드로 돌렸어요.

| ID | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-160 | 끝 | `e0b7f4f` | `tests/test_topics.py`(144개 확인): 같은 날 두 번째 화두 기록 없음, 설정 기본값과 바꾸기, 벨 줄 제약, 조용한 날(SPEC-264), 답 정하기 |
| TASK-161 | 끝 | `e0b7f4f` | 같은 시험: 화두 시각·범위·간격·간격 늘리기·그림 목록과 고르기·앱 버전·설정·말·화두 글 확인 |
| TASK-162 | 끝 | `e0b7f4f` | 같은 시험: 모델 정상·시간 넘김·거절·빈 답·400자 넘음·물음표 없음, 실패면 고정 글 |
| TASK-163 | 끝 | `e0b7f4f` | 앱·디스코드 그림 화두, 첨부 실패, 같은 날 두 번째 차례, 화두 시각까지 기다리는 칸. 스위치 끔이면 `tests/test_proactive.py` 165개 그대로 통과 |
| TASK-164 | 끝 | `e0b7f4f` | 이유·한 줄이 든 벨, 0.2.1 기기만이면 글, FCM 거절, 6시간, 통화 중, 시간대, 하루 최대 |
| TASK-165 | 끝 | `e0b7f4f` | 못 받음 글 한 번. 화두 기록은 맞춘 SPEC-270대로 `sent`에 `via`만 적음(이 표의 '화두 기록 `missed`' 대신). 약속 전화 못 받음은 `tests/test_app_ring.py` 75개 그대로 통과 |
| TASK-166 | 끝 | `e0b7f4f` | 답 정하기(3시간), 하루 최대 예시 |
| TASK-167 | 끝 | `e0b7f4f` | 3.7의 말이 설정을 바꾸고 정한 답, 비슷한 말과 스위치 끔은 모델로, 저장 실패 답 |
| TASK-168 | 끝(제공) | `e0b7f4f` | API-140 200·404·500, 그림에만 오래 두는 캐시, `Message.picture`, `kind: hello`. `tests/test_app_chat.py` 363개도 통과. Schemathesis는 안 돌림. 받아들임(실제 서버의 화면)은 12단계 |
| TASK-169 | 끝 | `e0b7f4f`, `96d1dc1` | 글 대화 브라우저 시험 15개(그림·기다림·못 받음·태그, 360·430px 가로 넘침 없음) |
| TASK-170 | 끝 | `96d1dc1` | `test_ring.py`(hello 벨 → 첫 `ready`에 `topic`, 다시 연결엔 없음, 벨 없음·DB 늦음은 보통 통화), `tests/test_app_ring.py`에서 통화 서버 계정으로 `claim_ring`(이유·그림) |
| TASK-171 | 끝 | `96d1dc1`, `2fba258` | 통화 화면 스크립트 시험 6개(첫 실행의 고장 하나를 `2fba258`에서 고침), 앱 통화 화면 시험 6개, 벨 시험 10개 |
| TASK-172 | 끝 | `d8cd58b` | 네 명령, 없는 친구·틀린 시간은 안 바뀜 |
| TASK-173 | 끝 | `d8cd58b` | 시험 중 화두·선 전화·그림 로그 83줄이 이름과 개수뿐 |
| TASK-174 | 끝 | `e5c515b`, `6d9f24a` | `tests/test_topic_pictures.py` 34개(그리기 성공·실패, 시트, 512px·120KB 묶기, 목록 규칙) |
| TASK-175 | 끝 | `2cb62e2` | `reviewed` 31장(털모자 `winter-hat`, 닭꼬치 `chicken-skewer` 포함), 두 눈 높이 측정 10% 이하, 2장은 다시 그림. 검수 기록은 프로젝트 파일 `marong-topic-set-v1-20261117/review.md` |
| TASK-176 | 진행(서명 APK만 남음) | `6d9f24a`, `2fba258` | 학원 컴퓨터(11/17 01:30\~01:46 KST): node 시험 30개 중 29 통과·1 건너뜀, JVM 시험 21개 실패 0(PushLinksTest의 새 시험 2개 포함), lint 오류 0·경고 11, 디버그 APK(versionCode 5, 0.2.2, targetSdk 36). 폴더 이름의 한글 때문에 Gradle이 막혀 같은 커밋을 영문 경로에 새로 받아 빌드했고 Java 21을 씀. 에뮬레이터(Android 16, 시험용 앱 이름 '마롱이 시험')에서 서버의 `tools/fcm_test_send.py`로 벨 두 번: 약속 벨은 '약속한 전화예요', 선 전화 벨은 '마롱이가 먼저 걸었어요' 아래 '나 털모자 샀다!', 알림 글 '마롱이가 먼저 걸었어요 · 나 털모자 샀다!'. 화면이 꺼진 상태에서 켜지며 벨 화면이 뜸. 못 본 것: 잠금 화면(이 에뮬레이터는 잠금 없음), 받기를 눌러 통화로 이어지는 흐름, 실제 폰. 서명 APK는 서명 키가 있는 노트북에서 |
| TASK-177 | 끝(반영) | `fc8d1bd` | 2026-11-17 01:22\~01:30 KST, 학원 컴퓨터에서 원격 세션으로. 반영 전 확인(멈출 파일 없음), DB 백업(`pg_dump`, 6MB), 018(칸 2개·표 2개, 통화 서버 계정 권한 확인), 파일 55개(봇 49, 통화 서버 6)가 새 해시, drop-in `zz-topics.conf`. 01:24:39 두 서비스 재시작(마지막 친구 말 약 3시간 40분 전, 진행 중 통화 0). 시작 로그 `app on fcm=on ring=on`, `topics_set set=v1 count=31 removed=0`, `topics on`, 그림 주소 200·없는 그림 404, 통화 화면 `app.js?v=20261117-topic1`. 재시작 5분 9초 뒤 두 서비스 Traceback·ERROR 0. 되돌리기 `~/marong-deploy/20261117-topics/rollback.sh`(서버) |
| TASK-178 | 진행 | | PR #27 설명, Notion 행, 프로젝트 메모, 보고 |

## 12단계에서 실제로 볼 것(사람 폰)

| ID | 경우 | From | 기대 결과 | 결과 |
| --- | --- | --- | --- | --- |
| TC-180 | 현경님 폰 0.2.2: 선 전화 벨, 잠금 화면과 폰을 쓰는 중 두 번 | SPEC-266, SPEC-267, SCR-110#hello, SCR-111#hello | 잠금 화면은 전체 화면 벨, 쓰는 중엔 위에 뜨는 알림. 둘 다 '마롱이가 먼저 걸었어요'와 미리보기 한 줄 | |
| TC-181 | 선 전화를 받음 | SPEC-268, SPEC-269, SCR-002#topic-card | 통화 화면 얼굴 원이 15초 동안 그림, 마롱이가 화두로 말을 꺼냄 | |
| TC-182 | 선 전화를 못 받음 | SPEC-270, SCR-107#hello | 한 번만 오는 글, 누르면 글 대화, 태그 '먼저 건 전화' | |
| TC-183 | 동희님 폰: 디스코드 DM 그림 화두 | SPEC-273 | 첫 말에 그림 첨부, 글과 그림이 맞음 | |
| TC-184 | 앱 글 대화의 그림(앱 창, 360px 폭) | SPEC-274, SCR-107#picture | 240px 그림이 말풍선 위에, 글이 밀리지 않음 | |

## 검사

- Must SPEC 행(SPEC-260\~283 가운데 Must 요구사항을 따르는 모든 행)에 작업이 있어요. SPEC-280은 TASK-163·177, SPEC-283은 TASK-160·177이에요.
- 작업마다 담당 한 명과 남이 확인할 수 있는 끝 조건이 있어요.
- API를 건드리는 작업(TASK-168, 170)은 그 작업이 나열한 응답마다 시험이 통과해야 끝이에요.
- 의존 관계에 되돌아오는 고리가 없어요. 모든 작업이 번호가 더 작은 작업에만 기대요.
