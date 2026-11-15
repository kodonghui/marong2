"""Sends one test message to one phone through FCM with the bot's own sender (marong/fcm.py), for the emulator and phone
tests of the Marong app (docs/app-chat.md TC-135, docs/app-ring.md TC-147).

    python tools/fcm_test_send.py KEY_FILE proactive|reply|reminder|missed_call TEXT < fid.txt
    python tools/fcm_test_send.py KEY_FILE ring [RING_ID] < fid.txt

The FID comes on standard input, so it stays out of the command line and the shell history. The message is the one the
bot sends for that kind (channel, time to live, the page a tap opens; a ring is data only, with a new ring id unless
one is given to send the same ring again). It prints the send result (ok, gone, auth, failed) and, for a ring, the
ring id; never the FID, the text, the key or a token. Send only to your own test device, with made-up text.
"""
import asyncio
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from marong import fcm  # noqa: E402

TALK, REMINDER = "marong_talk", "marong_reminder"
KINDS = {  # kind: (channel, ttl_s, open path), as discord_dm.py, app_chat.py and app_delivery.py send them
    "proactive": (TALK, 7200, "/chat/"),
    "reply": (TALK, 3600, "/chat/"),
    "reminder": (REMINDER, 3600, "/chat/"),
    "missed_call": (TALK, 3600, "/"),
}


async def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in (*KINDS, "ring") or (argv[1] != "ring" and len(argv) < 3):
        print("\n".join(line.strip() for line in __doc__.strip().splitlines()[3:5]), file=sys.stderr)
        return 2
    key, kind = Path(argv[0]), argv[1]
    ring_id = None
    if kind == "ring":
        try:
            ring_id = str(uuid.UUID(argv[2])) if len(argv) > 2 else str(uuid.uuid4())
        except ValueError:
            print("the ring id is not a UUID", file=sys.stderr)
            return 2
    fid = sys.stdin.readline().strip()
    if not fid:
        print("no FID on standard input", file=sys.stderr)
        return 2
    sender = fcm.FCM(fcm.ServiceAccount.load(key))
    try:
        if ring_id:
            print(f"ring {ring_id}")
            message = fcm.ring(fid, ring_id)
        else:
            channel, ttl_s, open_path = KINDS[kind]
            message = fcm.notice(fid, kind, " ".join(argv[2:]), channel=channel, ttl_s=ttl_s, open_path=open_path)
        result = await sender.send(message)
    finally:
        await sender.close()
    print(f"{kind} {result}")
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
