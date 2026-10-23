"""Status and diagnostic sensors for Sony ADCP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .custom_commands import CONF_CUSTOM_SENSORS, parse_sensor_value
from .entity import SonyAdcpEntity
from .manager import ProjectorManager, ProjectorState


@dataclass(frozen=True, kw_only=True)
class SonySensorDescription(SensorEntityDescription):
    """Describe a projector status sensor."""

    value_fn: Callable[[ProjectorState], str | int | None]


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

TIMER_SENSORS = tuple(
    SonySensorDescription(
        key=f"timer_{command}",
        translation_key=f"timer_{command}",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        value_fn=lambda state, key=command: state.timer_hours.get(key),
    )
    for command in ("operation", "light_src")
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data.manager
    # A shared physical device must keep one owner, not move between subentries.
    async_add_entities(
        [
            SonyAdcpCustomSensor(entry, manager, config)
            for config in entry.options.get(CONF_CUSTOM_SENSORS, [])
        ],
        config_subentry_id=None,
    )
    async_add_entities(SonyAdcpSensor(entry, manager, description) for description in SENSORS)
    known: set[str] = set()

    @callback
    def add_timer_sensors() -> None:
        new_sensors = [
            description
            for description in TIMER_SENSORS
            if description.key not in known and description.value_fn(manager.state) is not None
        ]
        if not new_sensors:
            return
        known.update(description.key for description in new_sensors)
        async_add_entities(
            SonyAdcpSensor(entry, manager, description) for description in new_sensors
        )

    add_timer_sensors()
    entry.async_on_unload(manager.async_add_listener(add_timer_sensors))


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
    def native_value(self) -> str | int | None:
        return self.entity_description.value_fn(self._manager.state)


class SonyAdcpCustomSensor(SonyAdcpEntity, SensorEntity):
    """A user-named sensor from a shared, read-only ADCP query."""

    def __init__(
        self, entry: SonyAdcpConfigEntry, manager: ProjectorManager, config: dict[str, str]
    ) -> None:
        super().__init__(entry, manager)
        self._config = config
        self._command = self._config["command"]
        self._attr_name = config["name"]
        self._attr_unique_id = f"{entry.unique_id}_custom_{config['id']}"
        self._attr_native_unit_of_measurement = self._config.get("unit") or None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_track_custom_command(self._command))

    @property
    def native_value(self) -> str | int | float | None:
        result = self._manager.custom_results.get(self._command)
        if result is None or result.response is None or result.error:
            return None
        try:
            return parse_sensor_value(result.response, self._config)
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._manager.state.power_status == "on"
            and self._manager.power_transition_target is None
            and self.native_value is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        result = self._manager.custom_results.get(self._command)
        error = result.error if result else "not_yet_refreshed"
        if result and result.response is not None and self.native_value is None:
            error = "invalid_response"
        return {
            "adcp_command": f"{self._command} ?",
            "json_field": self._config.get("json_field") or None,
            "last_error": error,
        }
