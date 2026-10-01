import base64

from src import payloads


def _payload(encoding: str, data: bytes) -> dict:
    return {
        "metadata": {"encoding": base64.b64encode(encoding.encode()).decode()},
        "data": base64.b64encode(data).decode(),
    }


def test_json_plain_decodes_to_native_json():
    p = _payload("json/plain", b'{"ticket_id": "TICKET-001"}')
    assert payloads.decode_payload(p) == {"ticket_id": "TICKET-001"}


def test_binary_null_decodes_to_none():
    p = _payload("binary/null", b"")
    assert payloads.decode_payload(p) is None


def test_unknown_encoding_falls_back_to_text():
    p = _payload("binary/plain", b"hello world")
    assert payloads.decode_payload(p) == "hello world"


def test_malformed_base64_data_does_not_raise():
    # A single corrupted payload among hundreds of events must degrade
    # gracefully, not crash the entire detail view render.
    p = {"metadata": {"encoding": base64.b64encode(b"json/plain").decode()}, "data": "not-valid-base64!!!"}
    result = payloads.decode_payload(p)
    assert isinstance(result, dict)
    assert "__decode_error__" in result


def test_decode_payloads_deep_replaces_nested_payload():
    tree = {"input": {"payloads": [_payload("json/plain", b'{"a": 1}')]}}
    decoded = payloads.decode_payloads_deep(tree)
    assert decoded == {"input": {"payloads": [{"a": 1}]}}


def test_decode_payloads_deep_is_idempotent():
    tree = {"input": {"payloads": [_payload("json/plain", b'{"a": 1}')]}}
    once = payloads.decode_payloads_deep(tree)
    twice = payloads.decode_payloads_deep(once)
    assert once == twice
