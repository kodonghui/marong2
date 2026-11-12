-- Apply after marong/call/schema.sql, as the migration administrator.
-- Additive Gemini adapter, durable operations, and private Kakao provenance.
BEGIN;
SET LOCAL ROLE marong_owner;
ALTER TABLE call.callers ADD COLUMN IF NOT EXISTS context_revision bigint NOT NULL DEFAULT 0;
ALTER TABLE call.calls ADD COLUMN IF NOT EXISTS next_seq integer NOT NULL DEFAULT 0;
ALTER TABLE call.calls ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE call.segments ADD COLUMN IF NOT EXISTS provider text NOT NULL DEFAULT 'openai';
ALTER TABLE call.segments ADD COLUMN IF NOT EXISTS provider_model text;
ALTER TABLE call.segments ADD COLUMN IF NOT EXISTS provider_session_id text;
ALTER TABLE call.segments ADD COLUMN IF NOT EXISTS provider_ready_at timestamptz;
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid='call.segments'::regclass
    AND contype='c' AND pg_get_constraintdef(oid) LIKE '%openai_session_id%'
  LOOP EXECUTE format('ALTER TABLE call.segments DROP CONSTRAINT %I',r.conname); END LOOP;
END $$;
ALTER TABLE call.segments ADD CONSTRAINT segments_provider_ready_check
  CHECK (state <> 'open' OR openai_session_id IS NOT NULL OR provider_ready_at IS NOT NULL);
ALTER TABLE call.turns ADD COLUMN IF NOT EXISTS turn_key text;
ALTER TABLE call.turns ADD COLUMN IF NOT EXISTS finalized boolean NOT NULL DEFAULT true;
ALTER TABLE call.turns ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;
ALTER TABLE call.turns ADD COLUMN IF NOT EXISTS interrupted boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS turns_key_idx ON call.turns(call_id,turn_key);
ALTER TABLE call.delegations ADD COLUMN IF NOT EXISTS provider_call_id text;
ALTER TABLE call.delegations ADD COLUMN IF NOT EXISTS request_key text;
ALTER TABLE call.delegations ADD COLUMN IF NOT EXISTS result_data jsonb NOT NULL DEFAULT '{}';
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT conname FROM pg_constraint WHERE conrelid='call.delegations'::regclass
    AND contype='c' AND pg_get_constraintdef(oid) LIKE '%openai_delegation_id%'
  LOOP EXECUTE format('ALTER TABLE call.delegations DROP CONSTRAINT %I',r.conname); END LOOP;
END $$;
ALTER TABLE call.delegations ADD CONSTRAINT delegations_provider_id_check
  CHECK (origin <> 'model' OR openai_delegation_id IS NOT NULL OR provider_call_id IS NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS delegations_request_idx ON call.delegations(call_id,request_key);
CREATE TABLE IF NOT EXISTS call.deletions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caller_id bigint NOT NULL REFERENCES call.callers(id) ON DELETE CASCADE,
  call_ref uuid,
  reason text NOT NULL CHECK(reason IN ('forget','delete_call','retention')),
  source_ids jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS call.source_exclusions (
  caller_id bigint NOT NULL REFERENCES call.callers(id) ON DELETE CASCADE,
  source_type text NOT NULL,
  source_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(caller_id,source_type,source_id)
);
-- Once voice memory enters a Kakao room, its later material is private. Sharing
-- uses the last pre-bridge notes. This survives call deletion and app rollback.
CREATE TABLE IF NOT EXISTS call.kakao_guards (
  room_key text PRIMARY KEY REFERENCES marong.rooms(room_key) ON DELETE RESTRICT,
  friend_id bigint NOT NULL REFERENCES marong.friends(id) ON DELETE RESTRICT,
  message_floor bigint NOT NULL,
  note_floor bigint NOT NULL,
  summary_floor bigint NOT NULL,
  message_forgotten_through bigint NOT NULL DEFAULT 0,
  note_forgotten_through bigint NOT NULL DEFAULT 0,
  summary_forgotten_through bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION call.kakao_private(kind text, source_id bigint, room text)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT source_id > CASE kind WHEN 'message' THEN message_floor
   WHEN 'note' THEN note_floor WHEN 'summary' THEN summary_floor ELSE 9223372036854775807 END
   FROM call.kakao_guards WHERE room_key=room),false)
$$;
CREATE OR REPLACE FUNCTION call.kakao_hidden(kind text, source_id bigint, room text)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT source_id > CASE kind WHEN 'message' THEN message_floor WHEN 'note' THEN note_floor ELSE summary_floor END
   AND source_id <= CASE kind WHEN 'message' THEN message_forgotten_through WHEN 'note' THEN note_forgotten_through ELSE summary_forgotten_through END
   FROM call.kakao_guards WHERE room_key=room),false)
   OR (kind='message' AND EXISTS(
     SELECT 1 FROM marong.messages m JOIN call.kakao_guards g ON g.room_key=m.room_key
     JOIN call.callers c ON c.friend_id=g.friend_id WHERE m.id=source_id
     AND (m.meta#>>'{memory,call_revision}') ~ '^[0-9]+$'
     AND (m.meta#>>'{memory,call_revision}')::bigint<c.context_revision))
$$;
REVOKE ALL ON FUNCTION call.kakao_private(text,bigint,text),call.kakao_hidden(text,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION call.kakao_private(text,bigint,text),call.kakao_hidden(text,bigint,text) TO marong,marong_call;
GRANT SELECT,INSERT,UPDATE,DELETE ON call.deletions,call.source_exclusions,call.kakao_guards TO marong_call;
GRANT SELECT,INSERT ON call.kakao_guards TO marong;
GRANT SELECT ON call.source_exclusions TO marong;
GRANT SELECT(context_revision) ON call.callers TO marong;
GRANT SELECT(deleted_at) ON call.calls TO marong;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA call TO marong_call;
UPDATE call.settings SET value='"Sulafat"'::jsonb WHERE key='voice';
UPDATE call.meta SET value='2' WHERE key='schema_version';
COMMIT;
