from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LatencyStats:
    count: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    avg_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "min_ms": round(self.min_ms, 3),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "avg_ms": round(self.avg_ms, 3),
        }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def summarize_latencies(latencies_ms: list[float]) -> LatencyStats:
    if not latencies_ms:
        return LatencyStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return LatencyStats(
        count=len(latencies_ms),
        min_ms=min(latencies_ms),
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=_percentile(latencies_ms, 0.95),
        max_ms=max(latencies_ms),
        avg_ms=sum(latencies_ms) / len(latencies_ms),
    )
