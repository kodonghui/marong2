"""Send only tool execution metadata to LangSmith, off the request thread."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
import os
from queue import Full, Queue
import re
from threading import Thread
import time
from types import SimpleNamespace
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
               "not_saved", "ending", "memory_unavailable", "temporary_error",
               "queued", "skipped", "fallback", "no_reply", "no_device"},
    "reason": {"timeout", "cancelled", "invalid_input", "permission_denied", "unknown_tool",
               "storage_error", "rate_limited", "provider_auth", "provider_rejected",
               "provider_unavailable", "connection_error", "invalid_result", "not_found",
               "call_unavailable", "capacity", "no_link", "disabled", "waiter_active",
               "no_ack", "exception", "not_attempted"},
    "recall": {"ok", "short", "off", "slow", "error"},
    "delivery": {"poll", "history", "push"},
}
NUMBERS = {"round", "offered", "requested", "results_attempted", "results_sent",
           "web_searches", "web_fetches", "status_code", "count", "attempt", "available",
           "candidates", "recalled", "summaries", "notes", "recent", "cache_write_5m", "cache_write_1h"}
STAGES = {"text_turn", "model_request", "tool_node", "tool_dispatch", "voice_setup", "voice_tool",
          "provider_send", "voice_search", "app_turn", "account_lookup", "room_queue",
          "context", "recent_memory", "memory_summaries", "memory_notes", "memory_search",
          "friend_context", "discord_context", "call_context", "schedules_context", "calendar_link",
          "calendar_context", "schedule_storage", "calendar_tool", "model_attempt",
          "reply_prepare", "reply_save", "reply_publish", "reply_push", "app_http_delivery"}
ROOT_STAGES = {"text_turn", "voice_setup", "voice_tool", "voice_search", "app_turn"}
ERRORS = {"timeout", "cancelled", "invalid_input", "provider_http_error",
          "connection_error", "exception", "storage_error"}
MODEL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,95}\Z")
MASKED = "[가림]"
ROLES = {"system", "developer", "user", "assistant", "tool"}
BLOCK_TYPES = {"text", "image", "thinking", "redacted_thinking", "tool_use", "tool_result",
               "server_tool_use", "web_search_tool_result", "web_fetch_tool_result", "function",
               "object", "string", "array", "boolean", "number", "integer", "null"}
TOOL_NAMES = LABELS["tool"] | {"web_search", "web_fetch"}
PAYLOAD_FIELDS = {
    "account", "args", "arguments", "body", "call", "choices", "content", "date", "description", "end",
    "findings", "finish_reason", "friend_id", "function", "id", "input", "input_schema", "is_error", "items",
    "kwargs", "limit", "max_tokens", "message", "messages", "model", "name", "parameters", "properties",
    "query", "records", "recalled", "recent", "remind_at", "repeat", "reply", "reply_to", "request",
    "required", "response", "role", "room_key", "say", "since_id", "skip_summary_ids", "start", "status",
    "status_code", "summaries", "system", "text", "title", "tool_call_id", "tool_calls", "tool_use_id",
    "tools", "transport", "type", "value", "before_id", "created_at", "due_at", "end_time", "meta",
    "notes", "source_id", "source_type",
}
INPUT_FACTS = {"surface", "round", "tool", "offered", "requested", "results_attempted", "attempt", "delivery"}
MAX_PAYLOAD_ITEMS = 8
MAX_PAYLOAD_DEPTH = 8
active = ContextVar("active_marong_trace", default=None)
log = logging.getLogger(__name__)


def _masked(value, depth=0, field=None):
    """Keep protocol structure, allowlisted labels and counts, and drop arbitrary keys and values."""
    if value is None:
        return None
    if depth >= MAX_PAYLOAD_DEPTH:
        return MASKED
    if isinstance(value, SimpleNamespace) or type(value).__module__.startswith("anthropic.types."):
        value = vars(value)
    if isinstance(value, dict):
        result = {}
        for key, entry in value.items():
            if type(key) is not str or key not in PAYLOAD_FIELDS:
                continue
            if (key == "name" and type(entry) is str and entry in TOOL_NAMES
                    and (value.get("type") in ("tool_use", "server_tool_use", "function")
                         or "input_schema" in value or field == "function")):
                result[key] = entry
            else:
                result[key] = _masked(entry, depth + 1, key)
        if len(result) < len(value):
            result["_masked_fields"] = len(value) - len(result)
        return result
    if isinstance(value, (list, tuple)):
        shown = [_masked(item, depth + 1, field) for item in value[:MAX_PAYLOAD_ITEMS]]
        if len(value) > MAX_PAYLOAD_ITEMS:
            shown.append({"_omitted_items": len(value) - MAX_PAYLOAD_ITEMS})
        return shown
    if type(value) is str:
        if (field == "role" and value in ROLES) or (field == "type" and value in BLOCK_TYPES):
            return value
        if field == "arguments" and len(value) <= 4096:
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                pass
            else:
                if isinstance(decoded, dict):
                    return _masked(decoded, depth + 1)
    return MASKED


class Span:
    def __init__(self, stage, parent, **facts):
        start = datetime.now(timezone.utc)
        identifier = str(uuid4())
        order = start.strftime("%Y%m%dT%H%M%S%fZ") + identifier
        self.root = parent.root if parent else self
        self.finished = False
        self.runs = parent.runs if parent and not self.root.finished else []
        self.data = {
            "id": identifier, "name": stage,
            "run_type": {"tool_dispatch": "tool", "voice_tool": "tool", "model_attempt": "llm",
                         "memory_search": "retriever"}.get(stage, "chain"),
            "start_time": start.isoformat(), "inputs": {}, "outputs": {},
            "trace_id": parent.data["trace_id"] if parent else identifier,
            "dotted_order": f'{parent.data["dotted_order"]}.{order}' if parent else order,
        }
        if parent:
            self.data["parent_run_id"] = parent.data["id"]
        self.runs.append(self.data)
        self.record(**facts)
        if self.root.data["name"] == "app_turn":
            self.data["inputs"] = {"operation": stage,
                                   **{field: self.data["outputs"][field] for field in sorted(facts.keys() & INPUT_FACTS)
                                      if field in self.data["outputs"]}}

    def record(self, **facts):
        for field, value in facts.items():
            if value is None:
                continue
            if field in LABELS:
                self.data["outputs"][field] = value if type(value) is str and value in LABELS[field] else "other"
            elif field in NUMBERS and type(value) is int and value >= 0:
                self.data["outputs"][field] = value

    def fail(self, error):
        self.data["error"] = error if error in ERRORS else "exception"

    def io(self, *, inputs=None, outputs=None):
        if self.root.data["name"] != "app_turn":
            return
        if inputs is not None:
            self.data["inputs"].update(_masked(inputs))
        if outputs is not None:
            self.data["outputs"].update(_masked(outputs))

    def model(self, provider, model):
        if provider in {"anthropic", "deepseek"} and isinstance(model, str) and MODEL_NAME.fullmatch(model):
            self.data["extra"] = {"metadata": {"ls_provider": provider, "ls_model_name": model}}

    def usage(self, inputs, outputs, cached=0, written=0, write_5m=0, write_1h=0):
        def number(value):
            return value if type(value) is int and value >= 0 else 0

        if type(inputs) is not int or type(outputs) is not int:
            return
        inputs, outputs = number(inputs), number(outputs)
        cached, written = min(inputs, number(cached)), min(inputs, number(written))
        usage = {"input_tokens": inputs, "output_tokens": outputs, "total_tokens": inputs + outputs,
                 "input_token_details": {"cache_read": cached, "cache_creation": written}}
        self.data["outputs"]["usage_metadata"] = usage
        self.data.update(prompt_tokens=inputs, completion_tokens=outputs, total_tokens=inputs + outputs)
        self.record(cache_write_5m=number(write_5m), cache_write_1h=number(write_1h))

    def capture(self, error, fallback="exception"):
        _record_error(self, error, fallback)


def _record_error(span, error, fallback="exception"):
    status = getattr(error, "status_code", None)
    # Hosted SDK exceptions do not all inherit from their built-in counterparts.
    # Match the known classes without importing the chat SDK in the voice relay.
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, asyncio.CancelledError):
        span.fail("cancelled")
        span.record(reason="cancelled")
    elif isinstance(error, TimeoutError) or names & {"APITimeoutError", "TimeoutException"}:
        span.fail("timeout")
        span.record(reason="timeout")
    elif type(status) is int and 100 <= status <= 599:
        span.fail("provider_http_error")
        category = {401: "provider_auth", 403: "provider_auth", 429: "rate_limited"}
        span.record(status_code=status, reason=category.get(status, "provider_unavailable" if status >= 500
                    else "invalid_result" if status < 400 else "provider_rejected"))
    elif isinstance(error, (TypeError, ValueError)):
        span.fail("invalid_input")
        span.record(reason="invalid_input")
    elif fallback == "storage_error":
        span.fail("storage_error")
        span.record(reason="storage_error")
    elif isinstance(error, OSError) or names & {"APIConnectionError", "ClientConnectionError", "NetworkError"}:
        span.fail("connection_error")
        span.record(reason="connection_error")
    else:
        span.fail("exception")
        span.record(reason="exception")


@contextmanager
def step(stage, parent=None, **facts):
    sink = _sink() if parent is None and stage in ROOT_STAGES else None
    if stage not in STAGES or (parent is None and sink is None):
        yield None
        return
    span = Span(stage, parent, **facts)
    token = active.set(span)
    try:
        yield span
    except (Exception, asyncio.CancelledError) as error:
        if "error" not in span.data:
            _record_error(span, error)
        raise
    finally:
        active.reset(token)
        span.data["end_time"] = datetime.now(timezone.utc).isoformat()
        if sink is not None:
            span.finished = True
            sink.submit(span.runs)


def app_parent():
    parent = active.get()
    return parent if parent and parent.root.data["name"] == "app_turn" else None


@contextmanager
def app_step(stage, *, storage=False, **facts):
    with step(stage, app_parent(), **facts) as span:
        if span is None:
            yield None
            return
        try:
            yield span
        except Exception as error:
            if storage:
                span.capture(error, "storage_error")
            raise


def app_note(**facts):
    if parent := app_parent():
        parent.record(**facts)


async def app_read(stage, read, *args, **kwargs):
    with app_step(stage, storage=True) as span:
        if span:
            span.io(inputs={"args": args, "kwargs": kwargs})
        result = await read(*args, **kwargs)
        if span:
            span.record(result="ok", count=len(result) if isinstance(result, list) else None)
            span.io(outputs={"records": result})
        return result


def app_delivery(parent, transport, reply):
    span = Span("app_http_delivery", parent, delivery=transport, result="ok", status_code=200)
    span.io(outputs={"response": {"messages": [{"role": "assistant", "content": reply}]}})
    span.data["end_time"] = datetime.now(timezone.utc).isoformat()
    if parent.root.finished and (sink := _sink()):
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
