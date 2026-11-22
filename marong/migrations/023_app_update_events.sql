-- 023 App update records (CTX-021): what the server sent to each phone, what each phone said about its update, when a
-- new version showed up on it, and when each friend fetched an APK.
-- (docs/04-functional-spec/app-update.md SPEC-430~438, docs/05-erd/app-update.md, decisions D122~D127, 2026-11-22.)
-- One new table (TBL-182). Nothing else changes.
-- Rules kept here:
--   * Additive only. No table or column is dropped or renamed, so the code of main 74d6451 keeps running on a
--     database that has this migration (the old code never reads the new table).
--   * Rows are only added. The bot account may read and add rows but never change or delete them, as in schema.sql.
--   * One update data message per phone and version (REQ-553): a unique index on pushed rows.
--   * No FID, email, name, release note or chat text goes into this table. Release notes live in the release
--     folder's history.json (SPEC-437), not in the database.
-- Not applied anywhere yet (design PR). Safe to run twice. Apply after 014_app_chat.sql, as the migration
-- administrator, before the server code that writes it (SPEC-442).
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-182 app_update_events (CTX-021) ← SPEC-430, SPEC-434, SPEC-435, SPEC-438 | terms: TERM-223, TERM-219, TERM-220
-- kind:
--   pushed       the server sent the update data message (TERM-219) for version_code to this phone (SPEC-430)
--   push_failed  sending it failed; status is 410 (FCM no longer knows the phone), 401 (key) or 500 (other)
--   state        the phone reported its update state (TERM-220) for version_code through API-105 (SPEC-434);
--                status is set only for state = 'failed' (numbers in SPEC 8.5)
--   installed    the phone's reported app_version went up (API-105); app_version is the new version and
--                version_code is filled from history.json when known
--   fetched      API-142 sent the whole APK of version_code to this friend; the request carries no install id
CREATE TABLE IF NOT EXISTS marong.app_update_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('pushed', 'push_failed', 'state', 'installed', 'fetched')),
  friend_id    bigint NOT NULL REFERENCES marong.friends(id),
  install_id   uuid REFERENCES marong.app_devices(install_id),
  version_code integer CHECK (version_code BETWEEN 1 AND 2100000000),
  app_version  text CHECK (app_version ~ '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'),
  state        text CHECK (state IN ('downloaded', 'waiting_quiet', 'needs_confirm', 'failed', 'installed')),
  status       smallint CHECK (status BETWEEN 1 AND 999),
  at           timestamptz NOT NULL DEFAULT now(),
  -- Which columns each kind fills (SPEC-435). A row that does not fit its kind is refused.
  CONSTRAINT app_update_events_kind_check CHECK (CASE kind
    WHEN 'pushed' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                       AND state IS NULL AND status IS NULL
    WHEN 'push_failed' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                            AND state IS NULL AND status IN (401, 410, 500)
    WHEN 'state' THEN install_id IS NOT NULL AND version_code IS NOT NULL AND app_version IS NULL
                      AND state IS NOT NULL AND (state = 'failed') = (status IS NOT NULL)
    WHEN 'installed' THEN install_id IS NOT NULL AND app_version IS NOT NULL AND state IS NULL AND status IS NULL
    WHEN 'fetched' THEN install_id IS NULL AND version_code IS NOT NULL AND app_version IS NULL
                        AND state IS NULL AND status IS NULL
    ELSE false END)
);
-- REQ-553: one update data message per phone and version, also across bot restarts (SPEC-430).
CREATE UNIQUE INDEX IF NOT EXISTS app_update_events_pushed_once
  ON marong.app_update_events (install_id, version_code) WHERE kind = 'pushed';
-- The watcher's choice (failures per phone and version) and the admin read per phone, newest first (SPEC-438).
CREATE INDEX IF NOT EXISTS app_update_events_device_idx ON marong.app_update_events (install_id, at DESC);
-- The admin read of APK fetches per friend, newest first (SPEC-438).
CREATE INDEX IF NOT EXISTS app_update_events_friend_idx ON marong.app_update_events (friend_id, at DESC);

GRANT SELECT, INSERT ON marong.app_update_events TO marong;
-- without a table: TERM-221 (release note) and TERM-222 (version history) live in the release folder's history.json
-- (SPEC-437); TERM-224 (update banner) is a screen state.
COMMIT;
