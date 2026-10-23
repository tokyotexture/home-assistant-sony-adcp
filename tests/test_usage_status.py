"""Optional firmware and event-driven usage-hour regression tests."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_power_transition import FakeClient, FakeHass
from test_protocol import (
    _HA_CONST,
    _PACKAGE,
    ProjectorManager,
    ProjectorState,
    _discovery,
    _load,
    _protocol,
)


class StatusParsingTest(unittest.TestCase):
    def test_xw_firmware_reply_uses_main_not_laser(self):
        self.assertEqual(
            _protocol.parse_firmware('[{"main":"1.101"},{"laser":"21/00/00/00/00"}]'), "1.101"
        )

    def test_unknown_firmware_stays_unknown(self):
        for response in (
            '[{"laser":"1.0"}]',
            '"1.0"',
            "[]",
            "null",
            "not json",
            '[{"main":null}]',
            '[{"main":5}]',
            '[{"main":" "}]',
        ):
            with self.subTest(response=response):
                self.assertIsNone(_protocol.parse_firmware(response))

    def test_xw_timer_reply_and_zero(self):
        self.assertEqual(
            _protocol.parse_timer_hours('[{"operation":3146},{"light_src":3084}]'),
            {"operation": 3146, "light_src": 3084},
        )
        self.assertEqual(
            _protocol.parse_timer_hours('{"operation":0,"light_src":0}'),
            {"operation": 0, "light_src": 0},
        )

    def test_rejects_invalid_counters_without_inventing_zero(self):
        for value in (None, True, False, -1, 1.5, "3084", [], {}):
            with self.subTest(value=value):
                response = json.dumps([{"operation": value}, {"light_src": value}])
                self.assertEqual(_protocol.parse_timer_hours(response), {})
        for response in ("not json", "null", "[]", '[1,"text",null]', '{"other":8}'):
            self.assertEqual(_protocol.parse_timer_hours(response), {})

    def test_partial_counters_and_unknown_fields(self):
        self.assertEqual(
            _protocol.parse_timer_hours('[null,{"operation":12,"light_src":-3,"other":900}]'),
            {"operation": 12},
        )


class IdentityStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_identity_reads_firmware_once(self):
        client = _protocol.AdcpClient("192.0.2.10", 53595, None)
        replies = {
            "modelname ?": "VPL-XW5000",
            "serialnum ?": "1234",
            "mac_address ?": "001122334455",
            "version ?": '[{"main":"1.101"}]',
        }
        client.async_command = AsyncMock(side_effect=lambda command: replies[command])
        identity = await client.async_get_identity()
        self.assertEqual(identity.firmware, "1.101")
        self.assertEqual(identity.model, "VPL-XW5000")
        self.assertEqual(identity.serial, "1234")
        self.assertEqual(identity.mac_address, "00:11:22:33:44:55")
        self.assertEqual(client.async_command.await_count, 4)

    async def test_optional_version_error_does_not_break_identity(self):
        for error in (
            _protocol.AdcpCommandError("version ?", "err_cmd"),
            _protocol.AdcpConnectionError("offline"),
        ):
            client = _protocol.AdcpClient("192.0.2.10", 53595, None)

            async def command(query, failure=error):
                if query == "version ?":
                    raise failure
                return "model" if query == "modelname ?" else ""

            client.async_command = command
            self.assertIsNone((await client.async_get_identity()).firmware)

    async def test_version_authentication_error_is_not_hidden(self):
        client = _protocol.AdcpClient("192.0.2.10", 53595, None)

        async def command(query):
            if query == "version ?":
                raise _protocol.AdcpAuthenticationError("bad")
            return ""

        client.async_command = command
        with self.assertRaises(_protocol.AdcpAuthenticationError):
            await client.async_get_identity()

    async def test_both_timers_use_one_query(self):
        client = _protocol.AdcpClient("192.0.2.10", 53595, None)
        client.async_command = AsyncMock(return_value='[{"operation":12},{"light_src":10}]')
        self.assertEqual(await client.async_get_timer_hours(), {"operation": 12, "light_src": 10})
        client.async_command.assert_awaited_once_with("timer ?")

    async def test_firmware_and_timers_on_one_real_tcp_connection(self):
        commands = []
        connections = []
        replies = {
            "modelname ?": '"VPL-XW5000"',
            "serialnum ?": '"1234"',
            "mac_address ?": '"001122334455"',
            "version ?": '[{"main":"1.101"},{"laser":"21/00/00/00/00"}]',
            "timer ?": '[{"operation":3146},{"light_src":3084}]',
        }

        async def handle(reader, writer):
            connections.append(writer)
            try:
                writer.write(b"NOKEY\r\n")
                await writer.drain()
                while raw := await reader.readline():
                    command = raw.decode().strip()
                    commands.append(command)
                    writer.write((replies[command] + "\r\n").encode())
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        client = _protocol.AdcpClient("127.0.0.1", server.sockets[0].getsockname()[1], None)
        try:
            self.assertEqual((await client.async_get_identity()).firmware, "1.101")
            self.assertEqual(
                await client.async_get_timer_hours(),
                {
                    "operation": 3146,
                    "light_src": 3084,
                },
            )
            self.assertEqual(len(connections), 1)
            self.assertEqual(commands.count("timer ?"), 1)
            self.assertEqual(commands.count("version ?"), 1)
        finally:
            await client.async_close()
            server.close()
            await server.wait_closed()


class UsageClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.timer_calls = 0
        self.hours = {"operation": 3146, "light_src": 3084}
        self.timer_error = None
        self.timer_started = asyncio.Event()
        self.timer_release = asyncio.Event()
        self.block_timer = False
        self.timer_cancelled = False

    async def async_get_identity(self):
        return _protocol.ProjectorIdentity(model="VPL-XW5000", firmware="1.101")

    async def async_get_command_info(self, command):
        return None

    async def async_get_timer_hours(self):
        self.timer_calls += 1
        self.timer_started.set()
        if self.block_timer:
            try:
                await self.timer_release.wait()
            except asyncio.CancelledError:
                self.timer_cancelled = True
                raise
        if self.timer_error is not None:
            raise self.timer_error
        return dict(self.hours)


class UsageRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.client = UsageClient()
        self.auth_failures = []
        self.manager = ProjectorManager(
            self.hass,
            self.client,
            lambda: self.auth_failures.append(True),
            lambda host: None,
            operational_refresh_interval=0,
        )
        self.manager._capabilities_probed = True

    async def asyncTearDown(self):
        await self.manager.async_close()
        await asyncio.gather(*self.hass.tasks, return_exceptions=True)

    async def finish_hours(self):
        if (task := self.manager._timer_refresh_task) is not None:
            await asyncio.wait_for(task, 0.5)

    async def initialize_hours(self):
        self.manager.state = ProjectorState(power_status="on", available=True)
        await self.manager.async_refresh_timer_hours()

    async def test_setup_reads_hours_once_even_in_standby(self):
        await self.manager.async_initialize()
        self.assertEqual(self.client.timer_calls, 1)
        self.assertEqual(self.manager.state.timer_hours, self.client.hours)
        self.assertEqual(self.manager.identity.firmware, "1.101")

    async def test_shutdown_refreshes_at_standby_not_at_command_or_cooling(self):
        await self.initialize_hours()
        self.client.block = True
        await self.manager.async_turn_off()
        await self.client.reading.wait()
        self.assertEqual(self.client.timer_calls, 1)
        # Resume the existing power monitor through cooling to confirmed standby.
        self.client.responses.extend(["cooling1", "cooling2", "standby"])
        self.client.hours = {"operation": 3147, "light_src": 3085}
        with patch("custom_components.sony_adcp.manager.POWER_TRANSITION_INTERVAL", 0.001):
            self.client.release.set()
            await asyncio.wait_for(self.manager._power_transition_task, 0.5)
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 2)
        self.assertEqual(self.manager.state.timer_hours, self.client.hours)

    async def test_remote_shutdown_via_sdap_refreshes_once(self):
        await self.initialize_hours()
        self.client.last_power = "standby"
        for raw in (4, 5):
            self.manager.async_handle_announcement(
                _discovery.DiscoveredProjector(
                    host=self.client.host,
                    raw_power_status=raw,
                )
            )
            # Avoid a full refresh racing this deliberately simulated SDAP sequence.
            if self.manager._refresh_task is not None:
                self.manager._refresh_task.cancel()
                await asyncio.gather(self.manager._refresh_task, return_exceptions=True)
        self.assertEqual(self.client.timer_calls, 1)
        for _ in range(3):
            self.manager.async_handle_announcement(
                _discovery.DiscoveredProjector(
                    host=self.client.host,
                    raw_power_status=0,
                )
            )
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 2)

    async def test_watchdog_detected_standby_also_refreshes(self):
        await self.initialize_hours()
        self.client.last_power = "saving_standby"
        await self.manager.async_refresh()
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 2)

    async def test_shutdown_with_dhcp_change_reads_hours_from_new_address(self):
        await self.initialize_hours()
        hosts = []
        original = self.client.async_get_timer_hours

        async def read_hours():
            hosts.append(self.client.host)
            return await original()

        self.client.async_get_timer_hours = read_hours
        self.client.last_power = "standby"
        self.manager.async_handle_announcement(
            _discovery.DiscoveredProjector(
                host="192.0.2.99",
                raw_power_status=0,
            )
        )
        await self.finish_hours()
        self.assertEqual(hosts, ["192.0.2.99"])
        self.assertEqual(self.client.timer_calls, 2)

    async def test_repeated_standby_and_saving_standby_do_not_poll_hours(self):
        await self.initialize_hours()
        self.manager._apply_power_status("standby")
        await self.finish_hours()
        for power in ("standby", "saving_standby", "standby", "saving_standby"):
            self.manager._apply_power_status(power)
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 2)

    async def test_operational_and_picture_refresh_do_not_read_timers(self):
        await self.initialize_hours()
        await self.manager._async_refresh_operational()
        await self.manager._async_refresh_operational()
        self.assertEqual(self.client.timer_calls, 1)

    async def test_power_on_does_not_read_known_hours_again(self):
        await self.initialize_hours()
        self.manager._apply_power_status("startup")
        self.manager._apply_power_status("on")
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 1)

    async def test_inactive_at_setup_can_retry_when_on(self):
        self.manager.state = ProjectorState(power_status="standby", available=True)
        self.client.timer_error = _protocol.AdcpCommandError("timer ?", "err_inactive")
        await self.manager.async_refresh_timer_hours()
        self.client.timer_error = None
        self.manager._apply_power_status("on")
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 2)
        self.assertEqual(self.manager.state.timer_hours["light_src"], 3084)

    async def test_unsupported_timer_is_not_retried_on_each_shutdown(self):
        self.client.timer_error = _protocol.AdcpCommandError("timer ?", "err_cmd")
        await self.initialize_hours()
        self.manager._apply_power_status("standby")
        self.manager._apply_power_status("on")
        self.manager._apply_power_status("standby")
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 1)
        self.assertEqual(self.manager.state.timer_hours, {})
        self.assertTrue(self.manager.state.available)

    async def test_transport_failure_preserves_known_counters(self):
        await self.initialize_hours()
        self.client.timer_error = _protocol.AdcpConnectionError("offline")
        self.manager._apply_power_status("standby")
        await self.finish_hours()
        self.assertEqual(self.manager.state.timer_hours, {"operation": 3146, "light_src": 3084})
        self.assertTrue(self.manager.state.available)

    async def test_malformed_or_partial_reply_never_overwrites_known_values_with_zero(self):
        await self.initialize_hours()
        self.client.hours = {}
        await self.manager.async_refresh_timer_hours()
        self.assertEqual(self.manager.state.timer_hours["light_src"], 3084)
        self.client.hours = {"operation": 3147}
        await self.manager.async_refresh_timer_hours()
        self.assertEqual(self.manager.state.timer_hours, {"operation": 3147, "light_src": 3084})

    async def test_genuine_counter_reset_to_zero_is_kept(self):
        await self.initialize_hours()
        self.client.hours = {"light_src": 0}
        await self.manager.async_refresh_timer_hours()
        self.assertEqual(self.manager.state.timer_hours["light_src"], 0)

    async def test_authentication_requests_reauth_without_replacing_counters(self):
        await self.initialize_hours()
        self.client.timer_error = _protocol.AdcpAuthenticationError("bad")
        await self.manager.async_refresh_timer_hours()
        self.assertEqual(self.auth_failures, [True])
        self.assertEqual(self.manager.state.timer_hours["operation"], 3146)

    async def test_slow_timer_read_does_not_delay_standby_publication(self):
        await self.initialize_hours()
        self.client.timer_started.clear()
        self.client.block_timer = True
        self.manager._apply_power_status("standby")
        await self.client.timer_started.wait()
        self.assertEqual(self.manager.state.power_status, "standby")
        self.assertFalse(self.manager._timer_refresh_task.done())

    async def test_new_shutdown_during_pending_read_is_not_lost(self):
        await self.initialize_hours()
        self.client.block_timer = True
        self.client.timer_started.clear()
        self.manager._apply_power_status("standby")
        await self.client.timer_started.wait()
        self.manager._apply_power_status("on")
        self.manager._apply_power_status("standby")
        self.client.timer_release.set()
        await self.finish_hours()
        self.assertEqual(self.client.timer_calls, 3)

    async def test_unload_cancels_pending_timer_read_and_stops_new_tasks(self):
        await self.initialize_hours()
        self.client.block_timer = True
        self.client.timer_started.clear()
        self.manager._apply_power_status("standby")
        await self.client.timer_started.wait()
        await self.manager.async_close()
        self.assertTrue(self.client.timer_cancelled)
        self.manager._schedule_timer_refresh()
        self.assertEqual(self.client.timer_calls, 2)

    async def test_unchanged_timer_reply_does_not_notify(self):
        await self.initialize_hours()
        notifications = []
        self.manager.async_add_listener(lambda: notifications.append(True))
        await self.manager.async_refresh_timer_hours()
        self.assertEqual(notifications, [])

    async def test_sdap_identity_fallback_preserves_firmware(self):
        self.manager.identity = _protocol.ProjectorIdentity(firmware="1.101")
        self.manager.async_handle_announcement(
            _discovery.DiscoveredProjector(
                host=self.client.host,
                model="VPL-XW5000",
                serial="1234",
            )
        )
        self.assertEqual(self.manager.identity.firmware, "1.101")


@dataclass(frozen=True, kw_only=True)
class FakeSensorDescription:
    key: str
    translation_key: str
    entity_category: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    native_unit_of_measurement: str | None = None


class UsageEntityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sensor_api = ModuleType("homeassistant.components.sensor")
        sensor_api.SensorEntity = type("SensorEntity", (), {})
        sensor_api.SensorEntityDescription = FakeSensorDescription
        sensor_api.SensorDeviceClass = SimpleNamespace(DURATION="duration")
        sensor_api.SensorStateClass = SimpleNamespace(TOTAL_INCREASING="total_increasing")
        entity_api = ModuleType("homeassistant.helpers.entity")

        class FakeEntity:
            async def async_added_to_hass(self):
                pass

            def async_on_remove(self, remove):
                if not hasattr(self, "removals"):
                    self.removals = []
                self.removals.append(remove)

            def async_write_ha_state(self):
                pass

        entity_api.Entity = FakeEntity
        entity_api.EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
        registry_api = ModuleType("homeassistant.helpers.device_registry")
        registry_api.CONNECTION_NETWORK_MAC = "mac"
        registry_api.DeviceInfo = dict
        platform_api = ModuleType("homeassistant.helpers.entity_platform")
        platform_api.AddConfigEntryEntitiesCallback = object
        config_api = ModuleType("homeassistant.config_entries")
        config_api.ConfigSubentry = object
        self.modules = patch.dict(
            sys.modules,
            {
                "homeassistant.components": ModuleType("homeassistant.components"),
                "homeassistant.components.sensor": sensor_api,
                "homeassistant.helpers": ModuleType("homeassistant.helpers"),
                "homeassistant.helpers.entity": entity_api,
                "homeassistant.helpers.device_registry": registry_api,
                "homeassistant.helpers.entity_platform": platform_api,
                "homeassistant.config_entries": config_api,
            },
        )
        self.modules.start()
        self.addCleanup(self.modules.stop)
        for name, value in {
            "CONF_HOST": "host",
            "CONF_NAME": "name",
            "UnitOfTime": SimpleNamespace(HOURS="h"),
        }.items():
            item = patch.object(_HA_CONST, name, value, create=True)
            item.start()
            self.addCleanup(item.stop)
        package = patch.object(_PACKAGE, "SonyAdcpConfigEntry", object, create=True)
        package.start()
        self.addCleanup(package.stop)
        _load("entity")
        self.sensor = _load("sensor")
        self.manager = ProjectorManager(
            FakeHass(), UsageClient(), lambda: None, lambda host: None, 0
        )
        self.manager.identity = _protocol.ProjectorIdentity(model="VPL-XW5000", firmware="1.101")
        self.unloads = []
        self.entry = SimpleNamespace(
            subentries={},
            options={},
            unique_id="1234",
            data={"host": "192.0.2.10"},
            runtime_data=SimpleNamespace(manager=self.manager),
            async_on_unload=self.unloads.append,
        )
        self.entities = []

    async def asyncTearDown(self):
        for unload in self.unloads:
            unload()
        await self.manager.async_close()

    def add_entities(self, entities, **kwargs):
        self.assertIsNone(kwargs.get("config_subentry_id"))
        self.entities.extend(entities)

    async def test_only_reported_counters_create_entities_with_hours_and_statistics(self):
        await self.sensor.async_setup_entry(None, self.entry, self.add_entities)
        self.assertEqual(len(self.entities), 4)
        self.manager.state = ProjectorState(timer_hours={"operation": 0})
        self.manager._notify()
        timer = self.entities[-1]
        self.assertEqual(timer.native_value, 0)
        self.assertEqual(timer._attr_unique_id, "1234_timer_operation")
        self.assertEqual(timer.entity_description.device_class, "duration")
        self.assertEqual(timer.entity_description.state_class, "total_increasing")
        self.assertEqual(timer.entity_description.native_unit_of_measurement, "h")
        self.assertEqual(timer.entity_description.entity_category, "diagnostic")
        self.manager.state = ProjectorState(timer_hours={"operation": 1, "light_src": 0})
        self.manager._notify()
        self.manager._notify()
        self.assertEqual(len(self.entities), 6)
        self.assertEqual(self.entities[-1]._attr_unique_id, "1234_timer_light_src")

    async def test_custom_sensor_grouping_and_stable_identity(self):
        config = {
            "id": "sensor-uuid",
            "name": "Custom aspect",
            "command": "aspect",
            "value_type": "text",
            "json_field": "",
            "unit": "",
        }
        self.entry.options = {"custom_sensors": [config]}
        groups = []

        def add(entities, **kwargs):
            groups.append((list(entities), kwargs))

        await self.sensor.async_setup_entry(None, self.entry, add)
        custom = groups[0][0][0]
        self.assertEqual(groups[0][1], {"config_subentry_id": None})
        self.assertEqual(custom._attr_unique_id, "1234_custom_sensor-uuid")
        config = {**config, "name": "Renamed", "command": "gamma"}
        edited = self.sensor.SonyAdcpCustomSensor(self.entry, self.manager, config)
        self.assertEqual(edited._attr_unique_id, custom._attr_unique_id)
        self.assertEqual(self.manager._custom_commands, {})  # Disabled entities aren't added.

    async def test_custom_entity_value_availability_and_errors(self):
        from custom_components.sony_adcp.custom_commands import CustomCommandResult

        config = {
            "id": "sensor-uuid",
            "name": "Gamma",
            "command": "gamma",
            "value_type": "number",
            "json_field": "0.gamma",
            "unit": "",
        }
        custom = self.sensor.SonyAdcpCustomSensor(self.entry, self.manager, config)
        self.manager.state = ProjectorState(power_status="on", available=True)
        self.assertFalse(custom.available)

        self.assertEqual(custom.extra_state_attributes["last_error"], "not_yet_refreshed")
        self.manager.custom_results["gamma"] = CustomCommandResult(response='[{"gamma":0}]')
        self.assertEqual(custom.native_value, 0)
        self.assertTrue(custom.available)
        self.manager.custom_results["gamma"] = CustomCommandResult(response='[{"other":1}]')
        self.assertFalse(custom.available)
        self.assertEqual(custom.extra_state_attributes["last_error"], "invalid_response")
        self.manager.custom_results["gamma"] = CustomCommandResult(response='[{"gamma":2.4}]')
        self.manager._power_transition_target = "off"
        self.assertFalse(custom.available)
        self.manager._power_transition_target = None
        self.manager.state = ProjectorState(power_status="standby", available=True)
        self.assertFalse(custom.available)

    async def test_custom_entity_registers_only_on_add_and_unregisters_on_remove(self):
        config = {
            "id": "sensor-uuid",
            "name": "Aspect",
            "command": "aspect",
            "value_type": "text",
            "json_field": "",
            "unit": "",
        }
        custom = self.sensor.SonyAdcpCustomSensor(self.entry, self.manager, config)
        self.assertEqual(self.manager._custom_commands, {})
        await custom.async_added_to_hass()
        self.assertEqual(self.manager._custom_commands, {"aspect": 1})
        for remove in custom.removals:
            remove()
        self.assertEqual(self.manager._custom_commands, {})
        self.assertEqual(self.manager._listeners, set())

    async def test_device_info_exposes_firmware_not_a_separate_sensor(self):
        await self.sensor.async_setup_entry(None, self.entry, self.add_entities)
        self.assertEqual(self.entities[0]._attr_device_info["sw_version"], "1.101")
        self.assertEqual(len(self.entities), 4)
