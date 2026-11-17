-- 019 Persona, proactive gate, favors and friend memory, stages 1 to 4
-- (docs/04-functional-spec/persona.md SPEC-192~242, CTX-008~013).
-- Eighteen new tables (TBL-115~124, TBL-127~134) and one schema for graph checkpoints. Nothing existing changes.
-- Rules kept here:
--   * Logs and result rows hold ids, labels and counts only. Text a friend wrote lives only where the spec needs it
--     (card values, rules, the custom instruction, memory items, a relay or call text until it is sent) and is
--     emptied when that row ends (common rule 10).
--   * Nobody gets DELETE on marong tables, as in schema.sql. Forgetting marks and empties rows instead (SPEC-230).
--     D63 approved marong.forget_embeddings() as the exception for vectors of forgotten sources.
--   * Friend writes run under pg_advisory_xact_lock(friend_id) in the bot and the call server (common rule 11).
--   * The call server (marong_call) never shares transcripts with the bot: call jobs run in the call organizer,
--     and the bot learns of a forgotten call turn only through forget_marks.
-- Safe to run twice. Apply after schema.sql, the call schema and 010~018, as the migration administrator
-- (superuser): the talk_graph line makes a schema owned by the bot role.
BEGIN;
SET LOCAL lock_timeout = '2s';

-- LangGraph checkpoints of the proactive gate (proactive:{friend}:{slot}), the text memory jobs (memory:{friend})
-- and the talk turn graph (talk:{friend}). AsyncPostgresSaver.setup() makes its own tables here, so they have no
-- TBL ID (same as call_graph, docs/05-erd/erd.md). State holds ids only (common rule 13). The bot owns the schema,
-- so it can remove old checkpoints (3.18, 3.20 step 5, 3.22).
CREATE SCHEMA IF NOT EXISTS talk_graph AUTHORIZATION marong;

SET LOCAL ROLE marong_owner;

-- TBL-115 friend_cards (CTX-008) ← SPEC-192, SPEC-193, SPEC-194, SPEC-195, SPEC-196, SPEC-197, SPEC-202, SPEC-220 | terms: TERM-040, TERM-041, TERM-042, TERM-047
-- One row per friend, made the first time any of these is needed. state 'none' holds only per-friend values that
-- exist before a card (lowered proactive, quiet_until); 'asking' is the first questions in progress; 'draft' is an
-- AI-13 draft waiting for its answer; 'set' is the card in use. The card sentence is not stored: code builds it from
-- the values (3.9). The latest write wins per column (common rule 11).
CREATE TABLE IF NOT EXISTS marong.friend_cards (
  friend_id      bigint PRIMARY KEY REFERENCES marong.friends (id),
  state          text NOT NULL DEFAULT 'none' CHECK (state IN ('none', 'asking', 'draft', 'set')),
  support        text CHECK (support IN ('listen', 'side', 'solve', 'distract', 'chat', 'ask')),
  advice         text CHECK (advice IN ('asked', 'sometimes', 'any')),
  honesty        text CHECK (honesty IN ('gentle', 'direct', 'let_go')),
  lead           text NOT NULL DEFAULT 'follow' CHECK (lead IN ('follow', 'lead')),
  proactive      text NOT NULL DEFAULT 'normal' CHECK (proactive IN ('normal', 'less', 'off')),  -- friends only lower it
  source         text CHECK (source IN ('questions', 'draft', 'draft_silent', 'default', 'proposal', 'talk', 'screen',
                                        'admin')),                  -- how the card was last set
  asking_since   timestamptz,                                       -- first question shown (24 h default, SPEC-192)
  set_at         timestamptz,
  notice_sent_at timestamptz,         -- the one "tell me if not" line after a draft_silent or default card
  want           text CHECK (want IN ('listen', 'side', 'solve', 'distract', 'chat', 'ask')),  -- for now (SPEC-195)
  want_until     timestamptz,                                       -- 24 hours after it was said
  quiet_until    timestamptz,         -- no proactive message until then, next 08:00 KST (SPEC-220)
  updated_at     timestamptz NOT NULL DEFAULT now(),
  updated_by     text NOT NULL DEFAULT 'friend' CHECK (updated_by IN ('friend', 'admin', 'system')),
  CHECK (state NOT IN ('draft', 'set') OR (support IS NOT NULL AND advice IS NOT NULL AND honesty IS NOT NULL)),
  CHECK ((state = 'set') = (set_at IS NOT NULL)),
  CHECK (state <> 'asking' OR asking_since IS NOT NULL),
  CHECK ((want IS NULL) = (want_until IS NULL))
);
CREATE INDEX IF NOT EXISTS friend_cards_asking_idx ON marong.friend_cards (asking_since) WHERE state IN ('asking', 'draft');

-- TBL-116 friend_rules (CTX-008) ← SPEC-194, SPEC-198, SPEC-199, SPEC-201, SPEC-212 | terms: TERM-044
-- Things a friend wants always kept, as structured values the send check reads (3.15 vocative, topic). A removed rule
-- keeps its row with removed_at. At most 20 live rules of a kind per friend: the bot counts under the friend lock.
CREATE TABLE IF NOT EXISTS marong.friend_rules (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  kind       text NOT NULL CHECK (kind IN ('no_vocative', 'avoid_topic', 'call_me')),
  text       text NOT NULL,
  source     text NOT NULL CHECK (source IN ('talk', 'instruction', 'screen', 'admin')),
  message_id bigint REFERENCES marong.messages (id),               -- the friend message it came from, if any
  created_at timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz,
  CHECK (CASE kind WHEN 'avoid_topic' THEN char_length(text) BETWEEN 2 AND 20 ELSE char_length(text) BETWEEN 1 AND 4 END)
);
CREATE UNIQUE INDEX IF NOT EXISTS friend_rules_live_idx ON marong.friend_rules (friend_id, kind, lower(text))
  WHERE removed_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS friend_rules_one_name_idx ON marong.friend_rules (friend_id)
  WHERE kind = 'call_me' AND removed_at IS NULL;

-- TBL-117 custom_instructions (CTX-008) ← SPEC-199, SPEC-200, SPEC-201 | terms: TERM-043
-- The friend's own "treat me like this" text (D25) and AI-14's reading of it. One row per friend; only the current
-- text is kept, and clearing empties it. The reading goes into 1:1 prompts; the text is shown on SCR-121 only.
-- version goes up on every change so a conversation keeps the version it opened with (SPEC-200).
CREATE TABLE IF NOT EXISTS marong.custom_instructions (
  friend_id  bigint PRIMARY KEY REFERENCES marong.friends (id),
  text       text CHECK (char_length(text) BETWEEN 1 AND 500),
  understood text CHECK (char_length(understood) BETWEEN 1 AND 300),  -- three sentences at most (AI-14)
  polite     boolean NOT NULL DEFAULT false,      -- the friend asked for 존댓말: the send check skips 'formal'
  via        text CHECK (via IN ('chat', 'screen')),
  version    integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((text IS NULL) = (understood IS NULL)),
  CHECK ((text IS NULL) = (via IS NULL)),
  CHECK (text IS NOT NULL OR NOT polite)
);

-- TBL-118 preference_signals (CTX-008, CTX-011) ← SPEC-195, SPEC-196, SPEC-197, SPEC-225 | terms: TERM-046, TERM-047
-- What a friend said about how to be treated, one row per value per Korean day. Three open rows of one value make a
-- proposal (SPEC-196); its answer closes the open rows of that field, so the count starts again from zero.
CREATE TABLE IF NOT EXISTS marong.preference_signals (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  field        text NOT NULL CHECK (field IN ('support', 'advice', 'honesty', 'lead')),
  value        text NOT NULL,
  day          date NOT NULL,                                       -- Korean date
  source       text NOT NULL CHECK (source IN ('want', 'ask_support', 'memory', 'call')),
  message_id   bigint REFERENCES marong.messages (id),
  call_turn_id bigint,                         -- call.turns id, no FK: transcripts go after 180 days
  created_at   timestamptz NOT NULL DEFAULT now(),
  closed_at    timestamptz,
  closed_by    text CHECK (closed_by IN ('accepted', 'declined', 'expired')),
  UNIQUE (friend_id, field, value, day),
  CHECK (CASE field WHEN 'support' THEN value IN ('listen', 'side', 'solve', 'distract', 'chat', 'ask')
                    WHEN 'advice' THEN value IN ('asked', 'sometimes', 'any')
                    WHEN 'honesty' THEN value IN ('gentle', 'direct', 'let_go')
                    ELSE value IN ('follow', 'lead') END),
  CHECK ((source = 'call') = (call_turn_id IS NOT NULL)),
  CHECK ((closed_at IS NULL) = (closed_by IS NULL))
);
CREATE INDEX IF NOT EXISTS preference_signals_open_idx ON marong.preference_signals (friend_id, field, value)
  WHERE closed_at IS NULL;

-- TBL-120 safety_states (CTX-012) ← SPEC-206, SPEC-207, SPEC-208, SPEC-209, SPEC-210, SPEC-211, SPEC-242 | terms: TERM-074, TERM-075, TERM-067
-- Where one friend's crisis steps are (kind crisis, 3.13) or a body and diet worry (kind body, 3.14, seven days).
-- At most one open row per friend and kind; a new signal after closing opens a new row. The signal text is never
-- stored. The bot and the call server both read and write it. No admin command, owner notice or sheet reads it
-- (SPEC-211): the code keeps this, the database cannot.
CREATE TABLE IF NOT EXISTS marong.safety_states (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id      bigint NOT NULL REFERENCES marong.friends (id),
  kind           text NOT NULL CHECK (kind IN ('crisis', 'body')),
  injured        boolean NOT NULL DEFAULT false,  -- crisis: already hurt, so 119 instead of 109
  opened_at      timestamptz NOT NULL DEFAULT now(),
  opened_via     text NOT NULL CHECK (opened_via IN ('text', 'call')),
  last_signal_at timestamptz NOT NULL DEFAULT now(),
  asked_at       timestamptz,                     -- crisis: the one safety question went out
  answer         text CHECK (answer IN ('now', 'not_now', 'unknown')),
  answered_at    timestamptz,
  told_109_at    timestamptz,                     -- crisis: 109 (or 119) line went out once
  told_help_at   timestamptz,                     -- body: the 1577-0199 line went out once
  care_sent_at   timestamptz,                     -- crisis: the one care check-in (SPEC-209)
  closed_at      timestamptz,
  close_reason   text CHECK (close_reason IN ('calm', 'quiet_3d', 'quiet_7d')),
  CHECK (kind = 'crisis' OR (asked_at IS NULL AND answer IS NULL AND told_109_at IS NULL AND care_sent_at IS NULL
                             AND NOT injured)),
  CHECK (kind = 'body' OR told_help_at IS NULL),
  CHECK (answer IS NULL OR asked_at IS NOT NULL),
  CHECK ((answer IS NULL) = (answered_at IS NULL)),
  CHECK ((closed_at IS NULL) = (close_reason IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS safety_states_one_open_idx ON marong.safety_states (friend_id, kind)
  WHERE closed_at IS NULL;

-- TBL-129 memory_forgets (CTX-011) ← SPEC-230, SPEC-231, SPEC-234, SPEC-242 | terms: TERM-071
-- One forget a friend asked for (tool, SCR-122 button, the sensitive-memory card or the call). The same request key
-- twice gives the same result (common rule 11). Same shape as call.deletions on the call side.
CREATE TABLE IF NOT EXISTS marong.memory_forgets (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id   bigint NOT NULL REFERENCES marong.friends (id),
  via         text NOT NULL CHECK (via IN ('tool', 'screen', 'card', 'call')),
  request_key text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 100),
  items       smallint NOT NULL DEFAULT 0 CHECK (items >= 0),      -- memory items and loops forgotten
  messages    smallint NOT NULL DEFAULT 0 CHECK (messages >= 0),   -- source messages and call turns marked
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (friend_id, request_key)
);

-- TBL-123 memory_items (CTX-011) ← SPEC-225, SPEC-226, SPEC-227, SPEC-229, SPEC-230, SPEC-231, SPEC-232, SPEC-233, SPEC-234, SPEC-235 | terms: TERM-063, TERM-064, TERM-065, TERM-072, TERM-073
-- One thing Marong remembers about one friend, with where it was heard (3.19). Only 'current' rows are read anywhere.
-- A changed value supersedes the old row (SPEC-226); forgetting empties text and quote and keeps ids and times.
-- room_key empty: the friend's own scope (1:1 words); set: only that group room (group words, SPEC-232).
CREATE TABLE IF NOT EXISTS marong.memory_items (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  kind         text NOT NULL CHECK (kind IN ('fact', 'preference', 'event', 'relation', 'hard')),
  text         text CHECK (char_length(text) BETWEEN 1 AND 80),
  status       text NOT NULL DEFAULT 'current'
                 CHECK (status IN ('current', 'superseded', 'retracted', 'forgotten', 'pending_ok')),
  heard_at     timestamptz NOT NULL,                                -- time of the source message or call turn
  channel      text NOT NULL CHECK (channel IN ('discord_dm', 'app', 'kakao_dm', 'kakao_group', 'discord_server',
                                                'call')),
  message_id   bigint REFERENCES marong.messages (id),
  call_turn_id bigint,                         -- call.turns id, no FK: transcripts go after 180 days
  quote        text CHECK (char_length(quote) BETWEEN 1 AND 120),   -- the friend's own words
  valid_until  date,                           -- plans and dates: that day + 7 (SPEC-227)
  room_key     text REFERENCES marong.rooms (room_key),
  share        text NOT NULL DEFAULT 'self' CHECK (share IN ('self', 'close', 'known')),
  sensitive    text CHECK (sensitive IN ('health', 'mental', 'sex', 'money', 'politics', 'religion', 'romance')),
  replaces_id  bigint REFERENCES marong.memory_items (id),          -- the row this one superseded
  source       text NOT NULL CHECK (source IN ('text', 'call')),    -- which job wrote it (two-week compare, SPEC-235)
  forget_id    bigint REFERENCES marong.memory_forgets (id),
  created_at   timestamptz NOT NULL DEFAULT now(),
  changed_at   timestamptz NOT NULL DEFAULT now(),                  -- last status change
  CHECK ((message_id IS NOT NULL) <> (call_turn_id IS NOT NULL)),
  CHECK ((channel = 'call') = (call_turn_id IS NOT NULL)),
  CHECK ((channel = 'call') = (source = 'call')),
  CHECK ((channel IN ('kakao_group', 'discord_server')) = (room_key IS NOT NULL)),
  CHECK (sensitive IS NULL OR share = 'self'),
  CHECK ((status = 'forgotten') = (forget_id IS NOT NULL)),
  CHECK ((status = 'forgotten') = (text IS NULL)),
  CHECK (status <> 'forgotten' OR quote IS NULL)
);
CREATE INDEX IF NOT EXISTS memory_items_friend_idx ON marong.memory_items (friend_id, kind, heard_at DESC)
  WHERE status = 'current';
CREATE INDEX IF NOT EXISTS memory_items_message_idx ON marong.memory_items (message_id) WHERE message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_items_turn_idx ON marong.memory_items (call_turn_id) WHERE call_turn_id IS NOT NULL;

-- TBL-124 open_loops (CTX-011) ← SPEC-213, SPEC-216, SPEC-217, SPEC-225, SPEC-228, SPEC-230, SPEC-240 | terms: TERM-066
-- Something not finished yet (an interview, a test result, a move). Closed, expired and forgotten loops are never
-- candidates or call topics. Whether a new loop is the same matter as an open one is the code's call (SPEC-228).
CREATE TABLE IF NOT EXISTS marong.open_loops (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  text         text CHECK (char_length(text) BETWEEN 1 AND 60),
  due          date,
  sensitivity  text NOT NULL CHECK (sensitivity IN ('low', 'mid', 'high')),
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'expired', 'forgotten')),
  opened_at    timestamptz NOT NULL,                                -- time of the source message or call turn
  expires_at   timestamptz NOT NULL,                                -- due + 7 days, or opened + 14 days
  closed_at    timestamptz,
  channel      text NOT NULL CHECK (channel IN ('discord_dm', 'app', 'kakao_dm', 'kakao_group', 'discord_server',
                                                'call')),
  message_id   bigint REFERENCES marong.messages (id),
  call_turn_id bigint,
  quote        text CHECK (char_length(quote) BETWEEN 1 AND 120),
  room_key     text REFERENCES marong.rooms (room_key),
  forget_id    bigint REFERENCES marong.memory_forgets (id),
  CHECK ((message_id IS NOT NULL) <> (call_turn_id IS NOT NULL)),
  CHECK ((channel = 'call') = (call_turn_id IS NOT NULL)),
  CHECK ((channel IN ('kakao_group', 'discord_server')) = (room_key IS NOT NULL)),
  CHECK ((status = 'open') = (closed_at IS NULL)),
  CHECK ((status = 'forgotten') = (forget_id IS NOT NULL)),
  CHECK ((status = 'forgotten') = (text IS NULL)),
  CHECK (status <> 'forgotten' OR quote IS NULL)
);
CREATE INDEX IF NOT EXISTS open_loops_open_idx ON marong.open_loops (friend_id, due) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS open_loops_expiry_idx ON marong.open_loops (expires_at) WHERE status = 'open';

-- TBL-131 relays (CTX-010) ← SPEC-238, SPEC-241 | terms: TERM-061, TERM-062, TERM-059
-- A message one friend asked Marong to pass to a friend they know, and the one reply the receiver asked to send back
-- (reply_of). The text is kept only until it is sent, cancelled or expired. Sent with the code template, never
-- rewritten by a model. At most three a day to one receiver: the bot counts under the receiver's lock.
CREATE TABLE IF NOT EXISTS marong.relays (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  from_friend  bigint NOT NULL REFERENCES marong.friends (id),
  to_friend    bigint NOT NULL REFERENCES marong.friends (id),
  reply_of     bigint REFERENCES marong.relays (id),
  text         text CHECK (char_length(text) BETWEEN 1 AND 300),
  status       text NOT NULL DEFAULT 'pending_confirm'
                 CHECK (status IN ('pending_confirm', 'confirmed', 'sent', 'cancelled', 'expired')),
  request_key  text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 100),  -- the tool call id
  send_after   timestamptz,                    -- confirmed: now, or 08:00 KST when confirmed at night
  reply_until  timestamptz,                    -- sent: three days for one reply back
  message_id   bigint REFERENCES marong.messages (id),               -- the delivered message
  created_at   timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  sent_at      timestamptz,
  closed_at    timestamptz,                    -- cancelled or expired
  UNIQUE (from_friend, request_key),
  CHECK (from_friend <> to_friend),
  CHECK ((status IN ('pending_confirm', 'confirmed')) = (text IS NOT NULL)),
  CHECK (status <> 'pending_confirm' OR confirmed_at IS NULL),
  CHECK (status NOT IN ('confirmed', 'sent') OR (confirmed_at IS NOT NULL AND send_after IS NOT NULL)),
  CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
  CHECK (status <> 'sent' OR (message_id IS NOT NULL AND reply_until IS NOT NULL)),
  CHECK ((status IN ('cancelled', 'expired')) = (closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS relays_due_idx ON marong.relays (send_after) WHERE status = 'confirmed';
CREATE INDEX IF NOT EXISTS relays_to_idx ON marong.relays (to_friend, sent_at) WHERE status = 'sent';
CREATE INDEX IF NOT EXISTS relays_pending_idx ON marong.relays (created_at) WHERE status = 'pending_confirm';

-- TBL-119 chat_cards (CTX-008, CTX-010, CTX-011) ← SPEC-192, SPEC-193, SPEC-196, SPEC-197, SPEC-212, SPEC-231, SPEC-238, SPEC-241 | terms: TERM-041, TERM-045, TERM-047, TERM-062
-- A choice card the code attaches to a reply (SCR-123, Discord buttons card:{kind}:{value}:{id}, Kakao numbers).
-- Labels are code constants per kind and the variable parts are ids or enum values, so no friend text is stored.
-- The first press or matching word answers it (UPDATE … WHERE status = 'open'); a second press finds it answered.
CREATE TABLE IF NOT EXISTS marong.chat_cards (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id      bigint NOT NULL REFERENCES marong.friends (id),
  kind           text NOT NULL CHECK (kind IN ('card_question', 'card_draft', 'card_proposal', 'ask_support',
                                               'memory_ok', 'relay_confirm', 'call_confirm')),
  step           smallint CHECK (step BETWEEN 1 AND 3),             -- card_question: which of the three
  field          text CHECK (field IN ('support', 'advice', 'honesty', 'lead')),  -- card_proposal
  value          text,                                              -- card_proposal: the proposed value
  memory_item_id bigint REFERENCES marong.memory_items (id),        -- memory_ok
  sensitive      text CHECK (sensitive IN ('health', 'mental', 'sex', 'money', 'politics', 'religion', 'romance')),
  relay_id       bigint REFERENCES marong.relays (id),              -- relay_confirm
  room_key       text NOT NULL REFERENCES marong.rooms (room_key),  -- where it was shown
  message_id     bigint REFERENCES marong.messages (id),            -- the reply that carried it
  status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'expired', 'replaced')),
  answer         text CHECK (char_length(answer) BETWEEN 1 AND 20), -- the chosen value
  answered_via   text CHECK (answered_via IN ('button', 'text', 'screen')),
  answered_at    timestamptz,
  expires_at     timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'card_question') = (step IS NOT NULL)),
  CHECK ((kind = 'card_proposal') = (field IS NOT NULL AND value IS NOT NULL)),
  CHECK ((kind = 'memory_ok') = (memory_item_id IS NOT NULL AND sensitive IS NOT NULL)),
  CHECK ((kind = 'relay_confirm') = (relay_id IS NOT NULL)),
  CHECK ((status = 'answered') = (answer IS NOT NULL AND answered_at IS NOT NULL AND answered_via IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS chat_cards_one_open_idx ON marong.chat_cards (friend_id, kind)
  WHERE status = 'open' AND kind IN ('card_question', 'card_draft', 'card_proposal', 'ask_support', 'call_confirm');
CREATE UNIQUE INDEX IF NOT EXISTS chat_cards_item_idx ON marong.chat_cards (memory_item_id)
  WHERE status = 'open' AND kind = 'memory_ok';
CREATE UNIQUE INDEX IF NOT EXISTS chat_cards_relay_idx ON marong.chat_cards (relay_id)
  WHERE status = 'open' AND kind = 'relay_confirm';
CREATE INDEX IF NOT EXISTS chat_cards_recent_idx ON marong.chat_cards (friend_id, kind, created_at DESC);

-- TBL-121 proactive_turns (CTX-009) ← SPEC-209, SPEC-213, SPEC-214, SPEC-215, SPEC-216, SPEC-218, SPEC-219, SPEC-220, SPEC-221, SPEC-222, SPEC-223 | terms: TERM-048, TERM-049, TERM-050, TERM-051, TERM-052, TERM-053, TERM-056, TERM-057, TERM-079
-- The gate's result for one slot: sent or skipped with a reason, never the text (SPEC-219). A friend target is a
-- friend; a group room without a friend is a room. One row per target, slot and mode, so the shadow graph and the live
-- graph can both write for the same slot. The legacy path keeps writing meta.slot on its message only.
CREATE TABLE IF NOT EXISTS marong.proactive_turns (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id     bigint REFERENCES marong.friends (id),
  room_key      text REFERENCES marong.rooms (room_key),            -- group room target without a friend
  slot_start    timestamptz NOT NULL,
  day           date NOT NULL,                                      -- Korean date of the slot
  mode          text NOT NULL CHECK (mode IN ('shadow', 'on')),
  decision      text NOT NULL CHECK (decision IN ('sent', 'skip')),
  reason        text CHECK (reason IN ('loop', 'care', 'schedule', 'interest', 'topic', 'daily')),
  skip_reason   text CHECK (skip_reason IN ('no_candidate', 'below_threshold', 'check_failed', 'write_failed',
                                            'send_failed', 'quiet', 'crisis', 'body', 'backoff', 'late')),
  score         smallint CHECK (score BETWEEN -1 AND 8),
  source_key    text CHECK (source_key ~ '^(loop|item|schedule|safety|topic):[0-9a-z/-]{1,60}$'),  -- same matter once
  grade         smallint CHECK (grade BETWEEN 1 AND 3),             -- lock screen grade (3.17)
  channel       text CHECK (channel IN ('kakao', 'discord', 'app')),
  message_id    bigint REFERENCES marong.messages (id),
  pending_state text NOT NULL DEFAULT 'none' CHECK (pending_state IN ('none', 'open', 'used', 'expired')),
  answered_2h   boolean,                                            -- NULL until known
  answered_24h  boolean,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (friend_id IS NOT NULL OR room_key IS NOT NULL),
  CHECK ((decision = 'skip') = (skip_reason IS NOT NULL)),
  CHECK (decision = 'skip' OR (reason IS NOT NULL AND grade IS NOT NULL)),
  CHECK (mode = 'on' OR message_id IS NULL),                         -- shadow never sends
  CHECK (pending_state = 'none' OR (decision = 'sent' AND grade = 3))
);
CREATE UNIQUE INDEX IF NOT EXISTS proactive_turns_slot_idx
  ON marong.proactive_turns ((COALESCE('f' || friend_id::text, 'r' || room_key)), slot_start, mode);
CREATE INDEX IF NOT EXISTS proactive_turns_day_idx ON marong.proactive_turns (friend_id, day) WHERE decision = 'sent';
CREATE INDEX IF NOT EXISTS proactive_turns_source_idx ON marong.proactive_turns (friend_id, source_key)
  WHERE decision = 'sent' AND source_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS proactive_turns_answer_idx ON marong.proactive_turns (friend_id, created_at)
  WHERE decision = 'sent' AND answered_24h IS NULL;

-- TBL-122 proactive_drafts (CTX-009) ← SPEC-218, SPEC-222 | terms: TERM-057
-- What AI-15 wrote for a slot, so the graph state keeps ids only and a restart can still send (3.18). first is the
-- message to send and is emptied once sent; later is the pending topic for the next 1:1 reply, emptied when used or
-- after 24 hours.
CREATE TABLE IF NOT EXISTS marong.proactive_drafts (
  turn_id     bigint PRIMARY KEY REFERENCES marong.proactive_turns (id),
  first_text  text CHECK (char_length(first_text) BETWEEN 1 AND 500),
  later_text  text CHECK (char_length(later_text) BETWEEN 1 AND 300),
  later_until timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  emptied_at  timestamptz,                                          -- both texts gone
  CHECK ((later_text IS NULL) OR (later_until IS NOT NULL)),
  CHECK (emptied_at IS NULL OR (first_text IS NULL AND later_text IS NULL))
);
CREATE INDEX IF NOT EXISTS proactive_drafts_later_idx ON marong.proactive_drafts (later_until) WHERE later_text IS NOT NULL;

-- TBL-127 memory_jobs (CTX-011) ← SPEC-224, SPEC-225, SPEC-235 | terms: TERM-070, TERM-065
-- One job row per friend and source. text jobs are run by the bot (messages after watermark), call jobs by the call
-- organizer (the calls listed), so transcripts never reach the bot role. A worker takes a due row with
-- FOR UPDATE SKIP LOCKED, sets a new token and a ten-minute lease, and applies ops only while the token is unchanged.
CREATE TABLE IF NOT EXISTS marong.memory_jobs (
  friend_id    bigint NOT NULL REFERENCES marong.friends (id),
  source       text NOT NULL CHECK (source IN ('text', 'call')),
  due_at       timestamptz,                                         -- NULL: nothing waiting
  watermark    bigint NOT NULL DEFAULT 0 CHECK (watermark >= 0),    -- text: last marong.messages id done
  calls        uuid[] NOT NULL DEFAULT '{}',                        -- call: calls waiting to be read
  token        uuid,
  lease_until  timestamptz,
  attempts     smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),  -- AI-16 failures in a row
  last_outcome text CHECK (last_outcome IN ('ok', 'rejected', 'ai_error', 'token_lost', 'skipped')),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (friend_id, source),
  CHECK ((token IS NULL) = (lease_until IS NULL)),
  CHECK (source = 'call' OR calls = '{}'),
  CHECK (source = 'text' OR watermark = 0)
);
CREATE INDEX IF NOT EXISTS memory_jobs_due_idx ON marong.memory_jobs (source, due_at) WHERE due_at IS NOT NULL;

-- TBL-128 forget_marks (CTX-011) ← SPEC-230, SPEC-233, SPEC-234, SPEC-242 | terms: TERM-071, TERM-069
-- What one forget touched outside the memory tables (3.20). A message or call turn is 'forgotten' for good: every
-- reader leaves it out (recent talk, search, summaries, diary material, sheet, proactive material, memory jobs, call
-- recall). A summary or note is 'hidden' until AI-19 rewrites it: a note or shared note gets a new row (the latest
-- row is the current one) named in replaced_by; a summary keeps the rewrite here (summaries allow one row per range).
-- After three failed rewrites a summary is 'dropped' and a note gets an empty new row.
-- The call server reads call_turn marks and sets call.turns.forgotten_at and its own exclusions.
CREATE TABLE IF NOT EXISTS marong.forget_marks (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  forget_id   bigint NOT NULL REFERENCES marong.memory_forgets (id),
  friend_id   bigint NOT NULL REFERENCES marong.friends (id),
  target_type text NOT NULL CHECK (target_type IN ('message', 'call_turn', 'summary', 'note', 'shared_note')),
  target_id   bigint NOT NULL,
  state       text NOT NULL CHECK (state IN ('forgotten', 'hidden', 'rewritten', 'dropped')),
  replacement text CHECK (char_length(replacement) BETWEEN 1 AND 4000),  -- summary rewrite
  replaced_by bigint,                                                -- new notes or shared_notes row
  attempts    smallint NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (target_type, target_id),
  CHECK ((target_type IN ('message', 'call_turn')) = (state = 'forgotten')),
  CHECK ((replacement IS NOT NULL) = (target_type = 'summary' AND state = 'rewritten')),
  CHECK ((replaced_by IS NOT NULL) = (target_type IN ('note', 'shared_note') AND state IN ('rewritten', 'dropped')))
);
CREATE INDEX IF NOT EXISTS forget_marks_friend_idx ON marong.forget_marks (friend_id, target_type);
CREATE INDEX IF NOT EXISTS forget_marks_hidden_idx ON marong.forget_marks (updated_at) WHERE state = 'hidden';

-- TBL-130 watches (CTX-010) ← SPEC-205, SPEC-237, SPEC-241 | terms: TERM-060, TERM-059
-- "Call me when I say I'm off work": a condition in the friend's own words, fired only by a turn whose speaker is that
-- friend. Three open per friend at most (bot counts under the friend lock); the condition is emptied when it ends.
CREATE TABLE IF NOT EXISTS marong.watches (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id        bigint NOT NULL REFERENCES marong.friends (id),
  condition        text CHECK (char_length(condition) BETWEEN 1 AND 60),
  contact          text NOT NULL CHECK (contact IN ('call', 'text')),  -- 'text' when the app ring is not available
  until_at         timestamptz NOT NULL,                             -- default 24:00 KST that day, 7 days at most
  status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'fired', 'expired', 'cancelled')),
  request_key      text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 100),
  message_id       bigint REFERENCES marong.messages (id),           -- where it was asked
  fired_at         timestamptz,
  fired_message_id bigint REFERENCES marong.messages (id),           -- the friend message that met it
  ring_id          uuid REFERENCES marong.app_rings (id),            -- contact 'call'
  created_at       timestamptz NOT NULL DEFAULT now(),
  closed_at        timestamptz,
  UNIQUE (friend_id, request_key),
  CHECK ((status = 'open') = (condition IS NOT NULL)),
  CHECK ((status = 'open') = (closed_at IS NULL)),
  CHECK ((status = 'fired') = (fired_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS watches_same_idx ON marong.watches (friend_id, lower(condition)) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS watches_open_idx ON marong.watches (until_at) WHERE status = 'open';

-- TBL-132 call_texts (CTX-010, CTX-002) ← SPEC-239 | terms: TERM-059
-- A text the call model sends to the friend's 1:1 chat during a call. The call server adds the row and runs
-- NOTIFY marong_outbox; the bot sends it on the D18 route with meta.from_call and marks it. The text is emptied once
-- the row ends. The same request in one call is one row.
CREATE TABLE IF NOT EXISTS marong.call_texts (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id   bigint NOT NULL REFERENCES marong.friends (id),
  call_id     uuid NOT NULL,                     -- call.calls id, no FK: calls can be deleted (SPEC-020)
  request_key text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 100),
  text        text CHECK (char_length(text) BETWEEN 1 AND 1500),
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed')),
  via         text CHECK (via IN ('app', 'discord', 'kakao')),
  message_id  bigint REFERENCES marong.messages (id),
  error_code  text CHECK (error_code IN ('no_route', 'send_error', 'too_late')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  done_at     timestamptz,
  UNIQUE (call_id, request_key),
  CHECK ((status = 'queued') = (text IS NOT NULL)),
  CHECK ((status = 'queued') = (done_at IS NULL)),
  CHECK ((status = 'sent') = (message_id IS NOT NULL AND via IS NOT NULL)),
  CHECK ((status = 'failed') = (error_code IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS call_texts_queued_idx ON marong.call_texts (created_at) WHERE status = 'queued';

-- TBL-133 persona_ai_runs (CTX-008~013) ← SPEC-193, SPEC-199, SPEC-206, SPEC-212, SPEC-213, SPEC-218, SPEC-225, SPEC-230 | terms: none
-- One row per model call of AI-13~19, written once when the call ends. No prompt, answer, card values, memory ops or
-- friend text: numbers and labels only. Same columns as diary_ai_runs and call.ai_runs. AI-11 and AI-12 (stage 0)
-- stay in marong.messages.meta as today.
CREATE TABLE IF NOT EXISTS marong.persona_ai_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind               text NOT NULL CHECK (kind IN ('card_draft', 'instruction', 'gate_write', 'memory_ops', 'rewrite',
                                                   'crisis_judge', 'forget_rewrite')),  -- AI-13 ~ AI-19 in order
  friend_id          bigint REFERENCES marong.friends (id),
  ref_id             bigint,                   -- proactive turn, forget or chat card id, by kind
  trace_id           text NOT NULL,
  model              text NOT NULL,
  prompt_version     text NOT NULL,
  effort             text,
  thinking           text,
  sent_at            timestamptz NOT NULL,
  first_token_ms     integer CHECK (first_token_ms >= 0),
  total_ms           integer CHECK (total_ms >= 0),
  input_tokens       integer CHECK (input_tokens >= 0),
  output_tokens      integer CHECK (output_tokens >= 0),
  cache_read_tokens  integer CHECK (cache_read_tokens >= 0),
  cache_write_tokens integer CHECK (cache_write_tokens >= 0),
  cost_usd           numeric(10, 6) CHECK (cost_usd >= 0),
  outcome            text NOT NULL CHECK (outcome IN ('ok', 'error', 'timeout', 'limit', 'invalid', 'refused')),
  stop_reason        text,
  error_code         text,
  fallback           text                      -- what was used instead, e.g. default_card, skip, fallback_text
);
CREATE INDEX IF NOT EXISTS persona_ai_runs_sent_idx ON marong.persona_ai_runs (kind, sent_at);

-- TBL-134 persona_tool_calls (CTX-008, CTX-010, CTX-011) ← SPEC-195, SPEC-198, SPEC-202, SPEC-229, SPEC-230, SPEC-237, SPEC-238, SPEC-241 | terms: TERM-059, TERM-065
-- One row per call of a new model tool in text talk (card_update, memory_list, memory_forget, watch_add, watch_fire,
-- relay_add, relay_reply), written when the tool returns. Arguments are not kept (only their length): the target id
-- and the outcome are enough to audit the quote check (common rule 9). The model's tool call id makes a repeated
-- call return the first result (common rule 11). Calls in a call stay in call.delegations, as today.
CREATE TABLE IF NOT EXISTS marong.persona_tool_calls (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id   bigint NOT NULL REFERENCES marong.friends (id),
  room_key    text NOT NULL REFERENCES marong.rooms (room_key),
  message_id  bigint REFERENCES marong.messages (id),               -- the friend message of the turn
  tool        text NOT NULL CHECK (tool IN ('card_update', 'memory_list', 'memory_forget', 'watch_add', 'watch_fire',
                                            'relay_add', 'relay_reply')),
  request_key text NOT NULL CHECK (char_length(request_key) BETWEEN 1 AND 100),  -- the model's tool call id
  outcome     text NOT NULL CHECK (outcome IN ('ok', 'refused', 'invalid', 'none_matched', 'ask_which', 'error')),
  why         text CHECK (why IN ('quote_missing', 'other_friend', 'not_speaker', 'group_room', 'limit',
                                  'raise_needs_owner', 'unknown_receiver', 'not_known', 'share_off', 'too_long',
                                  'closed', 'db_error')),
  target_type text CHECK (target_type IN ('card', 'rule', 'memory_item', 'open_loop', 'forget', 'watch', 'relay')),
  target_id   bigint,
  arg_chars   smallint CHECK (arg_chars >= 0),                     -- length of the arguments, never their text
  total_ms    integer CHECK (total_ms >= 0),
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (friend_id, request_key),
  CHECK ((target_type IS NULL) = (target_id IS NULL)),
  CHECK (outcome IN ('ok', 'none_matched', 'ask_which') OR why IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS persona_tool_calls_friend_idx ON marong.persona_tool_calls (friend_id, created_at DESC);

-- D63 exception to "no DELETE": search vectors are rebuildable copies
-- (schema.sql), and a forgotten message must stop turning up in search (3.20 step 3). The function deletes only the
-- vectors of sources one forget marked, so the bot still cannot delete anything else.
CREATE OR REPLACE FUNCTION marong.forget_embeddings(p_forget bigint)
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
  WITH gone AS (
    DELETE FROM marong.embeddings e
     USING marong.forget_marks m
     WHERE m.forget_id = p_forget
       AND ((m.target_type = 'message' AND e.source_type = 'message')
         OR (m.target_type = 'summary' AND e.source_type = 'summary'))
       AND e.source_id = m.target_id
    RETURNING 1)
  SELECT count(*)::integer FROM gone
$$;
REVOKE ALL ON FUNCTION marong.forget_embeddings(bigint) FROM PUBLIC;

-- without a table: TERM-045 (a chat card kind), TERM-048 (messages with meta.slot), TERM-054 and TERM-055 (worked out
-- from messages and calls, stage 0), TERM-058 (marong/capabilities.py), TERM-062 (a chat card kind and the talk graph
-- interrupt), TERM-067 (a proactive reason), TERM-068 (built from memory items when a conversation opens),
-- TERM-069 (not stored, SPEC-233), TERM-075 (not stored), TERM-076 (logs only), TERM-077 (worked out per turn),
-- TERM-078 (built when a call opens)

GRANT SELECT, INSERT, UPDATE ON marong.friend_cards, marong.friend_rules, marong.custom_instructions,
  marong.preference_signals, marong.chat_cards, marong.safety_states, marong.proactive_turns, marong.proactive_drafts,
  marong.memory_items, marong.open_loops, marong.memory_jobs, marong.forget_marks, marong.watches, marong.relays
  TO marong;
GRANT SELECT, INSERT ON marong.memory_forgets, marong.persona_ai_runs, marong.persona_tool_calls TO marong;
GRANT SELECT, UPDATE ON marong.call_texts TO marong;
GRANT EXECUTE ON FUNCTION marong.forget_embeddings(bigint) TO marong;

-- The call server: reads what the call instruction needs (SPEC-194, 200, 240, 242), keeps the shared crisis state
-- (3.13), runs call memory jobs (SPEC-235), forgets from a call (SPEC-242) and queues texts (SPEC-239).
GRANT SELECT ON marong.friend_cards, marong.friend_rules, marong.custom_instructions TO marong_call;
GRANT SELECT, INSERT, UPDATE ON marong.safety_states, marong.memory_items, marong.open_loops, marong.memory_jobs,
  marong.forget_marks TO marong_call;
GRANT SELECT, INSERT ON marong.preference_signals, marong.memory_forgets, marong.call_texts, marong.persona_ai_runs
  TO marong_call;
GRANT EXECUTE ON FUNCTION marong.forget_embeddings(bigint) TO marong_call;
COMMIT;
