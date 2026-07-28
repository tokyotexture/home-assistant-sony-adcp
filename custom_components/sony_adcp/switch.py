"""Display switches for Sony ADCP."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .const import SWITCH_COMMANDS
from .entity import SonyAdcpEntity
from .manager import ProjectorManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    async_add_entities(
        SonyAdcpSwitch(entry, manager, command) for command in SWITCH_COMMANDS
    )


class SonyAdcpSwitch(SonyAdcpEntity, SwitchEntity):
    """A projector on/off menu command, such as video muting."""

    def __init__(
        self,
        entry: SonyAdcpConfigEntry,
        manager: ProjectorManager,
        command: str,
    ) -> None:
        super().__init__(entry, manager)
        self._command = command
        self._attr_translation_key = command
        self._attr_unique_id = f"{entry.unique_id}_{command}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._manager.async_read_command(self._command)

    @property
    def is_on(self) -> bool | None:
        value = self._manager.state.values.get(self._command)
        return str(value).lower() == "on" if value is not None else None

    @property
    def available(self) -> bool:
        return super().available and (
            self._command in self._manager.command_info
            or self._command in self._manager.state.values
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._manager.async_set_switch(self._command, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._manager.async_set_switch(self._command, False)
