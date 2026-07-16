"""Entity metadata and action tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from custom_components.amperfield_connect.button import (
    AmperfieldDisconnectSimulationButton,
)


@pytest.mark.asyncio
async def test_disconnect_simulation_button_writes_documented_value() -> None:
    """A press should write command value 1 and refresh status."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    client = MagicMock()
    client.set_disconnect_simulation = AsyncMock(return_value=True)
    entity = AmperfieldDisconnectSimulationButton(
        coordinator, client, DeviceInfo(), "SERIAL-1"
    )

    await entity.async_press()

    client.set_disconnect_simulation.assert_awaited_once_with(True)
    coordinator.async_request_refresh.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_disconnect_simulation_button_reports_write_failure() -> None:
    """Failed commands should be visible to Home Assistant callers."""
    coordinator = MagicMock()
    client = MagicMock()
    client.set_disconnect_simulation = AsyncMock(return_value=False)
    entity = AmperfieldDisconnectSimulationButton(
        coordinator, client, DeviceInfo(), "SERIAL-1"
    )

    with pytest.raises(
        HomeAssistantError, match="Failed to trigger disconnect simulation"
    ):
        await entity.async_press()
