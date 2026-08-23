import re
import psycopg2


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def contains_any(text, patterns):
    return any(
        re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        for pattern in patterns
    )


def detect_stack_trace(text):
    patterns = [
        r"traceback \(most recent call last\)",
        r"\bat .+\(.+:\d+\)",
        r"caused by:",
        r"\bexception\b.*\n",
        r"\berror\b.*\n.*\bat\b",
        r"stack trace",
    ]

    return contains_any(text, patterns)


def detect_error_log(text):
    patterns = [
        r"\berror\b",
        r"\bexception\b",
        r"\bfatal\b",
        r"\bfailed\b",
        r"\bfailure\b",
        r"\bwarning\b",
        r"\bwarn\b",
    ]

    return contains_any(text, patterns)


def detect_reproduction_steps(text):
    patterns = [
        r"steps to reproduce",
        r"steps to reproduce the issue",
        r"how to reproduce",
        r"reproduction steps",
        r"to reproduce",
        r"reproduce:",
    ]

    return contains_any(text, patterns)


def detect_expected_behavior(text):
    patterns = [
        r"expected behavior",
        r"expected result",
        r"expected outcome",
        r"what should happen",
    ]

    return contains_any(text, patterns)


def detect_actual_behavior(text):
    patterns = [
        r"actual behavior",
        r"actual result",
        r"observed behavior",
        r"current behavior",
        r"what actually happens",
    ]

    return contains_any(text, patterns)


def detect_connector(text, title, labels):
    combined = f"{title}\n{text}\n{' '.join(labels)}".lower()

    connector_names = [
        "snowflake",
        "powerbi",
        "looker",
        "tableau",
        "postgres",
        "postgresql",
        "mysql",
        "mssql",
        "bigquery",
        "databricks",
        "redshift",
        "mongodb",
        "elasticsearch",
        "kafka",
        "airflow",
        "dbt",
        "unity catalog",
        "unity-catalog",
        "mlflow",
        "trino",
        "oracle",
        "clickhouse",
        "dynamodb",
        "athena",
        "glue",
    ]

    for connector in connector_names:
        if connector in combined:
            return connector.replace("-", " ").title()

    return None


def detect_version(text):
    patterns = [
        r"openmetadata[\s\-:]*(?:version)?[\s:]*v?(\d+\.\d+(?:\.\d+)?)",
        r"\bversion[\s:]+v?(\d+\.\d+(?:\.\d+)?)",
        r"\bv(\d+\.\d+\.\d+)\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

    return None


def count_code_blocks(text):
    return text.count("```") // 2


def main():
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            i.issue_id,
            i.title,
            i.body,
            COALESCE(
                ARRAY_AGG(l.label_name)
                FILTER (WHERE l.label_name IS NOT NULL),
                ARRAY[]::TEXT[]
            ) AS labels
        FROM issues i

        LEFT JOIN issue_labels il
            ON i.issue_id = il.issue_id

        LEFT JOIN labels l
            ON il.label_id = l.label_id

        GROUP BY
            i.issue_id,
            i.title,
            i.body;
        """
    )

    issues = cur.fetchall()

    processed = 0

    for issue_id, title, body, labels in issues:
        body = body or ""
        title = title or ""

        has_stack_trace = detect_stack_trace(body)
        has_error_log = detect_error_log(body)

        has_reproduction_steps = detect_reproduction_steps(body)
        has_expected_behavior = detect_expected_behavior(body)
        has_actual_behavior = detect_actual_behavior(body)

        connector = detect_connector(
            body,
            title,
            labels,
        )

        detected_version = detect_version(body)

        body_length = len(body)
        code_block_count = count_code_blocks(body)

        cur.execute(
            """
            INSERT INTO issue_features (
                issue_id,
                has_stack_trace,
                has_error_log,
                has_reproduction_steps,
                has_expected_behavior,
                has_actual_behavior,
                connector,
                detected_version,
                body_length,
                code_block_count
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )

            ON CONFLICT (issue_id)
            DO UPDATE SET
                has_stack_trace =
                    EXCLUDED.has_stack_trace,

                has_error_log =
                    EXCLUDED.has_error_log,

                has_reproduction_steps =
                    EXCLUDED.has_reproduction_steps,

                has_expected_behavior =
                    EXCLUDED.has_expected_behavior,

                has_actual_behavior =
                    EXCLUDED.has_actual_behavior,

                connector =
                    EXCLUDED.connector,

                detected_version =
                    EXCLUDED.detected_version,

                body_length =
                    EXCLUDED.body_length,

                code_block_count =
                    EXCLUDED.code_block_count;
            """,
            (
                issue_id,
                has_stack_trace,
                has_error_log,
                has_reproduction_steps,
                has_expected_behavior,
                has_actual_behavior,
                connector,
                detected_version,
                body_length,
                code_block_count,
            ),
        )

        processed += 1

    conn.commit()

    cur.close()
    conn.close()

    print(
        f"Enriched {processed} issues "
        "and stored debugging features."
    )


if __name__ == "__main__":
    main()