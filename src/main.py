#!/usr/bin/env python3
"""
Main orchestrator for Compliance Tracker
Runs event poller and compliance workflow
"""

import os
import sys
import signal
import time
from pathlib import Path
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
from vectorstore import ChromaComplianceStore
from agents import EvaluatorAgent, ReporterAgent
from compliance_workflow import ComplianceWorkflow
from poller import EventPoller
from utils import setup_logger


class ComplianceTracker:
    """Main orchestrator for compliance tracking system."""
    
    def __init__(self):
        """Initialize compliance tracker."""
        # Load environment variables
        load_dotenv()
        
        # Setup logger
        self.logger = setup_logger(
            name='compliance_tracker',
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            log_dir=os.getenv('LOG_DIR', 'logs')
        )
        
        self.logger.info("=" * 60)
        self.logger.info("Compliance Tracker - Continuous Compliance Monitoring")
        self.logger.info("=" * 60)
        
        # Initialize components
        self._init_database()
        self._init_vector_store()
        self._init_agents()
        self._init_workflow()
        self._init_poller()
        self._init_scheduler()
        
        self.running = False
    
    def _init_database(self):
        """Initialize database manager."""
        self.logger.info("Initializing database connection...")
        self.db_manager = DatabaseManager(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', ''),
            database=os.getenv('POSTGRES_DB', 'compliance_tracker'),
            logger=self.logger
        )
        self.logger.info("✓ Database connection initialized")
    
    def _init_vector_store(self):
        """Initialize vector store."""
        self.logger.info("Initializing vector store...")
        self.chroma_store = ChromaComplianceStore(
            persist_directory=os.getenv('CHROMA_PERSIST_DIR', 'src/vectorstore/chroma_data'),
            embedding_model=os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2'),
            logger=self.logger
        )
        
        # Check available frameworks
        frameworks = self.chroma_store.list_frameworks()
        if frameworks:
            self.logger.info(f"✓ Vector store ready with frameworks: {', '.join(frameworks)}")
        else:
            self.logger.warning("⚠ No compliance frameworks loaded in vector store")
            self.logger.warning("  Run: python src/vectorstore/ingest_pdfs.py")
    
    def _init_agents(self):
        """Initialize AI agents."""
        self.logger.info("Initializing AI agents...")
        
        groq_api_key = os.getenv('GROQ_API_KEY')
        if not groq_api_key:
            self.logger.error("GROQ_API_KEY not set in environment")
            sys.exit(1)
        
        groq_model = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
        
        # Initialize evaluator agent
        self.evaluator = EvaluatorAgent(
            db_manager=self.db_manager,
            chroma_store=self.chroma_store,
            groq_api_key=groq_api_key,
            model=groq_model,
            logger=self.logger
        )
        
        # Initialize reporter agent
        self.reporter = ReporterAgent(
            db_manager=self.db_manager,
            groq_api_key=groq_api_key,
            output_dir=os.getenv('OUTPUT_DIR', 'output'),
            model=groq_model,
            logger=self.logger
        )
        
        self.logger.info("✓ AI agents initialized")
    
    def _init_workflow(self):
        """Initialize LangGraph workflow."""
        self.logger.info("Initializing compliance workflow...")
        self.workflow = ComplianceWorkflow(
            db_manager=self.db_manager,
            evaluator_agent=self.evaluator,
            reporter_agent=self.reporter,
            logger=self.logger
        )
        self.logger.info("✓ Compliance workflow initialized")
    
    def _init_poller(self):
        """Initialize event poller."""
        self.logger.info("Initializing event poller...")
        
        ibm_api_key = os.getenv('IBM_CLOUD_API_KEY')
        if not ibm_api_key:
            self.logger.error("IBM_CLOUD_API_KEY not set in environment")
            sys.exit(1)
        
        self.poller = EventPoller(
            db_manager=self.db_manager,
            ibm_api_key=ibm_api_key,
            ibm_region=os.getenv('IBM_CLOUD_REGION', 'us-south'),
            poll_interval_seconds=int(os.getenv('POLL_INTERVAL_SECONDS', '60')),
            logger=self.logger
        )
        self.logger.info("✓ Event poller initialized")
    
    def _init_scheduler(self):
        """Initialize workflow scheduler."""
        self.logger.info("Initializing workflow scheduler...")
        self.scheduler = BackgroundScheduler()
        
        # Schedule workflow execution
        workflow_interval = int(os.getenv('WORKFLOW_INTERVAL_SECONDS', '120'))
        self.scheduler.add_job(
            func=self._run_workflow,
            trigger=IntervalTrigger(seconds=workflow_interval),
            id='compliance_workflow',
            name='Compliance Workflow Execution',
            replace_existing=True
        )
        
        self.logger.info(f"✓ Workflow scheduler initialized (interval: {workflow_interval}s)")
    
    def _run_workflow(self):
        """Execute compliance workflow."""
        try:
            self.logger.info("-" * 60)
            self.logger.info("Executing compliance workflow...")
            result = self.workflow.run()
            
            if result.get('success'):
                self.logger.info(
                    f"Workflow complete: {result.get('violations_found', 0)} violations, "
                    f"{result.get('reports_generated', 0)} reports"
                )
            else:
                self.logger.error(f"Workflow failed: {result.get('error')}")
            
            self.logger.info("-" * 60)
            
        except Exception as e:
            self.logger.error(f"Error executing workflow: {e}", exc_info=True)
    
    def start(self):
        """Start the compliance tracker."""
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("Starting Compliance Tracker...")
            self.logger.info("=" * 60 + "\n")
            
            # Start event poller
            self.poller.start()
            
            # Start workflow scheduler
            self.scheduler.start()
            
            self.running = True
            self.logger.info("✓ Compliance Tracker is running")
            self.logger.info("\nPress Ctrl+C to stop\n")
            
            # Keep main thread alive
            while self.running:
                time.sleep(1)
                
        except Exception as e:
            self.logger.error(f"Error starting compliance tracker: {e}", exc_info=True)
            self.stop()
    
    def stop(self):
        """Stop the compliance tracker."""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Stopping Compliance Tracker...")
        self.logger.info("=" * 60)
        
        self.running = False
        
        # Stop poller
        if hasattr(self, 'poller'):
            self.poller.stop()
        
        # Stop scheduler
        if hasattr(self, 'scheduler') and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
        
        self.logger.info("✓ Compliance Tracker stopped")
        self.logger.info("=" * 60)
    
    def get_status(self) -> dict:
        """Get system status."""
        return {
            'running': self.running,
            'poller_status': self.poller.get_status() if hasattr(self, 'poller') else {},
            'scheduler_running': self.scheduler.running if hasattr(self, 'scheduler') else False,
            'available_frameworks': self.chroma_store.list_frameworks() if hasattr(self, 'chroma_store') else []
        }


def signal_handler(signum, frame):
    """Handle interrupt signals."""
    print("\n\nReceived interrupt signal, shutting down...")
    if 'tracker' in globals():
        tracker.stop()
    sys.exit(0)


def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Create and start tracker
        global tracker
        tracker = ComplianceTracker()
        tracker.start()
        
    except KeyboardInterrupt:
        print("\n\nShutdown requested by user")
        if 'tracker' in globals():
            tracker.stop()
    except Exception as e:
        print(f"\nFatal error: {e}")
        if 'tracker' in globals():
            tracker.stop()
        sys.exit(1)


if __name__ == '__main__':
    main()

