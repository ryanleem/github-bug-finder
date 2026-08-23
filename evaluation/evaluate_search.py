import json
import re

import psycopg2
from sentence_transformers import SentenceTransformer


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"

TEST_FILE = "evaluation/test_queries.json"

TOP_K = 10
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


CONNECTORS = {
    "postgres": "Postgres",
    "postgresql": "Postgres",
    "snowflake": "Snowflake",
    "airflow": "Airflow",
    "bigquery": "Bigquery",
    "mysql": "Mysql",
    "mssql": "Mssql",
    "sql server": "Mssql",
    "redshift": "Redshift",
    "databricks": "Databricks",
    "dbt": "Dbt",
    "tableau": "Tableau",
    "looker": "Looker",
    "kafka": "Kafka",
    "oracle": "Oracle",
    "trino": "Trino",
    "powerbi": "Powerbi",
    "power bi": "Powerbi",
    "elasticsearch": "Elasticsearch",
    "athena": "Athena",
    "glue": "Glue",
    "clickhouse": "Clickhouse",
    "unity catalog": "Unity Catalog",
}


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def load_tests():
    with open(TEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_lexical_query(query):
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

    words = list(dict.fromkeys(words))

    if not words:
        return query

    return " OR ".join(words)


def detect_query_connector(query):
    query_lower = query.lower()

    for keyword in sorted(
        CONNECTORS,
        key=len,
        reverse=True,
    ):
        if keyword in query_lower:
            return CONNECTORS[keyword]

    return None


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


def lexical_search(cur, query, limit=TOP_K):
    lexical_query = build_lexical_query(query)

    cur.execute(
        """
        SELECT issue_number
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

        LIMIT %s;
        """,
        (
            lexical_query,
            lexical_query,
            limit,
        ),
    )

    return [row[0] for row in cur.fetchall()]


def semantic_search(
    cur,
    query_embedding,
    limit=TOP_K,
):
    cur.execute(
        """
        SELECT issue_number
        FROM issues

        WHERE embedding IS NOT NULL

        ORDER BY embedding <=> %s::vector

        LIMIT %s;
        """,
        (
            query_embedding,
            limit,
        ),
    )

    return [row[0] for row in cur.fetchall()]


def hybrid_search(
    cur,
    query,
    query_embedding,
    limit=TOP_K,
):
    lexical_query = build_lexical_query(query)

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
            SELECT issue_id FROM lexical

            UNION

            SELECT issue_id FROM semantic
        ),

        fused AS (
            SELECT
                c.issue_id,

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

        SELECT i.issue_number

        FROM fused

        JOIN issues i
            ON fused.issue_id = i.issue_id

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

    return [row[0] for row in cur.fetchall()]


def reranked_search(
    cur,
    query,
    query_embedding,
    limit=TOP_K,
):
    requested_connector = detect_query_connector(
        query
    )

    query_terms = extract_query_terms(query)

    cur.execute(
        """
        SELECT
            i.issue_number,
            i.title,
            f.connector,

            1 - (
                i.embedding <=> %s::vector
            ) AS semantic_score

        FROM issues i

        LEFT JOIN issue_features f
            ON i.issue_id = f.issue_id

        WHERE i.embedding IS NOT NULL

        ORDER BY
            i.embedding <=> %s::vector

        LIMIT %s;
        """,
        (
            query_embedding,
            query_embedding,
            CANDIDATE_LIMIT,
        ),
    )

    rows = cur.fetchall()

    scored = []

    for (
        issue_number,
        title,
        connector,
        semantic_score,
    ) in rows:

        overlap_score = title_overlap(
            query_terms,
            title,
        )

        connector_match = 0.0

        if (
            requested_connector
            and connector == requested_connector
        ):
            connector_match = 1.0

        final_score = (
            0.75 * float(semantic_score)
            + 0.15 * overlap_score
            + 0.10 * connector_match
        )

        scored.append(
            (
                issue_number,
                final_score,
            )
        )

    scored.sort(
        key=lambda row: row[1],
        reverse=True,
    )

    return [
        issue_number
        for issue_number, _
        in scored[:limit]
    ]


def reciprocal_rank(
    results,
    relevant_issue,
):
    try:
        rank = (
            results.index(relevant_issue)
            + 1
        )

        return 1.0 / rank

    except ValueError:
        return 0.0


def hit_at_k(
    results,
    relevant_issue,
    k,
):
    return int(
        relevant_issue
        in results[:k]
    )


def calculate_metrics(all_results):
    total = len(all_results)

    hit1 = sum(
        hit_at_k(
            results,
            relevant,
            1,
        )
        for results, relevant
        in all_results
    ) / total

    hit5 = sum(
        hit_at_k(
            results,
            relevant,
            5,
        )
        for results, relevant
        in all_results
    ) / total

    hit10 = sum(
        hit_at_k(
            results,
            relevant,
            10,
        )
        for results, relevant
        in all_results
    ) / total

    mrr = sum(
        reciprocal_rank(
            results,
            relevant,
        )
        for results, relevant
        in all_results
    ) / total

    return {
        "Hit@1": hit1,
        "Hit@5": hit5,
        "Hit@10": hit10,
        "MRR": mrr,
    }


def get_rank(
    results,
    relevant_issue,
):
    if relevant_issue not in results:
        return "Not in top 10"

    return str(
        results.index(
            relevant_issue
        ) + 1
    )


def print_metrics(
    name,
    metrics,
):
    print(
        f"{name:<18}"
        f"{metrics['Hit@1'] * 100:>8.1f}%"
        f"{metrics['Hit@5'] * 100:>8.1f}%"
        f"{metrics['Hit@10'] * 100:>9.1f}%"
        f"{metrics['MRR']:>10.3f}"
    )


def main():
    tests = load_tests()

    print(
        f"Loading embedding model: "
        f"{MODEL_NAME}"
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    conn = connect()
    cur = conn.cursor()

    lexical_results = []
    semantic_results = []
    hybrid_results = []
    reranked_results = []

    print()
    print(
        f"Evaluating "
        f"{len(tests)} labeled queries..."
    )
    print()

    for index, test in enumerate(
        tests,
        start=1,
    ):
        query = test["query"]

        relevant_issue = (
            test["relevant_issue"]
        )

        query_embedding = model.encode(
            query,
            normalize_embeddings=True,
        ).tolist()

        lexical = lexical_search(
            cur,
            query,
        )

        semantic = semantic_search(
            cur,
            query_embedding,
        )

        hybrid = hybrid_search(
            cur,
            query,
            query_embedding,
        )

        reranked = reranked_search(
            cur,
            query,
            query_embedding,
        )

        lexical_results.append(
            (
                lexical,
                relevant_issue,
            )
        )

        semantic_results.append(
            (
                semantic,
                relevant_issue,
            )
        )

        hybrid_results.append(
            (
                hybrid,
                relevant_issue,
            )
        )

        reranked_results.append(
            (
                reranked,
                relevant_issue,
            )
        )

        print(
            f"{index:>2}. "
            f"Target #{relevant_issue}"
        )

        print(
            "    Lexical rank: "
            + get_rank(
                lexical,
                relevant_issue,
            )
        )

        print(
            "    Semantic rank: "
            + get_rank(
                semantic,
                relevant_issue,
            )
        )

        print(
            "    Hybrid rank: "
            + get_rank(
                hybrid,
                relevant_issue,
            )
        )

        print(
            "    Reranked rank: "
            + get_rank(
                reranked,
                relevant_issue,
            )
        )

        print()

    lexical_metrics = (
        calculate_metrics(
            lexical_results
        )
    )

    semantic_metrics = (
        calculate_metrics(
            semantic_results
        )
    )

    hybrid_metrics = (
        calculate_metrics(
            hybrid_results
        )
    )

    reranked_metrics = (
        calculate_metrics(
            reranked_results
        )
    )

    print("=" * 66)
    print(
        "RETRIEVAL EVALUATION RESULTS"
    )
    print("=" * 66)

    print(
        f"{'Method':<18}"
        f"{'Hit@1':>9}"
        f"{'Hit@5':>9}"
        f"{'Hit@10':>10}"
        f"{'MRR':>10}"
    )

    print("-" * 66)

    print_metrics(
        "Lexical",
        lexical_metrics,
    )

    print_metrics(
        "Semantic",
        semantic_metrics,
    )

    print_metrics(
        "Hybrid RRF",
        hybrid_metrics,
    )

    print_metrics(
        "Metadata rerank",
        reranked_metrics,
    )

    print("=" * 66)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()