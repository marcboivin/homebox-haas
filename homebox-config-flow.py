"""Config flow for Homebox integration."""
import logging
import voluptuous as vol
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_URL,
    CONF_VERIFY_SSL,
    CONF_SCAN_INTERVAL,
)

from .auth_client import HomeboxAuthClient
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_VERIFY_SSL

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect to Homebox.
    
    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Create client
    client = HomeboxAuthClient(
        server_url=data[CONF_URL],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        refresh_interval=data[CONF_SCAN_INTERVAL],
        verify_ssl=data[CONF_VERIFY_SSL]
    )
    
    # Test connection and auth
    if not await client.test_connection():
        raise CannotConnect
        
    # Return info to be stored in the config entry
    return {"title": f"Homebox ({data[CONF_URL]})"}


class HomeboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Homebox."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL
    
    def __init__(self):
        """Initialize the config flow."""
        self._reauth_entry = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # If this is a reauth, update the config entry
                if self._reauth_entry:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry, data=user_input
                    )
                    await self.hass.config_entries.async_reload(
                        self._reauth_entry.entry_id
                    )
                    return self.async_abort(reason="reauth_successful")
                
                # Otherwise create a new entry
                return self.async_create_entry(title=info["title"], data=user_input)
                
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # Show form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): str,
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
                    vol.Optional(
                        CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL
                    ): bool,
                    vol.Optional(CONF_ASSET_LABEL): str,
                }
            ),
            errors=errors,
        )
        
    async def async_step_reauth(self, user_input=None):
        """Handle configuration by re-auth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""
    pass
