#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEED_SCRIPT = PROJECT_ROOT / "examples" / "feed_latency_examples.py"


def _load_env_credentials() -> None:
    candidates = [
        PROJECT_ROOT / "api" / ".env",
        PROJECT_ROOT / ".env",
        Path.cwd() / "api" / ".env",
        Path.cwd() / ".env",
    ]

    loaded: set[Path] = set()
    for path in candidates:
        if not path.is_file() or path in loaded:
            continue
        loaded.add(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value

    if "HYPER_API_KEY" not in os.environ and "API_KEY" in os.environ:
        os.environ["HYPER_API_KEY"] = os.environ["API_KEY"]
    if "RPC_GATEWAY_KEY" not in os.environ and "RPC_KEY" in os.environ:
        os.environ["RPC_GATEWAY_KEY"] = os.environ["RPC_KEY"]
    if "UNIFIED_STREAM_KEY" not in os.environ and "UNIFIED_KEY" in os.environ:
        os.environ["UNIFIED_STREAM_KEY"] = os.environ["UNIFIED_KEY"]
    if "DISK_STREAM_KEY" not in os.environ and "UNIFIED_KEY" in os.environ:
        os.environ["DISK_STREAM_KEY"] = os.environ["UNIFIED_KEY"]
    if "GRPC_STREAM_KEY" not in os.environ and "RPC_GATEWAY_KEY" in os.environ:
        os.environ["GRPC_STREAM_KEY"] = os.environ["RPC_GATEWAY_KEY"]
    if "GRPC_STREAM_KEY" not in os.environ and "HYPER_API_KEY" in os.environ:
        os.environ["GRPC_STREAM_KEY"] = os.environ["HYPER_API_KEY"]
    if "HYPER_API_KEY" not in os.environ and "RPC_GATEWAY_KEY" in os.environ:
        os.environ["HYPER_API_KEY"] = os.environ["RPC_GATEWAY_KEY"]


@dataclass(slots=True)
class ProviderSpec:
    name: str
    rpc_url: str | None = None
    ws_url: str | None = None
    disk_ws_url: str | None = None
    stream_url: str | None = None
    grpc_target: str | None = None
    grpc_server_name: str | None = None
    rpc_key: str | None = None
    grpc_key: str | None = None
    ws_key: str | None = None
    disk_ws_key: str | None = None
    unified_key: str | None = None
    ws_max_size: str | None = "none"
    unified_min_interval_ms: float = 700.0
    unified_retry_429: int = 1


def _from_mapping(data: dict[str, Any]) -> ProviderSpec:
    def _expand(value: Any) -> Any:
        if isinstance(value, str):
            return os.path.expandvars(value)
        return value

    return ProviderSpec(
        name=str(_expand(data["name"])),
        rpc_url=_expand(data.get("rpc_url")),
        ws_url=_expand(data.get("ws_url")),
        disk_ws_url=_expand(data.get("disk_ws_url")),
        stream_url=_expand(data.get("stream_url")),
        grpc_target=_expand(data.get("grpc_target")),
        grpc_server_name=_expand(data.get("grpc_server_name")),
        rpc_key=_expand(data.get("rpc_key")),
        grpc_key=_expand(data.get("grpc_key")),
        ws_key=_expand(data.get("ws_key")),
        disk_ws_key=_expand(data.get("disk_ws_key")),
        unified_key=_expand(data.get("unified_key")),
        ws_max_size=_expand(data.get("ws_max_size", "none")),
        unified_min_interval_ms=float(_expand(data.get("unified_min_interval_ms", 700.0))),
        unified_retry_429=int(_expand(data.get("unified_retry_429", 1))),
    )


def _default_provider_specs() -> list[ProviderSpec]:
    rpc_key = os.getenv("RPC_GATEWAY_KEY") or os.getenv("RPC_KEY") or os.getenv("HYPER_API_KEY")
    stream_key = os.getenv("UNIFIED_STREAM_KEY") or os.getenv("UNIFIED_KEY") or os.getenv("DISK_STREAM_KEY")
    grpc_stream_key = (
        os.getenv("ALEATORIC_GRPC_KEY")
        or os.getenv("GRPC_STREAM_KEY")
        or os.getenv("RPC_GATEWAY_KEY")
        or os.getenv("RPC_KEY")
        or rpc_key
        or stream_key
    )

    specs = [
        ProviderSpec(
            name="aleatoric",
            rpc_url=os.getenv("ALEATORIC_RPC_URL", "https://rpc.aleatoric.systems/"),
            ws_url=os.getenv("ALEATORIC_MARKET_WS_URL") or os.getenv("HYPER_MARKET_WS_URL", "wss://api.hyperliquid.xyz/ws"),
            disk_ws_url=os.getenv("ALEATORIC_DISK_WS_URL", "wss://disk.grpc.aleatoric.systems/"),
            stream_url=os.getenv("ALEATORIC_STREAM_URL", "https://unified.grpc.aleatoric.systems"),
            grpc_target=os.getenv("ALEATORIC_GRPC_TARGET", "hl.grpc.aleatoric.systems:443"),
            grpc_server_name=os.getenv("ALEATORIC_GRPC_SERVER_NAME"),
            rpc_key=rpc_key,
            grpc_key=grpc_stream_key,
            ws_key=os.getenv("ALEATORIC_MARKET_WS_KEY") or os.getenv("HYPER_API_KEY"),
            disk_ws_key=stream_key,
            unified_key=stream_key,
            ws_max_size=os.getenv("ALEATORIC_WS_MAX_SIZE", "none"),
            unified_min_interval_ms=float(os.getenv("ALEATORIC_UNIFIED_MIN_INTERVAL_MS", "700")),
            unified_retry_429=int(os.getenv("ALEATORIC_UNIFIED_RETRY_429", "1")),
        ),
        ProviderSpec(
            name="hyperliquid_public",
            rpc_url=os.getenv("HYPERLIQUID_PUBLIC_RPC_URL", "https://rpc.hyperliquid.xyz/evm"),
            ws_url=os.getenv("HYPERLIQUID_PUBLIC_WS_URL", "wss://api.hyperliquid.xyz/ws"),
            stream_url=None,
            grpc_target=None,
            rpc_key=None,
            grpc_key=None,
            ws_key=None,
            unified_key=None,
            ws_max_size=os.getenv("HYPERLIQUID_PUBLIC_WS_MAX_SIZE", "none"),
        ),
    ]

    hyperrpc_rpc = os.getenv("HYPERRPC_RPC_URL")
    hyperrpc_ws = os.getenv("HYPERRPC_WS_URL")
    hyperrpc_grpc = os.getenv("HYPERRPC_GRPC_TARGET")
    if hyperrpc_rpc or hyperrpc_ws or hyperrpc_grpc:
        key = os.getenv("HYPERRPC_API_KEY")
        specs.append(
            ProviderSpec(
                name="hyperrpc",
                rpc_url=hyperrpc_rpc,
                ws_url=hyperrpc_ws,
                grpc_target=hyperrpc_grpc,
                rpc_key=key,
                grpc_key=key,
                ws_key=key,
                disk_ws_key=key,
                unified_key=None,
                ws_max_size=os.getenv("HYPERRPC_WS_MAX_SIZE", "none"),
            )
        )

    dwellir_rpc = os.getenv("DWELLIR_RPC_URL")
    dwellir_ws = os.getenv("DWELLIR_WS_URL")
    dwellir_grpc = os.getenv("DWELLIR_GRPC_TARGET")
    if dwellir_rpc or dwellir_ws or dwellir_grpc:
        key = os.getenv("DWELLIR_API_KEY")
        specs.append(
            ProviderSpec(
                name="dwellir",
                rpc_url=dwellir_rpc,
                ws_url=dwellir_ws,
                grpc_target=dwellir_grpc,
                rpc_key=key,
                grpc_key=key,
                ws_key=key,
                disk_ws_key=key,
                unified_key=None,
                ws_max_size=os.getenv("DWELLIR_WS_MAX_SIZE", "none"),
            )
        )

    return specs


def _run_provider(
    spec: ProviderSpec,
    *,
    coin: str,
    runs: int,
    timeout: float,
    verify_tls: bool,
    grpc_subscriptions: str,
    grpc_include_liquidations: bool,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(FEED_SCRIPT),
        "--coin",
        coin,
        "--runs",
        str(runs),
        "--timeout",
        str(timeout),
        "--ws-max-size",
        spec.ws_max_size or "none",
        "--unified-min-interval-ms",
        str(spec.unified_min_interval_ms),
        "--unified-retry-429",
        str(spec.unified_retry_429),
        "--grpc-subscriptions",
        grpc_subscriptions,
    ]
    cmd.append("--verify-tls" if verify_tls else "--no-verify-tls")
    if grpc_include_liquidations:
        cmd.append("--grpc-include-liquidations")

    if spec.rpc_url:
        cmd.extend(["--rpc-url", spec.rpc_url])
    else:
        cmd.append("--skip-rpc")

    if spec.ws_url:
        cmd.extend(["--ws-url", spec.ws_url])
    else:
        cmd.append("--skip-ws")

    if spec.disk_ws_url:
        cmd.extend(["--disk-ws-url", spec.disk_ws_url])
    else:
        cmd.append("--skip-disk-ws")

    if spec.stream_url:
        cmd.extend(["--stream-url", spec.stream_url])
    else:
        cmd.append("--skip-unified")

    if spec.grpc_target:
        cmd.extend(["--grpc-target", spec.grpc_target])
    else:
        cmd.append("--skip-grpc")

    if spec.grpc_server_name:
        cmd.extend(["--grpc-server-name", spec.grpc_server_name])

    if spec.rpc_key:
        cmd.extend(["--rpc-key", spec.rpc_key])
    if spec.grpc_key:
        cmd.extend(["--grpc-key", spec.grpc_key])
    if spec.ws_key:
        cmd.extend(["--ws-key", spec.ws_key])
    if spec.disk_ws_key:
        cmd.extend(["--disk-ws-key", spec.disk_ws_key])
    if spec.unified_key:
        cmd.extend(["--unified-key", spec.unified_key])

    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "provider": spec.name,
            "ok": False,
            "returncode": proc.returncode,
            "stderr": proc.stderr,
            "stdout": proc.stdout,
        }

    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        return {
            "provider": spec.name,
            "ok": False,
            "returncode": 0,
            "error": f"failed to parse json: {exc}",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }

    return {
        "provider": spec.name,
        "ok": True,
        "result": payload,
    }


def _summary_row(provider_result: dict[str, Any]) -> dict[str, Any]:
    if not provider_result.get("ok"):
        return {
            "provider": provider_result.get("provider"),
            "status": "failed",
            "rpc_p50_ms": None,
            "ws_success_pct": None,
            "grpc_p50_ms": None,
            "unified_success_pct": None,
            "notes": provider_result.get("error") or f"rc={provider_result.get('returncode')}",
        }

    payload = provider_result["result"]
    feed_summary = payload.get("summary_by_feed_type", {})
    feed_results = payload.get("feeds", {})

    rpc = feed_summary.get("rpc", {})
    ws = feed_summary.get("ws", {})
    grpc = feed_summary.get("grpc", {})
    unified = feed_summary.get("unified", {})

    rpc_stats = rpc.get("aggregate_stats", {})
    grpc_stats = grpc.get("aggregate_stats", {})

    rpc_samples = rpc.get("samples", {})
    ws_samples = ws.get("samples", {})
    grpc_samples = grpc.get("samples", {})
    unified_samples = unified.get("samples", {})

    def _p50_or_none(stats: dict[str, Any]) -> float | None:
        try:
            return stats.get("p50_ms") if int(stats.get("count", 0)) > 0 else None
        except Exception:
            return None

    def _rate_or_none(samples: dict[str, Any]) -> float | None:
        try:
            return samples.get("success_rate_pct") if int(samples.get("total", 0)) > 0 else None
        except Exception:
            return None

    notes: list[str] = []
    for feed_name, samples in (
        ("rpc", rpc_samples),
        ("ws", ws_samples),
        ("grpc", grpc_samples),
        ("unified", unified_samples),
    ):
        total = int(samples.get("total", 0) or 0)
        failed = int(samples.get("failed", 0) or 0)
        if total > 0 and failed > 0:
            ok = int(samples.get("ok", 0) or 0)
            notes.append(f"{feed_name} {ok}/{total} ok")

    liq = feed_results.get("grpc.liquidations", {})
    if isinstance(liq, dict) and int(liq.get("skipped", 0) or 0) > 0:
        reason = str(liq.get("skipped_reason") or "not configured")
        notes.append(f"grpc.liquidations skipped ({reason})")

    tested_sample_sets = [s for s in (rpc_samples, ws_samples, grpc_samples, unified_samples) if int(s.get("total", 0) or 0) > 0]
    has_partial_failures = any(int(s.get("failed", 0) or 0) > 0 for s in tested_sample_sets)
    status = "partial" if has_partial_failures else "ok"

    return {
        "provider": provider_result.get("provider"),
        "status": status,
        "rpc_p50_ms": _p50_or_none(rpc_stats),
        "ws_success_pct": _rate_or_none(ws_samples),
        "grpc_p50_ms": _p50_or_none(grpc_stats),
        "unified_success_pct": _rate_or_none(unified_samples),
        "notes": "; ".join(notes),
    }


def _format_number(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _print_markdown(rows: list[dict[str, Any]]) -> None:
    print("| provider | status | rpc_p50_ms | ws_success_pct | grpc_p50_ms | unified_success_pct | notes |")
    print("|---|---:|---:|---:|---:|---:|---|")
    for row in rows:
        print(
            "| {provider} | {status} | {rpc_p50} | {ws_success} | {grpc_p50} | {unified_success} | {notes} |".format(
                provider=row["provider"],
                status=row["status"],
                rpc_p50=_format_number(row["rpc_p50_ms"]),
                ws_success=_format_number(row["ws_success_pct"]),
                grpc_p50=_format_number(row["grpc_p50_ms"]),
                unified_success=_format_number(row["unified_success_pct"]),
                notes=row["notes"],
            )
        )


def _load_specs(path: Path | None) -> list[ProviderSpec]:
    if path is None:
        return _default_provider_specs()

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("providers", data)
    if not isinstance(items, list):
        raise ValueError("providers config must be a list or object with 'providers' list")
    return [_from_mapping(item) for item in items]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run feed latency benchmark against multiple providers and print a normalized comparison table."
    )
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--verify-tls",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--providers-json",
        default=None,
        help=(
            "Optional JSON config file for provider endpoints/keys. "
            "If omitted, built-in defaults target Aleatoric + Hyperliquid public "
            "(and include HyperRPC/Dwellir when env vars are present)."
        ),
    )
    parser.add_argument(
        "--grpc-subscriptions",
        default="allMids,trades,l2Book",
        help="Comma-separated gRPC StreamMids subscriptions to benchmark per provider.",
    )
    parser.add_argument(
        "--grpc-include-liquidations",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also benchmark dedicated StreamLiquidations per provider.",
    )
    parser.add_argument("--out-json", default=None, help="Optional file to write full raw results JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env_credentials()
    args = build_parser().parse_args(argv)

    config_path = Path(args.providers_json) if args.providers_json else None
    specs = _load_specs(config_path)

    results: list[dict[str, Any]] = []
    for spec in specs:
        results.append(
            _run_provider(
                spec,
                coin=args.coin,
                runs=args.runs,
                timeout=args.timeout,
                verify_tls=args.verify_tls,
                grpc_subscriptions=args.grpc_subscriptions,
                grpc_include_liquidations=args.grpc_include_liquidations,
            )
        )

    rows = [_summary_row(item) for item in results]
    _print_markdown(rows)

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.write_text(json.dumps({"providers": results, "rows": rows}, indent=2), encoding="utf-8")
        print(f"\nWrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
