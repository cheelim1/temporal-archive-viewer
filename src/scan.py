"""Scope a date/hour range into S3 object summaries, then fetch+decode+index
new or changed ones concurrently, populating the sqlite cache in index_store.
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Callable

from . import decode, index_store, s3_client, status
from .decode import event_attrs


def parse_hours(text: str) -> list[int] | None:
    """Parse '13-17' or '0,6,12' into a list of hours; '' means all hours.

    Raises ValueError (with a message fit to show the user directly) on an
    out-of-range hour or a reversed range — both previously fell through
    silently to "0 results found" with no indication why.
    """
    text = text.strip()
    if not text:
        return None
    if "-" in text:
        start_s, end_s = text.split("-", 1)
        start, end = int(start_s), int(end_s)
        if start > end:
            raise ValueError(f"Range start ({start}) must not be after end ({end}).")
        hours = list(range(start, end + 1))
    else:
        hours = [int(h) for h in text.split(",") if h.strip()]
    if not all(0 <= h <= 23 for h in hours):
        raise ValueError("Hours must be between 0 and 23.")
    return hours


def _daterange(start_date: date, end_date: date) -> list[date]:
    days = []
    day = start_date
    while day <= end_date:
        days.append(day)
        day += timedelta(days=1)
    return days


def list_object_summaries(
    client,
    bucket: str,
    root_prefix: str,
    namespace: str,
    start_date: date,
    end_date: date,
    hours: list[int] | None = None,
    max_workers: int = 8,
    progress_cb: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """List every object across the date range in one S3 call per *day*
    (not per hour) across all shards, run concurrently across days, then
    filter by hour client-side if requested.

    Listing per hour (24 calls/day) instead of per day was the original
    approach and made a 1-month scan with no hour filter issue ~700+
    sequential S3 calls before a single file was even fetched. Listing per
    day cuts that by up to 24x, and running the day-level listings
    concurrently cuts wall-clock time further on top of that.

    Returns (summaries, errors) — a day that fails to list (e.g. a
    transient throttle) is skipped rather than aborting the whole range;
    errors is a list of (day_str, message) for any that failed.
    """
    days = _daterange(start_date, end_date)
    hour_set = set(hours) if hours is not None else None
    done = 0
    done_lock = threading.Lock()
    errors: list[tuple[str, str]] = []

    def list_day(day: date) -> list[dict]:
        nonlocal done
        prefix = f"{root_prefix}{namespace}/{day:%Y}/{day:%m}/{day:%d}/"
        try:
            objects = list(s3_client.iter_objects_recursive(client, bucket, prefix))
            if hour_set is not None:
                objects = [o for o in objects if _hour_of(o["Key"], prefix) in hour_set]
        except Exception as e:
            with done_lock:
                errors.append((day.isoformat(), s3_client.friendly_error(e)))
            objects = []
        with done_lock:
            done += 1
            current = done
        if progress_cb:
            progress_cb(current, len(days))
        return objects

    if not days:
        return [], []
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for objects in executor.map(list_day, days):
            results.extend(objects)
    return results, errors


def _hour_of(key: str, day_prefix: str) -> int | None:
    """Extract the hour folder (e.g. '17') from a key under a day prefix."""
    rest = key[len(day_prefix):]
    segment = rest.split("/", 1)[0]
    try:
        return int(segment)
    except ValueError:
        return None


def _build_rows(histories: list[dict]) -> list[dict]:
    rows = []
    for item_index, history in enumerate(histories):
        events = history.get("events", [])
        info = status.derive_status(events)
        started_attrs = event_attrs(events[0]) if events else {}

        rows.append(
            {
                "item_index": item_index,
                "workflow_id": started_attrs.get("workflowId"),
                "run_id": started_attrs.get("originalExecutionRunId"),
                "workflow_type": (started_attrs.get("workflowType") or {}).get("name"),
                "task_queue": (started_attrs.get("taskQueue") or {}).get("name"),
                "start_time": events[0].get("eventTime") if events else None,
                "close_time": events[-1].get("eventTime") if events else None,
                "status": info["status"],
                "event_count": len(events),
                "payload_text": json.dumps(history),
                "history_json": json.dumps(history),
            }
        )
    return rows


def scan_and_index(
    client,
    bucket: str,
    summaries: list[dict],
    conn,
    max_workers: int = 8,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str]]:
    """Fetch+decode+index each summary not already cached by ETag.

    Returns a list of (key, error_message) for any file that failed to
    fetch/decode — one corrupt or unexpected object (e.g. a non-export file
    dropped under the same prefix) no longer aborts the entire scan; it's
    skipped and reported so the rest of the batch still completes.
    """
    total = len(summaries)
    done = 0
    done_lock = threading.Lock()
    failures: list[tuple[str, str]] = []

    def process(summary: dict) -> None:
        nonlocal done
        key = summary["Key"]
        try:
            etag = summary.get("ETag", "").strip('"')
            if index_store.get_cached_etag(conn, bucket, key) != etag:
                data, fetched_etag = s3_client.get_object_bytes(client, bucket, key)
                histories = decode.decode_export_bytes(data)
                rows = _build_rows(histories)
                index_store.upsert_file(
                    conn,
                    bucket,
                    key,
                    fetched_etag or etag,
                    summary.get("Size"),
                    str(summary.get("LastModified")),
                    rows,
                )
        except Exception as e:
            with done_lock:
                failures.append((key, s3_client.friendly_error(e)))
        with done_lock:
            done += 1
            current = done
        if progress_cb:
            progress_cb(current, total)

    if not summaries:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(process, summaries))
    return failures
