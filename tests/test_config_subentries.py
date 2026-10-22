"""Custom-sensor forms tested with real schemas and a minimal HA flow harness."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import voluptuous as vol
from test_protocol import _HA_CONST, _PACKAGE, _load


class FlowHarness:
    """Capture the public flow results without starting Home Assistant."""

    def __init_subclass__(cls, **kwargs):
        pass

    def _get_entry(self):
        return self.entry

    def _get_reconfigure_subentry(self):
        return self.subentry

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

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
        return vol.In(self.options)(value)


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
        modules = patch.dict(sys.modules, {
            "homeassistant.config_entries": config_api,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.config_validation": validation,
            "homeassistant.helpers.selector": selectors,
        })
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
        self.flow = self.module.SonyAdcpCustomSensorFlow()
        self.flow.entry = SimpleNamespace(subentries={})
        self.data = {"name": "Aspect", "command": "aspect", "value_type": "text"}

    async def test_parent_advertises_custom_sensor_type(self):
        self.assertEqual(self.module.SonyAdcpConfigFlow.async_get_supported_subentry_types(
            self.flow.entry
        ), {"custom_sensor": self.module.SonyAdcpCustomSensorFlow})

    async def test_add_form_and_defaults(self):
        result = await self.flow.async_step_user()
        self.assertEqual(result["step_id"], "user")
        validated = result["data_schema"](self.data)
        self.assertEqual(validated["json_field"], "")
        self.assertEqual(validated["unit"], "")
        saved = await self.flow.async_step_user(validated)
        self.assertEqual(saved["type"], "create_entry")
        self.assertEqual(saved["title"], "Aspect")
        self.assertEqual(saved["data"]["command"], "aspect")

    async def test_invalid_command_shows_field_error_without_saving(self):
        result = await self.flow.async_step_user({**self.data, "command": 'power "off"'})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"command": "invalid_command"})

    async def test_edit_replaces_data_and_preserves_subentry(self):
        self.flow.subentry = SimpleNamespace(subentry_id="original", data=self.data)
        result = await self.flow.async_step_reconfigure()
        self.assertEqual(result["data_schema"]({})["command"], "aspect")
        saved = await self.flow.async_step_reconfigure({
            **self.data, "name": "Gamma", "command": "gamma", "value_type": "number",
        })
        self.assertIs(saved["subentry"], self.flow.subentry)
        self.assertEqual(saved["title"], "Gamma")
        self.assertEqual(saved["data"]["unit"], "")

    async def test_text_unit_error_can_be_cleared_during_edit(self):
        self.flow.subentry = SimpleNamespace(data={**self.data, "unit": "%"})
        result = await self.flow.async_step_reconfigure({**self.data, "unit": "%"})
        self.assertEqual(result["errors"], {"unit": "invalid_unit"})
        saved = await self.flow.async_step_reconfigure({**self.data, "unit": ""})
        self.assertEqual(saved["type"], "update")

    async def test_limit_applies_to_add_but_does_not_prevent_edit(self):
        self.flow.entry.subentries = {
            str(index): SimpleNamespace(subentry_type="custom_sensor", data=self.data)
            for index in range(32)
        }
        result = await self.flow.async_step_user(self.data)
        self.assertEqual(result["reason"], "too_many_sensors")
        self.flow.subentry = self.flow.entry.subentries["0"]
        saved = await self.flow.async_step_reconfigure(self.data)
        self.assertEqual(saved["type"], "update")

    async def test_translation_includes_all_fields_errors_and_steps(self):
        root = Path(__file__).parents[1] / "custom_components" / "sony_adcp"
        strings = json.loads((root / "strings.json").read_text())
        self.assertEqual(strings, json.loads((root / "translations/en.json").read_text()))
        translations = strings["config_subentries"]["custom_sensor"]
        for method in (self.flow.async_step_user, self.flow.async_step_reconfigure):
            self.flow.subentry = SimpleNamespace(data=self.data)
            result = await method()
            fields = {str(field) for field in result["data_schema"].schema}
            self.assertEqual(fields, set(translations["step"][result["step_id"]]["data"]))
            description = translations["step"][result["step_id"]]["description"]
            self.assertNotIn("https://", description)
            self.assertIn("documentation_url", result["description_placeholders"])
            self.assertIn("docs/custom-sensors.md", description.format(
                **result["description_placeholders"]
            ))
