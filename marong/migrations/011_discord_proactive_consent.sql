-- Record recipient consent before their DM opens. Scheduling still requires
-- a verified channel and timestamped incoming message.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;
ALTER TABLE marong.discord_dm_links DROP CONSTRAINT IF EXISTS discord_dm_links_check3;
COMMIT;
