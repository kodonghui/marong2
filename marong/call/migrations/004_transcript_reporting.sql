-- 2026-11-13: user requested saved call transcripts in the existing private
-- spreadsheet's conversation tab. Reporting only; no voice/bot runtime change.
BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='15s';
SET LOCAL ROLE marong_owner;
CREATE OR REPLACE VIEW call.transcript_report WITH (security_barrier=true) AS
SELECT t.id,t.call_id,t.seq,t.role,t.content,t.started_at,t.ended_at,
       t.finalized,t.interrupted,
       CASE WHEN t.turn_key LIKE 'text:%' THEN 'text' ELSE 'audio' END AS input_kind,
       f.name AS caller_name,s.provider_model
FROM call.turns t
JOIN call.calls c ON c.id=t.call_id
JOIN call.callers caller ON caller.id=c.caller_id
JOIN marong.friends f ON f.id=caller.friend_id
JOIN call.segments s ON s.id=t.segment_id AND s.call_id=c.id
WHERE c.deleted_at IS NULL AND t.forgotten_at IS NULL AND btrim(t.content)<>'';
GRANT SELECT ON call.transcript_report TO marong;
COMMIT;
