"""Tests for the Netatmo data update coordinator."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest

from custom_components.netatmo_custom.api import NetatmoAPIError, NetatmoAuthError
from custom_components.netatmo_custom.const import UPDATE_INTERVAL, WEBHOOK_UPDATE_INTERVAL
from custom_components.netatmo_custom.coordinator import NetatmoDataUpdateCoordinator


@pytest.fixture
def coordinator(hass, homes_data, home_status) -> NetatmoDataUpdateCoordinator:
    """Return a coordinator with a mocked API."""
    api = MagicMock()
    api.async_get_homes_data = AsyncMock(return_value=homes_data)
    api.async_get_home_status = AsyncMock(return_value=home_status)
    return NetatmoDataUpdateCoordinator(hass, api, "home-1")


async def test_update_success(coordinator):
    """A successful update returns combined data and resets failures."""
    data = await coordinator._async_update_data()
    assert data["update_successful"] is True
    assert data["homes_data"]["status"] == "ok"
    assert data["home_status"]["status"] == "ok"
    assert coordinator.consecutive_failures == 0


async def test_auth_error_triggers_reauth(coordinator):
    """An auth error raises ConfigEntryAuthFailed to start reauth."""
    coordinator.api.async_get_homes_data = AsyncMock(side_effect=NetatmoAuthError("401"))
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_api_error_without_cache_raises_update_failed(coordinator):
    """An API error with no cached data raises UpdateFailed."""
    coordinator.api.async_get_homes_data = AsyncMock(side_effect=NetatmoAPIError("boom"))
    coordinator.data = None
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_api_error_with_cache_returns_stale(coordinator):
    """An API error with cached data returns stale data (graceful degradation)."""
    coordinator.data = {"homes_data": {}, "home_status": {}, "timestamp": 123}
    coordinator.api.async_get_home_status = AsyncMock(side_effect=NetatmoAPIError("boom"))
    data = await coordinator._async_update_data()
    assert data["stale"] is True
    assert data["update_successful"] is False
    assert coordinator.consecutive_failures == 1


async def test_api_error_exhausts_stale_window(coordinator):
    """After too many consecutive failures, UpdateFailed is raised."""
    coordinator.data = {"timestamp": 123}
    coordinator._consecutive_update_failures = 3  # next failure -> 4 (> 3)
    coordinator.api.async_get_home_status = AsyncMock(side_effect=NetatmoAPIError("boom"))
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_failure_backs_off_interval(coordinator):
    """A failure increases the polling interval (backoff)."""
    base = coordinator.update_interval
    coordinator._adjust_update_interval(success=False)
    assert coordinator.update_interval > base
    coordinator._adjust_update_interval(success=True)
    assert coordinator.consecutive_failures == 0


async def test_webhook_slows_polling_and_refreshes_in_background(hass, coordinator):
    """A device event marks webhooks active, slows polling and schedules a refresh."""
    coordinator.async_request_refresh = AsyncMock()
    await coordinator.async_handle_webhook({"push_type": "device_event", "home_id": "home-1"})
    await hass.async_block_till_done()
    assert coordinator.webhook_active is True
    assert coordinator.update_interval.total_seconds() == WEBHOOK_UPDATE_INTERVAL
    coordinator.async_request_refresh.assert_awaited_once()


async def test_webhook_activation_does_not_refresh(hass, coordinator):
    """webhook_activation only marks webhooks as active."""
    coordinator.async_request_refresh = AsyncMock()
    await coordinator.async_handle_webhook({"push_type": "webhook_activation"})
    await hass.async_block_till_done()
    assert coordinator.webhook_active is True
    coordinator.async_request_refresh.assert_not_awaited()


async def test_webhook_deletion_restores_polling(hass, coordinator):
    """webhook_deletion falls back to the regular polling interval."""
    coordinator.async_request_refresh = AsyncMock()
    await coordinator.async_handle_webhook({"push_type": "webhook_activation"})
    await coordinator.async_handle_webhook({"push_type": "webhook_deletion"})
    assert coordinator.webhook_active is False
    assert coordinator.update_interval.total_seconds() == UPDATE_INTERVAL


async def test_webhook_for_other_home_ignored(hass, coordinator):
    """Events for a different home don't trigger a refresh."""
    coordinator.async_request_refresh = AsyncMock()
    await coordinator.async_handle_webhook({"push_type": "device_event", "home_id": "other"})
    await hass.async_block_till_done()
    coordinator.async_request_refresh.assert_not_awaited()


async def test_webhook_expires(coordinator, monkeypatch):
    """Webhooks are considered inactive after the timeout."""
    coordinator._last_webhook_at = 0.0
    monkeypatch.setattr(
        "custom_components.netatmo_custom.coordinator.time.monotonic", lambda: 10_000_000.0
    )
    assert coordinator.webhook_active is False


async def test_successful_update_keeps_webhook_interval(coordinator):
    """While webhooks are active, a successful poll keeps the slow interval."""
    await coordinator.async_handle_webhook({"push_type": "webhook_activation"})
    await coordinator._async_update_data()
    assert coordinator.update_interval.total_seconds() == WEBHOOK_UPDATE_INTERVAL


async def test_homes_data_is_cached(coordinator):
    """homesdata is fetched once and reused across polls."""
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert coordinator.api.async_get_homes_data.await_count == 1
    assert coordinator.api.async_get_home_status.await_count == 2


async def test_homes_data_refetched_after_expiry(coordinator):
    """homesdata is re-fetched once the cache expires."""
    await coordinator._async_update_data()
    coordinator._homes_data_fetched_at = -1_000_000.0
    await coordinator._async_update_data()
    assert coordinator.api.async_get_homes_data.await_count == 2


async def test_topology_webhook_invalidates_homes_data(hass, coordinator):
    """topology_changed/home_event_changed force a homesdata re-fetch."""
    await coordinator._async_update_data()
    for push_type in ("topology_changed", "home_event_changed"):
        coordinator.async_request_refresh = AsyncMock()
        await coordinator.async_handle_webhook({"push_type": push_type})
        await hass.async_block_till_done()
        await coordinator._async_update_data()
    assert coordinator.api.async_get_homes_data.await_count == 3


async def test_is_data_stale(coordinator):
    """is_data_stale reflects missing/old/flagged data."""
    coordinator.data = None
    assert coordinator.is_data_stale() is True
    coordinator.data = {"stale": True, "timestamp": 9_999_999_999}
    assert coordinator.is_data_stale() is True
    coordinator.data = {"stale": False, "timestamp": 9_999_999_999}
    assert coordinator.is_data_stale() is False


async def test_last_successful_update_property(coordinator):
    """last_successful_update reflects the last success timestamp."""
    assert coordinator.last_successful_update is None
    await coordinator._async_update_data()
    assert coordinator.last_successful_update is not None


async def test_seconds_since_last_update(coordinator):
    """seconds_since_last_update is None before any update, then numeric."""
    assert coordinator.seconds_since_last_update is None
    await coordinator._async_update_data()
    seconds = coordinator.seconds_since_last_update
    assert seconds is not None
    assert seconds >= 0


async def test_recovery_logs_after_failures(coordinator):
    """A successful update after failures logs a recovery and resets."""
    coordinator._consecutive_update_failures = 2
    data = await coordinator._async_update_data()
    assert data["update_successful"] is True
    assert coordinator.consecutive_failures == 0


async def test_unexpected_error_raises_update_failed(coordinator):
    """A non-API exception surfaces as UpdateFailed."""
    coordinator.api.async_get_homes_data = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(UpdateFailed, match="Unexpected error"):
        await coordinator._async_update_data()


async def test_force_refresh_success(coordinator):
    """async_force_refresh returns True when the refresh produced data."""
    coordinator.async_request_refresh = AsyncMock()
    coordinator.data = {"update_successful": True}
    assert await coordinator.async_force_refresh() is True
    coordinator.async_request_refresh.assert_awaited_once()


async def test_force_refresh_failure(coordinator):
    """async_force_refresh returns False when data is missing/stale."""
    coordinator.async_request_refresh = AsyncMock()
    coordinator.data = None
    assert await coordinator.async_force_refresh() is False
    coordinator.data = {"update_successful": False}
    assert await coordinator.async_force_refresh() is False


async def test_force_refresh_exception(coordinator):
    """async_force_refresh returns False when the refresh raises."""
    coordinator.async_request_refresh = AsyncMock(side_effect=RuntimeError("boom"))
    assert await coordinator.async_force_refresh() is False
