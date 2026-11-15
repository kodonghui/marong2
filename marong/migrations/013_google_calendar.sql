-- Google Calendar links a friend made themselves from their Discord DM ('구글 캘린더 연결').
-- Marong reads the friend's primary calendar (calendar.events.readonly) and writes only to a '마롱이' calendar it
-- created in their account (calendar.app.created). The refresh token is useless without the OAuth client secret,
-- which stays in a root-only systemd credential, never in this database.
-- The bot account may add and update rows but never delete them: disconnecting clears the token and the status.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

CREATE TABLE IF NOT EXISTS marong.google_links (
  friend_id     bigint PRIMARY KEY REFERENCES marong.friends(id),
  status        text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'broken', 'disconnected')),
  refresh_token text,                                   -- NULL unless connected
  can_read      boolean NOT NULL DEFAULT false,         -- the friend granted calendar.events.readonly
  can_write     boolean NOT NULL DEFAULT false,         -- the friend granted calendar.app.created
  calendar_id   text,                                   -- the '마롱이' calendar Marong created (NULL: not yet)
  connected_at  timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'connected') = (refresh_token IS NOT NULL)),
  CHECK (status <> 'connected' OR can_read OR can_write)
);

-- Dated schedules go to the friend's '마롱이' calendar; cancelling one removes it there.
-- none: not there yet | done: there | removed: taken out after cancelling | failed: gave up after 3 tries
ALTER TABLE marong.schedules
  ADD COLUMN IF NOT EXISTS google_event_id text,
  ADD COLUMN IF NOT EXISTS google_sync text NOT NULL DEFAULT 'none'
    CHECK (google_sync IN ('none', 'done', 'removed', 'failed')),
  ADD COLUMN IF NOT EXISTS google_failures smallint NOT NULL DEFAULT 0 CHECK (google_failures BETWEEN 0 AND 3);

GRANT SELECT, INSERT, UPDATE ON marong.google_links TO marong;
COMMIT;
