-- Query 1: filter closed issues
EXPLAIN ANALYZE
SELECT
    issue_number,
    title,
    created_at,
    closed_at
FROM issues
WHERE state = 'closed';


-- Query 2: issues by label
EXPLAIN ANALYZE
SELECT
    i.issue_number,
    i.title,
    l.label_name
FROM issues i
JOIN issue_labels il
    ON i.issue_id = il.issue_id
JOIN labels l
    ON il.label_id = l.label_id
WHERE l.label_name = 'Ingestion';


-- Query 3: issues assigned to developers
EXPLAIN ANALYZE
SELECT
    u.login,
    COUNT(*) AS assigned_issues
FROM issue_assignees ia
JOIN users u
    ON ia.user_id = u.user_id
GROUP BY u.login
ORDER BY assigned_issues DESC;


-- Query 4: closed issues during a date range
EXPLAIN ANALYZE
SELECT
    issue_number,
    title,
    closed_at
FROM issues
WHERE closed_at IS NOT NULL
ORDER BY closed_at DESC;

-- Query 5: recent closed issues
EXPLAIN ANALYZE
SELECT
    issue_number,
    title,
    closed_at
FROM issues
WHERE closed_at >= NOW() - INTERVAL '30 days'
ORDER BY closed_at DESC;