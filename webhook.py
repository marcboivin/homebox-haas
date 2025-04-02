"""Webhook support for Homebox integration."""
import logging
import json
import secrets
import hashlib
from typing import Dict, Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, WEBHOOK_ENDPOINT, SIGNAL_ITEM_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_webhook(hass: HomeAssistant, webhook_id: str = None) -> str:
    """Set up a webhook for Homebox."""
    if webhook_id is None:
        # Generate a random webhook ID if none provided
        webhook_id = secrets.token_hex(16)
    
    hass.http.register_view(HomeboxWebhookView(hass, webhook_id))
    
    # Get the external URL from Home Assistant config
    external_url = hass.config.external_url
    if not external_url:
        _LOGGER.warning("External URL not configured. Webhook functionality disabled.")
        return None
    
    # Parse external URL to get host and port
    from urllib.parse import urlparse
    parsed_url = urlparse(external_url)
    
    # Get host without the scheme
    host = parsed_url.netloc
    
    # If no port specified, use default ports
    if ":" not in host:
        port = "443" if parsed_url.scheme == "https" else "80"
        host = f"{host}:{port}"
    
    # Create a webhook URL in the shoutrrr format required by Homebox
    # Format: generic://host:port/api/webhook/webhook_id?template=json&disabletls=yes
    disabletls = "yes" if parsed_url.scheme == "http" else "no"
    shoutrrr_url = f"generic://{host}/api/webhook/{webhook_id}?template=json&disabletls={disabletls}"
    
    _LOGGER.debug(f"Created shoutrrr webhook URL: {shoutrrr_url}")
    
    return shoutrrr_url


class HomeboxWebhookView(HomeAssistantView):
    """Handle Homebox webhooks."""

    requires_auth = False
    cors_allowed = True
    url = f"/api/webhook/{{webhook_id}}"
    name = f"{DOMAIN}_webhook"

    def __init__(self, hass: HomeAssistant, webhook_id: str):
        """Initialize the webhook view."""
        self.hass = hass
        self.webhook_id = webhook_id

    async def post(self, request: web.Request, webhook_id: str) -> web.Response:
        """Handle POST requests for the webhook."""
        if webhook_id != self.webhook_id:
            return web.Response(status=404)

        try:
            data = await request.json()
        except json.decoder.JSONDecodeError:
            return web.Response(status=400)

        try:
            webhook_type = data.get("type", "unknown")
            
            if webhook_type == "item.updated":
                await self._handle_item_updated(data)
            elif webhook_type == "item.created":
                await self._handle_item_created(data)
            elif webhook_type == "item.deleted":
                await self._handle_item_deleted(data)
            else:
                _LOGGER.warning(f"Unhandled webhook type: {webhook_type}")
                
            # Trigger a coordinator refresh
            for entry_id in self.hass.data.get(DOMAIN, {}):
                if "coordinator" in self.hass.data[DOMAIN][entry_id]:
                    coordinator = self.hass.data[DOMAIN][entry_id]["coordinator"]
                    await coordinator.async_request_refresh()

            return web.Response(status=200)
            
        except Exception as ex:
            _LOGGER.error(f"Error handling webhook: {ex}")
            return web.Response(status=500)

    async def _handle_item_updated(self, data: Dict[str, Any]) -> None:
        """Handle item updated webhook."""
        item = data.get("data", {})
        item_id = item.get("id")
        
        if not item_id:
            _LOGGER.warning("Received item update webhook without item ID")
            return
            
        # Dispatch the signal for automations
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_ITEM_UPDATED}_{item_id}",
            item
        )
        
        # Also send a general signal for any item update
        async_dispatcher_send(
            self.hass,
            SIGNAL_ITEM_UPDATED,
            item
        )
        
        _LOGGER.debug(f"Processed item update webhook for item {item_id}")

    async def _handle_item_created(self, data: Dict[str, Any]) -> None:
        """Handle item created webhook."""
        # This will force a refresh of all entities
        _LOGGER.debug("Processed item creation webhook")

    async def _handle_item_deleted(self, data: Dict[str, Any]) -> None:
        """Handle item deleted webhook."""
        # This will force a refresh of all entities
        _LOGGER.debug("Processed item deletion webhook")