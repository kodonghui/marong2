-- 021 Per-account usage limits (CTX-029, CTX-006).
-- (docs/04-functional-spec/usage-limit.md SPEC-397~399, REQ-484~490, decision D106.)
-- Three columns on marong.friend_profiles (TBL-167) hold the account limit (TERM-199): unlimited, or this account's
-- daily units and monthly call dollars. A NULL number falls back to the server default (TERM-200:
-- MARONG_DAILY_UNITS, MARONG_CALL_PERSON_MONTHLY_USD). This file creates no table, so the TBL ID is a plain mention.
-- Rules kept here:
--   * Additive only. The code of main ad9f2f4 keeps running on a database with this migration: it never reads
--     these columns.
--   * Every profile that exists when usage_unlimited is first added becomes unlimited (REQ-490, D106). The backfill
--     runs only in the run that adds the column, so running this file again never undoes the owner's later change.
--   * Rows made later start as 'default' (false, NULL, NULL), so the sign-up code (SPEC-373) does not change.
--   * Grants: the app server role (marong) already has table-wide SELECT and UPDATE here (020), which the admin
--     API needs (API-243). The call role (marong_call) reads the new columns through its table-wide SELECT, and its
--     column UPDATE (tickets, updated_at) still keeps it from changing a limit.
-- Safe to run twice. Apply after 020 as the migration administrator, then call/migrations/009_usage_limit.sql.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- friend_profiles (TBL-167) ← SPEC-397, SPEC-398 | terms: TERM-199, TERM-200
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_attribute WHERE attrelid = 'marong.friend_profiles'::regclass
                 AND attname = 'usage_unlimited' AND NOT attisdropped) THEN
    ALTER TABLE marong.friend_profiles ADD COLUMN usage_unlimited boolean NOT NULL DEFAULT false;
    UPDATE marong.friend_profiles SET usage_unlimited = true;    -- the acquaintances using the app now (D106)
  END IF;
END $$;
ALTER TABLE marong.friend_profiles
  ADD COLUMN IF NOT EXISTS daily_units integer,                   -- NULL = MARONG_DAILY_UNITS
  ADD COLUMN IF NOT EXISTS call_monthly_usd numeric(7, 2);        -- NULL = MARONG_CALL_PERSON_MONTHLY_USD
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_constraint WHERE conrelid = 'marong.friend_profiles'::regclass
                 AND conname = 'friend_profiles_usage_limit_check') THEN
    ALTER TABLE marong.friend_profiles ADD CONSTRAINT friend_profiles_usage_limit_check CHECK (
      (daily_units IS NULL OR daily_units BETWEEN 1 AND 100000)
      AND (call_monthly_usd IS NULL OR call_monthly_usd BETWEEN 0.01 AND 1000)
      AND (NOT usage_unlimited OR (daily_units IS NULL AND call_monthly_usd IS NULL)));
  END IF;
END $$;

RESET ROLE;
COMMIT;
