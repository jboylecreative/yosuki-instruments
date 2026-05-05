"""
Adobe Firefly API client.

Handles OAuth 2.0 token acquisition (client credentials flow) with caching,
image generation via generateImagesV3Async, and async job polling.

Auth: Client ID + Client Secret → Bearer token (valid 24h, cached for 23h)
Endpoint: POST https://firefly-api.adobe.io/v3/images/generate-async

Stage 1 image generation only — Firefly has no text/image-to-video API.
"""
import base64
import json
import os
import time
from pathlib import Path

import httpx

FIREFLY_BASE = "https://firefly-api.adobe.io"
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,firefly_api,ff_apis"

# Token cache — persisted to disk so re-runs within 23h reuse the token
_TOKEN_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / ".firefly_token_cache.json"


def _load_cached_token() -> dict | None:
    if not _TOKEN_CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(_TOKEN_CACHE_PATH.read_text())
        if cache.get("expires_at", 0) > time.time() + 60:
            return cache
    except Exception:
        pass
    return None


def _save_token_cache(token: str, expires_in: int):
    cache = {
        "access_token": token,
        "expires_at": time.time() + expires_in - 3600,  # 1h safety margin
    }
    _TOKEN_CACHE_PATH.parent.mkdir(exist_ok=True)
    _TOKEN_CACHE_PATH.write_text(json.dumps(cache))


def get_access_token(client_id: str, client_secret: str) -> str:
    cached = _load_cached_token()
    if cached:
        return cached["access_token"]

    resp = httpx.post(
        IMS_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": IMS_SCOPES,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _save_token_cache(token, data.get("expires_in", 86400))
    return token


def _auth_headers(client_id: str, token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "x-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _upload_reference_image(client_id: str, token: str, image_path: Path) -> str | None:
    """Upload a product image as a structure reference. Returns uploadId or None."""
    try:
        upload_url = f"{FIREFLY_BASE}/v2/storage/image"
        img_bytes = image_path.read_bytes()
        resp = httpx.post(
            upload_url,
            content=img_bytes,
            headers={
                "Authorization": f"Bearer {token}",
                "x-api-key": client_id,
                "Content-Type": "image/png",
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("images", [{}])[0].get("id")
    except Exception as e:
        print(f"    [Firefly] Could not upload reference image: {e}")
        return None


async def generate_image(
    client_id: str,
    client_secret: str,
    prompt: str,
    width: int,
    height: int,
    reference_image_path: Path | None = None,
    poll_interval: float = 2.0,
    timeout: float = 300.0,
) -> bytes | None:
    """
    Generate an image via Firefly generateImagesV3Async.

    Returns raw PNG bytes on success, or None on failure.
    """
    import asyncio

    token = await asyncio.to_thread(get_access_token, client_id, client_secret)
    headers = _auth_headers(client_id, token)

    # Build request payload
    payload: dict = {
        "prompt": prompt,
        "size": {"width": width, "height": height},
        "contentClass": "photo",
        "numVariations": 1,
    }

    # Optional: structure reference from product image
    if reference_image_path and reference_image_path.exists():
        upload_id = await asyncio.to_thread(
            _upload_reference_image, client_id, token, reference_image_path
        )
        if upload_id:
            payload["structure"] = {
                "strength": 35,
                "imageReference": {"source": {"uploadId": upload_id}},
            }

    # Submit async job
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{FIREFLY_BASE}/v3/images/generate-async",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        job = resp.json()

    job_id = job.get("jobId")
    status_url = job.get("statusUrl")
    if not status_url:
        raise ValueError(f"No statusUrl in Firefly response: {job}")

    print(f"    [Firefly] Job {job_id} submitted — polling...")

    # Poll for completion
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=30) as client:
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            status_resp = await client.get(status_url, headers=headers)
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status")

            if status == "succeeded":
                # Download the result image
                outputs = status_data.get("result", {}).get("outputs", [])
                if not outputs:
                    raise ValueError("Firefly succeeded but no outputs in response")
                image_url = outputs[0].get("image", {}).get("presignedUrl")
                if not image_url:
                    raise ValueError(f"No presignedUrl in output: {outputs[0]}")
                img_resp = await client.get(image_url, timeout=60)
                img_resp.raise_for_status()
                print(f"    [Firefly] Job {job_id} complete")
                return img_resp.content

            elif status == "failed":
                err = status_data.get("error", {})
                raise RuntimeError(f"Firefly job failed: {err}")

            elif status in ("running", "queued", "pending"):
                continue
            else:
                print(f"    [Firefly] Unknown status: {status}")

    raise TimeoutError(f"Firefly job {job_id} timed out after {timeout}s")
