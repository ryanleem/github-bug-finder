import psycopg2
from sentence_transformers import SentenceTransformer

DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"


def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def build_search_text(title, body):
    title = title or ""
    body = body or ""

    return f"{title}\n\n{body}"


def main():
    print(f"Loading embedding model: {MODEL_NAME}")

    model = SentenceTransformer(MODEL_NAME)

    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            issue_id,
            title,
            body
        FROM issues
        WHERE embedding IS NULL
        ORDER BY issue_id;
        """
    )

    issues = cur.fetchall()

    print(f"Issues requiring embeddings: {len(issues)}")

    if not issues:
        print("All issues already have embeddings.")
        cur.close()
        conn.close()
        return

    texts = [
        build_search_text(title, body)
        for _, title, body in issues
    ]

    print("Generating embeddings...")

    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    print("Saving embeddings to PostgreSQL...")

    for (issue_id, _, _), embedding in zip(issues, embeddings):
        cur.execute(
            """
            UPDATE issues
            SET embedding = %s
            WHERE issue_id = %s;
            """,
            (
                embedding.tolist(),
                issue_id,
            ),
        )

    conn.commit()

    cur.close()
    conn.close()

    print()
    print("=" * 60)
    print("EMBEDDING GENERATION COMPLETE")
    print("=" * 60)
    print(f"Embedded {len(issues)} issues.")


if __name__ == "__main__":
    main()