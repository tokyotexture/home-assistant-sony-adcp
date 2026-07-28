"""Config flow for Sony ADCP projectors."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import async_get_listener
from .const import (
    CONF_DISCOVERED_HOST,
    CONF_OPERATIONAL_REFRESH_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_OPERATIONAL_REFRESH_INTERVAL,
    DEFAULT_PORT,
    DISCOVERY_TIMEOUT,
    DOMAIN,
    OPERATIONAL_REFRESH_INTERVALS,
)
from .discovery import DiscoveredProjector
from .protocol import (
    AdcpAuthenticationError,
    AdcpClient,
    AdcpConnectionError,
    AuthenticationMode,
    ProjectorIdentity,
    async_probe_authentication,
)


class SonyAdcpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover and configure a Sony ADCP projector."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the integration options flow."""
        return SonyAdcpOptionsFlow()

    def __init__(self) -> None:
        self._host: str | None = None
        self._port = DEFAULT_PORT
        self._name = DEFAULT_NAME
        self._discovered: dict[str, DiscoveredProjector] = {}
        self._auth_mode: AuthenticationMode | None = None
        self._discovery_task: asyncio.Task[list[DiscoveredProjector]] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start discovery when the flow is opened by the user."""
        return await self.async_step_discovery()

    async def async_step_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show cancellable progress while waiting for an SDAP interval."""
        if self._discovery_task is not None and self._discovery_task.done():
            devices = self._discovery_task.result()
            self._discovery_task = None
            self._discovered = {device.host: device for device in devices}
            return self.async_show_progress_done(next_step_id="select")

        if self._discovery_task is None:
            listener = await async_get_listener(self.hass)
            self._discovery_task = self.hass.async_create_task(
                listener.async_wait_for_devices(DISCOVERY_TIMEOUT),
                "Discover Sony SDAP projectors",
            )

        return self.async_show_progress(
            step_id="discovery",
            progress_action="discovering",
            progress_task=self._discovery_task,
            description_placeholders={"seconds": str(int(DISCOVERY_TIMEOUT))},
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a discovered projector or use manual setup."""
        if user_input is not None:
            selected = user_input[CONF_DISCOVERED_HOST]
            if selected == "manual":
                return await self.async_step_manual()
            device = self._discovered[selected]
            self._host = device.host
            self._name = device.model or DEFAULT_NAME
            await self.async_set_unique_id(device.unique_id)
            self._abort_if_unique_id_configured(updates={CONF_HOST: device.host})
            return await self._async_route_authentication()

        choices = {
            device.host: f"{device.model or 'Sony projector'} ({device.host})"
            for device in self._discovered.values()
        }
        choices["manual"] = "Enter address manually"
        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {vol.Required(CONF_DISCOVERED_HOST): vol.In(choices)}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a projector not received over SDAP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input[CONF_PORT]
            self._name = user_input[CONF_NAME]
            try:
                return await self._async_route_authentication()
            except AdcpConnectionError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): cv.string,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                }
            ),
            errors=errors,
        )

    async def _async_route_authentication(self) -> ConfigFlowResult:
        assert self._host is not None
        self._auth_mode = await async_probe_authentication(self._host, self._port)
        if self._auth_mode is AuthenticationMode.PASSWORD:
            return await self.async_step_auth()
        return await self._async_finish(password=None)

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request a password only when the projector sends a challenge."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                return await self._async_finish(user_input[CONF_PASSWORD])
            except AdcpAuthenticationError:
                errors["base"] = "invalid_auth"
            except AdcpConnectionError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            errors=errors,
            description_placeholders={"host": self._host or ""},
        )

    async def _async_finish(self, password: str | None) -> ConfigFlowResult:
        assert self._host is not None
        identity = await _async_validate(self._host, self._port, password)
        unique_id = identity.serial or identity.mac_address
        discovered = self._discovered.get(self._host)
        unique_id = unique_id or (discovered.unique_id if discovered else self._host)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        return self.async_create_entry(
            title=identity.model or self._name,
            data={
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_NAME: self._name,
                CONF_PASSWORD: password,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the projector rejects credentials."""
        entry = self._get_reauth_entry()
        self._host = entry.data[CONF_HOST]
        self._port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self._name = entry.data.get(CONF_NAME, entry.title)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                identity = await _async_validate(
                    self._host or "",
                    self._port,
                    user_input[CONF_PASSWORD],
                )
            except AdcpAuthenticationError:
                errors["base"] = "invalid_auth"
            except AdcpConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    identity.serial or identity.mac_address or self._host
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host or port while verifying device identity."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                identity = await _async_validate(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    entry.data.get(CONF_PASSWORD),
                )
            except AdcpAuthenticationError:
                errors["base"] = "invalid_auth"
            except AdcpConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    identity.serial or identity.mac_address or user_input[CONF_HOST]
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_NAME: user_input[CONF_NAME],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data[CONF_HOST]
                    ): cv.string,
                    vol.Optional(
                        CONF_PORT,
                        default=entry.data.get(CONF_PORT, DEFAULT_PORT),
                    ): cv.port,
                    vol.Optional(
                        CONF_NAME,
                        default=entry.data.get(CONF_NAME, entry.title),
                    ): cv.string,
                }
            ),
            errors=errors,
        )


class SonyAdcpOptionsFlow(OptionsFlow):
    """Configure runtime behavior for a Sony projector."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure refreshes for automation-relevant operational state."""
        if user_input is not None:
            interval = int(user_input[CONF_OPERATIONAL_REFRESH_INTERVAL])
            if self.config_entry.state is ConfigEntryState.LOADED:
                self.config_entry.runtime_data.manager.async_set_operational_refresh_interval(
                    interval
                )
            return self.async_create_entry(
                title="",
                data={CONF_OPERATIONAL_REFRESH_INTERVAL: interval},
            )

        current = int(
            self.config_entry.options.get(
                CONF_OPERATIONAL_REFRESH_INTERVAL,
                DEFAULT_OPERATIONAL_REFRESH_INTERVAL,
            )
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OPERATIONAL_REFRESH_INTERVAL,
                        default=str(current),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                str(value) for value in OPERATIONAL_REFRESH_INTERVALS
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="operational_refresh_interval",
                        )
                    )
                }
            ),
        )


async def _async_validate(
    host: str, port: int, password: str | None
) -> ProjectorIdentity:
    client = AdcpClient(host, port, password)
    try:
        identity = await client.async_get_identity()
        await client.async_get_power()
    finally:
        await client.async_close()
    return identity
