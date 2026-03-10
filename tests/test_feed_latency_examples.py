from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "examples" / "feed_latency_examples.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("examples.feed_latency_examples", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_result_payload_includes_availability_summary() -> None:
    module = _load_module()

    payload = module._result_payload(
        [
            {
                "ok": False,
                "latency_ms": 800.0,
                "error": "Server error '502 Bad Gateway'",
                "error_kind": "upstream_unavailable",
                "status_code": 502,
            }
        ],
        metric_kind="request_response_rtt",
    )

    assert payload["availability"] == {
        "state": "upstream_unavailable",
        "reason": "all_attempts_failed_upstream_unavailable",
        "error_kinds": ["upstream_unavailable"],
        "status_codes": [502],
    }


def test_build_availability_alerts_reports_non_ok_feeds() -> None:
    module = _load_module()

    alerts = module._build_availability_alerts(
        {
            "rpc.eth_blockNumber": {
                "availability": {
                    "state": "upstream_unavailable",
                    "reason": "all_attempts_failed_upstream_unavailable",
                    "error_kinds": ["upstream_unavailable"],
                    "status_codes": [502],
                }
            },
            "ws.allMids": {
                "availability": {
                    "state": "ok",
                    "reason": "all_attempts_succeeded",
                }
            },
        }
    )

    assert alerts == [
        {
            "feed": "rpc.eth_blockNumber",
            "state": "upstream_unavailable",
            "reason": "all_attempts_failed_upstream_unavailable",
            "error_kinds": ["upstream_unavailable"],
            "status_codes": [502],
        }
    ]
