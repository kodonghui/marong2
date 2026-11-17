-- Marong's diary (CTX-007). Design: docs/04-functional-spec/diary.md (functional spec), docs/05-erd/erd.md (picture).
-- Apply after 015_app_ring.sql as the migration administrator. The bot account (marong) runs the night job, the morning
-- notice, the diary pages and the admin commands. Nobody gets DELETE: settings are added as new rows, text is added as
-- new revisions, drawings stay after a redraw, hiding is a flag. Diary text, titles, scenes and drawings live only in
-- these tables; logs and admin views read numbers (REQ-177). The day bundle is built in memory and never stored.
-- Dates: diary_date is the Korean date on which the diary day started (04:00 KST to 04:00 KST); times are UTC.
-- without a table: TERM-023 (day bundle, memory only), TERM-028 (placeholder drawing, a static picture file)
-- without a table: TERM-029 (diary pages, a read model over these tables), TERM-032 (drawing budget, a server setting)
-- without a table: TERM-018 (Marong's face pictures, static files shared with the call screen)
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-103 diary_settings (CTX-007) ← SPEC-150, SPEC-151, SPEC-165, SPEC-168 | terms: TERM-031
-- Rule: rows are only added. The value for diary day D is the row added last among the friend's rows with
-- from_date <= D; no row means off (REQ-172). on/off start at the next diary day; off --now starts today and stops
-- unfinished diaries (stop_now).
CREATE TABLE IF NOT EXISTS marong.diary_settings (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id) ON DELETE RESTRICT,
  enabled    boolean NOT NULL,
  from_date  date NOT NULL,                                -- first diary day the value applies to
  stop_now   boolean NOT NULL DEFAULT false,               -- off --now (SPEC-150)
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT (stop_now AND enabled))
);
CREATE INDEX IF NOT EXISTS diary_settings_friend_idx ON marong.diary_settings (friend_id, id DESC);

-- TBL-104 diary_looks (CTX-007) ← SPEC-153, SPEC-154, SPEC-155, SPEC-166 | terms: TERM-030, TERM-031
-- Rule: values come only from the lists (no free text reaches the drawing model). All three or none; clearing the
-- card sets all three to NULL because the bot account has no DELETE.
CREATE TABLE IF NOT EXISTS marong.diary_looks (
  friend_id  bigint PRIMARY KEY REFERENCES marong.friends (id) ON DELETE RESTRICT,
  hair       text CHECK (hair IN ('long', 'bob', 'short', 'ponytail', 'curly')),
  glasses    text CHECK (glasses IN ('none', 'round', 'square')),
  top        text CHECK (top IN ('white', 'black', 'gray', 'navy', 'beige', 'pink', 'yellow', 'green')),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((hair IS NULL) = (glasses IS NULL) AND (glasses IS NULL) = (top IS NULL))
);

-- TBL-105 diaries (CTX-007) ← SPEC-150, SPEC-151, SPEC-152, SPEC-153, SPEC-155, SPEC-157, SPEC-158, SPEC-159, SPEC-160, SPEC-161, SPEC-162, SPEC-163, SPEC-164, SPEC-165, SPEC-167, SPEC-168 | terms: TERM-021, TERM-022, TERM-027, TERM-033
-- One row per friend and diary day (UNIQUE friend_id, diary_date). States follow the spec (3.1): pending → writing →
-- drawing → ready, or skipped/failed. ready, skipped and failed do not change, except that the admin re-run (SPEC-168)
-- puts a skipped or failed row back to pending. Text and drawings only grow; revision and drawing_id point at the
-- current ones (foreign keys at the end of this file). drawing_id NULL on a ready diary means the placeholder.
-- Rule: hide, stamp, notice, fixes and redraws exist only on a ready diary.
CREATE TABLE IF NOT EXISTS marong.diaries (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id          bigint NOT NULL REFERENCES marong.friends (id) ON DELETE RESTRICT,
  diary_date         date NOT NULL,
  state              text NOT NULL DEFAULT 'pending'
                     CHECK (state IN ('pending', 'writing', 'drawing', 'ready', 'skipped', 'failed')),
  fail_reason        text CHECK (fail_reason IN ('write_failed', 'refused', 'late', 'off')),
  attempts           smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),     -- write attempts used
  draw_tries         smallint NOT NULL DEFAULT 0 CHECK (draw_tries BETWEEN 0 AND 2),   -- night drawing and its retry
  next_at            timestamptz NOT NULL DEFAULT now(),   -- when the night job may take the row (retries: +30 min, +2 h)
  lease_until        timestamptz,                          -- night job lease (10 min)
  revision           integer,                              -- current revision; NULL before the first one
  drawing_id         uuid,                                 -- current AI drawing; NULL is the placeholder
  placeholder_reason text CHECK (placeholder_reason IN ('scene_rejected', 'draw_failed', 'draw_refused',
                                                        'drawing_budget', 'draw_unavailable', 'late')),
                                                           -- why the night job used the placeholder (kept after a redraw)
  ready_at           timestamptz,
  hidden             boolean NOT NULL DEFAULT false,       -- SPEC-163, never a deletion
  stamped_at         timestamptz,                          -- SPEC-164; NULL when there is no stamp
  fixes_used         smallint NOT NULL DEFAULT 0 CHECK (fixes_used BETWEEN 0 AND 5),      -- successful fixes (REQ-151)
  redraws_used       smallint NOT NULL DEFAULT 0 CHECK (redraws_used BETWEEN 0 AND 2),    -- successful redraws (REQ-153)
  busy               text CHECK (busy IN ('fix', 'redraw')),  -- one fix or redraw at a time (409 busy)
  busy_until         timestamptz,                          -- fix 90 s; a lapsed lease is free
  redraw_result      text CHECK (redraw_result IN ('done', 'scene_rejected', 'draw_failed', 'draw_refused',
                                                   'drawing_budget')),
  redraw_at          timestamptz,
  notice_state       text NOT NULL DEFAULT 'none'
                     CHECK (notice_state IN ('none', 'waiting', 'sending', 'sent', 'failed', 'cancelled')),
  notice_next_at     timestamptz,                          -- 08:30 KST of D+1 at the earliest; failed +10 min, later +1 min
  notice_attempts    smallint NOT NULL DEFAULT 0 CHECK (notice_attempts BETWEEN 0 AND 3),
  notice_sending_at  timestamptz,                          -- saved before sending: at most one notice (SPEC-157)
  notified_at        timestamptz,
  notice_line        smallint CHECK (notice_line BETWEEN 1 AND 3),  -- which sentence of the spec (3.7) was sent
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (friend_id, diary_date),
  CHECK ((state = 'failed') = (fail_reason IS NOT NULL)),
  CHECK ((state = 'ready') = (ready_at IS NOT NULL)),
  CHECK (state NOT IN ('drawing', 'ready') OR revision IS NOT NULL),
  CHECK (state = 'ready' OR (NOT hidden AND stamped_at IS NULL AND fixes_used = 0 AND redraws_used = 0
                             AND busy IS NULL AND redraw_result IS NULL)),
  CHECK (notice_state = 'none' OR state = 'ready'),
  CHECK ((notice_state = 'sent') = (notified_at IS NOT NULL)),
  CHECK (notice_state <> 'sending' OR notice_sending_at IS NOT NULL),
  CHECK ((busy IS NULL) = (busy_until IS NULL)),
  CHECK ((redraw_result IS NULL) = (redraw_at IS NULL))
);
CREATE INDEX IF NOT EXISTS diaries_due_idx ON marong.diaries (next_at) WHERE state IN ('pending', 'writing', 'drawing');
CREATE INDEX IF NOT EXISTS diaries_notice_idx ON marong.diaries (notice_next_at) WHERE notice_state = 'waiting';
CREATE INDEX IF NOT EXISTS diaries_stamp_idx ON marong.diaries (friend_id, stamped_at DESC) WHERE stamped_at IS NOT NULL;

-- TBL-106 diary_ai_runs (CTX-007) ← SPEC-153, SPEC-155, SPEC-156, SPEC-160, SPEC-161, SPEC-167 | terms: none
-- One row per model call (AI-6 write, AI-7 fix and scene, AI-8 draw), written once when the call ends. No prompt,
-- answer, day bundle, scene or picture: numbers and labels only (REQ-177). The drawing budget (SPEC-156) is the sum of
-- cost_usd of kind 'draw' in the Korean month, failed and refused calls included when usage came back.
CREATE TABLE IF NOT EXISTS marong.diary_ai_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  diary_id           bigint NOT NULL REFERENCES marong.diaries (id) ON DELETE RESTRICT,
  kind               text NOT NULL CHECK (kind IN ('write', 'fix', 'scene', 'draw')),
  origin             text NOT NULL CHECK (origin IN ('night', 'retry', 'fix', 'redraw')),
  attempt            smallint NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 3),  -- write attempt or night drawing try
  reask              boolean NOT NULL DEFAULT false,       -- the one re-ask inside an attempt (length or scene)
  trace_id           text NOT NULL,                        -- API traceId, or the night job run id
  model              text NOT NULL,
  prompt_version     text NOT NULL,                        -- e.g. diary-v1
  effort             text,                                 -- text models: effort; drawing: quality
  thinking           text,
  sent_at            timestamptz NOT NULL,
  first_token_ms     integer CHECK (first_token_ms >= 0),
  total_ms           integer CHECK (total_ms >= 0),
  input_tokens       integer CHECK (input_tokens >= 0),
  image_input_tokens integer CHECK (image_input_tokens >= 0),  -- drawing: reference pictures (part of input_tokens)
  output_tokens      integer CHECK (output_tokens >= 0),
  cache_read_tokens  integer CHECK (cache_read_tokens >= 0),
  cache_write_tokens integer CHECK (cache_write_tokens >= 0),
  cost_usd           numeric(10, 6) CHECK (cost_usd >= 0),
  cost_estimated     boolean NOT NULL DEFAULT false,       -- drawing usage missing: 0.025 (SPEC-156)
  outcome            text NOT NULL CHECK (outcome IN ('ok', 'error', 'timeout', 'limit', 'invalid', 'refused')),
  stop_reason        text,                                 -- the provider's stop reason
  error_code         text,                                 -- e.g. http_500, no_key, billing, too_long, scene:first_word
  fallback           text,                                 -- what was used instead, e.g. placeholder, keep_scene
  CHECK (NOT cost_estimated OR cost_usd IS NOT NULL),
  CHECK (CASE kind WHEN 'write' THEN origin IN ('night', 'retry') WHEN 'fix' THEN origin = 'fix'
                   WHEN 'scene' THEN origin = 'redraw' ELSE origin IN ('night', 'retry', 'redraw') END)
);
CREATE INDEX IF NOT EXISTS diary_ai_runs_sent_idx ON marong.diary_ai_runs (kind, sent_at);
CREATE INDEX IF NOT EXISTS diary_ai_runs_diary_idx ON marong.diary_ai_runs (diary_id, sent_at);

-- TBL-107 diary_revisions (CTX-007) ← SPEC-153, SPEC-154, SPEC-158, SPEC-159, SPEC-160, SPEC-161, SPEC-162, SPEC-163 | terms: TERM-021, TERM-025, TERM-026
-- Title, mood weather, text and scene of one revision. Rows are only added (README: records are never deleted).
-- write makes the first one, fix and weather add one, a redraw with a new scene adds one that copies the text.
-- The scene stays inside the server: no API response returns it.
CREATE TABLE IF NOT EXISTS marong.diary_revisions (
  diary_id   bigint NOT NULL REFERENCES marong.diaries (id) ON DELETE RESTRICT,
  revision   integer NOT NULL CHECK (revision >= 1),
  source     text NOT NULL CHECK (source IN ('write', 'fix', 'weather', 'redraw')),
  title      text NOT NULL CHECK (char_length(title) BETWEEN 2 AND 20),
  weather    text NOT NULL CHECK (weather IN ('sunny', 'cloudy', 'rain', 'snow', 'rainbow')),
  body       text NOT NULL CHECK (char_length(body) BETWEEN 60 AND 160),
  scene      text CHECK (char_length(scene) BETWEEN 1 AND 400),  -- NULL when the scene failed its check
  ai_run_id  bigint REFERENCES marong.diary_ai_runs (id) ON DELETE RESTRICT,  -- NULL for a weather change
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (diary_id, revision),
  CHECK ((source = 'weather') = (ai_run_id IS NULL))
);

-- TBL-108 diary_drawings (CTX-007) ← SPEC-155, SPEC-158, SPEC-161, SPEC-167 | terms: TERM-024
-- Only AI drawings that passed the server check (format by magic bytes, 5 MB, landscape). The id is the picture's
-- address (/chat/diary/api/drawings/{id}) and never changes, so the file can be cached for a year (SPEC-158).
CREATE TABLE IF NOT EXISTS marong.diary_drawings (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  diary_id   bigint NOT NULL REFERENCES marong.diaries (id) ON DELETE RESTRICT,
  revision   integer NOT NULL,                             -- the revision whose scene was drawn
  origin     text NOT NULL CHECK (origin IN ('night', 'retry', 'redraw')),
  ai_run_id  bigint NOT NULL UNIQUE REFERENCES marong.diary_ai_runs (id) ON DELETE RESTRICT,
  format     text NOT NULL CHECK (format IN ('webp', 'png')),
  width      integer NOT NULL,
  height     integer NOT NULL,
  image      bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 5242880),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (diary_id, id),
  FOREIGN KEY (diary_id, revision) REFERENCES marong.diary_revisions (diary_id, revision) ON DELETE RESTRICT,
  CHECK (height > 0 AND width > height)
);
CREATE INDEX IF NOT EXISTS diary_drawings_diary_idx ON marong.diary_drawings (diary_id, created_at);

-- TBL-109 diary_requests (CTX-007) ← SPEC-160, SPEC-161 | terms: none
-- Idempotency keys of fixes and redraws, and the per-friend limit of 5 a minute (rows of the last minute). A repeated
-- key gets the first result, rebuilt from the stored revision or code. Rows are kept, so a repeat is answered for at
-- least the 24 hours the spec promises. No text of the request is stored.
CREATE TABLE IF NOT EXISTS marong.diary_requests (
  friend_id       bigint NOT NULL REFERENCES marong.friends (id) ON DELETE RESTRICT,
  idem_key        uuid NOT NULL,
  diary_id        bigint NOT NULL REFERENCES marong.diaries (id) ON DELETE RESTRICT,
  kind            text NOT NULL CHECK (kind IN ('fix', 'redraw')),
  result_code     text,                                    -- NULL while running; ok or the error code
  result_revision integer,                                 -- the revision a successful fix made
  scene_changed   boolean,
  created_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  PRIMARY KEY (friend_id, idem_key),
  CHECK ((result_code IS NULL) = (finished_at IS NULL))
);
CREATE INDEX IF NOT EXISTS diary_requests_recent_idx ON marong.diary_requests (friend_id, created_at DESC);

-- The current revision and drawing belong to the same diary.
ALTER TABLE marong.diaries DROP CONSTRAINT IF EXISTS diaries_revision_fkey;
ALTER TABLE marong.diaries ADD CONSTRAINT diaries_revision_fkey
  FOREIGN KEY (id, revision) REFERENCES marong.diary_revisions (diary_id, revision) ON DELETE RESTRICT;
ALTER TABLE marong.diaries DROP CONSTRAINT IF EXISTS diaries_drawing_fkey;
ALTER TABLE marong.diaries ADD CONSTRAINT diaries_drawing_fkey
  FOREIGN KEY (id, drawing_id) REFERENCES marong.diary_drawings (diary_id, id) ON DELETE RESTRICT;

GRANT SELECT, INSERT ON marong.diary_settings, marong.diary_ai_runs, marong.diary_revisions, marong.diary_drawings
  TO marong;
GRANT SELECT, INSERT, UPDATE ON marong.diary_looks, marong.diaries, marong.diary_requests TO marong;
COMMIT;
