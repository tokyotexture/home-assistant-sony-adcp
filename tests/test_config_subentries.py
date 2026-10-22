"""Custom-sensor forms tested with real schemas and a minimal HA flow harness."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import voluptuous as vol
from test_protocol import _HA_CONST, _PACKAGE, _load


class FlowHarness:
    """Capture the public flow results without starting Home Assistant."""

    def __init_subclass__(cls, **kwargs):
        pass

    def _get_entry(self):
        return self.entry

    @property
    def config_entry(self):
        return self.entry

    def _get_reconfigure_subentry(self):
        return self.subentry

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_show_menu(self, **kwargs):
        return {"type": "menu", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_abort(self, **kwargs):
        return {"type": "abort", **kwargs}

    def async_update_and_abort(self, entry, subentry, **kwargs):
        return {"type": "update", "entry": entry, "subentry": subentry, **kwargs}


class SelectHarness:
    def __init__(self, config):
        self.options = config["options"]

    def __call__(self, value):
        options = [item["value"] if isinstance(item, dict) else item for item in self.options]
        return vol.In(options)(value)


class CustomSensorFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config_api = ModuleType("homeassistant.config_entries")
        for name in ("ConfigEntry", "ConfigFlow", "OptionsFlow", "ConfigSubentryFlow"):
            setattr(config_api, name, FlowHarness)
        config_api.ConfigEntryState = SimpleNamespace(LOADED="loaded")
        config_api.ConfigFlowResult = config_api.SubentryFlowResult = dict
        validation = ModuleType("homeassistant.helpers.config_validation")
        validation.string = str
        validation.port = int
        validation.boolean = bool
        selectors = ModuleType("homeassistant.helpers.selector")
        selectors.SelectSelector = SelectHarness
        selectors.SelectSelectorConfig = dict
        selectors.SelectSelectorMode = SimpleNamespace(DROPDOWN="dropdown")
        helpers = ModuleType("homeassistant.helpers")
        helpers.config_validation = validation
        modules = patch.dict(
            sys.modules,
            {
                "homeassistant.config_entries": config_api,
                "homeassistant.helpers": helpers,
                "homeassistant.helpers.config_validation": validation,
                "homeassistant.helpers.selector": selectors,
            },
        )
        modules.start()
        self.addCleanup(modules.stop)
        for name in ("CONF_HOST", "CONF_NAME", "CONF_PASSWORD", "CONF_PORT"):
            item = patch.object(_HA_CONST, name, name.removeprefix("CONF_").lower(), create=True)
            item.start()
            self.addCleanup(item.stop)
        listener = patch.object(_PACKAGE, "async_get_listener", object, create=True)
        listener.start()
        self.addCleanup(listener.stop)
        self.module = _load("config_flow")
        self.flow = self.module.SonyAdcpOptionsFlow()
        self.flow.entry = SimpleNamespace(
            options={}, state="loaded", runtime_data=SimpleNamespace(manager=Mock())
        )
        self.data = {"name": "Aspect", "command": "aspect", "value_type": "text"}

    async def test_parent_no_longer_advertises_subentries(self):
        self.assertNotIn(
            "async_get_supported_subentry_types", self.module.SonyAdcpConfigFlow.__dict__
        )
        self.assertEqual(self.module.SonyAdcpConfigFlow.MINOR_VERSION, 2)

    async def test_configure_menu_and_empty_sensor_menu(self):
        result = await self.flow.async_step_init()
        self.assertEqual(result["menu_options"], ["refresh", "custom_sensors"])
        result = await self.flow.async_step_custom_sensors()
        self.assertEqual(result["menu_options"], ["add_sensor"])

    async def test_add_form_and_defaults(self):
        result = await self.flow.async_step_add_sensor()
        self.assertEqual(result["step_id"], "sensor")
        validated = result["data_schema"](self.data)
        self.assertEqual(validated["json_field"], "")
        self.assertEqual(validated["unit"], "")
        saved = await self.flow.async_step_sensor(validated)
        self.assertEqual(saved["type"], "create_entry")
        self.assertEqual(saved["data"]["custom_sensors"][0]["name"], "Aspect")
        self.assertEqual(saved["data"]["custom_sensors"][0]["command"], "aspect")
        self.assertTrue(saved["data"]["custom_sensors"][0]["id"])
        self.assertEqual(self.flow.entry.options, {})  # Nothing persisted by showing a form.

    async def test_invalid_command_shows_field_error_without_saving(self):
        result = await self.flow.async_step_sensor({**self.data, "command": 'power "off"'})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"command": "invalid_command"})

    async def test_edit_replaces_data_and_preserves_id_and_unrelated_options(self):
        self.flow.entry.options = {
            "other": True,
            "custom_sensors": [{"id": "original", **self.data}],
        }
        result = await self.flow.async_step_edit_sensor({"sensor_id": "original"})
        self.assertEqual(result["data_schema"]({})["command"], "aspect")
        saved = await self.flow.async_step_sensor(
            {
                **self.data,
                "name": "Gamma",
                "command": "gamma",
                "value_type": "number",
            }
        )
        self.assertEqual(saved["data"]["custom_sensors"][0]["id"], "original")
        self.assertEqual(saved["data"]["custom_sensors"][0]["name"], "Gamma")
        self.assertEqual(saved["data"]["custom_sensors"][0]["unit"], "")
        self.assertTrue(saved["data"]["other"])

    async def test_text_unit_error_can_be_cleared_during_edit(self):
        result = await self.flow.async_step_sensor({**self.data, "unit": "%"})
        self.assertEqual(result["errors"], {"unit": "invalid_unit"})
        saved = await self.flow.async_step_sensor({**self.data, "unit": ""})
        self.assertEqual(saved["type"], "create_entry")

    async def test_limit_applies_to_add_but_does_not_prevent_edit(self):
        self.flow.entry.options = {
            "custom_sensors": [{"id": str(index), **self.data} for index in range(32)]
        }
        result = await self.flow.async_step_add_sensor(self.data)
        self.assertEqual(result["reason"], "too_many_sensors")
        await self.flow.async_step_edit_sensor({"sensor_id": "0"})
        saved = await self.flow.async_step_sensor(self.data)
        self.assertEqual(saved["type"], "create_entry")

    async def test_remove_requires_confirmation_and_only_removes_selected_sensor(self):
        self.flow.entry.options = {
            "custom_sensors": [
                {"id": "first", **self.data},
                {"id": "second", **self.data},
            ],
            "operational_refresh_interval": 5,
        }
        picker = await self.flow.async_step_remove_sensor()
        self.assertEqual(picker["data_schema"]({"sensor_id": "first"})["sensor_id"], "first")
        confirm = await self.flow.async_step_remove_sensor({"sensor_id": "first"})
        self.assertEqual(confirm["step_id"], "confirm_remove")
        self.assertEqual(len(self.flow.entry.options["custom_sensors"]), 2)
        saved = await self.flow.async_step_confirm_remove({})
        self.assertEqual([sensor["id"] for sensor in saved["data"]["custom_sensors"]], ["second"])
        self.assertEqual(saved["data"]["operational_refresh_interval"], 5)

    async def test_stale_edit_aborts_if_sensor_was_removed(self):
        self.flow._sensor_id = "removed"
        self.assertEqual(
            (await self.flow.async_step_sensor(self.data))["reason"], "sensor_not_found"
        )

    async def test_refresh_settings_preserve_custom_sensors_and_apply_without_reload(self):
        self.flow.entry.options = {"custom_sensors": [{"id": "first", **self.data}]}
        form = await self.flow.async_step_refresh()
        data = form["data_schema"](
            {"operational_refresh_interval": "5", "refresh_picture_settings": False}
        )
        result = await self.flow.async_step_refresh(data)
        self.assertEqual(
            result["data"]["custom_sensors"], self.flow.entry.options["custom_sensors"]
        )
        self.flow.entry.runtime_data.manager.async_set_operational_refresh_interval.assert_called_with(
            5
        )

    async def test_translation_includes_all_fields_errors_and_steps(self):
        root = Path(__file__).parents[1] / "custom_components" / "sony_adcp"
        strings = json.loads((root / "strings.json").read_text())
        self.assertEqual(strings, json.loads((root / "translations/en.json").read_text()))
        self.assertNotIn("config_subentries", strings)
        translations = strings["options"]
        for method in (self.flow.async_step_add_sensor, self.flow.async_step_refresh):
            result = await method()
            fields = {str(field) for field in result["data_schema"].schema}
            self.assertEqual(fields, set(translations["step"][result["step_id"]]["data"]))
            description = translations["step"][result["step_id"]]["description"]
            self.assertNotIn("https://", description)
            if result["step_id"] == "sensor":
                self.assertIn("documentation_url", result["description_placeholders"])
                self.assertIn(
                    "docs/custom-sensors.md",
                    description.format(**result["description_placeholders"]),
                )
