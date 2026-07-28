"""Sony Simple Display Advertisement Protocol support."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.core import callback

from .const import ADVERTISEMENT_PORT, SDAP_COMMUNICATION_ERROR

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveredProjector:
    """Fields sent in a Sony SDAP packet."""

    host: str
    community: str | None = None
    model: str | None = None
    serial: str | None = None
    raw_power_status: int | None = None
    location: str | None = None

    @property
    def unique_id(self) -> str:
        return self.serial or self.host


def normalize_serial(value: str | None) -> str | None:
    """Normalize serials because SDAP transports them as an integer."""
    if not value:
        return None
    normalized = value.strip().lstrip("0")
    return normalized or "0"


def _text(payload: bytes) -> str | None:
    value = payload.split(b"\0", 1)[0].decode("utf-8", errors="ignore").strip()
    return value or None


def parse_sdap_packet(payload: bytes, host: str) -> DiscoveredProjector | None:
    """Parse the 50-byte packet specified by Sony's common manual."""
    if (
        len(payload) < 50
        or payload[:2] != b"DA"
        or payload[2] != 0x01
        or payload[3] != 0x0A
    ):
        return None
    power = int.from_bytes(payload[24:26], byteorder="big")
    return DiscoveredProjector(
        host=host,
        community=_text(payload[4:8]),
        model=_text(payload[8:20]),
        serial=(
            str(serial_number)
            if (serial_number := int.from_bytes(payload[20:24], byteorder="big"))
            else None
        ),
        raw_power_status=None if power == SDAP_COMMUNICATION_ERROR else power,
        location=_text(payload[26:50]),
    )


class _SdapProtocol(asyncio.DatagramProtocol):
    def __init__(self, listener: SdapListener) -> None:
        self.listener = listener

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        projector = parse_sdap_packet(data, addr[0])
        if projector is not None:
            self.listener.async_process(projector)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("SDAP listener error: %s", exc)


class SdapListener:
    """One shared UDP listener with discovery cache and push callbacks."""

    def __init__(self) -> None:
        self.devices: dict[str, DiscoveredProjector] = {}
        self._host_callbacks: dict[
            str, set[Callable[[DiscoveredProjector], None]]
        ] = {}
        self._serial_callbacks: dict[
            str, set[Callable[[DiscoveredProjector], None]]
        ] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._changed = asyncio.Event()

    async def async_start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _SdapProtocol(self),
            local_addr=("0.0.0.0", ADVERTISEMENT_PORT),
            allow_broadcast=True,
        )
        self._transport = transport

    async def async_wait_for_devices(
        self, timeout_seconds: float
    ) -> list[DiscoveredProjector]:
        """Wait for at least one advertisement, returning the current cache."""
        if not self.devices:
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout_seconds)
            except TimeoutError:
                pass
        return sorted(
            self.devices.values(), key=lambda device: (device.model or "", device.host)
        )

    @callback
    def async_process(self, projector: DiscoveredProjector) -> None:
        if serial := normalize_serial(projector.serial):
            for known_host, known in tuple(self.devices.items()):
                if (
                    known_host != projector.host
                    and normalize_serial(known.serial) == serial
                ):
                    self.devices.pop(known_host)
        self.devices[projector.host] = projector
        self._changed.set()
        callbacks = set(self._host_callbacks.get(projector.host, ()))
        if serial:
            callbacks.update(self._serial_callbacks.get(serial, ()))
        for update_callback in callbacks:
            update_callback(projector)

    @callback
    def async_subscribe(
        self,
        host: str,
        serial: str | None,
        update_callback: Callable[[DiscoveredProjector], None],
    ) -> Callable[[], None]:
        host_callbacks = self._host_callbacks.setdefault(host, set())
        host_callbacks.add(update_callback)
        normalized_serial = normalize_serial(serial)
        if normalized_serial:
            serial_callbacks = self._serial_callbacks.setdefault(
                normalized_serial, set()
            )
            serial_callbacks.add(update_callback)

        @callback
        def unsubscribe() -> None:
            host_callbacks.discard(update_callback)
            if not host_callbacks:
                self._host_callbacks.pop(host, None)
            if normalized_serial:
                serial_callbacks.discard(update_callback)
                if not serial_callbacks:
                    self._serial_callbacks.pop(normalized_serial, None)

        return unsubscribe

    async def async_stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._host_callbacks.clear()
        self._serial_callbacks.clear()
