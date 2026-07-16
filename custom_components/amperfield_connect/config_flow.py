"""Config flow for Amperfield Wallbox Connect integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .modbus_client import AmperfieldModbusClient, AmperfieldModbusError

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SELECTOR = vol.All(vol.Coerce(int), vol.Range(min=5, max=86400))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): SCAN_INTERVAL_SELECTOR,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Raises CannotConnect if connection or basic communication fails.
    Any other exception propagates as-is to be caught as 'unknown' by the flow.
    """
    _LOGGER.debug("Validating connection to %s:%s", data[CONF_HOST], data[CONF_PORT])
    client = AmperfieldModbusClient(data[CONF_HOST], data[CONF_PORT])

    try:
        if not await client.connect(start_heartbeat=False):
            _LOGGER.debug(
                "Connection test failed for %s:%s", data[CONF_HOST], data[CONF_PORT]
            )
            raise CannotConnect

        # Verify communication by reading the Modbus version register
        _LOGGER.debug("Reading Modbus version to verify communication")
        version = await client.get_modbus_version()
        if version is None:
            _LOGGER.debug("Failed to read Modbus version")
            raise CannotConnect
        _LOGGER.debug("Modbus version: %s", version)

        serial_number = await client.get_serial_number()
        if not serial_number:
            _LOGGER.debug("Wallbox did not return a serial number")
            raise CannotConnect
        _LOGGER.debug("Serial number: %s", serial_number)
    except AmperfieldModbusError as err:
        raise CannotConnect from err
    finally:
        await client.close()

    _LOGGER.info("Successfully validated connection to wallbox %s", serial_number)
    return {
        "title": f"Amperfield Wallbox {serial_number}",
        "unique_id": serial_number,
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amperfield Wallbox Connect."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AmperfieldOptionsFlow:
        """Return the options flow handler."""
        return AmperfieldOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        _LOGGER.debug("Starting reconfigure flow")
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
                            CONF_PORT,
                            default=reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT),
                        ): int,
                        vol.Optional(
                            CONF_SCAN_INTERVAL,
                            default=reconfigure_entry.data.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            ),
                        ): SCAN_INTERVAL_SELECTOR,
                    }
                ),
            )

        errors = {}

        runtime_client = getattr(
            getattr(reconfigure_entry, "runtime_data", None), "client", None
        )
        if runtime_client is not None:
            _LOGGER.debug("Suspending existing connection for reconfigure validation")
            await runtime_client.suspend()

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception during reconfigure")
            errors["base"] = "unknown"
        finally:
            if runtime_client is not None:
                restored = await runtime_client.resume()
                if not restored:
                    _LOGGER.warning(
                        "Could not immediately restore the existing connection"
                    )

        if not errors:
            await self.async_set_unique_id(info["unique_id"])
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates=user_input,
                options={
                    **reconfigure_entry.options,
                    CONF_SCAN_INTERVAL: user_input.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST)): str,
                    vol.Required(
                        CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)
                    ): int,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): SCAN_INTERVAL_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        _LOGGER.debug("Starting user config flow")
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
            _LOGGER.exception("Unexpected exception during config flow")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(info["unique_id"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class AmperfieldOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Amperfield Wallbox Connect."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_scan_interval
                    ): SCAN_INTERVAL_SELECTOR,
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
