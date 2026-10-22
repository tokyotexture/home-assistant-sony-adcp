"""Move beta 1 sensors safely onto the parent projector configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .custom_commands import CONF_CUSTOM_SENSORS, CUSTOM_SENSOR, validate_sensor_config

if TYPE_CHECKING:
    from . import SonyAdcpConfigEntry


@callback
def async_migrate_beta1_sensors(hass: HomeAssistant, entry: SonyAdcpConfigEntry) -> None:
    """Save settings and detach registry ownership BEFORE removing subentries.

    Removing an owning subentry first can delete the projector and its entities.
    Reparent entities before devices: a device move also removes entities still
    owned by the old subentry. All operations here are synchronous callbacks.
    """
    legacy = {
        key: subentry
        for key, subentry in entry.subentries.items()
        if subentry.subentry_type == CUSTOM_SENSOR
    }
    if not legacy:
        return
    sensors = [dict(sensor) for sensor in entry.options.get(CONF_CUSTOM_SENSORS, [])]
    known = {sensor["id"] for sensor in sensors}
    for key, subentry in legacy.items():
        if key not in known:
            sensors.append(
                {
                    "id": key,
                    **validate_sensor_config({**subentry.data, "name": subentry.title}),
                }
            )
    # Persist a recoverable copy before touching any registry or subentry.
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_CUSTOM_SENSORS: sensors},
    )
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.config_subentry_id in legacy:
            entity_registry.async_update_entity(
                entity.entity_id,
                config_entry_id=entry.entry_id,
                config_subentry_id=None,
            )
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if hasattr(device, "config_subentry_id"):
            # HA's single-owner device registry.
            if device.config_subentry_id in legacy:
                device_registry.async_update_device(device.id, new_config_subentry_id=None)
        else:
            # HA 2026.3's registry can associate one device with multiple subentries.
            attached = device.config_entries_subentries.get(entry.entry_id, set())
            if affected := set(legacy).intersection(attached):
                device_registry.async_update_device(
                    device.id,
                    add_config_entry_id=entry.entry_id,
                    add_config_subentry_id=None,
                )
                for key in affected:
                    device_registry.async_update_device(
                        device.id,
                        remove_config_entry_id=entry.entry_id,
                        remove_config_subentry_id=key,
                    )
    for key in legacy:
        hass.config_entries.async_remove_subentry(entry, key)


@callback
def async_remove_deleted_custom_sensors(hass: HomeAssistant, entry: SonyAdcpConfigEntry) -> None:
    """Remove only deleted custom sensor registrations, never projector controls."""
    prefix = f"{entry.unique_id}_custom_"
    wanted = {f"{prefix}{sensor['id']}" for sensor in entry.options.get(CONF_CUSTOM_SENSORS, [])}
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.platform == DOMAIN
            and entity.domain == "sensor"
            and entity.unique_id.startswith(prefix)
            and entity.unique_id not in wanted
        ):
            registry.async_remove(entity.entity_id)
