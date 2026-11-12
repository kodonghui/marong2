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

-- TBL-003 calls (CTX-002) ← SPEC-002, SPEC-003, SPEC-007~011, SPEC-017~020, SPEC-022~024 | terms: TERM-001, TERM-009, TERM-013, TERM-015
-- 규칙: 친구 한 명에 끝나지 않은 통화는 하나(calls_one_open_idx). 끝난 통화는 되돌리지 않는다.
-- 규칙: 끝난 통화만 정리 상태를 가진다(none 은 끝나기 전).
CREATE TABLE IF NOT EXISTS call.calls (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  caller_id             bigint NOT NULL REFERENCES call.callers (id) ON DELETE RESTRICT,
  status                text NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'resting', 'ended')),
  client_id             uuid NOT NULL,                       -- 지금 통화를 가진 화면(넘겨받기, SPEC-009)
  prompt_version        text NOT NULL,                       -- 지시문 틀 sha256 앞 12자(SPEC-004)
  started_at            timestamptz NOT NULL DEFAULT now(),
  last_beat_at          timestamptz NOT NULL DEFAULT now(),  -- 신호(SPEC-010)
  last_turn_at          timestamptz,                         -- 마지막 자막 조각 시각(쉬기 판단, SPEC-008)
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

-- TBL-004 segments (CTX-002) ← SPEC-003, SPEC-006~011, SPEC-023 | terms: TERM-002, TERM-010, TERM-011, TERM-012
-- 규칙: 통화 하나에 닫히지 않은 구간은 하나(segments_one_open_idx). 서버 전체 열린 구간 3개는 코드가 친구별 잠금 안에서 센다.
CREATE TABLE IF NOT EXISTS call.segments (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id           uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  mode              text NOT NULL CHECK (mode IN ('start', 'reconnect', 'wake', 'takeover')),
  client_id         uuid NOT NULL,
  state             text NOT NULL DEFAULT 'opening' CHECK (state IN ('opening', 'open', 'closed')),
  openai_session_id text UNIQUE,                            -- OpenAI 가 준 세션 id(open 부터)
  opened_at         timestamptz NOT NULL DEFAULT now(),
  closed_at         timestamptz,
  close_reason      text CHECK (close_reason IN ('user_hangup', 'close_requested', 'expired', 'content', 'remote_hangup',
                                                 'connection_lost', 'server_rest', 'takeover', 'beat_lost',
                                                 'budget_hard_stop', 'reconnect_limit', 'server_restart',
                                                 'sideband_failed', 'start_failed', 'unknown')),
  CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
  CHECK ((state = 'closed') = (close_reason IS NOT NULL)),
  CHECK (state = 'opening' OR state = 'closed' OR openai_session_id IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS segments_one_open_idx ON call.segments (call_id) WHERE state <> 'closed';
CREATE INDEX IF NOT EXISTS segments_call_idx ON call.segments (call_id, opened_at);

-- TBL-005 turns (CTX-004) ← SPEC-006, SPEC-012~014, SPEC-017, SPEC-019, SPEC-022 | terms: TERM-005
-- 원음은 두지 않는다(REQ-034). 줄이 열려 있는 동안 5초마다 content 를 이어 붙여 고친다(SPEC-006 3.2).
CREATE TABLE IF NOT EXISTS call.turns (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id    uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  segment_id uuid NOT NULL REFERENCES call.segments (id) ON DELETE CASCADE,
  seq        integer NOT NULL CHECK (seq >= 1),            -- 통화 안 순서
  role       text NOT NULL CHECK (role IN ('user', 'assistant')),
  content    text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 4000),
  started_at timestamptz NOT NULL,
  ended_at   timestamptz NOT NULL,
  UNIQUE (call_id, seq),
  CHECK (ended_at >= started_at)
);

-- TBL-006 cards (CTX-004) ← SPEC-017, SPEC-019, SPEC-024 | terms: TERM-006
-- 규칙: 통화 하나에 카드 하나(call_id 가 기본 키, 정리를 다시 해도 upsert).
CREATE TABLE IF NOT EXISTS call.cards (
  call_id        uuid PRIMARY KEY REFERENCES call.calls (id) ON DELETE CASCADE,
  summary        text NOT NULL CHECK (char_length(summary) BETWEEN 1 AND 400),
  decided        jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(decided) = 'array'),
  undecided      jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(undecided) = 'array'),
  todos          jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(todos) = 'array'),
  ask_next       jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(ask_next) = 'array'),
  truncated      boolean NOT NULL DEFAULT false,            -- 자막이 150,000자를 넘어 앞부분을 못 봄
  model          text NOT NULL,
  prompt_version text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- TBL-007 memories (CTX-004) ← SPEC-004, SPEC-013~015, SPEC-017, SPEC-019~021, SPEC-024 | terms: TERM-007
-- 규칙: 같은 통화에서 같은 내용은 한 줄(UNIQUE call_id, idem_key; 멱등 키 = sha256(통화 id + 정리한 content)).
-- 규칙: 대체된 기억(superseded)은 지시문·검색·목록에 쓰지 않는다. 대체한 기억이 지워지면 코드가 이전 기억을 다시 active 로 둔다.
CREATE TABLE IF NOT EXISTS call.memories (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caller_id     bigint NOT NULL REFERENCES call.callers (id) ON DELETE CASCADE,
  call_id       uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  source        text NOT NULL CHECK (source IN ('delegation', 'organize')),
  content       text NOT NULL CHECK (char_length(content) BETWEEN 2 AND 200),
  quote         text NOT NULL CHECK (char_length(quote) BETWEEN 1 AND 200),
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
-- 규칙: OpenAI 위임 id 하나는 한 번만 처리(UNIQUE).
CREATE TABLE IF NOT EXISTS call.delegations (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  call_id              uuid NOT NULL REFERENCES call.calls (id) ON DELETE CASCADE,
  segment_id           uuid NOT NULL REFERENCES call.segments (id) ON DELETE CASCADE,
  openai_delegation_id text NOT NULL UNIQUE,
  state                text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed', 'dropped')),
  intent               text CHECK (intent IN ('recall', 'remember', 'forget', 'time', 'other')),
  result               text CHECK (result IN ('found', 'not_found', 'saved', 'not_saved', 'forgotten', 'none_matched',
                                              'ask_which', 'time', 'refused', 'revised', 'timeout', 'queue_full')),
  target_memory_ids    bigint[] NOT NULL DEFAULT '{}',
  request_chars        smallint CHECK (request_chars >= 0),  -- 다시 만든 요청의 길이(내용은 두지 않음)
  created_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz,
  latency_ms           integer CHECK (latency_ms >= 0)
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
CREATE TABLE IF NOT EXISTS call.budget_events (
  month      date NOT NULL CHECK (extract(day FROM month) = 1),   -- UTC 달의 1일
  kind       text NOT NULL CHECK (kind IN ('warn', 'exhausted', 'hard_stop')),
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

RESET ROLE;
