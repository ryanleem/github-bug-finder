import argparse
import json
import os
from pathlib import Path

import psycopg2


DB_NAME = os.getenv(
    "DB_NAME",
    "openmetadata_bug_intelligence",
)

DB_USER = os.getenv(
    "DB_USER",
    "ryanleem",
)

DB_HOST = os.getenv(
    "DB_HOST",
    "localhost",
)

DB_PORT = int(
    os.getenv(
        "DB_PORT",
        "5432",
    )
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Load extracted GitHub issues "
            "into PostgreSQL."
        )
    )

    parser.add_argument(
        "--file",
        required=True,
        help=(
            "Path to an extracted repository "
            "JSON file."
        ),
    )

    return parser.parse_args()


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def load_json(file_path):
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(
            "Expected the new repository-aware "
            "JSON format."
        )

    if "repository" not in data:
        raise ValueError(
            "JSON file is missing "
            "'repository'."
        )

    if "issues" not in data:
        raise ValueError(
            "JSON file is missing "
            "'issues'."
        )

    return data


def upsert_repository(
    cur,
    full_name,
):
    if "/" not in full_name:
        raise ValueError(
            "Repository must use owner/name format."
        )

    owner, name = full_name.split(
        "/",
        1,
    )

    html_url = (
        f"https://github.com/"
        f"{owner}/{name}"
    )

    cur.execute(
        """
        INSERT INTO repositories (
            owner,
            name,
            full_name,
            html_url
        )
        VALUES (%s, %s, %s, %s)

        ON CONFLICT (full_name)
        DO UPDATE SET
            owner = EXCLUDED.owner,
            name = EXCLUDED.name,
            html_url = EXCLUDED.html_url

        RETURNING repository_id;
        """,
        (
            owner,
            name,
            full_name,
            html_url,
        ),
    )

    return cur.fetchone()[0]


def upsert_user(
    cur,
    user,
):
    if not user:
        return None

    user_id = user.get("id")

    if user_id is None:
        return None

    cur.execute(
        """
        INSERT INTO users (
            user_id,
            login,
            html_url,
            user_type
        )
        VALUES (%s, %s, %s, %s)

        ON CONFLICT (user_id)
        DO UPDATE SET
            login = EXCLUDED.login,
            html_url = EXCLUDED.html_url,
            user_type = EXCLUDED.user_type;
        """,
        (
            user_id,
            user.get("login"),
            user.get("html_url"),
            user.get("type"),
        ),
    )

    return user_id


def upsert_issue(
    cur,
    issue,
    repository_id,
):
    author_id = upsert_user(
        cur,
        issue.get("user"),
    )

    cur.execute(
        """
        INSERT INTO issues (
            issue_id,
            repository_id,
            issue_number,
            title,
            body,
            state,
            created_at,
            updated_at,
            closed_at,
            comment_count,
            author_id,
            state_reason,
            html_url
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )

        ON CONFLICT (issue_id)
        DO UPDATE SET
            repository_id =
                EXCLUDED.repository_id,

            issue_number =
                EXCLUDED.issue_number,

            title =
                EXCLUDED.title,

            body =
                EXCLUDED.body,

            state =
                EXCLUDED.state,

            created_at =
                EXCLUDED.created_at,

            updated_at =
                EXCLUDED.updated_at,

            closed_at =
                EXCLUDED.closed_at,

            comment_count =
                EXCLUDED.comment_count,

            author_id =
                EXCLUDED.author_id,

            state_reason =
                EXCLUDED.state_reason,

            html_url =
                EXCLUDED.html_url;
        """,
        (
            issue["id"],
            repository_id,
            issue["number"],
            issue["title"],
            issue.get("body"),
            issue["state"],
            issue["created_at"],
            issue["updated_at"],
            issue.get("closed_at"),
            issue.get("comments", 0),
            author_id,
            issue.get("state_reason"),
            issue.get("html_url"),
        ),
    )


def rebuild_labels(
    cur,
    issue,
):
    issue_id = issue["id"]

    cur.execute(
        """
        DELETE FROM issue_labels
        WHERE issue_id = %s;
        """,
        (issue_id,),
    )

    for label in issue.get(
        "labels",
        [],
    ):
        # GitHub can theoretically return
        # string labels through some API formats.
        if not isinstance(label, dict):
            continue

        label_id = label.get("id")
        label_name = label.get("name")

        if label_id is None:
            continue

        cur.execute(
            """
            INSERT INTO labels (
                label_id,
                label_name
            )
            VALUES (%s, %s)

            ON CONFLICT (label_id)
            DO UPDATE SET
                label_name =
                    EXCLUDED.label_name;
            """,
            (
                label_id,
                label_name,
            ),
        )

        cur.execute(
            """
            INSERT INTO issue_labels (
                issue_id,
                label_id
            )
            VALUES (%s, %s)

            ON CONFLICT DO NOTHING;
            """,
            (
                issue_id,
                label_id,
            ),
        )


def rebuild_assignees(
    cur,
    issue,
):
    issue_id = issue["id"]

    cur.execute(
        """
        DELETE FROM issue_assignees
        WHERE issue_id = %s;
        """,
        (issue_id,),
    )

    for user in issue.get(
        "assignees",
        [],
    ):
        user_id = upsert_user(
            cur,
            user,
        )

        if user_id is None:
            continue

        cur.execute(
            """
            INSERT INTO issue_assignees (
                issue_id,
                user_id
            )
            VALUES (%s, %s)

            ON CONFLICT DO NOTHING;
            """,
            (
                issue_id,
                user_id,
            ),
        )


def main():
    args = parse_args()

    data = load_json(
        args.file
    )

    repository = data["repository"]
    issues = data["issues"]

    print(
        f"Repository: {repository}"
    )

    print(
        f"Issues in file: {len(issues)}"
    )

    conn = connect()
    cur = conn.cursor()

    try:
        repository_id = (
            upsert_repository(
                cur,
                repository,
            )
        )

        print(
            f"Repository ID: "
            f"{repository_id}"
        )

        for index, issue in enumerate(
            issues,
            start=1,
        ):
            upsert_issue(
                cur,
                issue,
                repository_id,
            )

            rebuild_labels(
                cur,
                issue,
            )

            rebuild_assignees(
                cur,
                issue,
            )

            if (
                index % 250 == 0
                or index == len(issues)
            ):
                print(
                    f"Processed "
                    f"{index}/"
                    f"{len(issues)} issues"
                )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()

    print()
    print(
        f"Upserted {len(issues)} issues "
        f"from {repository}."
    )

    print(
        "Existing issues were refreshed."
    )

    print(
        "Issue-label and "
        "issue-assignee relationships "
        "were rebuilt."
    )


if __name__ == "__main__":
    main()