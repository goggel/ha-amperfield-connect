"""Config-flow identity tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL

from custom_components.amperfield_connect import config_flow
from custom_components.amperfield_connect.const import CONF_CONTROL_MODE
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
async def test_reconfigure_default_uses_active_options_interval() -> None:
    """Host edits must start from the effective polling interval."""
    flow = MagicMock()
    entry = flow._get_reconfigure_entry.return_value
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502, CONF_SCAN_INTERVAL: 30}
    entry.options = {CONF_SCAN_INTERVAL: 60}
    await config_flow.ConfigFlow.async_step_reconfigure(flow)
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    assert (
        schema({CONF_HOST: "wallbox.local", CONF_PORT: 502})[CONF_SCAN_INTERVAL] == 60
    )


@pytest.mark.asyncio
async def test_reconfigure_without_interval_preserves_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct host submissions preserve interval and unrelated options."""
    flow = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    entry = flow._get_reconfigure_entry.return_value
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502, CONF_SCAN_INTERVAL: 30}
    entry.options = {CONF_SCAN_INTERVAL: 60, CONF_CONTROL_MODE: "power"}
    entry.runtime_data = None
    monkeypatch.setattr(
        config_flow, "validate_input", AsyncMock(return_value={"unique_id": "SERIAL-1"})
    )
    await config_flow.ConfigFlow.async_step_reconfigure(
        flow, {CONF_HOST: "new-wallbox.local", CONF_PORT: 502}
    )
    options = flow.async_update_reload_and_abort.call_args.kwargs["options"]
    assert options == {CONF_SCAN_INTERVAL: 60, CONF_CONTROL_MODE: "power"}


@pytest.mark.asyncio
async def test_reconfigure_does_not_resume_replaced_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reload during validation transfers ownership to a different client."""
    flow = MagicMock()
    entry = flow._get_reconfigure_entry.return_value
    entry.data = {CONF_HOST: "wallbox.local", CONF_PORT: 502}
    entry.options = {}
    old_client = MagicMock()
    old_client.suspend = AsyncMock()
    old_client.resume = AsyncMock()
    entry.runtime_data.client = old_client

    async def validate(*_):
        entry.runtime_data.client = MagicMock()
        raise config_flow.CannotConnect

    monkeypatch.setattr(config_flow, "validate_input", validate)
    await config_flow.ConfigFlow.async_step_reconfigure(
        flow, {CONF_HOST: "wallbox.local", CONF_PORT: 502}
    )
    old_client.suspend.assert_awaited_once_with()
    old_client.resume.assert_not_awaited()


@pytest.mark.parametrize("solar", [False, True])
@pytest.mark.asyncio
async def test_options_offer_control_mode_only_for_solar(solar: bool) -> None:
    """Solar models default to power control and can select current control."""
    flow = MagicMock()
    entry = flow.config_entry
    entry.data = {}
    entry.options = {}
    entry.runtime_data.supports_phase_switching = solar
    await config_flow.AmperfieldOptionsFlow.async_step_init(flow)
    schema = flow.async_show_form.call_args.kwargs["data_schema"]
    data = schema({})
    if solar:
        assert data[CONF_CONTROL_MODE] == "power"
        assert schema({CONF_CONTROL_MODE: "current"})[CONF_CONTROL_MODE] == "current"
        with pytest.raises(vol.Invalid):
            schema({CONF_CONTROL_MODE: "invalid"})
    else:
        assert CONF_CONTROL_MODE not in data


@pytest.mark.asyncio
async def test_options_interval_edit_preserves_control_mode() -> None:
    """Options submissions must retain any fields not present in the form."""
    flow = MagicMock()
    flow.config_entry.options = {CONF_CONTROL_MODE: "power", CONF_SCAN_INTERVAL: 30}
    await config_flow.AmperfieldOptionsFlow.async_step_init(
        flow, {CONF_SCAN_INTERVAL: 60}
    )
    flow.async_create_entry.assert_called_once_with(
        title="", data={CONF_CONTROL_MODE: "power", CONF_SCAN_INTERVAL: 60}
    )


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
