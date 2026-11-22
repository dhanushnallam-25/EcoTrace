"""Custom MaxHeap: invariant, ordering, update/remove (SYNTHETIC incidents)."""
import random

import pytest

from backend.max_heap import MaxHeap


def make(n, seed=1):
    rng = random.Random(seed)
    return [{"incident_id": f"SYN-{i}", "priority_score": rng.uniform(0, 100)} for i in range(n)]


def test_insert_maintains_invariant():
    h = MaxHeap()
    for item in make(200):
        h.insert(item)
        assert h.is_valid()
    assert len(h) == 200


def test_extract_max_sorted_descending():
    items = make(300)
    h = MaxHeap(items)
    out = []
    while h:
        out.append(h.extract_max()["priority_score"])
        assert h.is_valid()
    assert out == sorted((i["priority_score"] for i in items), reverse=True)
    assert h.extract_max() is None and h.peek() is None


def test_peek_is_o1_and_non_destructive():
    h = MaxHeap(make(50))
    top = h.peek()
    assert top["priority_score"] == max(i["priority_score"] for i in make(50))
    assert len(h) == 50
    assert "_seq" not in top


def test_heapify_equals_inserts():
    items = make(500, seed=9)
    a = MaxHeap(items)
    b = MaxHeap()
    for i in items:
        b.insert(i)
    assert a.is_valid() and b.is_valid()
    assert [a.extract_max()["incident_id"] for _ in range(500)] == [b.extract_max()["incident_id"] for _ in range(500)]


def test_update_priority_up_and_down():
    h = MaxHeap(make(100))
    h.update_priority("SYN-42", 1000)
    assert h.peek()["incident_id"] == "SYN-42"
    h.update_priority("SYN-42", -5)
    assert h.is_valid()
    assert h.peek()["incident_id"] != "SYN-42"
    assert h.update_priority("missing", 1) is False


def test_remove_and_duplicates():
    h = MaxHeap(make(20))
    assert h.remove("SYN-3") is True
    assert not h.contains("SYN-3") and len(h) == 19 and h.is_valid()
    with pytest.raises(ValueError):
        h.insert({"incident_id": "SYN-4", "priority_score": 1})
    with pytest.raises(ValueError):
        h.insert({"incident_id": "no-score"})


def test_ties_are_fifo_deterministic():
    h = MaxHeap([{"incident_id": x, "priority_score": 50} for x in "ABCD"])
    assert [h.extract_max()["incident_id"] for _ in range(4)] == ["A", "B", "C", "D"]


def test_top_k_non_destructive():
    items = make(100, seed=4)
    h = MaxHeap(items)
    top = [x["priority_score"] for x in h.top_k(10)]
    assert top == sorted((i["priority_score"] for i in items), reverse=True)[:10]
    assert len(h) == 100


def test_display_heap_structure():
    h = MaxHeap(make(7))
    rows = h.display_heap()
    assert rows[0]["parent"] is None and rows[0]["left"] == 1 and rows[0]["right"] == 2
    assert rows[6]["parent"] == 2
    for r in rows[1:]:
        assert rows[r["parent"]]["priority_score"] >= r["priority_score"]
    assert h.to_dot().startswith("digraph")
