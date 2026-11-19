-- 마롱이 저장소(Postgres 16 + pgvector). 슈퍼유저로 marong DB 에서 실행한다. 여러 번 실행해도 안전하다.
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d marong -f marong/schema.sql
-- 통합 앱 설치에는 이 기본 스키마 뒤에 통화 스키마와 기존 마이그레이션을 적용한다.
-- 통합 앱의 추가 표와 방 주인 이관은 marong/migrations/020_unified.sql에 있다.
-- 통화 계정 권한은 마지막에 marong/call/migrations/008_unified.sql을 적용한다.
-- 역할: marong_owner(로그인 불가, 표 주인) / marong(봇이 쓰는 계정. 같은 이름의 리눅스 계정으로 비밀번호 없이 접속).
-- 봇 계정에는 지우기(DELETE)와, 대화 원문·요약·메모를 고치는(UPDATE) 권한을 주지 않는다.
-- 그래서 채팅으로 무슨 말을 해도 기록은 지워지지 않는다. 지우기는 서버 관리자가 postgres 계정으로만 한다.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_owner') THEN
    CREATE ROLE marong_owner NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong') THEN
    CREATE ROLE marong LOGIN;
  END IF;
END
$$;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS marong AUTHORIZATION marong_owner;
SET ROLE marong_owner;

CREATE TABLE IF NOT EXISTS marong.meta (
  key   text PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO marong.meta (key, value) VALUES ('schema_version', '9')
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 채팅방. 채널채팅(1:1)도 방 하나로 친다.
CREATE TABLE IF NOT EXISTS marong.rooms (
  room_key   text PRIMARY KEY,                    -- 카카오 botGroupKey
  is_channel boolean NOT NULL DEFAULT false,      -- 채널채팅(1:1)이면 true, 단체·오픈·팀채팅이면 false
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen  timestamptz NOT NULL DEFAULT now()
);
-- 2: 선톡(마롱이가 먼저 말 걸기) 받기. 7 부터 관리자만 바꾼다(admin schedule <친구> on|off. 그 전에는 친구가 그만하라고 하면
-- 마롱이가 바꿨음)
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive boolean NOT NULL DEFAULT true;
-- 4: 요약(10턴)을 기다리지 않고 친구 메모를 먼저 고친 마지막 메시지 id. 이 뒤로 친구 말이 오면 메모를 다시 고침(memory.py note_due)
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS noted_id bigint NOT NULL DEFAULT 0;
-- 5: 이 방만의 선톡 일정(하루 횟수, 한국 시각 시작·끝 시). 비우면 .env 의 PROACTIVE_PER_DAY·PROACTIVE_HOURS.
-- 관리자가 admin schedule 로 정함(7 부터 친구 말로는 안 바뀜)
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_per_day smallint;
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_start smallint CHECK (proactive_start BETWEEN 0 AND 23);
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_end smallint CHECK (proactive_end BETWEEN 1 AND 24);
-- 6: 하루 횟수 1~24 → 1~48(config.py PER_DAY_MAX 와 같게). 표 버전 5 의 CHECK 는 Postgres 가 이름을 붙여서
-- 이름 대신 내용으로 찾아 모두 지우고 하나만 다시 건다(설치할 때마다 같은 결과)
DO $$
DECLARE c text;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid = 'marong.rooms'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%proactive_per_day%' LOOP
    EXECUTE format('ALTER TABLE marong.rooms DROP CONSTRAINT %I', c);
  END LOOP;
END
$$;
ALTER TABLE marong.rooms ADD CONSTRAINT rooms_proactive_per_day_check CHECK (proactive_per_day BETWEEN 1 AND 48);
-- 8: 단체방 선톡. 카카오가 2026-11-05 14:30 KST부터 1:1 방에 먼저 보내기를 막아서(사람 키 -876, 방 키 -880) 관리자가
-- 켠 단체방에도 보낸다(admin schedule <#방키> on). 기본 꺼짐(proactive 는 1:1 용이라 단체방도 true 로 남아 있음).
-- 일정은 1:1 과 같은 proactive_per_day·start·end
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS group_proactive boolean NOT NULL DEFAULT false;
-- 9: 기억 묶기. 관리자가 단체방을 한 친구의 1:1 방에 묶으면(admin merge <#방키> <친구>) 두 방이 기억(최근 대화·요약·메모·
-- 비슷한 예전 대화)을 같이 쓰고, 그 단체방 선톡은 그 친구에게 1:1 처럼 간다. 기록은 옮기지 않고 원래 방에 그대로 쌓으며
-- 읽을 때 묶인 방들을 함께 읽는다. 새 요약·메모는 1:1 방(memory_room) 쪽에 쌓는다. 1:1 이 막혀 친구 한 명과 마롱이만 있는
-- 단체방을 1:1 대신 쓰게 됨(2026-11-06 동희님 "데이터베이스 각각 합쳐주고, 기존처럼 작동하게 해줘")
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS memory_room text REFERENCES marong.rooms (room_key)
  CHECK (memory_room <> room_key);

-- 친구의 카카오 키 하나(같은 사람도 1:1 과 단체방에서 키가 다름). 이름은 본인이 알려 준 것만 저장한다(카카오가 이름을 주지 않음).
CREATE TABLE IF NOT EXISTS marong.people (
  user_key    text PRIMARY KEY,                   -- 카카오 botUserKey
  name        text,
  name_set_at timestamptz,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now()
);

-- 3: 친구 한 명(사람). 카카오는 같은 사람에게 1:1 과 단체방에서 다른 botUserKey 를 줘서, 키(people) 여럿을 친구 한 명으로
-- 묶는다. 이름을 알게 되면 새 친구로 묶고, 같은 이름 친구가 이미 있으면 묶지 않고 요청(requests)으로 남긴다(7. 이름만으로는
-- 같은 사람인지 몰라서). 관리자가 tools/admin.py link·unlink 로 묶거나 따로 둔다.
CREATE TABLE IF NOT EXISTS marong.friends (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name       text NOT NULL,                          -- 본인이 알려 준 이름(가장 최근)
  share      boolean NOT NULL DEFAULT true,          -- 이 친구 얘기를 다른 친구에게 해도 되는지(7 부터 관리자만 바꿈)
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE marong.people ADD COLUMN IF NOT EXISTS friend_id bigint REFERENCES marong.friends (id);

-- 3: 아는 사이. 같은 단체방에서 말한 친구끼리는 이 표에 없어도 아는 사이로 친다. 7 부터 관리자만 정한다(admin friendship).
-- 그 전에는 친구가 말해 주면 마롱이가 저장했다(told_by 가 그 친구).
CREATE TABLE IF NOT EXISTS marong.friendships (
  friend_a   bigint NOT NULL REFERENCES marong.friends (id),  -- 둘 중 작은 id
  friend_b   bigint NOT NULL REFERENCES marong.friends (id),  -- 둘 중 큰 id
  label      text,                                           -- 친구·회사 동기·동생 같은 관계
  told_by    bigint REFERENCES marong.friends (id),           -- 말해 준 친구(관리자가 정했으면 비움)
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (friend_a, friend_b),
  CHECK (friend_a < friend_b)
);
-- 7: 가까운 사이(연인·배우자·가족·절친). 서로 요즘 근황(shared_notes.close_content)까지 듣는다. 관리자만 정한다
-- (admin friendship <친구> <친구> <관계> close). 친구 말로는 정하지 않아서, 이 칸이 생기기 전에 저장된 사이도 아님으로 둔다.
ALTER TABLE marong.friendships ADD COLUMN IF NOT EXISTS close boolean NOT NULL DEFAULT false;

-- 7: 친구가 대화로 한 설정 요청(공유 켬·끔, 아는 사이, 키 묶기, 선톡 켬·끔·횟수). 설정은 관리자만 정해서 마롱이는 여기
-- 남기기만 한다(관리자가 시트에서 보고 admin share·friendship·link·schedule 로 정함). 한 번 쓰면 바꾸지 않는다.
CREATE TABLE IF NOT EXISTS marong.requests (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_key   text NOT NULL,                              -- 말한 키
  friend_id  bigint REFERENCES marong.friends (id),      -- 말한 친구(키가 아직 친구에 안 묶였으면 비움)
  room_key   text,                                       -- 말한 방(뒤 작업이 남긴 묶기 요청은 비움)
  kind       text NOT NULL CHECK (kind IN ('share_off', 'share_on', 'friendship', 'link', 'proactive_off', 'proactive_on',
                                           'proactive_less', 'proactive_more')),
  detail     jsonb NOT NULL DEFAULT '{}'::jsonb,         -- friendship: name·label·with(상대 친구 id), link: name,
                                                         -- proactive_less·more: per_day(친구가 말한 하루 횟수)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS requests_friend_idx ON marong.requests (friend_id, id);

-- 3: 다른 친구에게 해도 되는 얘기. 친구의 방별 메모(notes)를 걸러서 만든다. content 는 그 친구를 아는 친구 누구에게나 하는
-- 가벼운 얘기(취향·하는 일 같은 것), close_content(7)는 가까운 사이에게만 하는 요즘 근황(일·학교 사정, 요즘 기분 같은 것).
-- 새 줄을 쌓고 가장 최근 줄이 지금 것. 비어 있으면 나눌 얘기가 없음.
CREATE TABLE IF NOT EXISTS marong.shared_notes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  content    text NOT NULL,
  meta       jsonb NOT NULL DEFAULT '{}'::jsonb,          -- 거른 메모 id(note_ids)·거른 규칙(rules)·모델·토큰 수
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE marong.shared_notes ADD COLUMN IF NOT EXISTS close_content text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS shared_notes_friend_idx ON marong.shared_notes (friend_id, id);

-- 대화 원문. 한 번 쓰면 바꾸지 않는다.
CREATE TABLE IF NOT EXISTS marong.messages (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_key   text NOT NULL REFERENCES marong.rooms (room_key),
  user_key   text REFERENCES marong.people (user_key),   -- 보낸 친구. 마롱이 답은 비움
  role       text NOT NULL CHECK (role IN ('user', 'assistant')),
  content    text NOT NULL,
  kakao_id   text,                                        -- 카카오 메시지 id: 같은 메시지를 두 번 저장하지 않음
  reply_to   bigint REFERENCES marong.messages (id),     -- 마롱이 답이 어느 메시지에 대한 것인지(선톡은 비움)
  meta       jsonb NOT NULL DEFAULT '{}'::jsonb,          -- 모델·effort·stop_reason·토큰 수·전달 여부·선톡(proactive)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (room_key, kakao_id)
);
CREATE INDEX IF NOT EXISTS messages_room_idx ON marong.messages (room_key, id);
-- 3: 친구 키가 말한 방 찾기(아는 사이·키 묶기)
CREATE INDEX IF NOT EXISTS messages_user_idx ON marong.messages (user_key, room_key);

-- 방마다 대화 구간 요약(필받음 chat_summary 와 같은 생각: 일정 턴마다 한 개).
CREATE TABLE IF NOT EXISTS marong.summaries (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_key   text NOT NULL REFERENCES marong.rooms (room_key),
  first_id   bigint NOT NULL REFERENCES marong.messages (id),
  last_id    bigint NOT NULL REFERENCES marong.messages (id),
  content    text NOT NULL,
  meta       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (room_key, last_id)
);

-- 방 안에서 친구마다 기억해 둘 메모. 고치지 않고 새 줄을 쌓으며, 가장 최근 줄이 지금 메모다.
CREATE TABLE IF NOT EXISTS marong.notes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  room_key   text NOT NULL REFERENCES marong.rooms (room_key),
  user_key   text NOT NULL REFERENCES marong.people (user_key),
  content    text NOT NULL,
  summary_id bigint REFERENCES marong.summaries (id),     -- 이 메모를 만든 요약(요약 전에 먼저 고친 메모는 비움)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notes_room_idx ON marong.notes (room_key, user_key, id);

-- 검색 색인(임베딩). 원문에서 언제든 다시 만들 수 있다. 모델이 바뀌면 그 모델 이름으로 새로 쌓인다.
CREATE TABLE IF NOT EXISTS marong.embeddings (
  model       text NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('message', 'summary')),
  source_id   bigint NOT NULL,
  room_key    text NOT NULL,
  embedding   vector NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (model, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS embeddings_room_idx ON marong.embeddings (model, room_key);

GRANT USAGE ON SCHEMA marong TO marong;
GRANT SELECT ON marong.meta TO marong;
GRANT SELECT, INSERT, UPDATE ON marong.rooms, marong.people, marong.friends, marong.friendships TO marong;
GRANT SELECT, INSERT ON marong.messages, marong.summaries, marong.notes, marong.shared_notes, marong.embeddings,
  marong.requests TO marong;

-- Diary and listening-test tables. Keep aligned with migrations 016 and 017.
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

RESET ROLE;
