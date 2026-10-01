"""Decoding of Temporal Cloud export files (temporal.api.export.v1.WorkflowExecutions)."""

from google.protobuf.json_format import MessageToDict
from temporalio.api.export.v1 import WorkflowExecutions


def decode_export_bytes(data: bytes) -> list[dict]:
    """Parse a single S3 export object into decoded workflow histories.

    A single export file can contain more than one workflow execution
    (they are hourly batches), so this returns a list rather than assuming
    exactly one item like the reference temporal-sa script does.

    Raises google.protobuf.message.DecodeError on malformed input — callers
    must catch this (e.g. an S3 object under the export prefix that isn't
    actually an export file, or a zero-byte folder-marker object, which
    parses successfully but yields an empty list rather than erroring).
    """
    workflow_executions = WorkflowExecutions()
    workflow_executions.ParseFromString(data)
    return [MessageToDict(item.history) for item in workflow_executions.items]


def event_attrs(event: dict) -> dict:
    """The one `*EventAttributes` payload a HistoryEvent carries, if any."""
    key = next((k for k in event if k.endswith("EventAttributes")), None)
    return event.get(key, {}) if key else {}
