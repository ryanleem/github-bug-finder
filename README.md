# GitHub Bug Finder

Bug Finder lets you describe a coding bug in normal words and search for GitHub issues that look similar.

I made it after noticing how often I search old GitHub issues when I run into an error. Normal keyword search works, but the wording in an issue is not always the same as the wording I would use to describe the problem.

## What It Does

Bug Finder supports two kinds of search:

- **Indexed search** — searches GitHub issues already stored in PostgreSQL.
- **Live GitHub search** — searches current public GitHub issues through the GitHub API and reranks the results.

It can also add more issue data by downloading bug-labeled issues from a public repository or by importing GitHub issue-style JSON.

## Screenshots

### Home

![Bug Finder home](assets/screenshots/bug-finder-home.png)

### Search

![Bug Finder search](assets/screenshots/bug-finder-search.png)

### Add issue data

![Bug Finder add issues](assets/screenshots/bug-finder-add-issues.png)

## How the Search Works

For indexed repositories, issue text is stored in PostgreSQL and embedded with `all-MiniLM-L6-v2`. A bug description is compared with the stored issues and the closest matches are ranked.

For live GitHub search, the app:

1. builds a few short GitHub searches from the bug description
2. collects possible issue matches
3. removes duplicates
4. compares the full description with each issue
5. reranks the best results

The current reranking score uses:

- 85% semantic similarity
- 15% title word overlap

The goal is not to claim an issue is definitely the fix. It is to move useful old reports closer to the top so they are faster to find.

## Data Used

The main indexed test data contains:

- `open-metadata/OpenMetadata` — 1,824 bug issues
- `pandas-dev/pandas` — 9,512 bug issues

That gives **11,336 indexed issues** across the two repositories.

## Evaluation

I tested indexed search with 20 manually written bug descriptions across pandas and OpenMetadata. I paraphrased the bugs instead of copying the issue titles.

| Search Method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic search | 70% | 90% | 90% | 0.783 |
| Semantic + title reranking | **80%** | **100%** | **100%** | **0.868** |

`Hit@5 = 100%` means the correct issue appeared somewhere in the first five results for every test query.

The benchmark is small, so I treat it as a useful project test rather than proof that the ranking will work the same way on every repository.

## Example

For this bug description:

> upload body gets lost after a redirect and the request eventually times out

with the repository set to `psf/requests`, the issue I was looking for appeared at rank **#5**. The results above it were also related to redirects, request bodies, and timeouts.

## How to Run It Locally

### 1. Clone the repo

```bash
git clone https://github.com/ryanleem/github-bug-finder.git
cd github-bug-finder
```

### 2. Install the Python packages

```bash
python3 -m pip install -r requirements.txt
```

### 3. Install PostgreSQL

Bug Finder uses PostgreSQL for stored issue data.

On macOS with Homebrew:

```bash
brew install postgresql@17
brew services start postgresql@17
```

The current local database settings are near the top of `app/main.py`:

```python
DB_NAME = "openmetadata_bug_intelligence"
DB_USER = "ryanleem"
DB_HOST = "localhost"
DB_PORT = 5432
```

Change `DB_USER` to your local PostgreSQL username before running the app on another machine. The project database also needs the tables/indexes used by the SQL files in `database/`.

### 4. Optional: set a GitHub token

Live GitHub search works better with an API token because unauthenticated requests have a lower rate limit.

Set it as an environment variable instead of putting it in the repository:

```bash
export GITHUB_TOKEN="your_token_here"
```

### 5. Start the app

```bash
python3 -m uvicorn app.main:app --reload
```

Open the local address shown in the terminal, normally:

```text
http://127.0.0.1:8000
```

## Tech Used

- Python
- SQL
- PostgreSQL
- pgvector
- sentence-transformers
- FastAPI
- Jinja2 / HTML
- GitHub REST API

## Project Structure

```text
app/          FastAPI app and HTML template
data/         issue data used by the project
database/     SQL tables, features, and indexes
docs/         project notes
evaluation/   search evaluation work
queries/      SQL analysis queries
scripts/      ingestion and processing scripts
assets/       screenshots
```

## Current Limitations

- Live search is limited by the GitHub API rate limit.
- Large repositories take longer to download and embed.
- Search results are possible matches, not guaranteed fixes.
- The manual evaluation set is still small.
- Local PostgreSQL setup is currently configured in `app/main.py` rather than through a full setup script.

## Why I Made It

This started as a SQL project built around public GitHub bug data. I collected issues, stored them in PostgreSQL, and wrote queries to study the data.

I eventually wanted the database work to lead to something I would actually use, so I built search on top of it. The project grew into a mix of SQL, vector search, API work, evaluation, and a small web app.

The problem is simple: when I hit a bug, I want to know whether someone has already reported something similar. Bug Finder is my attempt to make that search quicker.