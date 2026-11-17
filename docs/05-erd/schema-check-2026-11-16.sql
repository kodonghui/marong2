-- 마롱이의 일기·통화 비용 표 규칙 확인(05단계 검사, 2026-11-16). 버리는 시험 DB에서만 실행한다. 운영 DB에서 실행하지 않는다.
--   1) 빈 DB에 marong/schema.sql → marong/call/schema.sql → 통화 002~004 → 카톡 010~013 → 통화 005·006 → 카톡 014·015
--      → 카톡 016·017 → 통화 007 순서로 적용
--   2) psql -d <시험 DB> -f docs/05-erd/schema-check-2026-11-16.sql
-- 'expect error' 줄 다음에는 오류가, 나머지는 성공이 나와야 한다(기대한 오류 35개). 끝의 세 결과 줄은
-- 구간 비용(저장 값 0.034800·추정 0.500000), 시트 칸(입력 9,000·출력 900, 0.534800달러, 추정 있음, base-20261116),
-- 통화를 지운 뒤 사용량 2줄(통화 id·구간 id 비움, 합 0.534800달러)이어야 한다.
\set ON_ERROR_STOP 0
\echo == setup as postgres
INSERT INTO marong.friends (name) VALUES ('현경') RETURNING id \gset f_
INSERT INTO marong.friends (name) VALUES ('동희') RETURNING id \gset g_

\echo == diary as marong (bot account)
SET ROLE marong;
INSERT INTO marong.diary_settings (friend_id, enabled, from_date) VALUES (:f_id, true, '2026-11-17');
\echo -- expect error 1: off --now cannot be an "on" row
INSERT INTO marong.diary_settings (friend_id, enabled, from_date, stop_now) VALUES (:f_id, true, '2026-11-18', true);
\echo -- expect error 2: settings rows are never changed
UPDATE marong.diary_settings SET enabled = false;
\echo -- expect error 3: settings rows are never deleted
DELETE FROM marong.diary_settings;
INSERT INTO marong.diary_looks (friend_id, hair, glasses, top) VALUES (:f_id, 'long', 'round', 'navy');
\echo -- expect error 4: a look card is all three values or none
INSERT INTO marong.diary_looks (friend_id, hair) VALUES (:g_id, 'bob');
\echo -- expect error 5: look values come from the list only
UPDATE marong.diary_looks SET hair = 'blue' WHERE friend_id = :f_id;
\echo == clearing the card sets the values to NULL
UPDATE marong.diary_looks SET hair = NULL, glasses = NULL, top = NULL, updated_at = now() WHERE friend_id = :f_id;
UPDATE marong.diary_looks SET hair = 'long', glasses = 'round', top = 'navy', updated_at = now() WHERE friend_id = :f_id;

INSERT INTO marong.diaries (friend_id, diary_date) VALUES (:f_id, '2026-11-16') RETURNING id \gset d_
\echo -- expect error 6: one diary per friend and diary day
INSERT INTO marong.diaries (friend_id, diary_date) VALUES (:f_id, '2026-11-16');
\echo -- expect error 7: failed needs a reason
UPDATE marong.diaries SET state = 'failed' WHERE id = :d_id;
\echo -- expect error 8: only a ready diary can be hidden
UPDATE marong.diaries SET hidden = true WHERE id = :d_id;
\echo -- expect error 9: ready needs a revision
UPDATE marong.diaries SET state = 'ready', ready_at = now() WHERE id = :d_id;
UPDATE marong.diaries SET state = 'writing', lease_until = now() + interval '10 minutes' WHERE id = :d_id;
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, effort, sent_at, total_ms,
  input_tokens, output_tokens, outcome, stop_reason)
  VALUES (:d_id, 'write', 'night', 'night-1', 'test-text-model', 'diary-v1', 'xhigh', now(), 61000, 6000, 5000, 'ok', 'end_turn')
  RETURNING id \gset w_
\echo -- expect error 10: a fix call cannot come from the night job
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, sent_at, outcome)
  VALUES (:d_id, 'fix', 'night', 'x', 'test-text-model', 'diary-v1', now(), 'ok');
INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body, scene, ai_run_id)
  VALUES (:d_id, 1, 'write', '붕어빵 얘기', 'sunny',
          '오늘 현경이랑 전화로 붕어빵 얘기를 했다. 현경이는 팥보다 슈크림이 좋대. 나는 둘 다 좋은데 군밤이 제일 좋다. 다음에 같이 먹으면 좋겠다.',
          'The little white character eats roasted chestnuts under the stars.', :w_id);
\echo -- expect error 11: text shorter than 60 characters
INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body, ai_run_id)
  VALUES (:d_id, 2, 'fix', '짧은 글', 'rain', '너무 짧은 일기.', :w_id);
\echo -- expect error 12: a fix revision names its model call
INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body)
  SELECT diary_id, 2, 'fix', title, weather, body FROM marong.diary_revisions WHERE diary_id = :d_id AND revision = 1;
UPDATE marong.diaries SET state = 'drawing', revision = 1, lease_until = NULL WHERE id = :d_id;
\echo -- expect error 13: the current revision must exist for this diary
UPDATE marong.diaries SET revision = 9 WHERE id = :d_id;
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, effort, sent_at, total_ms,
  input_tokens, image_input_tokens, output_tokens, cost_usd, outcome)
  VALUES (:d_id, 'draw', 'night', 'night-1', 'test-image-model', 'draw-v1', 'low', now(), 21000, 700, 400, 600, 0.0227, 'ok')
  RETURNING id \gset r_
INSERT INTO marong.diary_drawings (diary_id, revision, origin, ai_run_id, format, width, height, image)
  VALUES (:d_id, 1, 'night', :r_id, 'webp', 1536, 1024, decode('52494646', 'hex')) RETURNING id \gset dr_
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, sent_at, outcome)
  VALUES (:d_id, 'draw', 'retry', 'night-2', 'test-image-model', 'draw-v1', now(), 'ok') RETURNING id \gset r2_
\echo -- expect error 14: a portrait picture is refused
INSERT INTO marong.diary_drawings (diary_id, revision, origin, ai_run_id, format, width, height, image)
  VALUES (:d_id, 1, 'retry', :r2_id, 'webp', 1024, 1536, decode('52494646', 'hex'));
\echo -- expect error 15: a picture over 5 MB is refused
INSERT INTO marong.diary_drawings (diary_id, revision, origin, ai_run_id, format, width, height, image)
  VALUES (:d_id, 1, 'retry', :r2_id, 'png', 1536, 1024, decode(repeat('00', 5242881), 'hex'));
UPDATE marong.diaries SET state = 'ready', ready_at = now(), drawing_id = :'dr_id', notice_state = 'waiting',
  notice_next_at = '2026-11-16 23:30:00+00' WHERE id = :d_id;

\echo == a diary and drawing of another friend
INSERT INTO marong.diaries (friend_id, diary_date) VALUES (:g_id, '2026-11-16') RETURNING id \gset e_
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, sent_at, outcome)
  VALUES (:e_id, 'write', 'night', 'night-1', 'test-text-model', 'diary-v1', now(), 'ok') RETURNING id \gset ew_
INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body, scene, ai_run_id)
  SELECT :e_id, 1, 'write', title, 'cloudy', body, scene, :ew_id FROM marong.diary_revisions WHERE diary_id = :d_id;
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, sent_at, cost_usd, cost_estimated, outcome)
  VALUES (:e_id, 'draw', 'night', 'night-1', 'test-image-model', 'draw-v1', now(), 0.025, true, 'ok') RETURNING id \gset er_
INSERT INTO marong.diary_drawings (diary_id, revision, origin, ai_run_id, format, width, height, image)
  VALUES (:e_id, 1, 'night', :er_id, 'png', 1536, 1024, decode('89504e47', 'hex')) RETURNING id \gset edr_
\echo -- expect error 16: the current drawing must belong to this diary
UPDATE marong.diaries SET drawing_id = :'edr_id' WHERE id = :d_id;
\echo -- expect error 17: an estimated cost needs a value
INSERT INTO marong.diary_ai_runs (diary_id, kind, origin, trace_id, model, prompt_version, sent_at, cost_estimated, outcome)
  VALUES (:e_id, 'draw', 'redraw', 'x', 'test-image-model', 'draw-v1', now(), true, 'error');

\echo == ready diary: hide, stamp, weather revision, notice
UPDATE marong.diaries SET hidden = true, stamped_at = now(), updated_at = now() WHERE id = :d_id;
UPDATE marong.diaries SET hidden = false WHERE id = :d_id;
INSERT INTO marong.diary_revisions (diary_id, revision, source, title, weather, body, scene)
  SELECT diary_id, 2, 'weather', title, 'rain', body, scene FROM marong.diary_revisions WHERE diary_id = :d_id AND revision = 1;
UPDATE marong.diaries SET revision = 2 WHERE id = :d_id;
\echo -- expect error 18: five successful fixes at most
UPDATE marong.diaries SET fixes_used = 6 WHERE id = :d_id;
\echo -- expect error 19: two successful redraws at most
UPDATE marong.diaries SET redraws_used = 3 WHERE id = :d_id;
\echo -- expect error 20: sent needs the time it was sent
UPDATE marong.diaries SET notice_state = 'sent' WHERE id = :d_id;
\echo -- expect error 21: sending is saved with its time first
UPDATE marong.diaries SET notice_state = 'sending' WHERE id = :d_id;
UPDATE marong.diaries SET notice_state = 'sending', notice_sending_at = now() WHERE id = :d_id;
UPDATE marong.diaries SET notice_state = 'sent', notified_at = now(), notice_line = 2 WHERE id = :d_id;
\echo -- expect error 22: a busy lease needs its end time
UPDATE marong.diaries SET busy = 'fix' WHERE id = :d_id;
INSERT INTO marong.diary_requests (friend_id, idem_key, diary_id, kind) VALUES (:f_id, '11111111-1111-1111-1111-111111111111', :d_id, 'fix');
\echo -- expect error 23: the same idempotency key is stored once
INSERT INTO marong.diary_requests (friend_id, idem_key, diary_id, kind) VALUES (:f_id, '11111111-1111-1111-1111-111111111111', :d_id, 'fix');
\echo -- expect error 24: a result needs its finish time
UPDATE marong.diary_requests SET result_code = 'fix_failed' WHERE friend_id = :f_id;
UPDATE marong.diary_requests SET result_code = 'fix_failed', finished_at = now() WHERE friend_id = :f_id;
\echo -- expect error 25: revisions are never changed
UPDATE marong.diary_revisions SET title = '바꾼 제목' WHERE diary_id = :d_id;
\echo -- expect error 26: drawings are never deleted
DELETE FROM marong.diary_drawings WHERE diary_id = :d_id;
\echo -- expect error 27: diaries are never deleted
DELETE FROM marong.diaries WHERE id = :d_id;

\echo == listening test answers
INSERT INTO marong.listen_scores (test_id, friend_id, clip_id, sentence_no, score, marong_like)
  VALUES ('listen-1', :f_id, 'a1b2c3d4', 1, 4, true);
INSERT INTO marong.listen_scores (test_id, friend_id, clip_id, sentence_no, score)
  VALUES ('listen-1', :f_id, 'e5f6a7b8', 1, 3);
\echo -- expect error 28: one sounds-like-Marong pick per sentence
UPDATE marong.listen_scores SET marong_like = true WHERE clip_id = 'e5f6a7b8';
\echo == answering again keeps the last answer
INSERT INTO marong.listen_scores (test_id, friend_id, clip_id, sentence_no, score) VALUES ('listen-1', :f_id, 'e5f6a7b8', 1, 5)
  ON CONFLICT (test_id, friend_id, clip_id) DO UPDATE SET score = EXCLUDED.score, updated_at = now();
\echo -- expect error 29: scores are 1 to 5
UPDATE marong.listen_scores SET score = 6 WHERE clip_id = 'a1b2c3d4';
\echo == moving the pick off a clip with no score leaves a no-answer row (06 API-123)
INSERT INTO marong.listen_scores (test_id, friend_id, clip_id, sentence_no, marong_like)
  VALUES ('listen-1', :f_id, 'c9d0e1f2', 2, true);
UPDATE marong.listen_scores SET marong_like = false, updated_at = now() WHERE clip_id = 'c9d0e1f2';
INSERT INTO marong.listen_scores (test_id, friend_id, clip_id, sentence_no, score, marong_like)
  VALUES ('listen-1', :f_id, 'a9b8c7d6', 2, 4, true);
RESET ROLE;

\echo == call cost as marong_call
SET ROLE marong_call;
INSERT INTO call.callers (friend_id) VALUES (:f_id) RETURNING id \gset c_
INSERT INTO call.calls (caller_id, client_id, prompt_version, voice) VALUES (:c_id, gen_random_uuid(), 'p1', 'Sulafat') RETURNING id \gset k_
INSERT INTO call.segments (call_id, mode, client_id, state, provider, provider_model, provider_ready_at, tuning, opened_at)
  VALUES (:'k_id', 'reconnect', gen_random_uuid(), 'open', 'vertex', 'gemini-3.8-live', now(), 'base-20261116',
          now() - interval '20 minutes') RETURNING id \gset s_
\echo -- expect error 30: the tuning of a segment must exist
UPDATE call.segments SET tuning = 'nope' WHERE id = :'s_id';
INSERT INTO call.live_usage (call_id, segment_id, segment_ref, seq, received_at, entrypoint, tuning, model, text_in, audio_in,
  text_out, audio_out, price_id, usd)
  SELECT :'k_id', :'s_id', :'s_id', 1, now(), 'web', 'base-20261116', 'gemini-3.8-live', 1000, 8000, 100, 800, id,
         round((1000 * text_in + 8000 * audio_in + 100 * text_out + 800 * audio_out) / 1000000, 6)
  FROM call.live_prices WHERE model = 'gemini-3.8-live';
\echo -- expect error 31: the same turn is stored once
INSERT INTO call.live_usage (call_id, segment_id, segment_ref, seq, received_at, entrypoint, model)
  VALUES (:'k_id', :'s_id', :'s_id', 1, now(), 'web', 'gemini-3.8-live');
\echo -- expect error 32: a priced turn has dollars
INSERT INTO call.live_usage (call_id, segment_id, segment_ref, seq, received_at, entrypoint, model, price_id)
  SELECT :'k_id', :'s_id', :'s_id', 2, now(), 'web', 'gemini-3.8-live', id FROM call.live_prices WHERE model = 'gemini-3.8-live';
\echo == text handoff: close the old segment (handoff) and open the new one in one transaction
BEGIN;
UPDATE call.segments SET state = 'closed', closed_at = now() - interval '10 minutes', close_reason = 'handoff',
  mic_sent_ms = 420000, mic_held_ms = 180000 WHERE id = :'s_id';
INSERT INTO call.segments (call_id, mode, client_id, state, provider, provider_model, provider_ready_at, tuning, opened_at)
  VALUES (:'k_id', 'handoff', gen_random_uuid(), 'open', 'vertex', 'gemini-3.8-live', now(), 'base-20261116',
          now() - interval '10 minutes') RETURNING id \gset h_
COMMIT;
UPDATE call.segments SET state = 'closed', closed_at = opened_at + interval '10 minutes', close_reason = 'user_hangup'
  WHERE id = :'h_id';
\echo -- expect error 33: unknown segment mode
INSERT INTO call.segments (call_id, mode, client_id) VALUES (:'k_id', 'teleport', gen_random_uuid());
INSERT INTO call.live_prices (model, starts_at, text_in, audio_in, image_in, text_out, audio_out, checked_on, source)
  VALUES ('gemini-3.8-live', '2026-12-01 00:00:00+00', 0.75, 3.00, 1.00, 4.50, 12.00, '2026-11-16', 'test');
\echo -- expect error 34: prices are only added
UPDATE call.live_prices SET audio_in = 1 WHERE model = 'gemini-3.8-live';
INSERT INTO call.live_tunings (name, compression_trigger, compression_target, vad_silence_ms, vad_prefix_ms,
  max_output_tokens, seed_call_memories, web_quiet_mic, quiet_rms, text_handoff, handoff_tokens, handoff_chars)
  VALUES ('t2', 16384, 8192, 700, 100, 1024, 15, true, 0.018, true, 7000, 4000);
\echo -- expect error 35: compression target over half of the trigger
INSERT INTO call.live_tunings (name, compression_trigger, compression_target, vad_silence_ms, vad_prefix_ms,
  max_output_tokens, seed_call_memories, web_quiet_mic, quiet_rms, text_handoff, handoff_tokens, handoff_chars)
  VALUES ('t3', 8192, 5000, 700, 100, 1024, 30, false, 0.018, false, 7000, 4000);
UPDATE call.settings SET value = '"t2"'::jsonb, updated_at = now() WHERE key = 'live_tuning';
INSERT INTO call.settings (key, value) VALUES ('credit_checked_on', '"2026-11-16"'::jsonb);
INSERT INTO call.live_counters (month, entrypoint, name, count) VALUES ('2026-11-01', 'web', 'budget_unknown', 1)
  ON CONFLICT (month, entrypoint, name) DO UPDATE SET count = call.live_counters.count + EXCLUDED.count, updated_at = now();
INSERT INTO call.live_counters (month, entrypoint, name, count) VALUES ('2026-11-01', 'web', 'budget_unknown', 2)
  ON CONFLICT (month, entrypoint, name) DO UPDATE SET count = call.live_counters.count + EXCLUDED.count, updated_at = now();
UPDATE call.calls SET status = 'ended', ended_at = now(), end_reason = 'budget_hard_stop', organize_status = 'pending' WHERE id = :'k_id';
INSERT INTO call.ai_runs (kind, call_id, trace_id, model, prompt_version, thinking, sent_at, total_ms, input_tokens,
  output_tokens, thoughts_tokens, outcome) VALUES ('organize', :'k_id', 'organize:x', 'gemini-3.8-flash', 'o1', 'LOW', now(), 900, 3000, 200, 150, 'ok');
\echo == result 1: segment costs (stored 0.034800, estimated 0.500000)
SELECT mode, usage_rows, estimated, usd FROM call.segment_costs sc JOIN call.segments s ON s.id = sc.segment_id ORDER BY s.opened_at;
SELECT name, count FROM call.live_counters;
RESET ROLE;
\echo == result 2: spreadsheet columns (as marong)
SET ROLE marong;
SELECT segment_count, input_tokens, output_tokens, usd, usd_estimated, tunings FROM call.session_report;
RESET ROLE;
\echo == delete the call as marong_call: the estimate row first, then the call
SET ROLE marong_call;
INSERT INTO call.live_usage (kind, call_id, segment_id, segment_ref, seq, received_at, entrypoint, tuning, model, seconds, usd)
  SELECT 'estimate', call_id, segment_id, segment_id, 0, opened_at, entrypoint, tuning, 'gemini-3.8-live', seconds, usd
  FROM call.segment_costs WHERE call_id = :'k_id' AND estimated;
DELETE FROM call.calls WHERE id = :'k_id';
\echo == result 3: usage rows kept (2 rows, ids cleared, 0.534800)
SELECT count(*) AS rows, bool_and(call_id IS NULL AND segment_id IS NULL) AS ids_cleared, sum(usd) AS usd FROM call.live_usage;
RESET ROLE;
