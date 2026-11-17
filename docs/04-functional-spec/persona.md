# 마롱이 성향 맞춤·선톡: 기능 명세

상태: 0단계 고침(SPEC-184\~191, AI-11·AI-12) 작성(2026-11-17 13시대 KST, Claude, corthex 0.12.1). 1\~4단계는 SPEC-192부터 이 파일에 더해요.
입력: [요구사항](../02-prd/persona.md) REQ-202\~212. 0단계는 지금 흐름을 바꾸지 않아서(선톡·답·일정 알림이 나가는 경로는 그대로, 나가는 횟수와 글만 바뀜) 새 사용자 흐름(FL)이 없어요.
기준 코드: 규칙의 함수·쿼리 이름은 `main` `a5a138b`와 PR #27 브랜치 `claude/project-thread-jbvi9w` `a703918`에서 읽었어요. PR #27이 `main`에 먼저 합쳐지고 구현은 그 위에서 해요([docs/10-wbs/README.md](../10-wbs/README.md#겹치는-파일)).
표시: [사실] 코드·기록에서 확인, [규칙] 이번에 정한 동작, [확인 안 함] 아직 보지 않은 것.

## 1. 공통 규칙

1. DB에 저장된 방별 값(`marong.rooms.proactive_per_day`·`proactive_start`·`proactive_end`, `marong.discord_dm_links.per_day`·`start_hour`·`end_hour`)은 바꾸지 않아요. 쓸 때만 상한을 적용해요. 되돌리면 예전 값이 그대로 살아나요.
2. 새 DB 표나 칸은 없어요. 바뀌는 것은 코드와 쿼리, 설정 하나(`MARONG_DEEPSEEK_HEDGE_S`)예요.
3. 로그에는 결과 이름·개수·짧은 방 키(`short_key`)만 남겨요. 친구 말, 선톡 글, 일정 제목, 키를 남기지 않아요.
4. '선톡 한 번'은 저장된 메시지 한 줄이에요. 빈 줄로 나눈 말 여러 개도 한 줄로 저장돼요 [사실]. 그림 화두 글도 `meta.proactive = true`로 저장되고, 선 전화를 못 받았을 때의 한마디는 `meta.hello = true`로 저장돼요(PR #27) [사실].
5. '친구의 마지막 활동 L'은 PR #27 SPEC-264와 같아요: 친구가 마지막으로 보낸 말(디스코드 DM·앱 글 대화, 카카오 방)과 그 친구 통화의 마지막 시작 가운데 늦은 때. 디스코드에서 친구가 말한 적이 없으면 선톡을 켠 때(`opted_in_at`)예요.

## 2. 기능 표

| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-184 | 선톡 하루 횟수·시간 상한 | REQ-202, REQ-203 | 선톡 확인(`Proactive.step`)이 방의 일정을 정할 때(`proactive.schedule`) | 방의 하루 횟수와 시간대를 정하고 상한을 적용해요(3.1): 하루 횟수는 `min(방 값 또는 기본값, 3)`, 시간대는 방 값(없으면 기본값)과 8\~22시가 겹치는 부분. 칸 나누기(`slot`)·보낼지(`plan`)·디스코드의 `still_current`·그림 화두의 칸(`DiscordProactive._slot`)은 모두 이 값을 써요 | 방 값이 틀림(시작 ≥ 끝, 0\~24 밖) → 기본값<br>겹치는 부분이 없음(예: 방 값 23\~24시) → 8\~22시<br>방 값이 0 → 기본값, 음수 → 1 | Given 방 값 하루 12번·7\~24시, When 일정을 정함, Then 하루 3번·8\~22시<br>Given 방 값 없음, 기본값 12\~21시·2번, Then 12\~21시·2번<br>Given 9\~18시·5번, Then 9\~18시·3번<br>Given 지금 22:30, Then 이 방에 보낼 칸이 없음 | active |
| SPEC-185 | 친구에게 보이는 횟수·시간 | REQ-204 | 친구에게 횟수·시간을 말하는 글을 만들 때 | 디스코드 DM 안내(`_dm_lines`), 안내 명령 답, 대화 지시문의 '지금 상황' 줄, 선톡 지시문(`PROACTIVE_GUIDE`·`PROACTIVE_GROUP_GUIDE`의 `{per_day}`)에 SPEC-184로 정한 값을 넣어요(3.2) | 값을 못 읽음(DB 오류) → 그 줄을 빼고 답함(지금과 같음) | Given 디스코드 링크 하루 48번, When 안내 명령, Then 글에 "8\~22시에 하루 3번까지"<br>Given 방 값 12번, When 선톡 지시문을 만듦, Then "하루 3번쯤" | active |
| SPEC-186 | 답 없는 선톡 백오프 | REQ-205, REQ-206 | `Proactive.plan`이 이 방의 이번 칸을 볼 때(지금의 `quiet_for`·`sent_ago`·`failures` 검사 뒤) | 답 없는 선톡 수 u(L 뒤에 전달된 선톡과 선 전화 못 받음 한마디 수)를 세고, u = 0이면 지금처럼, 1·2·3이면 마지막 선톡 뒤 1일·2일·4일에서 3시간을 뺀 시간이 지나야, 4 이상이면 보내지 않아요(3.3) | 셀 수 없음(DB 오류) → 그 확인은 아무 방에도 보내지 않음(지금처럼 다음 확인에서 다시)<br>전달 실패(`delivered = false`)는 세지 않음<br>`sent_ago`가 없음(선톡을 보낸 적 없음) → u도 0 | Given 선톡 1번 전달, 친구 답 없음, When 같은 날 다음 칸, Then 안 보냄. When 23시간 뒤 칸, Then 보냄<br>Given 선톡 4번 전달, 답 없음, When 10일 뒤, Then 안 보냄. When 친구가 한 마디 함, Then 다음 칸부터 보냄<br>Given 디스코드 친구가 통화를 시작함, Then u = 0 | active |
| SPEC-187 | 선톡 재료에서 자기 선톡 빼기 | REQ-207 | 선톡 글을 만들 때(`Agent.proactive_message`, AI-11) | '최근 대화'에서 마롱이가 먼저 보낸 줄(선톡, 선 전화 못 받음 한마디)은 글 대신 `[먼저 보낸 말, 위 목록에 있음]`으로 넣고, 최근 7일 동안 보낸 선톡 12개까지를 '지금 상황'의 따로 된 절에 넣어요. 지시문에 그 소재·질문·마롱이 일상을 다시 꺼내지 말라는 줄을 더해요(3.4) | 최근 7일 선톡이 없음 → 그 절을 빼요<br>목록을 못 읽음(DB 오류) → 그 절 없이 만들고 SPEC-188 검사도 건너뜀(로그 `proactive_said_error`) | Given 군밤·이불·별 선톡 3번, When 선톡을 만듦, Then 모델 입력의 '최근 대화'에 세 글이 없고 7일 절에 세 줄이 있음 | active |
| SPEC-188 | 거의 같은 선톡 막기 | REQ-208 | SPEC-187로 만든 보통 선톡(그림 화두가 아님)을 `tidy`한 뒤 | 만든 말과 7일 목록의 말을 하나씩 견줘(이름 부르기를 빼고 글자 바이그램 자카드 유사도, 3.5) 가장 높은 값이 0.35 이상이면 보내지 않아요. 그 칸은 이미 잡혀서(`claim_slot`) 다시 만들지 않아요 | 그림 화두 글(PR #27 `topic`)은 검사하지 않음(그림은 30일 안에 같은 그림을 다시 쓰지 않음, PR #27 SPEC-262)<br>견줄 글자가 2자보다 적음 → 유사도 0 | Given 7일 목록에 "현경아 오늘 군밤 먹었는데 너무 달더라", When 모델이 "현경아 군밤 먹었는데 진짜 달았어"를 냄, Then 안 보냄, 메시지 줄 없음, 로그 `reason=repeat`<br>Given 다른 소재, Then 보냄 | active |
| SPEC-189 | 종일 일정 아침 알림 | REQ-209 | 일정 저장(`schedule_add`의 `check_add`), 날짜만 있는 일정(`all_day`), 알림 시각 없음, 반복 없음, 전화 약속 아님 | 알림 시각을 그날 한국 시각 9시로 정해요. 알림 글은 모델이 쓴 `say`, 없으면 "오늘 {제목} 있는 날이야 📅"(3.6) | 그날 9시가 이미 지남 → 알림 없이 기억만(지금과 같음)<br>반복 일정·전화 약속 → 지금 규칙 그대로<br>친구가 알림 시각을 정함 → 그 시각 | Given 오늘 8시에 "모레 토익"을 날짜만 저장, Then 알림 모레 9:00<br>Given 오늘 10시에 "오늘 회식"을 날짜만, Then 알림 없음<br>Given 매주 반복 종일 일정, Then 알림 없음(지금과 같음) | active |
| SPEC-190 | 괄호 지문 거르기 | REQ-210 | 답과 선톡을 보내기 전 `style.tidy` | 한 줄 안의 `( … )`·`（ … ）`·`* … *` 가운데 3.7의 지문 규칙에 걸리는 것을 지우고 빈칸을 정리해요. 고친 것 이름은 `stage` | 지문만 있던 답 → "응응"(`STAGE_FALLBACK`)<br>지문만 있던 보통 선톡 → 보내지 않음(로그 `reason=stage_only`)<br>지문만 있던 그림 화두 글 → 그림의 고정 글(PR #27 SPEC-271)<br>규칙에 안 걸리는 괄호('(3시)', '(진짜)') → 그대로 | 3.7 표의 입력 10개가 표의 결과와 같음 | active |
| SPEC-191 | 딥시크 늦으면 Claude 같이 출발 | REQ-211, REQ-212 | 딥시크로 보내는 첫 요청(도구 결과를 이어 보내는 요청이 아님), 대신 답하기 켜짐, `MARONG_DEEPSEEK_HEDGE_S` > 0 | 딥시크 요청을 띄우고 첫 응답을 HEDGE_S(기본 20초)까지 기다려요. 그 안에 응답이 오면 지금처럼 딥시크만 써요. 안 오면 Claude에도 같은 요청을 보내고 먼저 성공한 답을 쓰고 진 쪽은 취소해요(3.8, AI-12) | 한쪽이 오류 → 다른 쪽을 기다림, 둘 다 오류 → 마지막 오류(지금처럼 실패 답)<br>딥시크 내용 거절(400 risk)이 먼저 → 지금처럼 거절 답<br>딥시크가 웹 검색을 대신 찾는 중 → Claude를 띄우지 않음<br>설정이 0 → 지금 동작과 같음 | Given 딥시크 1초 응답, Then Claude를 부르지 않음<br>Given 딥시크 25초·Claude 3초, Then Claude 답(`served_model` 있음), 딥시크 취소<br>Given 도구 결과 뒤 요청, Then 같이 출발 안 함 | active |

## 3. 자세한 규칙

### 3.1 하루 횟수·시간 상한(SPEC-184)

지금 [사실]: `proactive.schedule(room, s)`가 방마다 정한 `per_day`·`start_hour`·`end_hour`(없으면 `.env`의 `PROACTIVE_PER_DAY`·`PROACTIVE_HOURS`)를 그대로 써요. 현경님 DM은 하루 36번까지 나갔어요(11/14).

규칙: `marong/config.py`에 상수와 함수를 둬요(`agent.py`가 `proactive.py`를 import하면 순환이라 config에 둠).

```python
PROACTIVE_CAP = 3          # D24: 방마다 정한 수가 더 커도 하루 이만큼까지
PROACTIVE_AWAKE = (8, 22)  # D24: 한국 시각 이 시간 안에서만(22~08시엔 안 보냄)

def proactive_schedule(start, end, per_day, default_hours=PROACTIVE_AWAKE, default_per_day=PROACTIVE_CAP):
    """실제로 쓰는 ((시작 시, 끝 시), 하루 횟수)."""
    hours = (default_hours[0] if start is None else start, default_hours[1] if end is None else end)
    if not 0 <= hours[0] < hours[1] <= 24:
        hours = default_hours
    hours = (max(hours[0], PROACTIVE_AWAKE[0]), min(hours[1], PROACTIVE_AWAKE[1]))
    if hours[0] >= hours[1]:
        hours = PROACTIVE_AWAKE
    return hours, max(1, min(per_day or default_per_day, PROACTIVE_CAP))
```

- `proactive.schedule(room, s)`는 `proactive_schedule(room.get("start_hour"), room.get("end_hour"), room.get("per_day"), s.proactive_hours, s.proactive_per_day)`를 돌려줘요.
- 모든 친구 합 `PROACTIVE_DAILY_MAX`와 PR #27의 `daily_count`(선 전화 벨을 더함)는 그대로예요.
- `Proactive.run` 시작 로그에 상한(하루 3번, 8\~22시)을 더해요.

| 입력(per_day, start, end, 기본 시간, 기본 횟수) | 결과 |
| --- | --- |
| 12, 7, 24, (12, 21), 2 | ((8, 22), 3) |
| None, None, None, (12, 21), 2 | ((12, 21), 2) |
| 2, 23, 24, (12, 21), 2 | ((8, 22), 2) |
| 5, 9, 18, (12, 21), 2 | ((9, 18), 3) |
| 0, 10, 9, (12, 21), 2 | ((12, 21), 2): 시간이 틀려 기본값, 횟수 0은 기본값 |
| -1, None, None, (12, 21), 2 | ((12, 21), 1) |

### 3.2 친구에게 보이는 값(SPEC-185)

- `DiscordAgent._dm_lines(link)`과 안내 명령 답: `hours, per_day = proactive_schedule(link["start_hour"], link["end_hour"], link["per_day"])`의 값으로 "8\~22시에 하루 3번까지"처럼 써요.
- `Agent`의 '지금 상황' 줄("하루 N번쯤 먼저 카톡을 보내")과 `_proactive_situation`의 `guide.format(per_day=…)`: `min(값, PROACTIVE_CAP)`.

### 3.3 답 없는 선톡 백오프(SPEC-186)

| 답 없는 선톡 수 u | 다음 선톡 |
| --- | --- |
| 0 | 지금처럼 칸마다 |
| 1 | 마지막 선톡 뒤 1일 − 3시간 |
| 2 | 마지막 선톡 뒤 2일 − 3시간 |
| 3 | 마지막 선톡 뒤 4일 − 3시간 |
| 4 이상 | 친구가 다시 말하거나 통화를 시작할 때까지 안 보냄 |

3시간을 빼는 건 칸 안에서 보내는 때가 무작위라 다음 날 칸에 걸리게 하려는 것이에요.

`proactive.py`:

```python
BACKOFF = tuple(timedelta(days=d) - timedelta(hours=3) for d in (1, 2, 4))

def backoff(unanswered: int) -> timedelta | None:
    if unanswered <= 0:
        return timedelta(0)
    return BACKOFF[unanswered - 1] if unanswered <= len(BACKOFF) else None
```

`plan()`에서 `failures` 검사 뒤: `wait = backoff(room.get("unanswered") or 0)`; `wait is None`이면 None, `sent_ago`가 있고 `sent_ago < wait`이면 None. `DiscordProactive.plan`은 `super().plan()`을 먼저 부르므로(PR #27) 그림 화두·선 전화 차례도 같이 막혀요 [사실].

카카오 `store.ROOM_STATE`에 열 하나(묶인 방들 함께, 마지막 사람 말 `u.id` 뒤):

```sql
(SELECT count(*) FROM marong.messages a WHERE a.room_key IN <scope(r.room_key)> AND a.id > u.id
   AND a.role = 'assistant' AND a.meta->>'delivered' = 'true'
   AND (a.meta->>'proactive' = 'true' OR a.meta->>'hello' = 'true')) AS unanswered
```

디스코드 `discord_store.DM_STATE`에 열 하나. L은 DM·앱 글(`last_incoming_at`, 앱 글 대화도 `store.incoming`으로 이 값을 바꿈 [사실]), 선톡을 켠 때(`opted_in_at`), 통화 시작 가운데 늦은 때예요. 봇 계정 `marong`은 `call.calls`의 `caller_id`·`started_at`와 `call.callers`를 읽을 수 있어요(`marong/call/schema.sql` GRANT) [사실]. `greatest`는 NULL을 건너뛰어요.

```sql
(SELECT count(*) FROM marong.messages a
  WHERE a.room_key = d.room_key AND a.role = 'assistant' AND a.meta->>'delivered' = 'true'
    AND (a.meta->>'proactive' = 'true' OR a.meta->>'hello' = 'true')
    AND a.created_at > greatest(d.last_incoming_at, d.opted_in_at,
          (SELECT max(c.started_at) FROM call.calls c JOIN call.callers k ON k.id = c.caller_id
            WHERE k.friend_id = d.friend_id))) AS unanswered
```

선 전화를 받으면 통화가 시작돼 L이 바뀌어 u = 0이에요. 선 전화를 못 받으면 못 받음 한마디(`meta.hello`)가 한 번으로 세져요.

### 3.4 선톡 재료(SPEC-187)

1. `store.recent`의 SELECT에 `coalesce(m.meta->>'proactive' = 'true' OR m.meta->>'hello' = 'true', false) AS proactive`를 더해요.
2. `store.recent_proactives(room_key, within, limit)`를 새로 만들어요: 같은 방 범위(`self._reply_rooms`), `role = 'assistant'`, 선톡 또는 못 받음 한마디, 전달됨, `created_at >= now() - within`, 새것부터 `limit`개, 열은 `id, content, created_at`.
3. `Agent.proactive_message(room, topic=None)`(PR #27 모양):
   - 최근 대화는 `recent(room, recent_turns * 2 + 20)`로 넉넉히 읽고, 선톡 줄은 글 대신 `마롱이: [먼저 보낸 말, 위 목록에 있음]`으로 바꾼 뒤 마지막 `recent_turns * 2`줄만 써요. `meta.memory.recent`는 실제로 넣은 첫 줄·끝 줄 id예요.
   - `said = recent_proactives(room, timedelta(days=7), 12)`를 '지금 상황'에 새 절로 넣어요. 제목 `# 최근 7일 동안 마롱이가 먼저 보낸 말 (참고 자료야. 같은 소재·같은 질문·같은 마롱이 일상은 다시 꺼내지 마)`, 줄마다 `- (시각) 글`, 줄바꿈은 ` / `, 200자까지.
   - `PROACTIVE_GUIDE`·`PROACTIVE_GROUP_GUIDE`에 한 줄: `- '최근 7일 동안 마롱이가 먼저 보낸 말'에 있는 소재(먹은 것·산 것·본 것), 질문, 마롱이 일상은 다시 꺼내지 마.`

### 3.5 유사도(SPEC-188)

- `style.py`에 둬요. 비교 전에 친구 이름 부르기('현경아', '현경이', '현경')를 빼요(이름이 같아서 높아지지 않게).
- 빈칸·문장 부호·이모지를 뺀 글자로 글자 바이그램(bigram, 연속 2글자) 집합을 만들고 자카드 유사도(겹친 수 ÷ 합친 수)를 써요.
- `REPEAT_SIMILARITY = 0.35`. 11/17 표본에서 측정한 값: 같은 소재 다른 말(군밤 두 문장) 0.38, (이불 두 문장) 0.36, 다른 소재 0.0\~0.04, '현경아 뭐 해?' 대 '현경아 오늘 출근했어?' 0.2(이름을 빼면 더 낮음). 트라이그램(연속 3글자)은 같은 소재 쌍에서 0.21·0.27로 낮아 바이그램을 골랐어요.
- 막을 때 로그 `proactive_skipped room=<짧은 키> reason=repeat similarity=0.xx`. 보내지 않은 것이 정상 결과예요.
- 답(친구 말에 대한 답)에는 걸지 않아요. 답의 '보내기 전 검사'는 4단계 설계 몫이에요.

### 3.6 종일 일정(SPEC-189)

- `schedules.py`에 `ALL_DAY_REMIND_HOUR = 9`. `check_add`: 조건(전제)이 맞으면 `remind_at = event_at.replace(hour=9)`(종일 `event_at`은 이미 한국 시각 0시 [사실]). 그 시각이 `now`보다 이르면 알림 없이 기억만.
- 도구 설명: `event_at` 끝에 "날짜만 쓴 종일 일정은 remind_at 이 없어도 그날 아침 9시에 마롱이가 먼저 말을 걸어.", `say` 끝에 "종일 일정이면 그날 아침에 건넬 말로(예: '오늘 토익 날이지? 긴장 풀고 잘 보고 와 📝')."
- `GUIDE` 셋째 줄: "시각이 있는 일정만 말했으면 알림 없이 기억만 하고, 알림이 있으면 좋겠다 싶으면 '전날 밤에 알려 줄까?'처럼 한 번만 물어봐. 날짜만 있는 종일 일정은 그날 아침 9시에 마롱이가 먼저 말을 걸어(say 에 그날 아침 말을 써)."
- `reminder_text`: `say`가 없고 종일 일정이면 `f"오늘 {title} 있는 날이야 📅"`.
- 알림은 선톡 하루 상한과 따로 세요(7.2). 9시는 8\~22시 안이에요.
- 이미 저장된 앞날의 종일 일정 채우기는 하지 않아요. 동희님이 따로 말하면 백업 뒤 `UPDATE marong.schedules SET remind_at = event_at + interval '9 hours', updated_at = now() WHERE status = 'active' AND all_day AND remind_at IS NULL AND repeat = 'none' AND event_at + interval '9 hours' > now() RETURNING id;`로 하고 돌려받은 id를 남겨요(되돌리기는 그 id의 `remind_at`을 NULL로).

### 3.7 괄호 지문(SPEC-190)

1. 후보: 한 줄 안의 `( … )`, 전각 `（ … ）`, `* … *` 가운데 안쪽이 40자(별표는 30자) 이하인 것.
2. 지울 것(안쪽 앞뒤 빈칸과 끝의 `.…!~`를 뺀 뒤):
   - '-ㅂ니다/습니다' 서술: 끝이 '니다'이고 그 앞 글자에 받침 ㅂ이 있음. 한글 음절의 받침 번호 `(ord(ch) - 0xAC00) % 28 == 17`이 ㅂ이에요(기다**립**니다, 웃**습**니다, 흔**듭**니다). 정규식 `[ㅂ습]니다`로는 '립'을 못 잡아요.
   - 짧은 '-며/-면서' 동작: 안쪽이 12자 이하이고 '며'나 '면서'로 끝남(속삭이며, 웃으면서).
   - 몸짓·표정 단어: `웃음 미소 한숨 끄덕 침묵 하품 눈물 훌쩍 머쓱 갸웃 두리번 토닥 쓰담 꼬옥 멈칫 뻘쭘 빙긋 싱긋 생긋` 가운데 하나로 시작하고 뒤에 한글 3자까지(끄덕끄덕), 앞에 꾸밈말 하나까지(살짝 조용히 작게 크게 괜히 슬쩍 가만히).
3. 지운 뒤 줄 안 빈칸 2개 이상은 하나로, 빈 줄이 3개 이상 겹치면 2개로.
4. 1:1 방의 '야' 시작 고침(`ya`, PR #17)은 그대로이고 지문을 먼저 지운 뒤 봐요.

| 입력 | 결과 |
| --- | --- |
| (조용히 기다립니다) | 답이면 '응응', 보통 선톡이면 안 보냄 |
| 응 알겠어 (웃음) | 응 알겠어 |
| \*끄덕\* 맞아 | 맞아 |
| 헤헤 (살짝 웃음) 고마워 | 헤헤 고마워 |
| 좋아!⏎⏎(꼬리를 흔듭니다)⏎⏎가자 | 좋아!⏎⏎가자 |
| (속삭이며) 비밀이야 | 비밀이야 |
| 내일 (3시) 보자 | 그대로 |
| 그거 (진짜) 좋다 | 그대로 |
| 오늘 일정(종일)이야 | 그대로 |
| 야 (웃음) 뭐해 (1:1, 이름 현경) | 현경아 뭐해(고친 것 `stage`, `ya`) |

### 3.8 같이 출발(SPEC-191)

지금 [사실]: `DeepSeekLLM.create`는 첫 요청이 오류·시간 초과(`MARONG_DEEPSEEK_TIMEOUT_S`, 코드 기본 30초)일 때만 Claude로 다시 보내요. 딥시크가 실패한 답은 중앙 42초, 딥시크 성공은 중앙 12.1초·상위 25% 17초였어요. Claude가 대신 답하면 응답에 `served_model`을 달고 `Agent.ask`가 그 턴 나머지를 Claude로 이어 가요(`meta.fallback = "deepseek"`). [확인 안 함] 서버의 지금 `MARONG_DEEPSEEK_TIMEOUT_S` 값.

1. 새 설정 `MARONG_DEEPSEEK_HEDGE_S`: 기본 20, 0이면 끔, 켜면 5 이상이고 `timeout_s`보다 작아야 해요(아니면 시작 때 끄고 로그). `from_env`와 시작 로그 `deepseek on …`에 같이 찍어요.
2. 조건: 첫 요청(`not _continuing(body)`)이고 대신 답하기가 켜짐(`_can_fall_back(first)`).
3. 흐름: 지금 `create` 본문을 `_run(body, deadline, first, replied: asyncio.Event | None, fall_back: bool)`로 옮겨요. 첫 `_post`가 응답을 받으면 `replied.set()`. `fall_back=False`면 오류를 Claude로 넘기지 않고 올려요. `create`는 조건이 아니면 지금과 같고, 맞으면 `_run`을 작업으로 띄워 `replied` 또는 작업 끝을 HEDGE_S까지 기다려요. 그 안에 응답이 왔으면 딥시크를 끝까지 기다려요(오류면 지금처럼 Claude가 대신 답함). 아직이면 Claude 작업(`self.claude.create(body, 남은 시간)`, 응답에 `served_model = self.claude_model`)을 띄우고 먼저 성공한 쪽을 돌려주고 진 쪽을 취소해요. Claude는 한 요청에 한 번만 띄워요.
4. 로그: `deepseek_hedge start after=20.0s`, `deepseek_hedge winner=deepseek|claude total=…s`.
5. 비용: Claude가 이기면 Claude 답 값이 들고, 딥시크가 이기면 Claude 요청은 취소되지만 이미 보낸 입력 토큰은 셈해질 수 있어요. 하루 같이 출발 수와 이긴 쪽을 로그로 봐요.

## 4. AI 호출

### AI-11 선톡 만들기(바뀜, SPEC-187·188·190)

| Field | What it says |
| --- | --- |
| Input | 지금과 같은 시스템 프롬프트(성격·지식·지금 상황)에 더해 '최근 7일 동안 마롱이가 먼저 보낸 말' 절(12줄까지, 줄마다 200자까지)과 지시 한 줄. '최근 대화'의 선톡 줄은 자리 표시만 |
| Not sent | 다른 친구 방의 대화(지금 범위 규칙 그대로), 키·이메일 |
| Output | 지금과 같은 자유 글(빈 줄로 나눈 말 여러 개) |
| Checked by the server | `tidy`(지문 SPEC-190, '야'), 빈 답·거절, 그다음 유사도(SPEC-188). 하나라도 걸리면 보내지 않음(그림 화두는 PR #27 SPEC-271의 고정 글) |
| Tools | 없음(지금과 같음) |
| Untrusted input | 7일 목록은 마롱이가 쓴 글이라 지시가 아닌 자료로 표시(절 제목) |
| Time budget and retries | 지금과 같음(`LLM_TIMEOUT_SECONDS` + 2초, 다시 하지 않음). 같이 출발(AI-12)은 선톡에도 걸림 |
| Data handling | 지금 딥시크 중계·Claude 설정 그대로. 새 공급자 없음 |
| Failure | 지금처럼 그 칸은 쉼 |
| Human decision | 없음(1주 지표를 동희님이 봄) |

### AI-12 답 같이 출발(SPEC-191)

| Field | What it says |
| --- | --- |
| Input | 같은 요청 몸통을 딥시크와 Claude에 보냄(지금 대신 답하기와 같은 몸통) |
| Not sent | 지금과 같음 |
| Output | 지금과 같음. Claude가 이기면 `served_model` |
| Checked by the server | 지금과 같음 |
| Tools | 첫 요청만 같이 출발. 도구를 부른 뒤 이어 보내는 요청은 이긴 쪽 모델로만 이어 감(`Agent.ask`의 지금 규칙). 도구 쓰기(일정·쇼핑)는 이긴 답 하나에서만 실행되므로 두 번 실행되지 않음 |
| Untrusted input | 지금과 같음 |
| Time budget and retries | 전체 기한은 지금 `deadline` 그대로. 같이 출발은 HEDGE_S 뒤 한 번만, Claude 재시도 없음. 진 쪽은 취소(응답을 받기 전이면 쓰기 없음) |
| Data handling | Claude로 가는 요청이 지금(딥시크 실패 때만)보다 늘어남. 같은 Anthropic API 계정, 새 데이터 종류 없음 |
| Failure | 둘 다 실패 → 지금 실패 답 |
| Human decision | 없음 |

## 5. 반영 뒤 볼 숫자(7일)

| 숫자 | 반영 전 | 목표 | 어디서 |
| --- | --- | --- | --- |
| 친구 한 명 하루 선톡 수 | 현경님 DM 최대 36 | 3 이하 | `marong.messages`의 `meta.proactive` 줄을 한국 날짜·방별로 셈 |
| 3시간 안에 답이 온 선톡 비율(현경님 DM) | 11/16 0/32 | 절반 넘게 | 같은 표, 선톡 뒤 3시간 안 친구 말 |
| 같은 소재 7일 안 되풀이 | 군밤 17·이불 16·별 9(15일) | 거의 0 | 로그 `reason=repeat` 수와 선톡 글 표본 |
| 22\~08시 선톡 | 있음 | 0 | 같은 표의 한국 시각 |
| 종일 일정 날 아침 알림 | 0 | 일정마다 1 | `marong.schedules`의 `remind_at`·`reminded_at` |
| 딥시크 실패·늦은 답 시간 | 중앙 42초 | 중앙 30초 안(REQ-212) | 로그 `deepseek_hedge`와 답 시간 |
| 괄호 지문이 나간 답 | 세어 둠 | 0 | 로그 `tidy stage` 수와 표본 |
