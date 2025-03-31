"""Constants for the Homebox integration."""

# Integration domain
DOMAIN = "homebox"

# Default values
DEFAULT_SCAN_INTERVAL = 60  # minutes
DEFAULT_VERIFY_SSL = False

# Configuration and options
CONF_REFRESH_TOKEN = "refresh_token"

CONF_ASSET_LABEL = "Asset Label"

# API paths
API_ENDPOINT_LOGIN = "users/login"
API_ENDPOINT_LOCATIONS = "locations"

# Synchronization settings
SYNC_LOCATIONS_INTERVAL = 86400  # Sync locations once per day (in seconds)

# Entity platforms this integration provides
PLATFORMS = []  # We'll add these as we implement entity support