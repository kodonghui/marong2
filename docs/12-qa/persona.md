# 마롱이 성향 맞춤·선톡: 시험 계획(12단계)

상태: 0단계 고침의 시험(TC-230\~255) 작성(2026-11-17 13시대 KST, Claude, corthex 0.12.1). 1\~4단계 시험은 TC-256부터 이 파일에 더해요. 시험을 돌리는 쪽은 GPT예요([AGENTS.md](../../AGENTS.md)).
입력: [기능 명세](../04-functional-spec/persona.md) SPEC-184\~191의 받아들임 조건과 예외, AI-11·AI-12, [요구사항](../02-prd/persona.md)의 비기능 REQ-212. 0단계는 새 흐름(FL)·API·화면(SCR)이 없어요.

돌리는 법(`Runs as`): `auto`는 저장소의 시험 파일(`tests/test_*.py`, 진짜 Postgres는 `pgserver`, 카카오·디스코드·FCM·모델은 가짜), `server`는 반영한 서버의 DB·로그 읽기, `manual`은 사람이 폰에서 봄. 진짜 모델·유료 API를 부르는 시험은 없어요.

## 0단계 고침

| ID | Case | From | Runs as | Steps | Expected | Last result |
| --- | --- | --- | --- | --- | --- | --- |
| TC-230 | 하루 횟수·시간 상한 표 | SPEC-184, REQ-202, REQ-203 | auto(`tests/test_proactive.py`) | 명세 3.1 표의 입력 6줄로 `proactive_schedule`와 `proactive.schedule` 부르기 | 표의 결과와 같음. DB의 방 값은 그대로(시험 뒤 다시 읽어 같음) | not run |
| TC-231 | 밤에는 칸이 없음 | SPEC-184, REQ-203 | auto(`tests/test_proactive.py`) | 방 값 7\~24시·12번인 방으로 한국 시각 07:59·08:00·21:59·22:00·23:30에 `slot`·`plan` | 07:59·22:00·23:30은 칸 없음(보낼 것 없음), 08:00·21:59는 칸 있음. 하루 칸은 3개 | not run |
| TC-232 | 친구에게 보이는 값 | SPEC-185, REQ-204 | auto(`tests/test_discord_dm.py`, `tests/test_proactive.py`) | 디스코드 링크 하루 48번·0\~24시로 안내 명령과 `_dm_lines`, 방 값 12번으로 선톡 지시문 만들기 | 안내 글 "8\~22시에 하루 3번까지", 지시문 "하루 3번쯤". 48·12라는 숫자가 글에 없음 | not run |
| TC-233 | 물러서기 표 | SPEC-186 | auto(`tests/test_proactive.py`) | `backoff(0)`\~`backoff(5)` | 0, 21시간, 45시간, 93시간, None, None | not run |
| TC-234 | 카카오 1:1 방 물러서기 | SPEC-186, REQ-205, REQ-206 | auto(`tests/test_proactive.py`) | 선톡 1번 전달 → 같은 날 다음 칸, 22·23시간 뒤 칸 → 4번째 전달까지 늘림 → 10일 뒤 칸 → 친구 한 마디 → 다음 칸 | 같은 날·22시간 뒤 안 보냄, 23시간 뒤 보냄. 4번 뒤 10일이 지나도 안 보냄(메시지 줄 늘지 않음). 친구 말 뒤 다음 칸 보냄 | not run |
| TC-235 | 디스코드 DM 물러서기와 L | SPEC-186 | auto(`tests/test_discord_dm.py`) | (가) 선톡 2번 전달 뒤 `call.calls`에 그 친구 통화 줄 추가 (나) 전달 실패(`delivered = false`) 선톡 3번 (다) 선 전화 못 받음 한마디(`meta.hello`) 1번 (라) 앱 글 대화로 친구가 말함 | (가) `unanswered = 0`, 다음 칸 보냄 (나) `unanswered = 0` (다) `unanswered = 1` (라) `unanswered = 0` | not run |
| TC-236 | 그림 화두 차례도 물러섬 | SPEC-186, PR #27 SPEC-263 | auto(`tests/test_topics.py`) | `MARONG_TOPICS=1`, 답 없는 선톡 1번 뒤 12시간에 화두 시각이 든 칸 | 화두도 선 전화도 안 감, 화두 기록(TBL-125) 줄 없음 | not run |
| TC-237 | 선톡 재료에서 자기 선톡 빼기 | SPEC-187, AI-11, REQ-207 | auto(`tests/test_proactive.py`) | 군밤·이불·별 선톡 3번과 친구 말 2개 뒤, 가짜 모델로 선톡 만들기 | 가짜 모델이 받은 시스템 프롬프트의 '최근 대화'에 세 선톡 글이 없고 자리 표시 3줄, '최근 7일 동안 마롱이가 먼저 보낸 말' 절에 세 줄, 지시 한 줄 있음. 친구 말 2개는 그대로 | not run |
| TC-238 | 7일 목록을 못 읽음 | SPEC-187 예외 | auto(`tests/test_proactive.py`) | `recent_proactives`가 오류를 내게 하고 선톡 만들기 | 7일 절 없이 만들어 보냄, 유사도 검사 안 함, 로그 `proactive_said_error`(글 없음) | not run |
| TC-239 | 유사도 표본 | SPEC-188 | auto(`tests/test_proactive.py`) | 명세 3.5의 표본 쌍(같은 소재 2쌍, 다른 소재, 이름만 같은 쌍) | 같은 소재 ≥ 0.35, 다른 소재·이름만 같은 쌍 < 0.35 | not run |
| TC-240 | 거의 같은 선톡 막기 | SPEC-188, REQ-208 | auto(`tests/test_proactive.py`, `tests/test_discord_dm.py`) | 7일 목록에 군밤 선톡, 가짜 모델이 거의 같은 말을 냄. 카카오와 디스코드 각각 | 보내지 않음, 메시지 줄 없음, 로그 `reason=repeat similarity=0.xx`. 그 칸은 다시 만들지 않음(가짜 모델 호출 1번) | not run |
| TC-241 | 그림 화두는 유사도 검사 없음 | SPEC-188 예외 | auto(`tests/test_topics.py`) | 7일 목록에 같은 그림 화두와 비슷한 선톡이 있는 상태로 그림 화두 차례 | 그림 화두 글이 감 | not run |
| TC-242 | 종일 일정 아침 알림 | SPEC-189, REQ-209 | auto(`tests/test_schedules.py`) | (가) 오늘 08:00에 모레 날짜만 일정 (나) 오늘 10:00에 오늘 날짜만 (다) 매주 반복 종일 (라) 전화 약속 (마) 친구가 정한 알림 시각 | (가) `remind_at` 모레 09:00 한국 시각, 도구 결과 "그때 이 DM으로 먼저 말할게" (나) 없음 (다)(라) 지금 규칙 그대로 (마) 그 시각. `say` 없으면 알림 글 "오늘 {제목} 있는 날이야 📅" | not run |
| TC-243 | 일정 알림은 선톡 횟수와 따로 | SPEC-189, SPEC-184 | auto(`tests/test_proactive.py`, `tests/test_schedules.py`) | 같은 날 종일 일정 알림 1번과 선톡 칸 3개 | 선톡 3번과 알림 1번이 모두 감 | not run |
| TC-244 | 괄호 지문 표 | SPEC-190, REQ-210 | auto(`tests/test_dm_help.py`의 `style_checks`) | 명세 3.7 표의 입력 10개를 `tidy`에 넣기 | 표의 결과와 고친 것 이름(`stage`, `ya`) | not run |
| TC-245 | 지문만 있던 말 | SPEC-190 예외 | auto(`tests/test_discord_dm.py`, `tests/test_proactive.py`, `tests/test_topics.py`) | 가짜 모델이 "(조용히 기다립니다)"만 냄: 답, 보통 선톡, 그림 화두 글 | 답 "응응", 보통 선톡은 안 보냄(로그 `reason=stage_only`, 메시지 줄 없음), 그림 화두는 그림의 고정 글 | not run |
| TC-246 | 딥시크가 빠르면 Claude 안 부름 | SPEC-191, AI-12 | auto(`tests/test_deepseek.py`) | 가짜 전송: 딥시크 1초 응답 | 딥시크 답, Claude 호출 0 | not run |
| TC-247 | 딥시크가 늦고 Claude가 빠름 | SPEC-191, REQ-211 | auto(`tests/test_deepseek.py`) | 딥시크 25초, Claude 3초, HEDGE_S 20 | 약 23초에 Claude 답, `served_model` 있음, 딥시크 작업 취소, 로그 `deepseek_hedge winner=claude` | not run |
| TC-248 | 같이 출발 뒤 딥시크가 먼저 | SPEC-191 | auto(`tests/test_deepseek.py`) | 딥시크 22초, Claude 10초(20초에 출발) | 딥시크 답, Claude 작업 취소, `served_model` 없음 | not run |
| TC-249 | 같이 출발 뒤 딥시크 오류 | SPEC-191 예외 | auto(`tests/test_deepseek.py`) | 딥시크 21초에 502, Claude 진행 중 | Claude 답 하나, Claude 호출 1번(두 번 띄우지 않음) | not run |
| TC-250 | 같이 출발하지 않는 경우 | SPEC-191 전제·예외 | auto(`tests/test_deepseek.py`) | (가) 도구 결과 뒤 이어 보내는 요청 (나) `MARONG_DEEPSEEK_HEDGE_S=0` (다) HEDGE_S가 `timeout_s` 이상 (라) 딥시크가 웹 검색을 대신 찾는 중 | (가)(나)(라) 지금 동작과 같음(Claude 호출은 지금 대신 답하기 규칙대로만) (다) 시작 로그에 끔 | not run |
| TC-251 | 딥시크 내용 거절이 먼저 | SPEC-191 예외 | auto(`tests/test_deepseek.py`) | 같이 출발 뒤 딥시크가 400 risk로 먼저 끝남 | 지금처럼 거절 답 | not run |
| TC-252 | 로그에 대화 글이 없음 | SPEC-184\~191(명세 1절 3번) | auto(시험 중 로그 모음) | TC-230\~251을 돌리며 남은 로그를 모음 | 선톡 글, 친구 말, 일정 제목, 키가 없음. 결과 이름·개수·짧은 방 키뿐 | not run |
| TC-253 | 지금 시험 그대로 통과 | SPEC-184\~191 | auto | `tests/test_proactive.py`, `test_discord_dm.py`, `test_schedules.py`, `test_deepseek.py`, `test_llm.py`, `test_app_chat.py`, `test_dm_help.py`, `test_app_ring.py`, `test_topics.py`, `test_check.py` | 모두 통과. 기대값을 새 규칙에 맞게 고친 체크(예: 하루 12번·7\~24시)는 PR 설명에 줄마다 이유 | not run |
| TC-254 | 반영 뒤 7일 숫자 | REQ-202\~212, 명세 5절 | server, manual | 반영 7일 뒤 서버 DB·로그를 읽어 명세 5절 표를 채움(숫자만, 글 없음). 현경님 폰은 동희님이 물어봄 | 하루 선톡 3 이하, 22\~08시 0, 같은 소재 되풀이 거의 0, 종일 일정마다 아침 알림, 늦은 답 중앙 30초 안(REQ-212), 지문 0 | not run |
| TC-255 | 되돌리기 | SPEC-184\~191, TASK-209 | server | 반영 전 되돌리기 스크립트를 마른 실행(`--dry-run`)으로 돌림 | 바꿀 파일 목록과 다시 시작할 서비스가 나오고 아무것도 바뀌지 않음 | not run |

해당 없음: 접근(새 입구 없음, 방 범위 규칙 그대로), 입력·대상·API 응답(API 바뀜 없음), 화면 상태(화면 없음), 동시성(칸 잡기 `claim_slot`·방 잠금은 그대로이고 지금 시험이 덮음), 레드팀(새 도구·새 대화 입구가 없음. 1\~4단계에서 함).

커버리지(작성 때): 받아들임 조건 23개 가운데 시험이 있는 것 23개, 돌린 것 0. 비기능 REQ-212는 TC-254로 봄.
