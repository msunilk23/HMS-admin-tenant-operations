"""Tenant logo storage plus automatic brand-color extraction from the image."""
from __future__ import annotations

import colorsys
import uuid
from io import BytesIO

from fastapi import HTTPException, UploadFile
from PIL import Image

from app.core.uploads import get_uploads_dir

_ALLOWED_CONTENT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB
_LOGO_SUBDIR = "tenant-logos"
_FALLBACK_PRIMARY = "#2563eb"
_FALLBACK_SECONDARY = "#eff6ff"


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _lighten_toward_white(rgb: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Blend a colour toward white by `amount` (0..1) for a pale secondary tint."""
    return tuple(round(channel + (255 - channel) * amount) for channel in rgb)


def _hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (channel / 255 for channel in rgb)
    return colorsys.rgb_to_hsv(r, g, b)


def _hue_distance_degrees(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hue_a, _saturation_a, _value_a = _hsv(a)
    hue_b, _saturation_b, _value_b = _hsv(b)
    diff = abs(hue_a - hue_b)
    return min(diff, 1 - diff) * 360


def _bucket(rgb: tuple[int, int, int], step: int = 24) -> tuple[int, int, int]:
    return tuple(min(255, (channel // step) * step) for channel in rgb)


def _dominant_vivid_colors(pixels, saturation_floor: float) -> list[tuple[int, tuple[int, int, int]]]:
    """Group vivid (non-background) pixels into coarse colour buckets, ranked by purity.

    Ranks by saturation (not raw frequency) among commonly-occurring buckets, so the
    purest part of a gradient/logo mark wins over a more frequent but paler blended edge.
    """
    totals: dict[tuple[int, int, int], list[int]] = {}
    for rgb in pixels:
        _hue, saturation, value = _hsv(rgb)
        if saturation < saturation_floor or value < 0.15 or value > 0.95:
            continue
        entry = totals.setdefault(_bucket(rgb), [0, 0, 0, 0])
        entry[0] += 1
        entry[1] += rgb[0]
        entry[2] += rgb[1]
        entry[3] += rgb[2]
    if not totals:
        return []

    total_vivid_pixels = sum(entry[0] for entry in totals.values())
    minimum_population = max(4, round(total_vivid_pixels * 0.01))
    averaged = [
        (count, (round(r_sum / count), round(g_sum / count), round(b_sum / count)))
        for count, r_sum, g_sum, b_sum in totals.values()
        if count >= minimum_population
    ] or [
        (count, (round(r_sum / count), round(g_sum / count), round(b_sum / count)))
        for count, r_sum, g_sum, b_sum in totals.values()
    ]
    # Weight frequency by saturation: a real brand colour occupies a meaningful area
    # (not a stray compression artefact) AND is vivid (not a pale blended edge tone).
    return sorted(averaged, key=lambda entry: entry[0] * _hsv(entry[1])[1], reverse=True)


def extract_brand_colors(image_bytes: bytes) -> tuple[str, str]:
    """Return (primary_hex, secondary_hex) sampled from the image's dominant colours.

    Scans individual pixels for a vivid (non-background) colour rather than relying on
    whole-image colour quantization, so a small logo mark on a large plain white/black
    background still yields its real brand colour instead of the background shade.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        rgb_image = image.convert("RGB")
        rgb_image.thumbnail((300, 300))
        pixels = list(rgb_image.getdata())

    ranked: list[tuple[int, tuple[int, int, int]]] = []
    for saturation_floor in (0.35, 0.20):
        ranked = _dominant_vivid_colors(pixels, saturation_floor)
        if ranked:
            break
    if not ranked:
        return _FALLBACK_PRIMARY, _FALLBACK_SECONDARY

    primary = ranked[0][1]
    secondary = next((rgb for _count, rgb in ranked[1:] if _hue_distance_degrees(rgb, primary) > 30), None)
    if secondary is None:
        secondary = _lighten_toward_white(primary, 0.85)
    return _rgb_to_hex(primary), _rgb_to_hex(secondary)


async def save_tenant_logo(tenant_id: uuid.UUID, upload: UploadFile) -> tuple[str, str, str]:
    """Validate, persist, and colour-sample an uploaded tenant logo.

    Returns (logo_url, primary_color, secondary_color).
    """
    extension = _ALLOWED_CONTENT_TYPES.get(upload.content_type or "")
    if extension is None:
        raise HTTPException(status_code=422, detail="Logo must be a PNG, JPEG, or WEBP image.")

    content = await upload.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded logo file is empty.")
    if len(content) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=422, detail="Logo must be smaller than 2 MB.")

    try:
        primary_hex, secondary_hex = extract_brand_colors(content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Could not read the uploaded image.") from exc

    logos_dir = get_uploads_dir() / _LOGO_SUBDIR
    logos_dir.mkdir(parents=True, exist_ok=True)

    # Remove any previous logo for this tenant regardless of its prior extension.
    for existing in logos_dir.glob(f"{tenant_id}.*"):
        existing.unlink(missing_ok=True)

    destination = logos_dir / f"{tenant_id}.{extension}"
    destination.write_bytes(content)

    return f"/uploads/{_LOGO_SUBDIR}/{destination.name}", primary_hex, secondary_hex
