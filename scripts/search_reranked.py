import argparse
import re

import psycopg2
from sentence_transformers import SentenceTransformer


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"

SEMANTIC_CANDIDATES = 100


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "by",
    "during",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "when",
    "with",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Metadata-aware semantic bug search."
    )

    parser.add_argument(
        "--repo",
        help="Filter to one repository, for example pandas-dev/pandas",
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


def extract_query_terms(query):
    words = re.findall(
        r"[A-Za-z0-9_]+",
        query.lower(),
    )

    return {
        word
        for word in words
        if word not in STOP_WORDS
        and len(word) > 2
    }


def title_overlap(query_terms, title):
    title_terms = set(
        re.findall(
            r"[A-Za-z0-9_]+",
            (title or "").lower(),
        )
    )

    if not query_terms:
        return 0.0

    matches = len(
        query_terms.intersection(title_terms)
    )

    return matches / len(query_terms)


def fetch_candidates(
    cur,
    query_embedding,
    repo=None,
):
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
                ) AS semantic_score

            FROM issues i

            JOIN repositories r
                ON i.repository_id = r.repository_id

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
                SEMANTIC_CANDIDATES,
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
                ) AS semantic_score

            FROM issues i

            JOIN repositories r
                ON i.repository_id = r.repository_id

            WHERE i.embedding IS NOT NULL

            ORDER BY
                i.embedding <=> %s::vector

            LIMIT %s;
            """,
            (
                query_embedding,
                query_embedding,
                SEMANTIC_CANDIDATES,
            ),
        )

    return cur.fetchall()


def search_reranked(
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

    query_terms = extract_query_terms(
        query
    )

    conn = connect()
    cur = conn.cursor()

    rows = fetch_candidates(
        cur,
        query_embedding,
        repo,
    )

    cur.close()
    conn.close()

    scored = []

    for row in rows:
        (
            issue_number,
            title,
            state,
            url,
            repository,
            semantic_score,
        ) = row

        overlap_score = title_overlap(
            query_terms,
            title,
        )

        final_score = (
            0.85 * float(semantic_score)
            + 0.15 * overlap_score
        )

        scored.append(
            {
                "issue_number": issue_number,
                "title": title,
                "state": state,
                "url": url,
                "repository": repository,
                "semantic_score": float(
                    semantic_score
                ),
                "title_overlap": overlap_score,
                "final_score": final_score,
            }
        )

    scored.sort(
        key=lambda item: item["final_score"],
        reverse=True,
    )

    return scored[:limit]


def main():
    args = parse_args()

    if args.repo and args.all_repos:
        raise ValueError(
            "Use either --repo or --all-repos, not both."
        )

    query = " ".join(
        args.query
    )

    repo = args.repo

    print()
    print("=" * 72)
    print("RERANKED BUG SEARCH")
    print("=" * 72)
    print(f"Query: {query}")

    if repo:
        print(f"Repository: {repo}")
    else:
        print("Repository: ALL")

    print()

    results = search_reranked(
        query=query,
        repo=repo,
    )

    if not results:
        print("No results found.")
        return

    for rank, result in enumerate(
        results,
        start=1,
    ):
        print(
            f"{rank}. "
            f"{result['repository']} "
            f"#{result['issue_number']}"
        )

        print(
            f"   {result['title']}"
        )

        print(
            f"   Semantic: "
            f"{result['semantic_score']:.4f}"
        )

        print(
            f"   Title overlap: "
            f"{result['title_overlap']:.4f}"
        )

        print(
            f"   Final score: "
            f"{result['final_score']:.4f}"
        )

        print(
            f"   State: "
            f"{result['state']}"
        )

        print(
            f"   {result['url']}"
        )

        print()


if __name__ == "__main__":
    main()