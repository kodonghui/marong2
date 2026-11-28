"""Generate the four approved default-character body layers, with no secret output.

Requires an explicitly configured OPENAI_API_KEY and MARONG_WEAR_IMAGE_MODEL.
Outputs only PNGs and an aggregate usage record in the requested directory.
"""
import argparse
import base64
from io import BytesIO
from decimal import Decimal
import json
import os
from pathlib import Path

import httpx
from PIL import Image


ITEMS = ('oat-sweater', 'blue-raincoat', 'forest-vest', 'apricot-apron')
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    key = os.getenv('OPENAI_API_KEY')
    model = os.getenv('MARONG_WEAR_IMAGE_MODEL')
    if not key or not model:
        parser.error('OPENAI_API_KEY and MARONG_WEAR_IMAGE_MODEL must be configured')
    prices = json.loads((ROOT / 'marong/pet/prices.json').read_text(encoding='utf-8'))['models']
    if model not in prices or prices[model].get('kind') != 'image':
        parser.error('MARONG_WEAR_IMAGE_MODEL must be the approved image model')
    args.out.mkdir(parents=True, exist_ok=True)
    if any((args.out / f'{ident}.png').exists() for ident in ITEMS) or (args.out / 'usage.json').exists():
        raise SystemExit('output already exists; use an empty output directory')
    face = (ROOT / 'marong/call/static/face/v1/01-neutral.webp').read_bytes()
    catalog = ROOT / 'marong/decor/v1'
    calls, ok, usages, cost, estimated_calls = 0, 0, [], Decimal(0), 0
    log = args.out / 'usage.json'
    def record():
        log.write_text(json.dumps({'calls':calls,'completed':ok,'usage':usages,'cost_usd':str(cost),
                                   'estimated_calls':estimated_calls}), encoding='utf-8')
    record()
    with httpx.Client(timeout=120) as client:
        for ident in ITEMS:
            target = args.out / f'{ident}.png'
            thumb = (catalog / ident / 'thumb.webp').read_bytes()
            for _ in range(2):
                if cost + Decimal('0.025') > Decimal('1'):
                    print('budget limit reached', flush=True)
                    return 1
                calls += 1
                estimated_calls += 1
                cost += Decimal('0.025')  # Reserve an estimate before a call, including a timeout or crash.
                record()
                try:
                    response = client.post('https://api.openai.com/v1/images/edits',
                        headers={'Authorization': f'Bearer {key}'},
                        data={'model':model, 'n':'1', 'size':'1024x1024', 'quality':'low', 'background':'transparent',
                              'prompt':'The first reference is the character and the second reference is a clothing item. '
                              'Draw only this same clothing item as it would fit this character, without the character. '
                              'Transparent background, no text, no people, no additional objects.'},
                        files=[('image[]', ('face.webp', face, 'image/webp')),
                               ('image[]', ('item.webp', thumb, 'image/webp'))])
                    response.raise_for_status()
                    body = response.json()
                    usage = body.get('usage') or {}
                    usages.append(usage)
                    inputs = usage.get('input_tokens_details') or {}
                    outputs = usage.get('output_tokens_details') or {}
                    counts = (inputs.get('text_tokens'), inputs.get('image_tokens'), outputs.get('image_tokens', usage.get('output_tokens')))
                    if all(type(value) is int and value >= 0 for value in counts):
                        usd = prices[model]['usd']
                        actual = sum(Decimal(value) * Decimal(str(usd[key])) for value, key in zip(counts, ('text_input','image_input','image_output'))) / Decimal(1000000)
                        cost += actual - Decimal('0.025')
                        estimated_calls -= 1
                    record()
                    data = base64.b64decode(body['data'][0]['b64_json'], validate=True)
                    with Image.open(BytesIO(data)) as image:
                        image.load()
                        if (image.size != (1024,1024) or image.mode != 'RGBA' or
                                image.getchannel('A').getextrema()[0] != 0 or image.getchannel('A').getbbox() is None):
                            raise ValueError('transparent PNG required')
                        image.save(target, 'PNG')
                    ok += 1
                    record()
                    break
                except (httpx.HTTPError, ValueError, OSError, KeyError, IndexError, TypeError):
                    print(f'{ident}: attempt failed', flush=True)
    record()
    print(f'calls={calls} completed={ok}')
    return 0 if ok == len(ITEMS) else 1


if __name__ == '__main__':
    raise SystemExit(main())
