"""Versioned adapter boundary for a future authenticated LAN service. No listener."""

from pathlib import Path

from core import FORMATS

API_VERSION = "v1"


def normalize_request(body, upload_root):
    """Resolve upload IDs inside a private staging area, never arbitrary remote paths.

    Future server owns authentication, upload limits and idempotency persistence.
    Return a draft for local operator confirmation; never print from this method.
    """
    if body.get("version") != API_VERSION:
        raise ValueError("Unsupported API version")
    key = body.get("idempotency_key", "")
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise ValueError("Invalid idempotency key")
    root = Path(upload_root).resolve()
    files = body.get("files", [])
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise ValueError("Invalid file count")
    resolved = []
    for file in files:
        p = (root / file["upload_id"]).resolve()
        if (
            not p.is_relative_to(root)
            or not p.is_file()
            or p.suffix.lower() not in FORMATS
        ):
            raise ValueError("Invalid upload")
        resolved.append(str(p))
    return {
        "version": API_VERSION,
        "idempotency_key": key,
        "community": str(body["community"]),
        "building": str(body["building"]),
        "files": resolved,
        "options": dict(body.get("options", {})),
        "requires_local_confirmation": True,
    }
