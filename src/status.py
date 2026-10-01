"""Rule-based status/diagnostics derivation from a decoded history's events.

Mirrors the heuristics used by the Gemini-based reference tool
(temporal-sa/temporal-workflow-export-analysis), but computed with plain
rules instead of an LLM call:
  - status comes from the last event's eventType
  - failure/cause surfaced from the last event's attributes when terminal
  - retries beyond a threshold and non-determinism errors are flagged as hints
"""

from .decode import event_attrs

TERMINAL_PREFIX = "EVENT_TYPE_WORKFLOW_EXECUTION_"
ATTEMPT_WARN_THRESHOLD = 3


def derive_status(events: list[dict]) -> dict:
    if not events:
        return {"status": "UNKNOWN", "failure": None, "hints": []}

    last = events[-1]
    event_type = last.get("eventType", "")
    if event_type.startswith(TERMINAL_PREFIX):
        status = event_type[len(TERMINAL_PREFIX):]
    else:
        status = "RUNNING"

    # Only FAILED carries a `failure` message. TERMINATED/CANCELED have no
    # Failure proto at all — their explanation lives in different fields
    # (`reason`/`identity` for terminated, `details` for canceled) — so
    # without this, those statuses showed a badge with zero explanation.
    # Each message is a complete, standalone sentence — the status badge
    # above already shows COMPLETED/FAILED/TERMINATED/etc., so these don't
    # need to (and shouldn't) repeat the status word themselves.
    failure = None
    last_attrs = event_attrs(last)
    if status == "FAILED":
        failure = last_attrs.get("failure")
    elif status == "TIMED_OUT":
        failure = {"message": f"Retry state: {last_attrs.get('retryState', 'unknown')}."}
    elif status == "TERMINATED":
        reason = last_attrs.get("reason") or "no reason given"
        identity = last_attrs.get("identity")
        failure = {"message": f"Terminated by {identity}: {reason}." if identity else f"Terminated: {reason}."}
    elif status == "CANCELED":
        failure = {"message": "Canceled by caller." if last_attrs.get("details") else "Canceled."}

    hints: list[str] = []
    for event in events:
        attrs = event_attrs(event)
        attempt = attrs.get("attempt")
        if isinstance(attempt, int) and attempt > ATTEMPT_WARN_THRESHOLD:
            hints.append(
                f"Event #{event.get('eventId')} ({event.get('eventType', '').replace('EVENT_TYPE_', '')}) "
                f"reached attempt {attempt} — check for a recurring failure."
            )
        cause = attrs.get("cause", "")
        if "NON_DETERMINISTIC" in cause:
            hints.append(
                f"Event #{event.get('eventId')}: non-determinism error detected — either revert the "
                "workflow code to the previous version, or terminate and reset this execution."
            )

    return {"status": status, "failure": failure, "hints": hints}
