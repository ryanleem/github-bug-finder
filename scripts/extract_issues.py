import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


GITHUB_API = "https://api.github.com"
RAW_DIR = Path("data/raw")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download GitHub issues from any repository."
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/name format",
    )

    parser.add_argument(
        "--label",
        default="bug",
        help="Issue label to filter by. Default: bug",
    )

    return parser.parse_args()


def safe_repo_filename(repo):
    return re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        repo,
    )


def get_headers():
    token = os.getenv("GITHUB_TOKEN")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "openmetadata-bug-intelligence",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def github_get(url, params=None):
    if params is None:
        params = {}

    max_retries = 8

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=get_headers(),
                params=params,
                timeout=30,
            )

        except requests.RequestException as exc:
            wait_seconds = min(
                5 * (2 ** attempt),
                60,
            )

            print()
            print(
                f"Network error: {exc}"
            )

            print(
                f"Waiting {wait_seconds} seconds "
                f"before retrying..."
            )

            time.sleep(wait_seconds)

            continue

        if response.status_code not in (
            403,
            429,
        ):
            response.raise_for_status()
            return response

        remaining = response.headers.get(
            "X-RateLimit-Remaining"
        )

        reset = response.headers.get(
            "X-RateLimit-Reset"
        )

        retry_after = response.headers.get(
            "Retry-After"
        )

        print()
        print(
            f"GitHub returned "
            f"{response.status_code}."
        )

        print(
            f"Rate limit remaining: "
            f"{remaining}"
        )

        if retry_after:
            wait_seconds = (
                int(retry_after)
                + 2
            )

        elif (
            remaining == "0"
            and reset
        ):
            reset_time = int(reset)

            wait_seconds = max(
                reset_time
                - int(time.time())
                + 2,
                2,
            )

        else:
            # Likely a secondary rate limit.
            wait_seconds = min(
                60 * (2 ** attempt),
                600,
            )

        print(
            f"Waiting {wait_seconds} seconds "
            f"before retrying..."
        )

        time.sleep(wait_seconds)

    raise RuntimeError(
        "GitHub API continued rate limiting "
        "after multiple retries."
    )


def get_repo_created_date(repo):
    url = (
        f"{GITHUB_API}/repos/{repo}"
    )

    response = github_get(
        url
    )

    created_at = response.json()[
        "created_at"
    ]

    return datetime.fromisoformat(
        created_at.replace(
            "Z",
            "+00:00",
        )
    ).date()


def build_search_query(
    repo,
    label,
    start_date,
    end_date,
):
    return (
        f"repo:{repo} "
        f"is:issue "
        f'label:"{label}" '
        f"created:{start_date}..{end_date}"
    )


def search_window_count(
    repo,
    label,
    start_date,
    end_date,
):
    url = (
        f"{GITHUB_API}/search/issues"
    )

    query = build_search_query(
        repo,
        label,
        start_date,
        end_date,
    )

    response = github_get(
        url,
        {
            "q": query,
            "per_page": 1,
        },
    )

    # Slow down search requests because
    # GitHub's Search API has stricter limits.
    time.sleep(2.1)

    return response.json()[
        "total_count"
    ]


def split_window(
    repo,
    label,
    start_date,
    end_date,
):
    count = search_window_count(
        repo,
        label,
        start_date,
        end_date,
    )

    print(
        f"Checking window "
        f"{start_date} -> {end_date}: "
        f"{count} issues"
    )

    if count == 0:
        return []

    if count <= 1000:
        return [
            (
                start_date,
                end_date,
                count,
            )
        ]

    if start_date >= end_date:
        raise RuntimeError(
            "A single day contains more "
            "than 1000 matching issues. "
            "A finer split strategy is required."
        )

    total_days = (
        end_date
        - start_date
    ).days

    midpoint = (
        start_date
        + timedelta(
            days=total_days // 2
        )
    )

    left_start = start_date
    left_end = midpoint

    right_start = (
        midpoint
        + timedelta(days=1)
    )
    right_end = end_date

    left = split_window(
        repo,
        label,
        left_start,
        left_end,
    )

    right = split_window(
        repo,
        label,
        right_start,
        right_end,
    )

    return left + right


def fetch_window(
    repo,
    label,
    start_date,
    end_date,
):
    url = (
        f"{GITHUB_API}/search/issues"
    )

    query = build_search_query(
        repo,
        label,
        start_date,
        end_date,
    )

    page = 1
    issues = []

    while True:
        response = github_get(
            url,
            {
                "q": query,
                "sort": "created",
                "order": "asc",
                "per_page": 100,
                "page": page,
            },
        )

        data = response.json()

        records = data.get(
            "items",
            [],
        )

        if not records:
            break

        issues.extend(records)

        print(
            f"  Page {page}: "
            f"{len(records)} issues"
        )

        if len(records) < 100:
            break

        page += 1

        # Search API has tighter limits
        # than normal REST endpoints.
        time.sleep(2.1)

    return issues


def deduplicate_issues(issues):
    unique = {}

    for issue in issues:
        issue_id = issue.get("id")

        if issue_id is None:
            continue

        unique[issue_id] = issue

    return list(
        unique.values()
    )


def save_output(
    repo,
    label,
    issues,
):
    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        RAW_DIR
        / (
            safe_repo_filename(repo)
            + "_bug_issues.json"
        )
    )

    payload = {
        "repository": repo,
        "label_filter": label,
        "issue_count": len(issues),
        "issues": issues,
    }

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            payload,
            f,
            indent=2,
        )

    return output_file


def main():
    args = parse_args()

    repo = args.repo.strip()
    label = args.label.strip()

    if "/" not in repo:
        raise ValueError(
            "--repo must use owner/name "
            "format, for example "
            "pandas-dev/pandas"
        )

    print(
        f"Repository: {repo}"
    )

    print(
        f"Label filter: {label}"
    )

    print()

    if os.getenv(
        "GITHUB_TOKEN"
    ):
        print(
            "GitHub token detected."
        )
    else:
        print(
            "WARNING: No GITHUB_TOKEN detected."
        )

        print(
            "Large repositories may hit "
            "API limits much faster."
        )

    print()

    repo_start = (
        get_repo_created_date(
            repo
        )
    )

    today = datetime.now(
        timezone.utc
    ).date()

    print(
        f"Repository created: "
        f"{repo_start}"
    )

    print(
        f"Searching through: "
        f"{today}"
    )

    print()
    print(
        "Finding safe search windows..."
    )
    print()

    windows = split_window(
        repo,
        label,
        repo_start,
        today,
    )

    print()
    print(
        f"Created {len(windows)} "
        f"safe search windows."
    )

    print()

    all_issues = []

    for index, (
        start_date,
        end_date,
        expected_count,
    ) in enumerate(
        windows,
        start=1,
    ):
        print(
            f"Window "
            f"{index}/{len(windows)}: "
            f"{start_date} -> {end_date} "
            f"({expected_count} expected)"
        )

        window_issues = fetch_window(
            repo,
            label,
            start_date,
            end_date,
        )

        all_issues.extend(
            window_issues
        )

        print(
            f"  Downloaded "
            f"{len(window_issues)} issues "
            f"from this window."
        )

        print()

        time.sleep(2.1)

    print(
        "Deduplicating issues..."
    )

    all_issues = (
        deduplicate_issues(
            all_issues
        )
    )

    all_issues.sort(
        key=lambda issue: (
            issue.get(
                "created_at",
                "",
            ),
            issue.get(
                "number",
                0,
            ),
        )
    )

    output_file = save_output(
        repo,
        label,
        all_issues,
    )

    print()
    print(
        f"Downloaded "
        f"{len(all_issues)} "
        f"total unique issues."
    )

    print(
        f"Saved to "
        f"{output_file}"
    )


if __name__ == "__main__":
    main()