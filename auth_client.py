"""Homebox API Client for authentication and API communication."""
import logging
import time
import requests
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)

class HomeboxAuthClient:
    """Client to handle Homebox authentication and API requests."""

    def __init__(
        self, 
        server_url: str, 
        username: str, 
        password: str, 
        refresh_interval: int = 60,
        verify_ssl: bool = True
    ):
        """Initialize the Homebox client.
        
        Args:
            server_url: Base URL of the Homebox server (without http/https)
            username: Homebox username (usually email)
            password: Homebox password
            refresh_interval: Minutes between token refreshes
            verify_ssl: Whether to verify SSL certificates
        """
        # Store configuration
        self.server_url = server_url.rstrip('/')
        if not self.server_url.startswith(('http://', 'https://')):
            self.server_url = f"https://{self.server_url}"
            
        self.username = username
        self.password = password
        self.refresh_interval = refresh_interval
        self.verify_ssl = verify_ssl
        
        # Authentication state
        self.auth_token = None
        self.token_expiry = None
        self.last_refresh = None
        self.authenticated = False

    async def authenticate(self) -> bool:
        """Authenticate with Homebox and get a new token."""
        auth_url = f"{self.server_url}/api/v1/users/login"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        payload = {
            "username": self.username,
            "password": self.password,
            "stayLoggedIn": True
        }
        
        try:
            response = requests.post(
                auth_url,
                headers=headers,
                json=payload,
                verify=self.verify_ssl
            )
            
            response.raise_for_status()
            auth_data = response.json()
            
            # Store the authentication token
            # Note: This assumes the response format. Adjust based on actual Homebox API response
            self.auth_token = auth_data.get("token")
            
            if not self.auth_token:
                _LOGGER.error("Authentication succeeded but no token was returned")
                self.authenticated = False
                return False
                
            # Set token expiry (if provided in response, otherwise use refresh interval)
            if "expires" in auth_data:
                self.token_expiry = datetime.fromisoformat(auth_data["expires"].replace("Z", "+00:00"))
            else:
                # If no expiry provided, set based on refresh interval
                self.token_expiry = datetime.now() + timedelta(minutes=self.refresh_interval)
                
            self.last_refresh = datetime.now()
            self.authenticated = True
            
            _LOGGER.info("Successfully authenticated with Homebox")
            return True
            
        except requests.exceptions.RequestException as ex:
            _LOGGER.error(f"Failed to authenticate with Homebox: {ex}")
            self.authenticated = False
            return False

    async def ensure_token_valid(self) -> bool:
        """Check if token needs refresh and authenticate if needed."""
        # If never authenticated or token expiry is approaching, authenticate
        if (
            not self.authenticated 
            or not self.auth_token 
            or not self.token_expiry 
            or datetime.now() >= (self.token_expiry - timedelta(minutes=5))
        ):
            return await self.authenticate()
            
        return True

    async def api_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an authenticated request to the Homebox API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path (without leading slash)
            data: Optional JSON data for POST/PUT requests
            params: Optional URL parameters
            
        Returns:
            Dict containing the JSON response from the API
            
        Raises:
            HomeboxAuthError: If authentication fails
            HomeboxApiError: If the API request fails
        """
        # Ensure we have a valid token
        if not await self.ensure_token_valid():
            raise HomeboxAuthError("Failed to authenticate with Homebox")
            
        # Build the request
        url = f"{self.server_url}/api/v1/{endpoint.lstrip('/')}"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.auth_token}"
        }
        
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=data if data else None,
                params=params if params else None,
                verify=self.verify_ssl
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as ex:
            # Check if it's an authentication error
            if response.status_code == 401:
                # Try to re-authenticate once
                if await self.authenticate():
                    # Retry the request with the new token
                    return await self.api_request(method, endpoint, data, params)
                else:
                    raise HomeboxAuthError("Failed to refresh authentication token")
            
            # Other API errors
            raise HomeboxApiError(f"API request failed: {ex}")

    async def test_connection(self) -> bool:
        """Test the connection to Homebox by attempting to authenticate."""
        return await self.authenticate()
        
    async def get_locations(self) -> list:
        """Get all locations from Homebox."""
        try:
            result = await self.api_request("GET", "locations")
            return result.get("data", [])
        except Exception as ex:
            _LOGGER.error(f"Failed to get Homebox locations: {ex}")
            return []
            
    async def create_location(self, name: str) -> bool:
        """Create a new location in Homebox.
        
        Args:
            name: The name of the location to create
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {"name": name}
            result = await self.api_request("POST", "locations", data=data)
            _LOGGER.info(f"Created new Homebox location: {name}")
            return True
        except Exception as ex:
            _LOGGER.error(f"Failed to create Homebox location '{name}': {ex}")
            return False
            
    async def get_assets(self, label: str = None) -> list:
        """Get assets from Homebox, optionally filtered by label.
        
        Args:
            label: Optional label to filter assets by
            
        Returns:
            List of asset objects
        """
        try:
            # Build query parameters if label is provided
            params = {"label": label} if label else None
            
            result = await self.api_request("GET", "assets", params=params)
            return result.get("data", [])
        except Exception as ex:
            _LOGGER.error(f"Failed to get Homebox assets: {ex}")
            return []
            
    async def update_asset_location(self, asset_id: str, location_id: str) -> bool:
        """Update the location of an asset.
        
        Args:
            asset_id: ID of the asset to update
            location_id: ID of the new location
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {"location_id": location_id}
            result = await self.api_request("PATCH", f"assets/{asset_id}", data=data)
            _LOGGER.info(f"Updated location for asset {asset_id} to {location_id}")
            return True
        except Exception as ex:
            _LOGGER.error(f"Failed to update asset location: {ex}")
            return False
            
    async def register_webhook(self, webhook_url: str, events: list = None) -> bool:
        """Register a webhook with Homebox.
        
        Args:
            webhook_url: The URL to send webhooks to
            events: List of event types to subscribe to (default: asset events)
            
        Returns:
            True if successful, False otherwise
        """
        if events is None:
            events = ["asset.created", "asset.updated", "asset.deleted"]
            
        try:
            data = {
                "url": webhook_url,
                "events": events,
                "is_active": True
            }
            
            result = await self.api_request("POST", "webhooks", data=data)
            _LOGGER.info(f"Registered webhook with Homebox: {webhook_url}")
            return True
        except Exception as ex:
            _LOGGER.error(f"Failed to register webhook: {ex}")
            return False
            
    async def list_webhooks(self) -> list:
        """List all registered webhooks.
        
        Returns:
            List of webhook objects
        """
        try:
            result = await self.api_request("GET", "webhooks")
            return result.get("data", [])
        except Exception as ex:
            _LOGGER.error(f"Failed to list webhooks: {ex}")
            return []


class HomeboxAuthError(Exception):
    """Exception raised for Homebox authentication errors."""
    pass


class HomeboxApiError(Exception):
    """Exception raised for Homebox API errors."""
    pass
