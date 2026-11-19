-- 020 Unified app (MVP): sign-up by invite link, device sessions, one 마롱이 per friend (name, pet character,
-- call voice), friend requests and daily usage.
-- (docs/04-functional-spec/unified.md SPEC-370~396, CTX-026~029, decisions D90~D104.)
-- Nine new tables (TBL-164~172) and new columns on rooms and friendships.
-- Rules kept here:
--   * Additive only. No table or column is dropped or renamed, so the code of main 0953b86 keeps running on a
--     database that has this migration (the old code never reads the new tables or columns).
--   * Invite tokens, session tokens and device codes are stored as hashes only (REQ-435). A device code has six
--     digits, so its hash is an HMAC with a server secret, never a bare SHA-256.
--   * Nobody gets DELETE on marong tables, as in schema.sql. Ended rows keep a timestamp (used_at, revoked_at,
--     retired_at, removed_at) or a state instead.
--   * discord_dm_links stays as it is. The backfill below only copies from it; new code does not read it (REQ-454).
--   * Existing rooms keep their keys and rows. Messages, summaries, notes and embeddings are not copied (REQ-453).
-- Safe to run twice. Apply after schema.sql, the call schema and 010~019, as the migration administrator.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-164 invites (CTX-026) ← SPEC-370, SPEC-373, SPEC-395 | terms: TERM-173
-- One row per invite link the owner makes. The link holds the token; the row holds its SHA-256.
--   join    : a new person signs up (friend_id is NULL until used, then used_by is the new friend).
--   link    : ties an existing friend row to a device (the owner picks friend_id when making it). No email match.
--   relogin : a new device login for someone whose sessions ended.
CREATE TABLE IF NOT EXISTS marong.invites (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
  kind       text NOT NULL CHECK (kind IN ('join', 'link', 'relogin')),
  friend_id  bigint REFERENCES marong.friends (id),
  note       text NOT NULL DEFAULT '' CHECK (char_length(note) <= 40),   -- the owner's own memo, shown only in admin
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,                                       -- created_at + 7 days (SPEC-370)
  used_at    timestamptz,
  used_by    bigint REFERENCES marong.friends (id),
  revoked_at timestamptz,
  CHECK ((kind = 'join') = (friend_id IS NULL)),
  CHECK ((used_at IS NULL) = (used_by IS NULL)),
  CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS invites_open_idx ON marong.invites (expires_at) WHERE used_at IS NULL AND revoked_at IS NULL;

-- TBL-165 app_sessions (CTX-026) ← SPEC-371, SPEC-372, SPEC-374, SPEC-395 | terms: TERM-174
-- A device login. The cookie holds the token; the row holds its SHA-256. The app server and the call server both
-- read it (REQ-436). method is how the session began; a later sign-in method only adds a value here.
CREATE TABLE IF NOT EXISTS marong.app_sessions (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  token_hash   bytea NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
  method       text NOT NULL CHECK (method IN ('invite', 'code')),
  label        text NOT NULL DEFAULT '' CHECK (char_length(label) <= 40),  -- 'Android 앱', 'iPhone Safari' and the like
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,                                       -- last_seen_at + 90 days (SPEC-371)
  revoked_at   timestamptz
);
CREATE INDEX IF NOT EXISTS app_sessions_friend_idx ON marong.app_sessions (friend_id) WHERE revoked_at IS NULL;

-- TBL-166 device_codes (CTX-026) ← SPEC-372 | terms: TERM-175
-- A six-digit code a signed-in device makes so another device can sign in. Ten minutes, one use.
CREATE TABLE IF NOT EXISTS marong.device_codes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  code_hash  bytea NOT NULL CHECK (octet_length(code_hash) = 32),          -- HMAC-SHA-256 with the server secret
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_at    timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS device_codes_live_idx ON marong.device_codes (code_hash) WHERE used_at IS NULL;

-- TBL-169 characters (CTX-027) ← SPEC-378, SPEC-379, SPEC-380 | terms: TERM-179, TERM-185
-- A pet character a friend made from photos. stage is where the making stands; status says whether it can be worn.
-- At most three rows with status draft or ready per friend: the app counts under the friend lock (REQ-446).
CREATE TABLE IF NOT EXISTS marong.characters (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  kind       text NOT NULL CHECK (kind IN ('dog', 'cat')),
  template   text CHECK (template IN ('dog_small', 'dog_large', 'dog_long', 'cat', 'cat_round')),
  name       text CHECK (char_length(name) BETWEEN 1 AND 12),
  traits     jsonb,                                  -- the trait sheet: what the model read while stage is
                                                     -- 'traits', the sheet the friend confirmed after that (SPEC-378)
  tone       text NOT NULL DEFAULT '' CHECK (char_length(tone) <= 60),    -- one line on how it talks
  stage      text NOT NULL DEFAULT 'photos'
             CHECK (stage IN ('photos', 'traits', 'preview', 'candidates', 'sheet', 'name', 'done')),
  status     text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'retired')),
  regen_left smallint NOT NULL DEFAULT 2 CHECK (regen_left BETWEEN 0 AND 2),  -- candidate regenerations left
  created_at timestamptz NOT NULL DEFAULT now(),
  ready_at   timestamptz,
  retired_at timestamptz,
  CHECK (((status = 'ready') = (stage = 'done' AND ready_at IS NOT NULL)) OR status = 'retired'),
  CHECK (status <> 'ready' OR (name IS NOT NULL AND template IS NOT NULL AND traits IS NOT NULL)),
  CHECK ((status = 'retired') = (retired_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS characters_friend_idx ON marong.characters (friend_id) WHERE status <> 'retired';

-- TBL-170 character_images (CTX-027) ← SPEC-378, SPEC-379 | terms: TERM-179
-- Files of a character under the character folder. photo_* rows are the processed photos (faces of people masked,
-- no metadata); the app removes those files and stamps removed_at once the expression sheet is done.
CREATE TABLE IF NOT EXISTS marong.character_images (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  character_id bigint NOT NULL REFERENCES marong.characters (id),
  slot         text NOT NULL CHECK (slot IN ('photo_1', 'photo_2', 'photo_3', 'preview',
                                             'candidate_1', 'candidate_2', 'candidate_3', 'candidate_4',
                                             'front', 'smile', 'excited', 'sleepy', 'surprised', 'sad', 'pout')),
  path         text NOT NULL,                                             -- relative to MARONG_CHARACTER_DIR
  width        integer NOT NULL CHECK (width > 0),
  height       integer NOT NULL CHECK (height > 0),
  bytes        integer NOT NULL CHECK (bytes > 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  removed_at   timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS character_images_live_idx ON marong.character_images (character_id, slot)
  WHERE removed_at IS NULL;

-- TBL-171 character_jobs (CTX-027) ← SPEC-378, SPEC-380 | terms: TERM-185
-- One model step of a making. error holds a code only. cost_usd sums into the monthly image budget (SPEC-380).
CREATE TABLE IF NOT EXISTS marong.character_jobs (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  character_id bigint NOT NULL REFERENCES marong.characters (id),
  step         text NOT NULL CHECK (step IN ('traits', 'preview', 'candidates', 'sheet')),
  state        text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed')),
  attempts     smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
  error        text CHECK (error IN ('model_error', 'model_refused', 'timeout', 'check_failed', 'budget')),
  cost_usd     numeric(8, 4) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  started_at   timestamptz,
  finished_at  timestamptz,
  CHECK ((state IN ('done', 'failed')) = (finished_at IS NOT NULL)),
  CHECK ((state = 'failed') = (error IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS character_jobs_open_idx ON marong.character_jobs (character_id)
  WHERE state IN ('queued', 'running');
-- The monthly image budget sums cost_usd of every finished job, failed ones included (SPEC-380).
CREATE INDEX IF NOT EXISTS character_jobs_month_idx ON marong.character_jobs (finished_at) WHERE finished_at IS NOT NULL;

-- TBL-167 friend_profiles (CTX-027, CTX-028, CTX-029) ← SPEC-373, SPEC-377, SPEC-379, SPEC-381, SPEC-385, SPEC-394
--   | terms: TERM-177, TERM-178, TERM-183, TERM-187, TERM-192
-- One row per friend who signed in through an invite link: the name of their 마롱이, the character it wears
-- (NULL = the default 마롱이), the call voice (NULL = the default voice), the friend code and the ticket balance.
-- The app makes the row at sign-up or link (SPEC-373); friends without a row get the defaults.
CREATE TABLE IF NOT EXISTS marong.friend_profiles (
  friend_id    bigint PRIMARY KEY REFERENCES marong.friends (id),
  bot_name     text NOT NULL DEFAULT '마롱이' CHECK (char_length(bot_name) BETWEEN 1 AND 12),
  character_id bigint REFERENCES marong.characters (id),
  voice        text CHECK (voice ~ '^[A-Za-z]{2,24}$'),                   -- a name from MARONG_CALL_VOICES
  friend_code  text NOT NULL UNIQUE CHECK (friend_code ~ '^[A-HJ-NP-Z2-9]{6}$'),
  tickets      integer NOT NULL DEFAULT 0 CHECK (tickets >= 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- TBL-168 contact_settings (CTX-001) ← SPEC-373, SPEC-383 | terms: TERM-193
-- Proactive settings and state per friend, the columns discord_dm_links carried, without any transport id.
CREATE TABLE IF NOT EXISTS marong.contact_settings (
  friend_id          bigint PRIMARY KEY REFERENCES marong.friends (id),
  opted_in_at        timestamptz,
  proactive_moved_at timestamptz,
  per_day            smallint NOT NULL CHECK (per_day BETWEEN 1 AND 48),
  start_hour         smallint NOT NULL CHECK (start_hour BETWEEN 0 AND 23),
  end_hour           smallint NOT NULL CHECK (end_hour > start_hour AND end_hour <= 24),
  last_incoming_at   timestamptz,
  last_slot          timestamptz,
  last_attempt_at    timestamptz,
  failures           smallint NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 2),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- TBL-172 usage_daily (CTX-029) ← SPEC-394, SPEC-390 | terms: TERM-190, TERM-191
-- What a friend used on one usage day (the day turns at 04:00 Korean time). Counts only, no text.
CREATE TABLE IF NOT EXISTS marong.usage_daily (
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  day          date NOT NULL,
  chat_turns   integer NOT NULL DEFAULT 0 CHECK (chat_turns >= 0),
  call_seconds integer NOT NULL DEFAULT 0 CHECK (call_seconds >= 0),
  images       integer NOT NULL DEFAULT 0 CHECK (images >= 0),
  searches     integer NOT NULL DEFAULT 0 CHECK (searches >= 0),
  shop_reads   integer NOT NULL DEFAULT 0 CHECK (shop_reads >= 0),
  units        integer NOT NULL DEFAULT 0 CHECK (units >= 0),
  tickets_used integer NOT NULL DEFAULT 0 CHECK (tickets_used >= 0),
  PRIMARY KEY (friend_id, day)
);

-- rooms: the owner of a 1:1 room (REQ-452). Group and channel rooms keep NULL.
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS owner_friend_id bigint REFERENCES marong.friends (id);
CREATE INDEX IF NOT EXISTS rooms_owner_idx ON marong.rooms (owner_friend_id) WHERE owner_friend_id IS NOT NULL;

-- friendships: request and accept (SPEC-381). Rows made before this migration are accepted.
-- close stays the value the readers use; it is true only while both sides turned it on (REQ-457).
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'accepted'
  CHECK (state IN ('pending', 'accepted', 'declined', 'ended'));
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS requested_by bigint REFERENCES marong.friends (id);
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS responded_at timestamptz;
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS close_a boolean NOT NULL DEFAULT false;  -- friend_a's wish
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS close_b boolean NOT NULL DEFAULT false;  -- friend_b's wish
-- A request names who sent it, and the sender is one of the two. Rows made before this migration have no sender.
ALTER TABLE marong.friendships DROP CONSTRAINT IF EXISTS friendships_request_check;
ALTER TABLE marong.friendships ADD CONSTRAINT friendships_request_check
  CHECK ((state <> 'pending' OR requested_by IS NOT NULL)
         AND (requested_by IS NULL OR requested_by IN (friend_a, friend_b)));

-- Backfill 1: owners of the 1:1 rooms the two linked accounts already have (their Discord DM room and the Kakao
-- 1:1 room that holds their older history). Rows are only stamped, never copied.
UPDATE marong.rooms r SET owner_friend_id = l.friend_id
  FROM marong.discord_dm_links l
 WHERE r.owner_friend_id IS NULL AND r.room_key IN (l.room_key, l.kakao_room_key);

-- Backfill 2: proactive settings and state of the linked accounts. It copies once and never overwrites. The bot
-- keeps writing discord_dm_links until the loops move to the app server, so the rollout copies these columns
-- once more right before that switch (docs/10-wbs/unified.md, TASK-384).
INSERT INTO marong.contact_settings (friend_id, opted_in_at, proactive_moved_at, per_day, start_hour, end_hour,
                                     last_incoming_at, last_slot, last_attempt_at, failures)
SELECT friend_id, opted_in_at, proactive_moved_at, per_day, start_hour, end_hour,
       last_incoming_at, last_slot, last_attempt_at, failures
  FROM marong.discord_dm_links
ON CONFLICT (friend_id) DO NOTHING;

-- Backfill 3: relations the owner set as close stay close for both sides.
UPDATE marong.friendships SET close_a = true, close_b = true WHERE close AND NOT (close_a AND close_b);

-- The app server (role marong) reads and writes all of it.
GRANT SELECT, INSERT, UPDATE ON marong.invites, marong.app_sessions, marong.device_codes, marong.characters,
  marong.character_images, marong.character_jobs, marong.friend_profiles, marong.contact_settings,
  marong.usage_daily TO marong;

-- The call server: checks the same login (SPEC-374), reads the name, character and voice for a call (SPEC-377,
-- SPEC-385) and adds call seconds (SPEC-394). It may slide a session's expiry but never makes or ends one.
-- When a daily limit is on, the call's units over the limit come off the ticket balance in the same transaction
-- as the usage row, so the call server may change tickets (and updated_at) but no other profile column.
GRANT SELECT ON marong.app_sessions, marong.friend_profiles, marong.characters, marong.character_images
  TO marong_call;
GRANT UPDATE (last_seen_at, expires_at) ON marong.app_sessions TO marong_call;
GRANT SELECT, INSERT, UPDATE ON marong.usage_daily TO marong_call;
GRANT UPDATE (tickets, updated_at) ON marong.friend_profiles TO marong_call;

RESET ROLE;
COMMIT;
