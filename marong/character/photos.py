"""Normalize uploads and mask detected human faces before storing a photograph."""

from dataclasses import dataclass
from io import BytesIO
import logging
from math import ceil, floor
from threading import Lock

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)


class PhotoError(ValueError):
    def __init__(self, code, number):
        super().__init__(code)
        self.code = code
        self.number = number


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
    error = PhotoError("photo_invalid", number)
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
        raise PhotoError("check_unavailable", number) from None
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


def crop_pick(raw, box):
    x, y, w, h = box
    with Image.open(BytesIO(raw)) as source:
        width, height = source.size
        left = max(0, floor((x - w * .1) * width))
        top = max(0, floor((y - h * .1) * height))
        right = min(width, ceil((x + w * 1.1) * width))
        bottom = min(height, ceil((y + h * 1.1) * height))
        cropped = source.crop((left, top, right, bottom)).convert("RGB")
    cropped.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    cropped.info.clear()
    output = BytesIO()
    cropped.save(output, format="PNG")
    return output.getvalue()
