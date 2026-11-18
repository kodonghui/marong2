"""A single, explicitly requested memorial letter or picture per pet (SPEC-340)."""

import asyncio
import json
from hashlib import sha256
from pathlib import Path
import tempfile
from uuid import uuid4

from aiohttp import web

from .account import require_overseas
from .creations import media_url
from .export import under
from .http import CONFIG, POOL, Problem, body_json, require_member, uuid_param
from .images import landscape_png
from .lifecycle import lock_pet
from .quota import quota_day
from .replies import GUIDE, bad_reply, normalized


LETTER = "pet-farewell-v1"
AGAIN = tuple(map(normalized, ("다시 올게", "기다릴게", "다시 돌아올게", "또 만나러 갈게")))
LETTER_GUIDE = GUIDE + (
    " 작별 편지를 200~500자로 써. 평안함과 고마움을 전하고 회원의 앞날을 응원해. "
    "붙잡거나 다시 온다고 약속하지 마. 회원이 알려 준 기억만 사용해."
)


def letter_ok(value):
    return (not bad_reply(value) and 200 <= len(value.strip()) <= 500
            and not any(phrase in normalized(value) for phrase in AGAIN))


def entry_view(row, *, drawing=False):
    return {"date": row["day"].isoformat(), "kind": row["kind"], "status": row["status"],
            "title": row["title"], "weather": row["weather"], "body": row["body"], "mood": row["mood"],
            "composite": row["composite"], "picture": media_url(row["picture_id"]) if row["picture_id"] else None,
            "redrawsLeft": 2 - row["redraws"],
            "drawing": drawing, "stickers": row["stickers"]}


async def generate_letter(model, job, pet, memories):
    data = {"아이": pet["name"], "아이 소개": pet["intro"],
            "무지개다리를 건넌 날": pet["passed_on"].isoformat() if pet["passed_on"] else None,
            "회원이 알려 준 기억": memories}
    system = LETTER_GUIDE
    for _ in range(2):
        payload = {"model": model.settings.chat_model, "max_tokens": 1500,
                   "system": system, "output_config": {"effort": "medium"},
                   "messages": [{"role": "user", "content": json.dumps(data, ensure_ascii=False)}]}
        output = await model.request(job, payload, validate=letter_ok, entry="AI-34", kind="letter",
                                     purpose="farewell", version=LETTER, timeout=55, effort="medium")
        if output is None:
            break
        if letter_ok(output):
            return output.strip()
        system = LETTER_GUIDE + " 이전 초안은 검사에 걸렸어. 길이와 약속 표현을 확인해 다시 써."
    raise ValueError("pet_farewell_letter_rejected")


async def reserve(pool, member, pet_id, kind):
    async with pool.connection() as conn, conn.transaction():
        pet = await lock_pet(conn, member, pet_id)
        if pet["mode"] != "memorial" or pet["status"] != "active":
            raise Problem("wrong_state")
        exists = await conn.execute(
            "SELECT 1 FROM pet.diary_entries WHERE member_id=%s AND pet_id=%s AND kind='farewell'", (member, pet_id),
        )
        if await exists.fetchone():
            raise Problem("farewell_done")
        await require_overseas(conn, member)
        active = await conn.execute("""
            SELECT 1 FROM pet.jobs WHERE member_id=%s AND pet_id=%s
            AND kind='farewell' AND status='running' AND lease_until>now()
        """, (member, pet_id))
        if await active.fetchone():
            raise Problem("farewell_failed")
        made = await conn.execute("""
            INSERT INTO pet.jobs(kind,member_id,pet_id,status,attempts,started_at,lease_until)
            VALUES ('farewell',%s,%s,'running',1,now(),now()+interval '2 minutes')
            RETURNING id,member_id,pet_id,lease_until,started_at
        """, (member, pet_id))
        job = await made.fetchone()
        if kind == "letter":
            cur = await conn.execute("""
                SELECT i.text FROM pet.memory_items i JOIN pet.messages m ON m.id=i.source_message_id
                  AND m.member_id=i.member_id AND m.pet_id=i.pet_id AND m.role='member'
                WHERE i.member_id=%s AND i.pet_id=%s AND i.status='current' ORDER BY i.heard_at DESC LIMIT 20
            """, (member, pet_id))
            return job, pet, [row["text"] for row in await cur.fetchall()]
        cur = await conn.execute("""
            SELECT storage_key FROM pet.media WHERE id::text=%s AND member_id=%s AND pet_id=%s AND kind='sheet_front'
        """, (pet["sheet"].get("front"), member, pet_id))
        front = await cur.fetchone()
        return job, pet, front["storage_key"] if front else None


async def finalize(pool, job, pet, letter, image, root):
    member, pet_id = job["member_id"], job["pet_id"]
    final = None
    try:
        async with pool.connection() as conn, conn.transaction():
            current = await lock_pet(conn, member, pet_id)
            if (current["status"] != "active" or current["mode"] != "memorial"
                    or current["memorial_since"] != pet["memorial_since"]):
                raise Problem("wrong_state")
            await require_overseas(conn, member)
            reserved = await conn.execute("""
                UPDATE pet.jobs SET status='done',finished_at=now(),lease_until=NULL
                WHERE id=%s AND status='running' AND lease_until=%s AND lease_until>now() RETURNING id
            """, (job["id"], job["lease_until"]))
            if not await reserved.fetchone():
                raise Problem("farewell_failed")
            ident = None
            if image is not None:
                ident = uuid4()
                key = f"scenes/{ident}.png"
                final = under(root, key)
                final.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=final.parent, delete=False) as scratch:
                    temp = Path(scratch.name)
                    try:
                        scratch.write(image)
                    except Exception:
                        scratch.close()
                        temp.unlink(missing_ok=True)
                        raise
                try:
                    temp.replace(final)
                finally:
                    temp.unlink(missing_ok=True)
                await conn.execute("""
                    INSERT INTO pet.media(id,member_id,pet_id,kind,storage_key,content_type,bytes,width,height,sha256)
                    VALUES (%s,%s,%s,'farewell',%s,'image/png',%s,1536,1024,%s)
                """, (ident, member, pet_id, key, len(image), sha256(image).digest()))
            created = await conn.execute("""
                INSERT INTO pet.diary_entries(member_id,pet_id,kind,day,status,title,body,picture_id)
                VALUES (%s,%s,'farewell',%s,'ready','마지막 장',%s,%s) RETURNING *
            """, (member, pet_id, quota_day(job["started_at"]), letter, ident))
            result = await created.fetchone()
        return result
    except Exception:
        if final is not None:
            final.unlink(missing_ok=True)
        raise


def register(app, budget, *, letter_model=None, picture_model=None):
    async def farewell(req):
        member = (await require_member(req))["id"]
        pet_id = uuid_param(req.match_info["id"])
        values = await body_json(req)
        kind, note = values.get("kind"), values.get("sceneNote", "")
        if (kind not in ("letter", "picture") or not set(values) <= {"kind", "sceneNote"} or not isinstance(note, str)
                or len(note) > 100 or any(ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in note)):
            raise Problem("invalid_input")
        pool = app[POOL]
        job, pet, evidence = await reserve(pool, member, pet_id, kind)
        root = app[CONFIG].media_dir.resolve()
        try:
            letter, image = None, None
            if kind == "letter":
                if letter_model is None:
                    raise Problem("farewell_failed")
                async with asyncio.timeout(60):
                    letter = await letter_model(job, pet, evidence)
                    if not letter_ok(letter):
                        raise ValueError("pet_farewell_letter_rejected")
            else:
                await app[budget].allow("farewell")
                if picture_model is None or evidence is None:
                    raise Problem("farewell_failed")
                front = await asyncio.to_thread(under(root, evidence).read_bytes)
                settings = app[CONFIG]
                scene = note.strip() or pet["intro"]["likes"]
                async with asyncio.timeout(90):
                    for model in filter(None, (settings.image_model, settings.image_fallback_model)):
                        try:
                            raw = await picture_model(model=model, front=front, scene_note=scene, job=job)
                            image = await asyncio.to_thread(landscape_png, raw)
                            break
                        except Exception:
                            continue
                if image is None:
                    raise Problem("farewell_failed")
            work = asyncio.create_task(finalize(pool, job, pet, letter, image, root))
            try:
                result = await asyncio.shield(work)
            except asyncio.CancelledError:
                await work
                raise
        except (Exception, asyncio.CancelledError) as error:
            async with pool.connection() as conn:
                await conn.execute("""
                    UPDATE pet.jobs SET status='failed',error_code='farewell_failed',finished_at=now(),lease_until=NULL
                    WHERE id=%s AND status='running' AND lease_until=%s
                """, (job["id"], job["lease_until"]))
            if isinstance(error, (Problem, asyncio.CancelledError)):
                raise
            raise Problem("farewell_failed") from None
        return web.json_response(entry_view(result))

    app.router.add_post("/api/pets/{id}/farewell", farewell)
