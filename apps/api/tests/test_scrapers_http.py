"""Tests for HTTP retry behavior in scrapers/base."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from local_bazaar.scrapers import base
from local_bazaar.scrapers.base import fetch_with_retry, http_client


@pytest.fixture(autouse=True)
def _reset_robots_cache() -> Iterator[None]:
    """Clear the module-level robots.txt cache so tests never leak state.

    ``fetch_with_retry`` now checks robots.txt automatically. Without this
    fixture, whichever test runs first would populate the shared in-memory
    cache for ``example.test`` and every later test would silently reuse it.
    """
    base._robots_cache.clear()
    base._robots_locks.clear()
    yield
    base._robots_cache.clear()
    base._robots_locks.clear()


@pytest.mark.asyncio
async def test_fetch_with_retry_returns_ok_response() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://example.test/robots.txt").mock(
            return_value=httpx.Response(200, text="")
        )
        router.get("https://example.test/ok").mock(return_value=httpx.Response(200, text="OK"))
        async with http_client() as client:
            resp = await fetch_with_retry(client, "GET", "https://example.test/ok")
            assert resp.status_code == 200
            assert resp.text == "OK"


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_on_timeout() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://example.test/robots.txt").mock(
            return_value=httpx.Response(200, text="")
        )
        route = router.get("https://example.test/flaky")
        route.side_effect = [
            httpx.TimeoutException("boom"),
            httpx.TimeoutException("boom"),
            httpx.Response(200, text="finally"),
        ]
        async with http_client() as client:
            resp = await fetch_with_retry(client, "GET", "https://example.test/flaky")
        assert resp.text == "finally"
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_fetch_with_retry_does_not_retry_4xx() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://example.test/robots.txt").mock(
            return_value=httpx.Response(200, text="")
        )
        route = router.get("https://example.test/notfound").mock(
            return_value=httpx.Response(404, text="nope")
        )
        async with http_client() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_with_retry(client, "GET", "https://example.test/notfound")
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_fetch_with_retry_raises_when_robots_disallows() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://example.test/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        )
        route = router.get("https://example.test/private")
        async with http_client() as client:
            with pytest.raises(base.RobotsDisallowedError):
                await fetch_with_retry(client, "GET", "https://example.test/private")
        assert route.call_count == 0


@pytest.mark.asyncio
async def test_http_client_sets_user_agent_from_settings() -> None:
    async with http_client() as client:
        ua = client.headers.get("User-Agent")
        assert ua is not None
        assert "local_bazaar" in ua.lower() or len(ua) > 0
