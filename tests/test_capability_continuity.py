"""Capability caching, deferred discovery and live-value lifecycle regressions."""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
from collections import deque
from unittest.mock import AsyncMock, patch

from test_power_transition import FakeHass
from test_protocol import ProjectorManager, ProjectorState, _load, _manager, _protocol

_cache = _load("capabilities")
IDENTITY = _protocol.ProjectorIdentity("VPL-VW535", "1234", "00:11:22:33:44:55", "5.003")
BRIGHTNESS = _protocol.CommandInfo("brightness", "menu_num", minimum=0, maximum=100, step=1)


class CacheTest(unittest.TestCase):
    def test_json_roundtrip_is_metadata_only(self):
        payload = json.loads(json.dumps(_cache.encode_capabilities(IDENTITY, {
            "brightness": BRIGHTNESS,
            "picture_mode": _protocol.CommandInfo("picture_mode", "menu_sel", ("game", "cinema")),
        })))
        restored = _cache.decode_capabilities(payload, IDENTITY)
        self.assertEqual(restored["brightness"], BRIGHTNESS)
        self.assertEqual(restored["picture_mode"].choices, ("game", "cinema"))
        self.assertNotIn("values", payload)
        self.assertNotIn("firmware", payload["identity"])

    def test_different_identity_does_not_inherit_capabilities(self):
        payload = _cache.encode_capabilities(IDENTITY, {"brightness": BRIGHTNESS})
        for identity in (
            _protocol.ProjectorIdentity("another model", "1234"),
            _protocol.ProjectorIdentity("VPL-VW535", "9999"),
            _protocol.ProjectorIdentity(mac_address="66:77:88:99:aa:bb"),
        ):
            with self.subTest(identity=identity):
                self.assertEqual(_cache.decode_capabilities(payload, identity), {})

    def test_normalized_serial_and_mac_match_and_dhcp_is_not_part_of_identity(self):
        payload = _cache.encode_capabilities(IDENTITY, {"brightness": BRIGHTNESS})
        identity = _protocol.ProjectorIdentity("vpl-vw535", "001234", "001122334455")
        self.assertEqual(_cache.decode_capabilities(payload, identity), {"brightness": BRIGHTNESS})

    def test_corrupt_or_incomplete_ranges_are_not_invented(self):
        payload = _cache.encode_capabilities(IDENTITY, {"brightness": BRIGHTNESS})
        for change in (
            {"minimum": None}, {"maximum": None}, {"minimum": True},
            {"minimum": float("nan")}, {"maximum": float("inf")},
            {"minimum": 200}, {"step": 0}, {"command": "contrast"},
            {"command_type": "menu_exec"}, {"choices": [5]},
        ):
            damaged = copy.deepcopy(payload)
            damaged["commands"]["brightness"].update(change)
            with self.subTest(change=change):
                self.assertEqual(_cache.decode_capabilities(damaged, IDENTITY), {})
        for damaged in (None, [], {}, {**payload, "version": 2}, {**payload, "identity": []}):
            self.assertEqual(_cache.decode_capabilities(damaged, IDENTITY), {})


class CapabilityClient:
    host = "192.0.2.1"

    def __init__(self):
        self.power = "standby"
        self.probes = []
        self.reads = []
        self.brightness_responses = deque([BRIGHTNESS])

    async def async_get_identity(self):
        return IDENTITY

    async def async_get_power(self):
        return self.power

    async def async_get_timer_hours(self):
        return {}

    async def async_get_json_list(self, command):
        return ()

    async def async_get_command_info(self, command):
        self.probes.append(command)
        if command != "brightness":
            return None
        result = self.brightness_responses.popleft()
        if isinstance(result, Exception):
            raise result
        return result

    async def async_command(self, command):
        self.reads.append(command)
        return {"input ?": "hdmi1", "signal ?": "1080p", "brightness ?": "49"}[command]

    async def async_close(self):
        pass


class ContinuityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = CapabilityClient()
        self.saved = []
        self.auth_failures = []
        self.managers = []
        self.manager = self.make_manager()

    def make_manager(self, cache=None):
        manager = ProjectorManager(
            self.hass, self.client, lambda: self.auth_failures.append(True), lambda host: None,
            operational_refresh_interval=0, refresh_picture_settings=False,
            cached_capabilities=cache, capabilities_changed=self.saved.append,
        )
        self.managers.append(manager)
        return manager

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def test_old_bug_would_probe_during_startup_and_never_retry(self):
        self.client.power = "startup"
        await self.manager.async_initialize()
        self.assertEqual(self.client.probes, [])
        self.assertFalse(self.manager._capabilities_probed)
        self.client.power = "on"
        await self.manager.async_refresh()
        self.assertEqual(self.manager.command_info["brightness"], BRIGHTNESS)
        self.assertTrue(self.manager._capabilities_probed)
        self.assertEqual(len(self.saved), 1)

    async def test_off_reload_restores_controls_but_not_live_values(self):
        self.client.power = "on"
        await self.manager.async_initialize()
        cache = json.loads(json.dumps(self.saved[-1]))
        await self.manager.async_close()
        self.client.power = "standby"
        self.client.probes.clear()
        self.client.reads.clear()
        restored = self.make_manager(cache)
        await restored.async_initialize()
        self.assertEqual(restored.command_info["brightness"], BRIGHTNESS)
        self.assertEqual(restored.state.values, {})
        self.assertEqual(self.client.probes, [])
        self.assertEqual(self.client.reads, [])

    async def test_temporary_failure_is_retried_on_watchdog_even_with_refresh_disabled(self):
        self.client.power = "on"
        self.client.brightness_responses = deque([
            _protocol.AdcpCommandError("brightness --info", "err_inactive"), BRIGHTNESS,
        ])
        await self.manager.async_initialize()
        self.assertNotIn("brightness", self.manager.command_info)
        self.assertFalse(self.manager._capabilities_probed)
        await self.manager.async_refresh()
        self.assertEqual(self.client.probes.count("brightness"), 1)
        self.manager._capability_retry_after = 0
        await self.manager.async_refresh()
        self.assertEqual(self.client.probes.count("brightness"), 2)
        self.assertEqual(self.manager.command_info["brightness"], BRIGHTNESS)
        self.assertTrue(self.manager._capabilities_probed)
        self.assertEqual(self.client.probes.count("input"), 1)

    async def test_cached_metadata_survives_temporary_failure(self):
        self.client.power = "on"
        self.client.brightness_responses = deque([_protocol.AdcpConnectionError("offline")])
        cache = _cache.encode_capabilities(IDENTITY, {"brightness": BRIGHTNESS})
        restored = self.make_manager(cache)
        await restored.async_initialize()
        self.assertEqual(restored.command_info["brightness"], BRIGHTNESS)
        self.assertEqual(self.saved, [])
        self.assertFalse(restored._capabilities_probed)

    async def test_on_readback_ignores_refresh_options_without_starting_another_loop(self):
        cache = _cache.encode_capabilities(IDENTITY, {"brightness": BRIGHTNESS})
        restored = self.make_manager(cache)
        await restored.async_initialize()
        restored.async_track_refresh_command("brightness")
        restored.state = ProjectorState(power_status="standby", available=True)
        self.client.power = "on"
        await restored.async_refresh()
        self.assertEqual(restored.state.values["brightness"], "49")
        self.assertIsNone(restored._operational_refresh_task)
        self.client.power = "standby"
        await restored.async_refresh()
        self.assertEqual(restored.state.values, {})
        self.assertIn("brightness", restored.command_info)

    async def test_power_change_mid_probe_discards_reply_and_keeps_it_pending(self):
        self.client.power = "on"
        self.manager.state = ProjectorState(power_status="on", available=True)
        original = self.client.async_get_command_info
        async def probe(command):
            value = await original(command)
            if command == "brightness":
                self.manager._apply_power_status("cooling1")
            return value
        self.client.async_get_command_info = probe
        await self.manager.async_probe_capabilities()
        self.assertNotIn("brightness", self.manager.command_info)
        self.assertIn("brightness", self.manager._capability_pending)
        self.assertFalse(self.manager._capabilities_probed)

    async def test_probe_deadline_preserves_progress_and_rotates_slow_command(self):
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.manager._capability_pending = dict.fromkeys(("brightness", "contrast"))
        async def probe(command):
            if command == "brightness":
                await asyncio.Event().wait()
            return None
        self.client.async_get_command_info = probe
        with patch.object(_manager, "CAPABILITY_PROBE_BUDGET", 0.01):
            await self.manager.async_probe_capabilities()
        self.assertEqual(tuple(self.manager._capability_pending), ("contrast", "brightness"))
        self.assertFalse(self.manager._capabilities_probed)


class MetadataFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_inactive_is_not_misclassified_as_unsupported(self):
        client = _protocol.AdcpClient("192.0.2.1", 53595, None)
        client.async_command = AsyncMock(
            side_effect=_protocol.AdcpCommandError("cmd", "err_inactive"),
        )
        with self.assertRaises(_protocol.AdcpCommandError):
            await client.async_get_command_info("brightness")
        self.assertEqual(client.async_command.await_count, 1)

    async def test_only_explicit_rejections_allow_syntax_fallback(self):
        client = _protocol.AdcpClient("192.0.2.1", 53595, None)
        client.async_command = AsyncMock(side_effect=[
            _protocol.AdcpCommandError("cmd", "err_option"),
            '{"type":"menu_num","range":{"min":0,"max":100}}',
        ])
        self.assertEqual((await client.async_get_command_info("brightness")).maximum, 100)
        client.async_command = AsyncMock(side_effect=_protocol.AdcpCommandError("cmd", "err_cmd"))
        self.assertIsNone(await client.async_get_command_info("brightness"))
        self.assertEqual(client.async_command.await_count, 2)

    async def test_malformed_metadata_is_retryable_not_negative_capability(self):
        client = _protocol.AdcpClient("192.0.2.1", 53595, None)
        for response in ("broken json", "[]", "null"):
            client.async_command = AsyncMock(return_value=response)
            with self.subTest(response=response), self.assertRaises(_protocol.AdcpError):
                await client.async_get_command_info("brightness")
