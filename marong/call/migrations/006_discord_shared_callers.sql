BEGIN;
SET LOCAL lock_timeout='2s';
SET LOCAL statement_timeout='15s';
SET LOCAL ROLE marong_owner;

-- The relay independently requires the configured Discord user, guild and channel.
-- A person can use both entry points now that call ownership is checked at start.
CREATE OR REPLACE VIEW call.discord_voice_bindings WITH (security_barrier=true) AS
SELECT d.discord_user_id,d.friend_id,c.id AS caller_id,f.name,c.context_revision,d.room_key,d.kakao_room_key
FROM marong.discord_dm_links d
JOIN call.callers c ON c.friend_id=d.friend_id
JOIN marong.friends f ON f.id=d.friend_id
JOIN marong.people p ON p.user_key=d.user_key AND p.friend_id=d.friend_id
JOIN call.kakao_guards g ON g.room_key=d.room_key AND g.friend_id=d.friend_id
WHERE c.enabled AND d.channel_id IS NOT NULL;

COMMIT;
