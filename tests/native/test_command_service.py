"""Exercise registration, device routing, permissions and responses in real HA."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_device_ownership as ownership
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError, Unauthorized

from custom_components.sony_adcp import async_setup
from custom_components.sony_adcp import services as command_services


class CommandServiceTest(ownership.DeviceOwnershipFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.entry._async_set_state(self.hass, ConfigEntryState.LOADED, None)
        self.hass.auth = SimpleNamespace(
            async_get_user=AsyncMock(return_value=SimpleNamespace(is_admin=True))
        )
        async def send(request, *, result):
            result.update(response="ok", readback="updated", value="6500K")
            return result
        self.sender = AsyncMock(side_effect=send)
        self.querier = AsyncMock(return_value={
            "command": "aspect", "query_type": "value", "response": "normal", "data": "normal"
        })
        self.entry.runtime_data.manager = SimpleNamespace(
            async_send_command=self.sender, async_query_command=self.querier
        )
        with patch("custom_components.sony_adcp.async_get_listener", AsyncMock()):
            await async_setup(self.hass, {})
        self.data = {"device_id": self.device_id, "command": "color_temp", "value": "6500K"}

    async def call(self, data=None, **kwargs):
        return await self.hass.services.async_call(
            "sony_adcp", "send_command", self.data if data is None else data,
            blocking=True, **kwargs,
        )

    async def test_real_registration_routing_and_optional_response(self):
        response = await self.call(return_response=True, context=Context(user_id="admin"))
        self.assertEqual(response, {"response": "ok", "readback": "updated", "value": "6500K"})
        request = self.sender.call_args.args[0]
        self.assertEqual((request.command, request.operation, request.value),
                         ("color_temp", "set", "6500K"))
        self.assertIsNone(await self.call())

    async def test_non_admin_cannot_send_commands(self):
        self.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
        with self.assertRaises(Unauthorized):
            await self.call(context=Context(user_id="not-admin"))
        self.sender.assert_not_awaited()

    async def test_missing_device_and_unloaded_entry_are_clear_errors(self):
        with self.assertRaises(ServiceValidationError):
            await self.call({**self.data, "device_id": "missing"})
        self.entry._async_set_state(self.hass, ConfigEntryState.NOT_LOADED, None)
        with self.assertRaises(ServiceValidationError):
            await self.call()
        self.assertTrue(self.hass.services.has_service("sony_adcp", "send_command"))
        self.sender.assert_not_awaited()

    async def test_invalid_payload_never_reaches_manager(self):
        with self.assertRaises(ServiceValidationError):
            await self.call({**self.data, "command": "color_temp\r\npower"})
        self.sender.assert_not_awaited()

    async def test_readback_deadline_keeps_acknowledged_success(self):
        async def send(request, *, result):
            result.update(response="ok", readback="not_configured")
            await asyncio.Event().wait()
        self.sender.side_effect = send
        with patch.object(command_services, "COMMAND_ACTION_TIMEOUT", 0.02):
            response = await self.call(return_response=True)
        self.assertEqual(response, {"response": "ok", "readback": "failed"})
        self.assertEqual(self.sender.await_count, 1)

    async def test_deadline_before_ack_raises_instead_of_returning_error_codes(self):
        async def send(request, *, result):
            await asyncio.Event().wait()
        self.sender.side_effect = send
        with patch.object(command_services, "COMMAND_ACTION_TIMEOUT", 0.02):
            with self.assertRaises(HomeAssistantError) as error:
                await self.call(return_response=True)
        self.assertEqual(error.exception.translation_key, "command_outcome_unknown")

    async def query(self, **kwargs):
        data = kwargs.pop("data", {"device_id": self.device_id, "command": "aspect"})
        return await self.hass.services.async_call(
            "sony_adcp", "query_command", data, blocking=True, **kwargs
        )

    async def test_query_registration_default_type_and_required_response(self):
        response = await self.query(return_response=True, context=Context(user_id="admin"))
        self.assertEqual(response["data"], "normal")
        request = self.querier.call_args.args[0]
        self.assertEqual((request.command, request.query_type), ("aspect", "value"))
        with self.assertRaises(ServiceValidationError):
            await self.query()
        self.sender.assert_not_awaited()

    async def test_query_permissions_and_invalid_payload(self):
        self.hass.auth.async_get_user.return_value = SimpleNamespace(is_admin=False)
        with self.assertRaises(Unauthorized):
            await self.query(return_response=True, context=Context(user_id="not-admin"))
        for data in (
            {"device_id": self.device_id, "command": "aspect --reset"},
            {"device_id": self.device_id, "command": "aspect", "value": "zoom"},
            {"device_id": self.device_id, "command": "aspect", "query_type": "execute"},
            {"device_id": "missing", "command": "aspect"},
        ):
            with self.assertRaises(ServiceValidationError):
                await self.query(data=data, return_response=True)
        self.querier.assert_not_awaited()

    async def test_query_deadline_is_not_an_uncertain_write(self):
        async def slow(request):
            await asyncio.Event().wait()
        self.querier.side_effect = slow
        with patch.object(command_services, "COMMAND_ACTION_TIMEOUT", 0.02):
            with self.assertRaises(HomeAssistantError) as error:
                await self.query(return_response=True)
        self.assertEqual(error.exception.translation_key, "query_timeout")

    async def test_query_error_translation_and_structured_response(self):
        self.querier.side_effect = command_services.AdcpCommandError("aspect ?", "err_inactive")
        with self.assertRaises(HomeAssistantError) as error:
            await self.query(return_response=True)
        self.assertEqual(error.exception.translation_key, "query_rejected")
        self.assertEqual(error.exception.translation_placeholders, {"response": "err_inactive"})
        self.querier.side_effect = None
        self.querier.return_value = {
            "command": "contrast", "query_type": "range", "response": '{"min":0,"max":100}',
            "data": {"min": 0, "max": 100},
        }
        response = await self.query(
            data={"device_id": self.device_id, "command": "contrast", "query_type": "range"},
            return_response=True,
        )
        self.assertEqual(response["data"]["max"], 100)

    async def asyncTearDown(self):
        # The fixture has no loaded entity platforms to unload.
        self.entry._async_set_state(self.hass, ConfigEntryState.NOT_LOADED, None)
        await super().asyncTearDown()
