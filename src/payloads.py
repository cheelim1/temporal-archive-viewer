"""Decoding of Temporal Payload objects embedded in history event attributes.

A Payload looks like: {"metadata": {"encoding": "<base64>", ...}, "data": "<base64>"}.
`metadata.encoding` is itself base64-encoded ASCII, e.g. "json/plain", "binary/null".
"""

import base64
import json


def _b64_text(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return None


def decode_payload(payload: dict):
    """Best-effort decode. Malformed base64/data never raises — a single bad
    payload among hundreds of events must not crash the whole detail view;
    it degrades to a `__decode_error__` marker with the raw value instead."""
    metadata = payload.get("metadata", {}) or {}
    encoding = _b64_text(metadata.get("encoding"))
    data_b64 = payload.get("data")

    try:
        raw = base64.b64decode(data_b64) if data_b64 else b""
    except Exception as e:
        return {"__decode_error__": str(e), "raw": data_b64}

    if encoding == "json/plain":
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return raw.decode("utf-8", errors="replace")
    if encoding == "binary/null":
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex()


def _is_payload_shape(obj) -> bool:
    return bool(obj) and isinstance(obj, dict) and set(obj.keys()) <= {"metadata", "data"}


def decode_payloads_deep(obj):
    """Recursively replace any Payload-shaped dict with its decoded value.

    Safe to call on already-decoded data: once a payload has been replaced,
    it no longer matches the {"metadata", "data"} shape, so recursion is a
    harmless no-op on the second pass.
    """
    if _is_payload_shape(obj):
        return decode_payload(obj)
    if isinstance(obj, dict):
        return {k: decode_payloads_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decode_payloads_deep(v) for v in obj]
    return obj
