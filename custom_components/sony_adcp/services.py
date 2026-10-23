"""Home Assistant actions for structured, administrator-only ADCP requests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service

from .command_request import (
    OPERATIONS,
    QUERY_TYPES,
    CommandValidationError,
    validate_query_request,
    validate_request,
)
from .const import DOMAIN
from .protocol import AdcpAuthenticationError, AdcpCommandError, AdcpError, AdcpOutcomeUnknownError

if TYPE_CHECKING:
    from . import SonyAdcpConfigEntry

SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("command"): cv.string,
        vol.Optional("operation", default="set"): vol.In(OPERATIONS),
        vol.Optional("value"): vol.Any(str, int, float),
    }
)
COMMAND_ACTION_TIMEOUT = 30
QUERY_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("command"): cv.string,
        vol.Optional("query_type", default="value"): vol.In(QUERY_TYPES),
    }
)


def _entry_for_device(hass: HomeAssistant, device_id: str) -> SonyAdcpConfigEntry:
    """Resolve exactly one loaded Sony owner across both registry API versions."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="command_device_invalid"
        )
    entry_ids = (
        [device.config_entry_id] if hasattr(device, "config_entry_id") else device.config_entries
    )
    entries = [
        entry for entry_id in entry_ids
        if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
        and entry.domain == DOMAIN
    ]
    if len(entries) != 1 or entries[0].state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="command_not_ready")
    return entries[0]


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register once in async_setup, including when no projector is loaded."""
    async def async_send_command(call: ServiceCall) -> ServiceResponse:
        result: dict[str, str] = {}
        try:
            request = validate_request(call.data)
            entry = _entry_for_device(hass, call.data["device_id"])
            async with asyncio.timeout(COMMAND_ACTION_TIMEOUT):
                await entry.runtime_data.manager.async_send_command(request, result=result)
        except CommandValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
        except AdcpCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={"response": err.response},
            ) from err
        except AdcpAuthenticationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_authentication"
            ) from err
        except (AdcpOutcomeUnknownError, TimeoutError) as err:
            if result.get("response") == "ok":
                # Do not misreport an acknowledged write as failed just because
                # subsequent status reads timed out: scripts might resend it.
                result["readback"] = "failed"
                return result if call.return_response else None
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_outcome_unknown"
            ) from err
        except AdcpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_connection"
            ) from err
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="command_value_invalid"
            ) from err
        return result if call.return_response else None

    service.async_register_admin_service(
        hass, DOMAIN, "send_command", async_send_command,
        schema=SEND_COMMAND_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )

    async def async_query_command(call: ServiceCall) -> ServiceResponse:
        try:
            request = validate_query_request(call.data)
            entry = _entry_for_device(hass, call.data["device_id"])
            async with asyncio.timeout(COMMAND_ACTION_TIMEOUT):
                return await entry.runtime_data.manager.async_query_command(request)
        except CommandValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=str(err)
            ) from err
        except AdcpCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="query_rejected",
                translation_placeholders={"response": err.response},
            ) from err
        except AdcpAuthenticationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_authentication"
            ) from err
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="query_timeout"
            ) from err
        except AdcpError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_connection"
            ) from err

    service.async_register_admin_service(
        hass, DOMAIN, "query_command", async_query_command,
        schema=QUERY_COMMAND_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
