from __future__ import annotations

from hypercore_sdk.stats import _percentile, summarize_latencies


def test_percentile_empty_and_singleton() -> None:
    assert _percentile([], 0.95) == 0.0
    assert _percentile([7.0], 0.95) == 7.0


def test_percentile_interpolates() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert _percentile(values, 0.50) == 25.0
    assert _percentile(values, 0.95) == 38.5


def test_summarize_latencies_roundtrip() -> None:
    stats = summarize_latencies([1.0, 2.0, 3.0])
    as_dict = stats.as_dict()

    assert as_dict["count"] == 3
    assert as_dict["min_ms"] == 1.0
    assert as_dict["p50_ms"] == 2.0
    assert as_dict["p95_ms"] == 2.9
    assert as_dict["max_ms"] == 3.0
    assert as_dict["avg_ms"] == 2.0
