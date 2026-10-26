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
INSERT INTO marong.meta (key, value) VALUES ('schema_version', '5')
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
-- 4: 요약(10턴)을 기다리지 않고 친구 메모를 먼저 고친 마지막 메시지 id. 이 뒤로 친구 말이 오면 메모를 다시 고침(memory.py note_due)
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS noted_id bigint NOT NULL DEFAULT 0;
-- 5: 이 방만의 선톡 일정(하루 횟수, 한국 시각 시작·끝 시). 비우면 .env 의 PROACTIVE_PER_DAY·PROACTIVE_HOURS.
-- 관리자가 admin schedule 로, 친구가 덜(더) 보내 달라고 하면 마롱이가 set_proactive 의 per_day 로 바꿈
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_per_day smallint CHECK (proactive_per_day BETWEEN 1 AND 24);
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_start smallint CHECK (proactive_start BETWEEN 0 AND 23);
ALTER TABLE marong.rooms ADD COLUMN IF NOT EXISTS proactive_end smallint CHECK (proactive_end BETWEEN 1 AND 24);

-- 친구의 카카오 키 하나(같은 사람도 1:1 과 단체방에서 키가 다름). 이름은 본인이 알려 준 것만 저장한다(카카오가 이름을 주지 않음).
CREATE TABLE IF NOT EXISTS marong.people (
  user_key    text PRIMARY KEY,                   -- 카카오 botUserKey
  name        text,
  name_set_at timestamptz,
  first_seen  timestamptz NOT NULL DEFAULT now(),
  last_seen   timestamptz NOT NULL DEFAULT now()
);

-- 3: 친구 한 명(사람). 카카오는 같은 사람에게 1:1 과 단체방에서 다른 botUserKey 를 줘서, 키(people) 여럿을 친구 한 명으로
-- 묶는다. 이름을 알게 되면 같은 이름 친구에 묶는다(store.py set_name). 잘못 묶이면 tools/admin.py link·unlink 로 고친다.
CREATE TABLE IF NOT EXISTS marong.friends (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name       text NOT NULL,                          -- 본인이 알려 준 이름(가장 최근)
  share      boolean NOT NULL DEFAULT true,          -- 가벼운 얘기를 이 친구를 아는 다른 친구에게 해도 되는지(본인이 끄면 false)
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE marong.people ADD COLUMN IF NOT EXISTS friend_id bigint REFERENCES marong.friends (id);

-- 3: 친구가 말해 준 아는 사이. 같은 단체방에서 말한 친구끼리는 이 표에 없어도 아는 사이로 친다.
CREATE TABLE IF NOT EXISTS marong.friendships (
  friend_a   bigint NOT NULL REFERENCES marong.friends (id),  -- 둘 중 작은 id
  friend_b   bigint NOT NULL REFERENCES marong.friends (id),  -- 둘 중 큰 id
  label      text,                                           -- 친구·회사 동기·동생 같은 관계(말해 준 대로)
  told_by    bigint REFERENCES marong.friends (id),           -- 말해 준 친구
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (friend_a, friend_b),
  CHECK (friend_a < friend_b)
);

-- 3: 다른 친구에게 해도 되는 가벼운 얘기(취향·하는 일 같은 것). 친구의 방별 메모(notes)를 걸러서 만든다.
-- 새 줄을 쌓고 가장 최근 줄이 지금 것. 비어 있으면 나눌 얘기가 없음.
CREATE TABLE IF NOT EXISTS marong.shared_notes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  friend_id  bigint NOT NULL REFERENCES marong.friends (id),
  content    text NOT NULL,
  meta       jsonb NOT NULL DEFAULT '{}'::jsonb,          -- 거른 메모 id(note_ids)·거른 규칙(rules)·모델·토큰 수
  created_at timestamptz NOT NULL DEFAULT now()
);
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
GRANT SELECT, INSERT ON marong.messages, marong.summaries, marong.notes, marong.shared_notes, marong.embeddings TO marong;

RESET ROLE;
