"""Each client must parse the shapes recorded in docs/camara-findings.md, and every
failure must degrade to a flagged fallback rather than raising.

The response bodies below are copied verbatim from the observed probe output.
"""

import httpx
import pytest
import respx

from app.camara import base
from app.camara.call_forwarding import check_call_forwarding
from app.camara.device_status import check_device_status
from app.camara.location_verification import verify_location
from app.camara.models import LocationVerificationResult, SignalSource
from app.camara.sim_swap import check_sim_swap, retrieve_sim_swap_date
from app.config import settings

BASE_URL = "https://nac.test"
SWAPPED = "+99999991000"
CLEAN = "+99999991001"

CF = "/passthrough/camara/v1/call-forwarding-signal/call-forwarding-signal/v0.3"
SS = "/passthrough/camara/v1/sim-swap/sim-swap/v0"


@pytest.fixture(autouse=True)
async def _isolate(monkeypatch):
    """Point clients at a fake host and guarantee DEMO_MODE is off for these tests."""
    monkeypatch.setattr(settings, "nokia_nac_base_url", BASE_URL)
    monkeypatch.setattr(settings, "nokia_nac_api_key", "test-key")
    monkeypatch.setattr(settings, "demo_mode", False)
    await base.close_client()
    yield
    await base.close_client()


# --------------------------------------------------------------------- parsing


@respx.mock
async def test_sim_swap_parses_swapped():
    respx.post(f"{BASE_URL}{SS}/check").mock(
        return_value=httpx.Response(200, json={"swapped": True})
    )
    signal = await check_sim_swap(SWAPPED)
    assert signal.swapped is True
    assert signal.source is SignalSource.LIVE
    assert signal.raw == {"swapped": True}


@respx.mock
async def test_sim_swap_retrieve_date_parses_timestamp():
    respx.post(f"{BASE_URL}{SS}/retrieve-date").mock(
        return_value=httpx.Response(
            200, json={"latestSimChange": "2026-08-12T11:40:52.028918Z"}
        )
    )
    signal = await retrieve_sim_swap_date(SWAPPED)
    assert signal.swapped is True
    assert signal.latest_sim_change is not None
    assert signal.latest_sim_change.year == 2026


@respx.mock
async def test_sim_swap_null_date_means_not_swapped():
    respx.post(f"{BASE_URL}{SS}/retrieve-date").mock(
        return_value=httpx.Response(200, json={"latestSimChange": None})
    )
    signal = await retrieve_sim_swap_date(CLEAN)
    assert signal.swapped is False
    assert signal.latest_sim_change is None


@respx.mock
async def test_call_forwarding_combines_both_endpoints():
    respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").mock(
        return_value=httpx.Response(200, json={"active": True})
    )
    respx.post(f"{BASE_URL}{CF}/call-forwardings").mock(
        return_value=httpx.Response(200, json=["unconditional", "conditional_no_answer"])
    )
    signal = await check_call_forwarding(SWAPPED)
    assert signal.active is True
    assert signal.forwarding_types == ["unconditional", "conditional_no_answer"]


@respx.mock
async def test_call_forwarding_survives_501_on_type_list():
    """A 501 on the optional endpoint must not lose the primary answer."""
    respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").mock(
        return_value=httpx.Response(200, json={"active": True})
    )
    respx.post(f"{BASE_URL}{CF}/call-forwardings").mock(
        return_value=httpx.Response(501, json={"detail": "Not Implemented"})
    )
    signal = await check_call_forwarding(SWAPPED)
    assert signal.active is True
    assert signal.forwarding_types == []
    assert signal.source is SignalSource.LIVE  # still a live answer, not a fallback


@respx.mock
async def test_device_status_parses_roaming_country_list():
    respx.post(f"{BASE_URL}/device-status/device-roaming-status/v1/retrieve").mock(
        return_value=httpx.Response(200, json={
            "device": {"phoneNumber": SWAPPED},
            "lastStatusTime": "2026-08-12T11:50:53.268270Z",
            "roaming": True, "countryCode": 36, "countryName": ["HU"],
        })
    )
    signal = await check_device_status(SWAPPED)
    assert signal.roaming is True
    assert signal.country_code == 36
    assert signal.country_names == ["HU"]


@respx.mock
async def test_device_status_home_network_omits_country():
    respx.post(f"{BASE_URL}/device-status/device-roaming-status/v1/retrieve").mock(
        return_value=httpx.Response(200, json={
            "device": {"phoneNumber": CLEAN},
            "lastStatusTime": "2026-08-12T11:50:53.534302Z",
            "roaming": False,
        })
    )
    signal = await check_device_status(CLEAN)
    assert signal.roaming is False
    assert signal.country_code is None
    assert signal.country_names == []


@respx.mock
async def test_location_partial_carries_match_rate():
    respx.post(f"{BASE_URL}/location-verification/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "verificationResult": "PARTIAL", "matchRate": 74,
            "lastLocationTime": "2026-08-12T11:50:54.339972",
        })
    )
    signal = await verify_location(SWAPPED, 25.204849, 55.270783)
    assert signal.verification_result is LocationVerificationResult.PARTIAL
    assert signal.match_rate == 74


# -------------------------------------------------------------------- fallback


@respx.mock
async def test_500_triggers_fallback_after_retries():
    route = respx.post(f"{BASE_URL}{SS}/check").mock(
        return_value=httpx.Response(500, json={"detail": "Internal Server Error"})
    )
    signal = await check_sim_swap(SWAPPED)

    assert signal.source is SignalSource.FALLBACK
    assert signal.fallback_reason is not None
    assert "500" in signal.fallback_reason
    assert route.call_count == settings.camara_max_retries + 1
    # The cached story must still be coherent for this scenario.
    assert signal.swapped is True
    # The failed attempt cost real time; reporting 0 would understate added latency.
    assert signal.latency_ms > 0


@respx.mock
async def test_4xx_does_not_retry():
    """A 400 is deterministic — retrying only burns the latency budget."""
    route = respx.post(f"{BASE_URL}{SS}/check").mock(
        return_value=httpx.Response(400, json={"detail": "Bad Request"})
    )
    signal = await check_sim_swap(SWAPPED)

    assert signal.source is SignalSource.FALLBACK
    assert route.call_count == 1


@respx.mock
async def test_timeout_triggers_fallback():
    respx.post(f"{BASE_URL}/device-status/device-roaming-status/v1/retrieve").mock(
        side_effect=httpx.ConnectTimeout("too slow")
    )
    signal = await check_device_status(CLEAN)
    assert signal.source is SignalSource.FALLBACK
    assert signal.roaming is False


@respx.mock
async def test_demo_mode_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    route = respx.post(f"{BASE_URL}{CF}/unconditional-call-forwardings").mock(
        return_value=httpx.Response(200, json={"active": False})
    )
    signal = await check_call_forwarding(SWAPPED)

    assert route.call_count == 0
    assert signal.source is SignalSource.FALLBACK
    assert signal.fallback_reason == "DEMO_MODE enabled"
    assert signal.active is True


async def test_every_api_has_a_fallback():
    """A signal with no fallback can break a live demo — guard against forgetting one."""
    from app.camara.fallback import _BUILDERS

    assert set(_BUILDERS) == {
        "sim_swap", "call_forwarding", "device_status", "location_verification",
    }
