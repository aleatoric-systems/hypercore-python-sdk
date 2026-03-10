from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping, Sequence


@dataclass(frozen=True, slots=True)
class ResolvedKey:
    value: str | None
    source: str | None


def load_env_credentials(
    project_root: Path,
    *,
    cwd: Path | None = None,
    env: MutableMapping[str, str] | None = None,
) -> list[str]:
    environment = os.environ if env is None else env
    working_dir = cwd or Path.cwd()
    loaded: list[str] = []
    seen: set[Path] = set()
    candidates = [
        project_root / "api" / ".env",
        project_root / ".env",
        working_dir / "api" / ".env",
        working_dir / ".env",
    ]

    for path in candidates:
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        loaded.append(str(path))
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
            if key and key not in environment:
                environment[key] = value

    apply_env_aliases(environment)
    return loaded


def apply_env_aliases(env: MutableMapping[str, str]) -> None:
    if "HYPER_API_KEY" not in env and "API_KEY" in env:
        env["HYPER_API_KEY"] = env["API_KEY"]
    if "RPC_GATEWAY_KEY" not in env and "RPC_KEY" in env:
        env["RPC_GATEWAY_KEY"] = env["RPC_KEY"]
    if "UNIFIED_STREAM_KEY" not in env and "UNIFIED_KEY" in env:
        env["UNIFIED_STREAM_KEY"] = env["UNIFIED_KEY"]
    if "DISK_STREAM_KEY" not in env and "UNIFIED_KEY" in env:
        env["DISK_STREAM_KEY"] = env["UNIFIED_KEY"]
    if "GRPC_STREAM_KEY" not in env and "RPC_GATEWAY_KEY" in env:
        env["GRPC_STREAM_KEY"] = env["RPC_GATEWAY_KEY"]
    if "GRPC_STREAM_KEY" not in env and "HYPER_API_KEY" in env:
        env["GRPC_STREAM_KEY"] = env["HYPER_API_KEY"]
    if "GRPC_STREAM_KEY" not in env and "UNIFIED_STREAM_KEY" in env:
        env["GRPC_STREAM_KEY"] = env["UNIFIED_STREAM_KEY"]
    if "HYPER_API_KEY" not in env and "RPC_GATEWAY_KEY" in env:
        env["HYPER_API_KEY"] = env["RPC_GATEWAY_KEY"]


def clean_key(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return None
    if cleaned.startswith("${") and cleaned.endswith("}"):
        return None
    if any(char in cleaned for char in {" ", "\t", "\n", "<", ">"}):
        return None
    return cleaned


def mask_key(value: str | None) -> str | None:
    cleaned = clean_key(value)
    if not cleaned:
        return None
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def split_key_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in re.split(r"[,\s]+", raw.strip()) if part]


def pick_key(explicit: str | None, candidates: Sequence[tuple[str, str | None]]) -> ResolvedKey:
    cleaned = clean_key(explicit)
    if cleaned:
        return ResolvedKey(cleaned, "cli")
    for source, value in candidates:
        cleaned = clean_key(value)
        if cleaned:
            return ResolvedKey(cleaned, source)
    return ResolvedKey(None, None)


def generic_key_candidate(*, env: MutableMapping[str, str] | None = None) -> tuple[str, str | None]:
    environment = os.environ if env is None else env
    return ("HYPER_API_KEY|API_KEY", environment.get("HYPER_API_KEY") or environment.get("API_KEY"))


def api_keys_candidate(*, env: MutableMapping[str, str] | None = None) -> tuple[str, str | None]:
    environment = os.environ if env is None else env
    values = split_key_list(environment.get("api_keys"))
    return ("api_keys[0]", values[0] if values else None)


def rpc_key_candidates(*, env: MutableMapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    environment = os.environ if env is None else env
    return [
        ("RPC_GATEWAY_KEY", environment.get("RPC_GATEWAY_KEY")),
        ("RPC_KEY", environment.get("RPC_KEY")),
        generic_key_candidate(env=environment),
        api_keys_candidate(env=environment),
    ]


def market_ws_key_candidates(*, env: MutableMapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    environment = os.environ if env is None else env
    return [
        ("ALEATORIC_MARKET_WS_KEY", environment.get("ALEATORIC_MARKET_WS_KEY")),
        generic_key_candidate(env=environment),
        api_keys_candidate(env=environment),
    ]


def unified_key_candidates(*, env: MutableMapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    environment = os.environ if env is None else env
    return [
        ("UNIFIED_STREAM_KEY", environment.get("UNIFIED_STREAM_KEY")),
        ("UNIFIED_KEY", environment.get("UNIFIED_KEY")),
        generic_key_candidate(env=environment),
        api_keys_candidate(env=environment),
    ]


def disk_ws_key_candidates(*, env: MutableMapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    environment = os.environ if env is None else env
    return [
        ("DISK_STREAM_KEY", environment.get("DISK_STREAM_KEY")),
        ("UNIFIED_STREAM_KEY", environment.get("UNIFIED_STREAM_KEY")),
        ("UNIFIED_KEY", environment.get("UNIFIED_KEY")),
        generic_key_candidate(env=environment),
        api_keys_candidate(env=environment),
    ]


def grpc_key_candidates(*, env: MutableMapping[str, str] | None = None) -> list[tuple[str, str | None]]:
    environment = os.environ if env is None else env
    return [
        ("ALEATORIC_GRPC_KEY", environment.get("ALEATORIC_GRPC_KEY")),
        ("RPC_GATEWAY_KEY", environment.get("RPC_GATEWAY_KEY")),
        ("RPC_KEY", environment.get("RPC_KEY")),
        generic_key_candidate(env=environment),
        ("GRPC_STREAM_KEY", environment.get("GRPC_STREAM_KEY")),
        ("UNIFIED_STREAM_KEY", environment.get("UNIFIED_STREAM_KEY")),
        ("UNIFIED_KEY", environment.get("UNIFIED_KEY")),
        api_keys_candidate(env=environment),
    ]
