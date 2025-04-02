"""Homebox API Client for authentication and API communication."""
import logging
import time
import aiohttp
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
        verify_ssl: bool = True,
        use_https: bool = True
    ):
        """Initialize the Homebox client.
        
        Args:
            server_url: Base URL of the Homebox server (without http/https)
            username: Homebox username (usually email)
            password: Homebox password
            refresh_interval: Minutes between token refreshes
            verify_ssl: Whether to verify SSL certificates
            use_https: Whether to use HTTPS or HTTP
        """
        # Store configuration
        self.server_url = server_url.rstrip('/')
        if not self.server_url.startswith(('http://', 'https://')):
            protocol = "https" if use_https else "http"
            self.server_url = f"{protocol}://{self.server_url}"
            
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
        
        _LOGGER.debug(f"Authenticating with Homebox at {auth_url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    auth_url,
                    headers=headers,
                    json=payload,
                    ssl=None if not self.verify_ssl else True
                ) as response:
                    response_text = await response.text()
                    _LOGGER.debug(f"Authentication response status: {response.status}, body: {response_text[:200]}")
                    
                    response.raise_for_status()
                    auth_data = await response.json()
                    
                    # Store the authentication token
                    # Extract token from response - adjust based on actual Homebox API response format
                    if "token" in auth_data:
                        self.auth_token = auth_data["token"]
                        _LOGGER.debug(f"Received token: {self.auth_token[:10]}...")
                    elif "data" in auth_data and "token" in auth_data["data"]:
                        self.auth_token = auth_data["data"]["token"]
                        _LOGGER.debug(f"Received token from data object: {self.auth_token[:10]}...")
                    else:
                        _LOGGER.error(f"Authentication response doesn't contain token: {auth_data}")
                        self.authenticated = False
                        return False
                    
                    if not self.auth_token:
                        _LOGGER.error("Authentication succeeded but no token was extracted")
                        self.authenticated = False
                        return False
                        
                    # Set token expiry (if provided in response, otherwise use refresh interval)
                    if "expires" in auth_data:
                        self.token_expiry = datetime.fromisoformat(auth_data["expires"].replace("Z", "+00:00"))
                    elif "data" in auth_data and "expires" in auth_data["data"]:
                        self.token_expiry = datetime.fromisoformat(auth_data["data"]["expires"].replace("Z", "+00:00"))
                    else:
                        # If no expiry provided, set based on refresh interval
                        self.token_expiry = datetime.now() + timedelta(minutes=self.refresh_interval)
                        
                    self.last_refresh = datetime.now()
                    self.authenticated = True
                    
                    _LOGGER.info("Successfully authenticated with Homebox")
                    return True
            
        except aiohttp.ClientError as ex:
            _LOGGER.error(f"Failed to authenticate with Homebox: {ex}")
            self.authenticated = False
            return False
        except Exception as ex:
            _LOGGER.error(f"Unexpected error during authentication: {ex}")
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
    ) -> Any:
        """Make an authenticated request to the Homebox API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path (without leading slash)
            data: Optional JSON data for POST/PUT requests
            params: Optional URL parameters
            
        Returns:
            The parsed JSON response from the API
            
        Raises:
            HomeboxAuthError: If authentication fails
            HomeboxApiError: If the API request fails
        """
        # Ensure we have a valid token
        if not await self.ensure_token_valid():
            raise HomeboxAuthError("Failed to authenticate with Homebox")
            
        # Build the request
        url = f"{self.server_url}/api/v1/{endpoint.lstrip('/')}"
        
        # Make sure we have an auth token
        if not self.auth_token:
            _LOGGER.error("No auth token available for API request")
            raise HomeboxAuthError("No authentication token available")
            
        _LOGGER.debug(f"Making API request to {url} with token: {self.auth_token[:10]}...")
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": self.auth_token
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=data if data else None,
                    params=params if params else None,
                    ssl=None if not self.verify_ssl else True
                ) as response:
                    response_text = await response.text()
                    _LOGGER.debug(f"Response status: {response.status}, body: {response_text[:200]}")
                    
                    if response.status == 401:
                        _LOGGER.warning("Authentication token rejected, attempting to re-authenticate")
                        # Try to re-authenticate once
                        if await self.authenticate():
                            _LOGGER.info("Re-authentication successful, retrying request")
                            # Retry the request with the new token
                            return await self.api_request(method, endpoint, data, params)
                        else:
                            raise HomeboxAuthError("Failed to refresh authentication token")
                            
                    response.raise_for_status()
                    
                    # Try to parse JSON response
                    try:
                        return await response.json()
                    except aiohttp.ContentTypeError:
                        # If response is not JSON, return the text
                        _LOGGER.warning(f"Response is not valid JSON: {response_text}")
                        return response_text
            
        except aiohttp.ClientError as ex:
            _LOGGER.error(f"API request failed: {ex}")
            raise HomeboxApiError(f"API request failed: {ex}")
        except Exception as ex:
            _LOGGER.error(f"Unexpected error during API request: {ex}")
            raise HomeboxApiError(f"Unexpected error during API request: {ex}")

    async def test_connection(self) -> bool:
        """Test the connection to Homebox by attempting to authenticate."""
        return await self.authenticate()
        
    async def get_locations(self) -> list:
        """Get all locations from Homebox."""
        try:
            result = await self.api_request("GET", "locations")
            _LOGGER.debug(f"Locations API response: {result}")
            
            # Handle different response formats
            if isinstance(result, list):
                # The response is directly a list of locations
                return result
            elif isinstance(result, dict):
                # The response is a dictionary, try to extract the locations from it
                if "data" in result and isinstance(result["data"], list):
                    return result["data"]
                else:
                    # Try to find any list in the response
                    for key, value in result.items():
                        if isinstance(value, list):
                            _LOGGER.debug(f"Found locations in '{key}' field")
                            return value
                    
                    _LOGGER.warning(f"Unexpected location response format, no list found: {result}")
                    return []
            else:
                _LOGGER.warning(f"Unexpected location response type: {type(result)}")
                return []
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
            
    async def get_items(self, label: str = None) -> list:
        """Get items from Homebox, optionally filtered by label.
        
        Args:
            label: Optional label to filter items by
            
        Returns:
            List of item objects
        """
        try:
            # Build query parameters if label is provided
            params = {"label": label} if label else None
            
            result = await self.api_request("GET", "items", params=params)
            _LOGGER.debug(f"Items API response structure: {type(result)}")
            
            # Handle different response formats
            if isinstance(result, list):
                return result
            elif isinstance(result, dict):
                # Check for "items" field in the response (most likely format)
                if "items" in result and isinstance(result["items"], list):
                    _LOGGER.debug(f"Found items in 'items' field, count: {len(result['items'])}")
                    return result["items"]
                # Check for "data" field in the response (alternative format)
                elif "data" in result and isinstance(result["data"], list):
                    _LOGGER.debug(f"Found items in 'data' field, count: {len(result['data'])}")
                    return result["data"]
                else:
                    # Try to find any list in the response
                    for key, value in result.items():
                        if isinstance(value, list):
                            _LOGGER.debug(f"Found items in '{key}' field")
                            return value
                    
                    _LOGGER.warning(f"Unexpected items response format, no list found: {result}")
                    return []
            else:
                _LOGGER.warning(f"Unexpected items response type: {type(result)}")
                return []
        except Exception as ex:
            _LOGGER.error(f"Failed to get Homebox items: {ex}")
            return []
            
    async def update_item_location(self, item_id: str, location_id: str) -> bool:
        """Update the location of an item.
        
        Args:
            item_id: ID of the item to update
            location_id: ID of the new location
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # The Homebox API might expect a different format than we initially thought
            # Let's try with two common formats
            data = {"location_id": location_id}
            
            try:
                # First attempt with location_id field
                result = await self.api_request("PATCH", f"items/{item_id}", data=data)
                _LOGGER.info(f"Updated location for item {item_id} to {location_id}")
                return True
            except HomeboxApiError as first_error:
                # If that fails, try with a nested location object
                _LOGGER.debug(f"First location update attempt failed: {first_error}, trying alternate format")
                data = {"location": {"id": location_id}}
                result = await self.api_request("PATCH", f"items/{item_id}", data=data)
                _LOGGER.info(f"Updated location for item {item_id} to {location_id} using alternate format")
                return True
                
        except Exception as ex:
            _LOGGER.error(f"Failed to update item location: {ex}")
            return False
            
    async def register_webhook(self, webhook_url: str, events: list = None) -> bool:
        """Register a webhook with Homebox.
        
        Args:
            webhook_url: The URL to send webhooks to
            events: List of event types to subscribe to (default: item events)
            
        Returns:
            True if successful, False otherwise
        """
        if events is None:
            events = ["item.created", "item.updated", "item.deleted"]
            
        try:
            data = {
                "url": webhook_url,
                "events": events,
                "is_active": True
            }
            
            result = await self.api_request("POST", "notifiers", data=data)
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
            result = await self.api_request("GET", "notifiers")
            _LOGGER.debug(f"Notifiers API response: {result}")
            
            # Handle different response formats
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "data" in result:
                if isinstance(result["data"], list):
                    return result["data"]
                else:
                    _LOGGER.warning(f"Unexpected data type in notifiers response: {type(result['data'])}")
                    return []
            else:
                _LOGGER.warning(f"Unexpected notifiers response format: {result}")
                return []
        except Exception as ex:
            _LOGGER.error(f"Failed to list notifiers: {ex}")
            return []


class HomeboxAuthError(Exception):
    """Exception raised for Homebox authentication errors."""
    pass


class HomeboxApiError(Exception):
    """Exception raised for Homebox API errors."""
    pass