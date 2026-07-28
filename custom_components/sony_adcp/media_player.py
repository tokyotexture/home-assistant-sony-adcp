"""Display-oriented media player for Sony ADCP projectors."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SonyAdcpConfigEntry
from .const import POWER_OFF_STATES
from .entity import SonyAdcpEntity
from .manager import ProjectorManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SonyAdcpConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SonyAdcpProjector(entry, entry.runtime_data.manager)])


class SonyAdcpProjector(SonyAdcpEntity, MediaPlayerEntity):
    """Projector power and input selection."""

    _attr_device_class = MediaPlayerDeviceClass.PROJECTOR
    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(
        self, entry: SonyAdcpConfigEntry, manager: ProjectorManager
    ) -> None:
        super().__init__(entry, manager)
        self._attr_unique_id = f"{entry.unique_id}_projector"

    @property
    def state(self) -> MediaPlayerState:
        if self._manager.state.power_status in POWER_OFF_STATES:
            return MediaPlayerState.OFF
        return MediaPlayerState.ON

    @property
    def source(self) -> str | None:
        return _source_label(self._manager.state.source)

    @property
    def source_list(self) -> list[str]:
        return [
            label
            for source in self._manager.sources
            if (label := _source_label(source)) is not None
        ]

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {
            "sony_power_status": self._manager.state.power_status,
            "signal": self._manager.state.signal,
        }

    async def async_turn_on(self) -> None:
        await self._manager.async_turn_on()

    async def async_turn_off(self) -> None:
        await self._manager.async_turn_off()

    async def async_select_source(self, source: str) -> None:
        source_map = {
            _source_label(value): value for value in self._manager.sources
        }
        await self._manager.async_select_source(source_map[source])


def _source_label(source: str | None) -> str | None:
    if source is None:
        return None
    normalized = source.lower()
    for prefix, label in {
        "hdmi": "HDMI",
        "hdbaset": "HDBaseT",
        "rgb": "RGB",
        "dvi": "DVI",
        "usb": "USB",
    }.items():
        if normalized.startswith(prefix):
            suffix = normalized[len(prefix) :].strip("_")
            return f"{label} {suffix}".strip()
    return normalized.replace("_", " ").title()
