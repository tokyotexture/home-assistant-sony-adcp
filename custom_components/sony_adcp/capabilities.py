"""Persist proven built-in capabilities, never cached operational values."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from .const import NUMBER_COMMANDS, SELECT_COMMANDS, SWITCH_COMMANDS
from .discovery import normalize_serial
from .protocol import CommandInfo, ProjectorIdentity, normalize_mac

CONF_CAPABILITIES = "capabilities"
CAPABILITY_COMMANDS = ("input", *SELECT_COMMANDS, *SWITCH_COMMANDS, *NUMBER_COMMANDS)


def encode_capabilities(
    identity: ProjectorIdentity, commands: dict[str, CommandInfo]
) -> dict[str, Any]:
    """Return JSON-safe, entry-scoped metadata for already supported commands."""
    return {
        "version": 1,
        "identity": {
            "model": identity.model,
            "serial": identity.serial,
            "mac_address": identity.mac_address,
        },
        "commands": {
            command: {**asdict(info), "choices": list(info.choices)}
            for command, info in commands.items() if command in CAPABILITY_COMMANDS
        },
    }


def decode_capabilities(payload: Any, identity: ProjectorIdentity) -> dict[str, CommandInfo]:
    """Reject corrupt metadata or a known different projector; never invent ranges."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return {}
    previous = payload.get("identity")
    commands = payload.get("commands")
    if not isinstance(previous, dict) or not isinstance(commands, dict):
        return {}
    for key, normalize in (
        ("model", lambda value: value.strip().casefold()),
        ("serial", normalize_serial),
        ("mac_address", normalize_mac),
    ):
        cached, current = previous.get(key), getattr(identity, key)
        if cached is not None and not isinstance(cached, str):
            return {}
        if cached and current and normalize(cached) != normalize(current):
            return {}
    result = {}
    for command in CAPABILITY_COMMANDS:
        info = commands.get(command)
        if not isinstance(info, dict) or info.get("command") != command:
            continue
        kind, choices = info.get("command_type"), info.get("choices")
        if kind not in {"menu_num", "menu_val", "menu_sel", "sys_sel"}:
            continue
        if not isinstance(choices, list) or not all(isinstance(x, str) for x in choices):
            continue
        bounds = [info.get(key) for key in ("minimum", "maximum", "step")]
        if any(value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float)
            or not math.isfinite(value)
        ) for value in bounds):
            continue
        minimum, maximum, step = bounds
        if (minimum is not None and maximum is not None and minimum > maximum) or (
            step is not None and step <= 0
        ):
            continue
        if command in NUMBER_COMMANDS and (
            kind not in {"menu_num", "menu_val"} or minimum is None or maximum is None
        ):
            continue
        result[command] = CommandInfo(command, kind, tuple(choices), minimum, maximum, step)
    return result
