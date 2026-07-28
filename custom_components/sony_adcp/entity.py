"""Shared entity base for Sony ADCP."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import SonyAdcpConfigEntry
from .const import DEFAULT_NAME, DOMAIN
from .manager import ProjectorManager


class SonyAdcpEntity(Entity):
    """Base entity backed by the push manager."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: SonyAdcpConfigEntry, manager: ProjectorManager) -> None:
        self._entry = entry
        self._manager = manager
        identity = manager.identity
        identifier = (
            entry.unique_id
            or identity.serial
            or identity.mac_address
            or entry.data[CONF_HOST]
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer="Sony",
            model=identity.model,
            serial_number=identity.serial,
            connections=(
                {(CONNECTION_NETWORK_MAC, identity.mac_address)}
                if identity.mac_address
                else set()
            ),
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        return self._manager.state.available
