"""Helpers for the RFC3339 timestamp strings protobuf's MessageToDict produces
for google.protobuf.Timestamp fields (e.g. "2026-09-28T09:00:24.643489360Z").
"""

from datetime import datetime, timezone


def parse_event_time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    s = ts[:-1] if ts.endswith("Z") else ts
    if "." in s:
        base, frac = s.split(".", 1)
        s = f"{base}.{frac[:6]}"  # datetime.fromisoformat only supports up to microseconds
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def format_event_time(ts: str | None) -> str:
    dt = parse_event_time(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "—"
