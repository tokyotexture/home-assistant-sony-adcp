"""Validate the copyable guide against real HA schemas and template rendering."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import test_device_ownership as ownership
import yaml
from homeassistant.components.automation.config import PLATFORM_SCHEMA
from homeassistant.components.homeassistant.triggers import state as state_trigger
from homeassistant.components.script.config import SCRIPT_ENTITY_SCHEMA
from homeassistant.core import State
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.template import Template

from custom_components.sony_adcp.command_request import validate_query_request, validate_request
from custom_components.sony_adcp.protocol import CommandInfo
from custom_components.sony_adcp.services import QUERY_COMMAND_SCHEMA, SEND_COMMAND_SCHEMA

_GUIDE = Path(__file__).parents[2] / "docs" / "automation-examples.md"


class DocumentationExamplesTest(ownership.DeviceOwnershipFixture):
    def examples(self):
        return [yaml.safe_load(block) for block in re.findall(
            r"^```yaml\n(.*?)^```", _GUIDE.read_text(), re.MULTILINE | re.DOTALL
        )]

    async def test_complete_examples_use_real_ha_schemas(self):
        examples = self.examples()
        self.assertEqual(len(examples), 4)
        for config in examples:
            with self.subTest(alias=config["alias"]):
                if "triggers" in config:
                    PLATFORM_SCHEMA(deepcopy(config))
                    for trigger in cv.TRIGGER_SCHEMA(config["triggers"]):
                        await state_trigger.async_validate_trigger_config(self.hass, trigger)
                else:
                    SCRIPT_ENTITY_SCHEMA(deepcopy(config))

    async def test_query_and_write_payloads_match_registered_services(self):
        queries = 0
        for config in self.examples():
            for step in config.get("sequence", config.get("actions", [])):
                action = step.get("action")
                if action == "sony_adcp.query_command":
                    payload = QUERY_COMMAND_SCHEMA(step["data"])
                    self.assertEqual(validate_query_request(payload).command, "aspect")
                    self.assertTrue(step["response_variable"])
                    self.assertNotIn("target", step)
                    queries += 1
                elif action == "sony_adcp.send_command":
                    payload = deepcopy(step["data"])
                    payload["value"] = Template(payload["value"], self.hass).async_render(
                        config["variables"]
                    )
                    request = validate_request(SEND_COMMAND_SCHEMA(payload))
                    info = CommandInfo("aspect", "menu_sel", choices=("normal", "zoom"))
                    self.assertEqual(request.encode(info), 'aspect "normal"')
        self.assertEqual(queries, 5)

    async def test_choice_guard_requires_matching_metadata_and_exact_choice(self):
        script = self.examples()[1]
        guard = Template(script["sequence"][1]["value_template"], self.hass)
        for metadata, expected in (
            ({"type": "menu_sel", "range": ["normal", "zoom"]}, True),
            ({"type": "menu_sel", "range": ["NORMAL"]}, False),
            ({"type": "menu_sel", "range": "normal"}, False),
            ({"type": "menu_sel", "range": {"normal": 1}}, False),
            ({"type": "menu_num", "range": ["normal"]}, False),
            ({"type": "menu_sel"}, False), ({}, False), ("normal", False), (None, False),
        ):
            with self.subTest(metadata=metadata):
                self.assertIs(guard.async_render({
                    "aspect_info": {"data": metadata}, "desired_aspect": "normal"
                }), expected)

    async def test_startup_wait_needs_confirmed_on_and_finished_monitor(self):
        script = self.examples()[3]
        wait = script["sequence"][1]
        self.assertFalse(wait["continue_on_timeout"])
        self.assertEqual(wait["timeout"], "00:01:15")
        guard = Template(wait["wait_template"], self.hass)
        for entity_state, power, transition, expected in (
            ("on", "startup", "on", False), ("on", "cooling2", None, False),
            ("on", "on", "on", False), ("on", "on", None, True),
            ("unavailable", "on", None, False), ("unknown", None, None, False),
        ):
            self.hass.states.async_set("media_player.projector", entity_state, {
                "sony_power_status": power, "power_transition": transition
            })
            self.assertIs(guard.async_render(script["variables"]), expected)

    async def test_monitor_filters_unavailable_and_attribute_only_changes(self):
        automation = self.examples()[2]
        trigger = automation["triggers"][0]
        self.assertEqual(trigger["not_from"], ["unknown", "unavailable"])
        self.assertEqual(trigger["not_to"], ["unknown", "unavailable"])
        guard = Template(automation["conditions"][0]["value_template"], self.hass)
        for before, after, expected in (
            (None, State("sensor.projector_aspect_ratio", "normal"), False),
            (State("sensor.projector_aspect_ratio", "normal"), None, False),
            (State("sensor.projector_aspect_ratio", "normal"),
             State("sensor.projector_aspect_ratio", "normal", {"new_attribute": 1}), False),
            (State("sensor.projector_aspect_ratio", "normal"),
             State("sensor.projector_aspect_ratio", "zoom"), True),
        ):
            self.assertIs(guard.async_render({
                "trigger": SimpleNamespace(from_state=before, to_state=after)
            }), expected)
