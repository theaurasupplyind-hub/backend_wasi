"""Supabase Storage — REST + service_role (patrón storage.py de backend_gal)."""
import uuid

import requests

from database import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL

BUCKET_PRODUCTOS = "wasi-productos"
BUCKET_REMITOS = "wasi-remitos"


def storage_available() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _headers() -> dict:
    return {"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}


def build_path(prefix: str, ext: str) -> str:
    return f"{prefix}/{uuid.uuid4().hex}.{ext.lstrip('.')}"


def upload_bytes(bucket: str, path: str, data: bytes, mime_type: str) -> str:
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    resp = requests.post(url, headers={**_headers(), "Content-Type": mime_type}, data=data, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase upload falló ({resp.status_code}): {resp.text[:200]}")
    return path


def public_url(bucket: str, path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{path}"


def delete_object(bucket: str, path: str) -> None:
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    resp = requests.delete(url, headers=_headers(), timeout=60)
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Supabase delete falló ({resp.status_code}): {resp.text[:200]}")