-- Schedules and reminders a friend asked Marong to keep in their private Discord DM.
-- The bot account may add and update rows but never delete them: cancelling only changes the status.
-- Reminders are delivered to the friend's own linked Discord DM, whatever the proactive opt-in says,
-- because the friend asked for each one.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

CREATE TABLE IF NOT EXISTS marong.schedules (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id         bigint NOT NULL REFERENCES marong.friends(id),
  room_key          text REFERENCES marong.rooms(room_key),          -- where it was asked (NULL: a call)
  source            text NOT NULL DEFAULT 'discord' CHECK (source IN ('discord', 'call')),
  source_message_id bigint REFERENCES marong.messages(id),
  title             text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 60),
  event_at          timestamptz,                                      -- when it happens (NULL: reminder only)
  all_day           boolean NOT NULL DEFAULT false,                   -- event_at is a date at 00:00 KST
  remind_at         timestamptz,                                      -- next DM (NULL: remember only)
  repeat            text NOT NULL DEFAULT 'none'
                    CHECK (repeat IN ('none', 'daily', 'weekdays', 'weekly', 'monthly')),
  repeat_anchor     timestamptz,                                      -- first reminder of a repeating one
  say               text CHECK (char_length(say) BETWEEN 1 AND 300),  -- what Marong says at remind_at
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done', 'canceled', 'missed')),
  sent_count        integer NOT NULL DEFAULT 0,
  last_sent_at      timestamptz,
  failures          smallint NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 3),
  claimed_until     timestamptz,                                      -- delivery lease after a crash
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (event_at IS NOT NULL OR remind_at IS NOT NULL OR status <> 'active'),
  CHECK (NOT all_day OR event_at IS NOT NULL),
  CHECK ((repeat = 'none') = (repeat_anchor IS NULL)),
  CHECK (repeat = 'none' OR event_at IS NULL)
);
CREATE INDEX IF NOT EXISTS schedules_due_idx ON marong.schedules (remind_at)
  WHERE status = 'active' AND remind_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS schedules_friend_idx ON marong.schedules (friend_id, status, id);

GRANT SELECT, INSERT, UPDATE ON marong.schedules TO marong;
COMMIT;
