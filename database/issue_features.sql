CREATE TABLE IF NOT EXISTS issue_features (
    issue_id BIGINT PRIMARY KEY,

    has_stack_trace BOOLEAN NOT NULL DEFAULT FALSE,
    has_error_log BOOLEAN NOT NULL DEFAULT FALSE,
    has_reproduction_steps BOOLEAN NOT NULL DEFAULT FALSE,
    has_expected_behavior BOOLEAN NOT NULL DEFAULT FALSE,
    has_actual_behavior BOOLEAN NOT NULL DEFAULT FALSE,

    connector TEXT,
    detected_version TEXT,

    body_length INTEGER,
    code_block_count INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (issue_id)
        REFERENCES issues(issue_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_issue_features_connector
ON issue_features(connector);

CREATE INDEX IF NOT EXISTS idx_issue_features_stack_trace
ON issue_features(has_stack_trace);