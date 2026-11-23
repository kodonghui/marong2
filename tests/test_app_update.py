"""TC-200~212 against local Postgres, a fake Access verifier key endpoint and a temporary release directory."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from aiohttp.test_utils import TestClient, TestServer
import httpx
from yarl import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools/vertex_live")]
from marong.access import AccessConfig, AccessVerifier  # noqa: E402
from marong.app_chat import AppChat  # noqa: E402
from marong.app_release import AppReleases, PACKAGE, Release  # noqa: E402
from marong.discord_store import DiscordStore  # noqa: E402
from pg import TestDB  # noqa: E402
from test_app_chat import AUD, Certs, HK_EMAIL, ORIGIN, STRANGER, TEAM, TOKENS, WRONG_KEY, auth, prepare, problem  # noqa: E402

GET = "/chat/api/app/release"
APK = "/chat/app/"
CHECKS = 0


def ok(condition, label):
    global CHECKS
    assert condition, label
    CHECKS += 1


def apk(path, signer=True):
    with ZipFile(path, "w") as zipped:
        zipped.writestr("AndroidManifest.xml", b"fixture, checked structurally only")
        if signer:
            zipped.writestr("META-INF/TEST.RSA", b"fixture")
        zipped.writestr("assets/sample.bin", b"\x19" * 200000)
    return path


def fixture(folder, code=5):
    content = b"fixture bytes"
    release = Release(code, f"0.2.{code - 3}", len(content), hashlib.sha256(content).hexdigest(),
                      datetime.now(timezone.utc).isoformat())
    (folder / "release.json").write_text(json.dumps(release.manifest()), encoding="utf-8")
    (folder / release.file).write_bytes(content)
    return release


def folder_checks(base, logs):
    releases = AppReleases(base / "release", clock=lambda: now[0])
    now = [1000]
    folder = releases.folder
    ok(releases.latest() is None, "TC-200 missing folder")
    folder.mkdir()
    ok(releases.latest() is None, "TC-200 missing manifest")
    release = fixture(folder)
    ok(releases.latest() == release, "TC-200 valid")
    (folder / "paused").touch()
    ok(releases.latest() is None, "TC-200 paused")
    (folder / "paused").unlink()
    manifest = folder / "release.json"
    for fields in ({"format": True}, {"format": 2}, {"package": "not.marong"}, {"file": "../wrong.apk"},
                   {"sha256": "1" * 63}, {"versionCode": 0}, {"versionCode": 2100000001}, {"versionName": "0.2.x"},
                   {"size": -1}, {"size": 209715201}, {"publishedAt": "fixture_time"}):
        manifest.write_text(json.dumps({**release.manifest(), **fields}), encoding="utf-8")
        ok(releases.latest() is None, "TC-200 invalid manifest fields")
    manifest.write_text("{unclosed", encoding="utf-8")
    before = logs.getvalue().count("reason=json")
    ok(releases.latest() is None and releases.latest() is None, "TC-200 malformed JSON")
    now[0] += 599
    ok(releases.latest() is None and logs.getvalue().count("reason=json") == before + 1, "TC-200 throttled")
    now[0] += 1
    ok(releases.latest() is None and logs.getvalue().count("reason=json") == before + 2, "TC-200 after 10 minutes")
    release = fixture(folder)
    (folder / release.file).write_bytes(b"wrong size")
    ok(releases.latest() is None, "TC-200 wrong size")
    (folder / release.file).unlink()
    ok(releases.latest() is None, "TC-200 APK missing")
    unrelated = base / "other.bin"
    unrelated.write_bytes(b"fixture bytes")
    (folder / release.file).symlink_to(unrelated)
    ok(releases.latest() is None and releases.open(release.file) is None, "TC-206 symlink stays private")
    (folder / release.file).unlink()


async def run_api(db, base, logs):
    store = DiscordStore(db.app_url, call_bridge=True)
    await store.open(wait=True)
    certs = Certs()
    access_config = AccessConfig(TEAM, AUD, frozenset({HK_EMAIL}))
    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(certs))
    releases = AppReleases(base / "release")
    chat = AppChat(store, None, None, AccessVerifier(access_config, httpx_client), None,
                   origin=ORIGIN, releases=releases)
    folder = releases.folder
    release = fixture(folder)

    def cli(*args):
        return subprocess.run([sys.executable, str(ROOT / "tools/app_release.py"), *map(str, args)],
                              env={**os.environ, "MARONG_APP_RELEASES_DIR": str(folder)},
                              capture_output=True, text=True, check=False)

    source = apk(base / "signed.apk")
    unsigned = apk(base / "unsigned.apk", signer=False)
    notes = base / "notes.txt"
    notes.write_text("시험 릴리스", encoding="utf-8")

    def upload(code, package=PACKAGE, file=source):
        return ["publish", "--apk", file, "--package", package, "--version-code", code,
                "--version-name", f"0.2.{code - 3}", "--notes-file", notes]

    try:
        async with TestClient(TestServer(chat.web_app())) as http:
            headers = {**auth(), "Cookie": "CF_Authorization=NOT_A_REAL_COOKIE"}
            r = await http.get(GET, headers=headers)
            ok(r.status == 200 and r.headers["Cache-Control"] == "no-store" and await r.json() == release.public(),
               "TC-201 exact API-141 schema")
            checked = logs.getvalue().count("app_release check")
            for path, user_agent, request_headers, status in (
                (GET, "MarongApp/0.2.2", headers, 200),
                (GET, "MarongApp/0.2.2", {}, 401),
                (GET, "MarongApp/invalid PRIVATE_USER_AGENT", headers, 200),
                (APK + release.file, "MarongApp/0.2.2", headers, 200),
            ):
                r = await http.get(path, headers={**request_headers, "User-Agent": user_agent})
                ok(r.status == status, "TC-229 check doesn't change the response")
                await r.read()
            logged = [line for line in logs.getvalue().splitlines() if line.startswith("app_release check")]
            ok(logged[checked:] == ["app_release check version=0.2.2 status=200",
                                    "app_release check version=0.2.2 status=401"], "TC-229 version and status only")
            r = await http.get(APK + release.file, headers=headers)
            ok(r.status == 200 and r.headers["Cache-Control"] == "no-store"
               and r.headers["Content-Type"] == "application/vnd.android.package-archive"
               and int(r.headers["Content-Length"]) == release.size
               and hashlib.sha256(await r.read()).hexdigest() == release.sha256, "TC-205 streamed APK")

            paths = (GET, APK + release.file)
            for path in paths:
                await problem(await http.get(path), 401, "unauthenticated")
                await problem(await http.get(path, headers=auth(key=WRONG_KEY)), 401, "unauthenticated")
                await problem(await http.get(path, headers=auth(STRANGER)), 403, "not_allowed")
            db.admin("UPDATE call.callers SET enabled=false WHERE friend_id=2")
            for path in paths:
                await problem(await http.get(path, headers=headers), 403, "not_allowed")
            db.admin("UPDATE call.callers SET enabled=true WHERE friend_id=2")
            db.admin("UPDATE marong.discord_dm_links SET channel_id=NULL WHERE friend_id=2")
            for path in paths:
                ok((await http.get(path, headers=headers)).status == 200, "TC-203/207 no DM required")

            chat.access = AccessVerifier(access_config, httpx_client)
            certs.fail = True
            for path in paths:
                await problem(await http.get(path, headers=headers), 503, "db_unavailable")
            certs.fail = False
            for path in paths:
                with patch.object(chat.access, "check", side_effect=RuntimeError("PRIVATE_FAILURE_TEXT")):
                    await problem(await http.get(path, headers=headers), 500, "internal")
            for tail in ("marong-0.2.1-4.apk", "bad.apk", "%2E%2E%2Ffake", "part%2F" + release.file):
                await problem(await http.get(URL(APK + tail, encoded=True), headers=headers), 404, "no_release")

            for mode in ("missing", "broken", "paused"):
                fixture(folder)
                manifest = folder / "release.json"
                if mode == "missing":
                    manifest.unlink()
                elif mode == "broken":
                    manifest.write_text("bad", encoding="utf-8")
                else:
                    ok(cli("pause").returncode == cli("pause").returncode == 0, "TC-212 repeat pause")
                r = await http.get(GET, headers=headers)
                ok(r.status == 204 and not await r.read() and r.headers["Cache-Control"] == "no-store", "TC-202")
                await problem(await http.get(APK + release.file, headers=headers), 404, "no_release")
            ok(cli("resume").returncode == 0 and (await http.get(GET, headers=headers)).status == 200, "TC-212 resume")

            manifest = folder / "release.json"
            snapshot = {p.name: p.read_bytes() for p in folder.iterdir()}
            invalid = base / "invalid.apk"
            invalid.write_bytes(b"not an APK")
            for inputs in (upload(5), upload(4), upload(6, package="other.app"),
                           upload(6, file=invalid), upload(6, file=unsigned)):
                check = cli(*inputs)
                ok(check.returncode == 2 and check.stderr and
                   {p.name: p.read_bytes() for p in folder.iterdir()} == snapshot, "TC-210 rejected without mutation")
            ok(cli("pause").returncode == 0, "TC-209 unpauses on publish")
            for code in (6, 7, 8):
                previous = json.loads(manifest.read_bytes())["versionCode"]
                child = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / "tools/app_release.py"),
                    *map(str, upload(code)), env={**os.environ, "MARONG_APP_RELEASES_DIR": str(folder)},
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                observed = set()
                while child.returncode is None:
                    observed.add(json.loads(manifest.read_bytes())["versionCode"])
                    await asyncio.sleep(0.002)
                out, _ = await child.communicate()
                ok(child.returncode == 0 and b"sha256=" in out and observed <= {previous, code},
                   "TC-209 atomic manifest and digest")
                old = await (await http.get(GET, headers=headers)).json()
                ok(old["versionCode"] == code and not (folder / "paused").exists(), "TC-209 new metadata served")
                ok("notes" not in old, "TC-611 API-141 does not expose release notes")
            ok(sorted(p.name for p in folder.glob("*.apk")) ==
               ["marong-0.2.3-6.apk", "marong-0.2.4-7.apk", "marong-0.2.5-8.apk"], "TC-211 keep three")
            ok(old["sha256"][:16] in cli("status").stdout, "TC-212 status hash prefix")
            manifest.unlink()
            ok(cli("pause").returncode == cli("resume").returncode == 0, "TC-212 no release")

            logged = logs.getvalue()
            ok("app_release apk sent code=5" in logged and "app_release invalid" in logged
               and not any(value in logged for value in [HK_EMAIL, STRANGER, "PRIVATE_FAILURE_TEXT", "NOT_A_REAL_COOKIE",
                                                        *TOKENS]), "TC-208 safe logs")
    finally:
        await httpx_client.aclose()
        await store.close()


def metadata_checks(base):
    # Source this one function without letting the test binary contact the real SSH host.
    subprocess.run(["bash", "-n", str(ROOT / "deploy/ovh.sh")], check=True)
    source = (ROOT / "deploy/ovh.sh").read_text(encoding="utf-8")
    fn = source.split("app_release_metadata() {", 1)[1].split("\ncase", 1)[0]
    script = base / "metadata.sh"
    script.write_text('app_release_metadata() {' + fn + '\napp_release_metadata "$1"\n', encoding="utf-8")
    file = apk(base / "APK fixture.apk")
    metadata = base / "output-metadata.json"

    def read():
        return subprocess.run(["bash", str(script), str(file)], capture_output=True, text=True)

    ok(read().returncode != 0, "TC-210 missing Gradle metadata")
    metadata.write_text(json.dumps({"applicationId": PACKAGE, "elements":
        [{"versionCode": 5, "versionName": "0.2.2", "outputFile": "other.apk"}]}), encoding="utf-8")
    ok(read().returncode != 0, "TC-210 APK name mismatch")
    metadata.write_text(metadata.read_text(encoding="utf-8").replace("other.apk", file.name), encoding="utf-8")
    result = read()
    ok(result.returncode == 0 and result.stdout.strip() == f"{PACKAGE} 5 0.2.2", "TC-210 local metadata")


if __name__ == "__main__":
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    with TemporaryDirectory() as directory:
        base = Path(directory)
        folder_checks(base, buffer)
        metadata_checks(base)
        db = TestDB()
        try:
            prepare(db)
            (base / "release" / "release.json").unlink(missing_ok=True)
            asyncio.run(run_api(db, base, buffer))
        finally:
            db.close()
    print(f"TC-200~212: {CHECKS} checks passed")
