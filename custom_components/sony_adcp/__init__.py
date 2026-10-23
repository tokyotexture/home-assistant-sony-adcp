"""Sony ADCP projector integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_OPERATIONAL_REFRESH_INTERVAL,
    CONF_REFRESH_PICTURE_SETTINGS,
    DEFAULT_OPERATIONAL_REFRESH_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_REFRESH_PICTURE_SETTINGS,
    DOMAIN,
    PLATFORMS,
)
from .custom_commands import CONF_CUSTOM_SENSORS
from .discovery import SdapListener
from .manager import ProjectorManager
from .migration import async_migrate_beta1_sensors, async_remove_deleted_custom_sensors
from .protocol import (
    AdcpAuthenticationError,
    AdcpClient,
    AdcpError,
)

_LOGGER = logging.getLogger(__name__)

DATA_LISTENER = "listener"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class SonyAdcpRuntimeData:
    """Runtime resources owned by a config entry."""

    manager: ProjectorManager
    unsubscribe_announcement: Callable[[], None]


type SonyAdcpConfigEntry = ConfigEntry[SonyAdcpRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Initialize the integration namespace and SDAP listener."""
    from .services import async_register_services

    async_register_services(hass)
    await async_get_listener(hass)
    return True


async def async_get_listener(hass: HomeAssistant) -> SdapListener:
    """Return the shared listener, creating it for config flows if needed."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if listener := domain_data.get(DATA_LISTENER):
        return listener
    listener = SdapListener()
    domain_data[DATA_LISTENER] = listener
    try:
        await listener.async_start()
    except OSError:
        _LOGGER.warning(
            "Could not listen for Sony SDAP announcements on UDP port 53862; "
            "automatic discovery and push updates are unavailable"
        )
    return listener


async def async_setup_entry(
    hass: HomeAssistant, entry: SonyAdcpConfigEntry
) -> bool:
    """Set up a Sony projector from a config entry."""
    async_remove_deleted_custom_sensors(hass, entry)
    client = AdcpClient(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_PASSWORD),
    )
    manager = ProjectorManager(
        hass,
        client,
        lambda: entry.async_start_reauth(hass),
        lambda host: _update_host(hass, entry, host),
        int(
            entry.options.get(
                CONF_OPERATIONAL_REFRESH_INTERVAL,
                DEFAULT_OPERATIONAL_REFRESH_INTERVAL,
            )
        ),
        refresh_picture_settings=entry.options.get(
            CONF_REFRESH_PICTURE_SETTINGS, DEFAULT_REFRESH_PICTURE_SETTINGS
        ),
    )
    try:
        await manager.async_initialize()
    except AdcpAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except AdcpError as err:
        raise ConfigEntryNotReady(str(err)) from err

    listener = await async_get_listener(hass)
    unsubscribe = listener.async_subscribe(
        entry.data[CONF_HOST],
        entry.unique_id,
        manager.async_handle_announcement,
    )
    entry.runtime_data = SonyAdcpRuntimeData(manager, unsubscribe)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    sensors = _custom_sensor_snapshot(entry)

    async def async_options_updated(
        hass: HomeAssistant, updated_entry: SonyAdcpConfigEntry
    ) -> None:
        """Reload only custom-sensor changes, not refresh or DHCP updates."""
        nonlocal sensors
        updated = _custom_sensor_snapshot(updated_entry)
        if updated != sensors:
            sensors = updated
            await hass.config_entries.async_reload(updated_entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


def _custom_sensor_snapshot(entry: SonyAdcpConfigEntry) -> list[dict[str, str]]:
    """Copy options so in-place changes cannot mask a required reload."""
    return [dict(sensor) for sensor in entry.options.get(CONF_CUSTOM_SENSORS, [])]


async def async_unload_entry(
    hass: HomeAssistant, entry: SonyAdcpConfigEntry
) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.unsubscribe_announcement()
    await entry.runtime_data.manager.async_close()
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: SonyAdcpConfigEntry
) -> bool:
    """Preserve beta 1 settings, unique IDs and device ownership on upgrade."""
    async_migrate_beta1_sensors(hass, entry)
    hass.config_entries.async_update_entry(entry, version=2, minor_version=2)
    return True


def _update_host(
    hass: HomeAssistant, entry: SonyAdcpConfigEntry, host: str
) -> None:
    """Persist a safely identified DHCP address change without reloading."""
    if host == entry.data[CONF_HOST]:
        return
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_HOST: host},
    )
    registry = dr.async_get(hass)
    if entry.unique_id and (
        device := registry.async_get_device(identifiers={(DOMAIN, entry.unique_id)})
    ):
        registry.async_update_device(
            device.id,
            configuration_url=f"http://{host}",
        )
