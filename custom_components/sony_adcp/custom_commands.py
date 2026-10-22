"""Validation and response conversion for read-only custom ADCP sensors."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CUSTOM_SENSOR = "custom_sensor"
CUSTOM_REFRESH_BUDGET = 2.0
CUSTOM_RETRY_INTERVAL = 60
MAX_CUSTOM_SENSORS = 32
_COMMAND = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_FIELD = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", re.ASCII)


class CustomSensorValidationError(ValueError):
    """A field-specific, translatable configuration error."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(reason)
        self.field = field
        self.reason = reason


def validate_sensor_config(data: Mapping[str, Any]) -> dict[str, str]:
    """Accept a command name, never arguments, queries, or command sequences."""
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 100:
        raise CustomSensorValidationError("name", "invalid_name")
    command = str(data.get("command", ""))
    if _COMMAND.fullmatch(command) is None:
        raise CustomSensorValidationError("command", "invalid_command")
    value_type = data.get("value_type", "text")
    if value_type not in {"text", "number"}:
        raise CustomSensorValidationError("value_type", "invalid_value_type")
    field = str(data.get("json_field", "")).strip()
    if field and (len(field) > 128 or _FIELD.fullmatch(field) is None):
        raise CustomSensorValidationError("json_field", "invalid_json_field")
    unit = str(data.get("unit", "")).strip()
    if len(unit) > 30 or (unit and value_type != "number"):
        raise CustomSensorValidationError("unit", "invalid_unit")
    return {
        "name": name, "command": command, "value_type": value_type,
        "json_field": field, "unit": unit,
    }


def parse_sensor_value(response: str, config: Mapping[str, str]) -> str | int | float:
    """Select an optional JSON path and convert a scalar without evaluating code."""
    value: Any = response
    field = config.get("json_field", "")
    if field:
        try:
            value = json.loads(response)
            for part in field.split("."):
                if isinstance(value, list):
                    if not part.isdecimal():
                        raise ValueError("invalid_response")
                    value = value[int(part)]
                else:
                    value = value[part]
        except (ValueError, TypeError, KeyError, IndexError, RecursionError) as err:
            raise ValueError("invalid_response") from err
    if config["value_type"] == "number":
        if isinstance(value, bool) or not isinstance(value, str | int | float):
            raise ValueError("invalid_response")
        try:
            number = float(value)
        except (ValueError, OverflowError) as err:
            raise ValueError("invalid_response") from err
        if not math.isfinite(number):
            raise ValueError("invalid_response")
        return number
    if isinstance(value, bool):
        value = "true" if value else "false"
    elif isinstance(value, int | float):
        value = str(value)
    if not isinstance(value, str) or len(value) > 255:
        raise ValueError("invalid_response")
    return value


@dataclass(frozen=True, slots=True)
class CustomCommandResult:
    """Last query result; errors never contain raw replies or credentials."""

    response: str | None = None
    error: str | None = None
