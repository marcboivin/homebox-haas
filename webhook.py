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

from .const import DOMAIN, WEBHOOK_ENDPOINT, SIGNAL_ASSET_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_webhook(hass: HomeAssistant, webhook_id: str = None) -> str:
    """Set up a webhook for Homebox."""
    if webhook_id is None:
        # Generate a random webhook ID if none provided
        webhook_id = secrets.token_hex(16)
    
    hass.http.register_view(HomeboxWebhookView(hass, webhook_id))
    
    # Return the webhook URL that can be registered with Homebox
    return f"{hass.config.external_url}/{WEBHOOK_ENDPOINT}/{webhook_id}"


class HomeboxWebhookView(HomeAssistantView):
    """Handle Homebox webhooks."""

    requires_auth = False
    cors_allowed = True
    url = f"/{WEBHOOK_ENDPOINT}/{{webhook_id}}"
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
            
            if webhook_type == "asset.updated":
                await self._handle_asset_updated(data)
            elif webhook_type == "asset.created":
                await self._handle_asset_created(data)
            elif webhook_type == "asset.deleted":
                await self._handle_asset_deleted(data)
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

    async def _handle_asset_updated(self, data: Dict[str, Any]) -> None:
        """Handle asset updated webhook."""
        asset = data.get("data", {})
        asset_id = asset.get("id")
        
        if not asset_id:
            _LOGGER.warning("Received asset update webhook without asset ID")
            return
            
        # Dispatch the signal for automations
        async_dispatcher_send(
            self.hass,
            f"{SIGNAL_ASSET_UPDATED}_{asset_id}",
            asset
        )
        
        # Also send a general signal for any asset update
        async_dispatcher_send(
            self.hass,
            SIGNAL_ASSET_UPDATED,
            asset
        )
        
        _LOGGER.debug(f"Processed asset update webhook for asset {asset_id}")

    async def _handle_asset_created(self, data: Dict[str, Any]) -> None:
        """Handle asset created webhook."""
        # This will force a refresh of all entities
        _LOGGER.debug("Processed asset creation webhook")

    async def _handle_asset_deleted(self, data: Dict[str, Any]) -> None:
        """Handle asset deleted webhook."""
        # This will force a refresh of all entities
        _LOGGER.debug("Processed asset deletion webhook")
