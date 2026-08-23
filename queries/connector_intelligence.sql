SELECT
    COALESCE(f.connector, 'Unknown') AS connector,

    COUNT(*) AS total_bugs,

    COUNT(*) FILTER (
        WHERE i.closed_at IS NOT NULL
    ) AS closed_bugs,

    ROUND(
        100.0 *
        COUNT(*) FILTER (WHERE i.closed_at IS NOT NULL)
        / COUNT(*),
        2
    ) AS closure_rate_pct,

    ROUND(
        AVG(
            EXTRACT(EPOCH FROM (i.closed_at - i.created_at)) / 3600
        ) FILTER (
            WHERE i.closed_at IS NOT NULL
        )::numeric,
        2
    ) AS avg_resolution_hours,

    ROUND(
        PERCENTILE_CONT(0.5)
        WITHIN GROUP (
            ORDER BY EXTRACT(
                EPOCH FROM (i.closed_at - i.created_at)
            ) / 3600
        )
        FILTER (
            WHERE i.closed_at IS NOT NULL
        )::numeric,
        2
    ) AS median_resolution_hours,

    ROUND(
        PERCENTILE_CONT(0.9)
        WITHIN GROUP (
            ORDER BY EXTRACT(
                EPOCH FROM (i.closed_at - i.created_at)
            ) / 3600
        )
        FILTER (
            WHERE i.closed_at IS NOT NULL
        )::numeric,
        2
    ) AS p90_resolution_hours,

    ROUND(
        100.0 *
        COUNT(*) FILTER (
            WHERE f.has_stack_trace
        )
        / COUNT(*),
        2
    ) AS stack_trace_pct,

    ROUND(
        100.0 *
        COUNT(*) FILTER (
            WHERE f.has_error_log
        )
        / COUNT(*),
        2
    ) AS error_log_pct

FROM issues i

JOIN issue_features f
    ON i.issue_id = f.issue_id

GROUP BY f.connector

HAVING COUNT(*) >= 10

ORDER BY total_bugs DESC;