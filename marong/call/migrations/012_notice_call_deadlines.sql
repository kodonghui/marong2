-- TBL-003 (CTX-002), SPEC-546 and SPEC-550. Draft for review.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

ALTER TABLE call.calls
    ADD COLUMN IF NOT EXISTS notice_first_connected_at timestamptz,
    ADD COLUMN IF NOT EXISTS notice_connection_deadline_at timestamptz;

COMMENT ON COLUMN call.calls.notice_first_connected_at IS
    'First successful server connection for a tracked notification call.';
COMMENT ON COLUMN call.calls.notice_connection_deadline_at IS
    'Current deadline for first connection or confirmed disconnection recovery, updated only on lifecycle transitions.';

COMMIT;
