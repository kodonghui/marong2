-- 008 Unified app (MVP): the app server makes a caller row at sign-up, and calls run one per friend.
-- (docs/04-functional-spec/unified.md SPEC-373, SPEC-386; marong/migrations/020_unified.sql.)
-- No table changes. call.caller_logins stays but the login no longer reads it (REQ-436): a call is allowed for
-- the friend of a live marong.app_sessions row whose call.callers row is enabled.
-- Safe to run twice. Apply after the call schema, 001~007 and marong migration 020.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- SPEC-373: sign-up makes friends, friend_profiles, contact_settings, the room, people and this row in one
-- transaction, so the app server's role needs to insert here. It never updates or disables a caller.
GRANT USAGE ON SCHEMA call TO marong;
GRANT SELECT, INSERT ON call.callers TO marong;
RESET ROLE;
COMMIT;
