from src import decode
from tests.conftest import SAMPLE_TASK_QUEUE, SAMPLE_WORKFLOW_ID, SAMPLE_WORKFLOW_TYPE


def test_decode_sample(sample_export_bytes):
    histories = decode.decode_export_bytes(sample_export_bytes)
    assert len(histories) == 1
    events = histories[0]["events"]
    assert len(events) == 2

    started = decode.event_attrs(events[0])
    assert started["workflowId"] == SAMPLE_WORKFLOW_ID
    assert started["workflowType"]["name"] == SAMPLE_WORKFLOW_TYPE
    assert started["taskQueue"]["name"] == SAMPLE_TASK_QUEUE

    last_type = events[-1]["eventType"]
    assert last_type == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"


def test_decode_empty_bytes_is_zero_items_not_an_error():
    # Zero-byte "folder marker" S3 objects parse as valid-but-empty protobuf
    # rather than raising — callers must handle an empty list, not assume
    # a parse failure is the only non-happy-path.
    assert decode.decode_export_bytes(b"") == []


def test_decode_garbage_bytes_raises():
    from google.protobuf.message import DecodeError

    try:
        decode.decode_export_bytes(b"\xff\xff\xff not a protobuf message")
    except DecodeError:
        pass
    else:
        raise AssertionError("expected a DecodeError for malformed input")


def test_event_attrs_returns_empty_dict_when_no_attributes_key():
    assert decode.event_attrs({"eventId": "1", "eventType": "X"}) == {}
