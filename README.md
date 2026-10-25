# 마롱이

동희와 친구들이 카카오톡에서 같이 수다 떠는 챗봇이에요. 반말로 이름을 불러 주고, 예전에 나눈 얘기를 기억해서 이어 가요.

- 모델: Claude Haiku 5.5, 답장 effort `xhigh` (요약은 `low`)
- 서버: 싱가포르 OVH(`ko-family`)의 `/opt/marong`, systemd 서비스 `marong`
- 저장: 같은 서버의 Postgres 16 + pgvector(`marong` DB). 대화 원문·요약·친구별 기억 메모·임베딩
- 카카오: 앱 1620899(이름 '마롱이')의 카카오톡 봇. 게이트웨이(웹소켓)로 메시지를 받고 콜백 API 로 답해요

## 마롱이가 하는 일

1. 친구가 말을 걸면 메시지를 저장하고, 기억을 모아서 Claude 에게 보내요.
   - 최근 대화 원문 10턴
   - 예전 대화 요약 최근 3개와 친구별 기억 메모(10턴마다 뒤에서 만들어요)
   - 지금 말과 비슷한 예전 대화(임베딩 검색, 같은 방 안에서만)
2. 카카오는 이름을 알려 주지 않아서, 처음 만난 친구에게는 이름을 물어보고 `set_name` 도구로 저장해요. 그다음부터는 "동희야"처럼 이름으로 불러요.
3. 답은 빈 줄마다 말풍선이 나뉘어요(최대 3개).
4. 기억은 방마다 따로예요. 1:1 에서 한 얘기는 단체방에서 그대로 보이지 않아요.
5. 친구들끼리는 마롱이를 같이 알아요. 아는 사이인 친구에게는 다른 친구의 가벼운 얘기(취향·하는 일)만 해요(아래 '친구들').
6. 선톡을 켜면 1:1 친구에게 이틀에 한 번쯤 먼저 말을 걸어요(아래 '선톡').

## 기록은 지워지지 않아요

- 채팅으로 기록을 지우는 기능이 없어요. '초기화', '처음부터'라고 해도, 그 말이 문장 안에 있어도 그냥 대화로 받아요.
- 봇이 쓰는 DB 계정(`marong`)에는 지우기·고치기 권한 자체가 없어요(`marong/schema.sql`). `run.py --check` 가 이걸 확인해요.
- 지워야 할 때는 서버 관리자가 `postgres` 계정으로 직접 지워요. 마롱이는 지워 달라는 친구에게 "동희한테 말해 줘"라고 답해요.

## 처음 서버에 올리기

노트북의 이 폴더에서 Git Bash(맥·리눅스는 터미널)로 실행해요. 서버는 ssh 별칭 `ko-family` 로 접속해요(다르면 `MARONG_HOST=별칭`).

```bash
bash deploy/ovh.sh install       # Postgres·pgvector·marong 계정·/opt/marong·systemd 설치(봇은 안 켬)
bash deploy/ovh.sh migrate-env   # 지금 돌던 봇의 BOT_TOKEN·Claude 키를 마롱이 .env 로 옮김(값은 안 보임)
bash deploy/ovh.sh check         # 점검. 처음엔 임베딩 모델(약 1.2GB)을 내려받느라 몇 분 걸려요
bash deploy/ovh.sh switch        # 점검이 통과하면 옛 봇(kakao-bot)을 끄고 마롱이를 켬
bash deploy/ovh.sh logs          # 로그 보기(Ctrl+C 로 나옴)
```

- 같은 봇 토큰으로 두 곳에서 켜면 서로 끊어 내요(4004). `switch` 는 옛 봇을 먼저 끄고 마롱이를 켜요. 되돌릴 때는 `bash deploy/ovh.sh rollback`.
- 옛 봇의 `/opt/kakao-bot`(코드·`bot.db`)은 그대로 둬요. 옛 대화는 마롱이로 옮기지 않아요.
- 서버의 공인 IPv4(15.235.186.239)는 카카오 앱의 '호출 허용 IP'에 이미 있어요. `check` 가 IP 를 보여 줘요.

## env(비밀값) 넣는 곳

비밀값은 서버의 `/opt/marong/.env` 한 곳에만 둬요. 깃·채팅·노션·메일·프로젝트 설정에 넣지 않아요.

| 방법 | 명령 |
|---|---|
| 옛 봇 값 그대로 옮기기 | `bash deploy/ovh.sh migrate-env` |
| 직접 넣기(nano) | `bash deploy/ovh.sh env` → 값 입력 → Ctrl+O, Enter, Ctrl+X |
| 확인(값은 안 보이고 '설정됨·정상'만) | `bash deploy/ovh.sh check` |
| 바꾼 값 반영 | `bash deploy/ovh.sh restart` |

항목 설명은 [.env.example](.env.example)에 있어요. 보통 바꿀 일이 있는 건 이것뿐이에요.

- `BOT_TOKEN`: 카카오 디벨로퍼스 > 앱 > [제품 설정] > [카카오톡 봇] > [봇]
- `ANTHROPIC_API_KEY`(필수), `ANTHROPIC_API_KEY_BACKUP`(선택, 주 키가 실패하면 씀)
- `ANTHROPIC_EFFORT`: 답장 effort. 기본 `xhigh`. 답이 느리면 `high`
- `GROUP_TRIGGER`: 단체방에서 이 말(예: `마롱`)이 들어간 메시지에만 답해요. 비우면 받은 메시지 모두에 답해요

## 말투·인사·참고 자료 바꾸기

- `prompt.md`: 마롱이 성격·취향(좋아하는 음식·간식·취미)·말투·규칙
- `welcome.txt`: 채팅방에 들어왔을 때 인사(`---` 아래 줄은 버튼)
- `knowledge/`: 친구들 사이에서 알아 둘 자료(.md·.txt·.csv). `_` 로 시작하는 파일은 안 읽어요

고친 뒤 `bash deploy/ovh.sh prompt` 로 올리면 재시작 없이 다음 메시지부터 반영돼요. `bash deploy/ovh.sh chat` 으로 서버에서 카카오 없이 말투를 시험할 수 있어요.

## 친구들(서로 아는 사이)

- 친구가 이름을 알려 주면 1:1 과 단체방의 키(카카오는 방마다 키가 달라요)를 이름으로 묶어 친구 한 명으로 봐요.
- 같은 단체방에서 말한 친구끼리, 그리고 친구가 말해 준 사이("현경이는 내 회사 동기야" → `add_friendship`)는 아는 사이예요. 아는 사이면 그 친구의 가벼운 얘기를 할 수 있고, 아니면 이름만 알아요("응 알아, 어떻게 알아?").
- 다른 친구에게 하는 얘기는 방별 메모에서 뒤 작업이 다시 거른 '공유 메모'뿐이에요. 음식·취미·하는 일 같은 것만 넣고, 고민·건강·연애·돈·시험·비밀은 빼요. 대화 원문·요약은 다른 방으로 넘어가지 않아요.
- 친구가 "내 얘기 다른 친구한테 하지 마"라고 하면 그 친구 얘기는 안 해요(`set_share`). 그 친구 이름도 다른 친구에게 안 보여요.

| 할 일 | 명령 |
|---|---|
| 누가 누구랑 아는 사이인지, 공유 메모 보기 | `bash deploy/ovh.sh admin friends` |
| 이름이 달라 따로 잡힌 같은 사람 묶기 | `bash deploy/ovh.sh admin link <#키> <친구 이름 또는 #키>` |
| 이름이 같아 잘못 묶인 다른 사람 떼기 | `bash deploy/ovh.sh admin unlink <#키>` |
| 그 친구 얘기를 다른 친구에게 안 하기·다시 하기 | `bash deploy/ovh.sh admin share <친구 이름 또는 #키> off`(또는 `on`) |

`#키` 는 `admin friends`·`admin people` 에 나오는 짧은 키예요. 셸에서 `#` 은 주석이라 `'#1a2b3c4d'` 처럼 따옴표로 감싸거나 `#` 을 빼고 써요.

## 선톡(마롱이가 먼저 말 걸기)

기본은 꺼져 있어요(`PROACTIVE=off`). 켜면 이렇게 움직여요.

- 대상: 카카오 1:1 방. 이틀에 한 번쯤(`PROACTIVE_EVERY_DAYS=2`: 선톡한 다음다음 날부터) 보내요. 그날 친구가 먼저 말했으면 그날은 안 보내고, 지난 선톡에 답이 없으면 답할 때까지 기다려요. 단체방에는 보내지 않아요(2026-10-25 동희님 결정: 처음엔 사흘 조용하면 한 번 → 이틀에 한 번쯤).
- 때: 한국 시각 12시~21시(`PROACTIVE_HOURS`)에 30분마다 확인해요. 대상이 있어도 매번 보내지는 않아서 보내는 시각이 매번 달라요. 한 번에 한 명.
- 양: 하루 최대 10개(`PROACTIVE_DAILY_MAX`). 카카오 전송 API 한도는 하루 1,000건이에요.
- 내용: 그 방의 최근 대화·요약·메모를 보고 1~2문장으로 말을 걸어요. 왜 연락 안 했냐고 서운해하거나 답을 조르지 않아요.
- 친구가 "먼저 연락하지 마"라고 하면 그 방은 꺼요(`set_proactive`). 다시 해 달라고 하면 켜요. `admin rooms` 에 '선톡 끔'으로 보여요.
- 기록: 보낸 선톡은 대화 기록에 마롱이 말로 남아요(`admin show` 에 '(선톡)'). 전달에 실패해도 남겨서 같은 방에 다시 시도하지 않아요.

| 할 일 | 명령 |
|---|---|
| 한 명에게 시험으로 보내기 | `bash deploy/ovh.sh proactive 동희` (`--dry` 를 붙이면 만든 말만 보여 주고 안 보냄) |
| 켜기 | `bash deploy/ovh.sh env` 에서 `PROACTIVE=on` → `bash deploy/ovh.sh restart` → `check` 에 '선톡: 켜짐' |
| 끄기(되돌리기) | `PROACTIVE=off` → `restart`. 이미 보낸 선톡은 기록에 남아요 |
| 확인 | `bash deploy/ovh.sh logs` 의 `선톡 room=… ok=True` 줄, `admin show <이름>` 의 '(선톡)' |

카카오 1:1 방에 먼저 보내려면 친구가 마롱이 채널을 친구로 추가했어야 하고(-877), 알림을 끈 친구에게는 가지 않아요(-879).

## 기록 보기·백업

```bash
bash deploy/ovh.sh admin friends         # 친구 목록(카카오 키들, 아는 사이, 공유 메모)
bash deploy/ovh.sh admin people          # 카카오 키 목록
bash deploy/ovh.sh admin rooms           # 방 목록
bash deploy/ovh.sh admin show 동희 30    # 그 친구가 있는 방의 최근 대화 30개와 기억 메모
bash deploy/ovh.sh admin stats           # 개수와 최근 7일 토큰·대략의 비용
bash deploy/ovh.sh backup                # /var/backups/marong 에 DB 백업 파일 하나(자동 백업은 없음)
```

마롱이는 받은 메시지를 모두 저장하고 동희는 위 명령으로 볼 수 있어요. 친구들에게 "마롱이랑 한 대화는 저장돼"라고 알려 주세요.

## 이 프로젝트(Claude)에 OVH 서버 연결하기

지금 이 프로젝트의 스레드는 동희 노트북에서 돌고, 서버는 노트북의 ssh 로 다뤄요. 그래서 노트북이 꺼지면 서버 작업도 멈춰요. 서버를 프로젝트에 직접 붙이려면 서버에서 Claude Code 의 Remote Control 을 켜 두면 돼요. 들어오는 포트를 열 필요는 없어요.

1. 서버에 접속해서 tmux 를 열어요: `ssh ko-family` → `tmux new -s marong-rc`
2. 작업 폴더를 만들고 들어가요(홈 폴더 자체는 '신뢰' 설정이 저장되지 않아서 하위 폴더를 써요): `mkdir -p ~/marong-work && cd ~/marong-work`
3. `claude remote-control` 을 실행하고 `Enable Remote Control? (y/n)` 에 `y`, `Trust ...?` 에 `y`.
   - 서버의 Claude Code 는 이미 2.1.310 이라 프로젝트 조건(2.1.280 이상)을 넘어요.
   - claude.ai 구독 계정으로 로그인돼 있어야 해요(`claude auth login`). API 키나 `setup-token` 으로는 Remote Control 이 안 돼요. 이 셸에 `ANTHROPIC_API_KEY` 를 export 하지 마세요.
4. tmux 에서 빠져나와요(Ctrl+B 다음 D). 서버가 재부팅되거나 10분쯤 오프라인이면 꺼지니, 그때는 1~3을 다시 해요.
5. 프로젝트에서 새 스레드를 시작할 때 "Allow Claude to work in a folder on your device" 카드에서 서버의 `~/marong-work` 를 고르면, 그 스레드는 서버에서 바로 일해요.

알아 둘 점

- 프로젝트 설정의 Environment 는 클라우드 환경용이에요. 마롱이 비밀값은 거기 넣지 않아요(서버 `.env` 에만).
- 서버 스레드는 그 리눅스 계정 권한을 그대로 가져요. 지금 `opc` 계정은 비밀번호 없는 sudo 가 되니, 스레드가 서버 전체를 바꿀 수 있어요. 더 안전하게 하려면 sudo 없는 계정을 따로 만들어 그 계정으로 Remote Control 을 켜고, 배포는 지금처럼 노트북의 `deploy/ovh.sh` 로 해요.
- 공식 문서가 리눅스 서버를 직접 예로 들지는 않아서, 카드에 서버 폴더가 보이는지 한 번 확인해 보세요.

## 시험(노트북)

카카오·Claude 없이 진짜 Postgres(pgserver)로 전체 흐름을 시험해요.

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt pgserver
.venv/Scripts/python tests/test_e2e.py      # 게이트웨이·콜백·SDK·이름 저장·요약·말풍선·재연결·로그에 내용 없음
.venv/Scripts/python tests/test_memory.py   # 저장소 권한·기억 모으기·요약·임베딩 검색·초기화가 안 지움·기록 보기
.venv/Scripts/python tests/test_llm.py      # 주 키 실패 → 백업 키, 400 은 바로 실패
.venv/Scripts/python tests/test_check.py    # run.py --check: 정상이면 0, 키·요약·지우기 권한·DB 문제면 1
.venv/Scripts/python tests/test_proactive.py  # 선톡: 대상 고르기·시간·하루 상한·전송·끄기·실패 기록·시험 명령
.venv/Scripts/python tests/test_friends.py    # 친구들: 키 묶기·아는 사이·공유 메모 거르기·다른 방 안 샘·도구·관리 명령
```

(맥·리눅스는 `.venv/bin/python`.) 노트북에서 `python run.py`(봇 모드)는 켜지 마세요. 서버의 봇과 같은 토큰이라 서로 끊어 내요.

## 파일

| 파일 | 하는 일 |
|---|---|
| `run.py` | 실행(`--check` 점검, `--chat` 터미널 대화, `--proactive` 선톡 시험) |
| `marong/agent.py` | 본체: 저장 → 기억·친구 모으기 → Claude → 답 → 저장, 도구(`set_name`·`add_friendship`·`set_share`·`set_proactive`) |
| `marong/memory.py` | 뒤 작업: 10턴마다 요약·친구별 메모, 공유 메모 거르기, 임베딩 |
| `marong/proactive.py` | 선톡: 1:1 친구에게 이틀에 한 번쯤 먼저 말 걸기 |
| `marong/store.py`, `marong/schema.sql` | Postgres 저장소와 표·권한 |
| `marong/embed.py` | 서버 CPU 임베딩(embeddinggemma-300m) |
| `marong/llm.py` | Claude 호출(주 키 → 백업 키) |
| `marong/gateway.py`, `marong/kakao.py`, `marong/app.py` | 카카오 게이트웨이·콜백·전송·이벤트 처리 |
| `deploy/` | 서버 설치·운영(`ovh.sh`), systemd, env 옮기기 |
| `tools/admin.py` | 기록 보기, 친구 키 묶기·풀기·공유 끄기(기록은 안 지움) |
| `docs/design.md` | 저장 설계와 이유 |
