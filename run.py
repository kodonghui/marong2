"""마롱이 실행
  python run.py           봇 실행(카카오 게이트웨이 연결). 서버의 systemd(marong.service)가 이걸 켬
  python run.py --check   설정·Claude 키·Postgres·임베딩·요약을 점검하고 이 서버의 공인 IPv4 를 출력. 하나라도 실패하면 종료 코드 1
  python run.py --chat    카카오 없이 터미널에서 마롱이와 대화(말투 다듬기용). 대화는 'terminal' 방으로 저장됨
  python run.py --proactive <이름|#키> [--dry]
                          그 친구의 1:1 방에 선톡 한 개를 지금 보냄(시험용. 선톡 간격·시간·PROACTIVE 설정과 상관없이).
                          --dry 면 만든 말만 보여 주고 보내지 않음
같은 봇 토큰으로 두 곳에서 run.py 를 켜지 않는다(서로 끊어 냄. 4004). --proactive 는 게이트웨이에 붙지 않아서 봇이 켜져 있어도 됨."""
import asyncio
import logging
import os
import sys

import httpx

from marong.agent import FALLBACK_TEXT, REFUSAL_TEXT, Agent, Incoming
from marong.app import BotApp
from marong.config import load_dotenv, load_settings
from marong.embed import Embeddings
from marong.gateway import FatalGatewayError, Gateway
from marong.knowledge import knowledge_files
from marong.llm import LLM, brief
from marong.memory import MemoryWorker
from marong.proactive import Proactive
from marong.store import SCHEMA_VERSION, Store

# 설정 오류·토큰 오류·다른 연결로 대체됨(4004)은 '정상 종료(0)'로 끝낸다.
# systemd(Restart=on-failure)가 이때는 다시 켜지 않아, 같은 봇을 두 곳에서 켰을 때 서로 끊어 대는 일을 막는다.
EXIT_CONFIG = 0
EXIT_FATAL = 0
EMBED_WAIT_CHECK_S = 900  # --check: 처음엔 모델(약 1.2GB)을 내려받느라 몇 분 걸릴 수 있음


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) or 1)


async def check(s, store: Store, emb: Embeddings, llm: LLM, agent: Agent, worker: MemoryWorker,
                http: httpx.AsyncClient) -> int:
    ok = True

    def bad(line: str) -> None:
        nonlocal ok
        ok = False
        print(line)

    print(f"모델: {s.anthropic_model} / 답장 effort {s.anthropic_effort or '모델 기본값'} / "
          f"요약 effort {s.summary_effort or '모델 기본값'} / 최대 출력 {s.llm_max_tokens}")
    for name, status in await llm.check_keys():
        (print if status.startswith("정상") else bad)(f"  Claude {name}: {status}")
    print("BOT_TOKEN:", "설정됨" if s.bot_token else "비어 있음(봇 실행 전에 넣어야 함)")
    persona = agent.persona()
    (print if persona else bad)(f"말투 지시문: {f'{len(persona)}자' if persona else s.prompt_path + ' 없음'}"
                                f" (지식 파일 {len(knowledge_files(s.knowledge_dir))}개)")
    print("첫 인사(welcome.txt):", "있음" if os.path.exists(s.welcome_path) else "없음(채팅방에 들어와도 인사하지 않음)")
    print("단체방:", f"{', '.join(s.group_triggers)} 이(가) 들어간 메시지에만 답함" if s.group_triggers
          else "받은 메시지 모두에 답함")
    start, end = s.proactive_hours
    print("선톡:", f"켜짐(1:1 친구에게 {s.proactive_every_days}일에 한 번쯤 {start}~{end}시에. 그날 친구가 먼저 말했거나 "
                 f"지난 선톡에 답이 없으면 안 보냄. 하루 최대 {s.proactive_daily_max}개)" if s.proactive
          else "꺼짐(PROACTIVE=off)")

    try:
        await store.open(wait=True, timeout=10)
        version = await store.schema_version()
        counts = await store.counts()
        (print if version == SCHEMA_VERSION else bad)(
            f"Postgres: 연결됨, 표 버전 {version}(코드 {SCHEMA_VERSION}) / 방 {counts['rooms']} · 친구 {counts['friends']}"
            f"(카카오 키 {counts['people']}) · 메시지 {counts['messages']} · 요약 {counts['summaries']}"
            f" · 임베딩 {counts['embeddings']}")
        if await store.can_delete():
            bad("  봇 계정이 대화 기록을 지우거나 고칠 수 있음: schema.sql 권한을 다시 적용하세요")
        else:
            print("  기록 지우기·고치기 권한: 없음(정상. 채팅으로는 기록이 지워지지 않음)")
    except Exception as e:
        bad(f"Postgres: 실패 {brief(e)}")

    if emb.enabled:
        print(f"임베딩: {emb.model} 불러오는 중(처음엔 내려받느라 몇 분 걸릴 수 있음)…", flush=True)
        if await emb.wait_ready(EMBED_WAIT_CHECK_S):
            q = await emb.query("이번 주말에 뭐 먹을까")
            near, far = await emb.documents(["토요일 저녁 메뉴로 마라탕 어때", "다음 달 시험 범위 나왔어"])
            sim = [cosine(q, v) for v in (near, far)]
            line = f"  준비됨: {emb.dim}차원, 비슷한 문장 {sim[0]:.2f} / 다른 문장 {sim[1]:.2f}"
            (print if sim[0] > sim[1] else bad)(line)
        else:
            bad(f"  실패: {emb.error or '시간 안에 준비되지 않음'}")
    else:
        print("임베딩: 꺼짐(EMBED_MODEL 비어 있음). 비슷한 예전 대화 찾기를 하지 않음")

    test = Incoming(room_key="check", user_key="check", text="안녕! 너는 누구야?")
    system = agent._system(agent._situation(test, None, [], [], []))
    try:
        reply, meta = await agent.ask(system, [{"role": "user", "content": test.text}], test,
                                      asyncio.get_running_loop().time() + s.llm_timeout_s)
        (print if reply not in (FALLBACK_TEXT, REFUSAL_TEXT) else bad)(
            f"답장 시험: {reply}\n  (호출 {meta['calls']}번, 입력 {meta['input_tokens']} · 출력 {meta['output_tokens']} 토큰)")
    except Exception as e:
        bad(f"답장 시험: 실패 {brief(e)}")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    sample = [
        {"id": 1, "role": "user", "user_key": "a", "name": "동희", "content": "나 다음 주 금요일에 토익 시험이야 ㅠ", "created_at": now},
        {"id": 2, "role": "assistant", "user_key": None, "name": None, "content": "헐 동희 화이팅이야 📚", "created_at": now},
        {"id": 3, "role": "user", "user_key": "a", "name": "동희", "content": "끝나면 마라탕 먹으러 갈 거야. 나 마라탕 진짜 좋아함", "created_at": now},
        {"id": 4, "role": "assistant", "user_key": None, "name": None, "content": "완전 좋다 🌶️", "created_at": now},
    ]
    notes = {}
    try:
        summary, notes, _ = await worker.summarize(sample, {})
        print(f"요약 시험: {summary}\n  메모: {notes.get('a', '(없음)')}")
    except Exception as e:
        bad(f"요약 시험: 실패 {brief(e)}")
    if notes.get("a"):
        try:
            shared, _ = await worker.share_filter("동희", [{"is_channel": True, "content": notes["a"]}])
            print(f"공유 메모 시험(시험 얘기는 빠져야 함): {shared.replace(chr(10), ' / ') or '(없음)'}")
        except Exception as e:
            bad(f"공유 메모 시험: 실패 {brief(e)}")

    try:
        ip = (await http.get("https://api.ipify.org", timeout=10)).text.strip()
        print("이 서버의 공인 IPv4(카카오 '호출 허용 IP'에 있어야 함):", ip)
    except httpx.HTTPError as e:
        print("공인 IP 확인 실패:", type(e).__name__)
    if not ok:
        print("점검 실패: 위에서 '실패'나 '없음' 줄을 확인하세요(종료 코드 1)")
    return 0 if ok else 1


async def chat(agent: Agent) -> None:
    print("터미널 대화 모드야. 끝내려면 Ctrl+C. 대화는 'terminal' 방으로 저장돼.")
    loop = asyncio.get_running_loop()

    async def show(text: str) -> bool:
        print("마롱이>", text)
        return True

    while True:
        text = await loop.run_in_executor(None, input, "나> ")
        await agent.handle(Incoming(room_key="terminal", user_key="terminal", text=text), show)


async def proactive_once(s, store: Store, agent: Agent, http: httpx.AsyncClient, args: list[str]) -> int:
    dry = "--dry" in args
    who = next((a for a in args if a != "--dry"), "")
    if not who:
        print("사용: run.py --proactive <이름|#키> [--dry]")
        return 1
    await store.open(wait=True, timeout=10)
    rooms = await store.channel_rooms(who)
    if len(rooms) != 1:
        print(f"'{who}' 의 1:1 방을 하나로 못 정함(찾은 방 {len(rooms)}개). tools/admin.py people 의 #키로 다시 해 봐요")
        return 1
    room = rooms[0]
    if not room["proactive"]:
        print("이 친구는 선톡을 꺼 뒀어요(친구가 마롱이에게 다시 켜 달라고 해야 함). 보내지 않음")
        return 1
    result = await Proactive(s, store, agent, http).deliver(room, dry=dry)
    if result["text"] is None:
        print("선톡 말을 만들지 못함(로그 확인)")
        return 1
    if dry:
        print(f"미리 보기(보내지 않음): {result['text']}")
        return 0
    if result["ok"]:
        print(f"보냄: {result['text']}")
        return 0
    print(f"전달 실패(카카오 코드 {result['code']}): {result['text']}")
    return 1


async def main(mode: str, args: list[str] | None = None) -> int:
    s = load_settings()
    sends = mode == "run" or (mode == "proactive" and "--dry" not in (args or []))
    problems = s.problems() if sends else [p for p in s.problems() if "BOT_TOKEN" not in p]
    if problems:
        for p in problems:
            logging.error("설정 오류: %s", p)
        return EXIT_CONFIG if mode == "run" else 1  # --check 는 실패를 알려야 뒤의 && 가 멈춤

    store = Store(s.database_url)
    emb = Embeddings(s.embed_model, s.embed_cache_dir)
    llm = LLM(s)
    worker = MemoryWorker(s, store, emb, llm)
    agent = Agent(s, store, emb, llm, on_saved=worker.kick)
    tasks: list[asyncio.Task] = []
    try:
        async with httpx.AsyncClient() as http:
            if mode == "check":
                return await check(s, store, emb, llm, agent, worker, http)
            if mode == "proactive":
                return await proactive_once(s, store, agent, http, args or [])
            # DB 가 아직 안 떠 있어도 봇은 켜지고, 연결은 뒤에서 계속 시도(그동안은 기억 없이 답함)
            await store.open(wait=False)
            emb.start()
            tasks.append(asyncio.create_task(worker.run()))
            if mode == "chat":
                await chat(agent)
                return 0
            app = BotApp(s, agent, http)
            if s.proactive:
                tasks.append(asyncio.create_task(Proactive(s, store, agent, http, app.room_lock).run()))
            gateway = Gateway(s.gateway_url, s.bot_token, app.on_dispatch)
            try:
                await gateway.run_forever()
            except FatalGatewayError as e:
                logging.error("게이트웨이 종료: %s", e)
                return EXIT_FATAL
    finally:
        for t in tasks:
            t.cancel()
        await store.close()
        await llm.close()
    return 0


if __name__ == "__main__":
    load_dotenv()
    # LOG_LEVEL=DEBUG 이면 게이트웨이 프레임까지 찍힘(대화 내용·토큰은 가려짐)
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpcore", "httpx2", "psycopg.pool", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # 요청마다 찍히는 줄은 숨김(오류는 그대로 남음)
    mode = ("check" if "--check" in sys.argv else "chat" if "--chat" in sys.argv
            else "proactive" if "--proactive" in sys.argv else "run")
    rest = [a for a in sys.argv[1:] if a not in ("--check", "--chat", "--proactive")]
    # psycopg 비동기는 윈도우 기본 이벤트 루프(Proactor)에서 돌지 않음
    options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
    try:
        sys.exit(asyncio.run(main(mode, rest), **options))
    except KeyboardInterrupt:
        print("\n종료")
