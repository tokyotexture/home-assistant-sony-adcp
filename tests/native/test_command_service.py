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
        self.entry.runtime_data.manager = SimpleNamespace(async_send_command=self.sender)
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

    async def asyncTearDown(self):
        # The fixture has no loaded entity platforms to unload.
        self.entry._async_set_state(self.hass, ConfigEntryState.NOT_LOADED, None)
        await super().asyncTearDown()
