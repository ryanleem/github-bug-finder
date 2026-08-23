import json
import re

import psycopg2
from sentence_transformers import SentenceTransformer


DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"

TEST_FILE = "evaluation/multi_repo_queries.json"

TOP_K = 10
CANDIDATE_LIMIT = 100


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


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def load_tests():
    with open(
        TEST_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


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


def title_overlap(
    query_terms,
    title,
):
    title_terms = set(
        re.findall(
            r"[A-Za-z0-9_]+",
            (title or "").lower(),
        )
    )

    if not query_terms:
        return 0.0

    matches = len(
        query_terms.intersection(
            title_terms
        )
    )

    return (
        matches
        / len(query_terms)
    )


def semantic_search(
    cur,
    repository,
    query_embedding,
    limit=TOP_K,
):
    cur.execute(
        """
        SELECT
            i.issue_number

        FROM issues i

        JOIN repositories r
            ON i.repository_id =
               r.repository_id

        WHERE
            r.full_name = %s
            AND i.embedding IS NOT NULL

        ORDER BY
            i.embedding <=> %s::vector

        LIMIT %s;
        """,
        (
            repository,
            query_embedding,
            limit,
        ),
    )

    return [
        row[0]
        for row in cur.fetchall()
    ]


def reranked_search(
    cur,
    repository,
    query,
    query_embedding,
    limit=TOP_K,
):
    query_terms = (
        extract_query_terms(query)
    )

    cur.execute(
        """
        SELECT
            i.issue_number,
            i.title,

            1 - (
                i.embedding <=> %s::vector
            ) AS semantic_score

        FROM issues i

        JOIN repositories r
            ON i.repository_id =
               r.repository_id

        WHERE
            r.full_name = %s
            AND i.embedding IS NOT NULL

        ORDER BY
            i.embedding <=> %s::vector

        LIMIT %s;
        """,
        (
            query_embedding,
            repository,
            query_embedding,
            CANDIDATE_LIMIT,
        ),
    )

    rows = cur.fetchall()

    scored = []

    for (
        issue_number,
        title,
        semantic_score,
    ) in rows:

        overlap = title_overlap(
            query_terms,
            title,
        )

        final_score = (
            0.85
            * float(semantic_score)
            +
            0.15
            * overlap
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


def get_rank(
    results,
    relevant_issue,
):
    if relevant_issue not in results:
        return None

    return (
        results.index(
            relevant_issue
        )
        + 1
    )


def hit_at_k(
    results,
    relevant_issue,
    k,
):
    return int(
        relevant_issue
        in results[:k]
    )


def reciprocal_rank(
    results,
    relevant_issue,
):
    rank = get_rank(
        results,
        relevant_issue,
    )

    if rank is None:
        return 0.0

    return 1.0 / rank


def calculate_metrics(
    result_pairs,
):
    total = len(result_pairs)

    return {
        "Hit@1": sum(
            hit_at_k(
                results,
                target,
                1,
            )
            for results, target
            in result_pairs
        ) / total,

        "Hit@5": sum(
            hit_at_k(
                results,
                target,
                5,
            )
            for results, target
            in result_pairs
        ) / total,

        "Hit@10": sum(
            hit_at_k(
                results,
                target,
                10,
            )
            for results, target
            in result_pairs
        ) / total,

        "MRR@10": sum(
            reciprocal_rank(
                results,
                target,
            )
            for results, target
            in result_pairs
        ) / total,
    }


def print_rank(rank):
    if rank is None:
        return "Not in top 10"

    return str(rank)


def print_metrics(
    name,
    metrics,
):
    print(
        f"{name:<18}"
        f"{metrics['Hit@1'] * 100:>8.1f}%"
        f"{metrics['Hit@5'] * 100:>8.1f}%"
        f"{metrics['Hit@10'] * 100:>9.1f}%"
        f"{metrics['MRR@10']:>10.3f}"
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

    semantic_results = []
    reranked_results = []

    results_by_repo = {}

    print()
    print(
        f"Evaluating "
        f"{len(tests)} "
        f"cross-repository queries..."
    )
    print()

    for index, test in enumerate(
        tests,
        start=1,
    ):
        repository = (
            test["repository"]
        )

        query = test["query"]

        target = (
            test["relevant_issue"]
        )

        query_embedding = model.encode(
            query,
            normalize_embeddings=True,
        ).tolist()

        semantic = semantic_search(
            cur,
            repository,
            query_embedding,
        )

        reranked = reranked_search(
            cur,
            repository,
            query,
            query_embedding,
        )

        semantic_results.append(
            (
                semantic,
                target,
            )
        )

        reranked_results.append(
            (
                reranked,
                target,
            )
        )

        if repository not in results_by_repo:
            results_by_repo[
                repository
            ] = {
                "semantic": [],
                "reranked": [],
            }

        results_by_repo[
            repository
        ]["semantic"].append(
            (
                semantic,
                target,
            )
        )

        results_by_repo[
            repository
        ]["reranked"].append(
            (
                reranked,
                target,
            )
        )

        semantic_rank = get_rank(
            semantic,
            target,
        )

        reranked_rank = get_rank(
            reranked,
            target,
        )

        print(
            f"{index:>2}. "
            f"{repository} "
            f"#{target}"
        )

        print(
            "    Semantic rank: "
            + print_rank(
                semantic_rank
            )
        )

        print(
            "    Reranked rank: "
            + print_rank(
                reranked_rank
            )
        )

        print()

    semantic_metrics = (
        calculate_metrics(
            semantic_results
        )
    )

    reranked_metrics = (
        calculate_metrics(
            reranked_results
        )
    )

    print("=" * 68)
    print(
        "CROSS-REPOSITORY "
        "RETRIEVAL RESULTS"
    )
    print("=" * 68)

    print(
        f"{'Method':<18}"
        f"{'Hit@1':>9}"
        f"{'Hit@5':>9}"
        f"{'Hit@10':>10}"
        f"{'MRR@10':>10}"
    )

    print("-" * 68)

    print_metrics(
        "Semantic",
        semantic_metrics,
    )

    print_metrics(
        "Title rerank",
        reranked_metrics,
    )

    print("=" * 68)

    print()
    print(
        "RESULTS BY REPOSITORY"
    )
    print("=" * 68)

    for repository, data in (
        results_by_repo.items()
    ):
        print()
        print(repository)

        sem_metrics = (
            calculate_metrics(
                data["semantic"]
            )
        )

        rerank_metrics = (
            calculate_metrics(
                data["reranked"]
            )
        )

        print(
            f"{'Method':<18}"
            f"{'Hit@1':>9}"
            f"{'Hit@5':>9}"
            f"{'Hit@10':>10}"
            f"{'MRR@10':>10}"
        )

        print("-" * 68)

        print_metrics(
            "Semantic",
            sem_metrics,
        )

        print_metrics(
            "Title rerank",
            rerank_metrics,
        )

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()