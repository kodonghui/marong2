-- The Discord service receives only DMs; account links are created by the owner.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

CREATE TABLE IF NOT EXISTS marong.discord_dm_links (
  discord_user_id text PRIMARY KEY CHECK (discord_user_id ~ '^[1-9][0-9]{16,19}$'),
  friend_id bigint NOT NULL UNIQUE REFERENCES marong.friends(id),
  room_key text NOT NULL UNIQUE REFERENCES marong.rooms(room_key),
  kakao_room_key text NOT NULL UNIQUE REFERENCES marong.rooms(room_key),
  user_key text NOT NULL UNIQUE REFERENCES marong.people(user_key),
  channel_id text CHECK (channel_id ~ '^[1-9][0-9]{16,19}$'),
  last_incoming_at timestamptz,
  opted_in_at timestamptz,
  proactive_moved_at timestamptz,
  per_day smallint NOT NULL CHECK (per_day BETWEEN 1 AND 48),
  start_hour smallint NOT NULL CHECK (start_hour BETWEEN 0 AND 23),
  end_hour smallint NOT NULL CHECK (end_hour > start_hour AND end_hour <= 24),
  last_slot timestamptz,
  last_attempt_at timestamptz,
  failures smallint NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 2),
  CHECK (room_key = 'discord-dm:' || discord_user_id AND user_key = 'discord-user:' || discord_user_id),
  CHECK ((channel_id IS NULL) = (last_incoming_at IS NULL)),
  CHECK (opted_in_at IS NULL OR channel_id IS NOT NULL)
);

GRANT SELECT ON marong.discord_dm_links TO marong;
GRANT UPDATE(channel_id, last_incoming_at, opted_in_at, proactive_moved_at, last_slot, last_attempt_at, failures)
  ON marong.discord_dm_links TO marong;
COMMIT;
