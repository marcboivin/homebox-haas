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
    SIGNAL_ITEM_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Homebox sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    
    _LOGGER.debug(f"Setting up Homebox sensors for entry {entry.entry_id}")
    
    # Get the item label filter (if any)
    item_label = entry.data.get(CONF_ASSET_LABEL)
    _LOGGER.debug(f"Using item label filter: {item_label}")
    
    # Get all items from Homebox (filtered by label if provided)
    items = await client.get_items(label=item_label)
    _LOGGER.debug(f"Retrieved {len(items)} items from Homebox")
    
    if items and len(items) > 0:
        # Log the first item to understand its structure
        _LOGGER.debug(f"Sample item structure: {items[0]}")
    
    if not items:
        _LOGGER.info("No items found in Homebox matching the criteria")
        return
    
    # Create a sensor entity for each item
    entities = []
    for item in items:
        _LOGGER.debug(f"Creating sensor for item: {item.get('id')} - {item.get('name')}")
        entities.append(HomeboxItemSensor(coordinator, client, item, entry))
    
    _LOGGER.debug(f"Adding {len(entities)} Homebox entities to Home Assistant")
    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homebox sensors to Home Assistant")


class HomeboxItemSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Homebox item as a sensor entity."""

    def __init__(self, coordinator, client, item, entry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.client = client
        self._item = item
        self._entry = entry
        
        # Get the item ID and name with fallbacks
        item_id = item.get("id") or item.get("_id")
        item_name = item.get("name", f"Item {item_id}")
        
        self._attr_unique_id = f"homebox_item_{item_id}"
        self._attr_name = item_name
        self._attr_icon = ENTITY_ICON
        
        _LOGGER.debug(f"Initializing sensor for item {item_id} - {item_name}")
        
        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, item_id)},
            name=self._attr_name,
            manufacturer="Homebox",
            model=item.get("model", "Item"),
            sw_version=None,
            # Don't use via_device to prevent referencing non-existing devices
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled by default."""
        return True

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        _LOGGER.debug(f"Getting state for sensor {self._attr_name}, item: {self._item}")
        
        # Check if location is directly included in the item (nested object)
        if "location" in self._item and isinstance(self._item["location"], dict):
            location_name = self._item["location"].get("name")
            _LOGGER.debug(f"Found location directly in item: {location_name}")
            return location_name
            
        # Fall back to looking up by location_id
        location_id = self._item.get("location_id")
        if location_id and self.coordinator.data:
            locations = self.coordinator.data.get("locations", [])
            for location in locations:
                if location.get("id") == location_id:
                    location_name = location.get("name")
                    _LOGGER.debug(f"Found location by ID lookup: {location_name}")
                    return location_name
        
        _LOGGER.debug(f"Could not determine location for item {self._attr_name}")
        return "Unknown"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "item_id": self._item.get("id"),
            "asset_id": self._item.get("id"), # Added for backward compatibility with template
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
        
        # Get the item ID safely
        item_id = self._item.get("id") or self._item.get("_id")
        if not item_id:
            _LOGGER.error("Cannot register service for item without ID")
            return
            
        # Register services
        location_service_name = f"change_location_{item_id}"
        _LOGGER.debug(f"Registering service {location_service_name}")
        
        self.async_on_remove(
            self.hass.services.async_register(
                DOMAIN,
                location_service_name,
                self._service_change_location,
                schema=vol.Schema({vol.Required("location_id"): str}),
            )
        )
        
        # Register move item service
        move_service_name = f"move_item_{item_id}"
        _LOGGER.debug(f"Registering service {move_service_name}")
        
        self.async_on_remove(
            self.hass.services.async_register(
                DOMAIN,
                move_service_name,
                self._service_move_item,
                schema=vol.Schema({vol.Required("target_item_id"): str}),
            )
        )
        
        # Listen for item update signals from webhook
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_ITEM_UPDATED}_{item_id}",
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
            
    async def _service_move_item(self, service_call) -> None:
        """Handle the service call to move the item to another item's location."""
        target_item_id = service_call.data["target_item_id"]
        
        _LOGGER.debug(f"Moving item {self._item['id']} to be with item {target_item_id}")
        success = await self.client.move_item(self._item["id"], target_item_id)
        
        if success:
            # Force a data update via coordinator - this will refresh all attributes
            await self.coordinator.async_request_refresh()
            self.async_write_ha_state()