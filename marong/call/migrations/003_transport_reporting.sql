-- Additive: apply as migration administrator after 002. No transcript access
-- is granted to the spreadsheet job, and a rollback need not drop this data.
BEGIN;
SET LOCAL ROLE marong_owner;
CREATE TABLE IF NOT EXISTS call.transport_events (
  call_id uuid NOT NULL REFERENCES call.calls(id) ON DELETE CASCADE,
  connection_id uuid NOT NULL,
  mode text NOT NULL CHECK (mode IN ('webrtc','pcm')),
  reason text NOT NULL CHECK (reason IN ('start','rtc_disconnected','rtc_reconnecting',
    'rtc_media_stalled','rtc_track_lost','rtc_no_media','control_reconnect',
    'network_change','server_pcm','rtc_server_lost')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (connection_id,mode)
);
CREATE INDEX IF NOT EXISTS transport_events_call_idx ON call.transport_events(call_id,created_at);
GRANT SELECT,INSERT,DELETE ON call.transport_events TO marong_call;

-- Metadata only. No caller/login IDs, transcripts, cards or memory text.
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
  SELECT count(*) FILTER (WHERE reason<>'start') AS fallback_count,
    (array_agg(mode ORDER BY created_at,mode DESC))[1] AS initial_transport,
    (array_agg(mode ORDER BY created_at DESC,mode))[1] AS last_transport,
    (array_agg(reason ORDER BY created_at DESC,mode))[1] AS last_reason
  FROM call.transport_events WHERE call_id=c.id
) t ON true
WHERE c.deleted_at IS NULL;
GRANT SELECT ON call.session_report TO marong;
COMMIT;
