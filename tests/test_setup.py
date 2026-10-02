"""Integration setup ownership and cleanup tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import ConfigEntryError

from custom_components import amperfield_connect as integration


@pytest.mark.parametrize(
    "stage", ["connect", "identity", "capability", "first_refresh", "platforms"]
)
@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.asyncio
async def test_aborted_setup_always_closes_client(
    monkeypatch: pytest.MonkeyPatch, stage: str, cancelled: bool
) -> None:
    """Every setup stage must release its client, including on cancellation."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.unique_id = "SERIAL-1"
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502}
    entry.options = {}
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.fetch_device_info = AsyncMock(
        return_value={"serial_number": "SERIAL-1", "item_number": "unknown-model"}
    )
    client.probe_phase_switching = AsyncMock(return_value=False)
    client.close = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    stages = {
        "connect": client.connect,
        "identity": client.fetch_device_info,
        "capability": client.probe_phase_switching,
        "first_refresh": coordinator.async_config_entry_first_refresh,
        "platforms": hass.config_entries.async_forward_entry_setups,
    }
    error = asyncio.CancelledError() if cancelled else RuntimeError("failed setup")
    stages[stage].side_effect = error
    monkeypatch.setattr(integration, "AmperfieldModbusClient", lambda *_: client)
    monkeypatch.setattr(
        integration, "AmperfieldDataUpdateCoordinator", lambda *_: coordinator
    )

    expected = asyncio.CancelledError if cancelled else Exception
    with pytest.raises(expected):
        await integration.async_setup_entry(hass, entry)
    client.close.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("solar", "options", "expected_mode"),
    [
        (False, {"control_mode": "power"}, "current"),
        (True, {}, "power"),
        (True, {"control_mode": "power"}, "power"),
        (True, {"control_mode": "current"}, "current"),
    ],
)
@pytest.mark.asyncio
async def test_successful_setup_applies_control_mode_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    solar: bool,
    options: dict[str, str],
    expected_mode: str,
) -> None:
    """Setup selects the policy without changing the wallbox's charge commands."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.unique_id = "SERIAL-1"
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502}
    entry.options = options
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.fetch_device_info = AsyncMock(
        return_value={"serial_number": "SERIAL-1", "item_number": "unknown-model"}
    )
    client.probe_phase_switching = AsyncMock(return_value=solar)
    client.close = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    monkeypatch.setattr(integration, "AmperfieldModbusClient", lambda *_: client)
    monkeypatch.setattr(
        integration, "AmperfieldDataUpdateCoordinator", lambda *_: coordinator
    )
    assert await integration.async_setup_entry(hass, entry)
    assert client.control_mode == expected_mode
    assert entry.runtime_data.client is client
    client.close.assert_not_awaited()
    client.set_max_current.assert_not_called()
    client.set_max_power_target.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_identity_keeps_permanent_setup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity failures must close the transport without becoming retry errors."""
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.fetch_device_info = AsyncMock(return_value={"serial_number": None})
    client.close = AsyncMock()
    monkeypatch.setattr(integration, "AmperfieldModbusClient", lambda *_: client)
    entry = MagicMock()
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502}
    with pytest.raises(ConfigEntryError, match="hardware serial"):
        await integration.async_setup_entry(MagicMock(), entry)
    client.close.assert_awaited_once_with()
