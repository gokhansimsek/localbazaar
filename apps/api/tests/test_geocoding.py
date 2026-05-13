"""Unit tests for the Google Geocoding wrapper."""

from __future__ import annotations

import httpx
import pytest
import respx

from local_bazaar.geocoding import GEOCODE_URL, geocode_address


@pytest.mark.asyncio
async def test_geocode_address_returns_lat_lng_on_ok() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get(GEOCODE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "OK",
                    "results": [{"geometry": {"location": {"lat": 41.01, "lng": 28.97}}}],
                },
            )
        )
        async with httpx.AsyncClient() as client:
            out = await geocode_address(client, "Moda, Kadıköy, İstanbul", api_key="fake")
        assert out is not None
        assert out.latitude == 41.01
        assert out.longitude == 28.97


@pytest.mark.asyncio
async def test_geocode_address_returns_none_on_zero_results() -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get(GEOCODE_URL).mock(
            return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
        )
        async with httpx.AsyncClient() as client:
            out = await geocode_address(client, "nowhere", api_key="fake")
        assert out is None


@pytest.mark.asyncio
async def test_geocode_address_short_circuits_when_no_api_key() -> None:
    async with respx.mock(assert_all_called=False) as router:
        route = router.get(GEOCODE_URL)
        async with httpx.AsyncClient() as client:
            out = await geocode_address(client, "anywhere", api_key="")
        assert out is None
        assert route.call_count == 0  # never called the network


@pytest.mark.asyncio
async def test_geocode_address_sends_country_bias_and_language() -> None:
    captured_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={"status": "OK", "results": [{"geometry": {"location": {"lat": 0, "lng": 0}}}]},
        )

    async with respx.mock(assert_all_called=False) as router:
        router.get(GEOCODE_URL).mock(side_effect=handler)
        async with httpx.AsyncClient() as client:
            await geocode_address(client, "Beşiktaş, İstanbul", api_key="fake-key")
    assert captured_params["components"] == "country:TR"
    assert captured_params["language"] == "tr"
    assert captured_params["key"] == "fake-key"
    assert captured_params["address"] == "Beşiktaş, İstanbul"
