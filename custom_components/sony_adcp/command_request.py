"""Structured ADCP requests; never accept raw protocol options."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from .protocol import CommandInfo

OPERATIONS = ("set", "relative", "reset", "execute")
QUERY_TYPES = ("value", "range", "info")
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_TEXT = re.compile(r"[A-Za-z0-9_+./: -]{1,400}", re.ASCII)
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", re.ASCII)


class CommandValidationError(ValueError):
    """A safe, translatable error key, containing no command payload."""


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """Read-only intent with only integration-generated protocol suffixes."""

    command: str
    query_type: str = "value"

    @property
    def frames(self) -> tuple[str, ...]:
        if self.query_type == "value":
            return (f"{self.command} ?",)
        return (f"{self.command} --{self.query_type}",
                f"{self.command} ? --{self.query_type}")


def validate_query_request(data: Mapping[str, Any]) -> QueryRequest:
    """Queries cannot carry write operations, values or raw protocol text."""
    command = data.get("command")
    if not isinstance(command, str) or _NAME.fullmatch(command) is None:
        raise CommandValidationError("command_name_invalid")
    query_type = data.get("query_type", "value")
    if query_type not in QUERY_TYPES or set(data) - {"device_id", "command", "query_type"}:
        raise CommandValidationError("query_type_invalid")
    return QueryRequest(command, query_type)


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """User intent, independent of its ADCP wire representation."""

    command: str
    operation: str
    value: str | int | float | None = None

    @property
    def power(self) -> bool | None:
        if self.command == "power":
            return self.value == "on"
        if self.command == "key" and self.value in ("power_on", "power_off"):
            return self.value == "power_on"
        return None

    def encode(self, info: CommandInfo | None) -> str:
        """Use reported metadata, preserving Sony's case-sensitive choices."""
        if self.power is not None:
            return f'power "{"on" if self.power else "off"}"'
        if self.command == "key":
            return f'key "{self.value}"'
        if info is None:
            raise CommandValidationError("command_metadata_required")
        kind = info.command_type
        if kind not in {"menu_sel", "menu_num", "menu_val", "menu_exec"}:
            raise CommandValidationError("command_type_unsupported")
        if self.operation == "execute":
            if kind != "menu_exec":
                raise CommandValidationError("command_operation_invalid")
            return self.command
        if kind == "menu_exec":
            raise CommandValidationError("command_operation_invalid")
        if self.operation == "reset":
            return f"{self.command} --reset"
        if kind == "menu_sel":
            if self.operation != "set" or not isinstance(self.value, str):
                raise CommandValidationError("command_operation_invalid")
            if info.choices and self.value not in info.choices:
                raise CommandValidationError("command_value_invalid")
            return f'{self.command} "{self.value}"'
        if isinstance(self.value, str) and _NUMBER.fullmatch(self.value) is None:
            raise CommandValidationError("command_value_invalid")
        try:
            value = Decimal(str(self.value))
        except InvalidOperation as err:
            raise CommandValidationError("command_value_invalid") from err
        if not value.is_finite():
            raise CommandValidationError("command_value_invalid")
        if self.operation == "set":
            if (info.minimum is not None and value < Decimal(str(info.minimum))) or (
                info.maximum is not None and value > Decimal(str(info.maximum))
            ):
                raise CommandValidationError("command_value_invalid")
        if info.step is not None and info.step > 0:
            origin = Decimal(str(info.minimum or 0)) if self.operation == "set" else Decimal(0)
            with localcontext() as context:
                context.prec = 1024
                if (value - origin) % Decimal(str(info.step)) != 0:
                    raise CommandValidationError("command_value_invalid")
        number = format(value, "f")
        prefix = "--rel " if self.operation == "relative" else ""
        return f"{self.command} {prefix}{number}"


def validate_request(data: Mapping[str, Any]) -> CommandRequest:
    """Reject malformed requests before any communication or metadata probe."""
    command = data.get("command")
    operation = data.get("operation", "set")
    value = data.get("value")
    if not isinstance(command, str) or _NAME.fullmatch(command) is None:
        raise CommandValidationError("command_name_invalid")
    if operation not in OPERATIONS:
        raise CommandValidationError("command_operation_invalid")
    if operation in {"reset", "execute"}:
        if "value" in data:
            raise CommandValidationError("command_value_unexpected")
    else:
        if type(value) not in {str, int, float}:
            raise CommandValidationError("command_value_invalid")
        if isinstance(value, str):
            if _TEXT.fullmatch(value) is None:
                raise CommandValidationError("command_value_invalid")
        # Bound numbers before Decimal conversion/formatting, including huge ints.
        elif (
            isinstance(value, int) and value.bit_length() > 330
        ) or len(str(value)) > 100 or str(value).lower() in {"nan", "inf", "-inf"}:
            raise CommandValidationError("command_value_invalid")
        if operation == "relative" and _NUMBER.fullmatch(str(value)) is None:
            raise CommandValidationError("command_value_invalid")
    if command == "power" and (operation != "set" or value not in {"on", "off"}):
        raise CommandValidationError("command_value_invalid")
    if command == "key" and (
        operation != "set" or not isinstance(value, str) or value == "power"
    ):
        raise CommandValidationError("command_operation_invalid")
    return CommandRequest(command, operation, value)
