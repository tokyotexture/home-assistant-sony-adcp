"""Read-only custom sensor validation and shared refresh regression tests."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from test_picture_refresh import PictureClient
from test_power_transition import FakeHass
from test_protocol import ProjectorManager, ProjectorState, _manager, _protocol

from custom_components.sony_adcp.custom_commands import (
    CustomCommandResult,
    CustomSensorValidationError,
    parse_sensor_value,
    validate_sensor_config,
)


def config(**changes):
    return validate_sensor_config({"name": "Aspect ratio", "command": "aspect", **changes})


class CustomValueTest(unittest.TestCase):
    def test_named_query_configuration(self):
        self.assertEqual(config()["command"], "aspect")
        self.assertEqual(config(name="  Aspect  ")["name"], "Aspect")
        self.assertEqual(config(value_type="number", unit=" % ")["unit"], "%")

    def test_rejects_arguments_injection_and_non_ascii(self):
        for command in (
            "", "aspect ?", "aspect;power", 'power "on"', "power\roff",
            "aspect\n", "aspect\t", " aspect", "Aspect", "аspect", "a" * 65,
        ):
            with self.subTest(command=command), self.assertRaises(CustomSensorValidationError):
                config(command=command)

    def test_field_specific_errors(self):
        for changes, field in (
            ({"name": " "}, "name"), ({"name": "x" * 101}, "name"),
            ({"value_type": "template"}, "value_type"),
            ({"unit": "%"}, "unit"),
            ({"json_field": "[0].main"}, "json_field"),
            ({"json_field": "a..b"}, "json_field"),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(CustomSensorValidationError) as error:
                    config(**changes)
                self.assertEqual(error.exception.field, field)

    def test_text_and_numbers_including_zero(self):
        self.assertEqual(parse_sensor_value("normal", config()), "normal")
        self.assertEqual(parse_sensor_value("0", config(value_type="number")), 0)
        self.assertEqual(parse_sensor_value("-2.5", config(value_type="number")), -2.5)

    def test_json_objects_arrays_and_boolean_text(self):
        self.assertEqual(parse_sensor_value(
            '[{"main":12}]', config(value_type="number", json_field="0.main")
        ), 12)
        self.assertEqual(parse_sensor_value(
            '{"status":{"active":true}}', config(json_field="status.active")
        ), "true")

    def test_invalid_responses_never_invent_values(self):
        for response, options in (
            ("NaN", {"value_type": "number"}), ("Infinity", {"value_type": "number"}),
            ("", {"value_type": "number"}), ("1e999", {"value_type": "number"}),
            ('{"n":true}', {"value_type": "number", "json_field": "n"}),
            ('{"n":null}', {"json_field": "n"}),
            ('{"n":{}}', {"json_field": "n"}),
            ("[]", {"json_field": "0.main"}),
            ('["last"]', {"json_field": "-1"}),
            ('["last"]', {"json_field": "main"}),
            ("not json", {"json_field": "main"}),
            ("[" * 1100 + "0" + "]" * 1100, {"json_field": "0"}),
            ("x" * 256, {}),
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_sensor_value(response, config(**options))


class CustomRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = PictureClient()
        self.client.responses.update({"aspect ?": "normal", "gamma ?": "2.4"})
        self.auth = []
        self.manager = ProjectorManager(self.hass, self.client, lambda: self.auth.append(True),
                                        lambda host: None, 0)
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.notifications = []
        self.manager.async_add_listener(lambda: self.notifications.append(True))

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def refresh(self):
        await self.manager._async_refresh_operational()

    async def test_enabled_commands_follow_input_signal_and_picture_controls(self):
        self.manager.async_track_refresh_command("sharpness")
        self.manager.state = ProjectorState(power_status="on", available=True,
                                           values={"sharpness": "20"})
        self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.assertEqual(self.client.commands, [
            "input ?", "signal ?", "sharpness ?", "aspect ?",
        ])
        self.assertEqual(self.manager.custom_results["aspect"].response, "normal")

    async def test_picture_option_does_not_disable_custom_sensors(self):
        self.manager.async_set_refresh_picture_settings(False)
        self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.assertIn("aspect ?", self.client.commands)

    async def test_no_registration_means_no_custom_queries(self):
        await self.refresh()
        self.assertEqual(self.client.commands, ["input ?", "signal ?"])

    async def test_builtin_reads_reused_in_same_cycle(self):
        self.manager.async_track_custom_command("input")
        self.manager.async_track_custom_command("sharpness")
        self.manager.async_track_refresh_command("sharpness")
        self.manager.state = ProjectorState(power_status="on", available=True,
                                           values={"sharpness": "20"})
        await self.refresh()
        self.assertEqual(self.client.commands.count("input ?"), 1)
        self.assertEqual(self.client.commands.count("sharpness ?"), 1)
        self.assertEqual(self.manager.custom_results["input"].response, "hdmi2")

    async def test_auth_failure_in_builtin_read_stops_custom_queries(self):
        self.manager.async_track_custom_command("aspect")
        self.client.responses["signal ?"] = _protocol.AdcpAuthenticationError("secret")
        await self.refresh()
        self.assertEqual(self.auth, [True])
        self.assertNotIn("aspect ?", self.client.commands)
        self.assertEqual(self.manager.custom_results["aspect"].error, "authentication")

    async def test_duplicate_commands_share_one_read_and_last_removal_cleans_cache(self):
        first = self.manager.async_track_custom_command("aspect")
        second = self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.assertEqual(self.client.commands.count("aspect ?"), 1)
        first()
        first()
        await self.refresh()
        self.assertEqual(self.client.commands.count("aspect ?"), 2)
        second()
        await self.refresh()
        self.assertEqual(self.client.commands.count("aspect ?"), 2)
        self.assertNotIn("aspect", self.manager.custom_results)

    async def test_registration_also_enforces_read_only_syntax(self):
        with self.assertRaises(ValueError):
            self.manager.async_track_custom_command('power "on"')

    async def test_error_isolated_and_backs_off_then_recovers(self):
        self.manager.async_track_custom_command("aspect")
        self.manager.async_track_custom_command("gamma")
        self.client.responses["aspect ?"] = _protocol.AdcpCommandError("aspect ?", "err_cmd")
        await self.refresh()
        self.assertTrue(self.manager.state.available)
        self.assertEqual(self.manager.custom_results["aspect"].error, "query_failed")
        self.assertEqual(self.manager.custom_results["gamma"].response, "2.4")
        await self.refresh()
        self.assertEqual(self.client.commands.count("aspect ?"), 1)
        self.client.responses["aspect ?"] = "zoom"
        self.manager._custom_retry_after["aspect"] = 0
        await self.refresh()
        self.assertEqual(self.manager.custom_results["aspect"].response, "zoom")

    async def test_failed_read_replaces_stale_success_with_error(self):
        self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.client.responses["aspect ?"] = _protocol.AdcpConnectionError("offline")
        await self.refresh()
        self.assertIsNone(self.manager.custom_results["aspect"].response)

    async def test_budget_rotation_and_backoff_prevent_starvation(self):
        self.manager.async_track_custom_command("aspect")
        self.manager.async_track_custom_command("gamma")
        self.client.block_command = "aspect ?"
        with patch.object(_manager, "CUSTOM_REFRESH_BUDGET", 0.01):
            await self.refresh()
        self.assertTrue(self.client.cancelled)
        self.assertEqual(self.manager.custom_results["aspect"].error, "timeout")
        self.assertTrue(self.manager.state.available)
        await self.refresh()
        self.assertEqual(self.manager.custom_results["gamma"].response, "2.4")
        self.assertEqual(self.client.commands.count("aspect ?"), 1)

    async def test_authentication_requests_reauth_and_stops_batch(self):
        self.manager.async_track_custom_command("aspect")
        self.manager.async_track_custom_command("gamma")
        self.client.responses["aspect ?"] = _protocol.AdcpAuthenticationError("secret")
        await self.refresh()
        self.assertEqual(self.auth, [True])
        self.assertNotIn("gamma ?", self.client.commands)
        self.assertEqual(self.manager.custom_results["aspect"].error, "authentication")

    async def test_not_on_or_transitioning_never_reads(self):
        self.manager.async_track_custom_command("aspect")
        for power in ("standby", "saving_standby", "startup", "cooling1", "cooling2"):
            self.manager.state = ProjectorState(power_status=power, available=True)
            await self.refresh()
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.manager._power_transition_target = "off"
        await self.refresh()
        self.assertEqual(self.client.commands, [])

    async def test_power_change_invalidates_cached_values_and_backoff(self):
        self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.manager._custom_retry_after["aspect"] = float("inf")
        self.manager._apply_power_status("standby")
        self.manager._apply_power_status("on")
        self.assertEqual(self.manager.custom_results, {})
        await self.refresh()
        self.assertEqual(self.client.commands.count("aspect ?"), 2)

    async def pending_read(self):
        self.manager.async_track_custom_command("aspect")
        self.client.block_command = "aspect ?"
        task = asyncio.create_task(self.refresh())
        self.addAsyncCleanup(self.cancel, task)
        await asyncio.wait_for(self.client.started.wait(), 0.5)
        return task

    @staticmethod
    async def cancel(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_power_change_discards_in_flight_response(self):
        task = await self.pending_read()
        self.manager._apply_power_status("standby")
        self.client.release.set()
        await task
        self.assertNotIn("aspect", self.manager.custom_results)

    async def test_power_change_discards_in_flight_error(self):
        self.client.responses["aspect ?"] = _protocol.AdcpConnectionError("old connection")
        task = await self.pending_read()
        self.manager._apply_power_status("standby")
        self.client.release.set()
        await task
        self.assertNotIn("aspect", self.manager.custom_results)
        self.assertNotIn("aspect", self.manager._custom_retry_after)

    async def test_removed_sensor_discards_in_flight_response(self):
        remove = self.manager.async_track_custom_command("aspect")
        self.client.block_command = "aspect ?"
        task = asyncio.create_task(self.refresh())
        self.addAsyncCleanup(self.cancel, task)
        await self.client.started.wait()
        remove()
        self.client.release.set()
        await task
        self.assertNotIn("aspect", self.manager.custom_results)

    async def test_unload_cancels_owned_refresh_and_stops_new_queries(self):
        self.manager.async_set_operational_refresh_interval(0.001)
        self.manager.async_track_custom_command("aspect")
        self.client.block_command = "aspect ?"
        await asyncio.wait_for(self.client.started.wait(), 0.5)
        await self.manager.async_close()
        self.assertTrue(self.client.cancelled)
        count = len(self.client.commands)
        await self.refresh()
        self.assertEqual(len(self.client.commands), count)

    async def test_disabling_interval_cancels_custom_read(self):
        self.manager.async_track_custom_command("aspect")
        self.client.block_command = "aspect ?"
        self.manager.async_set_operational_refresh_interval(0.001)
        await asyncio.wait_for(self.client.started.wait(), 0.5)
        task = self.manager._operational_refresh_task
        self.manager.async_set_operational_refresh_interval(0)
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(self.client.cancelled)
        self.assertNotIn("aspect", self.manager.custom_results)

    async def test_unchanged_response_does_not_write_state_again(self):
        self.manager.async_track_custom_command("aspect")
        await self.refresh()
        self.notifications.clear()
        await self.refresh()
        self.assertEqual(self.notifications, [])

    async def test_cached_result_is_plain_data(self):
        self.assertEqual(CustomCommandResult(response="zero").response, "zero")
