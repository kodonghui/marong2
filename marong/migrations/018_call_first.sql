-- 018 Calls first and picture topics (docs/04-functional-spec/call-first.md SPEC-283, CTX-020).
-- Two new tables and two columns on the app rings (TBL-102). Nobody gets DELETE. Safe to run twice.
-- The number leaves 016 and 017 to the diary (PR #25).
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- Changes to app_rings (defined as TBL-102 in 015) ← SPEC-266, SPEC-268, SPEC-270 | terms: TERM-080, TERM-081
-- A ring is a call promise (D19) or a hello call Marong places without one (D23). A hello ring has no schedule and
-- names its picture only when the friend takes picture topics (the call page shows it, SPEC-269).
ALTER TABLE marong.app_rings
  ADD COLUMN IF NOT EXISTS reason text NOT NULL DEFAULT 'promise' CHECK (reason IN ('promise', 'hello')),
  ADD COLUMN IF NOT EXISTS topic  text CHECK (topic ~ '^v[0-9]{1,3}/[a-z0-9-]{1,40}$');
ALTER TABLE marong.app_rings ALTER COLUMN schedule_id DROP NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_rings_reason_schedule') THEN
    -- A promise always has its schedule row; a hello call never has one.
    ALTER TABLE marong.app_rings ADD CONSTRAINT app_rings_reason_schedule
      CHECK ((reason = 'promise') = (schedule_id IS NOT NULL));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_rings_topic_hello') THEN
    ALTER TABLE marong.app_rings ADD CONSTRAINT app_rings_topic_hello CHECK (reason = 'hello' OR topic IS NULL);
  END IF;
END $$;
-- The last hello call of a friend (SPEC-265 ⑤) and the rings of the last six hours (⑥)
CREATE INDEX IF NOT EXISTS app_rings_friend_idx ON marong.app_rings (friend_id, created_at DESC);

-- TBL-125 topic_sends (CTX-020) ← SPEC-263, SPEC-264, SPEC-266, SPEC-270, SPEC-272, SPEC-273, SPEC-275 | terms: TERM-082, TERM-083, TERM-088
-- The topic a friend got on one Korean day: at most one a day (REQ-260), its picture (30 days apart, REQ-264), how it
-- went and whether the friend answered within three hours (REQ-291). Made before anything is sent, so a second turn
-- on the same day finds it and sends an ordinary proactive message instead.
CREATE TABLE IF NOT EXISTS marong.topic_sends (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id   bigint NOT NULL REFERENCES marong.friends(id),
  day         date NOT NULL,                                       -- the Korean date it went out
  picture     text NOT NULL CHECK (picture ~ '^v[0-9]{1,3}/[a-z0-9-]{1,40}$'),
  kind        text NOT NULL CHECK (kind IN ('text', 'call')),      -- a picture topic message or a hello call
  ring_id     uuid REFERENCES marong.app_rings(id),                -- the hello ring, also one that failed
  status      text NOT NULL DEFAULT 'sending' CHECK (status IN ('sending', 'sent', 'failed')),
  via         text CHECK (via IN ('app', 'discord')),              -- where the message went (a missed call's note too)
  sent_at     timestamptz NOT NULL DEFAULT now(),
  answer      text CHECK (answer IN ('answered', 'none')),         -- NULL: still open (three hours)
  answered_at timestamptz,
  CHECK (kind = 'text' OR ring_id IS NOT NULL),
  CHECK ((answer = 'answered') = (answered_at IS NOT NULL)),
  CHECK (answer IS NULL OR status = 'sent')
);
CREATE UNIQUE INDEX IF NOT EXISTS topic_sends_one_a_day ON marong.topic_sends (friend_id, day);
CREATE INDEX IF NOT EXISTS topic_sends_open_idx ON marong.topic_sends (sent_at) WHERE answer IS NULL AND status = 'sent';
CREATE INDEX IF NOT EXISTS topic_sends_ring_idx ON marong.topic_sends (ring_id) WHERE ring_id IS NOT NULL;

-- TBL-126 topic_prefs (CTX-020) ← SPEC-277, SPEC-278, SPEC-279 | terms: TERM-087, TERM-090
-- A friend's hello calls and picture topics. No row: both on, 19:00~21:30 (REQ-294). Changed by the friend's exact
-- phrases or by the admin command; only the latest value is kept, with who changed it.
CREATE TABLE IF NOT EXISTS marong.topic_prefs (
  friend_id   bigint PRIMARY KEY REFERENCES marong.friends(id),
  hello_call  boolean NOT NULL DEFAULT true,
  pictures    boolean NOT NULL DEFAULT true,
  call_from   smallint NOT NULL DEFAULT 1140 CHECK (call_from BETWEEN 0 AND 1439),   -- minutes after 00:00 KST
  call_until  smallint NOT NULL DEFAULT 1290 CHECK (call_until BETWEEN 1 AND 1440),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  updated_by  text NOT NULL DEFAULT 'friend' CHECK (updated_by IN ('friend', 'admin')),
  CHECK (call_from < call_until)
);

-- without a table: TERM-084 (the picture set is a folder in the repository), TERM-085, TERM-086 (worked out),
-- TERM-089 (worked out from messages and rings), TERM-091 (in the picture set)

GRANT SELECT, INSERT, UPDATE ON marong.topic_sends, marong.topic_prefs TO marong;
GRANT SELECT (reason, topic) ON marong.app_rings TO marong_call;
COMMIT;
