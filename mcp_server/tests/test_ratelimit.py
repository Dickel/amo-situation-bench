"""Rate limiter — pure Python, no network."""

from __future__ import annotations

import pytest

from mcp_server.ratelimit import RateLimiter, RateLimitExceeded


def test_allows_up_to_max_then_blocks():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        rl.check("client-a")
    with pytest.raises(RateLimitExceeded):
        rl.check("client-a")


def test_buckets_are_per_key():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    rl.check("client-a")
    rl.check("client-b")  # different key, own budget
    with pytest.raises(RateLimitExceeded):
        rl.check("client-a")


def test_message_names_the_budget():
    rl = RateLimiter(max_requests=1, window_seconds=30)
    rl.check("k")
    with pytest.raises(RateLimitExceeded, match="1 requests / 30s"):
        rl.check("k")
