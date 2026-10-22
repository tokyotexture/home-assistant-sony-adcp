"""Real Home Assistant registry regressions (run separately from offline stubs)."""

from __future__ import annotations

import tempfile
import unittest
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.sony_adcp import async_migrate_entry
from custom_components.sony_adcp.media_player import SonyAdcpProjector
from custom_components.sony_adcp.migration import async_remove_deleted_custom_sensors
from custom_components.sony_adcp.protocol import ProjectorIdentity
from custom_components.sony_adcp.sensor import async_setup_entry as async_setup_sensors


class DeviceOwnershipTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        self.config = {
            "id": "sensor-uuid",
            "name": "Aspect",
            "command": "aspect",
            "value_type": "text",
            "json_field": "",
            "unit": "",
        }
        self.entry = ConfigEntry(
            domain="sony_adcp",
            title="Projector",
            data={"host": "192.0.2.1"},
            options={},
            unique_id="1234",
            version=2,
            minor_version=1,
            source="user",
            discovery_keys=MappingProxyType({}),
            subentries_data=[
                {
                    "subentry_id": "sensor-uuid",
                    "subentry_type": "custom_sensor",
                    "title": "Aspect",
                    "data": {k: v for k, v in self.config.items() if k != "id"},
                    "unique_id": None,
                }
            ],
        )
        self.hass.config_entries._entries[self.entry.entry_id] = self.entry
        await dr.async_load(self.hass)
        await er.async_load(self.hass)
        self.devices = dr.async_get(self.hass)
        self.entities = er.async_get(self.hass)
        manager = SimpleNamespace(
            identity=ProjectorIdentity(model="VPL-VW535"),
            state=SimpleNamespace(timer_hours={}),
            async_add_listener=lambda listener: lambda: None,
        )
        self.entry.runtime_data = SimpleNamespace(manager=manager)
        self.projector = SonyAdcpProjector(self.entry, manager)
        self.power_id = self.register(self.projector, "media_player").entity_id
        self.device_id = self.entities.async_get(self.power_id).device_id
        await self.hass.async_block_till_done()

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self.directory.cleanup()

    def register(self, entity, domain, subentry_id=None):
        device = self.devices.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            config_subentry_id=subentry_id,
            **entity.device_info,
        )
        return self.entities.async_get_or_create(
            domain,
            "sony_adcp",
            entity.unique_id,
            config_entry=self.entry,
            config_subentry_id=subentry_id,
            device_id=device.id,
            supported_features=entity.supported_features,
            suggested_object_id=entity.unique_id,
        )

    def add_sensors(self, entities, update_before_add=False, *, config_subentry_id=None):
        self.assertIsNone(config_subentry_id, "Custom sensors must not claim device ownership")
        for entity in entities:
            self.register(entity, "sensor", config_subentry_id)

    async def test_reproduces_beta1_device_move_removing_power_entity(self):
        device = self.devices.async_get(self.device_id)
        if not hasattr(device, "config_subentry_id"):
            self.skipTest("Single-owner registry reproduction applies to newer Home Assistant")
        with patch("homeassistant.helpers.frame.report_usage"):
            self.devices.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                config_subentry_id="sensor-uuid",
                **self.projector.device_info,
            )
        await self.hass.async_block_till_done()
        self.assertIsNone(self.entities.async_get(self.power_id))

    async def test_add_edit_and_remove_sensors_keep_power_and_device_id(self):
        await async_migrate_entry(self.hass, self.entry)
        for config in (self.config, {**self.config, "name": "Renamed", "command": "gamma"}):
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={"custom_sensors": [config]},
            )
            await async_setup_sensors(self.hass, self.entry, self.add_sensors)
            await self.hass.async_block_till_done()
            self.assertEqual(self.entities.async_get(self.power_id).device_id, self.device_id)
            self.assertTrue(self.entities.async_get(self.power_id).supported_features)
        self.hass.config_entries.async_update_entry(self.entry, options={"custom_sensors": []})
        async_remove_deleted_custom_sensors(self.hass, self.entry)
        await self.hass.async_block_till_done()
        self.assertIsNotNone(self.entities.async_get(self.power_id))
        self.assertIsNotNone(self.devices.async_get(self.device_id))
        self.assertFalse(
            any(
                entity.unique_id == "1234_custom_sensor-uuid"
                for entity in self.entities.entities.values()
            )
        )

    async def test_migration_preserves_sensor_registration_and_reparents_before_delete(self):
        # A beta 1 entity on the shared device, with a user-chosen entity ID/name.
        with patch("homeassistant.helpers.frame.report_usage"):
            self.devices.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                config_subentry_id="sensor-uuid",
                **self.projector.device_info,
            )
        sensor = self.entities.async_get_or_create(
            "sensor",
            "sony_adcp",
            "1234_custom_sensor-uuid",
            config_entry=self.entry,
            config_subentry_id="sensor-uuid",
            device_id=self.device_id,
            suggested_object_id="custom_aspect",
        )
        sensor = self.entities.async_update_entity(sensor.entity_id, name="User name")
        await self.hass.async_block_till_done()
        await async_migrate_entry(self.hass, self.entry)
        await self.hass.async_block_till_done()
        migrated = self.entities.async_get(sensor.entity_id)
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated.unique_id, "1234_custom_sensor-uuid")
        self.assertEqual(migrated.name, "User name")
        self.assertIsNone(migrated.config_subentry_id)
        self.assertIsNotNone(self.devices.async_get(self.device_id))
        self.assertFalse(self.entry.subentries)
        self.assertEqual(self.entry.options["custom_sensors"], [self.config])
        self.register(self.projector, "media_player")  # Restore any already-removed beta 1 control.
        await async_setup_sensors(self.hass, self.entry, self.add_sensors)
        await self.hass.async_block_till_done()
        self.assertIsNotNone(self.entities.async_get(self.power_id))
        await async_migrate_entry(self.hass, self.entry)  # Idempotent.
        self.assertEqual(len(self.entry.options["custom_sensors"]), 1)
