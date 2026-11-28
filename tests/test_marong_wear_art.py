"""The artwork helper has a strict request limit and never needs real credentials in tests."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import draw_marong_wear


class ArtHelperTest(unittest.TestCase):
    def test_budget_stops_before_another_request(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {'usage':{'input_tokens_details':{'text_tokens':200000,'image_tokens':0},
                                 'output_tokens_details':{'image_tokens':0}}, 'data':[{'b64_json':'invalid'}]}
        class Client:
            calls = 0
            def __init__(self, **_): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_, **__):
                type(self).calls += 1
                return Response()
        prices=json.loads((draw_marong_wear.ROOT/'marong/pet/prices.json').read_text())['models']
        model=next(name for name, entry in prices.items() if entry['kind']=='image')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY':'fixture','MARONG_WEAR_IMAGE_MODEL':model}), \
                patch.object(draw_marong_wear.httpx,'Client',Client), patch.object(sys,'argv',['draw','--out',folder]):
            self.assertEqual(draw_marong_wear.main(),1)
            self.assertEqual(Client.calls,1)
            self.assertEqual(float(json.loads((Path(folder)/'usage.json').read_text())['cost_usd']),1)

    def test_maximum_two_calls_per_item_and_no_restart(self):
        buf = BytesIO()
        image = Image.new('RGBA',(1024,1024))
        image.putpixel((500,500),(20,30,40,255))
        image.save(buf,'PNG')
        payload = base64.b64encode(buf.getvalue()).decode()
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'data':[{'b64_json':payload}], 'usage':{}}
        class Client:
            calls = 0
            def __init__(self, **_): pass
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_, **__):
                self.calls += 1
                if self.calls % 2:
                    raise draw_marong_wear.httpx.ConnectError('fixture')
                return Response()
        prices = json.loads((draw_marong_wear.ROOT / 'marong/pet/prices.json').read_text())['models']
        model = next(name for name, entry in prices.items() if entry['kind'] == 'image')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENAI_API_KEY':'fixture','MARONG_WEAR_IMAGE_MODEL':model}), \
                patch.object(draw_marong_wear.httpx,'Client',Client), patch.object(sys,'argv',['draw','--out',folder]):
            self.assertEqual(draw_marong_wear.main(),0)
            self.assertEqual(json.loads((Path(folder)/'usage.json').read_text())['calls'],8)
            with self.assertRaises(SystemExit):
                draw_marong_wear.main()


if __name__ == '__main__':
    unittest.main()
