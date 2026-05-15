"""Event poller for fetching and normalizing cloud provider events."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from connectors import IBMActivityTrackerConnector
from database import DatabaseManager
from utils import EventNormalizer, setup_logger


class EventPoller:
    """Polls cloud providers for events and stores them in database."""
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        ibm_api_key: str,
        ibm_region: str = 'us-south',
        poll_interval_seconds: int = 60,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize event poller.
        
        Args:
            db_manager: Database manager instance
            ibm_api_key: IBM Cloud API key
            ibm_region: IBM Cloud region
            poll_interval_seconds: Polling interval in seconds
            logger: Logger instance
        """
        self.db_manager = db_manager
        self.poll_interval = poll_interval_seconds
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize connectors
        self.ibm_connector = IBMActivityTrackerConnector(
            api_key=ibm_api_key,
            region=ibm_region,
            logger=self.logger
        )
        
        # Initialize event normalizer
        self.normalizer = EventNormalizer(logger=self.logger)
        
        # Initialize scheduler
        self.scheduler = BackgroundScheduler()
        self.last_poll_time: Optional[datetime] = None
        
        self.logger.info(f"Event poller initialized with {poll_interval_seconds}s interval")
    
    def poll_ibm_events(self):
        """Poll IBM Cloud Activity Tracker for events."""
        try:
            self.logger.info("Starting IBM Cloud event polling...")
            
            # Determine time range for polling
            end_time = datetime.utcnow()
            if self.last_poll_time:
                start_time = self.last_poll_time
            else:
                # First poll: get events from last hour
                start_time = end_time - timedelta(hours=1)
            
            # Fetch COS events
            cos_events = self.ibm_connector.fetch_cos_events(
                start_time=start_time,
                end_time=end_time
            )
            self.logger.info(f"Fetched {len(cos_events)} COS events")
            
            # Fetch IAM events
            iam_events = self.ibm_connector.fetch_iam_events(
                start_time=start_time,
                end_time=end_time
            )
            self.logger.info(f"Fetched {len(iam_events)} IAM events")
            
            # Process all events
            all_events = cos_events + iam_events
            processed_count = 0
            
            for raw_event in all_events:
                try:
                    # Store raw event
                    event_id = raw_event.get('id') or raw_event.get('eventId', '')
                    if not event_id:
                        self.logger.warning("Event without ID, skipping")
                        continue
                    
                    raw_event_id = self.db_manager.insert_raw_event(
                        event_id=event_id,
                        source='ibm',
                        raw_data=raw_event
                    )
                    
                    if not raw_event_id:
                        self.logger.debug(f"Event {event_id} already exists, skipping")
                        continue
                    
                    # Normalize event
                    normalized = self.normalizer.normalize_ibm_event(raw_event)
                    
                    if normalized:
                        # Store normalized event
                        self.db_manager.insert_normalized_event(
                            event_id=normalized['event_id'],
                            raw_event_id=raw_event_id,
                            source=normalized['source'],
                            event_type=normalized['event_type'],
                            resource_id=normalized['resource_id'],
                            resource_type=normalized['resource_type'],
                            actor=normalized['actor'],
                            region=normalized['region'],
                            timestamp=normalized['timestamp'],
                            metadata=normalized['metadata']
                        )
                        processed_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error processing event: {e}", exc_info=True)
            
            self.logger.info(
                f"IBM polling complete: {processed_count} new events processed"
            )
            
            # Update last poll time
            self.last_poll_time = end_time
            
        except Exception as e:
            self.logger.error(f"Error during IBM event polling: {e}", exc_info=True)
    
    def start(self):
        """Start the event poller."""
        try:
            # Test connections
            self.logger.info("Testing cloud provider connections...")
            if not self.ibm_connector.test_connection():
                self.logger.warning("IBM Activity Tracker connection test failed")
            
            # Schedule IBM polling job
            self.scheduler.add_job(
                func=self.poll_ibm_events,
                trigger=IntervalTrigger(seconds=self.poll_interval),
                id='ibm_event_poll',
                name='IBM Cloud Event Polling',
                replace_existing=True
            )
            
            # Start scheduler
            self.scheduler.start()
            self.logger.info(f"Event poller started (interval: {self.poll_interval}s)")
            
            # Run initial poll immediately
            self.poll_ibm_events()
            
        except Exception as e:
            self.logger.error(f"Error starting event poller: {e}", exc_info=True)
            raise
    
    def stop(self):
        """Stop the event poller."""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
                self.logger.info("Event poller stopped")
        except Exception as e:
            self.logger.error(f"Error stopping event poller: {e}", exc_info=True)
    
    def get_status(self) -> dict:
        """
        Get poller status.
        
        Returns:
            Dictionary with poller status information
        """
        return {
            'running': self.scheduler.running if self.scheduler else False,
            'last_poll_time': self.last_poll_time.isoformat() if self.last_poll_time else None,
            'poll_interval_seconds': self.poll_interval,
            'scheduled_jobs': len(self.scheduler.get_jobs()) if self.scheduler else 0
        }


def main():
    """Main entry point for standalone poller."""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Setup logger
    logger = setup_logger(
        name='event_poller',
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
        log_dir='logs'
    )
    
    # Initialize database manager
    db_manager = DatabaseManager(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        user=os.getenv('POSTGRES_USER', 'postgres'),
        password=os.getenv('POSTGRES_PASSWORD', ''),
        database=os.getenv('POSTGRES_DB', 'compliance_tracker'),
        logger=logger
    )
    
    # Initialize and start poller
    poller = EventPoller(
        db_manager=db_manager,
        ibm_api_key=os.getenv('IBM_CLOUD_API_KEY', ''),
        ibm_region=os.getenv('IBM_CLOUD_REGION', 'us-south'),
        poll_interval_seconds=int(os.getenv('POLL_INTERVAL_SECONDS', '60')),
        logger=logger
    )
    
    try:
        poller.start()
        logger.info("Event poller is running. Press Ctrl+C to stop.")
        
        # Keep the main thread alive
        import time
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, stopping poller...")
        poller.stop()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        poller.stop()


if __name__ == '__main__':
    main()

# Made with Bob
