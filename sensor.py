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
    
    # Get the item label filter (if any)
    item_label = entry.data.get(CONF_ASSET_LABEL)
    
    # Get all items from Homebox (filtered by label if provided)
    items = await client.get_items(label=item_label)
    
    if not items:
        _LOGGER.info("No items found in Homebox matching the criteria")
        return
        
    # Create a sensor entity for each item
    entities = []
    for item in items:
        entities.append(HomeboxItemSensor(coordinator, client, item, entry))
        
    async_add_entities(entities)


class HomeboxItemSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Homebox item as a sensor entity."""

    def __init__(self, coordinator, client, item, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.client = client
        self._item = item
        self._entry = entry
        self._attr_unique_id = f"homebox_item_{item['id']}"
        self._attr_name = item.get("name", f"Item {item['id']}")
        self._attr_icon = ENTITY_ICON
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item["id"])},
            name=self._attr_name,
            manufacturer="Homebox",
            model=item.get("model", "Item"),
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
        # Check if location is directly included in the item (nested object)
        if "location" in self._item and isinstance(self._item["location"], dict):
            return self._item["location"].get("name", "Unknown")
            
        # Fall back to looking up by location_id
        location_id = self._item.get("location_id")
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
            "item_id": self._item.get("id"),
            "description": self._item.get("description", ""),
            "purchase_date": self._item.get("purchase_date"),
            "purchase_price": self._item.get("purchase_price"),
            "purchase_from": self._item.get("purchase_from"),
            "warranty_expires": self._item.get("warranty_expires"),
            "labels": self._item.get("labels", []),
            "manufacturer": self._item.get("manufacturer"),
            "model": self._item.get("model"),
            "serial_number": self._item.get("serial_number"),
            "last_updated": self._item.get("updated_at") or self._item.get("updatedAt"),
            "quantity": self._item.get("quantity", 1),
            ATTR_ATTRIBUTION: "Data provided by Homebox",
        }
        
        # Extract location information (either nested or by ID)
        if "location" in self._item and isinstance(self._item["location"], dict):
            location = self._item["location"]
            attributes["location_id"] = location.get("id")
            attributes["location_name"] = location.get("name")
        else:
            attributes["location_id"] = self._item.get("location_id")
            
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
                f"change_location_{self._item['id']}",
                self._service_change_location,
                schema=vol.Schema({vol.Required("location_id"): str}),
            )
        )
        
        # Listen for item update signals from webhook
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_ITEM_UPDATED}_{self._item['id']}",
                self._handle_item_update
            )
        )
        
    @callback
    def _handle_item_update(self, item: dict) -> None:
        """Handle item update from webhook."""
        # Update our local item data
        if item:
            self._item.update(item)
            # Update entity state
            self.async_write_ha_state()

    async def _service_change_location(self, service_call) -> None:
        """Handle the service call to change the item location."""
        location_id = service_call.data["location_id"]
        
        _LOGGER.debug(f"Changing location of item {self._item['id']} to {location_id}")
        success = await self.client.update_item_location(self._item["id"], location_id)
        
        if success:
            # Update the local item data
            self._item["location_id"] = location_id
            self.async_write_ha_state()
            
            # Force a data update via coordinator
            await self.coordinator.async_request_refresh()