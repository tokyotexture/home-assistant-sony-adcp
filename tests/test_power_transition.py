"""Bounded power-transition refresh tests without Home Assistant dependencies."""

from __future__ import annotations

import asyncio
import unittest
from collections import deque
from unittest.mock import patch

from test_protocol import ProjectorManager, ProjectorState, _discovery, _manager, _protocol


class FakeHass:
    def __init__(self):
        self.tasks = []

    def async_create_task(self, coroutine, name):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task

    async_create_background_task = async_create_task


class FakeClient:
    host = "192.0.2.10"

    def __init__(self):
        self.responses = deque()
        self.last_power = "standby"
        self.power_commands = []
        self.queries = []
        self.command_error = None
        self.block = False
        self.reading = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled_read = False

    async def async_set_power(self, power):
        if self.command_error is not None:
            raise self.command_error
        self.power_commands.append(power)

    async def async_get_power(self):
        self.queries.append("power_status ?")
        self.reading.set()
        if self.block:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled_read = True
                raise
        if self.responses:
            response = self.responses.popleft()
            if isinstance(response, Exception):
                raise response
            self.last_power = response
        return self.last_power

    async def async_command(self, command):
        self.queries.append(command)
        return {"input ?": "hdmi1", "signal ?": "3840x2160/60p"}[command]

    async def async_set_host(self, host):
        self.host = host

    async def async_close(self):
        pass


class PowerTransitionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = FakeClient()
        self.auth_failures = []
        self.host_changes = []
        self.manager = ProjectorManager(
            self.hass, self.client, lambda: self.auth_failures.append(True),
            self.host_changes.append, operational_refresh_interval=0,
        )
        self.manager._capabilities_probed = True
        self.manager.state = ProjectorState(power_status="standby", available=True)
        self.interval_patch = patch.object(_manager, "POWER_TRANSITION_INTERVAL", 0.001)
        self.interval_patch.start()
        self.history = []
        self.manager.async_add_listener(
            lambda: self.history.append(self.manager.state.power_status)
        )

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)
        self.interval_patch.stop()

    async def finish(self):
        task = self.manager._power_transition_task
        self.assertIsNotNone(task)
        await asyncio.wait_for(task, 0.5)
        self.assertIsNone(self.manager.power_transition_target)

    async def test_on_publishes_startup_then_stops_only_at_on(self):
        self.client.responses.extend(["standby", "startup", "on"])
        await self.manager.async_turn_on()
        self.assertEqual(self.manager.power_transition_target, "on")
        await self.finish()
        self.assertIn("startup", self.history)
        self.assertEqual(self.manager.state.power_status, "on")
        self.assertEqual(self.client.power_commands, [True])
        # The first three queries belong to the session and query power only.
        self.assertEqual(self.client.queries[:3], ["power_status ?"] * 3)
        await asyncio.gather(*self.hass.tasks)
        self.assertEqual(self.manager.state.source, "hdmi1")

    async def test_off_does_not_stop_at_old_on_or_intermediate_cooling(self):
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.client.responses.extend(["on", "cooling1", "cooling2", "standby"])
        await self.manager.async_turn_off()
        await self.finish()
        self.assertIn("cooling1", self.history)
        self.assertIn("cooling2", self.history)
        self.assertEqual(self.manager.state.power_status, "standby")
        self.assertEqual(self.client.queries, ["power_status ?"] * 4)
        count = len(self.client.queries)
        await asyncio.sleep(0.005)
        self.assertEqual(len(self.client.queries), count)

    async def test_saving_standby_is_an_off_endpoint(self):
        self.client.responses.extend(["cooling2", "saving_standby"])
        await self.manager.async_turn_off()
        await self.finish()
        self.assertEqual(self.manager.state.power_status, "saving_standby")

    async def test_service_returns_while_background_read_is_pending(self):
        self.client.block = True
        await asyncio.wait_for(self.manager.async_turn_on(), 0.1)
        await self.client.reading.wait()
        self.assertFalse(self.manager._power_transition_task.done())

    async def test_new_command_replaces_and_awaits_old_session(self):
        self.client.block = True
        await self.manager.async_turn_on()
        old = self.manager._power_transition_task
        await self.client.reading.wait()
        await self.manager.async_turn_off()
        self.assertTrue(old.cancelled())
        self.assertTrue(self.client.cancelled_read)
        self.assertEqual(self.manager.power_transition_target, "off")
        self.client.block = False
        self.client.last_power = "standby"
        await self.finish()
        self.assertEqual(self.client.power_commands, [True, False])

    async def test_failed_command_does_not_start_a_session(self):
        self.client.command_error = _protocol.AdcpCommandError('power "on"', "err_cmd")
        with self.assertRaises(_protocol.AdcpCommandError):
            await self.manager.async_turn_on()
        self.assertIsNone(self.manager._power_transition_task)
        self.assertEqual(self.client.queries, [])

    async def test_failed_replacement_preserves_previous_session(self):
        self.client.block = True
        await self.manager.async_turn_on()
        old = self.manager._power_transition_task
        self.client.command_error = _protocol.AdcpCommandError('power "off"', "err_cmd")
        with self.assertRaises(_protocol.AdcpCommandError):
            await self.manager.async_turn_off()
        self.assertIs(self.manager._power_transition_task, old)
        self.assertEqual(self.manager.power_transition_target, "on")

    async def test_timeout_includes_a_blocked_read(self):
        self.client.block = True
        with patch.object(_manager, "POWER_TRANSITION_TIMEOUT", 0.02):
            await self.manager.async_turn_on()
            await self.finish()
        self.assertTrue(self.client.cancelled_read)
        self.assertEqual(self.manager.state.power_status, "standby")
        self.assertEqual(self.client.power_commands, [True])

    async def test_ignored_command_times_out_without_resending_power(self):
        self.client.last_power = "on"
        with patch.object(_manager, "POWER_TRANSITION_TIMEOUT", 0.02):
            await self.manager.async_turn_off()
            await self.finish()
        self.assertEqual(self.manager.state.power_status, "on")
        self.assertEqual(self.client.power_commands, [False])
        self.assertGreater(len(self.client.queries), 1)

    async def test_authentication_failure_stops_and_requests_reauth(self):
        self.client.responses.append(_protocol.AdcpAuthenticationError("bad password"))
        await self.manager.async_turn_on()
        await self.finish()
        self.assertEqual(self.auth_failures, [True])
        self.assertFalse(self.manager.state.available)
        self.assertEqual(len(self.client.queries), 1)

    async def test_transient_transport_error_recovers_within_window(self):
        self.client.responses.extend([
            _protocol.AdcpConnectionError("restarting"), "startup", "on"
        ])
        await self.manager.async_turn_on()
        await self.finish()
        self.assertEqual(self.manager.state.power_status, "on")
        self.assertTrue(self.manager.state.available)

    async def test_close_cancels_pending_read_and_prevents_new_sessions(self):
        self.client.block = True
        await self.manager.async_turn_on()
        task = self.manager._power_transition_task
        await self.client.reading.wait()
        await self.manager.async_close()
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.manager.power_transition_target)
        await self.manager.async_turn_on()
        self.assertEqual(self.client.power_commands, [True])

    async def test_close_before_background_task_starts_clears_session(self):
        await self.manager.async_turn_on()
        await self.manager.async_close()
        self.assertIsNone(self.manager.power_transition_target)
        self.assertIsNone(self.manager._power_transition_task)

    async def test_sdap_cannot_override_adcp_or_end_transition_early(self):
        self.client.responses.extend(["startup", "on"])
        with patch.object(_manager, "POWER_TRANSITION_INTERVAL", 0.02):
            await self.manager.async_turn_on()
            await self.client.reading.wait()
            self.manager.async_handle_announcement(_discovery.DiscoveredProjector(
                host=self.client.host, raw_power_status=0,
            ))
            self.assertEqual(self.manager.state.power_status, "startup")
            self.manager.async_handle_announcement(_discovery.DiscoveredProjector(
                host=self.client.host, raw_power_status=3,
            ))
            self.assertEqual(self.manager.power_transition_target, "on")
            self.assertEqual(self.manager.state.power_status, "startup")
            self.assertIsNone(self.manager._refresh_task)
            await self.finish()

    async def test_sdap_resumes_after_session(self):
        await self.manager.async_turn_off()
        await self.finish()
        self.manager.async_handle_announcement(_discovery.DiscoveredProjector(
            host=self.client.host, raw_power_status=1,
        ))
        self.assertEqual(self.manager.state.power_status, "startup")
        self.assertIsNone(self.manager.power_transition_target)

    async def test_watchdog_and_optional_refresh_do_not_compete_with_session(self):
        self.client.block = True
        await self.manager.async_turn_on()
        await self.client.reading.wait()
        await self.manager.async_refresh(include_diagnostics=True)
        self.assertEqual(self.client.queries, ["power_status ?"])

    async def test_dhcp_migration_still_works_during_session(self):
        self.client.block = True
        await self.manager.async_turn_on()
        self.manager.async_handle_announcement(_discovery.DiscoveredProjector(
            host="192.0.2.20", raw_power_status=0,
        ))
        await self.manager._refresh_task
        self.assertEqual(self.client.host, "192.0.2.20")
        self.assertEqual(self.host_changes, ["192.0.2.20"])
        self.assertEqual(self.manager.power_transition_target, "on")

    async def test_external_sdap_change_does_not_start_fast_polling(self):
        self.manager.async_handle_announcement(_discovery.DiscoveredProjector(
            host=self.client.host, raw_power_status=1,
        ))
        self.assertIsNone(self.manager._power_transition_task)
        await self.manager._refresh_task
        self.assertFalse(any("power transition" in task.get_name() for task in self.hass.tasks))

    async def test_in_flight_optional_read_cannot_restore_stale_on_state(self):
        self.client.last_power = "on"
        input_started = asyncio.Event()
        input_release = asyncio.Event()
        original_command = self.client.async_command

        async def delayed_input(command):
            if command == "input ?":
                input_started.set()
                await input_release.wait()
            return await original_command(command)

        with patch.object(self.client, "async_command", side_effect=delayed_input):
            refresh = self.hass.async_create_task(self.manager.async_refresh(), "old refresh")
            await input_started.wait()
            self.client.last_power = "standby"
            await self.manager.async_turn_off()
            await self.finish()
            input_release.set()
            await refresh
        self.assertEqual(self.manager.state.power_status, "standby")
        self.assertIsNone(self.manager.state.source)
