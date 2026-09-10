import sys
import os
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from retry_queue import RetryQueue


def test_enqueue_dequeue():
    q = RetryQueue(max_size=10)
    q.enqueue({"a": 1})
    q.enqueue({"a": 2})
    assert q.size() == 2

    batch = q.dequeue(batch_size=1)
    assert len(batch) == 1
    assert batch[0]["payload"] == {"a": 1}
    assert q.size() == 1


def test_max_size_evicts_oldest():
    q = RetryQueue(max_size=3)
    for i in range(5):
        q.enqueue({"i": i})
    assert q.size() == 3
    batch = q.dequeue(batch_size=3)
    # oldest two (0, 1) should have been evicted; 2,3,4 remain
    assert [b["payload"]["i"] for b in batch] == [2, 3, 4]


def test_requeue_increments_retries_and_keeps_below_limit():
    q = RetryQueue(max_size=10)
    q.enqueue({"a": 1})
    batch = q.dequeue(batch_size=1)
    assert q.size() == 0

    entry = batch[0]
    entry["retries"] = 3  # incrementing to 4 is still under the limit (< 5)
    q.requeue([entry])
    assert q.size() == 1

    batch2 = q.dequeue(batch_size=1)
    assert batch2[0]["retries"] == 4


def test_requeue_drops_at_retry_limit():
    q = RetryQueue(max_size=10)
    entry = {"payload": {"a": 1}, "timestamp": 0, "retries": 4}
    q.requeue([entry])  # increments to 5, which is not < 5 -> dropped
    assert q.size() == 0


def test_requeue_drops_when_retries_exceeded():
    q = RetryQueue(max_size=10)
    entry = {"payload": {"a": 1}, "timestamp": 0, "retries": 10}
    q.requeue([entry])
    assert q.size() == 0  # dropped: retries (11) >= 5


def test_persistence_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "queue.json")
        q1 = RetryQueue(max_size=10, persist_path=path)
        q1.enqueue({"a": 1})
        q1.enqueue({"a": 2})

        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2

        q2 = RetryQueue(max_size=10, persist_path=path)
        assert q2.size() == 2


def test_stats_reports_oldest_entry_age():
    q = RetryQueue(max_size=10)
    stats_empty = q.get_stats()
    assert stats_empty["queue_size"] == 0
    assert stats_empty["oldest_entry_age"] == 0

    q.enqueue({"a": 1})
    stats = q.get_stats()
    assert stats["queue_size"] == 1
    assert stats["oldest_entry_age"] >= 0
