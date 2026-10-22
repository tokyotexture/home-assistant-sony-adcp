"""Subentry-only reload behavior; no network or running HA instance required."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from test_protocol import _HA_CONST


class GenericEntry:
    def __class_getitem__(cls, item):
        return cls


class SubentryLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config_api = ModuleType("homeassistant.config_entries")
        config_api.ConfigEntry = GenericEntry
        exceptions = ModuleType("homeassistant.exceptions")
        exceptions.ConfigEntryAuthFailed = exceptions.ConfigEntryNotReady = RuntimeError
        helpers = ModuleType("homeassistant.helpers")
        helpers.config_validation = SimpleNamespace(config_entry_only_config_schema=lambda _: {})
        helpers.device_registry = ModuleType("homeassistant.helpers.device_registry")
        helpers.entity_registry = ModuleType("homeassistant.helpers.entity_registry")
        helpers.entity_registry.async_get = Mock()
        helpers.entity_registry.async_entries_for_config_entry = Mock(return_value=[])
        modules = patch.dict(
            sys.modules,
            {
                "homeassistant.config_entries": config_api,
                "homeassistant.exceptions": exceptions,
                "homeassistant.helpers": helpers,
            },
        )
        modules.start()
        self.addCleanup(modules.stop)
        for name in ("CONF_HOST", "CONF_PASSWORD", "CONF_PORT"):
            item = patch.object(_HA_CONST, name, name.removeprefix("CONF_").lower(), create=True)
            item.start()
            self.addCleanup(item.stop)
        path = Path(__file__).parents[1] / "custom_components/sony_adcp/__init__.py"
        name = "custom_components.sony_adcp.integration_under_test"
        spec = importlib.util.spec_from_loader(
            name, importlib.machinery.SourceFileLoader(name, str(path)), is_package=False
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        self.integration = module
        self.manager = Mock(async_initialize=AsyncMock(), async_close=AsyncMock())
        self.listener = Mock()
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_reload=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            )
        )
        self.sensor = {"id": "sensor-uuid", "name": "Aspect", "command": "aspect"}
        self.entry = SimpleNamespace(
            data={"host": "192.0.2.1"},
            options={"custom_sensors": [self.sensor]},
            entry_id="projector",
            unique_id="1234",
            subentries={},
            async_on_unload=Mock(),
            add_update_listener=Mock(return_value=Mock()),
        )
        with (
            patch.object(module, "AdcpClient"),
            patch.object(module, "ProjectorManager", return_value=self.manager),
            patch.object(module, "async_get_listener", AsyncMock(return_value=self.listener)),
        ):
            await module.async_setup_entry(self.hass, self.entry)
        self.updated = self.entry.add_update_listener.call_args.args[0]

    async def test_options_and_dhcp_updates_do_not_reload(self):
        self.entry.options = {**self.entry.options, "operational_refresh_interval": 5}
        self.entry.data = {"host": "192.0.2.99"}
        await self.updated(self.hass, self.entry)
        self.hass.config_entries.async_reload.assert_not_awaited()

    async def test_in_place_subentry_edit_reloads_once(self):
        self.sensor["command"] = "gamma"
        await self.updated(self.hass, self.entry)
        await self.updated(self.hass, self.entry)
        self.hass.config_entries.async_reload.assert_awaited_once_with("projector")

    async def test_rename_add_and_remove_reload(self):
        self.sensor["name"] = "New name"
        await self.updated(self.hass, self.entry)
        self.entry.options["custom_sensors"].append({**self.sensor, "id": "second"})
        await self.updated(self.hass, self.entry)
        self.entry.options["custom_sensors"].pop()
        await self.updated(self.hass, self.entry)
        self.assertEqual(self.hass.config_entries.async_reload.await_count, 3)

    async def test_unload_closes_manager_and_unsubscribes(self):
        self.assertTrue(await self.integration.async_unload_entry(self.hass, self.entry))
        self.manager.async_close.assert_awaited_once()
        self.entry.runtime_data.unsubscribe_announcement.assert_called_once()
