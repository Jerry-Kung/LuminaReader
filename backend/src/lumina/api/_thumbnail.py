from __future__ import annotations

import base64
import io
import logging

from PIL import Image

from lumina.logging import get_logger, log_with_fields

logger = get_logger("lumina.thumbnail")

MAX_LONG_EDGE = 480
FALLBACK_LONG_EDGE = 360
MAX_BYTES = 200 * 1024


def _resize_to_png(image: Image.Image, long_edge: int) -> bytes:
    img = image.copy()
    img.thumbnail((long_edge, long_edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_thumbnail(image_data_b64: str) -> bytes | None:
    try:
        raw = base64.b64decode(image_data_b64, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            png_bytes = _resize_to_png(image, MAX_LONG_EDGE)
            if len(png_bytes) <= MAX_BYTES:
                return png_bytes
            png_bytes = _resize_to_png(image, FALLBACK_LONG_EDGE)
            if len(png_bytes) <= MAX_BYTES:
                return png_bytes
            size_kb = len(png_bytes) // 1024
            log_with_fields(
                logger,
                logging.WARNING,
                "thumbnail exceeds size budget",
                size_kb=size_kb,
            )
            return None
    except Exception as exc:
        log_with_fields(
            logger,
            logging.WARNING,
            "thumbnail generation failed",
            event="thumbnail_failed",
            exception_type=type(exc).__name__,
        )
        return None
