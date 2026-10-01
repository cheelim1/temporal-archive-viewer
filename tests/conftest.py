"""Builds a synthetic export fixture in-memory rather than committing a real
one — a real exported file contains actual production data (user emails,
AWS account numbers, resource ARNs, ticket IDs), which has no business in
version control. This constructs the same shape of message by hand, with
entirely fake values, using the same proto classes decode.py decodes with.
"""

import json

import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from temporalio.api.common.v1 import Payload, Payloads, WorkflowType
from temporalio.api.enums.v1 import EventType
from temporalio.api.export.v1 import WorkflowExecution, WorkflowExecutions
from temporalio.api.history.v1 import (
    History,
    HistoryEvent,
    WorkflowExecutionCompletedEventAttributes,
    WorkflowExecutionStartedEventAttributes,
)
from temporalio.api.taskqueue.v1 import TaskQueue

SAMPLE_WORKFLOW_ID = "test-workflow-1"
SAMPLE_WORKFLOW_TYPE = "TestWorkflow"
SAMPLE_TASK_QUEUE = "test-task-queue"
SAMPLE_TICKET_ID = "TEST-001"


@pytest.fixture
def sample_export_bytes() -> bytes:
    payload = Payload(
        metadata={"encoding": b"json/plain"},
        data=json.dumps({"ticket_id": SAMPLE_TICKET_ID, "requester": "test-user"}).encode(),
    )
    started = WorkflowExecutionStartedEventAttributes(
        workflow_type=WorkflowType(name=SAMPLE_WORKFLOW_TYPE),
        task_queue=TaskQueue(name=SAMPLE_TASK_QUEUE),
        input=Payloads(payloads=[payload]),
        workflow_id=SAMPLE_WORKFLOW_ID,
        original_execution_run_id="00000000-0000-0000-0000-000000000001",
    )
    ts_start, ts_end = Timestamp(), Timestamp()
    ts_start.FromSeconds(1700000000)
    ts_end.FromSeconds(1700000010)

    events = [
        HistoryEvent(
            event_id=1,
            event_time=ts_start,
            event_type=EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED,
            workflow_execution_started_event_attributes=started,
        ),
        HistoryEvent(
            event_id=2,
            event_time=ts_end,
            event_type=EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
            workflow_execution_completed_event_attributes=WorkflowExecutionCompletedEventAttributes(),
        ),
    ]
    workflow_executions = WorkflowExecutions(items=[WorkflowExecution(history=History(events=events))])
    return workflow_executions.SerializeToString()
