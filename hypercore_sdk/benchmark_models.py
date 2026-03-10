from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired


class LatencyStats(TypedDict):
    count: int
    min_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    avg_ms: float


class AvailabilitySummary(TypedDict, total=False):
    state: str
    reason: str
    error_kinds: list[str]
    status_codes: list[int]


class BenchmarkEvent(TypedDict, total=False):
    attempt: int
    start_time_ms: int
    start_time_iso_utc: str
    start_perf_counter_s: float
    end_time_ms: int
    end_time_iso_utc: str
    end_perf_counter_s: float
    latency_ms: float
    ok: bool
    error: str
    status_code: int
    error_kind: str
    availability: str
    event_ts_ms: int
    event_age_ms: int
    stream_channel: str
    stream_source: str
    sdk_reported_latency_ms: float
    tx_hash: str
    block_number: int
    skipped: bool
    sse_payload_parsed: bool


class FeedResult(TypedDict, total=False):
    metric_kind: str
    stats: LatencyStats
    event_age_stats: LatencyStats
    availability: AvailabilitySummary
    ok: int
    failed: int
    skipped: int
    errors: list[str]
    events: list[BenchmarkEvent]
    skipped_reason: str


class SamplesSummary(TypedDict):
    ok: int
    failed: int
    total: int
    success_rate_pct: float


class FeedSummary(TypedDict):
    feeds: list[str]
    samples: SamplesSummary
    aggregate_stats: LatencyStats
    latency_profile: str
    overview: str


class MetricSummary(TypedDict):
    feeds: list[str]
    samples: SamplesSummary
    latency_stats: LatencyStats
    event_age_stats: LatencyStats
    overview: str


class AvailabilityAlert(TypedDict):
    feed: str
    state: str
    reason: NotRequired[str]
    error_kinds: list[str]
    status_codes: list[int]


class ExitRecommendation(TypedDict):
    state: str
    code: int


class BenchmarkReport(TypedDict):
    coin: str
    runs: int
    timeout_s: float
    measurement_notes: dict[str, str]
    auth_key_selection: dict[str, str | None]
    auth_key_sources: dict[str, str | None]
    latency_measurement_stamps: dict[str, str]
    feeds: dict[str, FeedResult]
    summary_by_feed_type: dict[str, FeedSummary]
    summary_by_metric_kind: dict[str, MetricSummary]
    availability_alerts: list[AvailabilityAlert]
    exit_recommendation: ExitRecommendation
    profile_name: NotRequired[str | None]
    profile_path: NotRequired[str | None]
