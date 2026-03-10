from __future__ import annotations

from typing import Any, Sequence

import httpx


UPSTREAM_UNAVAILABLE_STATUS_CODES = frozenset({502, 503, 504})
AUTH_DENIED_STATUS_CODES = frozenset({401, 403})
RATE_LIMIT_STATUS_CODES = frozenset({429})


def classify_http_status_code(status_code: int) -> dict[str, Any]:
    classification: dict[str, Any] = {"status_code": status_code}
    if status_code in UPSTREAM_UNAVAILABLE_STATUS_CODES:
        classification["error_kind"] = "upstream_unavailable"
        classification["availability"] = "upstream_unavailable"
    elif status_code in AUTH_DENIED_STATUS_CODES:
        classification["error_kind"] = "auth_denied"
        classification["availability"] = "denied"
    elif status_code in RATE_LIMIT_STATUS_CODES:
        classification["error_kind"] = "rate_limited"
        classification["availability"] = "degraded"
    else:
        classification["error_kind"] = "http_status_error"
        classification["availability"] = "error"
    return classification


def classify_http_exception(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_status_code(exc.response.status_code)

    if isinstance(exc, httpx.TransportError):
        return {
            "error_kind": "transport_error",
            "availability": "unreachable",
        }

    return {
        "error_kind": "runtime_error",
        "availability": "error",
    }


def summarize_event_availability(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"state": "unknown", "reason": "no_events"}

    successes = [event for event in events if event.get("ok")]
    failures = [event for event in events if not event.get("ok")]

    if successes and not failures:
        return {"state": "ok", "reason": "all_attempts_succeeded"}

    if successes and failures:
        error_kinds = sorted({str(event.get("error_kind", "error")) for event in failures})
        return {
            "state": "degraded",
            "reason": "mixed_success_and_failure",
            "error_kinds": error_kinds,
        }

    error_kinds = sorted({str(event.get("error_kind", "error")) for event in failures})
    status_codes = sorted(
        {
            int(event["status_code"])
            for event in failures
            if isinstance(event.get("status_code"), int)
        }
    )
    if error_kinds == ["upstream_unavailable"]:
        return {
            "state": "upstream_unavailable",
            "reason": "all_attempts_failed_upstream_unavailable",
            "error_kinds": error_kinds,
            "status_codes": status_codes,
        }
    if error_kinds == ["auth_denied"]:
        return {
            "state": "auth_denied",
            "reason": "all_attempts_failed_auth_denied",
            "error_kinds": error_kinds,
            "status_codes": status_codes,
        }
    if error_kinds == ["rate_limited"]:
        return {
            "state": "rate_limited",
            "reason": "all_attempts_failed_rate_limited",
            "error_kinds": error_kinds,
            "status_codes": status_codes,
        }
    if error_kinds == ["transport_error"]:
        return {
            "state": "unreachable",
            "reason": "all_attempts_failed_transport_error",
            "error_kinds": error_kinds,
        }
    return {
        "state": "error",
        "reason": "all_attempts_failed_mixed_errors",
        "error_kinds": error_kinds,
        "status_codes": status_codes,
    }
