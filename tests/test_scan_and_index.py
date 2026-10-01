from src import index_store, scan
from tests.conftest import SAMPLE_WORKFLOW_ID


class _FakeClient:
    def __init__(self, bodies_by_key: dict[str, bytes], fail_keys=()):
        self.bodies_by_key = bodies_by_key
        self.fail_keys = set(fail_keys)

    def get_object(self, Bucket, Key):
        if Key in self.fail_keys:
            raise RuntimeError("simulated fetch failure")
        return {"Body": _Body(self.bodies_by_key[Key]), "ETag": '"etag-for-' + Key + '"'}


class _Body:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


def test_one_bad_file_does_not_abort_the_rest(tmp_path, sample_export_bytes, monkeypatch):
    monkeypatch.setattr(index_store, "DB_PATH", tmp_path / "index.db")
    conn = index_store.get_connection()

    good_key = "good.bin"
    bad_key = "bad.bin"
    client = _FakeClient({good_key: sample_export_bytes, bad_key: b"not a protobuf"}, fail_keys=())

    summaries = [
        {"Key": good_key, "ETag": '"g"', "Size": 1, "LastModified": "x"},
        {"Key": bad_key, "ETag": '"b"', "Size": 1, "LastModified": "y"},
    ]
    failures = scan.scan_and_index(client, "bucket", summaries, conn)

    assert len(failures) == 1
    assert failures[0][0] == bad_key

    # the good file was still indexed despite the bad one failing
    rows = index_store.search(conn, bucket="bucket")
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == SAMPLE_WORKFLOW_ID


def test_unreachable_file_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(index_store, "DB_PATH", tmp_path / "index.db")
    conn = index_store.get_connection()

    client = _FakeClient({}, fail_keys={"missing.bin"})
    summaries = [{"Key": "missing.bin", "ETag": '"x"', "Size": 1, "LastModified": "z"}]

    failures = scan.scan_and_index(client, "bucket", summaries, conn)
    assert len(failures) == 1
    assert "missing.bin" == failures[0][0]
