import os
import requests
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import psycopg2
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sentence_transformers import SentenceTransformer


# --------------------------------------------------
# Configuration
# --------------------------------------------------

DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432

MODEL_NAME = "all-MiniLM-L6-v2"

SEMANTIC_CANDIDATES = 100
RESULT_LIMIT = 10
GITHUB_API = "https://api.github.com"

LIVE_GITHUB_CANDIDATES = 50
LIVE_GITHUB_RESULTS = 10

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


# --------------------------------------------------
# FastAPI
# --------------------------------------------------

app = FastAPI(
    title="Bug Finder"
)

templates = Jinja2Templates(
    directory=str(
        PROJECT_ROOT / "app" / "templates"
    )
)

print("Loading search model...")

model = SentenceTransformer(
    MODEL_NAME
)

print("Search model ready.")


# --------------------------------------------------
# Database
# --------------------------------------------------

def connect():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        host=DB_HOST,
        port=DB_PORT,
    )


def get_repositories():
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            r.full_name,
            COUNT(i.issue_id)

        FROM repositories r

        JOIN issues i
            ON i.repository_id = r.repository_id

        GROUP BY
            r.repository_id,
            r.full_name

        ORDER BY
            r.full_name;
        """
    )

    repositories = [
        {
            "name": row[0],
            "count": row[1],
        }
        for row in cur.fetchall()
    ]

    cur.close()
    conn.close()

    return repositories


def repository_exists(repository):
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM repositories r

            JOIN issues i
                ON i.repository_id =
                   r.repository_id

            WHERE
                r.full_name = %s
        );
        """,
        (repository,),
    )

    exists = cur.fetchone()[0]

    cur.close()
    conn.close()

    return exists


# --------------------------------------------------
# Search
# --------------------------------------------------

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


def search_bugs(
    query,
    repository,
):
    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
    ).tolist()

    query_terms = extract_query_terms(
        query
    )

    conn = connect()
    cur = conn.cursor()

    if repository == "ALL":
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
                repository,
                query_embedding,
                SEMANTIC_CANDIDATES,
            ),
        )

    rows = cur.fetchall()

    cur.close()
    conn.close()

    scored = []

    for row in rows:
        (
            issue_number,
            title,
            state,
            url,
            repo,
            semantic_score,
        ) = row

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
            {
                "issue_number":
                    issue_number,

                "title":
                    title,

                "state":
                    state,

                "url":
                    url,

                "repository":
                    repo,

                "semantic_score":
                    float(
                        semantic_score
                    ),

                "title_overlap":
                    overlap,

                "final_score":
                    final_score,
            }
        )

    scored.sort(
        key=lambda item:
            item["final_score"],
        reverse=True,
    )

    return scored[:RESULT_LIMIT]


# --------------------------------------------------
# Commands
# --------------------------------------------------

def run_command(command):
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Unknown command error."
        )

        raise RuntimeError(
            message
        )

    return result.stdout


# --------------------------------------------------
# GitHub repository ingestion
# --------------------------------------------------

def validate_repository_name(repository):
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            repository,
        )
    )


def repo_output_file(repository):
    safe_name = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        repository,
    )

    return (
        PROJECT_ROOT
        / "data"
        / "raw"
        / f"{safe_name}_bug_issues.json"
    )


def ingest_repository(repository):
    run_command(
        [
            sys.executable,
            "scripts/extract_issues.py",
            "--repo",
            repository,
            "--label",
            "bug",
        ]
    )

    output_file = repo_output_file(
        repository
    )

    if not output_file.exists():
        raise RuntimeError(
            "The extractor finished, but the expected "
            "JSON file was not created."
        )

    run_command(
        [
            sys.executable,
            "scripts/load_postgres.py",
            "--file",
            str(output_file),
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/generate_embeddings.py",
        ]
    )


# --------------------------------------------------
# Flexible JSON upload
# --------------------------------------------------

def detect_repository_from_json(data):
    if not isinstance(
        data,
        dict,
    ):
        return None

    repository = data.get(
        "repository"
    )

    if isinstance(
        repository,
        str,
    ):
        return repository

    if isinstance(
        repository,
        dict,
    ):
        full_name = repository.get(
            "full_name"
        )

        if isinstance(
            full_name,
            str,
        ):
            return full_name

    repo = data.get(
        "repo"
    )

    if isinstance(
        repo,
        str,
    ):
        return repo

    return None


def extract_issue_list(data):
    # Raw JSON array:
    #
    # [
    #   {...},
    #   {...}
    # ]

    if isinstance(
        data,
        list,
    ):
        return data

    if not isinstance(
        data,
        dict,
    ):
        return None

    # Bug Finder format
    if isinstance(
        data.get("issues"),
        list,
    ):
        return data["issues"]

    # GitHub Search API format
    if isinstance(
        data.get("items"),
        list,
    ):
        return data["items"]

    # Common generic API wrapper
    if isinstance(
        data.get("data"),
        list,
    ):
        return data["data"]

    # Another common wrapper
    if isinstance(
        data.get("results"),
        list,
    ):
        return data["results"]

    return None


def looks_like_github_issue(issue):
    if not isinstance(
        issue,
        dict,
    ):
        return False

    # These are the most important fields
    # used by our current loader.
    required_fields = {
        "id",
        "number",
        "title",
    }

    return required_fields.issubset(
        issue.keys()
    )


def normalize_uploaded_json(
    data,
    repository_input,
):
    issues = extract_issue_list(
        data
    )

    if issues is None:
        raise ValueError(
            "I could not find an issue list in this JSON. "
            "Supported keys include issues, items, data, "
            "and results."
        )

    detected_repository = (
        detect_repository_from_json(
            data
        )
    )

    repository = (
        repository_input.strip()
        or detected_repository
        or ""
    )

    if not repository:
        raise ValueError(
            "The JSON does not include a repository name. "
            "Enter one using owner/repository format."
        )

    if not validate_repository_name(
        repository
    ):
        raise ValueError(
            "Repository must use owner/repository format."
        )

    normalized_issues = []

    skipped_pull_requests = 0
    skipped_invalid = 0

    for issue in issues:
        if not isinstance(
            issue,
            dict,
        ):
            skipped_invalid += 1
            continue

        # GitHub's issues API may include
        # pull requests. Bug Finder only
        # wants actual issues.
        if "pull_request" in issue:
            skipped_pull_requests += 1
            continue

        if not looks_like_github_issue(
            issue
        ):
            skipped_invalid += 1
            continue

        normalized_issues.append(
            issue
        )

    if not normalized_issues:
        raise ValueError(
            "No usable GitHub issues were found in the file."
        )

    normalized = {
        "repository": repository,
        "label_filter": "uploaded",
        "issue_count": len(
            normalized_issues
        ),
        "issues": normalized_issues,
    }

    stats = {
        "loaded": len(
            normalized_issues
        ),
        "skipped_pull_requests":
            skipped_pull_requests,
        "skipped_invalid":
            skipped_invalid,
    }

    return normalized, stats



# --------------------------------------------------
# Live GitHub search
# --------------------------------------------------

def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bug-finder",
    }

    token = os.getenv("GITHUB_TOKEN")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


GENERIC_GITHUB_SEARCH_TERMS = {
    "bug",
    "error",
    "issue",
    "problem",
    "wrong",
    "fails",
    "failed",
    "failure",
    "broken",
    "unexpected",
    "working",
    "doesnt",
    "does",
    "gets",
    "get",
    "got",
    "after",
    "before",
    "eventually",
    "using",
    "use",
}


def extract_ordered_query_terms(query):
    words = re.findall(
        r"[A-Za-z0-9_]+",
        query.lower(),
    )

    ordered = []
    seen = set()

    for word in words:
        if (
            word in STOP_WORDS
            or word in GENERIC_GITHUB_SEARCH_TERMS
            or len(word) <= 2
            or word in seen
        ):
            continue

        seen.add(word)
        ordered.append(word)

    return ordered


def expand_github_terms(terms):
    expansions = {
        "upload": [
            "upload",
            "body",
            "stream",
        ],

        "body": [
            "body",
            "payload",
            "stream",
        ],

        "lost": [
            "lost",
            "empty",
            "consumed",
        ],

        "redirect": [
            "redirect",
            "307",
            "308",
        ],

        "timeout": [
            "timeout",
            "readtimeout",
            "timedout",
        ],

        "times": [
            "timeout",
            "timedout",
        ],

        "out": [
            "timeout",
        ],

        "request": [
            "request",
            "requests",
        ],

        "response": [
            "response",
        ],

        "connection": [
            "connection",
            "socket",
        ],

        "close": [
            "close",
            "closed",
        ],

        "closes": [
            "close",
            "closed",
        ],

        "closed": [
            "closed",
            "close",
        ],

        "groupby": [
            "groupby",
            "group",
        ],

        "categorical": [
            "categorical",
            "category",
        ],

        "category": [
            "category",
            "categorical",
        ],
    }

    expanded = []
    seen = set()

    for term in terms:
        candidates = expansions.get(
            term,
            [term],
        )

        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)

    return expanded


def build_github_search_queries(
    query,
    repository="",
):
    terms = extract_ordered_query_terms(
        query
    )

    if not terms:
        terms = [
            word
            for word in re.findall(
                r"[A-Za-z0-9_]+",
                query.lower(),
            )
            if word not in STOP_WORDS
            and len(word) > 2
        ]

        terms = list(
            dict.fromkeys(terms)
        )

    if not terms:
        fallback_query = (
            f"{query.strip()} is:issue"
        )

        if repository:
            fallback_query += (
                f" repo:{repository}"
            )

        return [fallback_query]

    expanded_terms = expand_github_terms(
        terms
    )

    candidate_pairs = []

    # Pair original concepts together.
    for i in range(len(terms)):
        for j in range(
            i + 1,
            len(terms),
        ):
            candidate_pairs.append(
                [
                    terms[i],
                    terms[j],
                ]
            )

    # Pair expanded technical variants too.
    for i in range(
        len(expanded_terms)
    ):
        for j in range(
            i + 1,
            len(expanded_terms),
        ):
            candidate_pairs.append(
                [
                    expanded_terms[i],
                    expanded_terms[j],
                ]
            )

    priority_terms = {
        "redirect",
        "307",
        "308",
        "timeout",
        "readtimeout",
        "empty",
        "consumed",
        "payload",
        "stream",
        "upload",
        "body",
        "groupby",
        "categorical",
        "category",
    }

    def pair_priority(pair):
        score = 0

        for term in pair:
            if term in priority_terms:
                score += 2

        return score

    candidate_pairs.sort(
        key=pair_priority,
        reverse=True,
    )

    search_queries = []
    seen_queries = set()

    for pair in candidate_pairs:
        if pair[0] == pair[1]:
            continue

        search_text = " ".join(
            pair
        )

        search_query = (
            f"{search_text} is:issue"
        )

        if repository:
            search_query += (
                f" repo:{repository}"
            )

        if search_query in seen_queries:
            continue

        seen_queries.add(
            search_query
        )

        search_queries.append(
            search_query
        )

        # Maximum 3 GitHub Search API calls
        # per Bug Finder search.
        if len(search_queries) >= 3:
            break

    return search_queries


def github_search_request(
    search_query,
):
    print(
        "GitHub query:",
        search_query,
    )

    response = requests.get(
        f"{GITHUB_API}/search/issues",
        headers=github_headers(),
        params={
            "q":
                search_query,

            "per_page":
                100,
        },
        timeout=30,
    )

    if response.status_code in (
        403,
        429,
    ):
        remaining = (
            response.headers.get(
                "X-RateLimit-Remaining",
                "unknown",
            )
        )

        raise RuntimeError(
            "GitHub search rate limit reached. "
            f"Remaining requests: {remaining}. "
            "Try again after the rate limit resets."
        )

    response.raise_for_status()

    return response.json().get(
        "items",
        [],
    )


def search_github_live(
    query,
    repository="",
):
    search_queries = (
        build_github_search_queries(
            query,
            repository,
        )
    )

    print(
        "Repository filter:",
        repository or "ALL",
    )

    merged_issues = {}

    for search_query in search_queries:
        items = github_search_request(
            search_query
        )

        for item in items:
            if "pull_request" in item:
                continue

            issue_id = item.get(
                "id"
            )

            if issue_id is None:
                continue

            merged_issues[
                issue_id
            ] = item

    issues = list(
        merged_issues.values()
    )

    if not issues:
        return []

    query_embedding = model.encode(
        query,
        normalize_embeddings=True,
    )

    query_terms = extract_query_terms(
        query
    )

    texts = []

    for issue in issues:
        title = issue.get(
            "title",
            "",
        )

        body = (
            issue.get(
                "body",
                "",
            )
            or ""
        )

        body = body[:6000]

        texts.append(
            title
            + "\n\n"
            + body
        )

    issue_embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
    )

    scored = []

    for (
        issue,
        issue_embedding,
    ) in zip(
        issues,
        issue_embeddings,
    ):
        semantic_score = float(
            query_embedding
            @ issue_embedding
        )

        title = issue.get(
            "title",
            "",
        )

        overlap = title_overlap(
            query_terms,
            title,
        )

        final_score = (
            0.85 * semantic_score
            + 0.15 * overlap
        )

        repository_url = issue.get(
            "repository_url",
            "",
        )

        result_repository = (
            repository_url.replace(
                "https://api.github.com/repos/",
                "",
            )
        )

        scored.append(
            {
                "issue_number":
                    issue.get("number"),

                "title":
                    title,

                "state":
                    issue.get("state"),

                "url":
                    issue.get("html_url"),

                "repository":
                    result_repository,

                "semantic_score":
                    semantic_score,

                "title_overlap":
                    overlap,

                "final_score":
                    final_score,
            }
        )

    scored.sort(
        key=lambda item:
            item["final_score"],
        reverse=True,
    )

    return scored[
        :LIVE_GITHUB_RESULTS
    ]


# --------------------------------------------------
# Home
# --------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
)
def home(
    request: Request,
    message: str = "",
    error: str = "",
):
    repositories = get_repositories()

    total_issues = sum(
        repo["count"]
        for repo in repositories
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "repositories":
                repositories,

            "query":
                "",

            "selected_repo":
                "ALL",

            "results":
                [],

            "searched":
                False,

            "message":
                message,

            "error":
                error,

            "total_issues":
                total_issues,

            "search_mode":
                "local",
        },
    )


# --------------------------------------------------
# Search
# --------------------------------------------------

@app.post(
    "/search",
    response_class=HTMLResponse,
)
def search(
    request: Request,
    query: str = Form(...),
    repository: str = Form("ALL"),
):
    repositories = get_repositories()

    total_issues = sum(
        repo["count"]
        for repo in repositories
    )

    results = []

    if query.strip():
        results = search_bugs(
            query.strip(),
            repository,
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "repositories":
                repositories,

            "query":
                query,

            "selected_repo":
                repository,

            "results":
                results,

            "searched":
                True,

            "message":
                "",

            "error":
                "",

            "total_issues":
                total_issues,

            "search_mode":
                "local",
        },
    )




# --------------------------------------------------
# Live GitHub search route
# --------------------------------------------------

@app.post(
    "/search-github",
    response_class=HTMLResponse,
)
def search_github(
    request: Request,
    query: str = Form(...),
    github_repository: str = Form(""),
):
    repositories = get_repositories()

    total_issues = sum(
        repo["count"]
        for repo in repositories
    )

    results = []
    error = ""

    github_repository = (
        github_repository.strip()
    )

    print(
        "Received repository from form:",
        repr(github_repository),
    )

    try:
        if (
            github_repository
            and not validate_repository_name(
                github_repository
            )
        ):
            raise ValueError(
                "Repository must use "
                "owner/repository format."
            )

        if query.strip():
            results = search_github_live(
                query.strip(),
                github_repository,
            )

    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "repositories":
                repositories,

            "query":
                query,

            "selected_repo":
                "ALL",

            "results":
                results,

            "searched":
                True,

            "message":
                "",

            "error":
                error,

            "total_issues":
                total_issues,

            "search_mode":
                "github",

            "github_repository":
                github_repository,
        },
    )


# --------------------------------------------------
# Add GitHub repository
# --------------------------------------------------

@app.post(
    "/add-repository"
)
def add_repository(
    repository: str = Form(...),
):
    repository = repository.strip()

    if not validate_repository_name(
        repository
    ):
        return RedirectResponse(
            url=(
                "/?error="
                + quote(
                    "Repository must use "
                    "owner/repository format."
                )
            ),
            status_code=303,
        )

    if repository_exists(
        repository
    ):
        return RedirectResponse(
            url=(
                "/?message="
                + quote(
                    "That repository is already available."
                )
            ),
            status_code=303,
        )

    try:
        ingest_repository(
            repository
        )

    except Exception as exc:
        error = str(exc)

        if len(error) > 400:
            error = (
                error[:400]
                + "..."
            )

        return RedirectResponse(
            url=(
                "/?error="
                + quote(error)
            ),
            status_code=303,
        )

    return RedirectResponse(
        url=(
            "/?message="
            + quote(
                f"{repository} was added successfully."
            )
        ),
        status_code=303,
    )


# --------------------------------------------------
# Flexible JSON upload
# --------------------------------------------------

@app.post(
    "/upload"
)
async def upload_issue_json(
    file: UploadFile = File(...),

    repository: str = Form(""),
):
    filename = (
        file.filename
        or "issues.json"
    )

    if not filename.lower().endswith(
        ".json"
    ):
        return RedirectResponse(
            url=(
                "/?error="
                + quote(
                    "Please upload a JSON file."
                )
            ),
            status_code=303,
        )

    contents = await file.read()

    try:
        data = json.loads(
            contents.decode(
                "utf-8"
            )
        )

    except Exception:
        return RedirectResponse(
            url=(
                "/?error="
                + quote(
                    "The uploaded file is not valid JSON."
                )
            ),
            status_code=303,
        )

    try:
        normalized, stats = (
            normalize_uploaded_json(
                data,
                repository,
            )
        )

    except ValueError as exc:
        return RedirectResponse(
            url=(
                "/?error="
                + quote(
                    str(exc)
                )
            ),
            status_code=303,
        )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as temp_file:
            json.dump(
                normalized,
                temp_file,
            )

            temp_path = Path(
                temp_file.name
            )

        run_command(
            [
                sys.executable,
                "scripts/load_postgres.py",
                "--file",
                str(temp_path),
            ]
        )

        run_command(
            [
                sys.executable,
                "scripts/generate_embeddings.py",
            ]
        )

    except Exception as exc:
        error = str(exc)

        if len(error) > 400:
            error = (
                error[:400]
                + "..."
            )

        return RedirectResponse(
            url=(
                "/?error="
                + quote(error)
            ),
            status_code=303,
        )

    finally:
        if temp_path:
            temp_path.unlink(
                missing_ok=True
            )

    message = (
        f"Uploaded {stats['loaded']} issues."
    )

    if stats[
        "skipped_pull_requests"
    ]:
        message += (
            f" Skipped "
            f"{stats['skipped_pull_requests']} "
            f"pull requests."
        )

    if stats[
        "skipped_invalid"
    ]:
        message += (
            f" Skipped "
            f"{stats['skipped_invalid']} "
            f"records that did not look "
            f"like GitHub issues."
        )

    return RedirectResponse(
        url=(
            "/?message="
            + quote(message)
        ),
        status_code=303,
    )