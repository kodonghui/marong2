"""TC-418 with the production route, SQL, guard and synthetic providers."""

import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from psycopg.types.json import Jsonb

from marong.pet.artwork import Templates
from marong.pet.farewell import generate_letter
from marong.pet.settings import Settings
from pg import TestDB
from run_pet import make_app
from test_pet_core import fixtures
from test_pet_talk import ORIGIN, add_pet, seed


LETTER = (
    "누나, 함께 산책하던 날들을 떠올리면 마음이 따뜻해. 바람이 불 때마다 내 귀가 접혀도 "
    "누나 목소리를 들으면 괜히 꼬리가 흔들렸어. 나한테 다정하게 말을 걸어 준 순간들이 고마워. "
    "여기서는 해가 드는 자리에 편안히 누워 있어. 누나도 잠깐 햇볕을 쬐고, 천천히 쉬면서 "
    "누나의 하루를 살아가면 좋겠어. 우리 사이에 오갔던 다정함을 나는 소중하게 생각해. "
    "누나가 새로 만날 좋은 일들을 마음으로 응원할게. 같이 걸어 줘서 고마워."
)


async def scenario(admin, dsn, root):
    permitted = Settings.read({"PET_DATABASE_URL": dsn, "PET_ORIGIN": ORIGIN, "PET_MONTHLY_BUDGET_KRW": "10000",
                               "PET_MEDIA_DIR": str(root)})
    with psycopg.connect(admin) as conn:
        owner, headers = seed(conn, 1)
        stranger, outsider = seed(conn, 2)
        letter_pet, picture_pet, living = (add_pet(conn, owner) for _ in range(3))
        add_pet(conn, stranger)
        conn.execute("UPDATE pet.pets SET mode='memorial',memorial_since=now() WHERE id IN (%s,%s)",
                     (letter_pet, picture_pet))
        origin = Templates().front("dog_small")
        front = uuid4()
        key = f"{front}.png"
        (root / key).write_bytes(origin)
        conn.execute("""
            INSERT INTO pet.media(id,member_id,pet_id,kind,storage_key,content_type,bytes,sha256)
            VALUES (%s,%s,%s,'sheet_front',%s,'image/png',%s,%s)
        """, (front, owner, picture_pet, key, len(origin), sha256(origin).digest()))
        conn.execute("UPDATE pet.pets SET sheet=sheet || %s,intro=intro || %s WHERE id=%s",
                     (Jsonb({"front": str(front)}), Jsonb({"likes": "산책"}), picture_pet))
        for role in ("member", "pet"):
            message, = conn.execute("""
                INSERT INTO pet.messages(member_id,pet_id,role,kind,content) VALUES (%s,%s,%s,'chat','private fixture')
                RETURNING id
            """, (owner, letter_pet, role)).fetchone()
            conn.execute("""
                INSERT INTO pet.memory_items(member_id,pet_id,kind,text,source_message_id,heard_at)
                VALUES (%s,%s,'memory',%s,%s,now())
            """, (owner, letter_pet, f"fixture memory {role}", message))

    requests = []
    first_failed = True
    rendering = asyncio.Event()
    finish = asyncio.Event()

    async def letter(job, pet, memories):
        nonlocal first_failed
        assert memories == ["fixture memory member"]
        if first_failed:
            first_failed = False
            return "짧아"

        class Structured:
            settings = SimpleNamespace(chat_model="fixture")

            async def request(self, submitted, payload, **options):
                assert submitted is job
                assert options["entry"] == "AI-34" and payload["output_config"]["effort"] == "medium"
                assert "private fixture" not in payload["messages"][0]["content"]
                requests.append(payload)
                return LETTER if len(requests) == 2 else LETTER + " 기다릴게."

        rendering.set()
        await finish.wait()
        return await generate_letter(Structured(), job, pet, memories)

    async def image(*, model, front, scene_note, job):
        assert front == origin and scene_note == "산책" and job["pet_id"] == picture_pet
        output = BytesIO()
        Image.new("RGB", (1536, 1024), "#fbf6ee").save(output, "PNG")
        return output.getvalue()

    app = make_app(permitted, farewell_letter=letter, farewell_picture=image)
    async with TestClient(TestServer(app)) as client:
        def post(pet, kind="letter", *, member=headers, note=None):
            return client.post(f"/api/pets/{pet}/farewell", headers=member,
                               json={"kind": kind, **({} if note is None else {"sceneNote": note})})
        assert (await post(living)).status == 409
        assert (await post(letter_pet, member=outsider)).status == 404
        assert (await post(letter_pet, note="가" * 101)).status == 400
        fail = await post(letter_pet)
        assert fail.status == 503 and (await fail.json())["code"] == "farewell_failed"
        pending = asyncio.ensure_future(post(letter_pet))
        await asyncio.wait_for(rendering.wait(), timeout=5)
        try:
            assert (await post(letter_pet)).status == 503
        finally:
            finish.set()
        done = await pending
        assert done.status == 200, await done.text()
        result = await done.json()
        assert result["body"] == LETTER and result["kind"] == "farewell" and result["picture"] is None
        assert len(requests) == 2
        again = await post(letter_pet)
        assert again.status == 409 and (await again.json())["code"] == "farewell_done"
        picture = await post(picture_pet, "picture")
        assert picture.status == 200, await picture.text()
        location = (await picture.json())["picture"]
        owned = await client.get(location, headers=headers)
        assert owned.status == 200
        with Image.open(BytesIO(await owned.read())) as image_file:
            assert image_file.size == (1536, 1024) and image_file.mode == "RGB"
        assert (await client.get(location, headers=outsider)).status == 404
        pet = await client.get(f"/api/pets/{picture_pet}", headers=headers)
        assert (await pet.json())["farewellDone"] is True
        with psycopg.connect(admin) as conn:
            assert conn.execute("SELECT count(*) FROM pet.diary_entries WHERE kind='farewell'").fetchone() == (2,)
            assert conn.execute("SELECT count(*) FROM pet.quota_holds WHERE member_id=%s", (owner,)).fetchone() == (0,)


if __name__ == "__main__":
    db = TestDB()
    try:
        with TemporaryDirectory() as folder:
            asyncio.run(scenario(*fixtures(db), Path(folder)))
    finally:
        db.close()
    print("TC-418: letter guard and rewrite, retry, single execution, opaque picture, private media and unchanged quota")
