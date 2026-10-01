"""Config-flow identity tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT

from custom_components.amperfield_connect import config_flow
from custom_components.amperfield_connect.modbus_client import (
    AmperfieldConnectionError,
)


@pytest.mark.asyncio
async def test_validate_input_requires_hardware_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutable host must never become the config-entry unique ID."""
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.get_modbus_version = AsyncMock(return_value=1)
    client.get_serial_number = AsyncMock(return_value=None)
    client.close = AsyncMock()
    monkeypatch.setattr(config_flow, "AmperfieldModbusClient", lambda *_: client)

    with pytest.raises(config_flow.CannotConnect):
        await config_flow.validate_input(
            MagicMock(), {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
        )
    client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_validate_input_uses_serial_as_unique_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hardware serial should identify both flow and entities."""
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.get_modbus_version = AsyncMock(return_value=1)
    client.get_serial_number = AsyncMock(return_value="SERIAL-1")
    client.close = AsyncMock()
    monkeypatch.setattr(config_flow, "AmperfieldModbusClient", lambda *_: client)

    result = await config_flow.validate_input(
        MagicMock(), {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
    )

    assert result["unique_id"] == "SERIAL-1"
    client.connect.assert_awaited_once_with(start_heartbeat=False)


@pytest.mark.asyncio
async def test_validate_input_maps_modbus_failure_to_cannot_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport errors should use the actionable cannot-connect flow error."""
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.get_modbus_version = AsyncMock(
        side_effect=AmperfieldConnectionError("offline")
    )
    client.close = AsyncMock()
    monkeypatch.setattr(config_flow, "AmperfieldModbusClient", lambda *_: client)

    with pytest.raises(config_flow.CannotConnect):
        await config_flow.validate_input(
            MagicMock(), {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
        )
    client.close.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("host", "port"),
    [
        ("http://wallbox.local", 502),
        ("wallbox.local\nforged", 502),
        ("wallbox.local", 0),
        ("wallbox.local", 65536),
    ],
)
def test_config_schema_rejects_unsafe_endpoints(host: str, port: int) -> None:
    """Malformed network targets must be rejected before connection attempts."""
    with pytest.raises(vol.Invalid):
        config_flow.STEP_USER_DATA_SCHEMA({CONF_HOST: host, CONF_PORT: port})


@pytest.mark.asyncio
async def test_validate_input_rejects_malformed_device_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untrusted device identity must not flow into logs or entity identifiers."""
    client = MagicMock()
    client.connect = AsyncMock(return_value=True)
    client.get_modbus_version = AsyncMock(return_value=1)
    client.get_serial_number = AsyncMock(
        return_value="SERIAL\N{REPLACEMENT CHARACTER}FORGED"
    )
    client.close = AsyncMock()
    monkeypatch.setattr(config_flow, "AmperfieldModbusClient", lambda *_: client)

    with pytest.raises(config_flow.CannotConnect):
        await config_flow.validate_input(
            MagicMock(), {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
        )


@pytest.mark.asyncio
async def test_failed_reconfigure_restores_runtime_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected endpoint must not leave the existing integration suspended."""
    runtime_client = MagicMock()
    runtime_client.suspend = AsyncMock()
    runtime_client.resume = AsyncMock(return_value=True)
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
    entry.options = {}
    entry.runtime_data.client = runtime_client

    flow = MagicMock()
    flow.hass = MagicMock()
    flow._get_reconfigure_entry.return_value = entry
    flow.async_show_form.return_value = {"type": "form"}
    monkeypatch.setattr(
        config_flow,
        "validate_input",
        AsyncMock(side_effect=config_flow.CannotConnect),
    )

    result = await config_flow.ConfigFlow.async_step_reconfigure(
        flow, {CONF_HOST: "192.0.2.20", CONF_PORT: 502}
    )

    assert result == {"type": "form"}
    runtime_client.suspend.assert_awaited_once_with()
    runtime_client.resume.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_successful_reconfigure_verifies_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconfigure must reject changing the entry to another physical device."""
    runtime_client = MagicMock()
    runtime_client.suspend = AsyncMock()
    runtime_client.resume = AsyncMock(return_value=True)
    entry = MagicMock()
    entry.data = {CONF_HOST: "192.0.2.10", CONF_PORT: 502}
    entry.options = {}
    entry.runtime_data.client = runtime_client

    flow = MagicMock()
    flow.hass = MagicMock()
    flow._get_reconfigure_entry.return_value = entry
    flow.async_set_unique_id = AsyncMock()
    flow.async_update_reload_and_abort.return_value = {"type": "abort"}
    monkeypatch.setattr(
        config_flow,
        "validate_input",
        AsyncMock(return_value={"unique_id": "SERIAL-1", "title": "Wallbox"}),
    )

    result = await config_flow.ConfigFlow.async_step_reconfigure(
        flow, {CONF_HOST: "192.0.2.20", CONF_PORT: 502}
    )

    assert result == {"type": "abort"}
    flow.async_set_unique_id.assert_awaited_once_with("SERIAL-1")
    flow._abort_if_unique_id_mismatch.assert_called_once_with()
    runtime_client.resume.assert_awaited_once_with()
