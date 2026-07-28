"""Async Sony ADCP protocol implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from .const import COMMAND_TIMEOUT

_LINE_END: Final = b"\r\n"
_MAX_COMMAND_BYTES: Final = 510


class AdcpError(Exception):
    """Base error for ADCP communication."""


class AdcpConnectionError(AdcpError):
    """The projector could not be reached."""


class AdcpAuthenticationError(AdcpError):
    """The projector rejected authentication."""


class AdcpAuthenticationRequiredError(AdcpAuthenticationError):
    """The projector requires a password."""


class AdcpCommandError(AdcpError):
    """The projector rejected a command."""

    def __init__(self, command: str, response: str) -> None:
        super().__init__(f"{command}: {response}")
        self.command = command
        self.response = response


class AuthenticationMode(StrEnum):
    """Authentication mode learned from the ADCP greeting."""

    NONE = "none"
    PASSWORD = "password"


@dataclass(frozen=True, slots=True)
class ProjectorIdentity:
    """Identity fields reported by the projector."""

    model: str | None = None
    serial: str | None = None
    mac_address: str | None = None


@dataclass(frozen=True, slots=True)
class CommandInfo:
    """ADCP command metadata."""

    command: str
    command_type: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


def normalize_response(raw: bytes) -> str:
    """Normalize an ADCP response while preserving JSON."""
    text = raw.decode("ascii", errors="replace").strip()
    if "=" in text and not text.startswith(("[", "{")):
        text = text.split("=", 1)[1].strip()
    return text.strip().strip('"')


def normalize_mac(value: str | None) -> str | None:
    """Normalize a projector MAC address for the device registry."""
    if not value:
        return None
    compact = "".join(character for character in value if character.isalnum()).lower()
    if len(compact) != 12:
        return value.lower()
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


async def async_probe_authentication(
    host: str, port: int, *, timeout_seconds: float = COMMAND_TIMEOUT
) -> AuthenticationMode:
    """Read only the ADCP greeting and determine whether auth is required."""
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout_seconds
        )
        greeting = normalize_response(
            await asyncio.wait_for(
                reader.readuntil(_LINE_END), timeout=timeout_seconds
            )
        )
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
        raise AdcpConnectionError(f"Could not connect to {host}:{port}") from err
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
    return (
        AuthenticationMode.NONE
        if greeting.upper() == "NOKEY"
        else AuthenticationMode.PASSWORD
    )


class AdcpClient:
    """Serialized, reconnecting async ADCP connection."""

    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        *,
        timeout: float = COMMAND_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def async_close(self) -> None:
        """Close the command connection."""
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def async_set_host(self, host: str) -> None:
        """Move subsequent commands to a newly discovered address."""
        if host == self.host:
            return
        async with self._lock:
            await self.async_close()
            self.host = host

    async def async_command(self, command: str) -> str:
        """Execute a command, reconnecting once after transport failure."""
        encoded = command.encode("ascii")
        if len(encoded) > _MAX_COMMAND_BYTES:
            raise ValueError("ADCP command exceeds Sony's 512-byte frame limit")

        async with self._lock:
            for attempt in range(2):
                try:
                    await self._async_ensure_connected()
                    assert self._reader is not None
                    assert self._writer is not None
                    self._writer.write(encoded + _LINE_END)
                    await self._writer.drain()
                    raw = await asyncio.wait_for(
                        self._reader.readuntil(_LINE_END), timeout=self.timeout
                    )
                    response = normalize_response(raw)
                    if response.lower().startswith(("err_", "ng")):
                        raise AdcpCommandError(command, response)
                    return response
                except (AdcpAuthenticationError, AdcpCommandError):
                    raise
                except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
                    await self.async_close()
                    if attempt:
                        raise AdcpConnectionError(
                            f"Could not communicate with {self.host}:{self.port}"
                        ) from err
        raise AssertionError("unreachable")

    async def async_get_power(self) -> str:
        return (await self.async_command("power_status ?")).lower()

    async def async_set_power(self, power: bool) -> None:
        await self.async_command(f'power "{"on" if power else "off"}"')

    async def async_get_input(self) -> str:
        return (await self.async_command("input ?")).lower()

    async def async_set_input(self, source: str) -> None:
        await self.async_command(f'input "{source}"')

    async def async_get_identity(self) -> ProjectorIdentity:
        async def optional(command: str) -> str | None:
            try:
                value = await self.async_command(command)
            except AdcpCommandError:
                return None
            return value or None

        return ProjectorIdentity(
            model=await optional("modelname ?"),
            serial=await optional("serialnum ?"),
            mac_address=normalize_mac(await optional("mac_address ?")),
        )

    async def async_get_command_info(self, command: str) -> CommandInfo | None:
        """Get command metadata, accommodating Sony's two info syntaxes."""
        for request in (f"{command} --info", f"{command} ? --info"):
            try:
                response = await self.async_command(request)
                payload: dict[str, Any] = json.loads(response)
            except (AdcpCommandError, json.JSONDecodeError):
                continue
            command_type = str(payload.get("type", ""))
            range_value = payload.get("range")
            if isinstance(range_value, list):
                return CommandInfo(
                    command,
                    command_type,
                    tuple(str(value).strip('"').lower() for value in range_value),
                )
            if isinstance(range_value, dict):
                return CommandInfo(
                    command,
                    command_type,
                    minimum=_as_float(range_value.get("min")),
                    maximum=_as_float(range_value.get("max")),
                )
            return CommandInfo(command, command_type)
        return None

    async def async_get_json_list(self, command: str) -> tuple[str, ...]:
        """Read a Sony JSON-array status command."""
        response = await self.async_command(f"{command} ?")
        try:
            value = json.loads(response)
        except json.JSONDecodeError:
            return (response,) if response else ()
        if not isinstance(value, list):
            return (str(value),)
        return tuple(str(item) for item in value)

    async def _async_ensure_connected(self) -> None:
        if self._reader is not None and self._writer is not None:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=self.timeout
            )
            greeting = normalize_response(
                await asyncio.wait_for(
                    self._reader.readuntil(_LINE_END), timeout=self.timeout
                )
            )
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            await self.async_close()
            raise AdcpConnectionError(
                f"Could not connect to {self.host}:{self.port}"
            ) from err

        if greeting.upper() == "NOKEY":
            return
        if not self.password:
            await self.async_close()
            raise AdcpAuthenticationRequiredError(
                "The projector requires an administrator password"
            )

        digest = hashlib.sha256((greeting + self.password).encode("ascii")).hexdigest()
        assert self._writer is not None
        assert self._reader is not None
        try:
            self._writer.write(digest.encode("ascii") + _LINE_END)
            await self._writer.drain()
            response = normalize_response(
                await asyncio.wait_for(
                    self._reader.readuntil(_LINE_END), timeout=self.timeout
                )
            )
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            await self.async_close()
            raise AdcpConnectionError("Connection lost during authentication") from err
        if response.lower() != "ok":
            await self.async_close()
            raise AdcpAuthenticationError(f"Authentication failed: {response}")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
