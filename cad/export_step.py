"""Configured STEP export and local cache helpers (no live calls on import)."""
import hashlib
import os
import tempfile


def step_path(key):
    return os.path.join(".darwin", "geometry", key + ".step")


def cached_step(key):
    path = step_path(key)
    return path if os.path.isfile(path) and os.path.getsize(path) else None


def store_step(key, data):
    """Atomically store export bytes below the gitignored runtime directory."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("empty STEP export")
    path = step_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".step-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def content_key(space_id, model_revision, params, source_microversion=None):
    raw = repr((space_id, model_revision, source_microversion,
                sorted(params.items()))).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
