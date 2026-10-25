"""카카오톡 봇 게이트웨이(웹소켓) 클라이언트.
흐름: 연결 → HELLO(op10) → IDENTIFY(op2) 또는 RESUME(op6) → READY(op3)
      → HEARTBEAT(op1)/ACK(op11)로 연결 유지 → DISPATCH(op0)로 채팅방 이벤트 수신.
재연결 규칙(공식 문서):
  1001 서버 재시작·네트워크 끊김 → RESUME, 실패하면 새 IDENTIFY
  4009 세션 만료 → session 초기화 후 새 IDENTIFY
  4001 인증 실패 / 4003 잘못된 페이로드 / 4004 다른 연결로 대체됨 → 종료(EXIT_FATAL)
  반복해서 끊기면 1초 → 2초 → … 최대 30초 간격으로 다시 시도."""
import asyncio
import json
import logging

import websockets
from websockets.exceptions import ConnectionClosed

from .fmt import short_key

log = logging.getLogger("gateway")

OP_DISPATCH, OP_HEARTBEAT, OP_IDENTIFY, OP_READY = 0, 1, 2, 3
OP_RESUME, OP_HELLO, OP_HEARTBEAT_ACK = 6, 10, 11

FATAL_CLOSE = {
    4001: "인증 실패: BOT_TOKEN 확인",
    4003: "유효하지 않은 페이로드",
    4004: "다른 연결로 대체됨: 같은 봇이 다른 곳에서도 연결되어 있음",
}
SESSION_EXPIRED = 4009
MAX_BACKOFF_S = 30


class FatalGatewayError(Exception):
    pass


def redact(frame: dict) -> dict:
    """DEBUG 로그용: 대화 내용·콜백 토큰·카카오 키 원문을 가린다."""
    d = frame.get("d")
    if not isinstance(d, dict):
        return frame
    hidden = {}
    for k, v in d.items():
        if k in ("content", "callbackToken", "token", "session_id"):
            hidden[k] = f"<{len(str(v))}자>"
        elif k in ("botUserKey", "botGroupKey"):
            hidden[k] = "#" + short_key(str(v))
        else:
            hidden[k] = v
    return {**frame, "d": hidden}


class Gateway:
    def __init__(self, url: str, token: str, on_dispatch):
        self.url = url
        self.token = token
        self.on_dispatch = on_dispatch  # async (t: str, d: dict) -> None
        self.session_id: str | None = None
        self.seq = 0
        self._acked = True
        self._established = False
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self) -> None:
        backoff = 1
        while True:
            self._established = False
            try:
                await self._connect_once()
            except ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd else None
                reason = e.rcvd.reason if e.rcvd else ""
                if code in FATAL_CLOSE:
                    raise FatalGatewayError(f"close {code}: {FATAL_CLOSE[code]}") from e
                if code == SESSION_EXPIRED:
                    self.session_id, self.seq = None, 0
                log.warning("연결 끊김 code=%s reason=%s → 재연결", code, reason)
            except (OSError, asyncio.TimeoutError, websockets.InvalidHandshake, json.JSONDecodeError) as e:
                log.warning("연결 실패 %s: %s", type(e).__name__, e)
            if self._established:  # 정상 연결 뒤에 끊긴 것이면 1초부터 다시
                backoff = 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def _connect_once(self) -> None:
        """한 번 연결해서 끊길 때까지 수신한다."""
        async with websockets.connect(self.url, open_timeout=15, ping_interval=None, max_size=2**20) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if hello.get("op") != OP_HELLO:
                raise json.JSONDecodeError("HELLO 아님", "", 0)
            interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000

            if self.session_id:
                log.info("RESUME session=#%s seq=%d", short_key(self.session_id), self.seq)
                await ws.send(json.dumps({"op": OP_RESUME, "d": {
                    "token": self.token, "session_id": self.session_id, "seq": self.seq}}))
            else:
                await ws.send(json.dumps({"op": OP_IDENTIFY, "d": {"token": self.token}}))
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if frame.get("op") == OP_READY:
                        self.session_id = frame["d"]["session_id"]
                        self.seq = 0
                        log.info("READY bot=%s session=#%s", frame["d"].get("bot", {}).get("id"),
                                 short_key(self.session_id))
                        break

            self._established = True
            self._acked = True
            hb = asyncio.create_task(self._heartbeat(ws, interval))
            try:
                async for raw in ws:
                    self._handle(json.loads(raw))
            finally:
                hb.cancel()

    async def _heartbeat(self, ws, interval: float) -> None:
        while True:
            await asyncio.sleep(interval * 0.9)
            if not self._acked:
                log.warning("HEARTBEAT_ACK 누락 → 연결을 닫고 다시 연결")
                await ws.close(code=4000, reason="heartbeat ack missing")
                return
            self._acked = False
            await ws.send(json.dumps({"op": OP_HEARTBEAT}))

    def _handle(self, frame: dict) -> None:
        op = frame.get("op")
        if log.isEnabledFor(logging.DEBUG):
            log.debug("recv %s", json.dumps(redact(frame), ensure_ascii=False)[:2000])
        if op == OP_HEARTBEAT_ACK:
            self._acked = True
        elif op != OP_DISPATCH:
            log.info("기타 프레임 op=%s keys=%s", op, sorted((frame.get("d") or {}).keys()) if isinstance(frame.get("d"), dict) else None)
        else:
            d = frame.get("d") or {}
            log.info("DISPATCH s=%s t=%s keys=%s", frame.get("s"), frame.get("t"), sorted(d.keys()) if isinstance(d, dict) else type(d).__name__)
            if frame.get("s") is not None:
                self.seq = frame["s"]
            task = asyncio.create_task(self.on_dispatch(frame.get("t"), frame.get("d") or {}))
            self._tasks.add(task)
            task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("이벤트 처리 오류: %r", task.exception())
