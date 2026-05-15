#!/usr/bin/env python3
"""
FastAPI web interface for Compliance Tracker
Provides REST API endpoints for monitoring and management
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import io

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from database import DatabaseManager
from vectorstore import ChromaComplianceStore
from agents import EvaluatorAgent, ReporterAgent
from compliance_workflow import ComplianceWorkflow
from utils import setup_logger

# Load environment
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Compliance Tracker API",
    description="Continuous Compliance Monitoring System",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
logger = setup_logger(name='api', log_level=os.getenv('LOG_LEVEL', 'INFO'))
db_manager: Optional[DatabaseManager] = None
chroma_store: Optional[ChromaComplianceStore] = None
workflow: Optional[ComplianceWorkflow] = None


# Pydantic models
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    database: bool
    vector_store: bool
    frameworks: List[str]


class ViolationSummary(BaseModel):
    framework: str
    severity: str
    violation_count: int
    unresolved_count: int
    latest_violation: Optional[str]


class EventResponse(BaseModel):
    id: int
    event_id: str
    event_type: str
    resource_id: str
    timestamp: str
    status: str
    source: str


class ViolationResponse(BaseModel):
    id: int
    event_id: str
    framework: str
    control_id: str
    severity: str
    violation_reason: str
    detected_at: str
    resolved: bool


class WorkflowRunRequest(BaseModel):
    max_events: Optional[int] = 50


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize components on startup."""
    global db_manager, chroma_store, workflow
    
    logger.info("Initializing API components...")
    
    # Initialize database
    db_manager = DatabaseManager(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        user=os.getenv('POSTGRES_USER', 'postgres'),
        password=os.getenv('POSTGRES_PASSWORD', ''),
        database=os.getenv('POSTGRES_DB', 'compliance_tracker'),
        logger=logger
    )
    
    # Initialize vector store
    chroma_store = ChromaComplianceStore(
        persist_directory=os.getenv('CHROMA_PERSIST_DIR', 'src/vectorstore/chroma_data'),
        embedding_model=os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2'),
        logger=logger
    )
    
    # Initialize agents
    groq_api_key = os.getenv('GROQ_API_KEY')
    if groq_api_key:
        evaluator = EvaluatorAgent(
            db_manager=db_manager,
            chroma_store=chroma_store,
            groq_api_key=groq_api_key,
            model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
            logger=logger
        )
        
        reporter = ReporterAgent(
            db_manager=db_manager,
            groq_api_key=groq_api_key,
            output_dir=os.getenv('OUTPUT_DIR', 'output'),
            model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
            logger=logger
        )
        
        # Initialize workflow
        workflow = ComplianceWorkflow(
            db_manager=db_manager,
            evaluator_agent=evaluator,
            reporter_agent=reporter,
            logger=logger
        )
    
    logger.info("API components initialized successfully")


# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health and status."""
    try:
        # Test database connection
        db_ok = False
        try:
            db_manager.get_violation_summary()
            db_ok = True
        except Exception:
            pass
        
        # Get available frameworks
        frameworks = chroma_store.list_frameworks() if chroma_store else []
        
        return HealthResponse(
            status="healthy" if db_ok else "degraded",
            timestamp=datetime.utcnow().isoformat(),
            database=db_ok,
            vector_store=len(frameworks) > 0,
            frameworks=frameworks
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get workflow graph visualization
@app.get("/workflow/graph")
async def get_workflow_graph():
    """Get LangGraph workflow visualization as PNG image."""
    try:
        if not workflow:
            raise HTTPException(status_code=503, detail="Workflow not initialized")
        
        # Generate graph visualization
        from langgraph.graph import StateGraph
        
        # Get the compiled graph
        graph = workflow.graph
        
        # Generate mermaid diagram
        try:
            # Try to get PNG image
            img_data = graph.get_graph().draw_mermaid_png()
            return Response(content=img_data, media_type="image/png")
        except Exception:
            # Fallback to mermaid text
            mermaid = graph.get_graph().draw_mermaid()
            return JSONResponse(content={
                "format": "mermaid",
                "diagram": mermaid,
                "message": "Install graphviz for PNG rendering: pip install pygraphviz"
            })
            
    except Exception as e:
        logger.error(f"Error generating workflow graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get workflow graph as mermaid text
@app.get("/workflow/graph/mermaid")
async def get_workflow_graph_mermaid():
    """Get LangGraph workflow as Mermaid diagram text."""
    try:
        if not workflow:
            raise HTTPException(status_code=503, detail="Workflow not initialized")
        
        mermaid = workflow.graph.get_graph().draw_mermaid()
        return JSONResponse(content={
            "mermaid": mermaid,
            "render_url": "https://mermaid.live/edit"
        })
            
    except Exception as e:
        logger.error(f"Error generating mermaid diagram: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get violation summary
@app.get("/violations/summary", response_model=List[ViolationSummary])
async def get_violation_summary():
    """Get summary of violations by framework and severity."""
    try:
        summary = db_manager.get_violation_summary()
        return [
            ViolationSummary(
                framework=row['framework'],
                severity=row['severity'],
                violation_count=row['violation_count'],
                unresolved_count=row['unresolved_count'],
                latest_violation=row['latest_violation'].isoformat() if row['latest_violation'] else None
            )
            for row in summary
        ]
    except Exception as e:
        logger.error(f"Error fetching violation summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get recent violations
@app.get("/violations", response_model=List[ViolationResponse])
async def get_violations(
    limit: int = Query(50, ge=1, le=500),
    framework: Optional[str] = None,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None
):
    """Get recent violations with optional filters."""
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                # Build query
                query = "SELECT * FROM violations WHERE 1=1"
                params = []
                
                if framework:
                    query += " AND framework = %s"
                    params.append(framework)
                
                if severity:
                    query += " AND severity = %s"
                    params.append(severity)
                
                if resolved is not None:
                    query += " AND resolved = %s"
                    params.append(resolved)
                
                query += " ORDER BY detected_at DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                violations = []
                for row in rows:
                    data = dict(zip(columns, row))
                    violations.append(ViolationResponse(
                        id=data['id'],
                        event_id=data['event_id'],
                        framework=data['framework'],
                        control_id=data['control_id'],
                        severity=data['severity'],
                        violation_reason=data['violation_reason'],
                        detected_at=data['detected_at'].isoformat(),
                        resolved=data['resolved']
                    ))
                
                return violations
                
    except Exception as e:
        logger.error(f"Error fetching violations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get pending events
@app.get("/events/pending", response_model=List[EventResponse])
async def get_pending_events(limit: int = Query(50, ge=1, le=500)):
    """Get pending events waiting for evaluation."""
    try:
        events = db_manager.get_pending_events(limit=limit)
        return [
            EventResponse(
                id=event['id'],
                event_id=event['event_id'],
                event_type=event['event_type'],
                resource_id=event['resource_id'],
                timestamp=event['timestamp'].isoformat(),
                status=event['status'],
                source=event['source']
            )
            for event in events
        ]
    except Exception as e:
        logger.error(f"Error fetching pending events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get recent events
@app.get("/events", response_model=List[EventResponse])
async def get_events(
    limit: int = Query(50, ge=1, le=500),
    event_type: Optional[str] = None,
    status: Optional[str] = None
):
    """Get recent events with optional filters."""
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                query = "SELECT * FROM normalized_events WHERE 1=1"
                params = []
                
                if event_type:
                    query += " AND event_type = %s"
                    params.append(event_type)
                
                if status:
                    query += " AND status = %s"
                    params.append(status)
                
                query += " ORDER BY timestamp DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                events = []
                for row in rows:
                    data = dict(zip(columns, row))
                    events.append(EventResponse(
                        id=data['id'],
                        event_id=data['event_id'],
                        event_type=data['event_type'],
                        resource_id=data['resource_id'],
                        timestamp=data['timestamp'].isoformat(),
                        status=data['status'],
                        source=data['source']
                    ))
                
                return events
                
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get statistics
@app.get("/stats")
async def get_statistics():
    """Get system statistics."""
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                # Get event counts
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_events,
                        COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_events,
                        COUNT(CASE WHEN status = 'processed' THEN 1 END) as processed_events,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_events
                    FROM normalized_events
                """)
                event_stats = cursor.fetchone()
                
                # Get violation counts
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_violations,
                        COUNT(CASE WHEN resolved = false THEN 1 END) as unresolved_violations,
                        COUNT(CASE WHEN severity = 'critical' THEN 1 END) as critical_violations,
                        COUNT(CASE WHEN severity = 'high' THEN 1 END) as high_violations
                    FROM violations
                """)
                violation_stats = cursor.fetchone()
                
                # Get framework stats
                frameworks = chroma_store.list_frameworks() if chroma_store else []
                framework_stats = {}
                for fw in frameworks:
                    stats = chroma_store.get_collection_stats(fw)
                    framework_stats[fw] = stats.get('document_count', 0)
                
                return {
                    "events": {
                        "total": event_stats[0],
                        "pending": event_stats[1],
                        "processed": event_stats[2],
                        "failed": event_stats[3]
                    },
                    "violations": {
                        "total": violation_stats[0],
                        "unresolved": violation_stats[1],
                        "critical": violation_stats[2],
                        "high": violation_stats[3]
                    },
                    "frameworks": framework_stats,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
    except Exception as e:
        logger.error(f"Error fetching statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Trigger workflow manually
@app.post("/workflow/run")
async def run_workflow(background_tasks: BackgroundTasks):
    """Manually trigger compliance workflow execution."""
    try:
        if not workflow:
            raise HTTPException(status_code=503, detail="Workflow not initialized")
        
        # Run workflow in background
        background_tasks.add_task(workflow.run)
        
        return {
            "status": "started",
            "message": "Workflow execution started in background",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error running workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Get evidence report
@app.get("/violations/{violation_id}/report")
async def get_violation_report(violation_id: int):
    """Get evidence report for a specific violation."""
    try:
        with db_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM evidence_reports 
                    WHERE violation_id = %s 
                    ORDER BY generated_at DESC 
                    LIMIT 1
                """, (violation_id,))
                
                columns = [desc[0] for desc in cursor.description]
                row = cursor.fetchone()
                
                if not row:
                    raise HTTPException(status_code=404, detail="Report not found")
                
                data = dict(zip(columns, row))
                
                # If file exists, return file path
                if data['file_path'] and Path(data['file_path']).exists():
                    return FileResponse(
                        data['file_path'],
                        media_type='text/markdown',
                        filename=Path(data['file_path']).name
                    )
                
                # Otherwise return JSON
                return {
                    "violation_id": data['violation_id'],
                    "event_id": data['event_id'],
                    "evidence_text": data['evidence_text'],
                    "remediation_steps": data['remediation_steps'],
                    "generated_at": data['generated_at'].isoformat()
                }
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Root endpoint
@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "Compliance Tracker API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "workflow_graph": "/workflow/graph",
            "workflow_mermaid": "/workflow/graph/mermaid",
            "violations": "/violations",
            "violation_summary": "/violations/summary",
            "events": "/events",
            "pending_events": "/events/pending",
            "statistics": "/stats",
            "run_workflow": "/workflow/run (POST)",
            "docs": "/docs"
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv('API_PORT', '8000'))
    host = os.getenv('API_HOST', '0.0.0.0')
    
    logger.info(f"Starting API server on {host}:{port}")
    
    uvicorn.run(
        "api:app",
        host=host,
        port=port,
        reload=os.getenv('API_RELOAD', 'false').lower() == 'true',
        log_level=os.getenv('LOG_LEVEL', 'info').lower()
    )

# Made with Bob
