"""Generate the four approved default-character body layers, with no secret output.

Requires an explicitly configured OPENAI_API_KEY and MARONG_WEAR_IMAGE_MODEL.
Outputs only PNGs and an aggregate usage record in the requested directory.
"""
import argparse
import base64
from io import BytesIO
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
    args.out.mkdir(parents=True, exist_ok=True)
    if any((args.out / f'{ident}.png').exists() for ident in ITEMS) or (args.out / 'usage.json').exists():
        raise SystemExit('output already exists; use an empty output directory')
    face = (ROOT / 'marong/call/static/face/v1/01-neutral.webp').read_bytes()
    catalog = ROOT / 'marong/decor/v1'
    calls, ok, usages = 0, 0, []
    log = args.out / 'usage.json'
    def record():
        log.write_text(json.dumps({'calls':calls,'completed':ok,'usage':usages}), encoding='utf-8')
    record()
    with httpx.Client(timeout=120) as client:
        for ident in ITEMS:
            target = args.out / f'{ident}.png'
            thumb = (catalog / ident / 'thumb.webp').read_bytes()
            for _ in range(2):
                calls += 1
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
                    usages.append(body.get('usage') or {})
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
