"""문장 임베딩(서버 CPU에서 계산). 대화 원문을 다른 회사 API 로 보내지 않는다.
fastembed(ONNX)가 처음 쓸 때 모델을 한 번 내려받아 EMBED_CACHE_DIR 에 둔다(embeddinggemma 약 1.2GB).
모델은 뒤에서 불러오고, 준비되기 전에는 None 을 돌려준다. 그동안 답장은 '비슷한 예전 대화' 없이 나간다."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("embed")

# 모델 카드가 권하는 검색용 접두어: (질문에 붙일 것, 저장할 문장에 붙일 것)
PREFIXES = {
    "google/embeddinggemma-300m": ("task: search result | query: ", "title: none | text: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
}


class Embeddings:
    def __init__(self, model: str, cache_dir: str):
        self.model = model
        self.cache_dir = cache_dir
        self.dim: int | None = None
        self.error: str | None = None
        self._m = None
        self._loading: asyncio.Task | None = None
        # ONNX 계산은 한 줄로 세워 한 번에 하나씩(이벤트 루프는 막지 않음)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embed")
        self._q, self._d = PREFIXES.get(model, ("", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.model)

    @property
    def ready(self) -> bool:
        return self._m is not None

    def start(self) -> None:
        if self.enabled and self._loading is None:
            self._loading = asyncio.create_task(self._load())

    async def wait_ready(self, timeout: float) -> bool:
        self.start()
        if self._loading is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._loading), timeout)
            except asyncio.TimeoutError:
                pass
        return self.ready

    async def _load(self) -> None:
        def load():
            from fastembed import TextEmbedding  # 무거운 import 는 쓸 때만
            m = TextEmbedding(model_name=self.model, cache_dir=self.cache_dir)
            dim = len(next(iter(m.passage_embed([self._d + "준비"]))))
            return m, dim
        try:
            self._m, self.dim = await asyncio.get_running_loop().run_in_executor(self._pool, load)
            log.info("임베딩 모델 준비됨 model=%s dim=%d", self.model, self.dim)
        except Exception as e:
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
            log.error("임베딩 모델을 불러오지 못함(기억 검색 없이 답함) %s", self.error)

    async def query(self, text: str) -> list[float] | None:
        if not self.ready:
            return None
        m, prefix = self._m, self._q
        out = await asyncio.get_running_loop().run_in_executor(
            self._pool, lambda: next(iter(m.query_embed([prefix + text]))))
        return out.tolist()

    async def documents(self, texts: list[str]) -> list[list[float]] | None:
        if not self.ready:
            return None
        m, prefix = self._m, self._d
        out = await asyncio.get_running_loop().run_in_executor(
            self._pool, lambda: list(m.passage_embed([prefix + t for t in texts])))
        return [v.tolist() for v in out]
