"""Constants for the Homebox integration."""

# Integration domain
DOMAIN = "homebox"

# Default values
DEFAULT_SCAN_INTERVAL = 60  # minutes
DEFAULT_VERIFY_SSL = False

# Configuration and options
CONF_REFRESH_TOKEN = "refresh_token"

# API paths
API_ENDPOINT_LOGIN = "users/login"
API_ENDPOINT_LOCATIONS = "locations"
DEFAULT_USE_HTTPS = False
CONF_USE_HTTPS = "Use HTTPS?"

# Synchronization settings
SYNC_LOCATIONS_INTERVAL = 86400  # Sync locations once per day (in seconds)

# Entity platforms this integration provides
PLATFORMS = []  # We'll add these as we implement entity support

CONF_ASSET_LABEL = "Asset Label"

CONF_WEBHOOK_ID = "CONF_WEBHOOK_ID"

WEBHOOK_ENDPOINT = "WEBHOOK_ENDPOINT"

SIGNAL_ASSET_UPDATED = "SIGNAL_ASSET_UPDATED"

ENTITY_DEVICE_CLASS = "ENTITY_DEVICE_CLASS"
ENTITY_ICON = "mdi:alpha-c-circle"

SIGNAL_ASSET_UPDATED = "SIGNAL_ASSET_UPDATED"
SIGNAL_ITEM_UPDATED = "SIGNAL_ITEM_UPDATED"