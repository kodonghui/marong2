-- 통화 스키마 규칙 확인(05단계 검사). 버리는 시험 DB에서만 실행한다. 운영 DB에서 실행하지 않는다.
--   1) 빈 DB에 marong/schema.sql 과 marong/call/schema.sql 을 차례로 적용
--   2) psql -d <시험 DB> -f docs/05-erd/schema-check.sql
-- 'expect error' 줄 다음에는 오류가, 나머지는 성공이 나와야 한다. 마지막 줄은 통화를 지운 뒤
-- 자막·기억·카드·구간·위임 0줄, AI 호출 기록 2줄(음성 구간 1줄·느낌 고르기 1줄, 통화 id 비움, 600초)이어야 한다.
\set ON_ERROR_STOP 0
\echo == setup as postgres
INSERT INTO marong.friends (name) VALUES ('현경') RETURNING id \gset f_
SET ROLE marong_call;
\echo == as marong_call: insert caller, login, call, segment
INSERT INTO call.callers (friend_id) VALUES (:f_id) RETURNING id \gset c_
INSERT INTO call.caller_logins (email_sha256, caller_id, email_hint) VALUES (repeat('a',64), :c_id, 'a***@example.com');
INSERT INTO call.calls (caller_id, client_id, prompt_version, voice) VALUES (:c_id, gen_random_uuid(), 'abc123def456', 'noeul') RETURNING id \gset k_
\echo -- expect error: second open call for same caller
INSERT INTO call.calls (caller_id, client_id, prompt_version, voice) VALUES (:c_id, gen_random_uuid(), 'x', 'noeul');
INSERT INTO call.segments (call_id, mode, client_id) VALUES (:'k_id', 'start', gen_random_uuid()) RETURNING id \gset s_
\echo -- expect error: second open segment
INSERT INTO call.segments (call_id, mode, client_id) VALUES (:'k_id', 'reconnect', gen_random_uuid());
\echo -- expect error: open without session id
UPDATE call.segments SET state='open' WHERE id=:'s_id';
UPDATE call.segments SET state='open', openai_session_id='live_1' WHERE id=:'s_id';
INSERT INTO call.turns (call_id, segment_id, seq, role, content, started_at, ended_at) VALUES (:'k_id', :'s_id', 1, 'user', '내 생일 3월 14일이야 기억해 줘', now(), now()) RETURNING id \gset t_
INSERT INTO call.memories (caller_id, call_id, source, content, quote, turn_id, idem_key) VALUES (:c_id, :'k_id', 'delegation', '생일 3월 14일', '생일 3월 14일', :t_id, repeat('b',64));
\echo -- expect error: duplicate idem key
INSERT INTO call.memories (caller_id, call_id, source, content, quote, turn_id, idem_key) VALUES (:c_id, :'k_id', 'delegation', '생일 3월 14일', '생일 3월 14일', :t_id, repeat('b',64));
INSERT INTO call.delegations (call_id, segment_id, openai_delegation_id, intent, state, result) VALUES (:'k_id', :'s_id', 'dlg_1', 'remember', 'done', 'saved');
\echo -- expect error: ended without ended_at/end_reason
UPDATE call.calls SET status='ended' WHERE id=:'k_id';
UPDATE call.segments SET state='closed', closed_at=now(), close_reason='user_hangup' WHERE id=:'s_id';
INSERT INTO call.ai_runs (kind, call_id, segment_id, segment_ref, trace_id, model, prompt_version, sent_at, usage_seconds, outcome, stop_reason) VALUES ('live_session', :'k_id', :'s_id', :'s_id', 't1', 'gpt-live-1', 'abc123def456', now(), 600, 'ok', 'close_requested');
\echo -- expect error: same live segment counted twice
INSERT INTO call.ai_runs (kind, segment_ref, trace_id, model, prompt_version, sent_at, usage_seconds, outcome) VALUES ('live_session', :'s_id', 't2', 'gpt-live-1', 'x', now(), 1, 'ok');
INSERT INTO call.ai_runs (kind, call_id, segment_id, trace_id, model, prompt_version, sent_at, total_ms, input_tokens, output_tokens, outcome) VALUES ('mood_classify', :'k_id', :'s_id', 't3', 'gpt-6-luna', 'mood1', now(), 420, 60, 5, 'ok');
\echo -- expect error: unknown ai_runs kind
INSERT INTO call.ai_runs (kind, trace_id, model, prompt_version, sent_at, outcome) VALUES ('face_pick', 't4', 'x', 'x', now(), 'ok');
UPDATE call.calls SET status='ended', ended_at=now(), end_reason='hangup', organize_status='pending' WHERE id=:'k_id';
\echo -- expect error: empty voice
INSERT INTO call.calls (caller_id, client_id, prompt_version, voice) VALUES (:c_id, gen_random_uuid(), 'x', '');
INSERT INTO call.cards (call_id, summary, model, prompt_version) VALUES (:'k_id', '생일 얘기', 'claude-haiku-5-5', 'org1');
\echo -- expect error: budget 0
UPDATE call.settings SET value='0'::jsonb WHERE key='monthly_budget_usd';
UPDATE call.settings SET value='200'::jsonb WHERE key='monthly_budget_usd';
INSERT INTO call.budget_events (month, kind, spent_usd, budget_usd) VALUES (date_trunc('month', now() AT TIME ZONE 'UTC')::date, 'warn', 120, 150);
\echo -- expect error: second warn same month
INSERT INTO call.budget_events (month, kind, spent_usd, budget_usd) VALUES (date_trunc('month', now() AT TIME ZONE 'UTC')::date, 'warn', 121, 150);
\echo -- expect error: marong_call cannot write marong tables
INSERT INTO marong.friends (name) VALUES ('x');
RESET ROLE;
\echo == as marong (Kakao bot)
SET ROLE marong;
SELECT count(*) AS cards_visible FROM call.cards;
SELECT id, status, organize_status FROM call.calls;
\echo -- expect error: marong cannot read turns
SELECT count(*) FROM call.turns;
\echo -- expect error: marong cannot read calls.client_id
SELECT client_id FROM call.calls;
\echo -- expect error: marong cannot delete cards
DELETE FROM call.cards;
RESET ROLE;
\echo == delete call as marong_call (cascade, ai_runs kept)
SET ROLE marong_call;
DELETE FROM call.calls WHERE id=:'k_id';
SELECT (SELECT count(*) FROM call.turns) turns, (SELECT count(*) FROM call.memories) memories, (SELECT count(*) FROM call.cards) cards, (SELECT count(*) FROM call.segments) segments, (SELECT count(*) FROM call.delegations) delegations, (SELECT count(*) || ' rows, call_id null=' || bool_and(call_id IS NULL) || ', seconds=' || sum(usage_seconds) FROM call.ai_runs) ai_runs;
RESET ROLE;
