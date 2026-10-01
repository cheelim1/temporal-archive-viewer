import threading

from src import index_store


def _conn(tmp_path, monkeypatch):
    monkeypatch.setattr(index_store, "DB_PATH", tmp_path / "index.db")
    return index_store.get_connection()


def _row(item_index=0, workflow_id="wf-1", status="COMPLETED") -> dict:
    return {
        "item_index": item_index,
        "workflow_id": workflow_id,
        "run_id": "run-1",
        "workflow_type": "SomeWorkflow",
        "task_queue": "q",
        "start_time": "2026-01-01T00:00:00Z",
        "close_time": "2026-01-01T01:00:00Z",
        "status": status,
        "event_count": 10,
        "payload_text": "{}",
        "history_json": "{}",
    }


def test_upsert_and_search_roundtrip(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    index_store.upsert_file(conn, "bucket", "key.bin", "etag1", 10, "now", [_row()])

    assert index_store.get_cached_etag(conn, "bucket", "key.bin") == "etag1"
    rows = index_store.search(conn, bucket="bucket")
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "wf-1"


def test_underscore_in_search_term_is_matched_literally(tmp_path, monkeypatch):
    # Workflow IDs in this dataset look like "aws_jitaccess_TICKET-001" —
    # `_` is a SQL LIKE wildcard meaning "any one character". Without
    # escaping, searching that exact string would ALSO match
    # "awsXjitaccessXTICKET-001", silently over-matching.
    conn = _conn(tmp_path, monkeypatch)
    index_store.upsert_file(
        conn, "bucket", "key.bin", "etag1", 10, "now",
        [_row(workflow_id="aws_jitaccess_TICKET-001")],
    )
    index_store.upsert_file(
        conn, "bucket", "key2.bin", "etag2", 10, "now",
        [_row(workflow_id="awsXjitaccessXTICKET-001")],
    )

    rows = index_store.search(conn, bucket="bucket", workflow_id="aws_jitaccess_TICKET-001")
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "aws_jitaccess_TICKET-001"


def test_status_filter(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    index_store.upsert_file(conn, "bucket", "a.bin", "e1", 1, "now", [_row(workflow_id="a", status="COMPLETED")])
    index_store.upsert_file(conn, "bucket", "b.bin", "e2", 1, "now", [_row(workflow_id="b", status="FAILED")])

    rows = index_store.search(conn, bucket="bucket", statuses=["FAILED"])
    assert [r["workflow_id"] for r in rows] == ["b"]


def test_upsert_replaces_rows_for_same_key(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    index_store.upsert_file(conn, "bucket", "key.bin", "etag1", 10, "now", [_row(workflow_id="old")])
    index_store.upsert_file(conn, "bucket", "key.bin", "etag2", 10, "now", [_row(workflow_id="new")])

    rows = index_store.search(conn, bucket="bucket")
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "new"
    assert index_store.get_cached_etag(conn, "bucket", "key.bin") == "etag2"


def test_concurrent_reads_and_writes_do_not_error(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    errors = []

    def writer(i):
        try:
            index_store.upsert_file(conn, "bucket", f"k{i}.bin", f"e{i}", 1, "now", [_row(workflow_id=f"wf-{i}")])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def reader():
        try:
            index_store.search(conn, bucket="bucket")
            index_store.get_cached_etag(conn, "bucket", "k0.bin")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    threads += [threading.Thread(target=reader) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
