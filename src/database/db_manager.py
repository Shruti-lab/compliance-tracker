"""Database manager for PostgreSQL operations."""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager


class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""
    
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize database manager.
        
        Args:
            host: PostgreSQL host
            port: PostgreSQL port
            user: Database user
            password: Database password
            database: Database name
            logger: Logger instance
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.logger = logger or logging.getLogger(__name__)
        
        self.connection_params = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database
        }
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = None
        try:
            conn = psycopg2.connect(**self.connection_params)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def insert_raw_event(
        self,
        event_id: str,
        source: str,
        raw_data: Dict[str, Any]
    ) -> Optional[int]:
        """
        Insert raw event into database.
        
        Args:
            event_id: Unique event identifier
            source: Event source ('ibm' or 'aws')
            raw_data: Raw event data as dictionary
            
        Returns:
            Inserted row ID or None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO raw_events (event_id, source, raw_data)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        RETURNING id
                        """,
                        (event_id, source, Json(raw_data))
                    )
                    result = cursor.fetchone()
                    if result:
                        self.logger.debug(f"Inserted raw event {event_id}")
                        return result[0]
                    return None
        except Exception as e:
            self.logger.error(f"Error inserting raw event: {e}")
            return None
    
    def insert_normalized_event(
        self,
        event_id: str,
        raw_event_id: int,
        source: str,
        event_type: str,
        resource_id: str,
        resource_type: str,
        actor: str,
        region: str,
        timestamp: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Insert normalized event into database.
        
        Args:
            event_id: Unique event identifier
            raw_event_id: Reference to raw event
            source: Event source
            event_type: Normalized event type
            resource_id: Resource identifier
            resource_type: Type of resource
            actor: Actor who performed the action
            region: Cloud region
            timestamp: Event timestamp
            metadata: Additional metadata
            
        Returns:
            Inserted row ID or None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO normalized_events (
                            event_id, raw_event_id, source, event_type,
                            resource_id, resource_type, actor, region,
                            timestamp, metadata, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                        ON CONFLICT (event_id) DO NOTHING
                        RETURNING id
                        """,
                        (
                            event_id, raw_event_id, source, event_type,
                            resource_id, resource_type, actor, region,
                            timestamp, Json(metadata) if metadata else None
                        )
                    )
                    result = cursor.fetchone()
                    if result:
                        self.logger.debug(f"Inserted normalized event {event_id}")
                        return result[0]
                    return None
        except Exception as e:
            self.logger.error(f"Error inserting normalized event: {e}")
            return None
    
    def get_pending_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get pending events for processing.
        
        Args:
            limit: Maximum number of events to retrieve
            
        Returns:
            List of pending events
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT * FROM normalized_events
                        WHERE status = 'pending'
                        ORDER BY timestamp ASC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    events = cursor.fetchall()
                    return [dict(event) for event in events]
        except Exception as e:
            self.logger.error(f"Error fetching pending events: {e}")
            return []
    
    def update_event_status(
        self,
        event_id: str,
        status: str,
        processed_at: Optional[datetime] = None
    ) -> bool:
        """
        Update event processing status.
        
        Args:
            event_id: Event identifier
            status: New status ('processing', 'processed', 'failed')
            processed_at: Processing timestamp
            
        Returns:
            True if successful
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE normalized_events
                        SET status = %s, processed_at = %s
                        WHERE event_id = %s
                        """,
                        (status, processed_at or datetime.utcnow(), event_id)
                    )
                    return True
        except Exception as e:
            self.logger.error(f"Error updating event status: {e}")
            return False
    
    def insert_violation(
        self,
        event_id: str,
        normalized_event_id: int,
        framework: str,
        control_id: str,
        control_description: str,
        severity: str,
        violation_reason: str,
        llm_evaluation: str
    ) -> Optional[int]:
        """
        Insert compliance violation.
        
        Args:
            event_id: Event identifier
            normalized_event_id: Reference to normalized event
            framework: Compliance framework
            control_id: Control identifier
            control_description: Control description
            severity: Violation severity
            violation_reason: Reason for violation
            llm_evaluation: LLM evaluation text
            
        Returns:
            Inserted violation ID or None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO violations (
                            event_id, normalized_event_id, framework,
                            control_id, control_description, severity,
                            violation_reason, llm_evaluation
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            event_id, normalized_event_id, framework,
                            control_id, control_description, severity,
                            violation_reason, llm_evaluation
                        )
                    )
                    result = cursor.fetchone()
                    if result:
                        self.logger.info(f"Inserted violation for event {event_id}")
                        return result[0]
                    return None
        except Exception as e:
            self.logger.error(f"Error inserting violation: {e}")
            return None
    
    def insert_evidence_report(
        self,
        violation_id: int,
        event_id: str,
        evidence_text: str,
        remediation_steps: str,
        file_path: Optional[str] = None
    ) -> Optional[int]:
        """
        Insert evidence report.
        
        Args:
            violation_id: Reference to violation
            event_id: Event identifier
            evidence_text: Audit evidence text
            remediation_steps: Remediation guidance
            file_path: Path to saved report file
            
        Returns:
            Inserted report ID or None if failed
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO evidence_reports (
                            violation_id, event_id, evidence_text,
                            remediation_steps, file_path
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (violation_id, event_id, evidence_text, remediation_steps, file_path)
                    )
                    result = cursor.fetchone()
                    if result:
                        self.logger.info(f"Inserted evidence report for violation {violation_id}")
                        return result[0]
                    return None
        except Exception as e:
            self.logger.error(f"Error inserting evidence report: {e}")
            return None
    
    def get_violation_summary(self) -> List[Dict[str, Any]]:
        """
        Get violation summary by framework and severity.
        
        Returns:
            List of violation summaries
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT * FROM violation_summary")
                    return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Error fetching violation summary: {e}")
            return []
    
    def check_mfa_event_exists(
        self,
        user_id: str,
        after_timestamp: datetime,
        time_window_minutes: int = 5
    ) -> bool:
        """
        Check if MFA event exists for a user within time window.
        
        Args:
            user_id: User identifier
            after_timestamp: Start timestamp
            time_window_minutes: Time window in minutes
            
        Returns:
            True if MFA event found
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM normalized_events
                        WHERE event_type = 'IAM_MFA_ENABLED'
                        AND resource_id = %s
                        AND timestamp > %s
                        AND timestamp < %s + INTERVAL '%s minutes'
                        """,
                        (user_id, after_timestamp, after_timestamp, time_window_minutes)
                    )
                    count = cursor.fetchone()[0]
                    return count > 0
        except Exception as e:
            self.logger.error(f"Error checking MFA event: {e}")
            return False

# Made with Bob
