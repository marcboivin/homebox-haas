"""The Homebox integration."""
import asyncio
import logging
import voluptuous as vol
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_URL,
    CONF_VERIFY_SSL,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth_client import HomeboxAuthClient, HomeboxAuthError, HomeboxApiError
from .const import DOMAIN, PLATFORMS, CONF_ASSET_LABEL, CONF_WEBHOOK_ID, CONF_USE_HTTPS, DEFAULT_USE_HTTPS
from .webhook import async_setup_webhook

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homebox from a config entry."""
    # Get configuration
    server_url = entry.data[CONF_URL]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, 60)  # minutes
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    use_https = entry.data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
    
    # Create API client
    client = HomeboxAuthClient(
        server_url=server_url,
        username=username,
        password=password,
        refresh_interval=scan_interval,
        verify_ssl=verify_ssl,
        use_https=use_https
    )
    
    # Attempt initial authentication
    try:
        if not await client.authenticate():
            raise ConfigEntryAuthFailed("Failed to authenticate with Homebox")
    except (HomeboxAuthError, HomeboxApiError) as ex:
        _LOGGER.error("Error authenticating with Homebox: %s", ex)
        raise ConfigEntryAuthFailed(f"Authentication error: {ex}")
    
    # Create update coordinator
    coordinator = HomeboxDataUpdateCoordinator(
        hass,
        client=client,
        name=DOMAIN,
        update_interval=timedelta(minutes=scan_interval)
    )
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Set up webhook for real-time updates if external URL is configured
    if hass.config.external_url:
        # Use existing webhook_id or create a new one
        webhook_id = entry.data.get(CONF_WEBHOOK_ID)
        webhook_url = await async_setup_webhook(hass, webhook_id)
        
        # Register webhook with Homebox if we got a valid URL
        if webhook_url:
            if await client.register_webhook(webhook_url):
                # Save webhook_id if it's new
                if CONF_WEBHOOK_ID not in entry.data:
                    new_data = {**entry.data, CONF_WEBHOOK_ID: webhook_id}
                    hass.config_entries.async_update_entry(entry, data=new_data)
        else:
            _LOGGER.warning("Could not create a valid webhook URL. Webhook functionality disabled.")
    else:
        _LOGGER.warning(
            "External URL not configured. Webhook functionality disabled. "
            "Configure external_url in configuration.yaml to enable webhooks."
        )
    
    # Store client and coordinator for platforms to access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }
    
    # Synchronize Home Assistant areas to Homebox locations
    await sync_locations(hass, client)
    
    # Register service to manually synchronize locations
    async def handle_sync_locations(call):
        """Handle the service call to synchronize locations."""
        if entry.entry_id in hass.data[DOMAIN]:
            client = hass.data[DOMAIN][entry.entry_id]["client"]
            await sync_locations(hass, client)
    
    hass.services.async_register(
        DOMAIN, "sync_locations", handle_sync_locations
    )
    
    # Register service to change item location
    async def handle_change_item_location(call):
        """Handle the service call to change an item's location."""
        item_id = call.data.get("item_id")
        location_id = call.data.get("location_id")
        
        if not item_id or not location_id:
            _LOGGER.error("Missing required parameters: item_id and location_id")
            return
            
        if entry.entry_id in hass.data[DOMAIN]:
            client = hass.data[DOMAIN][entry.entry_id]["client"]
            await client.update_item_location(item_id, location_id)
            
            # Force coordinator to refresh data
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            await coordinator.async_request_refresh()
    
    hass.services.async_register(
        DOMAIN, 
        "change_item_location", 
        handle_change_item_location,
        schema=vol.Schema({
            vol.Required("item_id"): str,
            vol.Required("location_id"): str,
        })
    )
    
    # Register service for changing asset location (legacy service)
    async def handle_change_asset_location(call):
        """Handle the service call to change an asset's location."""
        asset_id = call.data.get("asset_id")
        location_id = call.data.get("location_id")
        
        if not asset_id or not location_id:
            _LOGGER.error("Missing required parameters: asset_id and location_id")
            return
            
        if entry.entry_id in hass.data[DOMAIN]:
            client = hass.data[DOMAIN][entry.entry_id]["client"]
            await client.update_item_location(asset_id, location_id)
            
            # Force coordinator to refresh data
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            await coordinator.async_request_refresh()
    
    hass.services.async_register(
        DOMAIN, 
        "change_asset_location", 
        handle_change_asset_location,
        schema=vol.Schema({
            vol.Required("asset_id"): str,
            vol.Required("location_id"): str,
        })
    )
    
    # Register a more intuitive "move_item" service that's an alias to change_item_location
    async def handle_move_item(call):
        """Handle the service call to move an item to a different location."""
        item_id = call.data.get("item_id")
        location_id = call.data.get("location_id")
        
        if not item_id or not location_id:
            _LOGGER.error("Missing required parameters: item_id and location_id")
            return
            
        if entry.entry_id in hass.data[DOMAIN]:
            client = hass.data[DOMAIN][entry.entry_id]["client"]
            await client.update_item_location(item_id, location_id)
            
            # Force coordinator to refresh data
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            await coordinator.async_request_refresh()
    
    hass.services.async_register(
        DOMAIN, 
        "move_item", 
        handle_move_item,
        schema=vol.Schema({
            vol.Required("item_id"): str,
            vol.Required("location_id"): str,
        })
    )
    
    # Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Add update listener for config entry changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    # Clean up
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def sync_locations(hass: HomeAssistant, client: HomeboxAuthClient) -> None:
    """Synchronize Home Assistant areas to Homebox locations.
    
    This creates locations in Homebox for each area in Home Assistant
    that doesn't already exist in Homebox.
    """
    _LOGGER.info("Synchronizing Home Assistant areas to Homebox locations")
    
    try:
        # Get Home Assistant areas
        area_reg = ar.async_get(hass)
        ha_areas = {area.name for area in area_reg.async_list_areas()}
        
        # Get Homebox locations
        homebox_locations = await client.get_locations()
        homebox_location_names = {loc.get("name") for loc in homebox_locations}
        
        # Find areas that need to be created in Homebox
        missing_locations = ha_areas - homebox_location_names
        
        if not missing_locations:
            _LOGGER.info("All Home Assistant areas already exist in Homebox")
            return
            
        # Create missing locations in Homebox
        _LOGGER.info(f"Creating {len(missing_locations)} new locations in Homebox")
        
        for location_name in missing_locations:
            await client.create_location(location_name)
            
        _LOGGER.info("Location synchronization complete")
        
    except Exception as ex:
        _LOGGER.error(f"Error synchronizing locations: {ex}")
        # We don't want to fail the entire integration if location sync fails
        # so we just log the error and continue


class HomeboxDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Homebox data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HomeboxAuthClient,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.hass = hass
        self.last_sync_time = None
        
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Fetch data from Homebox API."""
        try:
            # Ensure the token is valid before making any requests
            if not await self.client.ensure_token_valid():
                raise UpdateFailed("Failed to authenticate with Homebox")
            
            # Periodic location sync (once per day)
            current_time = datetime.now()
            if (not self.last_sync_time or 
                (current_time - self.last_sync_time).total_seconds() > 86400):  # 24 hours
                _LOGGER.info("Performing daily location synchronization")
                await sync_locations(self.hass, self.client)
                self.last_sync_time = current_time
            
            # Get asset label filter (if any)
            # We need to find the config entry from one of our client instances
            config_entries = self.hass.config_entries.async_entries(DOMAIN)
            asset_label = None
            for entry in config_entries:
                if CONF_ASSET_LABEL in entry.data:
                    asset_label = entry.data[CONF_ASSET_LABEL]
                    break
            
            # Fetch items and locations
            items = await self.client.get_items(label=asset_label)
            locations = await self.client.get_locations()
            
            return {
                "items": items,
                "locations": locations,
                "last_update": datetime.now(),
            }
            
        except HomeboxAuthError as ex:
            _LOGGER.error("Authentication error: %s", ex)
            raise ConfigEntryAuthFailed(f"Authentication error: {ex}")
        except HomeboxApiError as ex:
            _LOGGER.error("Error fetching data: %s", ex)
            raise UpdateFailed(f"Error fetching data: {ex}")
