"""Entity metadata and action tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from custom_components.amperfield_connect.button import (
    AmperfieldDisconnectSimulationButton,
)
from custom_components.amperfield_connect.number import (
    AmperfieldMaxCurrentNumber,
    AmperfieldMaxPowerNumber,
)
from custom_components.amperfield_connect.sensor import (
    AmperfieldChargingStateSensor,
    AmperfieldPhaseSwitchStateSensor,
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


@pytest.mark.parametrize(
    ("sensor_type", "key", "value", "expected"),
    [
        (AmperfieldChargingStateSensor, "charging_state", 1, None),
        (AmperfieldChargingStateSensor, "charging_state", None, None),
        (AmperfieldChargingStateSensor, "charging_state", 7, "charging"),
        (AmperfieldPhaseSwitchStateSensor, "phase_switch_state", 2, None),
        (AmperfieldPhaseSwitchStateSensor, "phase_switch_state", 3, "3_phases"),
    ],
)
def test_enum_states_are_valid_home_assistant_values(
    sensor_type: type, key: str, value: int | None, expected: str | None
) -> None:
    """Exercise HA's real enum validation, including unknown device values."""
    coordinator = MagicMock()
    coordinator.data = {key: value}
    entity = sensor_type(coordinator, DeviceInfo(), "SERIAL-1")
    entity.entity_id = "sensor.wallbox"
    # Unit translation requires a registered platform, unrelated to enum checks.
    entity._attr_translation_key = None
    assert entity.state == expected


@pytest.mark.parametrize("mode", ["current", "power"])
def test_number_availability_follows_control_mode(mode: str) -> None:
    """Keep both entity IDs, but enable commands only for the selected mode."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    client = MagicMock()
    client.control_mode = mode
    current = AmperfieldMaxCurrentNumber(
        coordinator, client, DeviceInfo(), "SERIAL-1", 16
    )
    power = AmperfieldMaxPowerNumber(coordinator, client, DeviceInfo(), "SERIAL-1", 16)
    assert current.available is (mode == "current")
    assert power.available is (mode == "power")
    coordinator.last_update_success = False
    assert not current.available
    assert not power.available
