"""Status and diagnostic sensors for Sony ADCP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .entity import SonyAdcpEntity
from .manager import ProjectorManager, ProjectorState


@dataclass(frozen=True, kw_only=True)
class SonySensorDescription(SensorEntityDescription):
    """Describe a projector status sensor."""

    value_fn: Callable[[ProjectorState], str | None]


SENSORS = (
    SonySensorDescription(
        key="power_status",
        translation_key="power_status",
        value_fn=lambda state: state.power_status,
    ),
    SonySensorDescription(
        key="signal",
        translation_key="signal",
        value_fn=lambda state: state.signal,
    ),
    SonySensorDescription(
        key="errors",
        translation_key="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: ", ".join(state.errors) if state.errors else "no_err",
    ),
    SonySensorDescription(
        key="warnings",
        translation_key="warnings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: ", ".join(state.warnings) if state.warnings else "no_warn",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    async_add_entities(
        SonyAdcpSensor(entry, manager, description) for description in SENSORS
    )


class SonyAdcpSensor(SonyAdcpEntity, SensorEntity):
    """A read-only projector status."""

    entity_description: SonySensorDescription

    def __init__(
        self,
        entry: SonyAdcpConfigEntry,
        manager: ProjectorManager,
        description: SonySensorDescription,
    ) -> None:
        super().__init__(entry, manager)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"

    @property
    def native_value(self) -> str | None:
        return self.entity_description.value_fn(self._manager.state)
