-- 022 Pet characters inside the unified app: the pet speaks for itself, scene pictures drawn each time, a free shop
-- of outfits and diary decorations, stickers on diary pages.
-- (docs/04-functional-spec/pet-app.md SPEC-406~427, CTX-030~031, decisions D110~D117.)
-- Seven new tables (TBL-175~181) and new columns on characters, friend_profiles, diaries, topic_sends and app_rings.
-- 021 is left for the usage-limit work, which is designed in parallel; this file does not depend on it.
-- Rules kept here:
--   * Additive only. No table or column is dropped or renamed, so the code of main ad9f2f4 keeps running on a
--     database that has this migration (the old code never reads the new tables or columns).
--   * Item files (layers, backgrounds, papers, fonts, stickers) live in the repository folder marong/decor/v1/ with
--     their licence ledger. The database holds only whether an item is in the shop and who claimed it.
--   * Prices are 0 for now (D113). A paid item needs a new migration and a decision, so price_krw is checked = 0.
--   * Nobody gets DELETE on marong tables, as in schema.sql. Ended rows keep a timestamp or a state instead.
--   * No names, intros, prompts or chat text go into these tables except the pet intro the friend wrote, which is
--     the friend's own setting (SPEC-409). Logs read ids and numbers only (REQ-524).
-- Safe to run twice. Apply after 020_unified.sql and the call's 008_unified.sql, as the migration administrator.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- Changes to characters (TBL-169 in 020) ← SPEC-409, SPEC-406 | terms: TERM-179
-- The pet intro: up to three personality words from a fixed list, likes, dislikes and what the pet calls its owner.
-- intro_at is set the first time the intro is saved; the recommended voice is picked at that moment (SPEC-407).
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS personality text[] NOT NULL DEFAULT '{}';
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS likes text NOT NULL DEFAULT '';
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS dislikes text NOT NULL DEFAULT '';
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS owner_call text;
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS intro_at timestamptz;
ALTER TABLE marong.characters DROP CONSTRAINT IF EXISTS characters_intro_check;
ALTER TABLE marong.characters ADD CONSTRAINT characters_intro_check CHECK (
  cardinality(personality) <= 3
  AND personality <@ ARRAY['활발함', '얌전함', '겁이 많음', '먹보', '애교 많음', '고집 셈', '호기심 많음', '느긋함']::text[]
  AND char_length(likes) <= 60 AND char_length(dislikes) <= 60
  AND (owner_call IS NULL OR char_length(owner_call) BETWEEN 1 AND 10)
  AND (intro_at IS NULL OR owner_call IS NOT NULL)
);

-- Changes to characters (TBL-169 in 020) ← SPEC-428 (D120)
-- Which processed photo shows the pet best and where the pet is in it, from the trait job (AI-30). It sits outside
-- the editable trait sheet, so confirming the sheet (API-222) does not overwrite it. The preview and candidate
-- drawings crop this box from the photo; it is cleared together with the photos when the sheet is done.
ALTER TABLE marong.characters ADD COLUMN IF NOT EXISTS photo_pick jsonb;
ALTER TABLE marong.characters DROP CONSTRAINT IF EXISTS characters_photo_pick_check;
ALTER TABLE marong.characters ADD CONSTRAINT characters_photo_pick_check CHECK (
  CASE
    WHEN photo_pick IS NULL THEN true
    WHEN jsonb_typeof(photo_pick -> 'box') = 'array' THEN
      coalesce(photo_pick ->> 'photo' IN ('photo_1', 'photo_2', 'photo_3'), false)
      AND jsonb_array_length(photo_pick -> 'box') = 4
    ELSE false
  END
);

-- Changes to friend_profiles (TBL-167 in 020) ← SPEC-407 | terms: TERM-217
-- Who set the call voice: NULL (nobody, the default voice), 'recommended' (picked from the pet intro) or 'chosen'
-- (the friend picked it). A recommendation never replaces a chosen voice.
ALTER TABLE marong.friend_profiles ADD COLUMN IF NOT EXISTS voice_source text;
ALTER TABLE marong.friend_profiles DROP CONSTRAINT IF EXISTS friend_profiles_voice_source_check;
ALTER TABLE marong.friend_profiles ADD CONSTRAINT friend_profiles_voice_source_check
  CHECK ((voice_source IS NULL OR voice_source IN ('recommended', 'chosen')) AND (voice_source IS NULL OR voice IS NOT NULL));
-- Voices set before this migration were picked by the friend.
UPDATE marong.friend_profiles SET voice_source = 'chosen' WHERE voice IS NOT NULL AND voice_source IS NULL;

-- Changes to diaries (TBL-105 in 016) ← SPEC-408, SPEC-413 | terms: TERM-021
-- The character that wrote this diary, fixed when writing starts. NULL is the default 마롱이 (and every diary made
-- before this migration). A later change of character leaves it as it is.
ALTER TABLE marong.diaries ADD COLUMN IF NOT EXISTS character_id bigint REFERENCES marong.characters (id);

-- TBL-175 decor_items (CTX-030) ← SPEC-417, SPEC-418, SPEC-425, SPEC-426 | terms: TERM-212, TERM-213, TERM-214
-- One row per item of the item folder that the admin put in the shop at least once. An item in the folder without a
-- row is 'new' on the admin page. Unlisting only takes it out of the shop; owners keep it (REQ-529).
-- slot follows kind: hat → head, top → body, scarf → neck; other kinds have none.
CREATE TABLE IF NOT EXISTS marong.decor_items (
  id          text PRIMARY KEY CHECK (id ~ '^[a-z0-9-]{3,40}$'),
  item_set    text NOT NULL DEFAULT 'v1' CHECK (item_set ~ '^v[0-9]{1,3}$'),       -- the folder marong/decor/<set>/
  kind        text NOT NULL CHECK (kind IN ('hat', 'top', 'scarf', 'background', 'paper', 'font', 'sticker')),
  slot        text CHECK (slot IN ('head', 'body', 'neck')),
  price_krw   integer NOT NULL DEFAULT 0 CHECK (price_krw = 0),                      -- D113: free for now
  starter     boolean NOT NULL DEFAULT false,                                        -- everyone owns it (SPEC-426)
  state       text NOT NULL DEFAULT 'listed' CHECK (state IN ('listed', 'unlisted')),
  listed_at   timestamptz NOT NULL DEFAULT now(),                                    -- the last time it was listed
  unlisted_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind IN ('hat', 'top', 'scarf')) = (slot IS NOT NULL)),
  CHECK (slot IS NULL OR slot = CASE kind WHEN 'hat' THEN 'head' WHEN 'top' THEN 'body' WHEN 'scarf' THEN 'neck' END),
  CHECK (NOT starter OR kind IN ('background', 'paper', 'font')),
  CHECK ((state = 'unlisted') = (unlisted_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS decor_items_shop_idx ON marong.decor_items (kind, listed_at) WHERE state = 'listed';

-- TBL-176 scene_pictures (CTX-031) ← SPEC-410, SPEC-411, SPEC-414, SPEC-415, SPEC-416, SPEC-422
--   | terms: TERM-210, TERM-211
-- One picture of the friend's pet character drawn for a picture topic or for a first-wear reaction. Diary scene
-- pictures stay in diary_drawings (TBL-108). A picture is never reused for another send (REQ-512).
-- The id is the picture's address (/chat/api/scenes/{id}) and never changes, so the file can be cached privately.
-- The work loop takes queued rows whose not_before has passed, oldest first, two at a time, each with a ten-minute
-- lease; a drawing row whose lease ran out goes back to queued, and fails after its third attempt.
-- cost_usd is recorded for every call; there is no monthly image budget for now (D119), so 'budget' is not used yet (SPEC-414).
CREATE TABLE IF NOT EXISTS marong.scene_pictures (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  friend_id      bigint NOT NULL REFERENCES marong.friends (id),
  character_id   bigint NOT NULL REFERENCES marong.characters (id),
  purpose        text NOT NULL CHECK (purpose IN ('topic', 'reaction')),
  topic          text CHECK (topic ~ '^v[0-9]{1,3}/[a-z0-9-]{1,40}$'),               -- the picture-set scene drawn
  item_id        text REFERENCES marong.decor_items (id),                            -- the item a reaction shows
  outfit         text[] NOT NULL DEFAULT '{}',                                       -- item ids worn when drawn
  state          text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'drawing', 'done', 'failed')),
  fail_reason    text CHECK (fail_reason IN ('budget', 'refused', 'model_error', 'timeout', 'check_failed')),
  fallback       boolean NOT NULL DEFAULT false,      -- a reaction picture made from the expression and item layers
  attempts       smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
  not_before     timestamptz NOT NULL DEFAULT now(),  -- a hello call's picture: 30 minutes before the topic time
  lease_until    timestamptz,
  model          text CHECK (char_length(model) BETWEEN 1 AND 60),
  prompt_version text CHECK (prompt_version ~ '^[a-z0-9-]{1,30}$'),                 -- e.g. scene-v1
  cost_usd       numeric(10, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
  cost_estimated boolean NOT NULL DEFAULT false,
  format         text CHECK (format IN ('webp', 'png')),
  width          integer CHECK (width > 0),
  height         integer CHECK (height > 0),
  image          bytea CHECK (octet_length(image) BETWEEN 1 AND 5242880),
  created_at     timestamptz NOT NULL DEFAULT now(),
  started_at     timestamptz,
  finished_at    timestamptz,
  CHECK ((purpose = 'topic') = (topic IS NOT NULL)),
  CHECK ((purpose = 'reaction') = (item_id IS NOT NULL)),
  CHECK ((state = 'done') = (image IS NOT NULL)),
  CHECK ((image IS NULL) = (format IS NULL) AND (image IS NULL) = (width IS NULL) AND (image IS NULL) = (height IS NULL)),
  CHECK ((state = 'failed') = (fail_reason IS NOT NULL)),
  CHECK ((state IN ('done', 'failed')) = (finished_at IS NOT NULL)),
  CHECK (state <> 'drawing' OR lease_until IS NOT NULL),
  CHECK (NOT fallback OR (purpose = 'reaction' AND state = 'done' AND cost_usd = 0)),
  CHECK (NOT cost_estimated OR cost_usd > 0)
);
CREATE INDEX IF NOT EXISTS scene_pictures_due_idx ON marong.scene_pictures (not_before) WHERE state IN ('queued', 'drawing');
CREATE INDEX IF NOT EXISTS scene_pictures_month_idx ON marong.scene_pictures (finished_at) WHERE finished_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS scene_pictures_friend_idx ON marong.scene_pictures (friend_id, created_at DESC);

-- Changes to topic_sends (TBL-125 in 018) ← SPEC-411 | terms: TERM-210
-- The scene picture sent with this topic, when the friend wears a pet character and it was drawn in time.
ALTER TABLE marong.topic_sends ADD COLUMN IF NOT EXISTS scene_picture_id uuid REFERENCES marong.scene_pictures (id);

-- Changes to app_rings (TBL-102 in 015, 018) ← SPEC-411 | terms: TERM-210
-- A hello ring of a pet character names the scene picture the call page shows on its topic card.
ALTER TABLE marong.app_rings ADD COLUMN IF NOT EXISTS scene_picture_id uuid REFERENCES marong.scene_pictures (id);
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_rings_scene_hello') THEN
    ALTER TABLE marong.app_rings ADD CONSTRAINT app_rings_scene_hello CHECK (reason = 'hello' OR scene_picture_id IS NULL);
  END IF;
END $$;

-- TBL-177 decor_owned (CTX-030) ← SPEC-418, SPEC-419 | terms: TERM-212
-- An item a friend claimed from the shop. One row per friend and item; claiming again changes nothing.
-- Starter items have no row: everyone owns them.
CREATE TABLE IF NOT EXISTS marong.decor_owned (
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  item_id    text NOT NULL REFERENCES marong.decor_items (id),
  claimed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (friend_id, item_id)
);

-- TBL-178 outfits (CTX-030) ← SPEC-420, SPEC-421 | terms: TERM-218
-- What a pet character wears, one item per slot. The app checks that each item is owned and fits the slot.
-- The default 마롱이 has no row until question A is answered (spec 3.10).
CREATE TABLE IF NOT EXISTS marong.outfits (
  character_id bigint PRIMARY KEY REFERENCES marong.characters (id),
  head         text REFERENCES marong.decor_items (id),
  body         text REFERENCES marong.decor_items (id),
  neck         text REFERENCES marong.decor_items (id),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- TBL-179 outfit_firsts (CTX-030) ← SPEC-420, SPEC-422 | terms: TERM-218
-- The first time a character wears an item, and the one reaction message that follows (REQ-536).
--   waiting → sent | blocked (the proactive gate stopped it twice) | skipped (taken off, character changed, or another
--   slot reacted for the same change).
CREATE TABLE IF NOT EXISTS marong.outfit_firsts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id        bigint NOT NULL REFERENCES marong.friends (id),
  character_id     bigint NOT NULL REFERENCES marong.characters (id),
  item_id          text NOT NULL REFERENCES marong.decor_items (id),
  state            text NOT NULL DEFAULT 'waiting' CHECK (state IN ('waiting', 'sent', 'blocked', 'skipped')),
  next_at          timestamptz NOT NULL,                                   -- worn_at + 3 minutes, then the next slot
  attempts         smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 1),
  scene_picture_id uuid REFERENCES marong.scene_pictures (id),
  worn_at          timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  UNIQUE (character_id, item_id),
  CHECK ((state = 'waiting') = (finished_at IS NULL)),
  CHECK (state <> 'sent' OR scene_picture_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS outfit_firsts_due_idx ON marong.outfit_firsts (friend_id, next_at) WHERE state = 'waiting';

-- TBL-180 diary_decor (CTX-030, CTX-007) ← SPEC-423 | terms: TERM-213, TERM-214, TERM-215
-- The background, paper and font of a friend's diary book. No row: the starter set, the diary as it looks today.
CREATE TABLE IF NOT EXISTS marong.diary_decor (
  friend_id     bigint PRIMARY KEY REFERENCES marong.friends (id),
  background_id text NOT NULL REFERENCES marong.decor_items (id),
  paper_id      text NOT NULL REFERENCES marong.decor_items (id),
  font_id       text NOT NULL REFERENCES marong.decor_items (id),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- TBL-181 diary_stickers (CTX-030, CTX-007) ← SPEC-424 | terms: TERM-216
-- A sticker placed on one diary page. Saving a page's stickers stamps removed_at on the rows that went and adds the
-- new ones in one transaction under the diary row's lock; a page has at most ten live rows (REQ-542).
-- x and y are per mille of the diary card, scale is a percentage, rotation is degrees, z is the stacking order.
CREATE TABLE IF NOT EXISTS marong.diary_stickers (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  diary_id   bigint NOT NULL REFERENCES marong.diaries (id),
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  item_id    text NOT NULL REFERENCES marong.decor_items (id),
  x          smallint NOT NULL CHECK (x BETWEEN 0 AND 1000),
  y          smallint NOT NULL CHECK (y BETWEEN 0 AND 1000),
  scale      smallint NOT NULL DEFAULT 100 CHECK (scale BETWEEN 50 AND 200),
  rotation   smallint NOT NULL DEFAULT 0 CHECK (rotation BETWEEN -180 AND 180),
  z          smallint NOT NULL CHECK (z BETWEEN 0 AND 9),
  created_at timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz
);
CREATE INDEX IF NOT EXISTS diary_stickers_live_idx ON marong.diary_stickers (diary_id, z) WHERE removed_at IS NULL;

-- The app server (role marong) reads and writes all of it.
GRANT SELECT, INSERT, UPDATE ON marong.decor_items, marong.scene_pictures, marong.decor_owned, marong.outfits,
  marong.outfit_firsts, marong.diary_decor, marong.diary_stickers TO marong;

-- The call server already reads characters and friend_profiles (020), so it sees the pet intro for the character
-- section (SPEC-406). It names a hello ring's scene picture on the topic card, and the call page loads the picture
-- from the app server with the same login (SPEC-411). It never reads the picture bytes.
GRANT SELECT (scene_picture_id) ON marong.app_rings TO marong_call;

RESET ROLE;
COMMIT;
