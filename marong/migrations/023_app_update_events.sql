-- 023 App update records (CTX-021): what the server sent to each phone, what each phone said about its update, when a
-- new version showed up on it, and when each friend fetched an APK.
-- (docs/04-functional-spec/app-update.md SPEC-430~438, docs/05-erd/app-update.md, decisions D122~D127, 2026-11-22.)
-- One new table (TBL-182). Nothing else changes.
-- Rules kept here:
--   * Additive only. No table or column is dropped or renamed, so the code of main 74d6451 keeps running on a
--     database that has this migration (the old code never reads the new table).
--   * Rows are only added. The bot account may read and add rows but never change or delete them, as in schema.sql.
--   * At most one update data message per phone, version and attempt (REQ-553): the watcher adds the pushed row
--     before it sends, and the unique index lets only one sender add it (SPEC-430).
--   * One installed row per phone and app version: installed is the only record of a finished install (SPEC-435).
--   * No FID, email, name, release note or chat text goes into this table. Release notes live in the release
--     folder's history.json (SPEC-437), not in the database.
-- Not applied anywhere yet (design PR). Safe to run twice. Apply after 014_app_chat.sql, as the migration
-- administrator, before the server code that writes it (SPEC-442).
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-182 app_update_events (CTX-021) ← SPEC-430, SPEC-434, SPEC-435, SPEC-438 | terms: TERM-223, TERM-219, TERM-220
-- kind:
--   pushed       the watcher claimed attempt `attempt` (1~3) of sending the update data message (TERM-219) for
--                version_code to this phone. It is added BEFORE the send (SPEC-430); a pushed row with no
--                push_failed row of the same attempt counts as sent, so a crash never causes a second send.
--   push_failed  that attempt failed; status is 410 (FCM no longer knows the phone), 401 (key) or 500 (other)
--   state        the phone reported its update state (TERM-220) for version_code through API-105 (SPEC-434);
--                status is set only for state = 'failed' (numbers in SPEC 8.5). A reported 'installed' adds no
--                state row: the installed kind below is the one record of an install.
--   installed    the phone's reported app_version went up (API-105); app_version is the new version and
--                version_code comes from the same report's update.versionCode, else from history.json when known
--   fetched      API-142 sent the whole APK of version_code to this friend; the request carries no install id
-- friend_id is the friend the phone belonged to when the row was added. app_devices.friend_id changes when the phone
-- logs in as another friend (app_store upsert), so the admin read shows a phone's rows only for its current friend
-- (SPEC-438).
CREATE TABLE IF NOT EXISTS marong.app_update_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('pushed', 'push_failed', 'state', 'installed', 'fetched')),
  friend_id    bigint NOT NULL REFERENCES marong.friends(id),
  install_id   uuid REFERENCES marong.app_devices(install_id),
  version_code integer CHECK (version_code BETWEEN 1 AND 2100000000),
  app_version  text CHECK (app_version ~ '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'),
  state        text CHECK (state IN ('downloaded', 'waiting_quiet', 'needs_confirm', 'failed')),
  status       smallint CHECK (status BETWEEN 1 AND 999),
  attempt      smallint CHECK (attempt BETWEEN 1 AND 3),
  at           timestamptz NOT NULL DEFAULT now(),
  -- Which columns each kind fills (SPEC-435). A row that does not fit its kind is refused. Every branch is built from
  -- IS [NOT] NULL tests or guards a comparison with IS NOT NULL, so no branch can be NULL (a NULL CHECK passes).
  CONSTRAINT app_update_events_fields_by_kind CHECK (CASE kind
    WHEN 'pushed' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                       AND state IS NULL AND status IS NULL AND attempt IS NOT NULL
    WHEN 'push_failed' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                            AND state IS NULL AND status IS NOT NULL AND status IN (401, 410, 500)
                            AND attempt IS NOT NULL
    WHEN 'state' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                      AND state IS NOT NULL AND (state = 'failed') = (status IS NOT NULL) AND attempt IS NULL
    WHEN 'installed' THEN install_id IS NOT NULL AND app_version IS NOT NULL AND state IS NULL AND status IS NULL
                          AND attempt IS NULL
    WHEN 'fetched' THEN install_id IS NULL AND version_code IS NOT NULL AND app_version IS NULL
                        AND state IS NULL AND status IS NULL AND attempt IS NULL
    ELSE false END)
);
-- REQ-553: the watcher's claim before each send, and one result per attempt (SPEC-430). INSERT ... ON CONFLICT DO
-- NOTHING on a pushed row returns no row when another pass or process already claimed that attempt: then it does not
-- send. The same index answers the watcher's choice (attempts and failures per phone and version).
CREATE UNIQUE INDEX IF NOT EXISTS app_update_events_push_attempt
  ON marong.app_update_events (install_id, version_code, attempt, kind) WHERE kind IN ('pushed', 'push_failed');
-- One installed row per phone and app version, even when the web page report and the app's own report both carry
-- the new version (SPEC-435). Android does not install a lower version over a higher one, so a version shows up once.
CREATE UNIQUE INDEX IF NOT EXISTS app_update_events_installed_once
  ON marong.app_update_events (install_id, app_version) WHERE kind = 'installed';
-- The admin read per phone, newest first (SPEC-438).
CREATE INDEX IF NOT EXISTS app_update_events_device_idx ON marong.app_update_events (install_id, at DESC);
-- The admin read of APK fetches per friend, newest first (SPEC-438). Only fetched rows are read by friend.
CREATE INDEX IF NOT EXISTS app_update_events_fetched_idx
  ON marong.app_update_events (friend_id, at DESC) WHERE kind = 'fetched';

GRANT SELECT, INSERT ON marong.app_update_events TO marong;
-- without a table: TERM-221 (release note) and TERM-222 (version history) live in the release folder's history.json
-- (SPEC-437); TERM-224 (update banner) is a screen state.
COMMIT;
