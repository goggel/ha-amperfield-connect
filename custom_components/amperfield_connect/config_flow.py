"""Config flow for Amperfield Wallbox Connect integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_NAME_PREFIX,
    DEFAULT_NAME_PREFIX,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .modbus_client import AmperfieldModbusClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_NAME_PREFIX, default=DEFAULT_NAME_PREFIX): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    client = AmperfieldModbusClient(data[CONF_HOST], data[CONF_PORT])

    try:
        if not await hass.async_add_executor_job(client.connect):
            raise CannotConnect

        # Try to read the Modbus version to verify communication
        version = await hass.async_add_executor_job(client.get_modbus_version)
        if version is None:
            raise CannotConnect

        # Get serial number for unique ID
        serial_number = await hass.async_add_executor_job(client.get_serial_number)

        await hass.async_add_executor_job(client.close)

    except Exception as err:
        await hass.async_add_executor_job(client.close)
        raise CannotConnect from err

    # Return info that you want to store in the config entry.
    return {
        "title": f"Amperfield Wallbox {serial_number or data[CONF_HOST]}",
        "unique_id": serial_number or data[CONF_HOST],
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amperfield Wallbox Connect."""

    VERSION = 1

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of an existing entry."""
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_HOST, default=reconfigure_entry.data.get(CONF_HOST)
                        ): str,
                        vol.Required(
                            CONF_PORT, default=reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT)
                        ): int,
                        vol.Optional(
                            CONF_SCAN_INTERVAL,
                            default=reconfigure_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        ): int,
                        vol.Optional(
                            CONF_NAME_PREFIX,
                            default=reconfigure_entry.data.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX),
                        ): str,
                    }
                ),
            )

        errors = {}

        try:
            await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates=user_input,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST)): str,
                    vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): int,
                    vol.Optional(
                        CONF_NAME_PREFIX,
                        default=user_input.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(info["unique_id"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
