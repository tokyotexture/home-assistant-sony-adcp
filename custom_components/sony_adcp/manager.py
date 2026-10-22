"""Event-driven state manager for Sony ADCP projectors."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import (
    DEFAULT_REFRESH_PICTURE_SETTINGS,
    DEFAULT_SOURCES,
    NUMBER_COMMANDS,
    PICTURE_REFRESH_BUDGET,
    PICTURE_REFRESH_RETRY_INTERVAL,
    POWER_OFF_STATES,
    POWER_OFF_TRANSITION_TIMEOUT,
    POWER_ON_TRANSITION_TIMEOUT,
    POWER_TRANSITION_INTERVAL,
    POWER_WATCHDOG_INTERVAL,
    SDAP_POWER_STATES,
    SELECT_COMMANDS,
    SWITCH_COMMANDS,
)
from .discovery import DiscoveredProjector
from .protocol import (
    AdcpAuthenticationError,
    AdcpClient,
    AdcpCommandError,
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
    timer_hours: dict[str, int] = field(default_factory=dict)
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
        refresh_picture_settings: bool = DEFAULT_REFRESH_PICTURE_SETTINGS,
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
        self._refresh_picture_settings = refresh_picture_settings
        self._picture_commands: dict[str, int] = {}
        self._picture_retry_after: dict[str, float] = {}
        self._picture_revision = 0
        self._operational_refresh_lock = asyncio.Lock()
        self._operational_refresh_task: asyncio.Task[None] | None = None
        self._power_watchdog_task: asyncio.Task[None] | None = None
        self._power_transition_task: asyncio.Task[None] | None = None
        self._power_transition_target: str | None = None
        self._timer_refresh_task: asyncio.Task[None] | None = None
        self._timer_refresh_requested = False
        self._timer_refresh_lock = asyncio.Lock()
        self._timers_initialized = False
        self._timers_supported: bool | None = None
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
        await self.async_refresh_timer_hours()
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
        previous_power = self.state.power_status
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
        if self._timers_initialized and (
            (
                power in POWER_OFF_STATES
                and previous_power is not None
                and previous_power not in POWER_OFF_STATES
            )
            or (power == "on" and previous_power != "on" and not self.state.timer_hours)
        ):
            self._schedule_timer_refresh()

    @callback
    def _schedule_timer_refresh(self) -> None:
        """Refresh counters once per standby transition, never on a timer."""
        if self._closed or self._timers_supported is False:
            return
        self._timer_refresh_requested = True
        if self._timer_refresh_task is None or self._timer_refresh_task.done():
            self._timer_refresh_task = self.hass.async_create_background_task(
                self._async_timer_refresh_loop(), "Refresh Sony projector usage hours",
                eager_start=False,
            )

    async def _async_timer_refresh_loop(self) -> None:
        try:
            # SDAP may also report a new DHCP address. Let that refresh finish
            # moving the connection before reading optional counters.
            refresh = self._refresh_task
            if refresh is not None and not refresh.done():
                await asyncio.shield(asyncio.gather(refresh, return_exceptions=True))
            while self._timer_refresh_requested and not self._closed:
                self._timer_refresh_requested = False
                await self.async_refresh_timer_hours()
        finally:
            self._timer_refresh_task = None

    async def async_refresh_timer_hours(self) -> None:
        """Read optional counters at setup and standby, retaining known values on error."""
        async with self._timer_refresh_lock:
            if self._closed or self._timers_supported is False:
                return
            self._timers_initialized = True
            try:
                hours = await self.client.async_get_timer_hours()
            except AdcpAuthenticationError:
                self._auth_failed()
                return
            except AdcpCommandError as err:
                if err.response == "err_cmd":
                    self._timers_supported = False
                return
            except AdcpError:
                return
            if self._closed or not hours:
                return
            self._timers_supported = True
            updated = {**self.state.timer_hours, **hours}
            if updated != self.state.timer_hours:
                self.state = replace(self.state, timer_hours=updated)
                self._notify()

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
    def async_track_refresh_command(self, command: str) -> Callable[[], None]:
        """Track only enabled control entities, with one query per command."""
        if command not in {*SELECT_COMMANDS, *NUMBER_COMMANDS, *SWITCH_COMMANDS}:
            raise ValueError(f"Not a picture-setting command: {command}")
        self._picture_commands[command] = self._picture_commands.get(command, 0) + 1
        subscribed = True

        @callback
        def unsubscribe() -> None:
            nonlocal subscribed
            if not subscribed:
                return
            subscribed = False
            remaining = self._picture_commands[command] - 1
            if remaining:
                self._picture_commands[command] = remaining
            else:
                del self._picture_commands[command]
                self._picture_retry_after.pop(command, None)

        return unsubscribe

    @callback
    def async_handle_announcement(self, projector: DiscoveredProjector) -> None:
        """Apply pushed power immediately; query only when it changes."""
        if self._closed:
            return
        if projector.model and not self.identity.model:
            self.identity = ProjectorIdentity(
                projector.model, projector.serial, self.identity.mac_address,
                self.identity.firmware,
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
        timeout = POWER_ON_TRANSITION_TIMEOUT if power else POWER_OFF_TRANSITION_TIMEOUT
        reached_target = False
        try:
            # Includes connection setup, retries, lock waits, and the final read.
            async with asyncio.timeout(timeout):
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

    @callback
    def async_set_refresh_picture_settings(self, enabled: bool) -> None:
        """Apply picture refresh options without reloading or extra tasks."""
        if enabled != self._refresh_picture_settings:
            self._refresh_picture_settings = enabled
            self._picture_revision += 1

    async def async_close(self) -> None:
        self._closed = True
        tasks = [
            task
            for task in (
                self._refresh_task,
                self._operational_refresh_task,
                self._power_watchdog_task,
                self._power_transition_task,
                self._timer_refresh_task,
            )
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._power_transition_task = None
        self._power_transition_target = None
        self._timer_refresh_requested = False
        self._timer_refresh_task = None
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
                "Refresh Sony projector operational state",
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
        """Publish input/signal first, then refresh enabled picture controls."""
        async with self._operational_refresh_lock:
            revision = self._power_revision
            if not self._can_refresh_operational(revision):
                return
            source = await self._optional_value("input", self.state.source)
            if not self._can_refresh_operational(revision):
                return
            signal = await self._optional_value("signal", self.state.signal)
            if not self._can_refresh_operational(revision):
                return
            updated = replace(self.state, source=source, signal=signal)
            if updated != self.state:
                self.state = updated
                self._notify()
            await self._async_refresh_picture_settings(revision)

    def _can_refresh_operational(self, revision: int) -> bool:
        return (
            not self._closed
            and revision == self._power_revision
            and self._power_transition_target is None
            and not self._power_command_lock.locked()
            and self.state.power_status == "on"
            and self.state.available
        )

    async def _async_refresh_picture_settings(self, power_revision: int) -> None:
        """Bound optional reads so slow settings cannot monopolize ADCP."""
        if not self._refresh_picture_settings:
            return
        picture_revision = self._picture_revision
        loop = asyncio.get_running_loop()
        command = ""
        try:
            # Picture mode first: changing it may also change numeric settings.
            async with asyncio.timeout(PICTURE_REFRESH_BUDGET):
                for command in (*SELECT_COMMANDS, *NUMBER_COMMANDS, *SWITCH_COMMANDS):
                    if (
                        not self._can_refresh_operational(power_revision)
                        or not self._refresh_picture_settings
                        or picture_revision != self._picture_revision
                    ):
                        return
                    if (
                        command not in self._picture_commands
                        or (command not in self.command_info and command not in self.state.values)
                        or self._picture_retry_after.get(command, 0) > loop.time()
                    ):
                        continue
                    try:
                        value = await self.client.async_command(f"{command} ?")
                    except AdcpAuthenticationError:
                        self._auth_failed()
                        return
                    except AdcpError:
                        self._picture_retry_after[command] = (
                            loop.time() + PICTURE_REFRESH_RETRY_INTERVAL
                        )
                        continue
                    if (
                        not self._can_refresh_operational(power_revision)
                        or not self._refresh_picture_settings
                        or picture_revision != self._picture_revision
                    ):
                        return
                    if command not in self._picture_commands:
                        continue
                    self._picture_retry_after.pop(command, None)
                    if self.state.values.get(command) != value:
                        values = {**self.state.values, command: value}
                        self.state = replace(self.state, values=values)
                        self._notify()
        except TimeoutError:
            self._picture_retry_after[command] = loop.time() + PICTURE_REFRESH_RETRY_INTERVAL
            _LOGGER.debug("Picture refresh budget exhausted while reading %s", command)

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
