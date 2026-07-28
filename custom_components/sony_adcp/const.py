"""Constants for the Sony ADCP integration."""

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "sony_adcp"

CONF_DISCOVERED_HOST: Final = "discovered_host"
CONF_OPERATIONAL_REFRESH_INTERVAL: Final = "operational_refresh_interval"
DEFAULT_NAME: Final = "Sony Projector"
DEFAULT_PORT: Final = 53595
DEFAULT_SOURCES: Final = ("hdmi1", "hdmi2")
DEFAULT_OPERATIONAL_REFRESH_INTERVAL: Final = 10
OPERATIONAL_REFRESH_INTERVALS: Final = (0, 5, 10, 30)
ADVERTISEMENT_PORT: Final = 53862
COMMAND_TIMEOUT: Final = 5.0
DISCOVERY_TIMEOUT: Final = 35.0

PLATFORMS: Final = [
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

POWER_OFF_STATES: Final = frozenset({"standby", "saving_standby"})
# The common Sony manual defines a two-byte SDAP field but not its enumeration.
# These values are intentionally not guessed. ADCP confirms the detailed state.
SDAP_COMMUNICATION_ERROR: Final = 0xFFFF
SDAP_POWER_STATES: Final = {
    0x0000: "standby",
    0x0001: "startup",
    0x0002: "startup",
    0x0003: "on",
    0x0004: "cooling1",
    0x0005: "cooling2",
}

SELECT_COMMANDS: Final = {
    "picture_mode": "Picture mode",
}

DEFAULT_PICTURE_MODES: Final = (
    "cinema_film1",
    "cinema_film2",
    "reference",
    "tv",
    "photo",
    "game",
    "brt_cinema",
    "brt_tv",
    "user",
    "user1",
    "user2",
    "user3",
)

SWITCH_COMMANDS: Final = {
    "blank": "Video mute",
}

NUMBER_COMMANDS: Final = {
    "brightness": "Brightness",
    "contrast": "Contrast",
    "sharpness": "Sharpness",
    "light_output_val": "Light output",
    "real_cre_reso": "Reality Creation resolution",
    "real_cre_noise": "Reality Creation noise filtering",
}
