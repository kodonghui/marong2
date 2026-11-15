BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='15s';
SET LOCAL ROLE marong_owner;

ALTER TABLE call.calls ADD COLUMN IF NOT EXISTS entrypoint text NOT NULL DEFAULT 'web';
ALTER TABLE call.calls DROP CONSTRAINT IF EXISTS calls_entrypoint_check;
ALTER TABLE call.calls ADD CONSTRAINT calls_entrypoint_check CHECK (entrypoint IN ('web','discord'));

ALTER TABLE call.transport_events DROP CONSTRAINT IF EXISTS transport_events_mode_check;
ALTER TABLE call.transport_events ADD CONSTRAINT transport_events_mode_check
  CHECK (mode IN ('webrtc','pcm','discord'));

-- Pilot callers are Discord-only. If the same person later gets a web
-- login, establish cross-transport session ownership before enabling both.
CREATE OR REPLACE VIEW call.discord_voice_bindings WITH (security_barrier=true) AS
SELECT d.discord_user_id,d.friend_id,c.id AS caller_id,f.name,c.context_revision,d.room_key,d.kakao_room_key
FROM marong.discord_dm_links d
JOIN call.callers c ON c.friend_id=d.friend_id
JOIN marong.friends f ON f.id=d.friend_id
JOIN marong.people p ON p.user_key=d.user_key AND p.friend_id=d.friend_id
JOIN call.kakao_guards g ON g.room_key=d.room_key AND g.friend_id=d.friend_id
WHERE c.enabled AND d.channel_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM call.caller_logins l WHERE l.caller_id=c.id);
GRANT SELECT ON call.discord_voice_bindings TO marong_call;

CREATE OR REPLACE VIEW call.session_report WITH (security_barrier=true) AS
SELECT c.id,c.status,c.started_at,c.ended_at,c.organize_status,
  COALESCE(s.segment_count,0)::integer AS segment_count,
  COALESCE(s.session_seconds,0)::double precision AS session_seconds,
  COALESCE(t.fallback_count,0)::integer AS fallback_count,
  t.initial_transport,t.last_transport,t.last_reason
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
WHERE c.deleted_at IS NULL;

CREATE OR REPLACE VIEW call.transcript_report WITH (security_barrier=true) AS
SELECT t.id,t.call_id,t.seq,t.role,t.content,t.started_at,t.ended_at,
       t.finalized,t.interrupted,
       CASE WHEN t.turn_key LIKE 'text:%' THEN 'text' ELSE 'audio' END AS input_kind,
       f.name AS caller_name,s.provider_model,c.entrypoint
FROM call.turns t
JOIN call.calls c ON c.id=t.call_id
JOIN call.callers caller ON caller.id=c.caller_id
JOIN marong.friends f ON f.id=caller.friend_id
JOIN call.segments s ON s.id=t.segment_id AND s.call_id=c.id
WHERE c.deleted_at IS NULL AND t.forgotten_at IS NULL AND btrim(t.content)<>'';
COMMIT;
