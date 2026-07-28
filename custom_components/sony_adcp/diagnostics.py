"""Diagnostics support for Sony ADCP."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import SonyAdcpConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SonyAdcpConfigEntry
) -> dict[str, Any]:
    """Return non-sensitive diagnostics for a config entry."""
    manager = entry.runtime_data.manager
    return {
        "config": async_redact_data(dict(entry.data), {CONF_PASSWORD}),
        "identity": {
            "model": manager.identity.model,
            "serial": manager.identity.serial,
            "mac_address": manager.identity.mac_address,
        },
        "state": {
            "power_status": manager.state.power_status,
            "source": manager.state.source,
            "signal": manager.state.signal,
            "errors": manager.state.errors,
            "warnings": manager.state.warnings,
            "available": manager.state.available,
        },
        "capabilities": {
            command: {
                "type": info.command_type,
                "choices": info.choices,
                "minimum": info.minimum,
                "maximum": info.maximum,
            }
            for command, info in manager.command_info.items()
        },
    }
