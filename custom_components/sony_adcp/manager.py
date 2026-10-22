"""Event-driven state manager for Sony ADCP projectors."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import (
    DEFAULT_SOURCES,
    NUMBER_COMMANDS,
    POWER_OFF_STATES,
    POWER_TRANSITION_INTERVAL,
    POWER_TRANSITION_TIMEOUT,
    POWER_WATCHDOG_INTERVAL,
    SDAP_POWER_STATES,
    SELECT_COMMANDS,
)
from .discovery import DiscoveredProjector
from .protocol import (
    AdcpAuthenticationError,
    AdcpClient,
    AdcpError,
    CommandInfo,
    ProjectorIdentity,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectorState:
    """All values exposed by Home Assistant, read from memory by entities."""

    power_status: str | None = None
    source: str | None = None
    signal: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    values: dict[str, str | float | bool] = field(default_factory=dict)
    available: bool = False


class ProjectorManager:
    """Own communication, capabilities, and pushed state."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AdcpClient,
        auth_failed: Callable[[], None],
        host_changed: Callable[[str], None],
        operational_refresh_interval: int,
    ) -> None:
        self.hass = hass
        self.client = client
        self._auth_failed = auth_failed
        self._host_changed = host_changed
        self.identity = ProjectorIdentity()
        self.state = ProjectorState()
        self.command_info: dict[str, CommandInfo] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._refresh_task: asyncio.Task[None] | None = None
        self._operational_refresh_interval = operational_refresh_interval
        self._operational_refresh_task: asyncio.Task[None] | None = None
        self._power_watchdog_task: asyncio.Task[None] | None = None
        self._power_transition_task: asyncio.Task[None] | None = None
        self._power_transition_target: str | None = None
        self._power_command_lock = asyncio.Lock()
        self._power_revision = 0
        self._closed = False
        self._availability_timer: asyncio.TimerHandle | None = None
        self._capabilities_probed = False

    @property
    def sources(self) -> tuple[str, ...]:
        info = self.command_info.get("input")
        return info.choices if info and info.choices else DEFAULT_SOURCES

    @property
    def power_transition_target(self) -> str | None:
        """Requested endpoint while the bounded power refresh is active."""
        return self._power_transition_target

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        @callback
        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    async def async_initialize(self) -> None:
        """Read stable identity, initial state, and available capabilities."""
        self.identity = await self.client.async_get_identity()
        await self.async_refresh(include_diagnostics=True)
        if self.state.power_status not in {None, "standby", "saving_standby"}:
            await self.async_probe_capabilities()
        self._update_operational_refresh_task()
        self._start_power_watchdog()

    @callback
    def _start_power_watchdog(self) -> None:
        """Poll full state on a slow cadence so power can never stay stale.

        Power is otherwise only ever updated by SDAP push announcements, so a
        projector that stops announcing (or announces a stale value) leaves
        Home Assistant permanently wrong with no way to recover short of
        reloading the config entry.
        """
        task = self._power_watchdog_task
        if task is not None and not task.done():
            return
        self._power_watchdog_task = self.hass.async_create_background_task(
            self._async_power_watchdog_loop(),
            "Sony projector power watchdog",
        )

    async def _async_power_watchdog_loop(self) -> None:
        """Refresh full state periodically, regardless of believed power."""
        while True:
            await asyncio.sleep(POWER_WATCHDOG_INTERVAL)
            await self.async_refresh()

    async def async_probe_capabilities(self) -> None:
        """Probe only documented commands; unsupported commands are omitted."""
        commands = (
            "input",
            *SELECT_COMMANDS,
            "blank",
            *NUMBER_COMMANDS,
        )
        for command in commands:
            if self._closed or self._power_transition_target is not None:
                return
            try:
                info = await self.client.async_get_command_info(command)
            except AdcpAuthenticationError:
                self._auth_failed()
                info = None
            except AdcpError:
                info = None
            if info is not None:
                self.command_info[command] = info
        self._capabilities_probed = True
        self._notify()

    async def async_refresh(self, *, include_diagnostics: bool = False) -> None:
        """Refresh after setup, command completion, or a push announcement."""
        if self._closed or self._power_transition_target is not None:
            return
        revision = self._power_revision
        try:
            power = await self.client.async_get_power()
            if self._closed or revision != self._power_revision:
                return
            self._apply_power_status(power)
            revision = self._power_revision
            source = self.state.source
            signal = self.state.signal
            errors = self.state.errors
            warnings = self.state.warnings
            if power == "on":
                source = await self._optional_value("input", source)
                signal = await self._optional_value("signal", signal)
                if include_diagnostics:
                    errors = await self._optional_list("error", errors)
                    warnings = await self._optional_list("warning", warnings)
            else:
                source = None
                signal = None
            # A command or a newer power report can arrive during optional I/O.
            if self._closed or revision != self._power_revision:
                return
            self.state = replace(
                self.state,
                source=source,
                signal=signal,
                errors=errors,
                warnings=warnings,
                available=True,
            )
        except AdcpAuthenticationError:
            if self._closed or revision != self._power_revision:
                return
            self._auth_failed()
            self.state = replace(self.state, available=False)
        except AdcpError:
            if self._closed or revision != self._power_revision:
                return
            self.state = replace(self.state, available=False)
        self._notify()
        self._update_operational_refresh_task()

    @callback
    def _apply_power_status(self, power: str) -> None:
        """Publish confirmed power without waiting for optional status reads."""
        self._power_revision += 1
        updated = replace(
            self.state,
            power_status=power,
            source=self.state.source if power == "on" else None,
            signal=self.state.signal if power == "on" else None,
            available=True,
        )
        if updated != self.state:
            self.state = updated
            self._notify()
        self._update_operational_refresh_task()

    async def async_read_command(self, command: str) -> str | None:
        try:
            value = await self.client.async_command(f"{command} ?")
        except AdcpAuthenticationError:
            self._auth_failed()
            return None
        except AdcpError:
            return None
        values = dict(self.state.values)
        values[command] = value
        self.state = replace(self.state, values=values, available=True)
        self._notify()
        return value

    @callback
    def async_handle_announcement(self, projector: DiscoveredProjector) -> None:
        """Apply pushed power immediately; query only when it changes."""
        if self._closed:
            return
        if projector.model and not self.identity.model:
            self.identity = ProjectorIdentity(
                projector.model, projector.serial, self.identity.mac_address
            )
        announced_power = (
            SDAP_POWER_STATES.get(projector.raw_power_status)
            if projector.raw_power_status is not None
            else None
        )
        power_changed = (
            self._power_transition_target is None
            and announced_power is not None
            and announced_power != self.state.power_status
        )
        host_changed = projector.host != self.client.host
        # During a commanded transition, a delayed SDAP packet must not replace
        # a newer ADCP reading or prematurely finish the requested transition.
        if announced_power is not None and self._power_transition_target is None:
            self._apply_power_status(announced_power)
        if self._availability_timer is not None:
            self._availability_timer.cancel()
        self._availability_timer = asyncio.get_running_loop().call_later(
            95, self._mark_push_unavailable
        )
        if (power_changed or host_changed) and (
            self._refresh_task is None or self._refresh_task.done()
        ):
            self._refresh_task = self.hass.async_create_task(
                self._async_refresh_after_announcement(projector.host),
                "Refresh Sony projector after SDAP announcement",
            )

    async def _async_refresh_after_announcement(self, announced_host: str) -> None:
        if announced_host != self.client.host:
            await self.client.async_set_host(announced_host)
            self._host_changed(announced_host)
        if self._closed or self._power_transition_target is not None:
            return
        await self.async_refresh()
        if (
            not self._capabilities_probed
            and self.state.power_status not in {None, "standby", "saving_standby"}
        ):
            await self.async_probe_capabilities()

    async def async_turn_on(self) -> None:
        await self._async_set_power(True)

    async def async_turn_off(self) -> None:
        await self._async_set_power(False)

    async def _async_set_power(self, power: bool) -> None:
        """Send power once, then monitor the requested endpoint in background."""
        async with self._power_command_lock:
            if self._closed:
                return
            await self._async_control(self.client.async_set_power(power))
            if self._closed:
                return
            previous = self._power_transition_task
            if previous is not None and not previous.done():
                previous.cancel()
                await asyncio.gather(previous, return_exceptions=True)
            self._power_revision += 1
            self._power_transition_target = "on" if power else "off"
            self._power_transition_task = self.hass.async_create_background_task(
                self._async_power_transition_loop(power),
                "Refresh Sony projector power transition",
            )
            self._update_operational_refresh_task()
            self._notify()

    async def _async_power_transition_loop(self, power: bool) -> None:
        """Query only power once a second, for at most the transition timeout."""
        target_states = {"on"} if power else POWER_OFF_STATES
        reached_target = False
        try:
            # Includes connection setup, retries, lock waits, and the final read.
            async with asyncio.timeout(POWER_TRANSITION_TIMEOUT):
                while True:
                    try:
                        status = await self.client.async_get_power()
                    except AdcpAuthenticationError:
                        self._auth_failed()
                        self.state = replace(self.state, available=False)
                        break
                    except AdcpError:
                        self.state = replace(self.state, available=False)
                        self._notify()
                    else:
                        self._apply_power_status(status)
                        if status in target_states:
                            reached_target = True
                            break
                    await asyncio.sleep(POWER_TRANSITION_INTERVAL)
        except TimeoutError:
            _LOGGER.debug("Power transition to %s timed out", self._power_transition_target)
        finally:
            self._power_transition_task = None
            self._power_transition_target = None
            self._notify()
            self._update_operational_refresh_task()
            if (
                reached_target
                and power
                and not self._closed
                and (self._refresh_task is None or self._refresh_task.done())
            ):
                self._refresh_task = self.hass.async_create_task(
                    self._async_refresh_after_announcement(self.client.host),
                    "Refresh Sony projector after power transition",
                )

    async def async_select_source(self, source: str) -> None:
        await self._async_control(self.client.async_set_input(source))
        await self.async_refresh()

    async def async_set_select(self, command: str, option: str) -> None:
        await self._async_control(
            self.client.async_command(f'{command} "{option}"')
        )
        await self.async_read_command(command)

    async def async_set_switch(self, command: str, enabled: bool) -> None:
        await self._async_control(
            self.client.async_command(
                f'{command} "{"on" if enabled else "off"}"'
            )
        )
        await self.async_read_command(command)

    async def async_set_number(self, command: str, value: float) -> None:
        formatted = str(int(value)) if value.is_integer() else str(value)
        await self._async_control(
            self.client.async_command(f"{command} {formatted}")
        )
        await self.async_read_command(command)

    @callback
    def async_set_operational_refresh_interval(self, interval: int) -> None:
        """Apply a new input/signal refresh interval without reloading."""
        if interval == self._operational_refresh_interval:
            return
        self._operational_refresh_interval = interval
        if (
            self._operational_refresh_task is not None
            and not self._operational_refresh_task.done()
        ):
            self._operational_refresh_task.cancel()
        self._operational_refresh_task = None
        self._update_operational_refresh_task()

    async def async_close(self) -> None:
        self._closed = True
        tasks = [
            task
            for task in (
                self._refresh_task,
                self._operational_refresh_task,
                self._power_watchdog_task,
                self._power_transition_task,
            )
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._power_transition_task = None
        self._power_transition_target = None
        if self._availability_timer is not None:
            self._availability_timer.cancel()
        await self.client.async_close()

    @callback
    def _mark_push_unavailable(self) -> None:
        """Mark unavailable after more than three default SDAP intervals."""
        if self._closed or self._power_transition_target is not None:
            return
        self.state = replace(self.state, available=False)
        self._notify()
        self._update_operational_refresh_task()

    @callback
    def _update_operational_refresh_task(self) -> None:
        """Run the operational refresh loop only while the projector is on."""
        should_run = (
            not self._closed
            and self._power_transition_target is None
            and self._operational_refresh_interval > 0
            and self.state.power_status == "on"
            and self.state.available
        )
        task = self._operational_refresh_task
        if not should_run:
            if task is not None and not task.done():
                task.cancel()
            self._operational_refresh_task = None
            return
        if task is None or task.done():
            # Background task: this loop never finishes, so scheduling it with
            # async_create_task makes HA's bootstrap phase wait on it and log
            # "Setup timed out for bootstrap" on every restart.
            self._operational_refresh_task = self.hass.async_create_background_task(
                self._async_operational_refresh_loop(),
                "Refresh Sony projector input and signal",
            )

    async def _async_operational_refresh_loop(self) -> None:
        """Refresh automation-relevant operational state at the chosen interval."""
        while True:
            await asyncio.sleep(self._operational_refresh_interval)
            if (
                self.state.power_status != "on"
                or not self.state.available
                or self._operational_refresh_interval <= 0
            ):
                return
            await self._async_refresh_operational()

    async def _async_refresh_operational(self) -> None:
        """Query input and signal without polling power or image settings."""
        revision = self._power_revision
        source = await self._optional_value("input", self.state.source)
        signal = await self._optional_value("signal", self.state.signal)
        if self._closed or revision != self._power_revision:
            return
        updated = replace(self.state, source=source, signal=signal)
        if updated != self.state:
            self.state = updated
            self._notify()

    async def _optional_value(self, command: str, previous: str | None) -> str | None:
        try:
            return (await self.client.async_command(f"{command} ?")).lower()
        except AdcpAuthenticationError:
            self._auth_failed()
            return previous
        except AdcpError:
            return previous

    async def _optional_list(
        self, command: str, previous: tuple[str, ...]
    ) -> tuple[str, ...]:
        try:
            return await self.client.async_get_json_list(command)
        except AdcpAuthenticationError:
            self._auth_failed()
            return previous
        except AdcpError:
            return previous

    async def _async_control(self, operation: Awaitable[Any]) -> None:
        """Execute a control and start reauth if credentials are rejected."""
        try:
            await operation
        except AdcpAuthenticationError:
            self._auth_failed()
            raise
