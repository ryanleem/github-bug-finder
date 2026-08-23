import argparse

import psycopg2
from sentence_transformers import SentenceTransformer


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Semantic bug search across GitHub repositories."
    )

    parser.add_argument(
        "--repo",
        help="Filter search to one repository, for example pandas-dev/pandas",
    )

    parser.add_argument(
        "--all-repos",
        action="store_true",
        help="Search across all repositories",
    )

    parser.add_argument(
        "query",
        nargs="+",
        help="Bug description to search for",
    )

    return parser.parse_args()


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def search(
    query,
    repo=None,
    limit=10,
):
    model = SentenceTransformer(
        MODEL_NAME
    )

    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
    ).tolist()

    conn = connect()
    cur = conn.cursor()

    if repo:
        cur.execute(
            """
            SELECT
                i.issue_number,
                i.title,
                i.state,
                i.html_url,
                r.full_name,
                1 - (
                    i.embedding <=> %s::vector
                ) AS similarity

            FROM issues i

            JOIN repositories r
                ON i.repository_id =
                   r.repository_id

            WHERE
                i.embedding IS NOT NULL
                AND r.full_name = %s

            ORDER BY
                i.embedding <=> %s::vector

            LIMIT %s;
            """,
            (
                query_embedding,
                repo,
                query_embedding,
                limit,
            ),
        )

    else:
        cur.execute(
            """
            SELECT
                i.issue_number,
                i.title,
                i.state,
                i.html_url,
                r.full_name,
                1 - (
                    i.embedding <=> %s::vector
                ) AS similarity

            FROM issues i

            JOIN repositories r
                ON i.repository_id =
                   r.repository_id

            WHERE
                i.embedding IS NOT NULL

            ORDER BY
                i.embedding <=> %s::vector

            LIMIT %s;
            """,
            (
                query_embedding,
                query_embedding,
                limit,
            ),
        )

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return rows


def main():
    args = parse_args()

    if args.repo and args.all_repos:
        raise ValueError(
            "Use either --repo or --all-repos, not both."
        )

    query = " ".join(args.query)

    if args.repo:
        repo = args.repo
    else:
        repo = None

    print()
    print("=" * 72)
    print("SEMANTIC BUG SEARCH")
    print("=" * 72)
    print(f"Query: {query}")

    if repo:
        print(f"Repository: {repo}")
    else:
        print("Repository: ALL")

    print()

    results = search(
        query=query,
        repo=repo,
    )

    if not results:
        print("No results found.")
        return

    for rank, row in enumerate(
        results,
        start=1,
    ):
        (
            issue_number,
            title,
            state,
            url,
            repository,
            similarity,
        ) = row

        print(
            f"{rank}. "
            f"{repository} "
            f"#{issue_number}"
        )

        print(
            f"   {title}"
        )

        print(
            f"   Similarity: "
            f"{float(similarity):.4f}"
        )

        print(
            f"   State: {state}"
        )

        print(
            f"   {url}"
        )

        print()


if __name__ == "__main__":
    main()