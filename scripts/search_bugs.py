import sys
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


def search_bugs(query, limit=10):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            i.issue_number,
            i.title,
            i.state,
            i.html_url,
            f.connector,
            f.detected_version,
            f.has_stack_trace,
            f.has_error_log,
            ts_rank(
                i.search_vector,
                plainto_tsquery('english', %s)
            ) AS relevance
        FROM issues i
        LEFT JOIN issue_features f
            ON i.issue_id = f.issue_id
        WHERE i.search_vector @@
            plainto_tsquery('english', %s)
        ORDER BY relevance DESC
        LIMIT %s;
        """,
        (
            query,
            query,
            limit,
        ),
    )

    results = cur.fetchall()

    cur.close()
    conn.close()

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print(
            'python3 scripts/search_bugs.py '
            '"your error message here"'
        )
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    results = search_bugs(query)

    print()
    print("=" * 70)
    print("OPENMETADATA BUG INTELLIGENCE")
    print("=" * 70)
    print(f"Search: {query}")
    print()

    if not results:
        print("No matching historical bugs found.")
        return

    for rank, result in enumerate(results, start=1):
        (
            issue_number,
            title,
            state,
            url,
            connector,
            version,
            has_stack_trace,
            has_error_log,
            relevance,
        ) = result

        print(f"{rank}. Issue #{issue_number}")
        print(f"   Title: {title}")
        print(f"   State: {state}")
        print(
            f"   Relevance: "
            f"{relevance:.4f}"
        )

        if connector:
            print(f"   Connector: {connector}")

        if version:
            print(f"   Detected version: {version}")

        print(
            "   Stack trace present: "
            f"{'Yes' if has_stack_trace else 'No'}"
        )

        print(
            "   Error/log content: "
            f"{'Yes' if has_error_log else 'No'}"
        )

        print(f"   URL: {url}")
        print()


if __name__ == "__main__":
    main()