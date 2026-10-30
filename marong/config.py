"""환경 변수 설정. 값은 .env 또는 systemd EnvironmentFile 로 넣는다."""
import os
from dataclasses import dataclass
from pathlib import Path

EFFORTS = ("", "low", "medium", "high", "xhigh", "max")
PER_DAY_MAX = 48  # 방 하나의 하루 선톡 수 상한(admin schedule·ask_owner 의 per_day). schema.sql 의 rooms.proactive_per_day CHECK 와 같게


def load_dotenv(path: str = ".env") -> None:
    """의존성 없이 KEY=VALUE 줄만 읽는다. 이미 있는 환경 변수는 덮어쓰지 않는다."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _hours(raw: str) -> tuple[int, int]:
    """'12-21' → (12, 21). 형식이 틀리면 (-1, -1)이고 problems() 가 알려 준다."""
    try:
        start, end = (int(x) for x in raw.split("-", 1))
    except ValueError:
        return -1, -1
    return start, end


@dataclass(frozen=True)
class Settings:
    bot_token: str
    gateway_url: str
    kakao_api_url: str
    anthropic_api_key: str
    anthropic_api_key_backup: str  # 첫 키가 실패(한도·크레딧·장애)하면 이 키로 한 번 더
    anthropic_model: str
    anthropic_effort: str          # 답장용. low·medium·high·xhigh·max. 비우면 모델 기본값
    summary_effort: str            # 뒤에서 하는 대화 요약·기억 메모 정리용
    anthropic_base_url: str
    database_url: str              # 서버에서는 postgresql:///marong (비밀번호 없이 같은 이름의 리눅스 계정으로 접속)
    embed_model: str               # 비우면 임베딩과 '비슷한 예전 대화 찾기'를 끔
    embed_cache_dir: str           # 임베딩 모델을 한 번 내려받아 두는 곳
    prompt_path: str
    knowledge_dir: str             # 친구들 사이 참고 자료. prompt.md 뒤에 붙여 메시지마다 다시 읽음
    welcome_path: str
    timezone: str
    llm_timeout_s: float
    reply_wait_s: float            # 답하기 전에 친구가 연달아 보내는 말을 기다리는 시간. 그사이 더 오면 한 번에 답함
    llm_max_tokens: int            # 생각(thinking)까지 포함한 출력 상한. 답 길이는 prompt.md 로 조절
    recent_turns: int              # 원문 그대로 다시 넣는 최근 대화(질문+답 한 쌍이 1턴)
    summary_turns: int             # 이만큼 쌓이면 뒤에서 요약 한 개를 만듦
    recall_min_similarity: float   # 이보다 덜 비슷한 예전 대화는 넣지 않음(0~1)
    group_triggers: tuple[str, ...]  # 단체방에서는 이 말이 들어간 메시지에만 답함. 비면 받은 메시지 모두에 답함
    proactive: bool                # 선톡: 1:1 친구에게 마롱이가 먼저 말 걸기. 기본 꺼짐
    proactive_per_day: int         # 친구 한 명에게 하루 선톡 수: PROACTIVE_HOURS 를 이만큼 칸으로 나눠 칸마다 한 번
    proactive_hours: tuple[int, int]  # 이 시간에만 보냄(한국 시각, 시작 시 이상 끝 시 미만)
    # 방마다 따로 정한 일정(rooms.proactive_per_day·start·end)이 있으면 위 두 값 대신 그것을 씀(tools/admin.py schedule)
    proactive_daily_max: int       # 하루에 보내는 선톡 상한(모든 친구 합, 연달아 보낸 말 묶음이 한 번. 카카오 전송 API 는 하루 1,000건)
    xai_api_key: str               # Grok(xAI) 키(console.x.ai). 비우면 Grok 을 안 씀
    xai_model: str                 # Grok 모델 이름. 쓸 수 있는 이름은 run.py --check 가 보여 줌. 비우면 Grok 을 안 씀
    xai_base_url: str
    grok_friends: tuple[str, ...]  # Grok 이 답할 친구 번호들(admin friends 의 '친구 N번'): 그 친구의 1:1 방 답만. all 이면 모든 방

    def grok_for(self, friend_id, is_channel: bool) -> bool:
        """이 방의 답을 Grok 이 하는지. 키나 모델이 비면 늘 Claude. 선톡·사진 설명·요약은 이 값과 상관없이 Claude."""
        if not (self.xai_api_key and self.xai_model and self.grok_friends):
            return False
        if "all" in self.grok_friends:
            return True
        return is_channel and friend_id is not None and str(friend_id) in self.grok_friends

    def problems(self) -> list[str]:
        """실행 전에 비어 있거나 잘못된 값을 알려 준다(값 자체는 출력하지 않음)."""
        out = []
        if not self.bot_token:
            out.append("BOT_TOKEN 이 비어 있음")
        if not (self.anthropic_api_key and self.anthropic_model):
            out.append("ANTHROPIC_API_KEY / ANTHROPIC_MODEL 이 비어 있음")
        if self.anthropic_effort not in EFFORTS:
            out.append("ANTHROPIC_EFFORT 는 low·medium·high·xhigh·max 중 하나(또는 비움)")
        if self.summary_effort not in EFFORTS:
            out.append("SUMMARY_EFFORT 는 low·medium·high·xhigh·max 중 하나(또는 비움)")
        if not self.database_url:
            out.append("DATABASE_URL 이 비어 있음")
        if self.recent_turns < 1 or self.summary_turns < 2:
            out.append("RECENT_TURNS 는 1 이상, SUMMARY_TURNS 는 2 이상")
        start, end = self.proactive_hours
        if not 0 <= start < end <= 24:
            out.append("PROACTIVE_HOURS 는 '12-21' 처럼 시작-끝 시(0~24, 시작이 끝보다 앞)")
        if self.proactive_per_day < 1 or self.proactive_daily_max < 1:
            out.append("PROACTIVE_PER_DAY·PROACTIVE_DAILY_MAX 는 1 이상")
        return out

    def anthropic_keys(self) -> list[tuple[str, str]]:
        """(이름, 키) 목록. 값은 로그에 쓰지 않고 이름만 쓴다."""
        keys = [("주 키", self.anthropic_api_key), ("백업 키", self.anthropic_api_key_backup)]
        return [(name, k) for name, k in keys if k]


def load_settings() -> Settings:
    return Settings(
        bot_token=_env("BOT_TOKEN"),
        gateway_url=_env("KAKAO_GATEWAY_URL", "wss://bot-gateway.kakao.com/gateway"),
        kakao_api_url=_env("KAKAO_API_URL", "https://kapi.kakao.com").rstrip("/"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_api_key_backup=_env("ANTHROPIC_API_KEY_BACKUP"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        # 줄이 없으면 기본값, 값을 비우면(ANTHROPIC_EFFORT=) 모델 기본값
        anthropic_effort=os.getenv("ANTHROPIC_EFFORT", "xhigh").strip().lower(),
        summary_effort=os.getenv("SUMMARY_EFFORT", "low").strip().lower(),
        anthropic_base_url=_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
        database_url=_env("DATABASE_URL", "postgresql:///marong"),
        embed_model=os.getenv("EMBED_MODEL", "google/embeddinggemma-300m").strip(),
        embed_cache_dir=_env("EMBED_CACHE_DIR", ".cache/fastembed"),
        prompt_path=_env("PROMPT_PATH", "prompt.md"),
        knowledge_dir=_env("KNOWLEDGE_DIR", "knowledge"),
        welcome_path=_env("WELCOME_PATH", "welcome.txt"),
        timezone=_env("TIMEZONE", "Asia/Seoul"),
        llm_timeout_s=float(_env("LLM_TIMEOUT_SECONDS", "120")),
        reply_wait_s=float(_env("REPLY_WAIT_SECONDS", "2")),
        llm_max_tokens=int(_env("LLM_MAX_TOKENS", "16000")),
        recent_turns=int(_env("RECENT_TURNS", "10")),
        summary_turns=int(_env("SUMMARY_TURNS", "10")),
        recall_min_similarity=float(_env("RECALL_MIN_SIMILARITY", "0.4")),
        group_triggers=tuple(t.strip() for t in _env("GROUP_TRIGGER").split(",") if t.strip()),
        proactive=_env("PROACTIVE", "off").lower() in ("on", "true", "1", "yes"),
        proactive_per_day=int(_env("PROACTIVE_PER_DAY", "2")),
        proactive_hours=_hours(_env("PROACTIVE_HOURS", "12-21")),
        proactive_daily_max=int(_env("PROACTIVE_DAILY_MAX", "60")),
        xai_api_key=_env("XAI_API_KEY"),
        xai_model=_env("XAI_MODEL"),
        xai_base_url=_env("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/"),
        grok_friends=tuple(t.strip().lower() for t in _env("GROK_FRIENDS").split(",") if t.strip()),
    )
