-- 마롱이 통화 기능 저장소(call 스키마). marong/schema.sql 다음에 슈퍼유저로 marong DB 에서 실행한다. 여러 번 실행해도 안전하다.
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d marong -f marong/call/schema.sql
-- 설계: docs/04-functional-spec/spec.md(SPEC), docs/05-erd/erd.md(그림), docs/01-domain/domain.md(CTX·TERM)
-- 역할: marong_call(통화 서버 계정. 같은 이름의 리눅스 계정으로 비밀번호 없이 접속).
--   카톡 봇 계정(marong)은 기록을 못 지우지만, 통화 기록은 현경님이 앱에서 보고 지울 수 있어야 해서(D5, REQ-041·042)
--   통화 서버 계정에는 call 스키마 안에서만 UPDATE·DELETE 를 준다. marong 스키마는 읽기만 한다.
-- without a table: TERM-016(sideband), TERM-017(통화 마롱이)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_owner') THEN
    RAISE EXCEPTION 'marong/schema.sql 을 먼저 실행해야 함(marong_owner 역할 없음)';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marong_call') THEN
    CREATE ROLE marong_call LOGIN;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS call AUTHORIZATION marong_owner;
-- LangGraph 체크포인트(AsyncPostgresSaver.setup()이 표를 만듦). 정리 그래프 thread 'call:<통화 id>'만 둔다(SPEC-017·020·022)
CREATE SCHEMA IF NOT EXISTS call_graph AUTHORIZATION marong_call;
SET ROLE marong_owner;

-- TBL-012 meta (CTX-002) ← SPEC-028 | terms: none
CREATE TABLE IF NOT EXISTS call.meta (
  key   text PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO call.meta (key, value) VALUES ('schema_version', '1')
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- TBL-001 callers (CTX-005) ← SPEC-001, SPEC-002, SPEC-024, SPEC-025 | terms: TERM-003
-- 규칙: 카톡 친구 한 명에 통화하는 친구는 하나(friend_id UNIQUE). 지금은 현경님 한 명.
CREATE TABLE IF NOT EXISTS call.callers (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL UNIQUE REFERENCES marong.friends (id) ON DELETE RESTRICT,
  enabled    boolean NOT NULL DEFAULT true,          -- 끄면 로그인해도 403 not_allowed
  created_at timestamptz NOT NULL DEFAULT now()
);

-- TBL-002 caller_logins (CTX-005) ← SPEC-001, SPEC-025 | terms: TERM-004
-- 규칙: 이메일 원문은 두지 않는다. 소문자로 바꾼 이메일의 sha256 과 가린 표시만 둔다(로그·화면·시트에 이메일 없음, REQ-055).
CREATE TABLE IF NOT EXISTS call.caller_logins (
  email_sha256 text PRIMARY KEY CHECK (email_sha256 ~ '^[0-9a-f]{64}$'),
  caller_id    bigint NOT NULL REFERENCES call.callers (id) ON DELETE CASCADE,
  email_hint   text NOT NULL CHECK (position('***' IN email_hint) > 0),  -- 예: a***@example.com
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- TBL-003 calls (CTX-002) ← SPEC-002~004, SPEC-007~011, SPEC-017~020, SPEC-022~024 | terms: TERM-001, TERM-009, TERM-013, TERM-015
-- 규칙: 친구 한 명에 끝나지 않은 통화는 하나(calls_one_open_idx). 끝난 통화는 되돌리지 않는다.
-- 규칙: 끝난 통화만 정리 상태를 가진다(none 은 끝나기 전).
-- 규칙: 목소리는 걸 때 설정(TBL-009)에서 읽어 두고 그 통화의 모든 구간에 쓴다(세션을 만든 뒤에는 못 바꿈, D16).
CREATE TABLE IF NOT EXISTS call.calls (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  caller_id             bigint NOT NULL REFERENCES call.callers (id) ON DELETE RESTRICT,
  status                text NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'resting', 'ended')),
  client_id             uuid NOT NULL,                       -- 지금 통화를 가진 화면(넘겨받기, SPEC-009)
  prompt_version        text NOT NULL,                       -- 지시문 틀 sha256 앞 12자(SPEC-004)
  voice                 text NOT NULL CHECK (char_length(voice) BETWEEN 1 AND 100),  -- 이 통화의 목소리(SPEC-004, D16)
  started_at            timestamptz NOT NULL DEFAULT now(),
  last_beat_at          timestamptz NOT NULL DEFAULT now(),  -- 신호(SPEC-010)
  last_marong_sound_at  timestamptz,                         -- 마롱이가 마지막으로 소리를 낸 시각(마롱이 자막 조각·출력 원음 이벤트 도착, 쉬기 판단, SPEC-008)
  ended_at              timestamptz,
  end_reason            text CHECK (end_reason IN ('hangup', 'beat_lost', 'reconnect_limit', 'budget_hard_stop', 'admin')),
  organize_status       text NOT NULL DEFAULT 'none'
                        CHECK (organize_status IN ('none', 'pending', 'running', 'done', 'skipped', 'failed')),
  organize_attempts     smallint NOT NULL DEFAULT 0 CHECK (organize_attempts BETWEEN 0 AND 3),
  organize_next_at      timestamptz,                         -- 다시 할 때(10초·60초·300초 뒤)
  organize_lease_until  timestamptz,                         -- 정리 작업자 임대(5분)
  organized_at          timestamptz,                         -- thread 를 7일 뒤 지울 기준(SPEC-022)
  transcript_deleted_at timestamptz,                         -- 180일 뒤 자막을 지운 때(SPEC-022)
  CHECK ((status = 'ended') = (ended_at IS NOT NULL)),
  CHECK ((status = 'ended') = (end_reason IS NOT NULL)),
  CHECK ((status = 'ended') = (organize_status <> 'none'))
);
CREATE UNIQUE INDEX IF NOT EXISTS calls_one_open_idx ON call.calls (caller_id) WHERE status <> 'ended';
CREATE INDEX IF NOT EXISTS calls_list_idx ON call.calls (caller_id, started_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS calls_beat_idx ON call.calls (last_beat_at) WHERE status <> 'ended';
CREATE INDEX IF NOT EXISTS calls_organize_idx ON call.calls (organize_next_at) WHERE organize_status IN ('pending', 'running');

-- TBL-004 segments (CTX-002) ← SPEC-003, SPEC-006~011, SPEC-023, SPEC-031 | terms: TERM-002, TERM-010, TERM-011, TERM-012, TERM-020
-- 규칙: 통화 하나에 닫히지 않은 구간은 하나(segments_one_open_idx). 서버 전체 열린 구간 3개는 코드가 친구별 잠금 안에서 센다.
-- 규칙: 미리 넘기기(renew)는 OpenAI 세션을 먼저 만든 뒤 한 트랜잭션으로 직전 구간을 닫고(renewed) 새 구간을 open 으로 넣는다(SPEC-031).
CREATE TABLE IF NOT EXISTS call.segments (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id           uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  mode              text NOT NULL CHECK (mode IN ('start', 'reconnect', 'wake', 'takeover', 'renew')),
  client_id         uuid NOT NULL,
  state             text NOT NULL DEFAULT 'opening' CHECK (state IN ('opening', 'open', 'closed')),
  openai_session_id text UNIQUE,                            -- OpenAI 가 준 세션 id(open 부터)
  expires_at        timestamptz,                            -- OpenAI 세션 만료 시각(session.started 의 expires_at, SPEC-031)
  opened_at         timestamptz NOT NULL DEFAULT now(),
  closed_at         timestamptz,
  close_reason      text CHECK (close_reason IN ('user_hangup', 'close_requested', 'expired', 'content', 'remote_hangup',
                                                 'connection_lost', 'server_rest', 'takeover', 'beat_lost',
                                                 'budget_hard_stop', 'reconnect_limit', 'server_restart',
                                                 'sideband_failed', 'start_failed', 'renewed', 'unknown')),
  CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
  CHECK ((state = 'closed') = (close_reason IS NOT NULL)),
  CHECK (state = 'opening' OR state = 'closed' OR openai_session_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS segments_one_open_idx ON call.segments (call_id) WHERE state <> 'closed';
CREATE INDEX IF NOT EXISTS segments_call_idx ON call.segments (call_id, opened_at);

-- TBL-005 turns (CTX-004) ← SPEC-006, SPEC-012~015, SPEC-017, SPEC-019, SPEC-021, SPEC-022 | terms: TERM-005
-- 원음은 두지 않는다(REQ-034). 줄이 열려 있는 동안 5초마다 content 를 이어 붙여 고친다(SPEC-006 3.2).
-- 잊기 표시(forgotten_at)가 있는 줄은 기억 찾기·통화 정리에 쓰지 않고, 통화 상세에는 보인다(SPEC-015·021, 기능 명세 3.7).
CREATE TABLE IF NOT EXISTS call.turns (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id    uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  segment_id uuid NOT NULL REFERENCES call.segments (id) ON DELETE CASCADE,
  seq        integer NOT NULL CHECK (seq >= 1),            -- 통화 안 순서
  role       text NOT NULL CHECK (role IN ('user', 'assistant')),
  content    text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 4000),
  started_at timestamptz NOT NULL,
  ended_at   timestamptz NOT NULL,
  forgotten_at timestamptz,                                -- 잊기 표시(기능 명세 3.7)
  UNIQUE (call_id, seq),
  CHECK (ended_at >= started_at)
);

-- TBL-006 cards (CTX-004) ← SPEC-004, SPEC-013, SPEC-015, SPEC-017, SPEC-019, SPEC-021, SPEC-024 | terms: TERM-006
-- 규칙: 통화 하나에 카드 하나(call_id 가 기본 키, 정리를 다시 해도 upsert).
-- 잊기: 잊은 얘기와 맞는 항목은 배열에서 지우고, 요약에 맞으면 forgotten_at 을 남겨 지시문·카톡 블록·기억 찾기에서 뺀다(기능 명세 3.7).
CREATE TABLE IF NOT EXISTS call.cards (
  call_id        uuid PRIMARY KEY REFERENCES call.calls (id) ON DELETE CASCADE,
  summary        text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 400),
  decided        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(decided) = 'array'),
  undecided      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(undecided) = 'array'),
  todos          jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(todos) = 'array'),
  ask_next       jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(ask_next) = 'array'),
  truncated      boolean NOT NULL DEFAULT false,            -- 자막이 150,000자를 넘어 앞부분을 못 봄
  forgotten_at   timestamptz,                               -- 잊기 표시(요약에 잊은 얘기가 있음)
  model          text NOT NULL,
  prompt_version text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- TBL-007 memories (CTX-004) ← SPEC-004, SPEC-013~015, SPEC-017, SPEC-019~022, SPEC-024 | terms: TERM-007
-- 규칙: 같은 통화에서 같은 내용은 한 줄(UNIQUE call_id, idem_key; 멱등 키 = sha256(통화 id + 정리한 content)).
-- 규칙: 대체된 기억(superseded)은 지시문·검색·목록에 쓰지 않는다.
-- 규칙: 기억 하나를 지우거나 잊으면(SPEC-015·021) 코드가 그 기억이 대체했던 이전 기억들(대체 사슬)도 함께 지운다.
--       이전 기억을 다시 active 로 두는 건 통화를 통째로 지울 때(SPEC-020)뿐이다.
CREATE TABLE IF NOT EXISTS call.memories (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caller_id     bigint NOT NULL REFERENCES call.callers (id) ON DELETE CASCADE,
  call_id       uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  source        text NOT NULL CHECK (source IN ('delegation', 'organize')),
  content       text NOT NULL CHECK (char_length(content) BETWEEN 2 AND 200),
  quote         text CHECK (quote IS NULL OR char_length(quote) BETWEEN 1 AND 200),  -- 현경님 말 그대로. 자막을 180일 뒤 지울 때 함께 비움(SPEC-022)
  turn_id       bigint REFERENCES call.turns (id) ON DELETE SET NULL,   -- 자막을 180일 뒤 지우면 비움
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
  superseded_by bigint REFERENCES call.memories (id) ON DELETE SET NULL,
  idem_key      text NOT NULL CHECK (idem_key ~ '^[0-9a-f]{64}$'),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (call_id, idem_key),
  CHECK (status = 'superseded' OR superseded_by IS NULL)
);
CREATE INDEX IF NOT EXISTS memories_caller_idx ON call.memories (caller_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS memories_superseded_idx ON call.memories (superseded_by) WHERE superseded_by IS NOT NULL;

-- TBL-008 delegations (CTX-003) ← SPEC-012~016 | terms: TERM-008
-- 위임(모델의 도구 호출) 기록. 말 내용은 두지 않고 길이만 둔다. 쓰거나 지운 기억 id 는 target_memory_ids.
-- 규칙: OpenAI 위임 id 하나는 한 번만 처리(UNIQUE). 서버 보조 판단(origin server, 기능 명세 3.6)은 위임 id 가 없다.
-- 규칙: 보조 판단과 같은 부탁인 모델 위임은 다시 쓰지 않고 same_as 로 그 줄을 가리킨다.
CREATE TABLE IF NOT EXISTS call.delegations (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id              uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  segment_id           uuid NOT NULL REFERENCES call.segments (id) ON DELETE CASCADE,
  origin               text NOT NULL DEFAULT 'model' CHECK (origin IN ('model', 'server')),
  openai_delegation_id text UNIQUE,
  same_as              bigint REFERENCES call.delegations (id) ON DELETE SET NULL,
  state                text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed', 'dropped')),
  intent               text CHECK (intent IN ('recall', 'remember', 'forget', 'time', 'other')),
  result               text CHECK (result IN ('found', 'not_found', 'saved', 'not_saved', 'forgotten', 'none_matched',
                                              'ask_which', 'time', 'refused', 'revised', 'timeout', 'queue_full')),
  target_memory_ids    bigint[] NOT NULL DEFAULT '{}',
  request_chars        smallint CHECK (request_chars >= 0),  -- 다시 만든 요청의 길이(내용은 두지 않음)
  created_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz,
  latency_ms           integer CHECK (latency_ms >= 0),
  CHECK ((origin = 'model') = (openai_delegation_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS delegations_call_idx ON call.delegations (call_id, created_at);

-- TBL-009 settings (CTX-006) ← SPEC-004, SPEC-023, SPEC-025 | terms: TERM-014
-- 관리 명령으로만 바꾼다. 월 예산(달러), 분당 요금(달러), 목소리.
CREATE TABLE IF NOT EXISTS call.settings (
  key        text PRIMARY KEY CHECK (key IN ('monthly_budget_usd', 'usd_per_minute', 'voice')),
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (key <> 'monthly_budget_usd' OR (jsonb_typeof(value) = 'number' AND (value)::numeric > 0
                                          AND (value)::numeric <= 10000)),
  CHECK (key <> 'usd_per_minute' OR (jsonb_typeof(value) = 'number' AND (value)::numeric > 0)),
  CHECK (key <> 'voice' OR jsonb_typeof(value) = 'string')
);
INSERT INTO call.settings (key, value) VALUES
  ('monthly_budget_usd', '150'::jsonb),
  ('usd_per_minute', '0.05'::jsonb),
  ('voice', '"noeul"'::jsonb)
  ON CONFLICT (key) DO NOTHING;

-- TBL-010 budget_events (CTX-006) ← SPEC-023, SPEC-025, SPEC-026 | terms: TERM-014
-- 규칙: 달마다 종류마다 한 줄(처음 넘었을 때만). 예산을 올렸다 내려도 다시 쌓이지 않는다.
-- provider_limit: 서버보다 OpenAI 지출 한도(429)가 먼저 막은 달(SPEC-023).
CREATE TABLE IF NOT EXISTS call.budget_events (
  month      date NOT NULL CHECK (extract(day FROM month) = 1),   -- UTC 달의 1일
  kind       text NOT NULL CHECK (kind IN ('warn', 'exhausted', 'hard_stop', 'provider_limit')),
  spent_usd  numeric(10, 2) NOT NULL CHECK (spent_usd >= 0),
  budget_usd numeric(10, 2) NOT NULL CHECK (budget_usd > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (month, kind)
);

-- TBL-011 ai_runs (CTX-002, CTX-003, CTX-004) ← SPEC-003, SPEC-006, SPEC-012, SPEC-013, SPEC-017, SPEC-022, SPEC-023, SPEC-026, SPEC-030 | terms: none
-- 모델 호출마다 한 줄(05단계 규칙). 프롬프트·답·자막·이메일은 두지 않는다. 음성 구간은 구간마다 한 줄이고 usage_seconds 가
-- 이번 달 예산 계산의 원본이다(SPEC-023). 통화를 지워도 통화 id 만 비우고 남겨서 예산이 줄지 않는다(SPEC-020).
-- 위임(도구 호출)의 이름·결과·대상 id 는 TBL-008 이 기록한다.
-- 느낌 고르기(mood_classify)는 마롱이 문장 하나마다 한 줄이고, 문장과 고른 느낌은 두지 않는다(SPEC-030).
CREATE TABLE IF NOT EXISTS call.ai_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind               text NOT NULL CHECK (kind IN ('live_session', 'delegate_classify', 'recall_compose', 'organize', 'mood_classify')),
  call_id            uuid REFERENCES call.calls (id) ON DELETE SET NULL,
  segment_id         uuid REFERENCES call.segments (id) ON DELETE SET NULL,
  delegation_id      bigint REFERENCES call.delegations (id) ON DELETE SET NULL,
  segment_ref        uuid,                                 -- 음성 구간 id(통화를 지워도 남는 중복 막기 키, FK 아님)
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
  usage_seconds      numeric(10, 1) CHECK (usage_seconds >= 0),
  usage_estimated    boolean NOT NULL DEFAULT false,
  outcome            text NOT NULL CHECK (outcome IN ('ok', 'error', 'timeout', 'limit', 'invalid')),
  stop_reason        text,                                 -- 모델의 stop_reason, 음성은 구간 닫힘 이유
  error_code         text,
  fallback           text,                                 -- 대신 쓴 답(예: not_found 지시)
  CHECK (kind <> 'live_session' OR (usage_seconds IS NOT NULL AND segment_ref IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_runs_live_segment_idx ON call.ai_runs (segment_ref) WHERE kind = 'live_session';
CREATE INDEX IF NOT EXISTS ai_runs_sent_idx ON call.ai_runs (kind, sent_at);

-- 통화 서버 계정: call 스키마 읽기·쓰기, marong 스키마는 통화 지시문·기억 찾기에 쓰는 표만 읽기(SPEC-004, SPEC-013).
GRANT USAGE ON SCHEMA call TO marong_call;
GRANT SELECT ON call.meta TO marong_call;
GRANT SELECT, INSERT, UPDATE, DELETE ON call.callers, call.caller_logins, call.calls, call.segments, call.turns,
  call.cards, call.memories, call.delegations, call.ai_runs TO marong_call;
GRANT SELECT, INSERT, UPDATE ON call.settings TO marong_call;
GRANT SELECT, INSERT ON call.budget_events TO marong_call;
GRANT USAGE ON SCHEMA marong TO marong_call;
GRANT SELECT ON marong.rooms, marong.people, marong.friends, marong.friendships, marong.messages, marong.summaries,
  marong.notes, marong.shared_notes TO marong_call;

-- 카톡 봇 계정: '# 최근 통화'(SPEC-024)와 시트 '통화' 탭(SPEC-026)에 필요한 것만 읽기. 자막(turns)은 주지 않는다.
GRANT USAGE ON SCHEMA call TO marong;
GRANT SELECT ON call.callers, call.cards, call.memories, call.settings, call.budget_events TO marong;
GRANT SELECT (id, caller_id, status, started_at, ended_at, end_reason, organize_status) ON call.calls TO marong;
GRANT SELECT (kind, call_id, sent_at, usage_seconds, usage_estimated, outcome) ON call.ai_runs TO marong;

-- Call-cost tables. Migration 007 also extends the segment constraints and reporting views.
-- TBL-110 live_prices (CTX-006) ← SPEC-170, SPEC-172, SPEC-173, SPEC-180 | terms: TERM-035
-- Rule: rows are only added. The price of usage is the row of the same model with the latest starts_at at or before
-- the time the usage was received; dollars already priced never change (REQ-187). US dollars per 1M tokens.
CREATE TABLE IF NOT EXISTS call.live_prices (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  model                 text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 100),
  starts_at             timestamptz NOT NULL,
  text_in               numeric(10, 4) NOT NULL CHECK (text_in >= 0),
  audio_in              numeric(10, 4) NOT NULL CHECK (audio_in >= 0),
  image_in              numeric(10, 4) NOT NULL CHECK (image_in >= 0),
  text_out              numeric(10, 4) NOT NULL CHECK (text_out >= 0),
  audio_out             numeric(10, 4) NOT NULL CHECK (audio_out >= 0),
  search_per_1000       numeric(10, 4) NOT NULL DEFAULT 0 CHECK (search_per_1000 >= 0),
  search_free_per_month integer NOT NULL DEFAULT 0 CHECK (search_free_per_month >= 0),
  checked_on            date NOT NULL,                     -- the cost view asks for a recheck after 90 days (REQ-188)
  source                text NOT NULL CHECK (char_length(source) BETWEEN 1 AND 200),
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (model, starts_at)
);
INSERT INTO call.live_prices (model, starts_at, text_in, audio_in, image_in, text_out, audio_out, search_per_1000,
                              search_free_per_month, checked_on, source) VALUES
  ('gemini-3.8-live', '2026-07-01 00:00:00+00', 0.75, 3.00, 1.00, 4.50, 12.00, 14, 5000, '2026-11-16',
   'Vertex AI pricing page, regional endpoint'),
  ('gemini-3.8-flash', '2026-11-01 00:00:00+00', 0.75, 0.75, 0.75, 3.75, 3.75, 0, 0, '2026-11-16',
   'Gemini API pricing page; Vertex value to confirm'),
  ('gemini-3.8-flash', '2027-01-01 00:00:00+00', 1.50, 1.50, 1.50, 7.50, 7.50, 0, 0, '2026-11-16',
   'Gemini API pricing page; Vertex value to confirm')
  ON CONFLICT (model, starts_at) DO NOTHING;

-- TBL-111 live_tunings (CTX-002) ← SPEC-177, SPEC-178, SPEC-179, SPEC-180 | terms: TERM-037
-- Rule: one name, one set of values; rows are only added. A segment reads the current tuning when it opens and keeps
-- it (REQ-189). Voice, language and instructions are not tuning values. Ranges and defaults: functional spec 3.3.
CREATE TABLE IF NOT EXISTS call.live_tunings (
  name                text PRIMARY KEY CHECK (name ~ '^[a-z0-9-]{2,40}$'),
  compression_trigger integer NOT NULL CHECK (compression_trigger BETWEEN 2048 AND 32768),
  compression_target  integer NOT NULL CHECK (compression_target >= 1024 AND compression_target * 2 <= compression_trigger),
  vad_silence_ms      integer NOT NULL CHECK (vad_silence_ms BETWEEN 300 AND 2000),
  vad_prefix_ms       integer NOT NULL CHECK (vad_prefix_ms BETWEEN 0 AND 500),
  max_output_tokens   integer NOT NULL CHECK (max_output_tokens BETWEEN 256 AND 2048),
  seed_call_memories  smallint NOT NULL CHECK (seed_call_memories BETWEEN 0 AND 30),
  web_quiet_mic       boolean NOT NULL,
  quiet_rms           numeric(5, 4) NOT NULL CHECK (quiet_rms BETWEEN 0.005 AND 0.05),
  text_handoff        boolean NOT NULL,
  handoff_tokens      integer NOT NULL CHECK (handoff_tokens BETWEEN 3000 AND 30000),
  handoff_chars       integer NOT NULL CHECK (handoff_chars BETWEEN 1000 AND 8000),
  created_at          timestamptz NOT NULL DEFAULT now()
);
INSERT INTO call.live_tunings (name, compression_trigger, compression_target, vad_silence_ms, vad_prefix_ms,
                               max_output_tokens, seed_call_memories, web_quiet_mic, quiet_rms, text_handoff,
                               handoff_tokens, handoff_chars)
  VALUES ('base-20261116', 8192, 4096, 700, 100, 1024, 30, false, 0.018, false, 7000, 4000)
  ON CONFLICT (name) DO NOTHING;
-- TBL-112 live_usage (CTX-006) ← SPEC-169, SPEC-170, SPEC-171, SPEC-173, SPEC-180, SPEC-181 | terms: TERM-034
-- One row per turn the engine reported (kind turn), saved by the segment's writer every 2 s and when it closes.
-- Rule: (segment_ref, seq) is saved once. Rows outlive the call: deleting a call clears call_id and segment_id and keeps
-- segment_ref and the dollars; it first adds one estimate row for a segment that is counted as an estimate, so this
-- month's cost does not drop (SPEC-171).
CREATE TABLE IF NOT EXISTS call.live_usage (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind            text NOT NULL DEFAULT 'turn' CHECK (kind IN ('turn', 'estimate')),
  call_id         uuid REFERENCES call.calls (id) ON DELETE SET NULL,
  segment_id      uuid REFERENCES call.segments (id) ON DELETE SET NULL,
  segment_ref     uuid NOT NULL,                           -- the segment id, kept after the call is deleted (no key)
  seq             integer NOT NULL CHECK (seq >= 0),       -- order in the segment; 0 for the estimate row
  received_at     timestamptz NOT NULL,                    -- an estimate row carries the segment's open time
  entrypoint      text NOT NULL CHECK (entrypoint IN ('web', 'discord')),
  tuning          text REFERENCES call.live_tunings (name) ON DELETE RESTRICT,
  model           text NOT NULL,
  text_in         integer NOT NULL DEFAULT 0 CHECK (text_in >= 0),
  audio_in        integer NOT NULL DEFAULT 0 CHECK (audio_in >= 0),
  image_in        integer NOT NULL DEFAULT 0 CHECK (image_in >= 0),       -- image and video
  tool_in         integer NOT NULL DEFAULT 0 CHECK (tool_in >= 0),
  cached_in       integer NOT NULL DEFAULT 0 CHECK (cached_in >= 0),      -- part of the input, priced as input for now
  text_out        integer NOT NULL DEFAULT 0 CHECK (text_out >= 0),
  audio_out       integer NOT NULL DEFAULT 0 CHECK (audio_out >= 0),
  thoughts        integer NOT NULL DEFAULT 0 CHECK (thoughts >= 0),
  total_tokens    integer NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),   -- as reported, for checking the split
  searches        smallint NOT NULL DEFAULT 0 CHECK (searches >= 0),      -- priced per month, not in usd
  details_missing boolean NOT NULL DEFAULT false,          -- no modality details: counted as audio (details_missing)
  values_fixed    boolean NOT NULL DEFAULT false,          -- a value was not a number or negative, saved as 0 (usage_bad)
  seconds         numeric(10, 1) CHECK (seconds >= 0),     -- estimate row: the segment's length
  price_id        bigint REFERENCES call.live_prices (id) ON DELETE RESTRICT,
  usd             numeric(12, 6) CHECK (usd >= 0),         -- turn row without a matching price: NULL (unpriced)
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (segment_ref, seq),
  CHECK (kind <> 'turn' OR (seq >= 1 AND seconds IS NULL AND (price_id IS NULL) = (usd IS NULL))),
  CHECK (kind <> 'estimate' OR (seq = 0 AND seconds IS NOT NULL AND price_id IS NULL AND usd IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS live_usage_received_idx ON call.live_usage (received_at);
CREATE INDEX IF NOT EXISTS live_usage_call_idx ON call.live_usage (call_id) WHERE call_id IS NOT NULL;

-- TBL-113 live_counters (CTX-006) ← SPEC-169, SPEC-170, SPEC-174, SPEC-180 | terms: none
-- Counts the cost view shows per UTC month and entry point: usage dropped from a full queue, usage lost after the
-- last retry, and budget checks that could not count. Each process keeps them in memory and adds them on its next
-- successful write, so a count can arrive late; counts still in memory when a process stops are only in its log.
CREATE TABLE IF NOT EXISTS call.live_counters (
  month      date NOT NULL CHECK (extract(day FROM month) = 1),
  entrypoint text NOT NULL CHECK (entrypoint IN ('web', 'discord')),
  name       text NOT NULL CHECK (name IN ('usage_dropped', 'usage_lost', 'budget_unknown')),
  count      integer NOT NULL DEFAULT 0 CHECK (count >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (month, entrypoint, name)
);

GRANT SELECT, INSERT ON call.live_prices, call.live_tunings, call.live_usage TO marong_call;
GRANT SELECT, INSERT, UPDATE ON call.live_counters TO marong_call;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA call TO marong_call;

RESET ROLE;
