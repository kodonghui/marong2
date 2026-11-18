"""Validate and mask creation photos locally before writing sanitized images."""

import asyncio
import os
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from math import ceil, floor
from threading import Lock
from uuid import uuid4

from aiohttp import BodyPartReader, web
from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg.types.json import Jsonb

from .account import require_overseas
from .creations import OPEN, view
from .http import CONFIG, POOL, Problem, require_member
from .log import logger

MAX_PHOTO = 8 * 1024 * 1024
MAX_BODY = 25 * 1024 * 1024
MAX_SIDE = 4096
FACE_SCORE = 0.6
MASK = (158, 158, 158)


@dataclass(frozen=True)
class Photo:
    png: bytes
    width: int
    height: int
    faces: int


def load_detector(path):
    if not path:
        return None
    try:
        import cv2
        import numpy as np

        detector = cv2.FaceDetectorYN.create(path, "", (320, 320), FACE_SCORE)
    except (ImportError, OSError, ValueError, RuntimeError):
        logger.warning("pet_photo_detector_unavailable")
        return None
    except cv2.error:
        logger.warning("pet_photo_detector_unavailable")
        return None

    lock = Lock()

    def detect(image):
        rgb = np.asarray(image)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        with lock:
            detector.setInputSize(image.size)
            _, faces = detector.detect(bgr)
        if faces is None:
            return []
        return [tuple(map(float, face[:4])) for face in faces if face[-1] >= FACE_SCORE]

    return detect


def sanitize(raw, number, detect):
    error = Problem("invalid_photo", extra={"photo": number})
    try:
        with Image.open(BytesIO(raw)) as source:
            if (source.format not in {"JPEG", "PNG", "WEBP"} or max(source.size) > MAX_SIDE
                    or getattr(source, "n_frames", 1) != 1):
                raise error
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.info.clear()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise error from None

    try:
        boxes = detect(image)
    except Exception:
        logger.warning("pet_photo_detector_failed")
        raise Problem("photo_check_unavailable") from None
    count = 0
    for x, y, width, height in boxes:
        left = max(0, floor(x - width * 0.2))
        top = max(0, floor(y - height * 0.2))
        right = min(image.width, ceil(x + width * 1.2))
        bottom = min(image.height, ceil(y + height * 1.2))
        if left < right and top < bottom:
            image.paste(MASK, (left, top, right, bottom))
            count += 1
    output = BytesIO()
    image.save(output, format="PNG")
    return Photo(output.getvalue(), image.width, image.height, count)


async def read_form(req):
    if req.content_length is not None and req.content_length > MAX_BODY:
        raise Problem("too_large")
    if req.content_type != "multipart/form-data" or req.headers.get("Content-Encoding"):
        raise Problem("invalid_input")

    kind = None
    photos = []
    total = 0
    try:
        form = await req.multipart()
        async for field in form:
            if not isinstance(field, BodyPartReader) or field.headers.get("Content-Transfer-Encoding"):
                raise Problem("invalid_input")
            if field.name == "kind" and kind is None and field.filename is None:
                limit = len(b"memorial")
                error = Problem("invalid_input")
            elif field.name == "photos" and field.filename and len(photos) < 3:
                limit = MAX_PHOTO
                error = Problem("invalid_photo", extra={"photo": len(photos) + 1})
            else:
                raise Problem("invalid_input")
            payload = bytearray()
            oversized = False
            while chunk := await field.read_chunk():
                total += len(chunk)
                if total > MAX_BODY:
                    raise Problem("too_large")
                if oversized or len(payload) + len(chunk) > limit:
                    if req.content_length is not None or limit != MAX_PHOTO:
                        raise error
                    # For a chunked request, continue counting without buffering.
                    oversized = True
                    continue
                payload.extend(chunk)
            if limit == MAX_PHOTO:
                if not payload or oversized:
                    raise error
                photos.append(payload)
            else:
                kind = bytes(payload)
    except (ValueError, AssertionError) as error:
        raise Problem("invalid_input") from error
    if kind not in {b"living", b"memorial"} or not photos:
        raise Problem("invalid_input")
    return kind.decode("ascii"), photos


async def require_capacity(conn, member_id):
    result = await conn.execute(
        f"""SELECT (SELECT count(*) FROM pet.pets WHERE member_id=%s) AS pets,
                  (SELECT count(*) FROM pet.creations WHERE member_id=%s
                   AND state NOT IN {OPEN}) AS open""",
        (member_id, member_id),
    )
    counts = await result.fetchone()
    if counts["pets"] + counts["open"] >= 5:
        raise Problem("pet_limit")
    if counts["open"] >= 3:
        raise Problem("too_many_creations")


async def save_photos(pool, root, member_id, kind, photos):
    written = []
    try:
        async with pool.connection() as conn, conn.transaction():
            # Consent revocation, a second upload and member erasure serialize on this row.
            result = await conn.execute("SELECT status FROM pet.members WHERE id=%s FOR UPDATE", (member_id,))
            member = await result.fetchone()
            if not member or member["status"] != "active":
                raise Problem("unauthenticated")
            await require_overseas(conn, member_id)
            await require_capacity(conn, member_id)
            result = await conn.execute(
                """INSERT INTO pet.creations(member_id,kind,faces_masked) VALUES (%s,%s,%s)
                RETURNING *""",
                (member_id, kind, sum(photo.faces for photo in photos)),
            )
            row = await result.fetchone()
            directory = root / "photos"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            for number, photo in enumerate(photos, 1):
                ident = uuid4()
                key = f"photos/{ident}.png"
                path = root / key
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as image:
                    written.append(path)
                    image.write(photo.png)
                await conn.execute(
                    """INSERT INTO pet.media(id,member_id,creation_id,kind,storage_key,content_type,
                       bytes,width,height,sha256,meta,delete_after)
                    VALUES (%s,%s,%s,'photo',%s,'image/png',%s,%s,%s,%s,%s,%s)""",
                    (ident, member_id, row["id"], key, len(photo.png), photo.width, photo.height,
                     sha256(photo.png).digest(), Jsonb({"faces_masked": photo.faces, "photo": number}), row["expires_at"]),
                )
            await conn.execute("INSERT INTO pet.jobs(kind,member_id,creation_id) VALUES ('traits',%s,%s)",
                               (member_id, row["id"]))
    except BaseException:
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error("pet_photo_rollback_unlink_failed")
        raise
    return row


def register(app, detect):
    slots = asyncio.Semaphore(2)

    async def create(req):
        member = await require_member(req)
        pool = req.app[POOL]
        member_id = member["id"]
        async with pool.connection() as conn:
            await require_overseas(conn, member_id)
            await require_capacity(conn, member_id)
        if detect is None:
            raise Problem("photo_check_unavailable")
        async with slots:
            kind, originals = await read_form(req)
            photos = await asyncio.to_thread(
                lambda: [sanitize(raw, index, detect) for index, raw in enumerate(originals, 1)]
            )
            row = await save_photos(pool, req.app[CONFIG].media_dir, member_id, kind, photos)
        return web.json_response(view(row), status=202)

    app.router.add_post("/api/creations", create)
