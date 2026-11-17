-- Listening test answers (CTX-002). Design: docs/04-functional-spec/call-cost.md (SPEC-183), docs/05-erd/erd.md.
-- Apply after 016_diary.sql as the migration administrator. The page /chat/listen/ on the bot's app chat server saves
-- answers with the bot account (marong). The ten sentences are a fixed file in the repository; clip files and the
-- answer key (which candidate made which clip) stay in server files, so no candidate name reaches this table.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE marong_owner;

-- TBL-114 listen_scores (CTX-002) ← SPEC-183 | terms: TERM-039
-- One answer per friend and clip; answering again keeps the last answer. At most one 'sounds like Marong' pick per
-- friend and sentence (listen_scores_one_pick_idx). A row with no score and no pick means 'no answer': moving the
-- pick off a clip that has no score leaves one, and the result tool skips it.
CREATE TABLE IF NOT EXISTS marong.listen_scores (
  test_id     text NOT NULL CHECK (test_id ~ '^[a-z0-9-]{3,40}$'),   -- the test bundle made by listen_test.py make
  friend_id   bigint NOT NULL REFERENCES marong.friends (id) ON DELETE RESTRICT,
  clip_id     text NOT NULL CHECK (clip_id ~ '^[a-z0-9]{8,32}$'),    -- random clip id, no candidate name
  sentence_no smallint NOT NULL CHECK (sentence_no BETWEEN 1 AND 10),
  score       smallint CHECK (score BETWEEN 1 AND 5),                -- naturalness; NULL until scored
  marong_like boolean NOT NULL DEFAULT false,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (test_id, friend_id, clip_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS listen_scores_one_pick_idx
  ON marong.listen_scores (test_id, friend_id, sentence_no) WHERE marong_like;

GRANT SELECT, INSERT, UPDATE ON marong.listen_scores TO marong;
COMMIT;
