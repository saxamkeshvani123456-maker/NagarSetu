from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

MAX_IMAGE_BYTES = int(os.getenv("CIVICLENS_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.getenv("CIVICLENS_MAX_IMAGE_PIXELS", "27000000"))
ALLOWED_MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/tiff": ".tiff",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def perceptual_hash_bytes(raw: bytes) -> str:
    """Return a 64-bit difference hash for visual duplicate suggestions.

    Similar hashes identify candidate matches only; they never merge reports.
    """
    with Image.open(__import__("io").BytesIO(raw)) as image:
        pixels = list(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}"


def validate_image_bytes(raw: bytes, content_type: str | None) -> dict[str, Any]:
    if not raw:
        raise ValueError("empty_file")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("file_too_large")
    if content_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError("unsupported_media_type")
    try:
        with Image.open(__import__("io").BytesIO(raw)) as image:
            image.verify()
        with Image.open(__import__("io").BytesIO(raw)) as image:
            width, height = image.size
            detected_format = (image.format or "").lower()
    except Exception as exc:
        raise ValueError("invalid_image") from exc
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError("too_many_pixels")
    return {
        "width": width,
        "height": height,
        "detected_format": detected_format,
        "sha256": sha256_bytes(raw),
    }


def inspect_c2pa(path: Path) -> dict[str, Any]:
    """Read a C2PA manifest without treating absent metadata as proof of fakery."""
    try:
        from c2pa import Context, Reader, Settings
    except ImportError:
        return {"status": "unavailable", "trust_status": "unknown", "error": "c2pa_python_not_installed"}
    try:
        trust_file = os.getenv("CIVICLENS_C2PA_TRUST_ANCHORS_FILE")
        if trust_file and Path(trust_file).exists():
            settings = Settings.from_dict({"verify": {"verify_cert_anchors": True}, "trust": {"trust_anchors": Path(trust_file).read_bytes()}})
            context_manager = Context(settings)
            trust_status = "trusted"
        else:
            context_manager = Context()
            trust_status = "unknown"
        with context_manager as context:
            with Reader(str(path), context=context) as reader:
                manifest_store = json.loads(reader.json())
        active_id = manifest_store.get("active_manifest")
        manifests = manifest_store.get("manifests", {})
        active = manifests.get(active_id) if active_id else None
        return {
            "status": "valid",
            "trust_status": trust_status,
            "active_manifest": active_id,
            "manifest": active,
            "manifest_store": manifest_store,
        }
    except Exception as exc:
        message = str(exc).lower()
        if "manifest" in message or "c2pa" in message or "credential" in message:
            return {"status": "absent", "trust_status": "unknown", "error": str(exc)}
        return {"status": "error", "trust_status": "unknown", "error": str(exc)}


def inspect_local_detector(path: Path) -> dict[str, Any]:
    """Best-effort, dependency-free detector used when Sightengine is unavailable.

    Image-only AI attribution is inherently uncertain, so this fallback deliberately
    does not label an image synthetic from weak signals.  It returns a stable,
    conservative result and never raises; C2PA is evaluated independently by the
    caller and is not overwritten by this heuristic.
    """
    try:
        with Image.open(path) as image:
            width, height = image.size
            bands = len(image.getbands())
            # A tiny amount of metadata is useful operationally, but is not evidence
            # of generation. Keep probability centered and classify as uncertain.
            has_exif = bool(getattr(image, "getexif", lambda: {})())
        return {
            "provider": "local",
            "status": "uncertain",
            "probability": 0.5,
            "confidence": "low",
            "signals": {"width": width, "height": height, "channels": bands, "has_exif": has_exif},
            "reason": "Local fallback cannot reliably distinguish synthetic from camera imagery.",
        }
    except Exception as exc:
        # A detector failure must never block storing a valid upload.
        return {
            "provider": "local",
            "status": "uncertain",
            "probability": 0.5,
            "confidence": "low",
            "error": "local_detector_unavailable",
            "detail": str(exc),
        }


async def inspect_with_sightengine(path: Path, media_type: str) -> dict[str, Any]:
    """Run the optional provider, falling back to the local conservative detector."""
    user = os.getenv("SIGHTENGINE_API_USER")
    secret = os.getenv("SIGHTENGINE_API_SECRET")
    if not user or not secret:
        return inspect_local_detector(path)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            with path.open("rb") as image_file:
                response = await client.post(
                    "https://api.sightengine.com/1.0/check.json",
                    data={"models": "genai", "api_user": user, "api_secret": secret},
                    files={"media": (path.name, image_file, media_type)},
                )
            response.raise_for_status()
            payload = response.json()
        score = payload.get("type", {}).get("ai_generated")
        if score is None:
            return {"status": "uncertain", "probability": None, "raw": payload}
        score = float(score)
        if score >= 0.85:
            status = "high_risk"
        elif score <= 0.15:
            status = "low_risk"
        else:
            status = "uncertain"
        return {
            "status": status,
            "probability": score,
            "request_id": payload.get("request", {}).get("id"),
            "raw": payload,
        }
    except httpx.TimeoutException:
        fallback = inspect_local_detector(path)
        fallback["error"] = "sightengine_timeout"
        return fallback
    except Exception as exc:
        fallback = inspect_local_detector(path)
        fallback["error"] = "sightengine_unavailable"
        fallback["detail"] = str(exc)
        return fallback


def combine_evidence(c2pa: dict[str, Any], detector: dict[str, Any]) -> tuple[str, str]:
    c2pa_status = c2pa.get("status")
    trust_status = c2pa.get("trust_status", "unknown")
    detector_status = detector.get("status")
    probability = detector.get("probability")
    if c2pa_status == "valid" and trust_status == "trusted" and detector_status != "high_risk":
        return "provenance_verified", "not_required"
    if c2pa_status == "invalid" or c2pa_status == "error":
        return "needs_review", "pending"
    if detector_status == "high_risk":
        return "likely_synthetic", "pending"
    if c2pa_status == "valid" and trust_status != "trusted":
        return "needs_review", "pending"
    if detector_status == "uncertain" or probability is None:
        return "insufficient_evidence", "not_required"
    return "insufficient_evidence", "not_required"
