import threading
from datetime import date

import pytest

from src import scan


class TestParseHours:
    def test_empty_means_all_hours(self):
        assert scan.parse_hours("") is None

    def test_range(self):
        assert scan.parse_hours("13-17") == [13, 14, 15, 16, 17]

    def test_csv(self):
        assert scan.parse_hours("0,6,12") == [0, 6, 12]

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError):
            scan.parse_hours("20-5")

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            scan.parse_hours("25-30")

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            scan.parse_hours("-5-10")


class _FakePaginator:
    def __init__(self, pages_by_prefix, call_log, call_lock, fail_prefixes):
        self.pages_by_prefix = pages_by_prefix
        self.call_log = call_log
        self.call_lock = call_lock
        self.fail_prefixes = fail_prefixes

    def paginate(self, **kwargs):
        prefix = kwargs["Prefix"]
        with self.call_lock:
            self.call_log.append(prefix)
        if prefix in self.fail_prefixes:
            raise RuntimeError("simulated transient S3 failure")
        return self.pages_by_prefix.get(prefix, [{"Contents": []}])


class _FakeClient:
    def __init__(self, pages_by_prefix, fail_prefixes=()):
        self.pages_by_prefix = pages_by_prefix
        self.call_log: list[str] = []
        self.call_lock = threading.Lock()
        self.fail_prefixes = set(fail_prefixes)

    def get_paginator(self, _name):
        return _FakePaginator(self.pages_by_prefix, self.call_log, self.call_lock, self.fail_prefixes)


def _two_hour_page(prefix: str) -> list[dict]:
    return [
        {
            "Contents": [
                {"Key": prefix + "05/shard0/file-a.bin", "ETag": '"a"', "Size": 1, "LastModified": "x"},
                {"Key": prefix + "17/shard0/file-b.bin", "ETag": '"b"', "Size": 2, "LastModified": "y"},
            ]
        }
    ]


class TestListObjectSummaries:
    ROOT = "temporal-workflow-history/export/"
    NS = "example-namespace"

    def _day_prefix(self, d: date) -> str:
        return f"{self.ROOT}{self.NS}/{d:%Y}/{d:%m}/{d:%d}/"

    def test_one_s3_call_per_day_not_per_hour(self):
        days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
        pages = {self._day_prefix(d): _two_hour_page(self._day_prefix(d)) for d in days}
        client = _FakeClient(pages)

        summaries, errors = scan.list_object_summaries(
            client, "bucket", self.ROOT, self.NS, days[0], days[-1], hours=None
        )
        assert len(client.call_log) == 3  # not 3 * 24
        assert len(summaries) == 6
        assert errors == []

    def test_hour_filter_applied_client_side_without_extra_calls(self):
        days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
        pages = {self._day_prefix(d): _two_hour_page(self._day_prefix(d)) for d in days}
        client = _FakeClient(pages)

        summaries, errors = scan.list_object_summaries(
            client, "bucket", self.ROOT, self.NS, days[0], days[-1], hours=[17]
        )
        assert len(client.call_log) == 3
        assert len(summaries) == 3
        assert all("/17/" in s["Key"] for s in summaries)

    def test_progress_callback_reaches_total(self):
        days = [date(2026, 9, 1), date(2026, 9, 2)]
        pages = {self._day_prefix(d): _two_hour_page(self._day_prefix(d)) for d in days}
        client = _FakeClient(pages)
        seen = []

        _summaries, _errors = scan.list_object_summaries(
            client, "bucket", self.ROOT, self.NS, days[0], days[-1],
            progress_cb=lambda done, total: seen.append((done, total)),
        )
        assert seen[-1] == (2, 2)

    def test_one_failing_day_does_not_abort_the_whole_range(self):
        days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
        pages = {self._day_prefix(d): _two_hour_page(self._day_prefix(d)) for d in days}
        failing_day_prefix = self._day_prefix(days[1])
        client = _FakeClient(pages, fail_prefixes={failing_day_prefix})

        summaries, errors = scan.list_object_summaries(
            client, "bucket", self.ROOT, self.NS, days[0], days[-1]
        )
        # the other two days still succeeded
        assert len(summaries) == 4
        assert len(errors) == 1
        assert errors[0][0] == days[1].isoformat()
