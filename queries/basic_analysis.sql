-- 1. Open vs closed issues
SELECT
    state,
    COUNT(*) AS issue_count
FROM issues
GROUP BY state
ORDER BY issue_count DESC;


-- 2. Most common labels
SELECT
    l.label_name,
    COUNT(*) AS issue_count
FROM issue_labels il
JOIN labels l
    ON il.label_id = l.label_id
GROUP BY l.label_name
ORDER BY issue_count DESC;


-- 3. Most active issue authors
SELECT
    u.login,
    COUNT(*) AS issues_created
FROM issues i
JOIN users u
    ON i.author_id = u.user_id
GROUP BY u.login
ORDER BY issues_created DESC
LIMIT 10;


-- 4. Most frequently assigned developers
SELECT
    u.login,
    COUNT(*) AS assigned_issues
FROM issue_assignees ia
JOIN users u
    ON ia.user_id = u.user_id
GROUP BY u.login
ORDER BY assigned_issues DESC
LIMIT 10;


-- 5. Average resolution time for closed issues
SELECT
    ROUND(
        AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600)::numeric,
        2
    ) AS avg_resolution_hours
FROM issues
WHERE closed_at IS NOT NULL;