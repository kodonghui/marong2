"""Marong release 20261117-topics: calls first and picture topics (docs/04-functional-spec/call-first.md SPEC-283,
docs/10-wbs/call-first.md TASK-177). Run on the Marong server as root, with a bundle made by `git archive` of the
release commit (the folders marong, tools, deploy and the file run_discord.py):

    python3 release-20261117-topics.py check     BUNDLE.tar   # what would change; changes nothing
    python3 release-20261117-topics.py db-backup BUNDLE.tar   # pg_dump of the marong database into the backup folder
    python3 release-20261117-topics.py migrate   BUNDLE.tar   # 018_call_first.sql (safe to run twice), then a check
    python3 release-20261117-topics.py apply     BUNDLE.tar   # back up and replace the files, add MARONG_TOPICS=1
    python3 release-20261117-topics.py rollback               # files and the drop-in as before apply (the tables stay)

Nothing here restarts a service. After apply or rollback, restart marong-discord and the call server (marong-vertex-live,
a user unit of the call server's owner) when nobody is talking or calling; rollback.sh in the backup folder does all
of it. Prints states, counts and the first 16 hex of sha256 only: no settings values, names or messages.
"""
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import tarfile

RELEASE = "20261117-topics"
BOT = "/opt/marong-discord"
CALL = "/home/opc/marong-vertex-test/app"
DROPIN = "/etc/systemd/system/marong-discord.service.d/zz-topics.conf"
DROPIN_TEXT = ("[Service]\n# Picture topics and hello calls (docs/04-functional-spec/call-first.md). "
               "Added 2026-11-17 (" + RELEASE + ").\nEnvironment=MARONG_TOPICS=1\n")
CONFIG = "/etc/marong-discord/config"
MIGRATION = "marong/migrations/018_call_first.sql"
MIGRATION_NEW = "e57d77308fa96d69"
SCRIPT = "deploy/release-" + RELEASE + ".py"

# (root, path in the repository, path under the root, sha256[:16] before (None: a new file), after, required)
# "before" is the release base 4c0b5b0: main 2a473ae, the face1 and ring1 changes and PR #28, all on the server.
# A file that is not required is left alone when its folder is missing or it is another version.
FILES = [
    # MANIFEST-START
    ("bot", "marong/agent.py", "marong/agent.py", "c220f2a931da32e3", "2aa98e66ffa275a9", True),
    ("bot", "marong/app_chat.py", "marong/app_chat.py", "fb94fe0f0abb8980", "181a1d320f786d84", True),
    ("bot", "marong/app_chat_static/chat.css", "marong/app_chat_static/chat.css", "a8a644864367a07c", "4197ff5d6ca4edf4", True),
    ("bot", "marong/app_chat_static/chat.js", "marong/app_chat_static/chat.js", "817833cd8852353e", "1ff1643520a15dd1", True),
    ("bot", "marong/app_delivery.py", "marong/app_delivery.py", "f06c3eed75831fd7", "189f90c9fb63dfc0", True),
    ("bot", "marong/app_push.py", "marong/app_push.py", "760eba2a2b72b502", "95a99be9bd304a8b", True),
    ("bot", "marong/app_store.py", "marong/app_store.py", "b5effe3cd458de80", "3128ca78e2de19f9", True),
    ("bot", "marong/discord_dm.py", "marong/discord_dm.py", "b3c68b923cfe6bfe", "83b40e0c0eec3edd", True),
    ("bot", "marong/discord_store.py", "marong/discord_store.py", "1992f7d7f0c11b04", "ef4937fca58a0b39", True),
    ("bot", "marong/fcm.py", "marong/fcm.py", "764ec17cc74b0e7a", "fe08605a81499e2f", True),
    ("bot", "marong/proactive.py", "marong/proactive.py", "9de55bc4458c4173", "c9a5d4a11de1101e", True),
    ("bot", "marong/topic_store.py", "marong/topic_store.py", None, "1ff25d562c23e25a", True),
    ("bot", "marong/topics.py", "marong/topics.py", None, "e17450e7763d7a1c", True),
    ("bot", "run_discord.py", "run_discord.py", "8af67801839c54bb", "ab0be3ed5a9fcc0c", True),
    ("bot", "marong/topics/v1/autumn-leaves.webp", "marong/topics/v1/autumn-leaves.webp", None, "77af701e480f780f", True),
    ("bot", "marong/topics/v1/baked-cookies.webp", "marong/topics/v1/baked-cookies.webp", None, "ff5fc0d7843c1cc8", True),
    ("bot", "marong/topics/v1/blanket-movie.webp", "marong/topics/v1/blanket-movie.webp", None, "f3b8ec470206210d", True),
    ("bot", "marong/topics/v1/bubble-bath.webp", "marong/topics/v1/bubble-bath.webp", None, "288a99878df0e884", True),
    ("bot", "marong/topics/v1/cherry-blossom.webp", "marong/topics/v1/cherry-blossom.webp", None, "72ea4927a7b0183f", True),
    ("bot", "marong/topics/v1/chicken-skewer.webp", "marong/topics/v1/chicken-skewer.webp", None, "94167e9ed7ba9c12", True),
    ("bot", "marong/topics/v1/crayon-drawing.webp", "marong/topics/v1/crayon-drawing.webp", None, "200633e370230add", True),
    ("bot", "marong/topics/v1/first-snow.webp", "marong/topics/v1/first-snow.webp", None, "de69158f1d48ba7c", True),
    ("bot", "marong/topics/v1/fish-bread.webp", "marong/topics/v1/fish-bread.webp", None, "cbf27e58af5801f4", True),
    ("bot", "marong/topics/v1/hand-warmer.webp", "marong/topics/v1/hand-warmer.webp", None, "29fc9c67828c48df", True),
    ("bot", "marong/topics/v1/headphones.webp", "marong/topics/v1/headphones.webp", None, "f9b6f6e451a52353", True),
    ("bot", "marong/topics/v1/hot-cocoa.webp", "marong/topics/v1/hot-cocoa.webp", None, "5403c6bf152581fd", True),
    ("bot", "marong/topics/v1/hotteok.webp", "marong/topics/v1/hotteok.webp", None, "9fbf33ad59174072", True),
    ("bot", "marong/topics/v1/ice-cream.webp", "marong/topics/v1/ice-cream.webp", None, "7ee42b3b2aad8734", True),
    ("bot", "marong/topics/v1/kimbap-picnic.webp", "marong/topics/v1/kimbap-picnic.webp", None, "651f28436fc0bb03", True),
    ("bot", "marong/topics/v1/knitting.webp", "marong/topics/v1/knitting.webp", None, "d632dee68979ff79", True),
    ("bot", "marong/topics/v1/new-pajamas.webp", "marong/topics/v1/new-pajamas.webp", None, "ec113fabe28cac44", True),
    ("bot", "marong/topics/v1/potted-sprout.webp", "marong/topics/v1/potted-sprout.webp", None, "94a758e275d92437", True),
    ("bot", "marong/topics/v1/rain-boots.webp", "marong/topics/v1/rain-boots.webp", None, "ba3b83aa5218f12d", True),
    ("bot", "marong/topics/v1/ramen-night.webp", "marong/topics/v1/ramen-night.webp", None, "3569d5484585d8ab", True),
    ("bot", "marong/topics/v1/reading-book.webp", "marong/topics/v1/reading-book.webp", None, "6e7903958ac42f65", True),
    ("bot", "marong/topics/v1/roasted-chestnuts.webp", "marong/topics/v1/roasted-chestnuts.webp", None, "2606c06f892dac37", True),
    ("bot", "marong/topics/v1/sledding.webp", "marong/topics/v1/sledding.webp", None, "07d90cd311ed6d70", True),
    ("bot", "marong/topics/v1/snowman.webp", "marong/topics/v1/snowman.webp", None, "21b6e541d7f6b9ae", True),
    ("bot", "marong/topics/v1/stargazing.webp", "marong/topics/v1/stargazing.webp", None, "6ed3756614c71a05", True),
    ("bot", "marong/topics/v1/strawberry-cake.webp", "marong/topics/v1/strawberry-cake.webp", None, "d6c700510ba2af95", True),
    ("bot", "marong/topics/v1/striped-scarf.webp", "marong/topics/v1/striped-scarf.webp", None, "1b61f3b109238672", True),
    ("bot", "marong/topics/v1/tangerines.webp", "marong/topics/v1/tangerines.webp", None, "c66ee7e510964f02", True),
    ("bot", "marong/topics/v1/topics.json", "marong/topics/v1/topics.json", None, "41497c554e8a7e8a", True),
    ("bot", "marong/topics/v1/tteokbokki.webp", "marong/topics/v1/tteokbokki.webp", None, "f3f495032b706d87", True),
    ("bot", "marong/topics/v1/watermelon.webp", "marong/topics/v1/watermelon.webp", None, "40a171dc14dab961", True),
    ("bot", "marong/topics/v1/winter-hat.webp", "marong/topics/v1/winter-hat.webp", None, "7d1a26abb1573b23", True),
    ("bot", "tools/admin.py", "tools/admin.py", "6aad701aac919b7d", "5000ba72970c79df", False),
    ("bot", "tools/fcm_test_send.py", "tools/fcm_test_send.py", "b43122a49a892d2e", "a109b79e0729d26c", False),
    ("bot", "marong/migrations/018_call_first.sql", "marong/migrations/018_call_first.sql", None, "e57d77308fa96d69", False),
    ("call", "tools/vertex_live/call_memory.py", "call_memory.py", "e6ea2d6188ba6be0", "02b700704cccac0d", True),
    ("call", "tools/vertex_live/live_session.py", "live_session.py", "b203e3427d63a96a", "54437865cb4101f5", True),
    ("call", "tools/vertex_live/server.py", "server.py", "537ec08dc4d6efff", "ea46f592c303c749", True),
    ("call", "tools/vertex_live/static/app.js", "static/app.js", "1194bc7ca489f508", "daf9a08837a76157", True),
    ("call", "tools/vertex_live/static/index.html", "static/index.html", "d1e843b0ed68568b", "54f3d12eb482e388", True),
    ("call", "tools/vertex_live/static/style.css", "static/style.css", "00f867cba10a1f3a", "b28ea4a31adb6b5a", True),
    # MANIFEST-END
]


def h(data):
    return hashlib.sha256(data).hexdigest()[:16]


def fail(text):
    print("STOP: " + text + "; nothing changed by this step")
    sys.exit(2)


def backup_dir():
    """~/marong-deploy/<release> of the user who ran sudo; the copy kept there for rollback uses its own folder."""
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.isfile(os.path.join(here, "state.json")):
        return here
    who = os.environ.get("SUDO_USER") or "root"
    return os.path.join(pwd.getpwnam(who).pw_dir, "marong-deploy", RELEASE)


def target(root, path):
    return os.path.join(BOT if root == "bot" else CALL, path)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def state(entry):
    root, repo, path, old, new, required = entry
    full = target(root, path)
    if not os.path.isfile(full):
        if not os.path.isdir(os.path.dirname(full)) and not required:
            return "no-folder"
        return "absent"
    now = h(read(full))
    return "new" if now == new else "old" if now == old else "other:" + now


def bundle(path):
    """The bundle's files for this release, each checked against its expected hash."""
    if not path or not os.path.isfile(path):
        fail("give the bundle made by git archive")
    found = {}
    with tarfile.open(path) as tar:
        names = {m.name: m for m in tar.getmembers() if m.isfile()}
        for root, repo, path, old, new, required in FILES:
            member = names.get(repo)
            if member is None:
                fail("the bundle has no " + repo)
            data = tar.extractfile(member).read()
            if h(data) != new:
                fail("the bundle's " + repo + " is " + h(data) + ", not this release's " + new)
            found[repo] = data
        member = names.get(MIGRATION)
        if member is None:
            fail("the bundle has no " + MIGRATION)
        data = tar.extractfile(member).read()
        if h(data) != MIGRATION_NEW:
            fail("the bundle's migration is " + h(data))
        found[MIGRATION] = data
    return found


def psql_bin(name):
    found = shutil.which("psql")
    if found:
        beside = os.path.join(os.path.dirname(os.path.realpath(found)), name)
        if os.path.isfile(beside):
            return beside
    return shutil.which(name) or name


def as_postgres(args, data=None, out=None):
    return subprocess.run(["runuser", "-u", "postgres", "--"] + args, input=data, stdout=out or subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False, cwd="/")


def query(sql):
    r = as_postgres([psql_bin("psql"), "-X", "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-d", "marong", "-c", sql])
    if r.returncode:
        fail("psql: " + r.stderr.decode("utf-8", "replace").strip().splitlines()[0][:160])
    return r.stdout.decode().strip()


def db_state():
    """'2|t|t' once 018 is in: the two app_rings columns and the two new tables."""
    return query("SELECT (SELECT count(*) FROM information_schema.columns WHERE table_schema='marong' AND "
                 "table_name='app_rings' AND column_name IN ('reason','topic')), "
                 "to_regclass('marong.topic_sends') IS NOT NULL, to_regclass('marong.topic_prefs') IS NOT NULL")


def config_note():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip().startswith("MARONG_TOPICS=")]
    except OSError:
        return "config unreadable"
    return "config sets MARONG_TOPICS=" + lines[-1].split("=", 1)[1][:1] if lines else "config does not set MARONG_TOPICS"


def summary():
    counts, odd = {}, []
    for entry in FILES:
        s = state(entry)
        key = entry[0] + ":" + s.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
        if s not in ("old", "new") and not (s == "absent" and entry[3] is None):
            odd.append(entry[2] + "=" + s)
    dropin = "on" if os.path.isfile(DROPIN) and read(DROPIN).decode() == DROPIN_TEXT else \
        "other" if os.path.exists(DROPIN) else "off"
    return counts, odd, dropin


def show(label):
    counts, odd, dropin = summary()
    print(label, json.dumps(counts, sort_keys=True), "dropin=" + dropin, "odd=" + (",".join(odd) or "none"))
    return counts, odd, dropin


def blockers():
    out = []
    for entry in FILES:
        s = state(entry)
        if entry[5] and (s.startswith("other") or (s == "absent" and entry[3] is not None)):
            out.append(entry[2] + "=" + s)
    return out


def like(path, mode=None):
    """Owner, group and mode for a file written at path: the old file's, or for a new one its folder's (0644)."""
    if os.path.exists(path):
        st = os.stat(path)
        return st.st_uid, st.st_gid, mode if mode is not None else st.st_mode & 0o7777
    st = os.stat(os.path.dirname(path))
    return st.st_uid, st.st_gid, 0o644 if mode is None else mode


def make_dirs(path):
    """Create missing folders with the owner and group of the nearest existing one, mode 0755."""
    missing = []
    while not os.path.isdir(path):
        missing.append(path)
        path = os.path.dirname(path)
    st = os.stat(path)
    for folder in reversed(missing):
        os.mkdir(folder, 0o755)
        os.chown(folder, st.st_uid, st.st_gid)
        os.chmod(folder, 0o755)
    return list(reversed(missing))


def put(path, data, mode=None):
    uid, gid, perm = like(path, mode)
    tmp = path + "." + RELEASE + "-new"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chown(tmp, uid, gid)
    os.chmod(tmp, perm)
    os.replace(tmp, path)


def check(args):
    files = bundle(args[0] if args else None)
    show("before")
    print("bundle ok", len(files), "files")
    print("db 018 columns|topic_sends|topic_prefs =", db_state())
    print(config_note())
    place = backup_dir()
    while not os.path.isdir(place):
        place = os.path.dirname(place)
    print("free MB", shutil.disk_usage(place).free // 2**20,
          "db MB", int(query("SELECT pg_database_size('marong')")) // 2**20)
    print("would stop on:", ", ".join(blockers()) or "nothing")


def db_backup(args):
    bundle(args[0] if args else None)
    bk = backup_dir()
    os.makedirs(bk, mode=0o700, exist_ok=True)
    os.chmod(bk, 0o700)
    size = int(query("SELECT pg_database_size('marong')"))
    if shutil.disk_usage(bk).free < 2 * size + 200 * 2**20:
        fail("not enough free space for the database backup")
    dump = os.path.join(bk, "marong-before-018.dump")
    tmp = dump + ".part"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as out:
        r = as_postgres([psql_bin("pg_dump"), "-Fc", "-d", "marong"], out=out)
    if r.returncode:
        os.unlink(tmp)
        fail("pg_dump: " + r.stderr.decode("utf-8", "replace").strip().splitlines()[0][:160])
    os.replace(tmp, dump)
    listing = subprocess.run([psql_bin("pg_restore"), "--list", dump], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if listing.returncode:
        fail("pg_restore cannot read the backup")
    entries = sum(1 for line in listing.stdout.decode("utf-8", "replace").splitlines() if line and line[0] != ";")
    print("db backup ok MB", os.path.getsize(dump) // 2**20, "entries", entries, "sha", h(read(dump)), "at", dump)


def migrate(args):
    files = bundle(args[0] if args else None)
    if not os.path.isfile(os.path.join(backup_dir(), "marong-before-018.dump")):
        fail("run db-backup first")
    print("db before", db_state())
    r = as_postgres([psql_bin("psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", "marong"], data=files[MIGRATION])
    if r.returncode:
        fail("migration: " + r.stderr.decode("utf-8", "replace").strip().splitlines()[0][:160])
    got = db_state()
    rights = query("SELECT has_table_privilege('marong','marong.topic_sends','INSERT'), "
                   "has_table_privilege('marong','marong.topic_prefs','UPDATE'), "
                   "has_column_privilege('marong_call','marong.app_rings','topic','SELECT'), "
                   "(SELECT count(*) FROM marong.app_rings WHERE reason = 'promise')")
    print("db after", got, "rights|promise rows", rights)
    if got != "2|t|t" or not rights.startswith("t|t|t|"):
        fail("the migration did not leave what the code needs")


def apply(args):
    files = bundle(args[0] if args else None)
    show("before")
    stop = blockers()
    if stop:
        fail("a deployed file matches neither version: " + ", ".join(stop))
    if db_state() != "2|t|t":
        fail("run migrate first")
    if os.path.exists(DROPIN) and read(DROPIN).decode() != DROPIN_TEXT:
        fail("another " + os.path.basename(DROPIN) + " exists")
    bk = backup_dir()
    os.makedirs(os.path.join(bk, "files"), mode=0o700, exist_ok=True)
    os.chmod(bk, 0o700)
    record_path = os.path.join(bk, "state.json")
    record = json.load(open(record_path)) if os.path.isfile(record_path) else {"files": {}, "folders": []}
    for entry in FILES:
        root, repo, rel, old, new, required = entry
        s = state(entry)
        key = root + "/" + rel
        if key not in record["files"] and s in ("old", "absent"):
            record["files"][key] = s
            if s == "old":
                saved = os.path.join(bk, "files", root, rel)
                os.makedirs(os.path.dirname(saved), mode=0o700, exist_ok=True)
                shutil.copy2(target(root, rel), saved)
    with open(record_path, "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
    shutil.copy2(os.path.abspath(__file__), os.path.join(bk, os.path.basename(SCRIPT)))
    with open(os.path.join(bk, "rollback.sh"), "w") as f:
        f.write("#!/bin/sh\n# Put Marong back as before " + RELEASE + " (files and MARONG_TOPICS; table 018 stays).\n"
                "# Run with sudo when nobody is talking or calling.\nset -e\n"
                "python3 " + os.path.join(bk, os.path.basename(SCRIPT)) + " rollback\n"
                "systemctl daemon-reload\nsystemctl restart marong-discord\n"
                "OWNER=$(stat -c %U " + CALL + ")\n"
                "runuser -u \"$OWNER\" -- env XDG_RUNTIME_DIR=/run/user/$(id -u \"$OWNER\") "
                "systemctl --user restart marong-vertex-live\n"
                "systemctl is-active marong-discord\n")
    os.chmod(os.path.join(bk, "rollback.sh"), 0o700)
    for entry in FILES:
        root, repo, rel, old, new, required = entry
        if state(entry) not in ("old", "absent"):
            continue
        full = target(root, rel)
        for folder in make_dirs(os.path.dirname(full)):
            if folder not in record["folders"]:
                record["folders"].append(folder)
        put(full, files[repo])
    with open(record_path, "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
    if not os.path.exists(DROPIN):
        os.makedirs(os.path.dirname(DROPIN), exist_ok=True)
        put(DROPIN, DROPIN_TEXT.encode(), 0o644)
    show("after")
    print("backup", bk, "rollback", os.path.join(bk, "rollback.sh"))
    print(config_note())


def rollback(args):
    bk = backup_dir()
    record_path = os.path.join(bk, "state.json")
    if not os.path.isfile(record_path):
        fail("no record of an apply in " + bk)
    record = json.load(open(record_path))
    known = {e[0] + "/" + e[2]: e for e in FILES}
    for key, before in sorted(record["files"].items()):
        root, repo, rel, old, new, required = known[key]
        full = target(root, rel)
        if before == "old":
            saved = os.path.join(bk, "files", root, rel)
            if h(read(saved)) != old:
                fail("the backup of " + rel + " is not the old version")
            put(full, read(saved))
        elif os.path.isfile(full):
            if h(read(full)) == new:
                os.unlink(full)
            else:
                print("left in place (changed after apply):", rel)
    for folder in sorted(record["folders"], key=len, reverse=True):
        if os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
    if os.path.isfile(DROPIN) and read(DROPIN).decode() == DROPIN_TEXT:
        os.unlink(DROPIN)
    show("after rollback")
    print("now: systemctl daemon-reload, restart marong-discord and marong-vertex-live")


def main(argv):
    modes = {"check": check, "db-backup": db_backup, "migrate": migrate, "apply": apply, "rollback": rollback}
    if not argv or argv[0] not in modes:
        print("\n".join(line.strip() for line in __doc__.strip().splitlines()[4:9]))
        return 2
    if os.geteuid() != 0:
        fail("run as root (sudo)")
    modes[argv[0]](argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
