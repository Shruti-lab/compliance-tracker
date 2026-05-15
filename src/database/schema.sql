-- Compliance Tracker Database Schema
-- PostgreSQL Database Schema for Continuous Compliance Monitoring

-- Drop tables if they exist (for clean setup)
DROP TABLE IF EXISTS evidence_reports CASCADE;
DROP TABLE IF EXISTS violations CASCADE;
DROP TABLE IF EXISTS normalized_events CASCADE;
DROP TABLE IF EXISTS raw_events CASCADE;

-- Raw events table - stores original event data from cloud providers
CREATE TABLE raw_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    source VARCHAR(50) NOT NULL,
    raw_data JSONB NOT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for raw_events
CREATE INDEX idx_raw_events_source ON raw_events(source);
CREATE INDEX idx_raw_events_received_at ON raw_events(received_at);

-- Normalized events table - standardized event format
CREATE TABLE normalized_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    raw_event_id INTEGER REFERENCES raw_events(id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(500) NOT NULL,
    resource_type VARCHAR(100),
    actor VARCHAR(500),
    region VARCHAR(100),
    timestamp TIMESTAMP NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

-- Create indexes for normalized_events
CREATE INDEX idx_normalized_events_status ON normalized_events(status);
CREATE INDEX idx_normalized_events_event_type ON normalized_events(event_type);
CREATE INDEX idx_normalized_events_timestamp ON normalized_events(timestamp);
CREATE INDEX idx_normalized_events_resource_id ON normalized_events(resource_id);

-- Violations table - stores detected compliance violations
CREATE TABLE violations (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) NOT NULL,
    normalized_event_id INTEGER REFERENCES normalized_events(id) ON DELETE CASCADE,
    framework VARCHAR(100) NOT NULL,
    control_id VARCHAR(100) NOT NULL,
    control_description TEXT,
    severity VARCHAR(50) NOT NULL,
    violation_reason TEXT NOT NULL,
    llm_evaluation TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP
);

-- Create indexes for violations
CREATE INDEX idx_violations_framework ON violations(framework);
CREATE INDEX idx_violations_severity ON violations(severity);
CREATE INDEX idx_violations_resolved ON violations(resolved);
CREATE INDEX idx_violations_detected_at ON violations(detected_at);

-- Evidence reports table - stores audit-ready evidence and remediation
CREATE TABLE evidence_reports (
    id SERIAL PRIMARY KEY,
    violation_id INTEGER REFERENCES violations(id) ON DELETE CASCADE,
    event_id VARCHAR(255) NOT NULL,
    evidence_text TEXT NOT NULL,
    remediation_steps TEXT NOT NULL,
    report_format VARCHAR(50) DEFAULT 'markdown',
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_path VARCHAR(500)
);

-- Create indexes for evidence_reports
CREATE INDEX idx_evidence_reports_violation_id ON evidence_reports(violation_id);
CREATE INDEX idx_evidence_reports_generated_at ON evidence_reports(generated_at);

-- Create a view for quick violation summary
CREATE OR REPLACE VIEW violation_summary AS
SELECT 
    v.framework,
    v.severity,
    COUNT(*) as violation_count,
    COUNT(CASE WHEN v.resolved = FALSE THEN 1 END) as unresolved_count,
    MAX(v.detected_at) as latest_violation
FROM violations v
GROUP BY v.framework, v.severity
ORDER BY v.framework, 
    CASE v.severity 
        WHEN 'critical' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'medium' THEN 3 
        WHEN 'low' THEN 4 
    END;

-- Create a view for pending events processing queue
CREATE OR REPLACE VIEW pending_events_queue AS
SELECT 
    ne.id,
    ne.event_id,
    ne.event_type,
    ne.resource_id,
    ne.timestamp,
    ne.created_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ne.created_at)) as age_seconds
FROM normalized_events ne
WHERE ne.status = 'pending'
ORDER BY ne.timestamp ASC;

-- Comments for documentation
COMMENT ON TABLE raw_events IS 'Stores original event data from cloud providers (IBM, AWS) for audit trail';
COMMENT ON TABLE normalized_events IS 'Standardized event format for processing by compliance agents';
COMMENT ON TABLE violations IS 'Detected compliance violations with framework mapping';
COMMENT ON TABLE evidence_reports IS 'Audit-ready evidence and remediation guidance';
COMMENT ON VIEW violation_summary IS 'Quick summary of violations by framework and severity';
COMMENT ON VIEW pending_events_queue IS 'Queue of events waiting to be processed by agents';

-- Made with Bob
