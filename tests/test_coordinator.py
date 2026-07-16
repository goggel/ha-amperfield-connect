"""Coordinator failure handling tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.amperfield_connect import AmperfieldDataUpdateCoordinator
from custom_components.amperfield_connect.modbus_client import (
    AmperfieldConnectionError,
)


@pytest.mark.asyncio
async def test_transport_failure_marks_coordinator_update_failed() -> None:
    """A transport failure must drive CoordinatorEntity availability."""
    coordinator = object.__new__(AmperfieldDataUpdateCoordinator)
    coordinator.client = MagicMock()
    coordinator.client.fetch_selected_data = AsyncMock(
        side_effect=AmperfieldConnectionError("offline")
    )
    coordinator._subscriptions = {"charging_state": {"sensor.wallbox_state"}}

    with pytest.raises(UpdateFailed, match="Error communicating with device"):
        await coordinator._async_update_data()
