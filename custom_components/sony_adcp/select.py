"""Capability-aware select entities for Sony ADCP."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .const import DEFAULT_PICTURE_MODES, SELECT_COMMANDS
from .entity import SonyAdcpEntity
from .manager import ProjectorManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    async_add_entities(
        SonyAdcpSelect(entry, manager, command) for command in SELECT_COMMANDS
    )


class SonyAdcpSelect(SonyAdcpEntity, SelectEntity):
    """A projector menu_sel command."""

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
    def current_option(self) -> str | None:
        value = self._manager.state.values.get(self._command)
        return str(value) if value is not None else None

    @property
    def available(self) -> bool:
        return super().available and (
            self._command in self._manager.command_info
            or self._command in self._manager.state.values
        )

    @property
    def options(self) -> list[str]:
        info = self._manager.command_info.get(self._command)
        if info and info.choices:
            return list(info.choices)
        if self._command == "picture_mode":
            return list(DEFAULT_PICTURE_MODES)
        return []

    async def async_select_option(self, option: str) -> None:
        await self._manager.async_set_select(self._command, option)
