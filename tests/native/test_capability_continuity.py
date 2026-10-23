"""Real HA entities/registries and config-entry persistence across off reloads."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import test_device_ownership as ownership

from custom_components.sony_adcp import (
    _update_capabilities,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.sony_adcp.capabilities import CONF_CAPABILITIES
from custom_components.sony_adcp.manager import ProjectorManager
from custom_components.sony_adcp.number import async_setup_entry as async_setup_numbers
from custom_components.sony_adcp.protocol import CommandInfo, ProjectorIdentity
from custom_components.sony_adcp.select import SonyAdcpSelect
from custom_components.sony_adcp.switch import SonyAdcpSwitch


class ProjectorClient:
    host = "192.0.2.1"

    def __init__(self):
        self.power = "on"
        self.probes = []
        self.reads = []

    async def async_get_identity(self):
        return ProjectorIdentity("VPL-VW535", "1234", firmware="5.003")

    async def async_get_power(self):
        return self.power

    async def async_get_json_list(self, command):
        return ()

    async def async_get_timer_hours(self):
        return {}

    async def async_get_command_info(self, command):
        self.probes.append(command)
        if command in {"brightness", "contrast", "sharpness"}:
            return CommandInfo(command, "menu_num", minimum=0, maximum=100, step=1)
        return None

    async def async_command(self, command):
        self.reads.append(command)
        if self.power != "on":
            raise AssertionError("No picture queries allowed in standby")
        return {
            "input ?": "hdmi1", "signal ?": "1080p", "brightness ?": "49",
            "contrast ?": "50", "sharpness ?": "30", "picture_mode ?": "game", "blank ?": "off",
        }[command]

    async def async_close(self):
        pass


class CapabilityContinuityTest(ownership.DeviceOwnershipFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.client = ProjectorClient()
        self.numbers = []
        self.started = []

    async def asyncTearDown(self):
        for entity in self.numbers:
            await entity.async_internal_will_remove_from_hass()
        for manager in self.started:
            await manager.async_close()
        await super().asyncTearDown()

    async def setup(self):
        async def forward(entry, platforms):
            self.started.append(entry.runtime_data.manager)
            def add(entities):
                for entity in entities:
                    entity.hass = self.hass
                    # No EntityPlatform in this registry fixture: suppress only
                    # state-machine writes, not real availability/value properties.
                    entity.async_write_ha_state = Mock()
                    self.numbers.append(entity)
                    entity.entity_id = self.register(entity, "number").entity_id
            await async_setup_numbers(self.hass, entry, add)
            for entity in self.numbers:
                if entity._manager is entry.runtime_data.manager:
                    await entity.async_added_to_hass()
        with (
            patch("custom_components.sony_adcp.AdcpClient", return_value=self.client),
            patch("custom_components.sony_adcp.async_get_listener", AsyncMock(return_value=
                  SimpleNamespace(async_subscribe=lambda *args: lambda: None))),
            patch.object(self.hass.config_entries, "async_forward_entry_setups", forward),
        ):
            await async_setup_entry(self.hass, self.entry)
        return self.entry.runtime_data.manager

    async def test_actual_setup_cache_off_reload_and_on_keep_registry_and_ids(self):
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={"operational_refresh_interval": 0, "refresh_picture_settings": False},
        )
        first = await self.setup()
        self.assertEqual(len(self.numbers), 3)
        before = {entity.unique_id: self.entities.async_get_entity_id(
            "number", "sony_adcp", entity.unique_id,
        ) for entity in self.numbers}
        self.assertTrue(all(entity.available for entity in self.numbers))
        # HA config-entry data is JSON persisted. No operational values are stored.
        persisted = json.loads(json.dumps(dict(self.entry.data)))
        self.assertIn(CONF_CAPABILITIES, persisted)
        self.assertNotIn("values", persisted[CONF_CAPABILITIES])
        self.assertEqual(persisted["host"], "192.0.2.1")
        with patch.object(
            self.hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True),
        ):
            await async_unload_entry(self.hass, self.entry)
        self.client.power = "standby"
        self.client.reads.clear()
        self.client.probes.clear()
        restored = await self.setup()
        restored_entities = self.numbers[3:]
        self.assertEqual(len(restored_entities), 3)
        self.assertTrue(all(not entity.available for entity in restored_entities))
        self.assertTrue(all(entity.native_value is None for entity in restored_entities))
        self.assertEqual(self.client.probes, [])
        self.assertEqual(self.client.reads, [])
        self.assertEqual(restored.command_info, first.command_info)
        for entity in restored_entities:
            self.assertEqual(self.entities.async_get_entity_id(
                "number", "sony_adcp", entity.unique_id,
            ), before[entity.unique_id])
        self.client.power = "on"
        await restored.async_refresh()
        self.assertTrue(all(entity.available for entity in restored_entities))
        self.assertIsNone(restored._operational_refresh_task)
        restored._apply_power_status("cooling1")
        self.assertTrue(all(not entity.available for entity in restored_entities))
        self.assertTrue(all(entity.native_value is None for entity in restored_entities))
        self.assertIsNotNone(self.entities.async_get(self.power_id))

    async def test_capability_updates_do_not_reload_or_drop_existing_data(self):
        self.hass.config_entries.async_update_entry(self.entry, data={
            **self.entry.data, "password": "not-a-real-password",
        })
        with patch.object(self.hass.config_entries, "async_reload", AsyncMock()) as reload:
            _update_capabilities(self.hass, self.entry, {"version": 1})
            await self.hass.async_block_till_done()
        self.assertEqual(self.entry.data["password"], "not-a-real-password")
        self.assertEqual(self.entry.options, {})
        reload.assert_not_awaited()

    async def test_picture_select_and_switch_availability_requires_fresh_on_value(self):
        manager = ProjectorManager(self.hass, self.client, lambda: None, lambda host: None, 0)
        self.started.append(manager)
        manager.identity = await self.client.async_get_identity()
        entities = [SonyAdcpSelect(self.entry, manager, "picture_mode"),
                    SonyAdcpSwitch(self.entry, manager, "blank")]
        manager._apply_power_status("on")
        self.assertTrue(all(not entity.available for entity in entities))
        await manager.async_read_command("picture_mode")
        await manager.async_read_command("blank")
        self.assertTrue(all(entity.available for entity in entities))
        manager._power_transition_target = "off"
        self.assertTrue(all(not entity.available for entity in entities))
        manager._power_transition_target = None
        manager._apply_power_status("standby")
        self.assertTrue(all(not entity.available for entity in entities))
        manager.state = replace(manager.state, power_status="on", available=True)
        self.assertTrue(all(not entity.available for entity in entities))

    async def test_input_refresh_inside_action_lock_does_not_deadlock(self):
        manager = await self.setup()
        async with manager._operational_refresh_lock:
            await asyncio.wait_for(manager.async_refresh(), 1)
