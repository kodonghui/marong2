-- 마롱이 저장소(Postgres 16 + pgvector). 슈퍼유저로 marong DB 에서 실행한다. 여러 번 실행해도 안전하다.
--   sudo -u postgres psql -v ON_ERROR_STOP=1 -d marong -f marong/schema.sql
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
INSERT INTO marong.meta (key, value) VALUES ('schema_version', '2')
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 채팅방. 채널채팅(1:1)도 방 하나로 친다.
CREATE TABLE IF NOT EXISTS marong.rooms (
  room_key   text PRIMARY KEY,                    -- 카카오 botGroupKey
  is_channel boolean NOT NULL DEFAULT false,      -- 채널채팅(1:1)이면 true, 단체·오픈·팀채팅이면 false
  first_seen timestamptz NOT NULL DEFAULT now(),
  last_seen  timestamptz NOT NULL DEFAULT now()
);
-- 2: 선톡(마롱이가 먼저 말 걸기) 받기. 친구가 그만하라고 하면 false(마롱이가 set_proactive 로 바꿈)
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive boolean NOT NULL DEFAULT true;

-- 친구. 이름은 본인이 알려 준 것만 저장한다(카카오가 이름을 주지 않음).
CREATE TABLE IF NOT EXISTS marong.people (
  user_key    text PRIMARY KEY,                   -- 카카오 botUserKey
  name        text,
  name_set_at timestamptz,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now()
);

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
  summary_id bigint REFERENCES marong.summaries (id),     -- 이 메모를 만든 요약
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
GRANT SELECT, INSERT, UPDATE ON marong.rooms, marong.people TO marong;
GRANT SELECT, INSERT ON marong.messages, marong.summaries, marong.notes, marong.embeddings TO marong;

RESET ROLE;
