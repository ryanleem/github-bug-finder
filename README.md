# Bug Finder

Bug Finder helps you search old GitHub issues to find similar bugs faster.

I made this because when I run into a bug, I usually end up searching old GitHub issues to see if someone else already had the same problem. That works, but it can take a while. Bug Finder makes that easier: describe the bug in normal words, and it shows issues that look related.

## What it does

Bug Finder has two main ways to search:

- **Search Indexed Repositories** — search repositories that are already loaded into Bug Finder.
- **Search Public GitHub** — search current public GitHub issues live.

You can also add more issue data in two ways:

- **Add a GitHub Repository** — enter a public repo such as `psf/requests` and Bug Finder downloads its issues labeled `bug` so they stay searchable.
- **Upload GitHub Issue Data** — for people who already have GitHub issue data saved as JSON.

## Screenshots

### Home and instructions

![Bug Finder home](assets/screenshots/bug-finder-home.png)

### Search

![Bug Finder search](assets/screenshots/bug-finder-search.png)

### Add issue data

![Bug Finder add issues](assets/screenshots/bug-finder-add-issues.png)

## How to use it

### Search indexed repositories

1. Pick a repository from the dropdown, or leave it on **All repositories**.
2. Describe the bug in your own words.
3. Click **Search Indexed Repositories**.
4. Scroll down to see the closest matches.

Two repositories currently used in the project are `pandas-dev/pandas` and `open-metadata/OpenMetadata`.

### Search public GitHub

1. If you know which repo the bug is from, enter it in the optional Repository box. Example: `psf/requests`.
2. Describe the bug in normal words.
3. Click **Search Public GitHub**.
4. Scroll down to see the results.

Live GitHub search uses GitHub's API, so repeated searches can temporarily hit GitHub's rate limit. Wait for a search to finish before clicking again.

## Example

I tested the public GitHub search with this description:

> upload body gets lost after a redirect and the request eventually times out

with the repository set to `psf/requests`.

The exact issue I was looking for, `psf/requests #7432` (`prepare_body` stream detection regression), appeared at rank **#5**. The higher results were also related to redirects, request bodies, and timeouts.

## How the search works

The indexed search stores GitHub issues in PostgreSQL and creates embeddings with `all-MiniLM-L6-v2`. When you type a bug description, Bug Finder compares your description with stored issues and ranks the closest matches.

The public GitHub search works a little differently:

1. It builds a few short GitHub searches from the important parts of your bug description.
2. GitHub returns possible matching issues.
3. Bug Finder combines those results and removes duplicates.
4. It compares your full description with the issue title and body.
5. It ranks the best matches and shows the top 10.

The final reranking score currently uses:

- **85% semantic similarity**
- **15% title word overlap**

The goal is not to prove that an issue is the exact fix. It is to make it faster to find old reports that are worth checking.

## Data used

The project currently uses public GitHub issue data from:

- `open-metadata/OpenMetadata` — 1,824 bug issues
- `pandas-dev/pandas` — 9,512 bug issues

That is **11,336 indexed issues** across the two main test repositories.

## Evaluation

I tested the indexed search using 20 manually written bug descriptions across pandas and OpenMetadata. The descriptions were paraphrased instead of copied directly from issue titles.

| Search method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic search | 70% | 90% | 90% | 0.783 |
| Semantic + title reranking | **80%** | **100%** | **100%** | **0.868** |

For the pandas half of the test set, Hit@1 improved from **50% to 70%** and MRR@10 improved from **0.633 to 0.803**. OpenMetadata stayed the same at 90% Hit@1.

This is a small manual benchmark, so I treat it as a useful test of the project rather than proof that the ranking will work perfectly on every repository.

## Tech used

- Python
- SQL
- PostgreSQL
- pgvector
- sentence-transformers
- FastAPI
- Jinja2 / HTML
- GitHub REST API

## Project structure

```text
app/
  main.py
  templates/
    index.html

data/
database/
docs/
evaluation/
queries/
scripts/
assets/
  screenshots/
README.md
```

## Running it locally

Clone the repo:

```bash
git clone https://github.com/ryanleem/openmetadata-bug-intelligence.git
cd openmetadata-bug-intelligence
```

Install the Python packages:

```bash
python3 -m pip install -r requirements.txt
```

Make sure PostgreSQL is running, then start the web app:

```bash
python3 -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

For live GitHub search, set a GitHub token in your environment as `GITHUB_TOKEN`. Do not put the token in the repo.

## Current limitations

- Live GitHub search depends on GitHub API rate limits.
- Large repositories can take a while to download and process.
- Search results are possible matches, not guaranteed fixes.
- The JSON upload expects GitHub issue-style data.
- The evaluation set is still small.

## Things I would improve next

- test live GitHub search on a larger set of known issues
- improve candidate search without using too many API calls
- add better filters for repository, label, and issue state
- make repository ingestion faster for large repos
- deploy the app so other people can use it online

## Why I made this

This started as a SQL project, but I wanted it to do more than just run queries on a dataset. It turned into a tool that stores real GitHub issue data, searches it, and helps find similar problems faster.

That made it a lot more useful to me than a normal SQL analysis project.
