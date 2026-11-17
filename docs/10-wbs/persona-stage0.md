# 성향 맞춤·선톡 0단계 고침 작업 목록(10단계 WBS)

2026-11-17 13시대 KST 작성(Claude, corthex 0.12.1). 입력: 기능 명세 [persona.md](../04-functional-spec/persona.md)의 SPEC-184\~191과 AI-11·AI-12, 요구사항 [persona.md](../02-prd/persona.md)의 REQ-202\~212, 시험 계획 [12-qa/persona.md](../12-qa/persona.md)의 TC-230\~255. API·표·화면은 바뀌지 않아요.

## GPT 인계

- 목표: 선톡이 너무 잦고 되풀이되고 밤에도 오는 것, 종일 일정에 알림이 없는 것, 답에 괄호 지문이 붙는 것, 딥시크가 늦으면 답이 40초 넘게 걸리는 것을 고쳐요. 동희님 D24(2026-11-17 12:24 KST 결정 카드 '바로 고치고 전부 설계', 12:25 논의 문서 댓글 "모두승인")와 D60(12:37 "구현은 gpt 시킬거야"). 원문 자리는 [docs/02-prd/persona.md](../02-prd/persona.md#출처-표기)
- 시작: `main` 머리에서 새 브랜치 `codex/persona-stage0`(PR #27은 2026-11-17 `4c74b02`로 `main`에 합쳐짐). 설계 문서는 PR #25가 합쳐지기 전이면 브랜치 `claude/project-thread-7y5bt4`(PR #25, PR #30을 합쳐 담음), 합쳐진 뒤면 `main`에 있어요
- 읽을 것: [docs/04-functional-spec/persona.md](../04-functional-spec/persona.md)의 1·3절과 SPEC-184\~191, AI-11·AI-12. [docs/12-qa/persona.md](../12-qa/persona.md)의 TC-230\~255. 이 파일의 TASK 표. 그 밖의 문서는 읽지 않아도 돼요(PR #27의 SPEC-263·264·271은 명세에서 가리킬 때만)
- 이미 된 것: 저장소 코드는 없어요. 설계 스레드가 멈춘 참고 패치(프로젝트 파일 `marong-persona-research-20261116/stage0/참고-초안-미완성-20261117.patch`)가 있지만 `main` `a5a138b` 위에서 만든 것이고 PR #27 위가 아니에요. 시험하지 않았고 괄호 지문 판정이 틀려서 쓰지 않아요. 명세가 기준이에요
- 순서: TASK-200 → TASK-201 → TASK-202 → TASK-203 → TASK-204 → TASK-205·206·207(서로 독립, 순서 상관없음) → TASK-208 → TASK-209 → TASK-210
- 시험 환경: Python 3.12와 `pgserver`(AGENTS.md '시험'). 카카오·디스코드·FCM·모델은 가짜. 진짜 모델·유료 API는 부르지 않아요
- 반영: 함. 시험이 모두 통과하면 동희님의 상시 반영 허락(2026-11-15 19:58 KST "만들어지는대로 계속 넣어", 조건: 백업·대화와 통화가 없을 때 재시작·되돌리기 스크립트)과 D24로 반영해요. 마이그레이션 없음. 파일은 디스코드 봇(`/opt/marong-discord`)에, 카카오 봇이 서버에서 돌고 있으면 그 사본에도. 설정은 `MARONG_DEEPSEEK_HEDGE_S`만 새로 생기고 코드 기본값 20이라 drop-in이 필요 없어요(끌 때만 `Environment=MARONG_DEEPSEEK_HEDGE_S=0`을 drop-in에). 다시 시작: `marong-discord`(통화 서버는 바뀌지 않음). 되돌리기: 서버 `~/marong-deploy/<날짜>-persona-stage0/`에 바꾼 파일의 원래 사본과 `rollback.sh`(파일을 되돌리고 다시 시작). DB는 바뀌지 않아요
- 하면 안 되는 것: DB에 저장된 방별 선톡 값 바꾸기(명세 1절 1번), 이미 저장된 종일 일정에 알림 시각 채우기(명세 3.6, 동희님이 따로 말할 때만), `/opt/marong/prompt.md` 고치기(이번 일은 그 파일을 건드리지 않음), 친구 카드·선톡 게이트·할 일 목록 같은 1\~4단계 기능 미리 만들기, 선톡 상한 숫자(3번·8\~22시) 바꾸기
- 겹치는 파일: `marong/proactive.py`, `marong/discord_dm.py`(`DiscordProactive`, `DiscordAgent._dm_lines`), `marong/agent.py`(`proactive_message`, `_proactive_situation`), `marong/store.py`, `marong/discord_store.py`는 PR #27과 겹쳐요. PR #27을 먼저 합치고 그 위에서 해요([README 겹치는 파일](README.md#겹치는-파일)). 일기 패키지(PR #25)가 먼저 합쳐지면 그 위에 맞춰요. `marong/style.py`, `marong/schedules.py`, `marong/deepseek.py`, `marong/config.py`는 지금 다른 패키지와 겹치지 않아요
- 사람 확인: 반영 7일 뒤 TC-254(동희님이 현경님께 선톡이 줄었는지, 밤에 안 오는지, 종일 일정 아침 말이 왔는지 물어봄). TC-255 되돌리기 마른 실행
- 끝 조건: TASK-200\~208의 끝 조건 시험이 모두 통과하고 TC-253(지금 시험 전체)이 통과. 반영 뒤 5분 동안 `marong-discord` 로그에 Traceback·ERROR 0, 시작 로그에 선톡 상한과 `deepseek on … hedge=20.0s`. 되돌리기 스크립트가 서버에 있음
- 설계 질문: PR 설명 맨 위 '설계 질문'에 적으면 설계 스레드('마롱이 성향 맞춤·선톡 고치고 설계하기')가 답해요

## 작업 표

- 번호: TASK-200부터예요(이 패키지와 1\~4단계가 200\~259를 나눠 씀).
- 담당: 모두 GPT예요. 크기는 사람이 하는 일 기준의 대략값(일)이에요.

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-200 | `config.PROACTIVE_CAP`·`PROACTIVE_AWAKE`·`proactive_schedule`, `proactive.schedule`이 그것을 부름, `Proactive.run` 시작 로그에 상한 | SPEC-184 | `marong/config.py`, `marong/proactive.py` | 없음 | GPT | 0.25 | TC-230·231 통과. `tests/test_proactive.py`의 하루 12번·7\~24시 기대 체크를 새 규칙으로 고치고 줄마다 이유 주석 |
| TASK-201 | 친구에게 보이는 횟수·시간을 상한 뒤 값으로(`_dm_lines`, 안내 명령 답, '지금 상황' 줄, 선톡 지시문의 `{per_day}`) | SPEC-185 | `marong/discord_dm.py`, `marong/agent.py` | TASK-200 | GPT | 0.25 | TC-232 통과 |
| TASK-202 | 답 없는 선톡 수: `ROOM_STATE`·`DM_STATE`에 `unanswered` 열, `proactive.BACKOFF`·`backoff()`, `plan()`의 검사 | SPEC-186 | `marong/store.py`, `marong/discord_store.py`, `marong/proactive.py`, `call.calls`·`call.callers` 읽기 | TASK-200 | GPT | 0.5 | TC-233·234·235·236 통과 |
| TASK-203 | 선톡 재료: `store.recent`의 `proactive` 열, `store.recent_proactives`, `proactive_message`의 자리 표시·7일 절·지시 한 줄, `meta.memory.recent` | SPEC-187, AI-11 | `marong/store.py`, `marong/agent.py` | TASK-202 | GPT | 0.5 | TC-237·238 통과 |
| TASK-204 | 유사도(`style.py`의 이름 빼기·바이그램 자카드·`REPEAT_SIMILARITY`)와 보통 선톡의 되풀이 막기 | SPEC-188, AI-11 | `marong/style.py`, `marong/agent.py` | TASK-203 | GPT | 0.5 | TC-239·240·241 통과 |
| TASK-205 | 종일 일정 아침 9시 알림(`ALL_DAY_REMIND_HOUR`, `check_add`, 도구 설명, `GUIDE`, `reminder_text`) | SPEC-189 | `marong/schedules.py` | 없음 | GPT | 0.25 | TC-242·243 통과 |
| TASK-206 | 괄호 지문 거르기(`tidy`의 `stage`, `STAGE_FALLBACK`, 선톡·그림 화두에서 지문만 있던 말) | SPEC-190, AI-11 | `marong/style.py`, `marong/agent.py` | TASK-204 | GPT | 0.5 | TC-244·245 통과. 지금 `style_checks`(야·한숨) 그대로 통과 |
| TASK-207 | 딥시크 같이 출발(`MARONG_DEEPSEEK_HEDGE_S`, `_run`, 먼저 성공한 쪽, 취소, 로그) | SPEC-191, AI-12 | `marong/deepseek.py` | 없음 | GPT | 1 | TC-246\~251 통과(가짜 전송, 실제 API 없음) |
| TASK-208 | 전체 시험·로그 검사·초안 PR(TASK·SPEC ID, 돌린 시험과 결과, 고친 기대값과 이유, 돌리지 못한 것) | SPEC-184\~191 | 없음 | TASK-200\~207 | GPT | 0.25 | TC-252·253 통과, PR 설명에 파일별 통과 수 |
| TASK-209 | 서버 반영: 서버 파일 해시를 `main`과 비교, 백업, 되돌리기 스크립트, 파일, 대화·통화가 없을 때 `marong-discord` 다시 시작, 로그 5분 | SPEC-184\~191 | 서버 | TASK-208 | GPT | 0.25 | TC-255 통과, 5분 로그 오류 0, 시작 로그에 상한·같이 출발 값, PR에 되돌리기 경로 |
| TASK-210 | 기록: 아래 '11단계 진행' 표를 채우고, 반영 7일 뒤 TC-254 숫자를 명세 5절 표 모양으로 PR에 남김(숫자만) | SPEC-184\~191, REQ-212 | 없음 | TASK-209 | GPT | 0.25 | 진행 표의 모든 TASK에 상태·커밋·확인한 것, TC-254 숫자가 PR 댓글에 있음 |

## 11단계 진행

GPT가 TASK마다 채워요. 아래는 [PR #31](https://github.com/kodonghui/marong2/pull/31) 설명의 진행표를 옮긴 것이에요(2026-11-17 15:2x KST 읽음, 이 문서가 그 PR에 없어서 설계 스레드가 옮김). '확인'은 GPT가 돌린 시험 보고이고 설계 스레드가 다시 돌리지는 않았어요. 설계 검토(2026-11-17): 코드가 SPEC-184\~191과 맞고, TC-234의 '22시간' 문구는 SPEC-186의 21시간으로 고쳤어요.

| 작업 | 상태 | 커밋 | 확인한 것 |
| --- | --- | --- | --- |
| TASK-200 | 확인 | `35ee467` | 적용 상한, 발송 경계와 종료 시각 |
| TASK-201 | 확인 | `35ee467` | DM 도움말과 모델 안내 문구 |
| TASK-202 | 확인 | `35ee467` | 무응답·전달 실패·통화/앱 답장·그림 차례 |
| TASK-203 | 확인 | `35ee467` | 7일 재료, 최근 대화 표시, 조회 오류 처리 |
| TASK-204 | 확인 | `35ee467` | 반복 발송 생략, 해당 칸 재생성 없음 |
| TASK-205 | 확인 | `35ee467` | 종일 알림 09:00, 기존 시간·반복·전화 규칙 |
| TASK-206 | 확인 | `35ee467` | 지문만 있는 답·선톡·그림 화두 |
| TASK-207 | 확인 | `35ee467` | 응답 경합, 취소, 오류·거절·검색·도구 이어 쓰기 |
| TASK-208 | 확인 | `35ee467` | TC-252·253, 전체 시험(25개 파일 통과)과 초안 PR |
| TASK-209 | 병합 대기 |  | 반영 알림, 서버 해시·백업·되돌리기, 서비스 재시작, 5분 관찰 |
| TASK-210 | 반영 대기 |  | 반영 7일 뒤 수치와 실제 사용 확인 |

## 검사

- Must SPEC 행(SPEC-184\~190)과 Should 행 SPEC-191에 모두 작업이 있어요.
- 작업마다 담당 한 명(GPT)과 남이 돌려 볼 수 있는 끝 조건(TC ID)이 있어요.
- API를 건드리는 작업은 없어요.
- 의존 관계에 되돌아오는 고리가 없어요. 모든 작업이 번호가 더 작은 작업에만 기대요.
