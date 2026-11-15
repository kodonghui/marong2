-- TBL-101 app_devices ← SPEC-115, SPEC-116, SPEC-117 (docs/app-chat.md) | Phones with the Marong Android app.
-- A device can receive app notifications when it has an FID, notifications are granted and it reported in the last
-- 30 days (SPEC-116). The bot account may add and update rows but never delete them: unlinking only clears the FID.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

CREATE TABLE IF NOT EXISTS marong.app_devices (
  install_id    uuid PRIMARY KEY,                         -- made once by the app (not backed up)
  friend_id     bigint NOT NULL REFERENCES marong.friends(id),
  fid           text UNIQUE CHECK (fid ~ '^[A-Za-z0-9_-]{16,200}$'),  -- Firebase installation ID. NULL: none or dropped
  notifications text NOT NULL CHECK (notifications IN ('granted', 'denied')),
  app_version   text NOT NULL CHECK (app_version ~ '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'),
  seen_at       timestamptz NOT NULL DEFAULT now(),       -- when the app last reported
  dropped_at    timestamptz,                              -- when FCM said the device is gone
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (dropped_at IS NULL OR fid IS NULL)
);
CREATE INDEX IF NOT EXISTS app_devices_friend_idx ON marong.app_devices (friend_id, seen_at DESC);

GRANT SELECT, INSERT, UPDATE ON marong.app_devices TO marong;
-- In-app chat sign-in (SPEC-111): email sha256 → call friend. The masked email is not readable.
GRANT SELECT (email_sha256, caller_id) ON call.caller_logins TO marong;
COMMIT;
