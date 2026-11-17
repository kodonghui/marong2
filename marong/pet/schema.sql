-- Marong pet service: tables of the new database marong_pet (docs/04-functional-spec/pet.md SPEC-310~369,
-- CTX-022~025). Design draft from stage 05 (2026-11-17): the schema is not frozen.
-- The friend Marong's database (marong) and its tables do not change (REQ-418). This file builds the pet
-- database from empty; later changes go to marong/pet/migrations/NNN_<name>.sql and are never edited once applied.
-- Rules kept here:
--   * Members delete their own data (SPEC-314, SPEC-341), so the service role may DELETE, unlike the friend
--     database. Everything a member owns hangs off pet.members with ON DELETE CASCADE. Orders keep their row with
--     member_id set to NULL for five years, and AI runs and jobs keep theirs with no member.
--   * Birth dates, names, phone numbers, emails and raw photos are never stored (SPEC-311, SPEC-313, SPEC-316).
--     The OIDC subject and the identity CI are kept only as HMAC-SHA256 with a server secret.
--   * Member writes that check a count (pets per member, creations in progress, one call) run under
--     pg_advisory_xact_lock on the member's key in the service; the counters below are also capped by CHECKs.
--   * Ids in addresses and answers are UUIDs (gen_random_uuid, PostgreSQL 13 or later). Times are timestamptz;
--     "day" columns are the Korea day that turns at 04:00 KST (common rule 4).
-- Roles: marong_pet_owner (NOLOGIN, owns the tables) and marong_pet (the run_pet.py service, peer login).
-- Run as the database administrator on an empty database marong_pet: createdb -O marong_pet_owner marong_pet.
-- Safe to run twice.
BEGIN;
SET LOCAL lock_timeout = '2s';

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_pet_owner') THEN
    CREATE ROLE marong_pet_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_pet') THEN
    CREATE ROLE marong_pet LOGIN;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS pet AUTHORIZATION marong_pet_owner;
SET LOCAL ROLE marong_pet_owner;

-- TBL-140 members (CTX-025) ← SPEC-310, SPEC-311, SPEC-313, SPEC-314, SPEC-346, SPEC-361, SPEC-364 | terms: TERM-136, TERM-137, TERM-148
CREATE TABLE IF NOT EXISTS pet.members (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_no              char(8) NOT NULL UNIQUE,            -- shown to the member, used by the operator to find them
  provider               text NOT NULL CHECK (provider IN ('kakao', 'google')),
  sub_hash               bytea,                              -- HMAC of the OIDC sub; NULL once deleting (a new login is a new member)
  status                 text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'minor_locked', 'deleting')),
  adult_self_declared_at timestamptz NOT NULL,               -- age 19+ from the signup birth date, which is not kept
  identity_verified_at   timestamptz,                        -- first-payment identity check (SPEC-313)
  identity_ci_hash       bytea,                              -- HMAC of the CI only; no name, phone or birth date
  free_tickets           integer NOT NULL DEFAULT 0 CHECK (free_tickets BETWEEN 0 AND 20),
  invite_id              uuid,                               -- the invite code used at signup, if any
  defaults_synced_at     timestamptz,                        -- free default items given up to this time (SPEC-346)
  created_at             timestamptz NOT NULL DEFAULT now(),
  last_login_at          timestamptz,
  deleting_since         timestamptz,
  minor_locked_at        timestamptz,
  CHECK ((status = 'deleting') = (deleting_since IS NOT NULL)),
  CHECK (status = 'deleting' OR sub_hash IS NOT NULL),
  CHECK ((identity_verified_at IS NULL) = (identity_ci_hash IS NULL))
);
-- rule: one member per OIDC account (SPEC-310)
CREATE UNIQUE INDEX IF NOT EXISTS members_login ON pet.members (provider, sub_hash) WHERE sub_hash IS NOT NULL;

-- TBL-141 sessions (CTX-025) ← SPEC-310, SPEC-311, SPEC-314 | terms: TERM-136
CREATE TABLE IF NOT EXISTS pet.sessions (
  token_hash          bytea PRIMARY KEY,                     -- SHA-256 of the random 32-byte cookie value
  kind                text NOT NULL CHECK (kind IN ('pending', 'member')),
  member_id           uuid REFERENCES pet.members (id) ON DELETE CASCADE,
  provider            text CHECK (provider IN ('kakao', 'google')),
  sub_hash            bytea,                                 -- pending signup only, cleared when it becomes a member session
  created_at          timestamptz NOT NULL DEFAULT now(),
  expires_at          timestamptz NOT NULL,                  -- pending 30 minutes, member 30 days sliding
  absolute_expires_at timestamptz NOT NULL,                  -- member 90 days from login
  CHECK ((kind = 'member') = (member_id IS NOT NULL)),
  CHECK (kind = 'member' OR (provider IS NOT NULL AND sub_hash IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS sessions_member ON pet.sessions (member_id);
CREATE INDEX IF NOT EXISTS sessions_expiry ON pet.sessions (expires_at);

-- TBL-142 consents (CTX-025) ← SPEC-311, SPEC-312 | terms: TERM-138, TERM-134
-- One row per change, never updated: the current value is the newest row of each kind (SPEC-311).
CREATE TABLE IF NOT EXISTS pet.consents (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  member_id   uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('terms', 'privacy', 'ai_notice', 'overseas_transfer')),
  doc_version text NOT NULL,
  value       boolean NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS consents_current ON pet.consents (member_id, kind, created_at DESC);

-- TBL-143 invites (CTX-025) ← SPEC-311, SPEC-368 | terms: none
CREATE TABLE IF NOT EXISTS pet.invites (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code_hash  bytea NOT NULL UNIQUE,                          -- SHA-256 of the code; the code is shown once to the operator
  uses_left  integer NOT NULL CHECK (uses_left >= 0),        -- rule: an invite cannot be used more than its uses
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz
);

-- TBL-144 media (CTX-022, CTX-023) ← SPEC-316, SPEC-317, SPEC-320, SPEC-322, SPEC-323, SPEC-324, SPEC-336, SPEC-340, SPEC-342, SPEC-364 | terms: TERM-106, TERM-107, TERM-108, TERM-109, TERM-143
-- Every stored file a member owns: processed photos, preview, candidates, the character sheet, new pictures,
-- the farewell picture and export zips. Files live under the service data folder by storage_key; the row says
-- who may read it (SPEC-364) and when it goes (delete_after). Shared art (backgrounds, item layers, fonts,
-- templates) is static files, not rows.
CREATE TABLE IF NOT EXISTS pet.media (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id    uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  creation_id  uuid,                                         -- FK added after pet.creations
  pet_id       uuid,                                         -- FK added after pet.pets
  kind         text NOT NULL CHECK (kind IN ('photo', 'preview', 'candidate', 'sheet_front', 'sheet_expression',
                                             'scene', 'farewell', 'export')),
  storage_key  text NOT NULL UNIQUE,
  content_type text NOT NULL CHECK (content_type IN ('image/png', 'image/webp', 'application/zip')),
  bytes        integer NOT NULL CHECK (bytes > 0),
  width        integer,
  height       integer,
  sha256       bytea NOT NULL,
  meta         jsonb NOT NULL DEFAULT '{}',                  -- round (0~2), expression, iou, faces_masked, model; no text from the member
  created_at   timestamptz NOT NULL DEFAULT now(),
  delete_after timestamptz                                   -- photos 30 days or at sheet, unchosen candidates 7 days, exports 24 hours
);
CREATE INDEX IF NOT EXISTS media_owner ON pet.media (member_id, kind);
CREATE INDEX IF NOT EXISTS media_creation ON pet.media (creation_id, kind) WHERE creation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS media_pet ON pet.media (pet_id, kind) WHERE pet_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS media_expiry ON pet.media (delete_after) WHERE delete_after IS NOT NULL;

-- TBL-145 creations (CTX-022) ← SPEC-316, SPEC-317, SPEC-318, SPEC-319, SPEC-320, SPEC-321, SPEC-322, SPEC-323, SPEC-324, SPEC-325, SPEC-326 | terms: TERM-110, TERM-105, TERM-111, TERM-102, TERM-103
CREATE TABLE IF NOT EXISTS pet.creations (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id       uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  kind            text NOT NULL CHECK (kind IN ('living', 'memorial')),
  state           text NOT NULL DEFAULT 'photos' CHECK (state IN (
                    'photos', 'traits', 'traits_confirmed', 'previewed', 'paid', 'candidates', 'chosen',
                    'sheet_ready', 'done', 'sheet_needs_operator',
                    'rejected', 'failed_traits', 'failed_candidates', 'expired')),
  traits          jsonb,                                     -- 3.4 fields, list values only
  template        text CHECK (template IN ('dog_small', 'dog_large', 'dog_long', 'cat', 'cat_round')),
  faces_masked    integer NOT NULL DEFAULT 0 CHECK (faces_masked >= 0),
  preview_id      uuid REFERENCES pet.media (id) ON DELETE SET NULL,
  regenerations   integer NOT NULL DEFAULT 0 CHECK (regenerations BETWEEN 0 AND 2),   -- rule: two regenerations (SPEC-323)
  regenerate_note text CHECK (char_length(regenerate_note) <= 100),                    -- emptied when its round is drawn
  chosen_id       uuid REFERENCES pet.media (id) ON DELETE SET NULL,
  order_id        uuid,                                      -- FK added after pet.orders
  failure         text,                                      -- not_dog_or_cat, pet_not_visible, preview_failed, ...
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  expires_at      timestamptz NOT NULL DEFAULT now() + interval '30 days',             -- unpaid creations end (SPEC-326)
  CHECK (state IN ('photos', 'traits', 'rejected', 'failed_traits') OR template IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS creations_open ON pet.creations (member_id)
  WHERE state NOT IN ('done', 'rejected', 'failed_traits', 'failed_candidates', 'expired');
ALTER TABLE pet.media DROP CONSTRAINT IF EXISTS media_creation_fk;
ALTER TABLE pet.media ADD CONSTRAINT media_creation_fk
  FOREIGN KEY (creation_id) REFERENCES pet.creations (id) ON DELETE CASCADE;

-- TBL-146 pets (CTX-022) ← SPEC-324, SPEC-325, SPEC-331, SPEC-338, SPEC-339, SPEC-341, SPEC-364 | terms: TERM-101, TERM-102, TERM-103, TERM-107, TERM-111, TERM-132, TERM-141
CREATE TABLE IF NOT EXISTS pet.pets (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id      uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  creation_id    uuid NOT NULL UNIQUE REFERENCES pet.creations (id),  -- NO ACTION: checked after the member's cascade; deleting a pet also deletes its creation (SPEC-341)
  name           text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 12),
  intro          jsonb NOT NULL,                            -- personality (0~3 of 8), likes 60, dislikes 60, callMe 1~10 (3.4)
  species        text NOT NULL CHECK (species IN ('dog', 'cat')),
  template       text NOT NULL CHECK (template IN ('dog_small', 'dog_large', 'dog_long', 'cat', 'cat_round')),
  sheet          jsonb NOT NULL                             -- media ids of the character sheet: front and six expressions
                   CHECK (sheet ?& ARRAY['front', 'smile', 'excited', 'sleepy', 'surprised', 'sad', 'pout']),
  mode           text NOT NULL CHECK (mode IN ('living', 'memorial')),
  memorial_since timestamptz,                               -- rule: back to living only within 7 days (SPEC-338)
  passed_on      date,
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CHECK ((mode = 'memorial') = (memorial_since IS NOT NULL)),
  CHECK (status = 'active' OR mode = 'memorial')            -- rule: only memorial pets are archived (SPEC-341)
);
CREATE INDEX IF NOT EXISTS pets_member ON pet.pets (member_id, created_at);
ALTER TABLE pet.media DROP CONSTRAINT IF EXISTS media_pet_fk;
ALTER TABLE pet.media ADD CONSTRAINT media_pet_fk
  FOREIGN KEY (pet_id) REFERENCES pet.pets (id) ON DELETE CASCADE;

-- TBL-148 calls (CTX-022, CTX-024) ← SPEC-344, SPEC-345 | terms: TERM-123
CREATE TABLE IF NOT EXISTS pet.calls (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id        uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  pet_id           uuid NOT NULL REFERENCES pet.pets (id) ON DELETE CASCADE,
  token_hash       bytea NOT NULL UNIQUE,                    -- one-time call token, 60 seconds
  token_expires_at timestamptz NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  connected_at     timestamptz,
  ended_at         timestamptz,
  minutes          integer NOT NULL DEFAULT 0 CHECK (minutes >= 0),   -- minutes charged at 30 units each
  unbilled_minutes integer NOT NULL DEFAULT 0 CHECK (unbilled_minutes >= 0), -- minutes past the day's quota, not charged
  end_reason       text CHECK (end_reason IN ('member', 'quota', 'error', 'unused'))
);
-- rule: one call per member at a time (SPEC-344)
CREATE UNIQUE INDEX IF NOT EXISTS calls_one_open ON pet.calls (member_id) WHERE ended_at IS NULL;

-- TBL-147 messages (CTX-022) ← SPEC-325, SPEC-327, SPEC-328, SPEC-330, SPEC-332, SPEC-333, SPEC-335, SPEC-342, SPEC-344 | terms: TERM-120, TERM-142
-- Chat, proactive messages and call transcripts of one pet. Composite pictures are kept as a spec, not a file
-- (TERM-142): {backgroundId, expression, outfit: {head, body, neck}}.
CREATE TABLE IF NOT EXISTS pet.messages (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seq        bigint GENERATED ALWAYS AS IDENTITY UNIQUE,     -- order inside a pet's conversation
  member_id  uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  pet_id     uuid NOT NULL REFERENCES pet.pets (id) ON DELETE CASCADE,
  role       text NOT NULL CHECK (role IN ('member', 'pet', 'system')),
  kind       text NOT NULL CHECK (kind IN ('chat', 'greeting', 'proactive', 'item_reaction', 'call',
                                           'reply_failed', 'crisis_notice')),
  content    text NOT NULL,
  client_id  uuid,                                           -- member messages: repeat of the same send is one message
  composite  jsonb,                                          -- the picture of a proactive message or item reaction
  item_id    uuid,                                           -- item reaction: the item (FK added after pet.items)
  call_id    uuid REFERENCES pet.calls (id) ON DELETE CASCADE,  -- call transcript lines go with their call
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (role <> 'member' OR (char_length(content) BETWEEN 1 AND 1000 OR kind = 'call')),
  CHECK (kind <> 'call' OR call_id IS NOT NULL),
  CHECK (kind <> 'item_reaction' OR item_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS messages_client ON pet.messages (member_id, client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS messages_pet ON pet.messages (pet_id, seq);
CREATE INDEX IF NOT EXISTS messages_member_day ON pet.messages (member_id, created_at) WHERE role = 'member';

-- TBL-149 memory_items (CTX-022, changed CTX-011) ← SPEC-329, SPEC-327 | terms: none
-- The friend memory items (TBL-123, SPEC-225~227) keyed by (member, pet). Open loops (TBL-124 in the friend
-- database) are the kind 'open_loop' here. Rule: a memory comes from a member message only (SPEC-329);
-- the service checks source_message_id is a member message before it inserts.
CREATE TABLE IF NOT EXISTS pet.memory_items (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id         uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  pet_id            uuid NOT NULL REFERENCES pet.pets (id) ON DELETE CASCADE,
  kind              text NOT NULL CHECK (kind IN ('fact', 'like', 'dislike', 'event', 'memory', 'open_loop')),
  text              text NOT NULL CHECK (char_length(text) BETWEEN 1 AND 80),
  status            text NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'superseded', 'withdrawn', 'forgotten')),
  source_message_id uuid REFERENCES pet.messages (id) ON DELETE SET NULL,
  heard_at          timestamptz NOT NULL,
  due_on            date,                                    -- open loops
  superseded_by     uuid REFERENCES pet.memory_items (id) ON DELETE SET NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (status <> 'superseded' OR superseded_by IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS memory_current ON pet.memory_items (pet_id, kind) WHERE status = 'current';

-- TBL-150 diary_entries (CTX-022, changed CTX-009) ← SPEC-335, SPEC-336, SPEC-340, SPEC-342, SPEC-343, SPEC-351 | terms: TERM-135, TERM-130, TERM-142, TERM-143, TERM-118
-- One page a day per pet, and one farewell page per pet (rule: the farewell happens once, SPEC-340).
CREATE TABLE IF NOT EXISTS pet.diary_entries (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id   uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  pet_id      uuid NOT NULL REFERENCES pet.pets (id) ON DELETE CASCADE,
  kind        text NOT NULL DEFAULT 'day' CHECK (kind IN ('day', 'farewell')),
  day         date NOT NULL,
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'skipped', 'failed')),
  attempts    integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
  title       text CHECK (char_length(title) <= 30),
  weather     text,
  body        text CHECK (char_length(body) <= 600),        -- day body or the farewell letter (200~500)
  mood        text,
  composite   jsonb,                                         -- the composite picture of the day
  picture_id  uuid REFERENCES pet.media (id) ON DELETE SET NULL,  -- a new picture (redraw) or the farewell picture
  redraws     integer NOT NULL DEFAULT 0 CHECK (redraws BETWEEN 0 AND 2),   -- rule: two redraws per page (SPEC-336)
  stickers    jsonb NOT NULL DEFAULT '[]'
                CHECK (jsonb_typeof(stickers) = 'array' AND jsonb_array_length(stickers) <= 10),  -- rule: ten stickers (SPEC-351)
  notified_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS diary_one_day ON pet.diary_entries (pet_id, day) WHERE kind = 'day';
CREATE UNIQUE INDEX IF NOT EXISTS diary_one_farewell ON pet.diary_entries (pet_id) WHERE kind = 'farewell';

-- TBL-151 items (CTX-023) ← SPEC-346, SPEC-347, SPEC-348, SPEC-352, SPEC-355 | terms: TERM-113, TERM-112, TERM-116, TERM-117, TERM-118, TERM-119, TERM-121
CREATE TABLE IF NOT EXISTS pet.items (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind           text NOT NULL CHECK (kind IN ('wear', 'sticker_pack', 'theme', 'font', 'theme_package')),
  name           text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 30),
  slot           text CHECK (slot IN ('head', 'body', 'neck')),
  price_krw      integer CHECK (price_krw > 0),              -- KRW total with VAT; NULL for items not sold alone
  is_default     boolean NOT NULL DEFAULT false,             -- free default item given at signup (SPEC-346)
  sellable       boolean NOT NULL DEFAULT false,
  limited        boolean NOT NULL DEFAULT false,
  sale_starts_at timestamptz,
  sale_ends_at   timestamptz,
  ended_at       timestamptz,                                -- rule: an ended limited item never reopens (SPEC-352)
  license_key    text NOT NULL,                              -- row of design/pet/licenses.csv
  tags           text[] NOT NULL DEFAULT '{}',               -- background choice for item reactions (snow, rain, ...)
  contents       uuid[] NOT NULL DEFAULT '{}',               -- theme package: the items inside
  assets         jsonb NOT NULL,                             -- static file names: layers per template, sticker set, theme art, font
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'wear') = (slot IS NOT NULL)),
  CHECK (kind <> 'font' OR NOT sellable),                    -- rule: fonts are not sold alone (REQ-395)
  CHECK (NOT sellable OR price_krw IS NOT NULL),
  CHECK (NOT (is_default AND sellable)),
  CHECK (kind = 'theme_package' OR cardinality(contents) = 0),
  CHECK (sale_ends_at IS NULL OR sale_starts_at IS NULL OR sale_starts_at < sale_ends_at)
);
ALTER TABLE pet.messages DROP CONSTRAINT IF EXISTS messages_item_fk;
ALTER TABLE pet.messages ADD CONSTRAINT messages_item_fk
  FOREIGN KEY (item_id) REFERENCES pet.items (id) ON DELETE RESTRICT;

-- TBL-153 orders (CTX-024) ← SPEC-321, SPEC-322, SPEC-349, SPEC-350, SPEC-351, SPEC-355, SPEC-356, SPEC-357, SPEC-358, SPEC-359, SPEC-360, SPEC-314 | terms: TERM-127, TERM-128, TERM-129, TERM-121
-- Kept five years without the member after an account is deleted (SPEC-314): order number, product, amounts,
-- times and the payment gateway's transaction id only.
CREATE TABLE IF NOT EXISTS pet.orders (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_no        text NOT NULL UNIQUE,
  member_id       uuid REFERENCES pet.members (id) ON DELETE SET NULL,
  product         text NOT NULL CHECK (product IN ('character_creation', 'recharge_half', 'recharge_full',
                                                   'subscription_month', 'item')),
  item_id         uuid REFERENCES pet.items (id) ON DELETE RESTRICT,
  creation_id     uuid REFERENCES pet.creations (id) ON DELETE SET NULL,
  amount_krw      integer NOT NULL CHECK (amount_krw >= 0),  -- KRW total with VAT, from the server price list
  vat_krw         integer NOT NULL CHECK (vat_krw >= 0 AND vat_krw <= amount_krw),
  free_ticket     boolean NOT NULL DEFAULT false,
  withdrawal_rule text NOT NULL,                             -- version of the 3.8 rule shown before payment
  status          text NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'paid', 'fulfilled', 'failed',
                                                                    'refund_pending', 'refunded')),
  idempotency_key uuid NOT NULL,
  pg_tx_id        text,                                      -- the payment gateway's transaction id
  used_at         timestamptz,                               -- first wear, apply or stick: withdrawal ends (3.8)
  refund_reason   text CHECK (refund_reason IN ('withdrawal', 'auto_generation_failed', 'operator')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  paid_at         timestamptz,
  fulfilled_at    timestamptz,
  refunded_at     timestamptz,
  keep_until      timestamptz NOT NULL DEFAULT now() + interval '5 years',
  CHECK ((product = 'item') = (item_id IS NOT NULL)),     -- creation_id may be NULL after the member is deleted
  CHECK (NOT free_ticket OR (product = 'character_creation' AND amount_krw = 0))
);
-- rule: the same key makes one order (SPEC-355)
CREATE UNIQUE INDEX IF NOT EXISTS orders_idempotent ON pet.orders (member_id, idempotency_key) WHERE member_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS orders_pg_tx ON pet.orders (pg_tx_id) WHERE pg_tx_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS orders_member ON pet.orders (member_id, created_at DESC) WHERE member_id IS NOT NULL;
ALTER TABLE pet.creations DROP CONSTRAINT IF EXISTS creations_order_fk;
ALTER TABLE pet.creations ADD CONSTRAINT creations_order_fk
  FOREIGN KEY (order_id) REFERENCES pet.orders (id) ON DELETE SET NULL;

-- TBL-152 inventory (CTX-023) ← SPEC-346, SPEC-349, SPEC-350, SPEC-351, SPEC-357, SPEC-360 | terms: TERM-115
CREATE TABLE IF NOT EXISTS pet.inventory (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id    uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  item_id      uuid NOT NULL REFERENCES pet.items (id) ON DELETE RESTRICT,
  source       text NOT NULL CHECK (source IN ('free_default', 'order', 'package')),
  order_id     uuid REFERENCES pet.orders (id) ON DELETE SET NULL,
  acquired_at  timestamptz NOT NULL DEFAULT now(),
  withdrawn_at timestamptz,                                  -- taken back by a withdrawal (SPEC-360)
  CHECK (source = 'free_default' OR order_id IS NOT NULL OR withdrawn_at IS NOT NULL)
);
-- rule: a member holds an item once (SPEC-346, SPEC-355)
CREATE UNIQUE INDEX IF NOT EXISTS inventory_once ON pet.inventory (member_id, item_id) WHERE withdrawn_at IS NULL;

-- TBL-154 decor (CTX-023) ← SPEC-333, SPEC-334, SPEC-349, SPEC-350 | terms: TERM-114, TERM-116, TERM-117
-- The decoration state of one pet: what it wears and its diary theme and font. Stickers stay with their diary
-- page (TBL-150). The service checks each item is in the member's inventory and in the right slot (SPEC-349).
CREATE TABLE IF NOT EXISTS pet.decor (
  pet_id     uuid PRIMARY KEY REFERENCES pet.pets (id) ON DELETE CASCADE,
  head_item  uuid REFERENCES pet.items (id) ON DELETE SET NULL,
  body_item  uuid REFERENCES pet.items (id) ON DELETE SET NULL,
  neck_item  uuid REFERENCES pet.items (id) ON DELETE SET NULL,
  theme_item uuid REFERENCES pet.items (id) ON DELETE SET NULL,
  font_item  uuid REFERENCES pet.items (id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- TBL-155 subscriptions (CTX-024) ← SPEC-353, SPEC-357, SPEC-359, SPEC-360, SPEC-314 | terms: TERM-126
CREATE TABLE IF NOT EXISTS pet.subscriptions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id        uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  status           text NOT NULL CHECK (status IN ('active', 'canceling', 'ended')),
  billing_key_enc  bytea,                                    -- the gateway billing key, encrypted with a server key; NULL once deleted
  price_krw        integer NOT NULL CHECK (price_krw > 0),
  first_order_id   uuid NOT NULL REFERENCES pet.orders (id) ON DELETE RESTRICT,
  period_start     timestamptz NOT NULL,
  period_end       timestamptz NOT NULL,
  next_charge_at   timestamptz,                              -- 09:00 KST on the renewal day
  retry_at         timestamptz,                              -- one retry a day after a failed charge
  new_price_krw    integer CHECK (new_price_krw > 0),        -- a price change waiting for the member's consent
  new_price_from   date,
  new_price_agreed_at timestamptz,
  canceled_at      timestamptz,
  ended_at         timestamptz,
  CHECK (period_start < period_end),
  CHECK ((status = 'ended') = (ended_at IS NOT NULL)),
  CHECK (status <> 'ended' OR billing_key_enc IS NULL),
  CHECK ((new_price_krw IS NULL) = (new_price_from IS NULL))
);
-- rule: one live subscription per member (SPEC-359)
CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_one ON pet.subscriptions (member_id) WHERE status <> 'ended';

-- TBL-156 member_days (CTX-024, CTX-022) ← SPEC-320, SPEC-328, SPEC-353, SPEC-354, SPEC-357, SPEC-358 | terms: TERM-123, TERM-124, TERM-145, TERM-146, TERM-125
-- One row per member and Korea day (the day turns at 04:00 KST, TERM-124). Held units count as used until
-- they are released (TBL-157). Rule: the day's quota is never exceeded, even by concurrent requests (SPEC-353):
-- a hold is one UPDATE ... WHERE used_units + n <= quota_limit.
CREATE TABLE IF NOT EXISTS pet.member_days (
  member_id            uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  day                  date NOT NULL,
  quota_limit          integer NOT NULL CHECK (quota_limit IN (100, 200)),
  used_units           integer NOT NULL DEFAULT 0 CHECK (used_units >= 0 AND used_units <= quota_limit),
  refilled_units       integer NOT NULL DEFAULT 0 CHECK (refilled_units >= 0),
  messages             integer NOT NULL DEFAULT 0 CHECK (messages BETWEEN 0 AND 300),   -- rule: asleep after 300 (SPEC-328)
  previews             integer NOT NULL DEFAULT 0 CHECK (previews BETWEEN 0 AND 3),     -- rule: three previews a day (SPEC-320)
  recharges            integer NOT NULL DEFAULT 0 CHECK (recharges BETWEEN 0 AND 3),    -- rule: three recharges a day (SPEC-358)
  rest_nudged_at       timestamptz,                          -- the 100th message's rest nudge, once a day
  recharge_prompted_at timestamptz,                          -- the first quota_exhausted of the day shows recharge (SPEC-354)
  PRIMARY KEY (member_id, day)
);

-- TBL-157 quota_holds (CTX-024) ← SPEC-336, SPEC-344, SPEC-345, SPEC-353 | terms: TERM-145
CREATE TABLE IF NOT EXISTS pet.quota_holds (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id  uuid NOT NULL,
  day        date NOT NULL,
  units      integer NOT NULL CHECK (units > 0),
  purpose    text NOT NULL CHECK (purpose IN ('call_minute', 'new_picture')),
  call_id    uuid REFERENCES pet.calls (id) ON DELETE SET NULL,
  diary_id   uuid REFERENCES pet.diary_entries (id) ON DELETE SET NULL,
  status     text NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'committed', 'released')),
  created_at timestamptz NOT NULL DEFAULT now(),
  settled_at timestamptz,
  FOREIGN KEY (member_id, day) REFERENCES pet.member_days (member_id, day) ON DELETE CASCADE,
  CHECK ((status = 'held') = (settled_at IS NULL))
);
CREATE INDEX IF NOT EXISTS quota_holds_open ON pet.quota_holds (created_at) WHERE status = 'held';  -- released after 10 minutes

-- TBL-158 ai_runs (CTX-022, CTX-024) ← SPEC-318, SPEC-320, SPEC-322, SPEC-324, SPEC-325, SPEC-327, SPEC-332, SPEC-333, SPEC-335, SPEC-336, SPEC-340, SPEC-345, SPEC-363, SPEC-367 | terms: none
-- One row per model call (AI-30~36) and per charged call minute: the cost record of SPEC-363 and the stage 05
-- AI call record. No prompt, answer, photo or member text; the pet entries have no tools, so no tool rows.
CREATE TABLE IF NOT EXISTS pet.ai_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  trace_id           uuid NOT NULL,                          -- the request or job that made the call
  member_id          uuid REFERENCES pet.members (id) ON DELETE SET NULL,
  pet_id             uuid REFERENCES pet.pets (id) ON DELETE SET NULL,
  entry              text NOT NULL CHECK (entry IN ('AI-30', 'AI-31', 'AI-32', 'AI-33', 'AI-34', 'AI-35', 'AI-36')),
  cost_kind          text NOT NULL CHECK (cost_kind IN ('vision', 'image', 'chat', 'diary', 'letter', 'call_minute')),
  purpose            text,                                   -- preview, candidate, expression, scene, farewell, greeting, reply, ...
  model              text NOT NULL,
  prompt_version     text NOT NULL,
  price_version      text NOT NULL,                          -- marong/pet/prices.json version
  effort             text,                                   -- reasoning setting, if any
  input_tokens       integer,
  output_tokens      integer,
  cache_read_tokens  integer,
  cache_write_tokens integer,
  images             integer,
  first_token_ms     integer,
  total_ms           integer,
  result             text NOT NULL CHECK (result IN ('ok', 'error', 'timeout', 'refused', 'limit', 'rejected_by_check')),
  stop_reason        text,
  fallback_reason    text,                                   -- why the backup model or a fixed sentence was used
  est_cost_microusd  bigint NOT NULL DEFAULT 0 CHECK (est_cost_microusd >= 0),
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_runs_month ON pet.ai_runs (created_at);

-- TBL-160 jobs (CTX-022, CTX-024, CTX-025) ← SPEC-314, SPEC-318, SPEC-320, SPEC-322, SPEC-323, SPEC-324, SPEC-327, SPEC-333, SPEC-335, SPEC-336, SPEC-340, SPEC-342, SPEC-357, SPEC-359, SPEC-369 | terms: TERM-133
-- The work queue of run_pet.py and the time record of SPEC-369 (queued_at to finished_at, with the number of
-- running jobs when it started). An export's zip is a media row (kind export) named in result_media_id.
CREATE TABLE IF NOT EXISTS pet.jobs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            text NOT NULL CHECK (kind IN ('traits', 'preview', 'candidates', 'sheet', 'reply', 'diary', 'redraw',
                                                'farewell', 'export', 'item_reaction', 'proactive', 'fulfil',
                                                'renew', 'account_delete', 'cleanup')),
  member_id       uuid REFERENCES pet.members (id) ON DELETE SET NULL,
  pet_id          uuid REFERENCES pet.pets (id) ON DELETE SET NULL,
  creation_id     uuid REFERENCES pet.creations (id) ON DELETE SET NULL,
  ref             jsonb NOT NULL DEFAULT '{}',               -- ids only (order, diary day, item); never member text
  status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed', 'canceled')),
  attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  run_after       timestamptz NOT NULL DEFAULT now(),
  lease_until     timestamptz,
  queued_at       timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  running_at_start integer,
  error_code      text,
  result_media_id uuid REFERENCES pet.media (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON pet.jobs (run_after) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_timing ON pet.jobs (kind, finished_at) WHERE status = 'done';
-- rule: one drawing at a time per creation (busy, SPEC-323)
CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_drawing ON pet.jobs (creation_id)
  WHERE status IN ('queued', 'running') AND kind IN ('preview', 'candidates', 'sheet');

-- TBL-161 push_subscriptions (CTX-022) ← SPEC-337 | terms: none
CREATE TABLE IF NOT EXISTS pet.push_subscriptions (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id  uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  endpoint   text NOT NULL UNIQUE,
  p256dh     text NOT NULL,
  auth       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_ok_at timestamptz
);

-- TBL-162 proactive_turns (CTX-022, changed CTX-007, CTX-020) ← SPEC-332, SPEC-333, SPEC-338 | terms: TERM-120
-- The friend gate's result rows (TBL-121, SPEC-213~219) keyed by (member, pet). The cap of three a day counts
-- sent rows per member. The draft is kept only until it is sent or dropped.
CREATE TABLE IF NOT EXISTS pet.proactive_turns (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id   uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  pet_id      uuid NOT NULL REFERENCES pet.pets (id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('memory', 'light', 'topic', 'item_reaction')),
  slot_at     timestamptz NOT NULL,
  status      text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'sent', 'skipped', 'retry', 'dropped')),
  reason      text,                                          -- cap, quiet_hours, memorial, item_removed, ...
  item_id     uuid REFERENCES pet.items (id) ON DELETE RESTRICT,
  message_id  uuid REFERENCES pet.messages (id) ON DELETE SET NULL,
  attempts    integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 2),
  draft       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  decided_at  timestamptz,
  CHECK ((kind = 'item_reaction') = (item_id IS NOT NULL)),
  CHECK (status IN ('planned', 'retry') OR draft IS NULL)
);
-- rule: one item reaction per pet and item (SPEC-333)
CREATE UNIQUE INDEX IF NOT EXISTS proactive_item_once ON pet.proactive_turns (pet_id, item_id) WHERE item_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS proactive_member_day ON pet.proactive_turns (member_id, slot_at) WHERE status = 'sent';

-- TBL-159 reports (CTX-025) ← SPEC-315 | terms: TERM-140
CREATE TABLE IF NOT EXISTS pet.reports (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id   uuid NOT NULL REFERENCES pet.members (id) ON DELETE CASCADE,
  target_type text NOT NULL CHECK (target_type IN ('message', 'picture')),
  target_id   uuid NOT NULL,                                 -- a message or media id; the copy below survives its deletion
  reason      text NOT NULL CHECK (reason IN ('strange', 'hurtful', 'sexual', 'dangerous', 'bad_picture', 'other')),
  note        text CHECK (char_length(note) <= 200),
  copy_text   text,                                          -- the reported pet message as it was
  copy_media  uuid REFERENCES pet.media (id) ON DELETE SET NULL,
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);
-- rule: one report per member and target (SPEC-315)
CREATE UNIQUE INDEX IF NOT EXISTS reports_once ON pet.reports (member_id, target_type, target_id);
CREATE INDEX IF NOT EXISTS reports_open ON pet.reports (created_at) WHERE status = 'open';

-- TBL-163 settings (CTX-024, CTX-025) ← SPEC-362, SPEC-363, SPEC-368 | terms: none
-- Operator settings kept out of Git: payments_enabled, business_info (registration and mail-order numbers,
-- trade name, representative, address, contact, shown under the shop), budget_alert:<YYYY-MM>:<80|100>.
CREATE TABLE IF NOT EXISTS pet.settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- without a table: TERM-104, TERM-122, TERM-131, TERM-139, TERM-144, TERM-147
--   TERM-104 무지개다리 is a word of the memorial mode; TERM-122 확률형 아이템 is not sold (REQ-403);
--   TERM-131 워터마크 is drawn into exported files; TERM-139 광고성 푸시 동의 is not asked in the first release
--   (REQ-337); TERM-144 배경 세트 is static art (design/pet/backgrounds); TERM-147 공개 서비스 is the deployment.

RESET ROLE;
GRANT USAGE ON SCHEMA pet TO marong_pet;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pet TO marong_pet;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pet TO marong_pet;
-- Consents are a record: the service adds rows and never changes one (SPEC-311).
REVOKE UPDATE ON pet.consents FROM marong_pet;
COMMIT;
