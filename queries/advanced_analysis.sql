-- 1. Resolution time by label/category
WITH issue_resolution AS (
    SELECT
        i.issue_id,
        EXTRACT(EPOCH FROM (i.closed_at - i.created_at)) / 3600 AS resolution_hours
    FROM issues i
    WHERE i.closed_at IS NOT NULL
)
SELECT
    l.label_name,
    COUNT(*) AS closed_issues,
    ROUND(AVG(ir.resolution_hours)::numeric, 2) AS avg_resolution_hours
FROM issue_resolution ir
JOIN issue_labels il
    ON ir.issue_id = il.issue_id
JOIN labels l
    ON il.label_id = l.label_id
WHERE l.label_name <> 'bug'
GROUP BY l.label_name
HAVING COUNT(*) >= 2
ORDER BY avg_resolution_hours DESC;


-- 2. Rank authors by number of issues created
WITH author_counts AS (
    SELECT
        u.login,
        COUNT(*) AS issues_created
    FROM issues i
    JOIN users u
        ON i.author_id = u.user_id
    GROUP BY u.login
)
SELECT
    login,
    issues_created,
    DENSE_RANK() OVER (
        ORDER BY issues_created DESC
    ) AS author_rank
FROM author_counts
ORDER BY author_rank, login;


-- 3. Compare each closed issue to the overall average resolution time
SELECT
    issue_number,
    title,
    ROUND(
        (EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600)::numeric,
        2
    ) AS resolution_hours,
    ROUND(
        AVG(EXTRACT(EPOCH FROM (closed_at - created_at)) / 3600)
        OVER ()::numeric,
        2
    ) AS overall_avg_hours
FROM issues
WHERE closed_at IS NOT NULL
ORDER BY resolution_hours DESC;


-- 4. Percentage of issues that are still open by label
SELECT
    l.label_name,
    COUNT(*) AS total_issues,
    COUNT(*) FILTER (WHERE i.state = 'open') AS open_issues,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE i.state = 'open')
        / COUNT(*),
        2
    ) AS open_percentage
FROM issues i
JOIN issue_labels il
    ON i.issue_id = il.issue_id
JOIN labels l
    ON il.label_id = l.label_id
WHERE l.label_name <> 'bug'
GROUP BY l.label_name
HAVING COUNT(*) >= 2
ORDER BY open_percentage DESC;


-- 5. Bucket closed issues by resolution speed
SELECT
    CASE
        WHEN closed_at - created_at < INTERVAL '24 hours'
            THEN 'Under 1 day'
        WHEN closed_at - created_at < INTERVAL '3 days'
            THEN '1-3 days'
        WHEN closed_at - created_at < INTERVAL '7 days'
            THEN '3-7 days'
        ELSE '7+ days'
    END AS resolution_bucket,
    COUNT(*) AS issue_count
FROM issues
WHERE closed_at IS NOT NULL
GROUP BY resolution_bucket
ORDER BY issue_count DESC;