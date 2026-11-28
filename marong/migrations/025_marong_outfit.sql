-- 025 The default 마롱이 wears items too (part pet-app, feature change 1 "기본 마롱이에게 입히기", D192, 2026-11-28).
-- Design draft from the design PR; not applied to the server. 024 is left for the iPhone web app notifications draft
-- (docs/05-erd/024_web_push_subscriptions.draft.sql). Needs 022. Only adds a table, a column, indexes and a CHECK, lets two
-- columns be empty and allows one more fail_reason value, so the code on main keeps working: it never writes a row
-- without a character. Safe to apply twice. No down script: a rollback turns the switch off, drains the default
-- 마롱이 rows and reverts the code, and the tables stay (SPEC-575, docs/05-erd/pet-app.md 8절).

-- TBL-190 marong_outfits (CTX-030) ← SPEC-570, SPEC-571 | terms: TERM-218
-- What a friend's default 마롱이 wears, one item per slot. One row per friend; no row means nothing worn.
-- Pet characters keep their own row in outfits (TBL-178). The app checks that each item is owned and fits the slot,
-- as for outfits (SPEC-420).
CREATE TABLE IF NOT EXISTS marong.marong_outfits (
  friend_id  bigint PRIMARY KEY REFERENCES marong.friends (id),
  head       text REFERENCES marong.decor_items (id),
  body       text REFERENCES marong.decor_items (id),
  neck       text REFERENCES marong.decor_items (id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- TBL-179 outfit_firsts: a row with no character is the default 마롱이's first wear of an item (SPEC-572).
-- One such row per friend and item, like (character_id, item_id) for a pet.
ALTER TABLE marong.outfit_firsts ALTER COLUMN character_id DROP NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS outfit_firsts_marong_once ON marong.outfit_firsts (friend_id, item_id)
  WHERE character_id IS NULL;

-- TBL-179 outfit_firsts.scene_job_id (SPEC-422, SPEC-572): the one model drawing job of this first wear, the key every
-- retry reuses. scene_picture_id stays the picture that was actually sent (the job's picture when it is done in time,
-- otherwise a separate fallback row). The job row keeps its own cost; a fallback row costs 0 (022's CHECK), so the two are
-- never the same row. The app creates the job and stores its id in one transaction while holding the first-wear row
-- (SELECT ... FOR UPDATE), so a crash leaves neither and a second worker waits and then reuses the stored job.
ALTER TABLE marong.outfit_firsts ADD COLUMN IF NOT EXISTS scene_job_id uuid REFERENCES marong.scene_pictures (id);
CREATE UNIQUE INDEX IF NOT EXISTS outfit_firsts_scene_job_once ON marong.outfit_firsts (scene_job_id)
  WHERE scene_job_id IS NOT NULL;

-- TBL-176 scene_pictures: a picture with no character is the default 마롱이 drawn for a first-wear reaction.
-- Topic pictures of the default 마롱이 stay the drawn picture set (REQ-694), so such a row is always a reaction.
ALTER TABLE marong.scene_pictures ALTER COLUMN character_id DROP NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'scene_pictures_marong_reaction') THEN
    ALTER TABLE marong.scene_pictures
      ADD CONSTRAINT scene_pictures_marong_reaction CHECK (character_id IS NOT NULL OR purpose = 'reaction');
  END IF;
END $$;

-- Rollback support (SPEC-575): with MARONG_DEFAULT_WEAR=0 the new code finishes queued default 마롱이 pictures as
-- failed with the reason 'disabled' and no model call, so the code on main never claims one after a code rollback.
-- The column's CHECK from 022 gets that one value; every old value stays valid.
ALTER TABLE marong.scene_pictures DROP CONSTRAINT IF EXISTS scene_pictures_fail_reason_check;
ALTER TABLE marong.scene_pictures ADD CONSTRAINT scene_pictures_fail_reason_check
  CHECK (fail_reason IN ('budget', 'refused', 'model_error', 'timeout', 'check_failed', 'disabled'));

-- The app server (role marong) reads and writes it, without delete, like the other decor tables.
GRANT SELECT, INSERT, UPDATE ON marong.marong_outfits TO marong;
