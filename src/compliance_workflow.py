"""LangGraph workflow for compliance evaluation and reporting."""

import logging
from typing import Dict, Any, List, TypedDict, Annotated
from datetime import datetime
import operator
from langgraph.graph import StateGraph, END
from agents import EvaluatorAgent, ReporterAgent
from database import DatabaseManager


class ComplianceState(TypedDict):
    """State for compliance workflow."""
    events: List[Dict[str, Any]]
    current_event: Dict[str, Any]
    evaluation: Dict[str, Any]
    report: Dict[str, Any]
    violations_found: Annotated[int, operator.add]
    reports_generated: Annotated[int, operator.add]
    errors: List[str]


class ComplianceWorkflow:
    """LangGraph workflow for continuous compliance monitoring."""
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        evaluator_agent: EvaluatorAgent,
        reporter_agent: ReporterAgent,
        logger: logging.Logger
    ):
        """
        Initialize compliance workflow.
        
        Args:
            db_manager: Database manager instance
            evaluator_agent: Evaluator agent instance
            reporter_agent: Reporter agent instance
            logger: Logger instance
        """
        self.db_manager = db_manager
        self.evaluator = evaluator_agent
        self.reporter = reporter_agent
        self.logger = logger
        
        # Build workflow graph
        self.graph = self._build_graph()
        
        self.logger.info("Compliance workflow initialized")
    
    def _build_graph(self) -> StateGraph:
        """Build LangGraph state graph."""
        # Create workflow graph
        workflow = StateGraph(ComplianceState)
        
        # Add nodes
        workflow.add_node("fetch_events", self.fetch_events_node)
        workflow.add_node("evaluate", self.evaluate_node)
        workflow.add_node("report", self.report_node)
        workflow.add_node("finalize", self.finalize_node)
        
        # Set entry point
        workflow.set_entry_point("fetch_events")
        
        # Add edges
        workflow.add_edge("fetch_events", "evaluate")
        workflow.add_conditional_edges(
            "evaluate",
            self.should_generate_report,
            {
                "report": "report",
                "finalize": "finalize"
            }
        )
        workflow.add_edge("report", "finalize")
        workflow.add_edge("finalize", END)
        
        return workflow.compile()
    
    def fetch_events_node(self, state: ComplianceState) -> ComplianceState:
        """
        Fetch pending events from database.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with events
        """
        try:
            self.logger.info("Fetching pending events...")
            events = self.db_manager.get_pending_events(limit=50)
            
            self.logger.info(f"Fetched {len(events)} pending events")
            
            return {
                **state,
                "events": events,
                "violations_found": 0,
                "reports_generated": 0,
                "errors": []
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching events: {e}", exc_info=True)
            return {
                **state,
                "events": [],
                "errors": [f"Fetch error: {str(e)}"]
            }
    
    def evaluate_node(self, state: ComplianceState) -> ComplianceState:
        """
        Evaluate events for compliance violations.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with evaluation results
        """
        events = state.get("events", [])
        violations_found = state.get("violations_found", 0)
        errors = state.get("errors", [])
        
        if not events:
            self.logger.info("No events to evaluate")
            return state
        
        # Process first event
        event = events[0]
        remaining_events = events[1:]
        
        try:
            event_id = event['event_id']
            self.logger.info(f"Evaluating event: {event_id}")
            
            # Update event status to processing
            self.db_manager.update_event_status(event_id, 'processing')
            
            # Evaluate event
            evaluation = self.evaluator.evaluate_event(event)
            
            # Store violation if found
            if evaluation.get('violation'):
                self.logger.warning(f"Violation detected for event {event_id}")
                
                # Store violation in database
                for framework in evaluation.get('frameworks', []):
                    violation_id = self.db_manager.insert_violation(
                        event_id=event_id,
                        normalized_event_id=event['id'],
                        framework=framework,
                        control_id=evaluation.get('control_id', 'UNKNOWN'),
                        control_description=evaluation.get('control_description', ''),
                        severity=evaluation.get('severity', 'medium'),
                        violation_reason=evaluation.get('violation_reason', ''),
                        llm_evaluation=evaluation.get('llm_evaluation', '')
                    )
                    
                    if violation_id:
                        evaluation['violation_id'] = violation_id
                
                violations_found += 1
            else:
                # No violation - mark as processed
                self.db_manager.update_event_status(event_id, 'processed')
            
            return {
                **state,
                "events": remaining_events,
                "current_event": event,
                "evaluation": evaluation,
                "violations_found": violations_found
            }
            
        except Exception as e:
            self.logger.error(f"Error evaluating event: {e}", exc_info=True)
            errors.append(f"Evaluation error: {str(e)}")
            
            # Mark event as failed
            if event:
                self.db_manager.update_event_status(event['event_id'], 'failed')
            
            return {
                **state,
                "events": remaining_events,
                "errors": errors
            }
    
    def report_node(self, state: ComplianceState) -> ComplianceState:
        """
        Generate report for violation.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with report
        """
        event = state.get("current_event")
        evaluation = state.get("evaluation", {})
        reports_generated = state.get("reports_generated", 0)
        errors = state.get("errors", [])
        
        if not event or not evaluation.get('violation'):
            return state
        
        try:
            event_id = event['event_id']
            self.logger.info(f"Generating report for event: {event_id}")
            
            # Generate report
            report = self.reporter.generate_report(event, evaluation)
            
            # Store report in database
            violation_id = evaluation.get('violation_id')
            if violation_id and report.get('file_path'):
                self.db_manager.insert_evidence_report(
                    violation_id=violation_id,
                    event_id=event_id,
                    evidence_text=report.get('evidence_text', ''),
                    remediation_steps=report.get('remediation_steps', ''),
                    file_path=report.get('file_path')
                )
            
            # Mark event as processed
            self.db_manager.update_event_status(event_id, 'processed')
            
            reports_generated += 1
            
            return {
                **state,
                "report": report,
                "reports_generated": reports_generated
            }
            
        except Exception as e:
            self.logger.error(f"Error generating report: {e}", exc_info=True)
            errors.append(f"Report error: {str(e)}")
            
            # Still mark as processed even if report fails
            if event:
                self.db_manager.update_event_status(event['event_id'], 'processed')
            
            return {
                **state,
                "errors": errors
            }
    
    def finalize_node(self, state: ComplianceState) -> ComplianceState:
        """
        Finalize workflow execution.
        
        Args:
            state: Current workflow state
            
        Returns:
            Final state
        """
        # Check if there are more events to process
        remaining_events = state.get("events", [])
        
        if remaining_events:
            # Continue processing remaining events
            return self.evaluate_node(state)
        
        # All events processed
        violations = state.get("violations_found", 0)
        reports = state.get("reports_generated", 0)
        errors = state.get("errors", [])
        
        self.logger.info(
            f"Workflow complete: {violations} violations found, "
            f"{reports} reports generated, {len(errors)} errors"
        )
        
        return state
    
    def should_generate_report(self, state: ComplianceState) -> str:
        """
        Determine if report should be generated.
        
        Args:
            state: Current workflow state
            
        Returns:
            Next node name
        """
        evaluation = state.get("evaluation", {})
        
        if evaluation.get('violation'):
            return "report"
        
        # Check if more events to process
        if state.get("events"):
            return "finalize"  # Will loop back to evaluate
        
        return "finalize"
    
    def run(self) -> Dict[str, Any]:
        """
        Run the compliance workflow.
        
        Returns:
            Workflow execution results
        """
        try:
            self.logger.info("Starting compliance workflow...")
            
            # Initialize state
            initial_state: ComplianceState = {
                "events": [],
                "current_event": {},
                "evaluation": {},
                "report": {},
                "violations_found": 0,
                "reports_generated": 0,
                "errors": []
            }
            
            # Execute workflow
            final_state = self.graph.invoke(initial_state)
            
            # Return summary
            return {
                "success": True,
                "violations_found": final_state.get("violations_found", 0),
                "reports_generated": final_state.get("reports_generated", 0),
                "errors": final_state.get("errors", []),
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Workflow execution error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }

# Made with Bob
