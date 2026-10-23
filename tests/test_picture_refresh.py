"""Shared, bounded picture-setting refresh regression tests."""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_power_transition import FakeHass
from test_protocol import ProjectorManager, ProjectorState, _manager, _protocol


class PictureClient:
    host = "192.0.2.10"

    def __init__(self):
        self.commands = []
        self.responses = {
            "input ?": "hdmi2", "signal ?": "3840x2160_60p",
            "picture_mode ?": "game", "sharpness ?": "65", "blank ?": "on",
        }
        self.block_command = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def async_command(self, command, *, retry=True):
        self.commands.append(command)
        if command == self.block_command:
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        response = self.responses[command]
        if isinstance(response, Exception):
            raise response
        return response

    async def async_close(self):
        pass


class PictureRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = PictureClient()
        self.auth_failures = []
        self.manager = ProjectorManager(
            self.hass, self.client, lambda: self.auth_failures.append(True),
            lambda host: None, operational_refresh_interval=0,
        )
        self.manager.state = ProjectorState(
            power_status="on", available=True, source="hdmi1", signal="old",
            values={"picture_mode": "cinema_film1", "sharpness": "20", "blank": "off"},
        )
        self.history = []
        self.manager.async_add_listener(lambda: self.history.append(self.manager.state))

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    def enable(self, *commands):
        return [self.manager.async_track_refresh_command(command) for command in commands]

    async def test_updates_existing_controls_after_input_and_signal(self):
        self.enable("sharpness", "blank", "picture_mode")
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, [
            "input ?", "signal ?", "picture_mode ?", "sharpness ?", "blank ?",
        ])
        self.assertEqual(self.history[0].source, "hdmi2")
        self.assertEqual(self.history[0].signal, "3840x2160_60p")
        self.assertEqual(self.history[0].values["sharpness"], "20")
        self.assertEqual(self.manager.state.values, {
            "picture_mode": "game", "sharpness": "65", "blank": "on",
        })

    async def test_no_enabled_entities_means_no_picture_queries(self):
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, ["input ?", "signal ?"])

    async def test_option_off_keeps_input_and_signal_refresh(self):
        self.enable("sharpness")
        self.manager._picture_pending_reads.clear()  # Initial read already completed.
        self.manager.async_set_refresh_picture_settings(False)
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, ["input ?", "signal ?"])
        self.assertEqual(self.manager.state.values["sharpness"], "20")

    async def test_duplicate_registration_queries_once_and_unsubscribes_safely(self):
        first, second = self.enable("sharpness", "sharpness")
        first()
        first()
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands.count("sharpness ?"), 1)
        second()
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands.count("sharpness ?"), 1)

    async def test_unproven_command_is_not_queried(self):
        self.enable("brightness")
        self.manager._picture_pending_reads.clear()  # Not a pending initial on-read.
        await self.manager._async_refresh_operational()
        self.assertNotIn("brightness ?", self.client.commands)

    async def test_capability_metadata_allows_first_read(self):
        self.enable("brightness")
        self.manager.command_info["brightness"] = _protocol.CommandInfo("brightness", "menu_num")
        self.client.responses["brightness ?"] = "40"
        await self.manager._async_refresh_operational()
        self.assertEqual(self.manager.state.values["brightness"], "40")

    async def test_unknown_commands_cannot_be_registered(self):
        with self.assertRaises(ValueError):
            self.manager.async_track_refresh_command('power "off"')

    async def test_failed_setting_keeps_other_settings_and_backs_off(self):
        self.enable("picture_mode", "sharpness", "blank")
        self.client.responses["sharpness ?"] = _protocol.AdcpCommandError(
            "sharpness ?", "err_cmd"
        )
        await self.manager._async_refresh_operational()
        self.assertTrue(self.manager.state.available)
        self.assertNotIn("sharpness", self.manager.state.values)
        self.assertEqual(self.manager.state.values["blank"], "on")
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands.count("sharpness ?"), 1)
        self.client.responses["sharpness ?"] = "75"
        self.manager._picture_retry_after["sharpness"] = 0
        await self.manager._async_refresh_operational()
        self.assertEqual(self.manager.state.values["sharpness"], "75")

    async def test_startup_inactive_settings_recover_on_next_configured_cycle(self):
        self.enable("picture_mode", "sharpness", "blank")
        self.manager._operational_refresh_interval = 10
        self.manager._apply_power_status("startup")
        self.manager._apply_power_status("on")
        revision = self.manager._power_revision
        now = asyncio.get_running_loop().time()
        for command in ("picture_mode ?", "sharpness ?"):
            self.client.responses[command] = _protocol.AdcpCommandError(command, "err_inactive")
        with self.assertLogs("custom_components.sony_adcp.manager", level="DEBUG") as logs:
            await self.manager._async_refresh_picture_settings(revision, {}, initial=True)
        self.assertEqual(self.manager.state.values, {"blank": "on"})
        self.assertTrue(any("err_inactive" in message and "10 seconds" in message
                            for message in logs.output))
        for command in ("picture_mode", "sharpness"):
            self.assertAlmostEqual(self.manager._picture_retry_after[command], now + 10, delta=1)

        self.client.responses.update({"picture_mode ?": "game", "sharpness ?": "65"})
        self.client.commands.clear()
        await self.manager._async_refresh_operational()
        self.assertNotIn("picture_mode ?", self.client.commands)  # Still before next cycle.
        with patch.object(asyncio.get_running_loop(), "time", return_value=now + 11):
            await self.manager._async_refresh_operational()
        self.assertEqual(self.manager.state.values, {
            "picture_mode": "game", "sharpness": "65", "blank": "on",
        })
        self.assertEqual(self.manager._picture_retry_after, {})
        self.assertEqual(self.manager._picture_pending_reads, set())

    async def test_startup_retry_uses_each_configured_interval(self):
        self.manager._picture_startup_until = asyncio.get_running_loop().time() + 60
        inactive = _protocol.AdcpCommandError("sharpness ?", "err_inactive")
        for interval in (5, 10, 30):
            with self.subTest(interval=interval):
                self.manager._operational_refresh_interval = interval
                self.assertEqual(self.manager._picture_retry_delay(inactive), interval)

    async def test_startup_short_retry_is_only_for_inactive_not_other_failures(self):
        self.manager._operational_refresh_interval = 10
        self.manager._picture_startup_until = asyncio.get_running_loop().time() + 60
        for error in (
            _protocol.AdcpCommandError("sharpness ?", "err_cmd"),
            _protocol.AdcpCommandError("sharpness ?", "err_option"),
            _protocol.AdcpConnectionError("offline"),
        ):
            with self.subTest(error=type(error).__name__, message=str(error)):
                self.assertEqual(self.manager._picture_retry_delay(error), 60)

    async def test_startup_recovery_window_is_not_extended_by_repeated_on_reports(self):
        self.enable("sharpness")
        self.manager._operational_refresh_interval = 10
        self.manager._apply_power_status("startup")
        self.manager._apply_power_status("on")
        deadline = self.manager._picture_startup_until
        inactive = _protocol.AdcpCommandError("sharpness ?", "err_inactive")
        with patch.object(asyncio.get_running_loop(), "time", return_value=deadline + 1):
            self.manager._apply_power_status("on")
            self.assertEqual(self.manager._picture_startup_until, deadline)
            self.assertEqual(self.manager._picture_retry_delay(inactive), 60)
            self.client.responses["sharpness ?"] = inactive
            await self.manager._async_refresh_picture_settings(
                self.manager._power_revision, {}, initial=True,
            )
            self.assertEqual(self.manager._picture_retry_after["sharpness"], deadline + 61)
        self.manager._apply_power_status("cooling1")
        self.assertEqual(self.manager._picture_startup_until, 0)

    async def test_picture_option_off_still_finishes_pending_initial_reads(self):
        self.enable("picture_mode", "sharpness")
        self.manager._operational_refresh_interval = 10
        self.manager.async_set_refresh_picture_settings(False)
        self.manager._apply_power_status("startup")
        self.manager._apply_power_status("on")
        now = asyncio.get_running_loop().time()
        self.client.responses["picture_mode ?"] = _protocol.AdcpCommandError(
            "picture_mode ?", "err_inactive",
        )
        await self.manager._async_refresh_picture_settings(
            self.manager._power_revision, {}, initial=True,
        )
        self.assertEqual(self.manager.state.values, {"sharpness": "65"})
        self.client.responses["picture_mode ?"] = "game"
        self.client.commands.clear()
        with patch.object(asyncio.get_running_loop(), "time", return_value=now + 11):
            await self.manager._async_refresh_operational()
        self.assertIn("picture_mode ?", self.client.commands)
        self.assertNotIn("sharpness ?", self.client.commands)  # Already read successfully.
        self.assertEqual(self.manager.state.values["picture_mode"], "game")
        self.client.commands.clear()
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, ["input ?", "signal ?"])

    async def test_disabled_refresh_does_not_start_short_retry_loop(self):
        self.enable("sharpness")
        self.manager._apply_power_status("startup")
        self.manager._apply_power_status("on")
        self.client.responses["sharpness ?"] = _protocol.AdcpCommandError(
            "sharpness ?", "err_inactive",
        )
        now = asyncio.get_running_loop().time()
        await self.manager._async_refresh_picture_settings(
            self.manager._power_revision, {}, initial=True,
        )
        self.assertAlmostEqual(self.manager._picture_retry_after["sharpness"], now + 60, delta=1)
        self.assertIsNone(self.manager._operational_refresh_task)
        self.assertEqual(self.hass.tasks, [])

    async def test_budget_cancels_slow_query_and_other_settings_recover_next_cycle(self):
        self.enable("picture_mode", "sharpness")
        self.client.block_command = "picture_mode ?"
        with patch.object(_manager, "PICTURE_REFRESH_BUDGET", 0.01):
            await self.manager._async_refresh_operational()
        self.assertTrue(self.client.cancelled)
        self.assertTrue(self.manager.state.available)
        self.assertEqual(self.manager.state.source, "hdmi2")
        self.assertNotIn("sharpness ?", self.client.commands)
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands.count("picture_mode ?"), 1)
        self.assertEqual(self.manager.state.values["sharpness"], "65")

    async def test_authentication_stops_optional_queries_and_requests_reauth(self):
        self.enable("picture_mode", "sharpness")
        self.client.responses["picture_mode ?"] = _protocol.AdcpAuthenticationError("bad")
        await self.manager._async_refresh_operational()
        self.assertEqual(self.auth_failures, [True])
        self.assertNotIn("sharpness ?", self.client.commands)

    async def test_not_on_or_transitioning_means_no_operational_queries(self):
        self.enable("sharpness")
        for power in ("standby", "saving_standby", "startup", "cooling1", "cooling2"):
            self.manager.state = ProjectorState(power_status=power, available=True)
            await self.manager._async_refresh_operational()
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.manager._power_transition_target = "off"
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, [])

    async def test_power_command_waiting_stops_new_operational_queries(self):
        async with self.manager._power_command_lock:
            await self.manager._async_refresh_operational()
        self.assertEqual(self.client.commands, [])

    async def pending_picture_read(self):
        self.enable("picture_mode", "sharpness")
        self.client.block_command = "picture_mode ?"
        task = asyncio.create_task(self.manager._async_refresh_operational())
        self.addAsyncCleanup(self.cancel_task, task)
        await asyncio.wait_for(self.client.started.wait(), 0.5)
        return task

    @staticmethod
    async def cancel_task(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_disabling_option_discards_in_flight_reply_and_stops_further_reads(self):
        task = await self.pending_picture_read()
        self.manager.async_set_refresh_picture_settings(False)
        self.client.release.set()
        await task
        self.assertEqual(self.manager.state.values["picture_mode"], "cinema_film1")
        self.assertNotIn("sharpness ?", self.client.commands)

    async def test_new_power_state_discards_in_flight_setting(self):
        task = await self.pending_picture_read()
        self.manager._apply_power_status("standby")
        self.client.release.set()
        await task
        self.assertEqual(self.manager.state.power_status, "standby")
        self.assertEqual(self.manager.state.values, {})
        self.assertIsNone(self.manager.state.source)
        self.assertNotIn("sharpness ?", self.client.commands)

    async def test_entity_removal_discards_its_in_flight_reply(self):
        task = await self.pending_picture_read()
        del self.manager._picture_commands["picture_mode"]
        self.client.release.set()
        await task
        self.assertEqual(self.manager.state.values["picture_mode"], "cinema_film1")
        self.assertEqual(self.manager.state.values["sharpness"], "65")

    async def test_stale_failed_read_does_not_clear_new_power_sessions_value(self):
        self.enable("sharpness")
        self.client.block_command = "sharpness ?"
        self.client.responses["sharpness ?"] = _protocol.AdcpConnectionError("old failure")
        task = asyncio.create_task(self.manager.async_read_command("sharpness"))
        await self.client.started.wait()
        self.manager._apply_power_status("standby")
        self.manager._apply_power_status("on")
        self.manager.state = replace(self.manager.state, values={"sharpness": "80"})
        self.client.release.set()
        await task
        self.assertEqual(self.manager.state.values["sharpness"], "80")

    async def test_unchanged_values_do_not_notify_entities_again(self):
        self.enable("picture_mode", "sharpness", "blank")
        await self.manager._async_refresh_operational()
        self.history.clear()
        await self.manager._async_refresh_operational()
        self.assertEqual(self.history, [])

    async def test_refresh_cycles_do_not_overlap(self):
        first = await self.pending_picture_read()
        second = asyncio.create_task(self.manager._async_refresh_operational())
        self.addAsyncCleanup(self.cancel_task, second)
        await asyncio.sleep(0)
        self.assertEqual(self.client.commands.count("input ?"), 1)
        self.client.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(self.client.commands.count("input ?"), 2)

    def test_option_defaults_on_and_translation_matches(self):
        self.assertTrue(self.manager._refresh_picture_settings)
        root = Path(__file__).parents[1] / "custom_components" / "sony_adcp"
        strings = json.loads((root / "strings.json").read_text())
        english = json.loads((root / "translations" / "en.json").read_text())
        self.assertEqual(strings, english)
        self.assertIn("refresh_picture_settings", strings["options"]["step"]["refresh"]["data"])
