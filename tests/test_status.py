from src import decode, status


def test_completed_from_sample_fixture(sample_export_bytes):
    history = decode.decode_export_bytes(sample_export_bytes)[0]
    info = status.derive_status(history["events"])
    assert info["status"] == "COMPLETED"
    assert info["failure"] is None


def _event(event_type: str, attrs_key: str | None = None, attrs: dict | None = None) -> dict:
    e: dict = {"eventId": "1", "eventType": event_type}
    if attrs_key:
        e[attrs_key] = attrs or {}
    return e


def test_failed_surfaces_failure_message():
    events = [
        _event("EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "workflowExecutionStartedEventAttributes"),
        _event(
            "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
            "workflowExecutionFailedEventAttributes",
            {"failure": {"message": "boom"}},
        ),
    ]
    info = status.derive_status(events)
    assert info["status"] == "FAILED"
    assert info["failure"]["message"] == "boom"


def test_terminated_surfaces_reason_even_though_no_failure_field():
    # WorkflowExecutionTerminatedEventAttributes has no `failure` field at
    # all (only FAILED does) — before the fix, TERMINATED showed a status
    # badge with zero explanation despite reason/identity being available.
    events = [
        _event(
            "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED",
            "workflowExecutionTerminatedEventAttributes",
            {"reason": "operator action", "identity": "someone@example.com"},
        ),
    ]
    info = status.derive_status(events)
    assert info["status"] == "TERMINATED"
    assert info["failure"] is not None
    assert "operator action" in info["failure"]["message"]


def test_canceled_surfaces_something():
    events = [_event("EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED", "workflowExecutionCanceledEventAttributes", {})]
    info = status.derive_status(events)
    assert info["status"] == "CANCELED"
    assert info["failure"] is not None


def test_non_terminal_last_event_means_running():
    events = [_event("EVENT_TYPE_WORKFLOW_TASK_SCHEDULED", "workflowTaskScheduledEventAttributes")]
    info = status.derive_status(events)
    assert info["status"] == "RUNNING"


def test_attempt_over_threshold_produces_hint():
    events = [
        _event("EVENT_TYPE_ACTIVITY_TASK_STARTED", "activityTaskStartedEventAttributes", {"attempt": 5}),
    ]
    info = status.derive_status(events)
    assert any("attempt 5" in h for h in info["hints"])


def test_non_determinism_cause_produces_hint():
    events = [
        _event(
            "EVENT_TYPE_WORKFLOW_TASK_FAILED",
            "workflowTaskFailedEventAttributes",
            {"cause": "WORKFLOW_TASK_FAILED_CAUSE_NON_DETERMINISTIC_ERROR"},
        ),
    ]
    info = status.derive_status(events)
    assert any("non-determinism" in h.lower() for h in info["hints"])


def test_empty_events_is_unknown_not_a_crash():
    info = status.derive_status([])
    assert info["status"] == "UNKNOWN"
