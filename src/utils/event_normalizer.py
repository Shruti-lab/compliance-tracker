"""Event normalizer for converting cloud provider events to standard format."""

import logging
from datetime import datetime
from typing import Dict, Any, Optional
import uuid


class EventNormalizer:
    """Normalizes events from different cloud providers to a standard format."""
    
    # Event type mappings for IBM Cloud Activity Tracker
    IBM_EVENT_TYPE_MAP = {
        # COS (Cloud Object Storage) events
        'cloud-object-storage.bucket-acl.update': 'COS_ACL_UPDATE',
        'cloud-object-storage.bucket-acl.create': 'COS_ACL_UPDATE',
        'cloud-object-storage.bucket-policy.update': 'COS_POLICY_UPDATE',
        'cloud-object-storage.bucket-policy.create': 'COS_POLICY_UPDATE',
        'cloud-object-storage.bucket.create': 'COS_BUCKET_CREATE',
        'cloud-object-storage.bucket.delete': 'COS_BUCKET_DELETE',
        
        # IAM events
        'iam-identity.user.create': 'IAM_USER_CREATE',
        'iam-identity.user.delete': 'IAM_USER_DELETE',
        'iam-identity.user.update': 'IAM_USER_UPDATE',
        'iam-identity.serviceid.create': 'IAM_SERVICE_ID_CREATE',
        'iam-identity.mfa-totp.create': 'IAM_MFA_ENABLED',
        'iam-identity.mfa-totp.delete': 'IAM_MFA_DISABLED',
        'iam-identity.apikey.create': 'IAM_API_KEY_CREATE',
        'iam-identity.apikey.delete': 'IAM_API_KEY_DELETE',
        
        # IAM Policy events
        'iam-am.policy.create': 'IAM_POLICY_CREATE',
        'iam-am.policy.update': 'IAM_POLICY_UPDATE',
        'iam-am.policy.delete': 'IAM_POLICY_DELETE',
    }
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize event normalizer.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def normalize_ibm_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize IBM Cloud Activity Tracker event.
        
        Args:
            raw_event: Raw event from IBM Activity Tracker
            
        Returns:
            Normalized event dictionary or None if normalization fails
        """
        try:
            # Extract action from event
            action = raw_event.get('action', '')
            
            # Map to normalized event type
            event_type = self.IBM_EVENT_TYPE_MAP.get(action, 'UNKNOWN')
            
            # Generate event ID if not present
            event_id = raw_event.get('id') or raw_event.get('eventId') or str(uuid.uuid4())
            
            # Extract resource information
            target = raw_event.get('target', {})
            resource_id = target.get('id') or target.get('name', 'unknown')
            resource_type = target.get('typeURI', '').split('/')[-1] if target.get('typeURI') else 'unknown'
            
            # Extract actor (initiator) information
            initiator = raw_event.get('initiator', {})
            actor = initiator.get('id') or initiator.get('name', 'unknown')
            
            # Extract timestamp
            event_time = raw_event.get('eventTime') or raw_event.get('timestamp')
            if isinstance(event_time, str):
                timestamp = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
            else:
                timestamp = datetime.utcnow()
            
            # Extract region
            region = raw_event.get('dataEvent', {}).get('region') or 'unknown'
            
            # Check for public access indicators in COS events
            if event_type in ['COS_ACL_UPDATE', 'COS_POLICY_UPDATE']:
                event_type = self._check_cos_public_exposure(raw_event, event_type)
            
            # Build normalized event
            normalized = {
                'event_id': event_id,
                'source': 'ibm',
                'event_type': event_type,
                'resource_id': resource_id,
                'resource_type': resource_type,
                'actor': actor,
                'region': region,
                'timestamp': timestamp,
                'metadata': {
                    'action': action,
                    'outcome': raw_event.get('outcome', 'unknown'),
                    'severity': raw_event.get('severity', 'normal'),
                    'initiator_type': initiator.get('typeURI', ''),
                    'target_type': target.get('typeURI', ''),
                    'request_data': raw_event.get('requestData', {}),
                    'response_data': raw_event.get('responseData', {})
                }
            }
            
            self.logger.debug(f"Normalized IBM event: {event_id} -> {event_type}")
            return normalized
            
        except Exception as e:
            self.logger.error(f"Error normalizing IBM event: {e}", exc_info=True)
            return None
    
    def _check_cos_public_exposure(
        self,
        raw_event: Dict[str, Any],
        base_event_type: str
    ) -> str:
        """
        Check if COS event indicates public exposure.
        
        Args:
            raw_event: Raw event data
            base_event_type: Base event type
            
        Returns:
            Updated event type if public exposure detected
        """
        try:
            # Check request data for public access indicators
            request_data = raw_event.get('requestData', {})
            response_data = raw_event.get('responseData', {})
            
            # Check for AllUsers or public grants in ACL
            acl = request_data.get('acl') or response_data.get('acl', {})
            if acl:
                grants = acl.get('grants', [])
                for grant in grants:
                    grantee = grant.get('grantee', {})
                    if grantee.get('type') == 'Group' and 'AllUsers' in grantee.get('uri', ''):
                        return 'COS_PUBLIC_EXPOSE'
            
            # Check for public policy statements
            policy = request_data.get('policy') or response_data.get('policy', {})
            if policy:
                statements = policy.get('Statement', [])
                for statement in statements:
                    principal = statement.get('Principal', {})
                    if principal == '*' or principal.get('AWS') == '*':
                        return 'COS_PUBLIC_EXPOSE'
            
            return base_event_type
            
        except Exception as e:
            self.logger.warning(f"Error checking public exposure: {e}")
            return base_event_type
    
    def normalize_aws_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Normalize AWS CloudTrail event.
        
        Args:
            raw_event: Raw event from AWS CloudTrail
            
        Returns:
            Normalized event dictionary or None if normalization fails
        """
        try:
            # Extract event name
            event_name = raw_event.get('eventName', '')
            
            # Map to normalized event type
            event_type = self._map_aws_event_type(event_name)
            
            # Generate event ID
            event_id = raw_event.get('eventID', str(uuid.uuid4()))
            
            # Extract resource information
            resources = raw_event.get('resources', [])
            resource_id = resources[0].get('ARN', 'unknown') if resources else 'unknown'
            resource_type = resources[0].get('type', 'unknown') if resources else 'unknown'
            
            # Extract actor
            user_identity = raw_event.get('userIdentity', {})
            actor = user_identity.get('arn') or user_identity.get('principalId', 'unknown')
            
            # Extract timestamp
            event_time = raw_event.get('eventTime')
            if isinstance(event_time, str):
                timestamp = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
            else:
                timestamp = datetime.utcnow()
            
            # Extract region
            region = raw_event.get('awsRegion', 'unknown')
            
            # Build normalized event
            normalized = {
                'event_id': event_id,
                'source': 'aws',
                'event_type': event_type,
                'resource_id': resource_id,
                'resource_type': resource_type,
                'actor': actor,
                'region': region,
                'timestamp': timestamp,
                'metadata': {
                    'event_name': event_name,
                    'event_source': raw_event.get('eventSource', ''),
                    'user_agent': raw_event.get('userAgent', ''),
                    'request_parameters': raw_event.get('requestParameters', {}),
                    'response_elements': raw_event.get('responseElements', {})
                }
            }
            
            self.logger.debug(f"Normalized AWS event: {event_id} -> {event_type}")
            return normalized
            
        except Exception as e:
            self.logger.error(f"Error normalizing AWS event: {e}", exc_info=True)
            return None
    
    def _map_aws_event_type(self, event_name: str) -> str:
        """
        Map AWS event name to normalized event type.
        
        Args:
            event_name: AWS CloudTrail event name
            
        Returns:
            Normalized event type
        """
        aws_event_map = {
            'PutBucketAcl': 'S3_ACL_UPDATE',
            'PutBucketPolicy': 'S3_POLICY_UPDATE',
            'CreateBucket': 'S3_BUCKET_CREATE',
            'DeleteBucket': 'S3_BUCKET_DELETE',
            'CreateUser': 'IAM_USER_CREATE',
            'DeleteUser': 'IAM_USER_DELETE',
            'CreateVirtualMFADevice': 'IAM_MFA_ENABLED',
            'DeleteVirtualMFADevice': 'IAM_MFA_DISABLED',
            'CreateAccessKey': 'IAM_ACCESS_KEY_CREATE',
            'DeleteAccessKey': 'IAM_ACCESS_KEY_DELETE',
        }
        
        return aws_event_map.get(event_name, 'UNKNOWN')
    
    def normalize(
        self,
        raw_event: Dict[str, Any],
        source: str
    ) -> Optional[Dict[str, Any]]:
        """
        Normalize event based on source.
        
        Args:
            raw_event: Raw event data
            source: Event source ('ibm' or 'aws')
            
        Returns:
            Normalized event or None if normalization fails
        """
        if source.lower() == 'ibm':
            return self.normalize_ibm_event(raw_event)
        elif source.lower() == 'aws':
            return self.normalize_aws_event(raw_event)
        else:
            self.logger.error(f"Unknown event source: {source}")
            return None

# Made with Bob
