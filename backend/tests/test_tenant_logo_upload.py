"""Unit tests for tenant logo upload + automatic brand-color extraction."""
import uuid
from io import BytesIO

import pytest
from PIL import Image
from starlette.datastructures import Headers

from app.services import logo_service


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (40, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _two_tone_png_bytes(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (40, 40), top)
    for y in range(20, 40):
        for x in range(40):
            image.putpixel((x, y), bottom)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _black_background_with_accent_and_gray_noise_png_bytes() -> bytes:
    """A black-background logo with a small vivid teal accent plus low-saturation
    gray pixels (mimicking JPEG compression artefacts around the black background)."""
    image = Image.new("RGB", (60, 60), (0, 0, 0))
    for y in range(20, 40):
        for x in range(20, 40):
            image.putpixel((x, y), (10, 170, 150))  # vivid teal brand colour
    for y in range(0, 4):
        for x in range(60):
            image.putpixel((x, y), (226, 229, 231))  # near-white/grey compression noise
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_file(content: bytes, content_type: str, filename: str = "logo.png"):
    from fastapi import UploadFile

    return UploadFile(file=BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def test_extract_brand_colors_prefers_non_white_dominant_color():
    image_bytes = _two_tone_png_bytes(top=(255, 255, 255), bottom=(220, 20, 60))
    primary, secondary = logo_service.extract_brand_colors(image_bytes)
    assert primary.lower() == "#dc143c"
    assert secondary != primary


def test_extract_brand_colors_falls_back_to_defaults_for_a_blank_white_image():
    primary, secondary = logo_service.extract_brand_colors(_png_bytes((255, 255, 255)))
    assert (primary, secondary) == (logo_service._FALLBACK_PRIMARY, logo_service._FALLBACK_SECONDARY)


def test_extract_brand_colors_skips_grey_compression_noise_on_a_black_background():
    image_bytes = _black_background_with_accent_and_gray_noise_png_bytes()
    primary, _secondary = logo_service.extract_brand_colors(image_bytes)
    # Must pick the vivid teal accent, not the near-white/grey noise band or the black background.
    assert primary.lower() not in {"#e2e5e7", "#000000"}
    r, g, b = int(primary[1:3], 16), int(primary[3:5], 16), int(primary[5:7], 16)
    assert g > r and g > b


@pytest.mark.asyncio
async def test_save_tenant_logo_rejects_non_image_content_type():
    upload = _upload_file(b"not an image", "text/plain")
    with pytest.raises(Exception) as error:
        await logo_service.save_tenant_logo(uuid.uuid4(), upload)
    assert getattr(error.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_save_tenant_logo_rejects_oversized_files():
    oversized = b"0" * (logo_service._MAX_LOGO_BYTES + 1)
    upload = _upload_file(oversized, "image/png")
    with pytest.raises(Exception) as error:
        await logo_service.save_tenant_logo(uuid.uuid4(), upload)
    assert getattr(error.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_save_tenant_logo_writes_file_and_returns_extracted_colors(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_service, "get_uploads_dir", lambda: tmp_path)
    tenant_id = uuid.uuid4()
    upload = _upload_file(_two_tone_png_bytes(top=(255, 255, 255), bottom=(220, 20, 60)), "image/png")

    logo_url, primary, secondary = await logo_service.save_tenant_logo(tenant_id, upload)

    assert logo_url == f"/uploads/tenant-logos/{tenant_id}.png"
    assert (tmp_path / "tenant-logos" / f"{tenant_id}.png").exists()
    assert primary.lower() == "#dc143c"
    assert secondary != primary


@pytest.mark.asyncio
async def test_save_tenant_logo_replaces_a_previous_logo_with_a_different_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_service, "get_uploads_dir", lambda: tmp_path)
    tenant_id = uuid.uuid4()
    logos_dir = tmp_path / "tenant-logos"
    logos_dir.mkdir(parents=True)
    stale_file = logos_dir / f"{tenant_id}.jpg"
    stale_file.write_bytes(b"stale")

    upload = _upload_file(_png_bytes((37, 99, 235)), "image/png")
    logo_url, _primary, _secondary = await logo_service.save_tenant_logo(tenant_id, upload)

    assert logo_url == f"/uploads/tenant-logos/{tenant_id}.png"
    assert not stale_file.exists()
    assert (logos_dir / f"{tenant_id}.png").exists()
