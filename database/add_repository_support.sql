CREATE TABLE IF NOT EXISTS repositories (
    repository_id BIGSERIAL PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT UNIQUE NOT NULL,
    html_url TEXT
);

ALTER TABLE issues
ADD COLUMN IF NOT EXISTS repository_id BIGINT;

ALTER TABLE issues
DROP CONSTRAINT IF EXISTS issues_issue_number_key;

ALTER TABLE issues
ADD CONSTRAINT fk_issue_repository
FOREIGN KEY (repository_id)
REFERENCES repositories(repository_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_repo_number
ON issues(repository_id, issue_number);

CREATE INDEX IF NOT EXISTS idx_issues_repository_id
ON issues(repository_id);