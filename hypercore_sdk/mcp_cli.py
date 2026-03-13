from __future__ import annotations

from .mcp import HypercoreMCPServer


def main() -> int:
    server = HypercoreMCPServer()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
