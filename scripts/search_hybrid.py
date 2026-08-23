import re
import sys
import psycopg2
from sentence_transformers import SentenceTransformer


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"

CANDIDATE_LIMIT = 50
RRF_K = 60


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
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


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def build_lexical_query(query):
    """
    Convert natural-language input into an OR-based
    PostgreSQL web-search query.

    Example:

    snowflake pipeline breaks when query tag contains quotation marks

    becomes roughly:

    snowflake OR pipeline OR breaks OR query OR tag
    OR contains OR quotation OR marks
    """

    words = re.findall(
        r"[A-Za-z0-9_]+",
        query.lower(),
    )

    words = [
        word
        for word in words
        if word not in STOP_WORDS
        and len(word) > 1
    ]

    # Remove duplicates while preserving order
    words = list(dict.fromkeys(words))

    if not words:
        return query

    return " OR ".join(words)


def search_hybrid(query, limit=10):
    print(f"Loading embedding model: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)

    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
    ).tolist()

    lexical_query = build_lexical_query(query)

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        WITH lexical AS (
            SELECT
                issue_id,

                ROW_NUMBER() OVER (
                    ORDER BY
                        ts_rank_cd(
                            search_vector,
                            websearch_to_tsquery(
                                'english',
                                %s
                            )
                        ) DESC
                ) AS lexical_rank

            FROM issues

            WHERE search_vector @@
                websearch_to_tsquery(
                    'english',
                    %s
                )

            ORDER BY
                ts_rank_cd(
                    search_vector,
                    websearch_to_tsquery(
                        'english',
                        %s
                    )
                ) DESC

            LIMIT %s
        ),

        semantic AS (
            SELECT
                issue_id,

                ROW_NUMBER() OVER (
                    ORDER BY embedding <=> %s::vector
                ) AS semantic_rank

            FROM issues

            WHERE embedding IS NOT NULL

            ORDER BY embedding <=> %s::vector

            LIMIT %s
        ),

        candidates AS (
            SELECT issue_id
            FROM lexical

            UNION

            SELECT issue_id
            FROM semantic
        ),

        fused AS (
            SELECT
                c.issue_id,

                l.lexical_rank,
                s.semantic_rank,

                COALESCE(
                    1.0 / (%s + l.lexical_rank),
                    0
                )
                +
                COALESCE(
                    1.0 / (%s + s.semantic_rank),
                    0
                ) AS rrf_score

            FROM candidates c

            LEFT JOIN lexical l
                ON c.issue_id = l.issue_id

            LEFT JOIN semantic s
                ON c.issue_id = s.issue_id
        )

        SELECT
            i.issue_number,
            i.title,
            i.state,
            i.html_url,

            f.connector,
            f.detected_version,

            fused.lexical_rank,
            fused.semantic_rank,
            fused.rrf_score

        FROM fused

        JOIN issues i
            ON fused.issue_id = i.issue_id

        LEFT JOIN issue_features f
            ON i.issue_id = f.issue_id

        ORDER BY fused.rrf_score DESC

        LIMIT %s;
        """,
        (
            lexical_query,
            lexical_query,
            lexical_query,
            CANDIDATE_LIMIT,

            query_embedding,
            query_embedding,
            CANDIDATE_LIMIT,

            RRF_K,
            RRF_K,

            limit,
        ),
    )

    results = cur.fetchall()

    cur.close()
    conn.close()

    return lexical_query, results


def main():
    if len(sys.argv) < 2:
        print(
            'Usage: python3 scripts/search_hybrid.py '
            '"your error description"'
        )
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    lexical_query, results = search_hybrid(query)

    print()
    print("=" * 72)
    print("OPENMETADATA HYBRID BUG SEARCH — RRF")
    print("=" * 72)

    print(f"Search: {query}")
    print(f"Lexical query: {lexical_query}")
    print()

    if not results:
        print("No matching historical bugs found.")
        return

    for rank, result in enumerate(
        results,
        start=1,
    ):
        (
            issue_number,
            title,
            state,
            url,
            connector,
            version,
            lexical_rank,
            semantic_rank,
            rrf_score,
        ) = result

        print(f"{rank}. Issue #{issue_number}")
        print(f"   Title: {title}")
        print(f"   State: {state}")

        if lexical_rank is not None:
            print(
                f"   Lexical rank: "
                f"{lexical_rank}"
            )
        else:
            print("   Lexical rank: —")

        if semantic_rank is not None:
            print(
                f"   Semantic rank: "
                f"{semantic_rank}"
            )
        else:
            print("   Semantic rank: —")

        print(
            f"   Hybrid RRF score: "
            f"{rrf_score:.6f}"
        )

        if connector:
            print(
                f"   Connector: "
                f"{connector}"
            )

        if version:
            print(
                f"   Detected version: "
                f"{version}"
            )

        print(f"   URL: {url}")
        print()


if __name__ == "__main__":
    main()