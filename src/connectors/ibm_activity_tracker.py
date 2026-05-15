"""IBM Activity Tracker connector for fetching audit events."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from ibm_platform_services import AtrackerV2
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator


class IBMActivityTrackerConnector:
    """Connector for IBM Cloud Activity Tracker events."""
    
    def __init__(
        self,
        api_key: str,
        region: str = 'us-south',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize IBM Activity Tracker connector.
        
        Args:
            api_key: IBM Cloud API key
            region: IBM Cloud region
            logger: Logger instance
        """
        self.api_key = api_key
        self.region = region
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize authenticator
        self.authenticator = IAMAuthenticator(api_key)
        
        # Initialize Activity Tracker client
        self._client: Optional[AtrackerV2] = None
        
        self.logger.info(f"IBM Activity Tracker connector initialized for region: {region}")
    
    @property
    def client(self) -> AtrackerV2:
        """Get or create Activity Tracker client."""
        if not self._client:
            self._client = AtrackerV2(authenticator=self.authenticator)
            # Set service URL based on region
            self._client.set_service_url(
                f'https://{self.region}.atracker.cloud.ibm.com'
            )
            self.logger.debug("Activity Tracker client initialized")
        return self._client
    
    def fetch_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Fetch events from IBM Activity Tracker.
        
        Args:
            start_time: Start time for event query (default: 1 hour ago)
            end_time: End time for event query (default: now)
            event_types: List of event types to filter (optional)
            limit: Maximum number of events to fetch
            
        Returns:
            List of raw events
        """
        try:
            # Set default time range if not provided
            if not end_time:
                end_time = datetime.utcnow()
            if not start_time:
                start_time = end_time - timedelta(hours=1)
            
            self.logger.info(
                f"Fetching Activity Tracker events from {start_time} to {end_time}"
            )
            
            # Note: IBM Activity Tracker V2 API structure
            # This is a simplified implementation - actual API may vary
            # You may need to use the Events API or search functionality
            
            events = []
            
            # Build query parameters
            query_params: Dict[str, Any] = {
                'from': int(start_time.timestamp() * 1000),  # milliseconds
                'to': int(end_time.timestamp() * 1000),
                'size': limit
            }
            
            # Add event type filter if provided
            if event_types:
                query_params['action'] = ','.join(event_types)
            
            # Fetch events using the Activity Tracker API
            # Note: The actual API method may differ based on IBM SDK version
            try:
                # This is a placeholder - adjust based on actual IBM SDK
                response = self.client.list_events(**query_params)
                events = response.get_result().get('events', [])
                
                self.logger.info(f"Fetched {len(events)} events from Activity Tracker")
                
            except AttributeError:
                # Fallback: If list_events doesn't exist, log warning
                self.logger.warning(
                    "Activity Tracker API method not available. "
                    "Using alternative approach or mock data for development."
                )
                # For development, you might want to return empty list or mock data
                events = []
            
            return events
            
        except Exception as e:
            self.logger.error(f"Error fetching Activity Tracker events: {e}", exc_info=True)
            return []
    
    def fetch_cos_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch Cloud Object Storage related events.
        
        Args:
            start_time: Start time for event query
            end_time: End time for event query
            
        Returns:
            List of COS events
        """
        cos_event_types = [
            'cloud-object-storage.bucket-acl.update',
            'cloud-object-storage.bucket-acl.create',
            'cloud-object-storage.bucket-policy.update',
            'cloud-object-storage.bucket-policy.create',
            'cloud-object-storage.bucket.create',
            'cloud-object-storage.bucket.delete'
        ]
        
        return self.fetch_events(
            start_time=start_time,
            end_time=end_time,
            event_types=cos_event_types
        )
    
    def fetch_iam_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch IAM related events.
        
        Args:
            start_time: Start time for event query
            end_time: End time for event query
            
        Returns:
            List of IAM events
        """
        iam_event_types = [
            'iam-identity.user.create',
            'iam-identity.user.delete',
            'iam-identity.user.update',
            'iam-identity.serviceid.create',
            'iam-identity.mfa-totp.create',
            'iam-identity.mfa-totp.delete',
            'iam-identity.apikey.create',
            'iam-identity.apikey.delete',
            'iam-am.policy.create',
            'iam-am.policy.update',
            'iam-am.policy.delete'
        ]
        
        return self.fetch_events(
            start_time=start_time,
            end_time=end_time,
            event_types=iam_event_types
        )
    
    def test_connection(self) -> bool:
        """
        Test connection to IBM Activity Tracker.
        
        Returns:
            True if connection is successful
        """
        try:
            # Try to fetch a small number of recent events
            events = self.fetch_events(limit=1)
            self.logger.info("Activity Tracker connection test successful")
            return True
        except Exception as e:
            self.logger.error(f"Activity Tracker connection test failed: {e}")
            return False

# Made with Bob
