-- TBL-102 app_rings ← SPEC-130, SPEC-136, SPEC-138 (docs/app-ring.md) | One call Marong places at a time a friend set.
-- Answered and missed are decided here. Nobody gets DELETE.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- Call promises ← SPEC-128. The schedule tool checks the time (a promise with an event keeps its row after the call).
ALTER TABLE marong.schedules
  ADD COLUMN IF NOT EXISTS action text NOT NULL DEFAULT 'remind' CHECK (action IN ('remind', 'call'));

CREATE TABLE IF NOT EXISTS marong.app_rings (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_id  bigint NOT NULL REFERENCES marong.schedules(id),
  friend_id    bigint NOT NULL REFERENCES marong.friends(id),
  caller_id    bigint NOT NULL REFERENCES call.callers(id),
  via          text NOT NULL CHECK (via IN ('app', 'discord')),
  status       text NOT NULL DEFAULT 'ringing'
               CHECK (status IN ('ringing', 'answered', 'missed', 'busy', 'skipped', 'failed')),
  title        text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 60),  -- copied from the schedule (the call server reads it)
  say          text CHECK (char_length(say) BETWEEN 1 AND 300),
  devices      smallint NOT NULL DEFAULT 0 CHECK (devices BETWEEN 0 AND 20),  -- devices FCM accepted
  created_at   timestamptz NOT NULL DEFAULT now(),
  answer_until timestamptz NOT NULL,                                        -- a call started by then is this call
  answered_at  timestamptz,
  call_id      uuid REFERENCES call.calls(id),
  resolved_at  timestamptz,                                                 -- when it became missed or skipped
  CHECK ((status = 'answered') = (call_id IS NOT NULL)),
  CHECK ((status = 'answered') = (answered_at IS NOT NULL))
);
-- One ringing call per friend (REQ-132)
CREATE UNIQUE INDEX IF NOT EXISTS app_rings_one_ringing ON marong.app_rings (friend_id) WHERE status = 'ringing';
CREATE INDEX IF NOT EXISTS app_rings_due_idx ON marong.app_rings (answer_until) WHERE status = 'ringing';
CREATE INDEX IF NOT EXISTS app_rings_caller_idx ON marong.app_rings (caller_id, created_at DESC);

-- Devices that can ring ← SPEC-129, SPEC-139. NULL: an app without the ring report
ALTER TABLE marong.app_devices
  ADD COLUMN IF NOT EXISTS ring_channel text CHECK (ring_channel IN ('enabled', 'disabled')),
  ADD COLUMN IF NOT EXISTS full_screen  text CHECK (full_screen IN ('granted', 'denied'));

GRANT SELECT, INSERT, UPDATE ON marong.app_rings TO marong;
GRANT SELECT (id, caller_id, status, title, say, created_at, answer_until, call_id) ON marong.app_rings TO marong_call;
GRANT UPDATE (status, answered_at, call_id) ON marong.app_rings TO marong_call;
COMMIT;
