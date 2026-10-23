"""Protocol-aware writes and readback without a Home Assistant installation."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_power_transition import FakeHass
from test_protocol import AdcpClient, ProjectorManager, ProjectorState, _protocol

from custom_components.sony_adcp.command_request import CommandValidationError, validate_request


def request(command="contrast", operation="set", **kwargs):
    if operation in {"set", "relative"}:
        kwargs.setdefault("value", 50)
    return validate_request({"command": command, "operation": operation, **kwargs})


def info(command="contrast", kind="menu_num", **kwargs):
    return _protocol.CommandInfo(command, kind, **kwargs)


class CommandEncodingTest(unittest.TestCase):
    def test_official_sony_operations(self):
        for cmd, operation, value, metadata, expected in (
            ("color_temp", "set", "6500K", info("color_temp", "menu_sel", choices=("6500K",)),
             'color_temp "6500K"'),
            ("contrast", "set", 50, info(), "contrast 50"),
            ("contrast", "set", "50", info(), "contrast 50"),
            ("contrast", "relative", -1, info(minimum=0, maximum=100), "contrast --rel -1"),
            ("contrast", "reset", None, info(), "contrast --reset"),
            ("picture_mode_reset", "execute", None, info("picture_mode_reset", "menu_exec"),
             "picture_mode_reset"),
            ("key", "set", "menu", None, 'key "menu"'),
        ):
            with self.subTest(command=cmd, operation=operation):
                data = {"command": cmd, "operation": operation}
                if value is not None:
                    data["value"] = value
                self.assertEqual(validate_request(data).encode(metadata), expected)

    def test_power_and_explicit_power_keys_use_power_path(self):
        self.assertTrue(request("power", value="on").power)
        self.assertFalse(request("power", value="off").power)
        self.assertTrue(request("key", value="power_on").power)
        self.assertFalse(request("key", value="power_off").power)
        with self.assertRaises(CommandValidationError):
            request("key", value="power")

    def test_rejects_unsafe_or_malformed_requests(self):
        for data in (
            {"command": "contrast\r\npower"}, {"command": "contrast --reset"},
            {"command": "Color_temp"}, {"command": "contrast", "value": True},
            {"command": "contrast", "value": float("nan")},
            {"command": "contrast", "value": float("inf")},
            {"command": "contrast", "value": 10 ** 5000},
            {"command": "contrast", "value": [1, 2]},
            {"command": "color_temp", "value": '6500K"\r\npower "off'},
            {"command": "color_temp", "value": "café"},
            {"command": "color_temp", "value": "a\\b"},
            {"command": "contrast", "operation": "reset", "value": ""},
            {"command": "contrast", "operation": "relative", "value": "1 --reset"},
            {"command": "power", "operation": "execute"},
        ):
            with self.subTest(command=data["command"]), self.assertRaises(CommandValidationError):
                validate_request(data)

    def test_type_range_step_and_case_validation(self):
        for req, metadata in (
            (request(value=101), info(minimum=0, maximum=100)),
            (request(value=1.5), info(minimum=0, maximum=100, step=1)),
            (request(value="1e999999999"), info()),
            (request("color_temp", value="6500k"),
             info("color_temp", "menu_sel", choices=("6500K",))),
            (request("color_temp", "relative", value=1), info("color_temp", "menu_sel")),
            (request("picture_mode_reset", value=1), info("picture_mode_reset", "menu_exec")),
            (request("contrast", "execute"), info()),
            (request("ipv4_ip_address", value="192.0.2.1"), info("ipv4_ip_address", "sys_var")),
            (request(), None),
        ):
            with self.subTest(req=req), self.assertRaises(CommandValidationError):
                req.encode(metadata)
        self.assertEqual(request(value="2.5").encode(info(step=0.5)), "contrast 2.5")


class CommandActionManagerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = SimpleNamespace(
            async_get_command_info=AsyncMock(return_value=info()),
            async_command=AsyncMock(side_effect=lambda cmd, **kw: "49" if "?" in cmd else "ok"),
            async_set_power=AsyncMock(), async_close=AsyncMock(),
        )
        self.auth = []
        self.manager = ProjectorManager(
            self.hass, self.client, lambda: self.auth.append(True), lambda host: None, 0
        )
        self.manager.state = ProjectorState(power_status="on", available=True)

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def test_write_once_and_shared_immediate_readback(self):
        self.manager.async_track_custom_command("contrast")
        result = await self.manager.async_send_command(request(operation="relative", value=-1))
        self.assertEqual(result, {"response": "ok", "readback": "updated", "value": "49"})
        self.assertEqual(self.manager.state.values["contrast"], "49")
        self.assertEqual(self.manager.custom_results["contrast"].response, "49")
        self.assertEqual(self.client.async_command.call_args_list[0].args, ("contrast --rel -1",))
        self.assertFalse(self.client.async_command.call_args_list[0].kwargs["retry"])
        self.assertEqual(self.client.async_command.call_args_list[1].args, ("contrast ?",))
        await self.manager.async_send_command(request(value=50))
        self.client.async_get_command_info.assert_awaited_once()

    async def test_execute_and_keys_do_not_query_nonexistent_values(self):
        self.client.async_get_command_info.return_value = info("picture_mode_reset", "menu_exec")
        for req in (request("picture_mode_reset", "execute"), request("key", value="menu")):
            result = await self.manager.async_send_command(req)
            self.assertEqual(result["readback"], "not_supported")
        self.assertEqual(self.client.async_command.await_count, 2)

    async def test_unknown_metadata_never_sends_write(self):
        self.client.async_get_command_info.return_value = None
        with self.assertRaises(CommandValidationError):
            await self.manager.async_send_command(request())
        self.client.async_command.assert_not_awaited()

    async def test_authentication_starts_reauth(self):
        self.client.async_get_command_info.side_effect = _protocol.AdcpAuthenticationError()
        with self.assertRaises(_protocol.AdcpAuthenticationError):
            await self.manager.async_send_command(request())
        self.assertEqual(self.auth, [True])

    async def test_readback_failure_does_not_turn_ack_into_write_failure(self):
        self.manager.async_track_refresh_command("contrast")
        async def exchange(command, **kwargs):
            if "?" in command:
                raise _protocol.AdcpConnectionError()
            return "ok"
        self.client.async_command.side_effect = exchange
        result = await self.manager.async_send_command(request())
        self.assertEqual(result, {"response": "ok", "readback": "failed"})

    async def test_disabled_or_missing_entity_does_not_add_readback(self):
        result = await self.manager.async_send_command(request())
        self.assertEqual(result, {"response": "ok", "readback": "not_configured"})
        self.client.async_command.assert_awaited_once_with("contrast 50", retry=False)

    async def test_transition_started_while_queued_does_not_even_probe_metadata(self):
        await self.manager._operational_refresh_lock.acquire()
        task = asyncio.create_task(self.manager.async_send_command(request()))
        await asyncio.sleep(0)
        self.manager._power_transition_target = "off"
        self.manager._operational_refresh_lock.release()
        with self.assertRaises(CommandValidationError):
            await task
        self.client.async_get_command_info.assert_not_awaited()
        self.client.async_command.assert_not_awaited()

    async def test_power_uses_existing_monitor_not_generic_command(self):
        self.manager._async_set_power = AsyncMock()
        result = await self.manager.async_send_command(request("key", value="power_off"))
        self.manager._async_set_power.assert_awaited_once_with(False)
        self.assertEqual(result["readback"], "power_monitor")
        self.client.async_command.assert_not_awaited()

    async def test_stale_metadata_and_transitions_block_writes(self):
        self.manager._power_transition_target = "off"
        with self.assertRaises(CommandValidationError):
            await self.manager.async_send_command(request())
        self.manager._power_transition_target = None
        async def metadata(_):
            self.manager._apply_power_status("standby")
            return info()
        self.client.async_get_command_info.side_effect = metadata
        with self.assertRaises(CommandValidationError):
            await self.manager.async_send_command(request())
        self.client.async_command.assert_not_awaited()

    async def test_unload_cancels_active_actions(self):
        started = asyncio.Event()
        async def blocked_metadata(_):
            started.set()
            await asyncio.Event().wait()
        self.client.async_get_command_info.side_effect = blocked_metadata
        task = asyncio.create_task(self.manager.async_send_command(request()))
        await started.wait()
        await self.manager.async_close()
        self.assertTrue(task.cancelled())
        self.client.async_command.assert_not_awaited()


class WriteTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_preserves_case_step_and_nonreplayed_builtin_writes(self):
        client = AdcpClient("192.0.2.1", 53595, None)
        client.async_command = AsyncMock(return_value='{"type":"menu_sel","range":["6500K"]}')
        metadata = await client.async_get_command_info("color_temp")
        self.assertEqual(metadata.choices, ("6500K",))
        client.async_command.return_value = (
            '{"type":"menu_num","range":{"min":0,"max":100,"step":1}}'
        )
        metadata = await client.async_get_command_info("contrast")
        self.assertEqual(metadata.step, 1)
        client.async_command.return_value = "ok"
        await client.async_set_power(False)
        client.async_command.assert_awaited_with('power "off"', retry=False)
        await client.async_set_input("hdmi1")
        client.async_command.assert_awaited_with('input "hdmi1"', retry=False)

    async def test_lost_reply_is_not_replayed_but_queries_still_retry(self):
        commands = []
        async def handle(reader, writer):
            writer.write(b"NOKEY\r\n")
            await writer.drain()
            commands.append(await reader.readuntil(b"\r\n"))
            writer.close()  # The projector executed it; its acknowledgement was lost.
            await writer.wait_closed()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        client = AdcpClient("127.0.0.1", server.sockets[0].getsockname()[1], None)
        try:
            with self.assertRaises(_protocol.AdcpOutcomeUnknownError):
                await client.async_command("contrast --rel -1", retry=False)
            self.assertEqual(len(commands), 1)
            with self.assertRaises(_protocol.AdcpConnectionError):
                await client.async_command("contrast ?")
            self.assertEqual(len(commands), 3)
        finally:
            await client.async_close()
            server.close()
            await server.wait_closed()

    async def test_frame_boundaries_and_control_characters(self):
        client = AdcpClient("192.0.2.1", 53595, None)
        client._async_ensure_connected = AsyncMock(side_effect=_protocol.AdcpConnectionError())
        for payload in ("a" * 511, "contrast\npower", "contrast\r", "contrast\t", "", "é"):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError):
                await client.async_command(payload, retry=False)
        client._async_ensure_connected.assert_not_awaited()
        with self.assertRaises(_protocol.AdcpConnectionError):
            await client.async_command("a" * 510, retry=False)
        client._async_ensure_connected.assert_awaited_once()
