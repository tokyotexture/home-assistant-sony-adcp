"""Dynamically ranged numeric controls for Sony ADCP."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .const import NUMBER_COMMANDS
from .entity import SonyAdcpEntity
from .manager import ProjectorManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    known: set[str] = set()

    def add_supported_entities() -> None:
        new_commands = [
            command
            for command in NUMBER_COMMANDS
            if command not in known
            and (info := manager.command_info.get(command)) is not None
            and info.minimum is not None
            and info.maximum is not None
        ]
        if not new_commands:
            return
        known.update(new_commands)
        async_add_entities(
            SonyAdcpNumber(entry, manager, command) for command in new_commands
        )

    add_supported_entities()
    entry.async_on_unload(manager.async_add_listener(add_supported_entities))


class SonyAdcpNumber(SonyAdcpEntity, NumberEntity):
    """A projector menu_num command using its reported range."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: SonyAdcpConfigEntry,
        manager: ProjectorManager,
        command: str,
    ) -> None:
        super().__init__(entry, manager)
        info = manager.command_info[command]
        self._command = command
        self._attr_translation_key = command
        self._attr_unique_id = f"{entry.unique_id}_{command}"
        self._attr_native_min_value = info.minimum or 0
        self._attr_native_max_value = info.maximum or 100
        self._attr_native_step = 1

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._manager.async_read_command(self._command)

    @property
    def native_value(self) -> float | None:
        value = self._manager.state.values.get(self._command)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._manager.async_set_number(self._command, value)
