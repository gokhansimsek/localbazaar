"""Tests for the robots.txt checker in scrapers/base."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from local_bazaar.scrapers import base
from local_bazaar.scrapers.base import is_allowed


@pytest.fixture(autouse=True)
def _reset_robots_cache() -> Iterator[None]:
    """Clear the module-level robots.txt cache before and after each test."""
    base._robots_cache.clear()
    base._robots_locks.clear()
    yield
    base._robots_cache.clear()
    base._robots_locks.clear()


@pytest.mark.asyncio
async def test_is_allowed_true_when_no_disallow_rule_matches() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://robots-allowed.test/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        )
        assert await is_allowed("https://robots-allowed.test/prices") is True


@pytest.mark.asyncio
async def test_is_allowed_false_when_disallow_rule_matches() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://robots-disallowed.test/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        )
        assert await is_allowed("https://robots-disallowed.test/private/page") is False


@pytest.mark.asyncio
async def test_is_allowed_fails_open_on_404() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://robots-404.test/robots.txt").mock(
            return_value=httpx.Response(404, text="not found")
        )
        assert await is_allowed("https://robots-404.test/anything") is True


@pytest.mark.asyncio
async def test_is_allowed_fails_open_on_network_error() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://robots-timeout.test/robots.txt").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )
        assert await is_allowed("https://robots-timeout.test/anything") is True


@pytest.mark.asyncio
async def test_is_allowed_fails_open_on_malformed_content() -> None:
    async with respx.mock(assert_all_called=False) as router:
        # Not a valid robots.txt at all — RobotFileParser.parse() should
        # tolerate it silently (no matching directives means "allow").
        router.get("https://robots-malformed.test/robots.txt").mock(
            return_value=httpx.Response(200, text="<html>this is not robots.txt</html>")
        )
        assert await is_allowed("https://robots-malformed.test/anything") is True


@pytest.mark.asyncio
async def test_is_allowed_respects_explicit_user_agent() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get("https://robots-ua.test/robots.txt").mock(
            return_value=httpx.Response(
                200,
                text="User-agent: local_bazaar/0.1\nDisallow: /blocked\n",
            )
        )
        assert (
            await is_allowed("https://robots-ua.test/blocked", user_agent="local_bazaar/0.1")
            is False
        )
        # A different, unrelated user-agent isn't covered by that group, and
        # there is no "*" catch-all group in this robots.txt, so it's allowed.
        assert (
            await is_allowed("https://robots-ua.test/blocked", user_agent="some-other-bot/1.0")
            is True
        )


@pytest.mark.asyncio
async def test_is_allowed_caches_robots_txt_fetch() -> None:
    async with respx.mock(assert_all_called=False) as router:
        route = router.get("https://robots-cache.test/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        )
        assert await is_allowed("https://robots-cache.test/one") is True
        assert await is_allowed("https://robots-cache.test/two") is True
        assert await is_allowed("https://robots-cache.test/private") is False
        # All three checks target the same host — robots.txt should only be
        # fetched once regardless of how many distinct paths are checked.
        assert route.call_count == 1
