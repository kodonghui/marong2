-- 010 Call connect speed and silent playback (BUG-108~110). Design: docs/04-functional-spec/call-connect.md
-- (SPEC-400, SPEC-404), docs/05-erd/call-connect.md (picture), docs/12-qa/call-connect.md (bugs).
-- Additive and safe to run twice. Apply after 001~009 as the migration administrator. The call server writes
-- with the call account (marong_call), which already has SELECT, INSERT, UPDATE on call.segments and INSERT
-- on call.transport_events.
-- Numbers and state names only: no transcript, name, address, token or device id reaches these columns (REQ-492).
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '30s';
SET LOCAL ROLE marong_owner;

-- segments (TBL-004) <- SPEC-400, SPEC-404: stage timings of one /live connection and the last playback report.
-- provider_ready_at keeps its column but its meaning is fixed by SPEC-400: the segment is inserted as 'opening'
-- without it and set to 'open' with clock_timestamp() on Gemini setupComplete (the 002 check already allows this).
ALTER TABLE call.segments
  ADD COLUMN IF NOT EXISTS connect_timing jsonb,
  ADD COLUMN IF NOT EXISTS playback jsonb;
ALTER TABLE call.segments DROP CONSTRAINT IF EXISTS segments_connect_timing_check;
ALTER TABLE call.segments ADD CONSTRAINT segments_connect_timing_check
  CHECK (connect_timing IS NULL OR (jsonb_typeof(connect_timing) = 'object' AND pg_column_size(connect_timing) <= 4096));
ALTER TABLE call.segments DROP CONSTRAINT IF EXISTS segments_playback_check;
ALTER TABLE call.segments ADD CONSTRAINT segments_playback_check
  CHECK (playback IS NULL OR (jsonb_typeof(playback) = 'object' AND pg_column_size(playback) <= 2048));

-- transport_events <- SPEC-404: a new fallback reason when WebRTC audio arrives but does not play.
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid = 'call.transport_events'::regclass AND contype = 'c'
    AND pg_get_constraintdef(oid) LIKE '%reason%'
  LOOP EXECUTE format('ALTER TABLE call.transport_events DROP CONSTRAINT %I', r.conname); END LOOP;
END $$;
ALTER TABLE call.transport_events ADD CONSTRAINT transport_events_reason_check
  CHECK (reason IN ('start', 'rtc_disconnected', 'rtc_reconnecting', 'rtc_media_stalled', 'rtc_track_lost',
                    'rtc_no_media', 'control_reconnect', 'network_change', 'server_pcm', 'rtc_server_lost',
                    'rtc_silent'));

RESET ROLE;
COMMIT;
