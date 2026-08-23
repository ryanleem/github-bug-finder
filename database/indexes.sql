-- Speed up filtering by issue state
CREATE INDEX IF NOT EXISTS idx_issues_state
ON issues(state);

-- Speed up resolution-time/date analysis
CREATE INDEX IF NOT EXISTS idx_issues_closed_at
ON issues(closed_at);

CREATE INDEX IF NOT EXISTS idx_issues_created_at
ON issues(created_at);

-- Speed up author joins
CREATE INDEX IF NOT EXISTS idx_issues_author_id
ON issues(author_id);

-- Speed up label relationship joins
CREATE INDEX IF NOT EXISTS idx_issue_labels_label_id
ON issue_labels(label_id);

-- issue_id is already covered by the composite primary key
-- (issue_id, label_id)

-- Speed up assignee lookups
CREATE INDEX IF NOT EXISTS idx_issue_assignees_user_id
ON issue_assignees(user_id);