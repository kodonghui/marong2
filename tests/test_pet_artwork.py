"""Exercise the shipped AI-31 inputs, masks, response validation and usage accounting."""

import asyncio
from base64 import b64encode
from io import BytesIO
import json
from uuid import uuid4

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from PIL import Image

from marong.pet.artwork import ImageEditor, TEMPLATE_IDS, Templates
from marong.pet.candidates import fit_score
from marong.pet.sheet import head_in_box
from marong.pet.settings import IMAGE_MODELS


class BudgetFixture:
    def __init__(self):
        self.runs = []

    async def record(self, run):
        self.runs.append(run)


async def check():
    assets = Templates()
    for name in TEMPLATE_IDS:
        front, mask = assets.front(name), assets.mask(name)
        assert fit_score(front, mask) == 1
        assert head_in_box(mask, assets.head(name))
    assert len({assets.front(name) for name in TEMPLATE_IDS}) == 5
    assert fit_score(assets.front("cat"), assets.mask("dog_large")) < 0.75

    block = BytesIO()
    Image.new("RGB", (1024, 1024), "#fff").save(block, "PNG")
    calls = []

    async def edit(request):
        assert request.headers["Authorization"] == "Bearer toy-credential"
        parts = {key: value for key, value in (await request.post()).items() if key != "image[]"}
        posted = await request.post()
        files = [(value.filename, value.file.read()) for value in posted.getall("image[]")]
        calls.append((parts, files))
        assert parts["size"] == "1024x1024" and parts["background"] == "transparent"
        assert parts["output_format"] == "png" and parts["n"] == "1"
        if len(calls) == 4:
            return web.json_response({"error": {"code": "moderation_blocked"}}, status=400)
        raw = block.getvalue() if len(calls) == 3 else files[0][1]
        return web.json_response({"data": [{"b64_json": b64encode(raw).decode("ascii")}],
                                  "usage": {"input_tokens": 20, "output_tokens": 8,
                                            "input_tokens_details": {"image_tokens": 11}}})

    app = web.Application()
    app.router.add_post("/v1/images/edits", edit)
    accounting = BudgetFixture()
    traits = {"species": "dog", "breedGuess": "시험견", "petVisible": True, "rawPhoto": "private fixture"}
    model = next(iter(IMAGE_MODELS))
    job = {"member_id": uuid4()}
    async with TestServer(app) as server, ClientSession() as session:
        editor = ImageEditor(session, "toy-credential", assets, accounting, endpoint=server.make_url("/v1/images/edits"))
        preview = await editor.preview(model=model, template="dog_small", traits=traits, job=job)
        expression = await editor.expression(model=model, template="dog_small", front=preview, expression="smile", job=job)
        assert fit_score(expression, assets.mask("dog_small")) == 1
        for expected in ("unexpected_alpha", "pet_image_request_failed"):
            try:
                await editor.candidate(model=model, template="dog_small", traits=traits, note="시험", slot=1, job=job)
            except ValueError as error:
                assert str(error) == expected
            else:
                raise AssertionError(expected)

    assert json.loads(calls[0][0]["prompt"].split("\n", 1)[1])["특징표"] == {"species": "dog", "breedGuess": "시험견"}
    assert calls[0][1] == [("template.png", assets.front("dog_small")), ("style.webp", assets.style)]
    assert calls[1][1] == [("chosen.png", preview)]
    assert [item.result for item in accounting.runs] == ["ok", "ok", "rejected_by_check", "refused"]
    assert accounting.runs[0].image_input == 11
    print("AI-31: five exact masks and head boxes, reference uploads, transparency, refusal and usage passed")


if __name__ == "__main__":
    asyncio.run(check())
