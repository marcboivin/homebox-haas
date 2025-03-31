"""Sensor platform for Homebox integration."""
import logging
import voluptuous as vol
from typing import Any, Callable, Dict, List, Optional, Union

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_URL, ATTR_ATTRIBUTION
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .auth_client import HomeboxAuthClient
from .const import (
    CONF_ASSET_LABEL,
    DOMAIN,
    ENTITY_DEVICE_CLASS,
    ENTITY_ICON,
    SIGNAL_ASSET_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homebox sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    
    # Get the asset label filter (if any)
    asset_label = entry.data.get(CONF_ASSET_LABEL)
    
    # Get all assets from Homebox (filtered by label if provided)
    assets = await client.get_assets(label=asset_label)
    
    if not assets:
        _LOGGER.info("No assets found in Homebox matching the criteria")
        return
        
    # Create a sensor entity for each asset
    entities = []
    for asset in assets:
        entities.append(HomeboxAssetSensor(coordinator, client, asset, entry))
        
    async_add_entities(entities)


class HomeboxAssetSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Homebox asset as a sensor entity."""

    def __init__(self, coordinator, client, asset, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.client = client
        self._asset = asset
        self._entry = entry
        self._attr_unique_id = f"homebox_asset_{asset['id']}"
        self._attr_name = asset.get("name", f"Asset {asset['id']}")
        self._attr_icon = ENTITY_ICON
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset["id"])},
            name=self._attr_name,
            manufacturer="Homebox",
            model=asset.get("model", "Asset"),
            sw_version=None,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled by default."""
        return True

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        # The state of the sensor is the current location name
        location_id = self._asset.get("location_id")
        if location_id and self.coordinator.data:
            locations = self.coordinator.data.get("locations", [])
            for location in locations:
                if location.get("id") == location_id:
                    return location.get("name")
        
        return "Unknown"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "asset_id": self._asset.get("id"),
            "description": self._asset.get("description", ""),
            "purchase_date": self._asset.get("purchase_date"),
            "purchase_price": self._asset.get("purchase_price"),
            "purchase_from": self._asset.get("purchase_from"),
            "warranty_expires": self._asset.get("warranty_expires"),
            "location_id": self._asset.get("location_id"),
            "labels": self._asset.get("labels", []),
            "manufacturer": self._asset.get("manufacturer"),
            "model": self._asset.get("model"),
            "serial_number": self._asset.get("serial_number"),
            "last_updated": self._asset.get("updated_at"),
            ATTR_ATTRIBUTION: "Data provided by Homebox",
        }
        
        # Add all available locations to allow changing location from Lovelace
        if self.coordinator.data and "locations" in self.coordinator.data:
            attributes["all_locations"] = self.coordinator.data["locations"]
            
        return attributes

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        
        # Register services
        self.async_on_remove(
            self.hass.services.async_register(
                DOMAIN,
                f"change_location_{self._asset['id']}",
                self._service_change_location,
                schema=vol.Schema({vol.Required("location_id"): str}),
            )
        )
        
        # Listen for asset update signals from webhook
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_ASSET_UPDATED}_{self._asset['id']}",
                self._handle_asset_update
            )
        )
        
    @callback
    def _handle_asset_update(self, asset: dict) -> None:
        """Handle asset update from webhook."""
        # Update our local asset data
        if asset:
            self._asset.update(asset)
            # Update entity state
            self.async_write_ha_state()

    async def _service_change_location(self, service_call) -> None:
        """Handle the service call to change the asset location."""
        location_id = service_call.data["location_id"]
        
        _LOGGER.debug(f"Changing location of asset {self._asset['id']} to {location_id}")
        success = await self.client.update_asset_location(self._asset["id"], location_id)
        
        if success:
            # Update the local asset data
            self._asset["location_id"] = location_id
            self.async_write_ha_state()
            
            # Force a data update via coordinator
            await self.coordinator.async_request_refresh()
