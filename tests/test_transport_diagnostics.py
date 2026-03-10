from __future__ import annotations

import httpx

from hypercore_sdk.transport_diagnostics import (
    classify_http_exception,
    classify_http_status_code,
    summarize_event_availability,
)


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code} error", request=request, response=response)


def test_classify_http_status_code_marks_upstream_unavailable() -> None:
    classification = classify_http_status_code(502)

    assert classification == {
        "status_code": 502,
        "error_kind": "upstream_unavailable",
        "availability": "upstream_unavailable",
    }


def test_classify_http_exception_marks_auth_denied() -> None:
    classification = classify_http_exception(_http_error(403))

    assert classification == {
        "status_code": 403,
        "error_kind": "auth_denied",
        "availability": "denied",
    }


def test_classify_http_status_code_marks_generic_http_error() -> None:
    classification = classify_http_status_code(418)

    assert classification == {
        "status_code": 418,
        "error_kind": "http_status_error",
        "availability": "error",
    }


def test_classify_http_exception_marks_transport_and_runtime_failures() -> None:
    transport = classify_http_exception(httpx.ConnectError("boom"))
    runtime = classify_http_exception(RuntimeError("boom"))

    assert transport == {
        "error_kind": "transport_error",
        "availability": "unreachable",
    }
    assert runtime == {
        "error_kind": "runtime_error",
        "availability": "error",
    }


def test_summarize_event_availability_marks_degraded_when_mixed() -> None:
    availability = summarize_event_availability(
        [
            {"ok": True, "latency_ms": 12.3},
            {"ok": False, "error_kind": "upstream_unavailable", "status_code": 502},
        ]
    )

    assert availability == {
        "state": "degraded",
        "reason": "mixed_success_and_failure",
        "error_kinds": ["upstream_unavailable"],
    }


def test_summarize_event_availability_marks_full_upstream_outage() -> None:
    availability = summarize_event_availability(
        [
            {"ok": False, "error_kind": "upstream_unavailable", "status_code": 502},
            {"ok": False, "error_kind": "upstream_unavailable", "status_code": 502},
        ]
    )

    assert availability == {
        "state": "upstream_unavailable",
        "reason": "all_attempts_failed_upstream_unavailable",
        "error_kinds": ["upstream_unavailable"],
        "status_codes": [502],
    }


def test_summarize_event_availability_handles_empty_success_and_other_failures() -> None:
    assert summarize_event_availability([]) == {
        "state": "unknown",
        "reason": "no_events",
    }
    assert summarize_event_availability([{"ok": True, "latency_ms": 1.0}]) == {
        "state": "ok",
        "reason": "all_attempts_succeeded",
    }
    assert summarize_event_availability(
        [{"ok": False, "error_kind": "auth_denied", "status_code": 403}]
    ) == {
        "state": "auth_denied",
        "reason": "all_attempts_failed_auth_denied",
        "error_kinds": ["auth_denied"],
        "status_codes": [403],
    }
    assert summarize_event_availability(
        [{"ok": False, "error_kind": "rate_limited", "status_code": 429}]
    ) == {
        "state": "rate_limited",
        "reason": "all_attempts_failed_rate_limited",
        "error_kinds": ["rate_limited"],
        "status_codes": [429],
    }
    assert summarize_event_availability(
        [{"ok": False, "error_kind": "transport_error"}]
    ) == {
        "state": "unreachable",
        "reason": "all_attempts_failed_transport_error",
        "error_kinds": ["transport_error"],
    }
    assert summarize_event_availability(
        [
            {"ok": False, "error_kind": "transport_error"},
            {"ok": False, "error_kind": "runtime_error"},
        ]
    ) == {
        "state": "error",
        "reason": "all_attempts_failed_mixed_errors",
        "error_kinds": ["runtime_error", "transport_error"],
        "status_codes": [],
    }
