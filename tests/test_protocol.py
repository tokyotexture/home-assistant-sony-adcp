"""Offline tests for ADCP and SDAP."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
import unittest
from enum import StrEnum
from pathlib import Path
from types import ModuleType

# Load dependency-free modules without installing Home Assistant.
_ROOT = Path(__file__).parents[1] / "custom_components" / "sony_adcp"
sys.modules["custom_components"] = ModuleType("custom_components")
_PACKAGE = ModuleType("custom_components.sony_adcp")
_PACKAGE.__path__ = [str(_ROOT)]
sys.modules["custom_components.sony_adcp"] = _PACKAGE
_HOMEASSISTANT = ModuleType("homeassistant")
_HA_CONST = ModuleType("homeassistant.const")


class _Platform(StrEnum):
    MEDIA_PLAYER = "media_player"
    SENSOR = "sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"


_HA_CONST.Platform = _Platform
sys.modules["homeassistant"] = _HOMEASSISTANT
sys.modules["homeassistant.const"] = _HA_CONST
_HA_CORE = ModuleType("homeassistant.core")
_HA_CORE.callback = lambda function: function
_HA_CORE.HomeAssistant = object
sys.modules["homeassistant.core"] = _HA_CORE


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"custom_components.sony_adcp.{name}", _ROOT / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_const = _load("const")
_protocol = _load("protocol")
_discovery = _load("discovery")
_manager = _load("manager")

AdcpAuthenticationError = _protocol.AdcpAuthenticationError
AdcpClient = _protocol.AdcpClient
AuthenticationMode = _protocol.AuthenticationMode
async_probe_authentication = _protocol.async_probe_authentication
normalize_response = _protocol.normalize_response
parse_sdap_packet = _discovery.parse_sdap_packet
SdapListener = _discovery.SdapListener
ProjectorManager = _manager.ProjectorManager
ProjectorState = _manager.ProjectorState


class ProtocolHelpersTest(unittest.TestCase):
    def test_discovery_window_covers_default_sdap_interval(self) -> None:
        self.assertGreater(_const.DISCOVERY_TIMEOUT, 30)

    def test_normalize_response(self) -> None:
        self.assertEqual(normalize_response(b'"standby"\r\n'), "standby")
        self.assertEqual(normalize_response(b'{"type":"sys_stat"}\r\n'), '{"type":"sys_stat"}')

    def test_binary_sdap_packet(self) -> None:
        payload = (
            b"DA"
            + bytes((1, 0x0A))
            + b"SONY"
            + b"VPL-VW535\0\0\0"
            + (1234).to_bytes(4, "big")
            + (3).to_bytes(2, "big")
            + b"Cinema\0"
            + bytes(17)
        )
        projector = parse_sdap_packet(payload, "192.0.2.10")
        assert projector is not None
        self.assertEqual(projector.model, "VPL-VW535")
        self.assertEqual(projector.serial, "1234")
        self.assertEqual(projector.raw_power_status, 3)
        self.assertEqual(projector.location, "Cinema")

    def test_rejects_non_projector_sdap_packet(self) -> None:
        payload = b"DA" + bytes((1, 1)) + bytes(46)
        self.assertIsNone(parse_sdap_packet(payload, "192.0.2.10"))

    def test_serial_subscription_survives_address_change(self) -> None:
        listener = SdapListener()
        received = []
        unsubscribe = listener.async_subscribe(
            "192.0.2.10", "001234", received.append
        )
        listener.async_process(
            _discovery.DiscoveredProjector(
                host="192.0.2.10", serial="001234", model="VPL-VW535"
            )
        )
        received.clear()
        packet = _discovery.DiscoveredProjector(
            host="192.0.2.99", serial="1234", model="VPL-VW535"
        )
        listener.async_process(packet)
        self.assertEqual(received, [packet])
        self.assertNotIn("192.0.2.10", listener.devices)
        self.assertIn("192.0.2.99", listener.devices)
        unsubscribe()
        listener.async_process(packet)
        self.assertEqual(received, [packet])


class AdcpClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.commands: list[str] = []
        self.password = "secret"

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                challenge = "challenge"
                writer.write(f"{challenge}\r\n".encode())
                await writer.drain()
                digest = (await reader.readline()).decode().strip()
                expected = hashlib.sha256(
                    (challenge + self.password).encode()
                ).hexdigest()
                writer.write(b"OK\r\n" if digest == expected else b"err_auth\r\n")
                await writer.drain()
                if digest != expected:
                    return
                while command := await reader.readline():
                    text = command.decode().strip()
                    self.commands.append(text)
                    responses = {
                        "power_status ?": '"on"',
                        "input ?": '"hdmi2"',
                        'power "off"': "ok",
                        "input --info": (
                            '{"type":"menu_sel","version":"1.0",'
                            '"range":["hdmi1","hdmi2"]}'
                        ),
                    }
                    writer.write(f"{responses[text]}\r\n".encode())
                    await writer.drain()
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def test_authenticated_commands_and_capabilities(self) -> None:
        client = AdcpClient("127.0.0.1", self.port, self.password)
        self.assertEqual(await client.async_get_power(), "on")
        self.assertEqual(await client.async_get_input(), "hdmi2")
        info = await client.async_get_command_info("input")
        assert info is not None
        self.assertEqual(info.command_type, "menu_sel")
        self.assertEqual(info.choices, ("hdmi1", "hdmi2"))
        await client.async_set_power(False)
        await client.async_close()

    async def test_invalid_password(self) -> None:
        client = AdcpClient("127.0.0.1", self.port, "wrong")
        with self.assertRaises(AdcpAuthenticationError):
            await client.async_get_power()

    async def test_host_can_change_without_recreating_client(self) -> None:
        client = AdcpClient("127.0.0.1", self.port, self.password)
        self.assertEqual(await client.async_get_power(), "on")
        await client.async_set_host("127.0.0.2")
        self.assertEqual(client.host, "127.0.0.2")
        self.assertIsNone(client._reader)
        self.assertIsNone(client._writer)


class AuthenticationProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_detects_no_authentication(self) -> None:
        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            writer.write(b"NOKEY\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            mode = await async_probe_authentication("127.0.0.1", port)
        finally:
            server.close()
            await server.wait_closed()
        self.assertEqual(mode, AuthenticationMode.NONE)


class OperationalRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_standby_clears_input_and_signal_without_querying_them(self) -> None:
        class FakeClient:
            async def async_get_power(self) -> str:
                return "standby"

            async def async_command(self, command: str) -> str:
                raise AssertionError(f"Unexpected command: {command}")

        manager = ProjectorManager(
            hass=None,
            client=FakeClient(),
            auth_failed=lambda: None,
            host_changed=lambda host: None,
            operational_refresh_interval=10,
        )
        manager.state = ProjectorState(
            power_status="on",
            source="hdmi1",
            signal="1920x1080_60p",
            available=True,
        )

        await manager.async_refresh()

        self.assertEqual(manager.state.power_status, "standby")
        self.assertIsNone(manager.state.source)
        self.assertIsNone(manager.state.signal)

    async def test_refresh_queries_only_input_and_signal(self) -> None:
        class FakeClient:
            host = "192.0.2.10"

            def __init__(self) -> None:
                self.commands: list[str] = []

            async def async_command(self, command: str) -> str:
                self.commands.append(command)
                return {"input ?": "hdmi2", "signal ?": "3840x2160_60p"}[command]

        client = FakeClient()
        manager = ProjectorManager(
            hass=None,
            client=client,
            auth_failed=lambda: None,
            host_changed=lambda host: None,
            operational_refresh_interval=10,
        )
        manager.state = ProjectorState(
            power_status="on",
            source="hdmi1",
            signal="1920x1080_60p",
            available=True,
        )

        await manager._async_refresh_operational()

        self.assertEqual(client.commands, ["input ?", "signal ?"])
        self.assertEqual(manager.state.source, "hdmi2")
        self.assertEqual(manager.state.signal, "3840x2160_60p")

    async def test_disabled_interval_stops_running_task(self) -> None:
        class FakeHass:
            @staticmethod
            def async_create_task(coroutine, name):
                return asyncio.create_task(coroutine, name=name)

        manager = ProjectorManager(
            hass=FakeHass(),
            client=None,
            auth_failed=lambda: None,
            host_changed=lambda host: None,
            operational_refresh_interval=10,
        )
        manager.state = ProjectorState(power_status="on", available=True)
        manager._update_operational_refresh_task()
        self.assertIsNotNone(manager._operational_refresh_task)

        manager.async_set_operational_refresh_interval(0)
        await asyncio.sleep(0)

        self.assertIsNone(manager._operational_refresh_task)


if __name__ == "__main__":
    unittest.main()
