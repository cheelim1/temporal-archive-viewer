"""Shared Streamlit widgets used by both the Browse and Search pages."""

import json
import os

import streamlit as st

from . import payloads, s3_client, status, timeutil
from .decode import event_attrs

DEFAULT_ROOT_PREFIX = "temporal-workflow-history/export/"

_STATUS_COLOR = {
    "COMPLETED": "green",
    "FAILED": "red",
    "TERMINATED": "red",
    "TIMED_OUT": "orange",
    "CANCELED": "orange",
    "RUNNING": "blue",
}

_NOTABLE_EVENT_MARKERS = ("FAILED", "TIMED_OUT", "TERMINATED", "CANCELED")


@st.cache_data(ttl=60, show_spinner=False)
def cached_list_prefix(_client, bucket: str, prefix: str):
    """Cached wrapper around s3_client.list_prefix (1 min TTL) so repeat
    clicks while browsing the same folder don't re-hit S3 every rerun."""
    return s3_client.list_prefix(_client, bucket, prefix)


@st.cache_data(ttl=300, show_spinner=False)
def cached_get_object_bytes(_client, bucket: str, key: str):
    """Cached wrapper around s3_client.get_object_bytes (5 min TTL). Archived
    export files are immutable once written, so caching their bytes is safe."""
    return s3_client.get_object_bytes(_client, bucket, key)


@st.cache_resource(show_spinner=False)
def _cached_client(profile: str | None, region: str | None):
    """boto3 client, cached per (profile, region) for the process lifetime.

    Without this, every single widget interaction reruns the whole script,
    which was constructing a brand new boto3.Session + client (re-resolving
    credentials from disk/SSO cache every time) on every rerun — wasted work
    on every keystroke/click, not just when the connection settings change.
    """
    return s3_client.get_client(profile, region)


def render_connection_sidebar():
    st.sidebar.header("Connection")
    bucket = st.sidebar.text_input(
        "S3 bucket", value=os.environ.get("TEMPORAL_ARCHIVE_BUCKET", ""), key="cfg_bucket"
    )
    profile = st.sidebar.text_input(
        "AWS profile (optional)", value=os.environ.get("AWS_PROFILE", ""), key="cfg_profile"
    )
    root_prefix = st.sidebar.text_input(
        "Root prefix",
        value=os.environ.get("TEMPORAL_ARCHIVE_PREFIX", DEFAULT_ROOT_PREFIX),
        key="cfg_root_prefix",
    )
    region = st.sidebar.text_input(
        "AWS region (optional)",
        value=os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "")),
        key="cfg_region",
        help="Only needed if the bucket's region differs from your profile's default "
        "region — a common cause of connection errors.",
    )
    if not bucket:
        st.sidebar.info("Enter an S3 bucket to begin.")
        st.stop()

    client = _cached_client(profile or None, region or None)

    if st.sidebar.button("Test connection"):
        try:
            with st.sidebar:
                with st.spinner("Checking..."):
                    client.list_objects_v2(Bucket=bucket, Prefix=root_prefix, MaxKeys=1)
            st.sidebar.success("Connected — bucket is reachable.")
        except Exception as e:
            st.sidebar.error(s3_client.friendly_error(e))

    return bucket, (profile or None), root_prefix, client


def render_workflow_detail(history: dict, source_label: str | None = None, widget_key: str | None = None):
    events = history.get("events", [])
    info = status.derive_status(events)
    started_attrs = event_attrs(events[0]) if events else {}

    workflow_id = started_attrs.get("workflowId", "?")
    run_id = started_attrs.get("originalExecutionRunId", "?")
    workflow_type = (started_attrs.get("workflowType") or {}).get("name", "?")
    task_queue = (started_attrs.get("taskQueue") or {}).get("name", "?")
    # Caller-supplied widget_key disambiguates cases where workflow_id+run_id
    # alone wouldn't be unique (e.g. "?"/"?" when events is empty).
    key_base = widget_key or f"{workflow_id}-{run_id}"

    st.subheader(f"{workflow_type} — {workflow_id}")
    color = _STATUS_COLOR.get(info["status"], "gray")
    st.markdown(f":{color}[**{info['status']}**]")

    cols = st.columns(4)
    cols[0].metric("Events", len(events))
    cols[1].metric("Task queue", task_queue)
    cols[2].metric("Start", timeutil.format_event_time(events[0].get("eventTime")) if events else "—")
    cols[3].metric("Close", timeutil.format_event_time(events[-1].get("eventTime")) if events else "—")
    caption = f"Run ID: {run_id}"
    if source_label:
        caption += f"  ·  Source: `{source_label}`"
    st.caption(caption)

    if info.get("failure"):
        message = info["failure"].get("message", "(no message)")
        st.error(f"Failure: {message}" if info["status"] == "FAILED" else message)
        cause = info["failure"].get("cause")
        if cause:
            st.caption(f"Cause: {cause.get('message', '(no message)')}")

    for hint in info.get("hints", []):
        st.warning(hint)

    st.download_button(
        "Download decoded JSON",
        data=json.dumps(payloads.decode_payloads_deep(history), indent=2),
        file_name=f"{workflow_id}.json",
        mime="application/json",
        key=f"download-{key_base}",
    )

    st.markdown("### Event timeline")
    expand_all = st.checkbox("Expand all events", key=f"expand-all-{key_base}")

    for event in events:
        attrs = payloads.decode_payloads_deep(event_attrs(event))
        event_type = event.get("eventType", "").replace("EVENT_TYPE_", "")
        is_notable = any(marker in event_type for marker in _NOTABLE_EVENT_MARKERS)
        icon = "❌" if is_notable else "▫️"
        label = f"{icon} #{event.get('eventId')} · {event_type}"
        with st.expander(label, expanded=expand_all or is_notable or event is events[-1]):
            st.caption(timeutil.format_event_time(event.get("eventTime")))
            st.json(attrs)
