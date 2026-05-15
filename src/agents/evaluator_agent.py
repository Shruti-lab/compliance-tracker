"""Evaluator agent for compliance violation detection."""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from groq import Groq
from database import DatabaseManager
from vectorstore import ChromaComplianceStore


class EvaluatorAgent:
    """Agent that evaluates events for compliance violations using RAG and LLM."""
    
    # Event type to framework mapping
    EVENT_FRAMEWORK_MAP = {
        'COS_PUBLIC_EXPOSE': ['soc2', 'iso27001', 'hipaa', 'pci_dss', 'gdpr'],
        'IAM_USER_NO_MFA': ['soc2', 'iso27001', 'pci_dss', 'fedramp'],
        'IAM_USER_CREATE': ['soc2', 'iso27001', 'pci_dss'],
        'S3_PUBLIC_EXPOSE': ['soc2', 'iso27001', 'hipaa', 'pci_dss', 'gdpr'],
    }
    
    # Severity mapping
    SEVERITY_MAP = {
        'COS_PUBLIC_EXPOSE': 'critical',
        'S3_PUBLIC_EXPOSE': 'critical',
        'IAM_USER_NO_MFA': 'high',
        'IAM_USER_CREATE': 'medium',
    }
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        chroma_store: ChromaComplianceStore,
        groq_api_key: str,
        model: str = 'llama-3.3-70b-versatile',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize evaluator agent.
        
        Args:
            db_manager: Database manager instance
            chroma_store: ChromaDB store instance
            groq_api_key: Groq API key
            model: Groq model name
            logger: Logger instance
        """
        self.db_manager = db_manager
        self.chroma_store = chroma_store
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize Groq client
        self.groq_client = Groq(api_key=groq_api_key)
        self.model = model
        
        self.logger.info(f"Evaluator agent initialized with model: {model}")
    
    def evaluate_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a single event for compliance violations.
        
        Args:
            event: Normalized event dictionary
            
        Returns:
            Evaluation result with violation details if found
        """
        try:
            event_id = event['event_id']
            event_type = event['event_type']
            
            self.logger.info(f"Evaluating event {event_id} (type: {event_type})")
            
            # Check if event type requires evaluation
            if event_type not in self.EVENT_FRAMEWORK_MAP:
                self.logger.debug(f"Event type {event_type} not in evaluation map")
                return {'violation': False, 'reason': 'Event type not monitored'}
            
            # Special handling for IAM user creation - check for MFA
            if event_type == 'IAM_USER_CREATE':
                return self._evaluate_iam_user_mfa(event)
            
            # Get relevant frameworks
            frameworks = self.EVENT_FRAMEWORK_MAP[event_type]
            
            # Build query context
            query_text = self._build_query_context(event)
            
            # Retrieve relevant controls from vector store
            controls = self._retrieve_controls(query_text, frameworks)
            
            if not controls:
                self.logger.warning(f"No controls found for event {event_id}")
                return {'violation': False, 'reason': 'No applicable controls found'}
            
            # Evaluate with LLM
            evaluation = self._llm_evaluate(event, controls)
            
            return evaluation
            
        except Exception as e:
            self.logger.error(f"Error evaluating event: {e}", exc_info=True)
            return {'violation': False, 'reason': f'Evaluation error: {str(e)}'}
    
    def _evaluate_iam_user_mfa(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Special evaluation for IAM user creation - check if MFA was enabled.
        
        Args:
            event: IAM user creation event
            
        Returns:
            Evaluation result
        """
        try:
            user_id = event['resource_id']
            event_timestamp = event['timestamp']
            
            # Check if MFA event exists within 5 minutes
            mfa_exists = self.db_manager.check_mfa_event_exists(
                user_id=user_id,
                after_timestamp=event_timestamp,
                time_window_minutes=5
            )
            
            if mfa_exists:
                return {
                    'violation': False,
                    'reason': 'MFA enabled within acceptable timeframe'
                }
            
            # MFA not enabled - this is a violation
            frameworks = self.EVENT_FRAMEWORK_MAP.get('IAM_USER_NO_MFA', ['soc2'])
            
            return {
                'violation': True,
                'frameworks': frameworks,
                'severity': 'high',
                'control_id': 'IAM-MFA-001',
                'control_description': 'Multi-factor authentication required for all users',
                'violation_reason': f'User {user_id} created without MFA enabled within 5 minutes',
                'llm_evaluation': 'IAM user created without MFA violates access control requirements'
            }
            
        except Exception as e:
            self.logger.error(f"Error evaluating IAM MFA: {e}", exc_info=True)
            return {'violation': False, 'reason': f'Evaluation error: {str(e)}'}
    
    def _build_query_context(self, event: Dict[str, Any]) -> str:
        """
        Build query context for RAG retrieval.
        
        Args:
            event: Event dictionary
            
        Returns:
            Query text
        """
        event_type = event['event_type']
        resource_id = event['resource_id']
        source = event['source']
        
        # Build descriptive query
        queries = {
            'COS_PUBLIC_EXPOSE': f'{source} cloud object storage bucket {resource_id} made publicly accessible',
            'S3_PUBLIC_EXPOSE': f'{source} S3 bucket {resource_id} made publicly accessible',
            'IAM_USER_CREATE': f'{source} IAM user {resource_id} created',
        }
        
        return queries.get(event_type, f'{event_type} on {resource_id}')
    
    def _retrieve_controls(
        self,
        query_text: str,
        frameworks: List[str],
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant controls from vector store.
        
        Args:
            query_text: Query text
            frameworks: List of frameworks to query
            n_results: Number of results per framework
            
        Returns:
            List of control documents with metadata
        """
        controls = []
        
        for framework in frameworks:
            try:
                results = self.chroma_store.query(
                    framework=framework,
                    query_text=query_text,
                    n_results=n_results
                )
                
                # Extract documents and metadata
                if results['documents'] and results['documents'][0]:
                    for i, doc in enumerate(results['documents'][0]):
                        metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                        controls.append({
                            'framework': framework,
                            'document': doc,
                            'metadata': metadata,
                            'distance': results['distances'][0][i] if results['distances'] else 0
                        })
                        
            except Exception as e:
                self.logger.warning(f"Error querying {framework}: {e}")
        
        # Sort by relevance (distance)
        controls.sort(key=lambda x: x['distance'])
        
        self.logger.debug(f"Retrieved {len(controls)} controls")
        return controls[:5]  # Return top 5 most relevant
    
    def _llm_evaluate(
        self,
        event: Dict[str, Any],
        controls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use LLM to evaluate if event violates controls.
        
        Args:
            event: Event dictionary
            controls: List of relevant controls
            
        Returns:
            Evaluation result
        """
        try:
            # Build prompt
            prompt = self._build_evaluation_prompt(event, controls)
            
            # Call Groq LLM
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a compliance expert evaluating cloud infrastructure events against compliance controls. Respond in JSON format."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            # Parse response
            llm_response = response.choices[0].message.content
            self.logger.debug(f"LLM response: {llm_response}")
            
            # Parse LLM response (expecting JSON-like format)
            evaluation = self._parse_llm_response(llm_response, event, controls)
            
            return evaluation
            
        except Exception as e:
            self.logger.error(f"Error in LLM evaluation: {e}", exc_info=True)
            return {'violation': False, 'reason': f'LLM evaluation error: {str(e)}'}
    
    def _build_evaluation_prompt(
        self,
        event: Dict[str, Any],
        controls: List[Dict[str, Any]]
    ) -> str:
        """Build prompt for LLM evaluation."""
        event_desc = f"""
Event Details:
- Type: {event['event_type']}
- Resource: {event['resource_id']}
- Actor: {event['actor']}
- Timestamp: {event['timestamp']}
- Source: {event['source']}
"""
        
        controls_desc = "\n\nRelevant Compliance Controls:\n"
        for i, control in enumerate(controls, 1):
            controls_desc += f"\n{i}. Framework: {control['framework']}\n"
            controls_desc += f"   Control: {control['document'][:300]}...\n"
        
        prompt = f"""{event_desc}{controls_desc}

Question: Does this event violate any of the compliance controls listed above?

Respond in this exact format:
VIOLATION: [YES/NO]
FRAMEWORK: [primary framework name if violation]
SEVERITY: [critical/high/medium/low if violation]
CONTROL_ID: [control identifier if violation]
REASON: [brief explanation]
"""
        
        return prompt
    
    def _parse_llm_response(
        self,
        llm_response: str,
        event: Dict[str, Any],
        controls: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Parse LLM response into structured format."""
        try:
            lines = llm_response.strip().split('\n')
            result = {}
            
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    result[key.strip().lower()] = value.strip()
            
            violation = result.get('violation', 'NO').upper() == 'YES'
            
            if not violation:
                return {'violation': False, 'reason': result.get('reason', 'No violation detected')}
            
            # Extract frameworks from controls
            frameworks = list(set(c['framework'] for c in controls))
            
            return {
                'violation': True,
                'frameworks': frameworks,
                'severity': result.get('severity', self.SEVERITY_MAP.get(event['event_type'], 'medium')),
                'control_id': result.get('control_id', 'UNKNOWN'),
                'control_description': controls[0]['document'][:200] if controls else '',
                'violation_reason': result.get('reason', 'Compliance violation detected'),
                'llm_evaluation': llm_response
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing LLM response: {e}")
            return {'violation': False, 'reason': 'Failed to parse LLM response'}

# Made with Bob
