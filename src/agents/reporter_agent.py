"""Reporter agent for generating audit evidence and remediation guidance."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from groq import Groq
from database import DatabaseManager


class ReporterAgent:
    """Agent that generates audit-ready evidence reports and remediation steps."""
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        groq_api_key: str,
        output_dir: str = 'output',
        model: str = 'llama-3.3-70b-versatile',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize reporter agent.
        
        Args:
            db_manager: Database manager instance
            groq_api_key: Groq API key
            output_dir: Directory for output reports
            model: Groq model name
            logger: Logger instance
        """
        self.db_manager = db_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize Groq client
        self.groq_client = Groq(api_key=groq_api_key)
        self.model = model
        
        self.logger.info(f"Reporter agent initialized with model: {model}")
    
    def generate_report(
        self,
        event: Dict[str, Any],
        violation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate audit evidence report for a violation.
        
        Args:
            event: Event dictionary
            violation: Violation details
            
        Returns:
            Report details with file path
        """
        try:
            event_id = event['event_id']
            self.logger.info(f"Generating report for event {event_id}")
            
            # Generate evidence text
            evidence = self._generate_evidence(event, violation)
            
            # Generate remediation steps
            remediation = self._generate_remediation(event, violation)
            
            # Create markdown report
            report_content = self._create_markdown_report(event, violation, evidence, remediation)
            
            # Save report to file
            file_path = self._save_report(event_id, report_content)
            
            self.logger.info(f"Report generated: {file_path}")
            
            return {
                'evidence_text': evidence,
                'remediation_steps': remediation,
                'report_content': report_content,
                'file_path': str(file_path)
            }
            
        except Exception as e:
            self.logger.error(f"Error generating report: {e}", exc_info=True)
            return {
                'evidence_text': f'Error generating evidence: {str(e)}',
                'remediation_steps': 'Manual review required',
                'report_content': '',
                'file_path': None
            }
    
    def _generate_evidence(
        self,
        event: Dict[str, Any],
        violation: Dict[str, Any]
    ) -> str:
        """
        Generate audit evidence text using LLM.
        
        Args:
            event: Event dictionary
            violation: Violation details
            
        Returns:
            Evidence text
        """
        try:
            prompt = f"""Generate a formal audit evidence statement for the following compliance violation:

Event Details:
- Event ID: {event['event_id']}
- Event Type: {event['event_type']}
- Resource: {event['resource_id']}
- Actor: {event['actor']}
- Timestamp: {event['timestamp']}
- Source: {event['source']}
- Region: {event['region']}

Violation Details:
- Frameworks: {', '.join(violation.get('frameworks', []))}
- Severity: {violation.get('severity', 'unknown')}
- Control: {violation.get('control_id', 'unknown')}
- Reason: {violation.get('violation_reason', 'unknown')}

Generate a professional audit evidence statement (2-3 paragraphs) that:
1. Describes what happened
2. Explains which compliance controls were violated
3. States the potential impact
4. Is suitable for inclusion in an audit report

Evidence Statement:"""

            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a compliance auditor writing formal audit evidence statements."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=800
            )
            
            evidence = response.choices[0].message.content.strip()
            return evidence
            
        except Exception as e:
            self.logger.error(f"Error generating evidence: {e}")
            return f"Evidence generation failed: {str(e)}"
    
    def _generate_remediation(
        self,
        event: Dict[str, Any],
        violation: Dict[str, Any]
    ) -> str:
        """
        Generate remediation steps using LLM.
        
        Args:
            event: Event dictionary
            violation: Violation details
            
        Returns:
            Remediation steps
        """
        try:
            # Build cloud-specific context
            source = event['source']
            event_type = event['event_type']
            resource_id = event['resource_id']
            
            prompt = f"""Generate specific remediation steps for the following compliance violation:

Cloud Provider: {source.upper()}
Event Type: {event_type}
Resource: {resource_id}
Violation: {violation.get('violation_reason', 'unknown')}
Severity: {violation.get('severity', 'unknown')}

Provide:
1. Immediate actions to remediate the violation
2. Specific commands or console steps for {source.upper()}
3. Preventive measures to avoid future violations
4. Verification steps to confirm remediation

Format as a numbered list with clear, actionable steps.

Remediation Steps:"""

            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are a cloud security expert providing remediation guidance for {source.upper()} infrastructure."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            remediation = response.choices[0].message.content.strip()
            return remediation
            
        except Exception as e:
            self.logger.error(f"Error generating remediation: {e}")
            return f"Remediation generation failed: {str(e)}"
    
    def _create_markdown_report(
        self,
        event: Dict[str, Any],
        violation: Dict[str, Any],
        evidence: str,
        remediation: str
    ) -> str:
        """
        Create markdown formatted report.
        
        Args:
            event: Event dictionary
            violation: Violation details
            evidence: Evidence text
            remediation: Remediation steps
            
        Returns:
            Markdown report content
        """
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        report = f"""# Compliance Violation Report

**Report Generated:** {timestamp}  
**Event ID:** {event['event_id']}  
**Severity:** {violation.get('severity', 'unknown').upper()}

---

## Executive Summary

A compliance violation was detected in {event['source'].upper()} infrastructure that affects the following frameworks:
{', '.join(f'**{fw.upper()}**' for fw in violation.get('frameworks', []))}

---

## Event Details

| Field | Value |
|-------|-------|
| Event Type | {event['event_type']} |
| Resource ID | {event['resource_id']} |
| Resource Type | {event.get('resource_type', 'unknown')} |
| Actor | {event['actor']} |
| Cloud Provider | {event['source'].upper()} |
| Region | {event['region']} |
| Timestamp | {event['timestamp']} |

---

## Violation Details

**Control ID:** {violation.get('control_id', 'unknown')}  
**Control Description:** {violation.get('control_description', 'N/A')}

**Violation Reason:**  
{violation.get('violation_reason', 'unknown')}

---

## Audit Evidence

{evidence}

---

## Remediation Steps

{remediation}

---

## Compliance Impact

**Affected Frameworks:**
{chr(10).join(f'- {fw.upper()}' for fw in violation.get('frameworks', []))}

**Risk Level:** {violation.get('severity', 'unknown').upper()}

---

## Next Steps

1. Review and validate the violation
2. Execute remediation steps
3. Verify compliance restoration
4. Update security policies to prevent recurrence
5. Document lessons learned

---

*This report was automatically generated by the Compliance Tracker system.*
"""
        
        return report
    
    def _save_report(self, event_id: str, content: str) -> Path:
        """
        Save report to file.
        
        Args:
            event_id: Event identifier
            content: Report content
            
        Returns:
            Path to saved file
        """
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"violation_report_{event_id}_{timestamp}.md"
        file_path = self.output_dir / filename
        
        with open(file_path, 'w') as f:
            f.write(content)
        
        return file_path

# Made with Bob
