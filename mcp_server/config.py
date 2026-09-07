"""Runtime configuration, all from the environment.

  DOMAINS           comma list. Default "AMO" (the only domain this repo ships).
                    Each domain is served as its own MCP endpoint at
                    /<domain-lower>/mcp with only that domain's tools and data —
                    the seam for adding another domain later.
  DOMAIN            single-domain shorthand — overrides DOMAINS.
  MEMGRAPH_URI      default bolt://localhost:7687
  MEMGRAPH_USER     optional (Memgraph Community has auth off by default)
  MEMGRAPH_PASSWORD optional
  MCP_HOST          default 0.0.0.0
  MCP_PORT          default 8000
  MCP_ALLOWED_HOSTS optional comma list. If set, the MCP transport only accepts
                    requests whose Host header matches (DNS-rebinding
                    protection). If unset, that check is off — the right default
                    for a public server, where the protection (aimed at
                    browser-reachable localhost servers) does not apply.
  RATE_LIMIT_MAX    default 60   — requests per window, per client, per domain
  RATE_LIMIT_WINDOW default 60   — window in seconds
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VALID_DOMAINS = ("AMO",)


@dataclass(frozen=True)
class Config:
    domains: tuple[str, ...]
    memgraph_uri: str
    memgraph_user: str | None
    memgraph_password: str | None
    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    rate_limit_max: int
    rate_limit_window: int

    def mount_path(self, domain: str) -> str:
        return f"/{domain.lower()}"

    def endpoint(self, domain: str) -> str:
        return f"{self.mount_path(domain)}/mcp"


def _parse_domains() -> tuple[str, ...]:
    single = (os.environ.get("DOMAIN") or "").strip().upper()
    if single:
        raw = [single]
    else:
        raw = [d.strip().upper() for d in (os.environ.get("DOMAINS") or "AMO").split(",")]
    seen: list[str] = []
    for d in raw:
        if not d:
            continue
        if d not in VALID_DOMAINS:
            raise SystemExit(f"unknown domain {d!r}; valid: {list(VALID_DOMAINS)}")
        if d not in seen:
            seen.append(d)
    if not seen:
        raise SystemExit("no domains configured (set DOMAINS or DOMAIN)")
    return tuple(seen)


def load() -> Config:
    return Config(
        domains=_parse_domains(),
        memgraph_uri=os.environ.get("MEMGRAPH_URI", "bolt://localhost:7687"),
        memgraph_user=os.environ.get("MEMGRAPH_USER"),
        memgraph_password=os.environ.get("MEMGRAPH_PASSWORD"),
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
        allowed_hosts=tuple(
            h.strip() for h in (os.environ.get("MCP_ALLOWED_HOSTS") or "").split(",") if h.strip()
        ),
        rate_limit_max=int(os.environ.get("RATE_LIMIT_MAX", "60")),
        rate_limit_window=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
    )
