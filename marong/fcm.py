"""Firebase Cloud Messaging HTTP v1 sender for the Marong app (docs/app-chat.md SPEC-117, docs/app-ring.md SPEC-131).

The target is the app's Firebase installation ID (`fid`): FCM deprecated the `token` field. Authentication is a
one-hour OAuth token obtained with a JWT signed by the service account key (scope firebase.messaging), refreshed five
minutes before it ends and kept in memory only. The key file is read once from the systemd credential directory.
Only HTTP 404 with a typed FcmError of UNREGISTERED confirms that a device's FID should be dropped (SPEC-510).
Nothing here logs a message text, an FID, the key or a token.
"""
import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import time

import httpx
import jwt

log = logging.getLogger("marong.fcm")
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
TOKEN_EARLY_S = 300       # refresh this long before the token ends
SEND_BUDGET_S = 10        # one send, retries included
RETRY_AFTER_MAX_S = 10
RETRY_GAPS_S = (1, 2)     # 429/500/503 without Retry-After: again after 1 s, then 2 s
WARN_EVERY_S = 3600       # key or permission problems: one warning an hour
PREVIEW_MAX = 120
TITLE = "마롱이"
RING_TTL_S = 45
RING_LINE_MAX = 30
LOG_KIND = re.compile(r"[a-z_]{1,20}")
LOG_STATUS_OR_CODE = re.compile(r"[A-Z_]{1,40}")
LOG_FIELD = re.compile(r"[A-Za-z0-9_.\[\]]{1,80}")


@dataclass(frozen=True)
class ServiceAccount:
    email: str
    key_id: str
    private_key: str
    project_id: str

    @classmethod
    def load(cls, path: Path) -> "ServiceAccount":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("type") != "service_account" or data.get("token_uri") != TOKEN_URL:
            raise ValueError("not a Google service account key")
        values = [data.get(k) for k in ("client_email", "private_key_id", "private_key", "project_id")]
        if not all(isinstance(v, str) and v for v in values):
            raise ValueError("service account key fields")
        return cls(*values)


def preview(text: str, limit: int = PREVIEW_MAX) -> str:
    """The notification body: the first 120 characters, line breaks as spaces, '…' when cut."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def notice(fid: str, kind: str, text: str, *, channel: str, ttl_s: int, open_path: str = "/chat/",
           title: str = TITLE) -> dict:
    """A visible notification (proactive, reminder, reply, missed_call). PRIVATE hides the text on a locked screen
    when the phone's settings say so (REQ-118)."""
    return {"fid": fid, "notification": {"title": title, "body": preview(text)},
            "data": {"kind": kind, "open": open_path},
            "android": {"priority": "HIGH", "ttl": f"{max(1, int(ttl_s))}s",
                        "notification": {"channel_id": channel, "visibility": "PRIVATE"}}}


def ring(fid: str, ring_id: str, reason: str = "promise", line: str | None = None, *, title=None) -> dict:
    """The ring signal (SPEC-131): data only, nothing about the promise (REQ-130). The app shows the call itself.
    reason: promise | hello (a call without a promise, docs/04-functional-spec/call-first.md 3.4). A hello call adds
    the picture's preview line (1~30 characters, one line), the only words it carries."""
    data = {"kind": "ring", "ringId": ring_id, "v": "1", "reason": "hello" if reason == "hello" else "promise"}
    line = (line or "").strip()
    if reason == "hello" and 1 <= len(line) <= RING_LINE_MAX and "\n" not in line and "\r" not in line:
        data["line"] = line
    if title:
        data["title"] = title
    return {"fid": fid, "data": data, "android": {"priority": "HIGH", "ttl": f"{RING_TTL_S}s"}}


def app_update(fid: str, version_code: int) -> dict:
    """Wake the app to check its release, without a visible notification (SPEC-431)."""
    return {"fid": fid, "data": {"kind": "app_update", "v": str(version_code)},
            "android": {"priority": "HIGH", "ttl": "86400s", "collapse_key": "app_update"}}


def _error(response: httpx.Response) -> tuple[object, object, object]:
    try:
        body = response.json()
    except ValueError:
        return None, None, None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None, None, None
    status = error.get("status")
    details = error.get("details")
    if not isinstance(details, list):
        return status, None, None

    code = None
    bad_request = None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        detail_type = detail.get("@type")
        if detail_type == "type.googleapis.com/google.firebase.fcm.v1.FcmError":
            candidate = detail.get("errorCode")
            if code is None or (response.status_code == 404 and candidate == "UNREGISTERED"):
                code = candidate
        elif detail_type == "type.googleapis.com/google.rpc.BadRequest" and bad_request is None:
            bad_request = detail
    violations = bad_request.get("fieldViolations") if bad_request is not None else None
    first = violations[0] if isinstance(violations, list) and violations else None
    field = first.get("field") if isinstance(first, dict) else None
    return status, code, field


def _log_value(value: object, pattern: re.Pattern[str]) -> str:
    if value is None:
        return "-"
    return value if isinstance(value, str) and pattern.fullmatch(value) else "other"


class FCM:
    def __init__(self, account: ServiceAccount, project_id: str | None = None, http: httpx.AsyncClient | None = None,
                 *, clock=time.time, monotonic=time.monotonic, sleep=asyncio.sleep):
        self.account = account
        self.project = project_id or account.project_id
        self.http = http or httpx.AsyncClient(timeout=SEND_BUDGET_S)
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.token: str | None = None
        self.token_until = 0.0
        self.lock = asyncio.Lock()
        self.warned = -WARN_EVERY_S

    @classmethod
    def from_credentials(cls, directory: str | None, env=os.environ) -> "FCM | None":
        """The key systemd loaded (LoadCredential=fcm-service-account.json, SPEC-127). None when it is not there."""
        if not directory:
            return None
        path = Path(directory) / "fcm-service-account.json"
        if not path.exists():
            return None
        account = ServiceAccount.load(path)
        return cls(account, env.get("FCM_PROJECT_ID", "").strip() or None)

    async def close(self) -> None:
        await self.http.aclose()

    async def _token(self) -> str:
        async with self.lock:
            if self.token and self.clock() < self.token_until:
                return self.token
            now = int(self.clock())
            assertion = jwt.encode({"iss": self.account.email, "scope": SCOPE, "aud": TOKEN_URL, "iat": now,
                                    "exp": now + 3600}, self.account.private_key, algorithm="RS256",
                                   headers={"kid": self.account.key_id})
            r = await self.http.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                      "assertion": assertion})
            if r.status_code != 200:
                raise PermissionError(f"token {r.status_code}")
            body = r.json()
            self.token = body["access_token"]
            self.token_until = now + int(body.get("expires_in", 3600)) - TOKEN_EARLY_S
            return self.token

    def _warn(self, what: str) -> None:
        if self.monotonic() - self.warned >= WARN_EVERY_S:
            self.warned = self.monotonic()
            log.warning("fcm_auth_failed %s", what)

    async def send(self, message: dict) -> str:
        """ok | gone (HTTP 404 with FcmError UNREGISTERED) | auth (key or permission) | failed."""
        end = self.monotonic() + SEND_BUDGET_S
        url = SEND_URL.format(project=self.project)
        data = message.get("data")
        kind = data.get("kind") if isinstance(data, dict) else None
        # App updates persist and schedule their own numbered attempts (SPEC-430).
        retries = () if kind == "app_update" else RETRY_GAPS_S
        last_http = None
        status = code = field = None
        result = "failed"
        for attempt in range(len(retries) + 1):
            left = end - self.monotonic()
            if left <= 0:
                break
            try:
                token = await asyncio.wait_for(self._token(), left)
                r = await asyncio.wait_for(self.http.post(url, json={"message": message},
                                                          headers={"Authorization": f"Bearer {token}"}),
                                           end - self.monotonic())
            except PermissionError as e:
                self._warn(str(e))
                return "auth"
            except (httpx.HTTPError, OSError, asyncio.TimeoutError, ValueError, KeyError) as e:
                log.info("fcm_send_error %s", type(e).__name__)
                if attempt == len(retries) or self.monotonic() + retries[attempt] >= end:
                    break
                await self.sleep(retries[attempt])
                continue
            if r.status_code == 200:
                return "ok"
            last_http = r.status_code
            status, code, field = _error(r)
            if last_http == 404 and code == "UNREGISTERED":
                result = "gone"
                break
            if r.status_code in (401, 403):
                if r.status_code == 401:
                    self.token = None  # refresh before the next send
                self._warn(f"status={r.status_code} code={_log_value(code, LOG_STATUS_OR_CODE)}")
                return "auth"
            if r.status_code not in (429, 500, 502, 503, 504) or attempt == len(retries):
                break
            try:
                wait = min(RETRY_AFTER_MAX_S, max(0, int(r.headers.get("Retry-After", ""))))
            except ValueError:
                wait = retries[attempt]
            if self.monotonic() + wait >= end:
                break
            await self.sleep(wait)
        if last_http is not None:
            log.info("fcm_send_status kind=%s http=%s status=%s code=%s field=%s result=%s",
                     _log_value(kind, LOG_KIND), last_http if 100 <= last_http <= 599 else "other",
                     _log_value(status, LOG_STATUS_OR_CODE), _log_value(code, LOG_STATUS_OR_CODE),
                     _log_value(field, LOG_FIELD), result)
        return result
