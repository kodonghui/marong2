-- TBL-003 (CTX-002), SPEC-548 and SPEC-550. Draft for review.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

ALTER TABLE call.calls
    ADD COLUMN IF NOT EXISTS notice_receipt_expires_at timestamptz;

COMMENT ON COLUMN call.calls.notice_receipt_expires_at IS
    'Fixed expiry for the read-only notification receipt, set at the first web notification acceptance.';

COMMIT;
