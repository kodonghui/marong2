-- Call cost on the Gemini path (CTX-006) and tuning experiments (CTX-002). Design: docs/04-functional-spec/call-cost.md
-- (functional spec), docs/05-erd/erd.md (picture). Apply after 006_discord_shared_callers.sql as the migration
-- administrator. The web call server and the Discord voice relay both write with the call account (marong_call).
-- Numbers and labels only: no transcript, instruction, memory or search query reaches these tables (REQ-195).
-- Months here are UTC months, like the first budget design.
-- without a table: TERM-036 (Google Cloud spend cap, set in the cloud console), TERM-038 (text handoff, a segment mode)
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
SET LOCAL ROLE marong_owner;

-- Changes to existing call tables. These lines name no table this file creates, so their IDs are plain mentions.
-- segments (TBL-004) ← SPEC-177, SPEC-178, SPEC-179: the tuning a segment used (kept for the whole segment), the web
-- mic gate's sent and held time, and the text handoff as a new mode and close reason.
ALTER TABLE call.segments
  ADD COLUMN IF NOT EXISTS tuning text,
  ADD COLUMN IF NOT EXISTS mic_sent_ms integer CHECK (mic_sent_ms >= 0),
  ADD COLUMN IF NOT EXISTS mic_held_ms integer CHECK (mic_held_ms >= 0);
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid = 'call.segments'::regclass AND contype = 'c'
    AND (pg_get_constraintdef(oid) LIKE '%(mode = ANY%' OR pg_get_constraintdef(oid) LIKE '%(close_reason = ANY%')
  LOOP EXECUTE format('ALTER TABLE call.segments DROP CONSTRAINT %I', r.conname); END LOOP;
END $$;
ALTER TABLE call.segments ADD CONSTRAINT segments_mode_check
  CHECK (mode IN ('start', 'reconnect', 'wake', 'takeover', 'renew', 'handoff'));
ALTER TABLE call.segments ADD CONSTRAINT segments_close_reason_check
  CHECK (close_reason IN ('user_hangup', 'close_requested', 'expired', 'content', 'remote_hangup', 'connection_lost',
                          'server_rest', 'takeover', 'beat_lost', 'budget_hard_stop', 'reconnect_limit',
                          'server_restart', 'sideband_failed', 'start_failed', 'renewed', 'unknown', 'handoff'));

-- settings (TBL-009) ← SPEC-169, SPEC-177, SPEC-180: the current tuning, the day the cloud credit was last checked and
-- whether the engine reports usage per turn or cumulatively (decided by the probe before implementation).
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid = 'call.settings'::regclass AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%(key = ANY%'
  LOOP EXECUTE format('ALTER TABLE call.settings DROP CONSTRAINT %I', r.conname); END LOOP;
END $$;
ALTER TABLE call.settings ADD CONSTRAINT settings_key_check
  CHECK (key IN ('monthly_budget_usd', 'usd_per_minute', 'voice', 'live_tuning', 'credit_checked_on', 'usage_mode'));
ALTER TABLE call.settings DROP CONSTRAINT IF EXISTS settings_live_tuning_check;
ALTER TABLE call.settings ADD CONSTRAINT settings_live_tuning_check
  CHECK (key <> 'live_tuning' OR (jsonb_typeof(value) = 'string' AND (value #>> '{}') ~ '^[a-z0-9-]{2,40}$'));
ALTER TABLE call.settings DROP CONSTRAINT IF EXISTS settings_credit_checked_on_check;
ALTER TABLE call.settings ADD CONSTRAINT settings_credit_checked_on_check
  CHECK (key <> 'credit_checked_on' OR (jsonb_typeof(value) = 'string'
                                        AND (value #>> '{}') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'));
ALTER TABLE call.settings DROP CONSTRAINT IF EXISTS settings_usage_mode_check;
ALTER TABLE call.settings ADD CONSTRAINT settings_usage_mode_check
  CHECK (key <> 'usage_mode' OR value IN ('"turn"'::jsonb, '"cumulative"'::jsonb));
INSERT INTO call.settings (key, value) VALUES ('live_tuning', '"base-20261116"'::jsonb) ON CONFLICT (key) DO NOTHING;

-- ai_runs (TBL-011) ← SPEC-173: the organizer's thinking tokens, priced at the output price.
ALTER TABLE call.ai_runs ADD COLUMN IF NOT EXISTS thoughts_tokens integer CHECK (thoughts_tokens >= 0);

-- TBL-110 live_prices (CTX-006) ← SPEC-170, SPEC-172, SPEC-173, SPEC-180 | terms: TERM-035
-- Rule: rows are only added. The price of usage is the row of the same model with the latest starts_at at or before
-- the time the usage was received; dollars already priced never change (REQ-187). US dollars per 1M tokens.
CREATE TABLE IF NOT EXISTS call.live_prices (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model                 text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 100),
  starts_at             timestamptz NOT NULL,
  text_in               numeric(10, 4) NOT NULL CHECK (text_in >= 0),
  audio_in              numeric(10, 4) NOT NULL CHECK (audio_in >= 0),
  image_in              numeric(10, 4) NOT NULL CHECK (image_in >= 0),
  text_out              numeric(10, 4) NOT NULL CHECK (text_out >= 0),
  audio_out             numeric(10, 4) NOT NULL CHECK (audio_out >= 0),
  search_per_1000       numeric(10, 4) NOT NULL DEFAULT 0 CHECK (search_per_1000 >= 0),
  search_free_per_month integer NOT NULL DEFAULT 0 CHECK (search_free_per_month >= 0),
  checked_on            date NOT NULL,                     -- the cost view asks for a recheck after 90 days (REQ-188)
  source                text NOT NULL CHECK (char_length(source) BETWEEN 1 AND 200),
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (model, starts_at)
);
INSERT INTO call.live_prices (model, starts_at, text_in, audio_in, image_in, text_out, audio_out, search_per_1000,
                              search_free_per_month, checked_on, source) VALUES
  ('gemini-3.8-live', '2026-07-01 00:00:00+00', 0.75, 3.00, 1.00, 4.50, 12.00, 14, 5000, '2026-11-16',
   'Vertex AI pricing page, regional endpoint'),
  ('gemini-3.8-flash', '2026-11-01 00:00:00+00', 0.75, 0.75, 0.75, 3.75, 3.75, 0, 0, '2026-11-16',
   'Gemini API pricing page; Vertex value to confirm'),
  ('gemini-3.8-flash', '2027-01-01 00:00:00+00', 1.50, 1.50, 1.50, 7.50, 7.50, 0, 0, '2026-11-16',
   'Gemini API pricing page; Vertex value to confirm')
  ON CONFLICT (model, starts_at) DO NOTHING;

-- TBL-111 live_tunings (CTX-002) ← SPEC-177, SPEC-178, SPEC-179, SPEC-180 | terms: TERM-037
-- Rule: one name, one set of values; rows are only added. A segment reads the current tuning when it opens and keeps
-- it (REQ-189). Voice, language and instructions are not tuning values. Ranges and defaults: functional spec 3.3.
CREATE TABLE IF NOT EXISTS call.live_tunings (
  name                text PRIMARY KEY CHECK (name ~ '^[a-z0-9-]{2,40}$'),
  compression_trigger integer NOT NULL CHECK (compression_trigger BETWEEN 2048 AND 32768),
  compression_target  integer NOT NULL CHECK (compression_target >= 1024 AND compression_target * 2 <= compression_trigger),
  vad_silence_ms      integer NOT NULL CHECK (vad_silence_ms BETWEEN 300 AND 2000),
  vad_prefix_ms       integer NOT NULL CHECK (vad_prefix_ms BETWEEN 0 AND 500),
  max_output_tokens   integer NOT NULL CHECK (max_output_tokens BETWEEN 256 AND 2048),
  seed_call_memories  smallint NOT NULL CHECK (seed_call_memories BETWEEN 0 AND 30),
  web_quiet_mic       boolean NOT NULL,
  quiet_rms           numeric(5, 4) NOT NULL CHECK (quiet_rms BETWEEN 0.005 AND 0.05),
  text_handoff        boolean NOT NULL,
  handoff_tokens      integer NOT NULL CHECK (handoff_tokens BETWEEN 3000 AND 30000),
  handoff_chars       integer NOT NULL CHECK (handoff_chars BETWEEN 1000 AND 8000),
  created_at          timestamptz NOT NULL DEFAULT now()
);
INSERT INTO call.live_tunings (name, compression_trigger, compression_target, vad_silence_ms, vad_prefix_ms,
                               max_output_tokens, seed_call_memories, web_quiet_mic, quiet_rms, text_handoff,
                               handoff_tokens, handoff_chars)
  VALUES ('base-20261116', 8192, 4096, 700, 100, 1024, 30, false, 0.018, false, 7000, 4000)
  ON CONFLICT (name) DO NOTHING;
-- A segment's tuning name must exist (older segments have none).
ALTER TABLE call.segments DROP CONSTRAINT IF EXISTS segments_tuning_fkey;
ALTER TABLE call.segments ADD CONSTRAINT segments_tuning_fkey
  FOREIGN KEY (tuning) REFERENCES call.live_tunings (name) ON DELETE RESTRICT;

-- TBL-112 live_usage (CTX-006) ← SPEC-169, SPEC-170, SPEC-171, SPEC-173, SPEC-180, SPEC-181 | terms: TERM-034
-- One row per turn the engine reported (kind turn), saved by the segment's writer every 2 s and when it closes.
-- Rule: (segment_ref, seq) is saved once. Rows outlive the call: deleting a call clears call_id and segment_id and keeps
-- segment_ref and the dollars; it first adds one estimate row for a segment that is counted as an estimate, so this
-- month's cost does not drop (SPEC-171).
CREATE TABLE IF NOT EXISTS call.live_usage (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind            text NOT NULL DEFAULT 'turn' CHECK (kind IN ('turn', 'estimate')),
  call_id         uuid REFERENCES call.calls (id) ON DELETE SET NULL,
  segment_id      uuid REFERENCES call.segments (id) ON DELETE SET NULL,
  segment_ref     uuid NOT NULL,                           -- the segment id, kept after the call is deleted (no key)
  seq             integer NOT NULL CHECK (seq >= 0),       -- order in the segment; 0 for the estimate row
  received_at     timestamptz NOT NULL,                    -- an estimate row carries the segment's open time
  entrypoint      text NOT NULL CHECK (entrypoint IN ('web', 'discord')),
  tuning          text REFERENCES call.live_tunings (name) ON DELETE RESTRICT,
  model           text NOT NULL,
  text_in         integer NOT NULL DEFAULT 0 CHECK (text_in >= 0),
  audio_in        integer NOT NULL DEFAULT 0 CHECK (audio_in >= 0),
  image_in        integer NOT NULL DEFAULT 0 CHECK (image_in >= 0),       -- image and video
  tool_in         integer NOT NULL DEFAULT 0 CHECK (tool_in >= 0),
  cached_in       integer NOT NULL DEFAULT 0 CHECK (cached_in >= 0),      -- part of the input, priced as input for now
  text_out        integer NOT NULL DEFAULT 0 CHECK (text_out >= 0),
  audio_out       integer NOT NULL DEFAULT 0 CHECK (audio_out >= 0),
  thoughts        integer NOT NULL DEFAULT 0 CHECK (thoughts >= 0),
  total_tokens    integer NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),   -- as reported, for checking the split
  searches        smallint NOT NULL DEFAULT 0 CHECK (searches >= 0),      -- priced per month, not in usd
  details_missing boolean NOT NULL DEFAULT false,          -- no modality details: counted as audio (details_missing)
  values_fixed    boolean NOT NULL DEFAULT false,          -- a value was not a number or negative, saved as 0 (usage_bad)
  seconds         numeric(10, 1) CHECK (seconds >= 0),     -- estimate row: the segment's length
  price_id        bigint REFERENCES call.live_prices (id) ON DELETE RESTRICT,
  usd             numeric(12, 6) CHECK (usd >= 0),         -- turn row without a matching price: NULL (unpriced)
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (segment_ref, seq),
  CHECK (kind <> 'turn' OR (seq >= 1 AND seconds IS NULL AND (price_id IS NULL) = (usd IS NULL))),
  CHECK (kind <> 'estimate' OR (seq = 0 AND seconds IS NOT NULL AND price_id IS NULL AND usd IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS live_usage_received_idx ON call.live_usage (received_at);
CREATE INDEX IF NOT EXISTS live_usage_call_idx ON call.live_usage (call_id) WHERE call_id IS NOT NULL;

-- TBL-113 live_counters (CTX-006) ← SPEC-169, SPEC-170, SPEC-174, SPEC-180 | terms: none
-- Counts the cost view shows per UTC month and entry point: usage dropped from a full queue, usage lost after the
-- last retry, and budget checks that could not count. Each process keeps them in memory and adds them on its next
-- successful write, so a count can arrive late; counts still in memory when a process stops are only in its log.
CREATE TABLE IF NOT EXISTS call.live_counters (
  month      date NOT NULL CHECK (extract(day FROM month) = 1),
  entrypoint text NOT NULL CHECK (entrypoint IN ('web', 'discord')),
  name       text NOT NULL CHECK (name IN ('usage_dropped', 'usage_lost', 'budget_unknown')),
  count      integer NOT NULL DEFAULT 0 CHECK (count >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (month, entrypoint, name)
);

-- Cost of each segment: its stored dollars, or, for a closed segment without usage or with a row that has no price,
-- its length times the per-minute estimate. An open segment counts only what is stored. Numbers only.
CREATE OR REPLACE VIEW call.segment_costs WITH (security_barrier=true) AS
SELECT s.id AS segment_id, s.call_id, c.entrypoint, s.tuning, s.state, s.opened_at, s.closed_at,
  greatest(0, extract(epoch FROM (COALESCE(s.closed_at, now()) - s.opened_at)))::double precision AS seconds,
  COALESCE(u.usage_rows, 0)::integer AS usage_rows,
  COALESCE(u.unpriced_rows, 0)::integer AS unpriced_rows,
  COALESCE(u.input_tokens, 0)::bigint AS input_tokens,
  COALESCE(u.audio_in_tokens, 0)::bigint AS audio_in_tokens,
  COALESCE(u.output_tokens, 0)::bigint AS output_tokens,
  COALESCE(u.searches, 0)::integer AS searches,
  e.estimated,
  (CASE WHEN e.estimated
        THEN round(greatest(0, extract(epoch FROM (s.closed_at - s.opened_at))) / 60 * p.usd_per_minute, 6)
        ELSE COALESCE(u.usd, 0) END)::numeric(12, 6) AS usd
FROM call.segments s
JOIN call.calls c ON c.id = s.call_id
LEFT JOIN LATERAL (
  SELECT count(*) AS usage_rows, count(*) FILTER (WHERE usd IS NULL) AS unpriced_rows,
    sum(text_in + audio_in + image_in + tool_in) AS input_tokens, sum(audio_in) AS audio_in_tokens,
    sum(text_out + audio_out + thoughts) AS output_tokens, sum(searches) AS searches, sum(usd) AS usd
  FROM call.live_usage WHERE segment_ref = s.id AND kind = 'turn'
) u ON true
CROSS JOIN LATERAL (
  SELECT s.state = 'closed' AND (COALESCE(u.usage_rows, 0) = 0 OR COALESCE(u.unpriced_rows, 0) > 0) AS estimated
) e
CROSS JOIN LATERAL (
  SELECT COALESCE((SELECT (value #>> '{}')::numeric FROM call.settings WHERE key = 'usd_per_minute'), 0.05)
    AS usd_per_minute
) p;

-- The spreadsheet's call session tab gains tokens, dollars (stored plus estimated), whether any part is an estimate,
-- and the tuning names. The earlier columns stay as they were.
CREATE OR REPLACE VIEW call.session_report WITH (security_barrier=true) AS
SELECT c.id,c.status,c.started_at,c.ended_at,c.organize_status,
  COALESCE(s.segment_count,0)::integer AS segment_count,
  COALESCE(s.session_seconds,0)::double precision AS session_seconds,
  COALESCE(t.fallback_count,0)::integer AS fallback_count,
  t.initial_transport,t.last_transport,t.last_reason,
  COALESCE(k.input_tokens,0)::bigint AS input_tokens,
  COALESCE(k.output_tokens,0)::bigint AS output_tokens,
  COALESCE(k.usd,0)::numeric(12,6) AS usd,
  COALESCE(k.estimated,false) AS usd_estimated,
  k.tunings
FROM call.calls c
LEFT JOIN LATERAL (
  SELECT count(*) AS segment_count,
    sum(greatest(0,extract(epoch FROM (COALESCE(closed_at,now())-opened_at)))) AS session_seconds
  FROM call.segments WHERE call_id=c.id
) s ON true
LEFT JOIN LATERAL (
  SELECT count(*) FILTER (WHERE mode='pcm' AND reason<>'start') AS fallback_count,
    (array_agg(mode ORDER BY created_at,mode DESC))[1] AS initial_transport,
    (array_agg(mode ORDER BY created_at DESC,mode))[1] AS last_transport,
    (array_agg(reason ORDER BY created_at DESC,mode))[1] AS last_reason
  FROM call.transport_events WHERE call_id=c.id
) t ON true
LEFT JOIN LATERAL (
  SELECT sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(usd) AS usd,
    bool_or(estimated) AS estimated, string_agg(DISTINCT tuning, ', ' ORDER BY tuning) AS tunings
  FROM call.segment_costs WHERE call_id=c.id
) k ON true
WHERE c.deleted_at IS NULL;

GRANT SELECT, INSERT ON call.live_prices, call.live_tunings, call.live_usage TO marong_call;
GRANT SELECT, INSERT, UPDATE ON call.live_counters TO marong_call;
GRANT SELECT ON call.segment_costs TO marong_call;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA call TO marong_call;
COMMIT;
