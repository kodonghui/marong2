"""Send only tool execution metadata to LangSmith, off the request thread."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import os
from queue import Full, Queue
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


PROJECT = "marong-tool-diagnostics"
DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
ENDPOINTS = {DEFAULT_ENDPOINT, "https://eu.api.smith.langchain.com"}
LABELS = {
    "surface": {"app_chat", "discord_chat", "kakao_chat", "web_voice", "discord_voice"},
    "tool": {"set_name", "ask_owner", "card_update", "schedule_add", "schedule_list",
             "schedule_cancel", "recall", "current_time", "end_call"},
    "stop_reason": {"end_turn", "tool_use", "pause_turn", "max_tokens", "stop_sequence",
                    "refusal", "model_context_window_exceeded"},
    "result": {"ok", "rejected", "invalid_result", "no_tool_blocks",
               "time", "found", "not_found", "ask_which", "refused", "unavailable",
               "not_saved", "ending", "memory_unavailable", "temporary_error"},
}
NUMBERS = {"round", "offered", "requested", "results_attempted", "results_sent",
           "web_searches", "web_fetches", "status_code"}
STAGES = {"text_turn", "model_request", "tool_node", "tool_dispatch", "voice_setup", "voice_tool",
          "provider_send", "voice_search"}
ROOT_STAGES = {"text_turn", "voice_setup", "voice_tool", "voice_search"}
ERRORS = {"timeout", "cancelled", "invalid_input", "provider_http_error",
          "connection_error", "exception"}
log = logging.getLogger(__name__)


class Span:
    def __init__(self, stage, parent, **facts):
        start = datetime.now(timezone.utc)
        identifier = str(uuid4())
        order = start.strftime("%Y%m%dT%H%M%S%fZ") + identifier
        self.runs = parent.runs if parent else []
        self.data = {
            "id": identifier, "name": stage,
            "run_type": "tool" if stage in {"tool_dispatch", "voice_tool"} else "chain",
            "start_time": start.isoformat(), "inputs": {}, "outputs": {},
            "trace_id": parent.data["trace_id"] if parent else identifier,
            "dotted_order": f'{parent.data["dotted_order"]}.{order}' if parent else order,
        }
        if parent:
            self.data["parent_run_id"] = parent.data["id"]
        self.runs.append(self.data)
        self.record(**facts)

    def record(self, **facts):
        for field, value in facts.items():
            if field in LABELS:
                self.data["outputs"][field] = value if type(value) is str and value in LABELS[field] else "other"
            elif field in NUMBERS and type(value) is int and value >= 0:
                self.data["outputs"][field] = value

    def fail(self, error):
        self.data["error"] = error if error in ERRORS else "exception"


def _record_error(span, error):
    status = getattr(error, "status_code", None)
    # Hosted SDK exceptions do not all inherit from their built-in counterparts.
    # Match the known classes without importing the chat SDK in the voice relay.
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, asyncio.CancelledError):
        span.fail("cancelled")
    elif isinstance(error, TimeoutError) or names & {"APITimeoutError", "TimeoutException"}:
        span.fail("timeout")
    elif type(status) is int and 100 <= status <= 599:
        span.fail("provider_http_error")
        span.record(status_code=status)
    elif isinstance(error, (TypeError, ValueError)):
        span.fail("invalid_input")
    elif isinstance(error, OSError) or names & {"APIConnectionError", "ClientConnectionError", "NetworkError"}:
        span.fail("connection_error")
    else:
        span.fail("exception")


@contextmanager
def step(stage, parent=None, **facts):
    sink = _sink() if parent is None and stage in ROOT_STAGES else None
    if stage not in STAGES or (parent is None and sink is None):
        yield None
        return
    span = Span(stage, parent, **facts)
    try:
        yield span
    except (Exception, asyncio.CancelledError) as error:
        _record_error(span, error)
        raise
    finally:
        span.data["end_time"] = datetime.now(timezone.utc).isoformat()
        if sink is not None:
            sink.submit(span.runs)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Sender:
    def __init__(self, key, endpoint, project, workspace):
        self.endpoint = endpoint
        self.project = project
        self.headers = {"X-Api-Key": key, "Content-Type": "application/json"}
        if workspace:
            self.headers["X-Tenant-Id"] = workspace
        self.opener = build_opener(_NoRedirect())
        self.queue = Queue(maxsize=128)
        self.last_warning = float("-inf")
        Thread(target=self._send_pending, name="langsmith-tool-trace", daemon=True).start()

    def _warn(self, reason):
        now = time.monotonic()
        if now - self.last_warning >= 60:
            self.last_warning = now
            log.warning("tool_trace_export_failed reason=%s", reason)

    def submit(self, runs):
        try:
            self.queue.put_nowait(runs)
        except Full:
            self._warn("queue_full")

    def publish(self, runs):
        body = {"post": [{**run, "session_name": self.project} for run in runs], "patch": []}
        req = Request(self.endpoint + "/runs/batch", json.dumps(body).encode(), self.headers)
        with self.opener.open(req, timeout=3):
            pass

    def _send_pending(self):
        while True:
            runs = self.queue.get()
            try:
                self.publish(runs)
            except HTTPError as error:
                self._warn(f"http_{error.code}")
            except Exception:
                self._warn("transport")
            finally:
                self.queue.task_done()


@lru_cache(maxsize=1)
def _sink():
    if os.getenv("MARONG_TOOL_TRACE") != "1":
        return None
    key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    endpoint = (os.getenv("LANGSMITH_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
    if not key or endpoint not in ENDPOINTS:
        log.warning("tool_trace_disabled reason=%s", "missing_key" if not key else "unsupported_endpoint")
        return None
    return _Sender(key, endpoint, os.getenv("LANGSMITH_PROJECT") or PROJECT,
                   os.getenv("LANGSMITH_WORKSPACE_ID"))
