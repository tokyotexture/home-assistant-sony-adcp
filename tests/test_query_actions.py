"""Read-only queries stay distinct from custom writes and periodic sensors."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_power_transition import FakeHass
from test_protocol import ProjectorManager, ProjectorState, _protocol

from custom_components.sony_adcp.command_request import (
    CommandValidationError,
    validate_query_request,
)


def query(command="aspect", query_type="value"):
    return validate_query_request({"command": command, "query_type": query_type})


class QueryEncodingTest(unittest.TestCase):
    def test_only_generated_read_only_suffixes(self):
        self.assertEqual(query().frames, ("aspect ?",))
        self.assertEqual(query(query_type="range").frames,
                         ("aspect --range", "aspect ? --range"))
        self.assertEqual(query(query_type="info").frames,
                         ("aspect --info", "aspect ? --info"))
        self.assertEqual(validate_query_request({"command": "aspect"}), query())

    def test_no_raw_arguments_options_values_or_write_operations(self):
        for data in (
            {"command": "aspect ?"}, {"command": "aspect --reset"},
            {"command": "aspect\r\npower"}, {"command": "Aspect"},
            {"command": "aspect", "query_type": "execute"},
            {"command": "aspect", "value": "normal"},
            {"command": "aspect", "operation": "execute"},
            {"command": "aspect", "query_type": ["value"]},
        ):
            with self.subTest(data=data), self.assertRaises(CommandValidationError):
                validate_query_request(data)


class QueryManagerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = SimpleNamespace(
            async_get_command_info=AsyncMock(),
            async_command=AsyncMock(return_value="normal"), async_close=AsyncMock(),
        )
        self.auth = []
        self.manager = ProjectorManager(
            self.hass, self.client, lambda: self.auth.append(True), lambda host: None, 0
        )
        self.manager.state = ProjectorState(power_status="on", available=True)

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def test_aspect_is_fresh_and_needs_no_metadata_or_sensor(self):
        self.assertEqual(await self.manager.async_query_command(query()), {
            "command": "aspect", "query_type": "value", "response": "normal", "data": "normal"
        })
        self.client.async_command.assert_awaited_once_with("aspect ?")
        self.client.async_get_command_info.assert_not_awaited()
        self.client.async_command.return_value = "zoom"
        self.assertEqual((await self.manager.async_query_command(query()))["data"], "zoom")
        self.assertEqual(self.manager.state.values, {})
        self.assertEqual(self.manager.custom_results, {})
        self.assertEqual(self.manager._custom_commands, {})
        self.assertIsNone(self.manager._operational_refresh_task)

    async def test_metadata_fallback_on_format_rejection(self):
        for kind in ("range", "info"):
            for error in ("err_cmd", "err_option"):
                self.client.async_command.reset_mock()
                self.client.async_command.side_effect = [
                    _protocol.AdcpCommandError(f"aspect --{kind}", error),
                    '["normal","zoom"]',
                ]
                result = await self.manager.async_query_command(query(query_type=kind))
                self.assertEqual(result["data"], ["normal", "zoom"])
                frames = [call.args[0] for call in self.client.async_command.call_args_list]
                self.assertEqual(frames, [f"aspect --{kind}", f"aspect ? --{kind}"])

    async def test_structured_json_only_and_original_normalized_response(self):
        for reply, expected in (
            ('{"min":0,"max":100}', {"min": 0, "max": 100}),
            ('["d65","d93"]', ["d65", "d93"]),
            ("2.4", "2.4"), ("on", "on"), ("{broken", "{broken"),
        ):
            self.client.async_command.return_value = reply
            result = await self.manager.async_query_command(query())
            self.assertEqual(result["response"], reply)
            self.assertEqual(result["data"], expected)

    async def test_no_syntax_fallback_for_inactive_auth_or_connection(self):
        for error in (
            _protocol.AdcpCommandError("aspect --info", "err_inactive"),
            _protocol.AdcpAuthenticationError(), _protocol.AdcpConnectionError(),
        ):
            self.client.async_command.reset_mock()
            self.client.async_command.side_effect = error
            with self.assertRaises(type(error)):
                await self.manager.async_query_command(query(query_type="info"))
            self.assertEqual(self.client.async_command.await_count, 1)
        self.assertEqual(self.auth, [True])

    async def test_value_rejection_never_tries_a_bare_execution(self):
        self.client.async_command.side_effect = _protocol.AdcpCommandError("aspect ?", "err_cmd")
        with self.assertRaises(_protocol.AdcpCommandError):
            await self.manager.async_query_command(query())
        self.client.async_command.assert_awaited_once_with("aspect ?")

    async def test_transition_and_unload_reject_without_io(self):
        self.manager._power_transition_target = "off"
        with self.assertRaises(CommandValidationError):
            await self.manager.async_query_command(query())
        self.manager._power_transition_target = None
        self.manager._closed = True
        with self.assertRaises(CommandValidationError):
            await self.manager.async_query_command(query())
        self.client.async_command.assert_not_awaited()

    async def test_rechecks_after_queue_wait(self):
        await self.manager._operational_refresh_lock.acquire()
        task = asyncio.create_task(self.manager.async_query_command(query()))
        await asyncio.sleep(0)
        self.manager._power_transition_target = "on"
        self.manager._operational_refresh_lock.release()
        with self.assertRaises(CommandValidationError):
            await task
        self.client.async_command.assert_not_awaited()

    async def test_changed_power_discards_reply_and_stops_fallback(self):
        async def changed(frame):
            self.manager._power_revision += 1
            raise _protocol.AdcpCommandError(frame, "err_cmd")
        self.client.async_command.side_effect = changed
        with self.assertRaisesRegex(CommandValidationError, "query_stale"):
            await self.manager.async_query_command(query(query_type="info"))
        self.assertEqual(self.client.async_command.await_count, 1)
        async def reply(frame):
            self.manager._power_revision += 1
            return "normal"
        self.client.async_command.side_effect = reply
        with self.assertRaisesRegex(CommandValidationError, "query_stale"):
            await self.manager.async_query_command(query())

    async def test_unload_cancels_inflight_query(self):
        started = asyncio.Event()
        async def slow(frame):
            started.set()
            await asyncio.Event().wait()
        self.client.async_command.side_effect = slow
        task = asyncio.create_task(self.manager.async_query_command(query()))
        await started.wait()
        await self.manager.async_close()
        self.assertTrue(task.cancelled())
        self.assertFalse(self.manager._command_action_tasks)
