"""Character creation and wardrobe with a fake vision reader and renderer."""

from decimal import Decimal
from io import BytesIO
from pathlib import Path
import secrets
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, PngImagePlugin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marong.app_chat import AppChat
from marong.app_push import AppPush
from marong.app_session import AppSessions, COOKIE
from marong.character.artwork import PROMPT_VERSION, ImageEditor
from marong.character.graphics import EXPRESSIONS, TEMPLATE_IDS, Templates, alpha, fit_score, head_in_box
from marong.character.http import CharacterAPI
from marong.character.worker import CharacterWorker, photo_selection
from marong.unified_store import UnifiedStore
from pg import TestDB
from run_app import RoomLocks


BASE = "/chat/api/characters"
ORIGIN = "https://fixture.invalid"
OBSERVED = {
    "species": "dog", "coatColors": ["크림"], "pattern": "단색", "earShape": "선 귀",
    "eyeColor": "갈색", "build": "작음", "furLength": "짧음", "breedGuess": "", "patternNotes": "",
    "distinctive": "", "petVisible": True, "multiplePets": False, "confidence": "high",
    "bestPhoto": 2, "petBox": [0.2, 0.1, 0.5, 0.8],
}


class TestCharacter(unittest.IsolatedAsyncioTestCase):
    def test_bad_photo_box_preserves_the_trait_job(self):
        with self.assertLogs("marong.character.worker", level="INFO") as logs:
            picked = photo_selection(21, ["photo_1", "photo_2"], 2, [0.9, 0.9, 0.5, 0.5])
        self.assertEqual(picked, {"photo": "photo_1", "box": [0, 0, 1, 1]})
        self.assertIn("pet_box_fallback character=21", logs.output[0])

    def test_all_five_templates_match_their_masks(self):
        templates = Templates()
        for template in TEMPLATE_IDS:
            front = templates.front(template)
            self.assertEqual(fit_score(front, templates.mask(template)), 1)
            self.assertTrue(head_in_box(alpha(front), templates.head(template)))

    async def test_from_photo_to_retired_with_two_accounts(self):
        db = TestDB()
        self.addCleanup(db.close)
        db.apply_unified_prerequisites()
        db.apply_unified()
        db.apply_pet_app_prerequisites()
        db.apply_pet_app()
        directory = self.enterContext(tempfile.TemporaryDirectory())
        store = UnifiedStore(db.app_url)
        await store.open(wait=True)
        self.addAsyncCleanup(store.close)
        sessions = AppSessions(store.pool, secrets.token_bytes(32), contact_schedule=(2, 8, 22))

        async def owner(name):
            invite, _ = await sessions.create_invite("join")
            login = await sessions.join(invite, name, "웹")
            return {"Cookie": f"{COOKIE}={login.token}", "Origin": ORIGIN}

        a, b = await owner("Fixture A"), await owner("Fixture B")
        chat = AppChat(store, SimpleNamespace(friend_cards=None), RoomLocks(), None, AppPush(store), origin=ORIGIN,
                       sessions=sessions, authentication="session")
        detector = lambda _image: [(8, 8, 10, 12)]
        chat.characters = api = CharacterAPI(chat, directory, detector)
        templates = Templates()
        model_options = SimpleNamespace(vision_model="fixture_vision", image_model="fixture_image")

        async def identify(photos, job):
            self.assertEqual(len(photos), 2)
            with Image.open(BytesIO(photos[0])) as prepared:
                self.assertEqual(prepared.format, "JPEG")
                self.assertNotIn("exif", prepared.info)
                self.assertTrue(all(140 <= value <= 175 for value in prepared.getpixel((13, 14))))
            return dict(OBSERVED)

        draw = AsyncMock(return_value=templates.front("dog_small"))
        models = ImageEditor(None, "", templates, None)
        models.request = draw
        worker = CharacterWorker(api, templates, identify, models, model_options,
                                 SimpleNamespace(prices={model_options.vision_model: {}, model_options.image_model: {}}))
        async with TestClient(TestServer(chat.web_app())) as client:
            create = await client.post(BASE, json={"kind": "dog"}, headers=a)
            self.assertEqual(create.status, 201)
            created = (await create.json())["character"]
            target = BASE + f"/{created['id']}"
            self.assertEqual((await client.get(target, headers=b)).status, 404)
            self.assertEqual((await client.post(target + "/candidates", headers=a)).status, 409)
            self.assertEqual((await client.get(target + "/try", headers=a)).status, 409)
            def upload():
                form = FormData()
                metadata = PngImagePlugin.PngInfo()
                metadata.add_text("fixture", "stripped")
                for size, color in [((80, 80), (30, 50, 100)), ((1800, 1800), (200, 20, 40))]:
                    photo = BytesIO()
                    Image.new("RGB", size, color).save(photo, "PNG", pnginfo=metadata)
                    form.add_field("photos", photo.getvalue(), filename="fixture.png", content_type="image/png")
                return form

            request = await client.put(target + "/photos", data=upload(), headers=a)
            self.assertEqual(request.status, 202)
            self.assertEqual((await client.delete(target, headers=a)).status, 409)
            self.assertTrue(await worker.step())
            info = (await (await client.get(target, headers=a)).json())["character"]
            self.assertEqual(info["stage"], "traits")
            self.assertEqual(info["template"], "dog_small")
            self.assertFalse({"bestPhoto", "petBox"} & info["traits"].keys())
            query = "SELECT photo_pick FROM marong.characters WHERE id=%s"
            ident = (created["id"],)
            selected = {"photo": "photo_2", "box": OBSERVED["petBox"]}
            self.assertEqual(db.admin(query, ident), [(selected,)])
            trait = await client.patch(target + "/traits", headers=a, json={
                "traits": info["traits"], "template": "dog_small", "tone": "짧게 말해 줘",
            })
            self.assertEqual(trait.status, 200)
            self.assertEqual(db.admin(query, ident), [(selected,)])
            lost = next(Path(directory).rglob("photo_2.jpg"))
            lost.unlink()
            self.assertEqual((await client.post(target + "/preview", headers=a)).status, 202)
            self.assertTrue(await worker.step())
            failed = (await (await client.get(target, headers=a)).json())["character"]
            self.assertEqual(failed["stage"], "preview")
            self.assertEqual(failed["job"], {"step": "preview", "state": "failed", "error": "photo_missing"})
            draw.assert_not_awaited()
            self.assertEqual((await client.put(target + "/photos", data=upload(), headers=a)).status, 202)
            self.assertTrue(await worker.step())
            self.assertEqual((await client.patch(target + "/traits", headers=a, json={
                "traits": info["traits"], "template": "dog_small", "tone": "짧게 말해 줘",
            })).status, 200)
            self.assertEqual((await client.post(target + "/preview", headers=a)).status, 202)
            self.assertTrue(await worker.step())
            self.assertEqual((await client.post(target + "/candidates", headers=a)).status, 202)
            self.assertTrue(await worker.step())
            purpose, _, prompt, references, _ = draw.await_args.args
            self.assertEqual(purpose, "candidate")
            self.assertEqual(PROMPT_VERSION, "pet-artwork-v2")
            self.assertIn("Use the sitting front pose", prompt)
            self.assertNotIn("bestPhoto", prompt)
            self.assertNotIn("petBox", prompt)
            self.assertEqual([item[0] for item in references], ["pet.png", "template.png", "style.webp"])
            self.assertEqual(references[1][1], templates.front("dog_small"))
            self.assertEqual(references[2][1], templates.style)
            with Image.open(BytesIO(references[0][1])) as cropped:
                self.assertEqual(cropped.format, "PNG")
                self.assertEqual(max(cropped.size), 1024)
                self.assertLess(cropped.width, cropped.height)
                self.assertEqual(cropped.info, {})
                self.assertGreater(cropped.getpixel((30, 30))[0], 180)
            info = (await (await client.get(target, headers=a)).json())["character"]
            self.assertEqual(info["regenLeft"], 2)
            draw.side_effect = ValueError("image_refused")
            rejected_job = await client.post(target + "/candidates", headers=a)
            self.assertEqual(rejected_job.status, 202)
            self.assertTrue(await worker.step())
            info = (await (await client.get(target, headers=a)).json())["character"]
            self.assertEqual(info["job"]["state"], "failed")
            self.assertEqual(info["regenLeft"], 2)

            draw.side_effect = None
            for remaining in (1, 0):
                regenerate = await client.post(target + "/candidates", headers=a)
                self.assertEqual(regenerate.status, 202)
                self.assertTrue(await worker.step())
                info = (await (await client.get(target, headers=a)).json())["character"]
                self.assertEqual(info["job"]["state"], "done")
                self.assertEqual(info["regenLeft"], remaining)
            limit = await client.post(target + "/candidates", headers=a)
            self.assertEqual(limit.status, 409)
            self.assertEqual((await limit.json())["code"], "no_regen_left")

            chat.admin.email_hash = "a" * 64
            chat.access = SimpleNamespace(check=AsyncMock(return_value=("ok", chat.admin.email_hash)))
            db.admin("""UPDATE marong.character_jobs SET cost_usd=16
                        WHERE character_id=%s AND step='preview' AND state='done'""",
                     (created["id"],))
            admin = await client.get("/chat/admin/", headers={"Cf-Access-Jwt-Assertion": "fixture"})
            self.assertIn("이번 달 그림 예산 사용률 80%", await admin.text())
            db.admin("""UPDATE marong.character_jobs SET cost_usd=20
                        WHERE character_id=%s AND step='preview' AND state='done'""",
                     (created["id"],))
            self.assertEqual((await client.post(BASE, json={"kind": "cat"}, headers=a)).status, 409)
            self.assertEqual((await client.post(target + "/candidates", headers=a)).status, 409)
            self.assertEqual((await client.post(target + "/pick", json={"slot": "candidate_2"}, headers=a)).status, 202)
            draw.reset_mock()
            self.assertTrue(await worker.step())
            self.assertEqual(draw.await_count, len(EXPRESSIONS))
            for request in draw.await_args_list:
                purpose, _, prompt, references, _ = request.args
                self.assertEqual(purpose, "expression")
                self.assertIn("이 아이의 눈매와 얼굴 느낌", prompt)
                self.assertEqual([item[0] for item in references], ["chosen.png"])
            self.assertEqual(db.admin(query, ident), [(None,)])
            info = (await (await client.get(target, headers=a)).json())["character"]
            self.assertEqual(info["stage"], "name")
            self.assertGreaterEqual(info["images"].keys(), {"front", "preview", *EXPRESSIONS})
            self.assertFalse(any(key.startswith("photo_") for key in info["images"]))
            self.assertTrue(not any(Path(directory).rglob("photo_*.jpg")))
            self.assertEqual((await client.patch(target, json={"name": "초코"}, headers=a)).status, 200)
            self.assertEqual((await client.get(target + "/try", headers=a)).status, 200)
            applied = await client.patch("/chat/api/profile/character", json={"characterId": created["id"]}, headers=a)
            self.assertEqual(applied.status, 200)
            self.assertEqual((await applied.json())["botName"], "초코")
            image = await client.get(target + "/images/front", headers=a)
            self.assertEqual(image.status, 200)
            self.assertEqual(image.headers["Cache-Control"], "private, max-age=0")
            self.assertEqual((await client.get(target + "/images/front", headers=b)).status, 404)
            self.assertEqual((await client.delete(target, headers=a)).status, 204)
            result = await (await client.get("/chat/api/profile", headers=a)).json()
            self.assertEqual((result["botName"], result["character"]), ("마롱이", None))
            self.assertFalse(any(Path(directory).rglob("*.png")))


if __name__ == "__main__":
    unittest.main()
