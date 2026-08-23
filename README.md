# Bug Finder

Bug Finder helps you find old GitHub issues that are similar to a bug you are dealing with.

The idea is simple: describe the problem in your own words, and Bug Finder searches for GitHub issues that look related. This can save time when somebody has already run into the same problem before.

## What it can do

Bug Finder currently has two ways to search:

- **Search Indexed Repositories** — searches repositories that were already added to Bug Finder.
- **Search Public GitHub** — searches current public GitHub issues. If you know the repository, you can enter it to make the search more focused.

You can also add more issue data in two ways:

- **Add a GitHub Repository** — enter something like `psf/requests` and Bug Finder downloads the issues labeled `bug`, stores them, and makes them searchable.
- **Upload GitHub Issue Data** — if you already have GitHub issue data saved as JSON, you can upload it instead.

Most people will not need the JSON option.

## Screenshots

### Main page and instructions
![Bug Finder home](assets/screenshots/bug-finder-home.png)

### Indexed and live GitHub search
![Bug Finder search](assets/screenshots/bug-finder-search.png)

### Adding more issue data
![Bug Finder add issues](assets/screenshots/bug-finder-add-issues.png)

## How to use it

### Search repositories already in Bug Finder

1. Choose a repository, or choose **All repositories**.
2. Describe the bug in your own words.
3. Click **Search Indexed Repositories**.
4. Scroll down to see the closest matches.
5. Open a result to read the original GitHub issue.

Two repositories I used while building and testing the project are:

- `pandas-dev/pandas`
- `open-metadata/OpenMetadata`

### Search public GitHub

1. If you know the repository, enter it in the optional repository box. Example: `psf/requests`.
2. Describe the bug in your own words.
3. Click **Search Public GitHub**.
4. Scroll down to see the results.

You can leave the repository box blank to search across public GitHub issues, but entering a repository usually gives a more focused search.

Live GitHub search uses GitHub's API, so repeated searches can temporarily hit the API rate limit. Wait for a search to finish before clicking the button again.

## Example

I tested the live search using this description:

> upload body gets lost after a redirect and the request eventually times out

with the repository set to `psf/requests`.

Bug Finder returned several related redirect/body/timeout issues, including the issue I was trying to find: `psf/requests #7432`.

The target issue appeared at rank 5 in that test.

## How the search works

For the indexed search, Bug Finder stores GitHub issue data in PostgreSQL and creates an embedding for each issue using `all-MiniLM-L6-v2`.

When you type a bug description, the app:

1. turns your description into an embedding,
2. finds similar issues,
3. checks for useful title-word matches,
4. reranks the candidates,
5. returns the top results.

The current final score is:

```text
85% semantic similarity
15% title overlap
```

The public GitHub search works a little differently. GitHub is first used to find a smaller set of possible issues. Bug Finder then compares those candidates to the full bug description and reranks them locally.

## Data used while building the project

I started with OpenMetadata and later added pandas so I could test whether the system still worked across more than one repository.

The indexed test database contains:

- **1,824** OpenMetadata bug issues
- **9,512** pandas bug issues
- **11,336 issues total**

The data comes from public GitHub issues.

## Evaluation

I did not want to judge the search only by looking at a few examples, so I also made small evaluation sets using known issues and paraphrased bug descriptions.

On a 20-query multi-repository evaluation set:

| Method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic search | 70% | 90% | 90% | 0.783 |
| Semantic + title reranking | **80%** | **100%** | **100%** | **0.868** |

For the pandas half of the test set, Hit@1 improved from **50% to 70%** after title-aware reranking. OpenMetadata stayed the same at **90% Hit@1**.

This is a small manually written benchmark, so I treat the numbers as project evaluation results rather than a general claim about all GitHub issues.

## Tech used

- Python
- SQL
- PostgreSQL
- pgvector
- FastAPI
- Jinja2 / HTML
- GitHub REST API
- sentence-transformers
- `all-MiniLM-L6-v2`

## Project structure

```text
app/                  FastAPI web app
database/             schema and database setup
evaluation/           search evaluation scripts and test queries
queries/              SQL analysis queries
scripts/              extraction, loading, embeddings, and search
data/                  local/raw data folders
docs/                  project notes and results
assets/screenshots/    README screenshots
```

## Running it locally

Install the project dependencies, make sure PostgreSQL is running, and then start the app with:

```bash
python3 -m uvicorn app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

For live GitHub search, set a GitHub token in your environment as `GITHUB_TOKEN` so you are not limited to unauthenticated API requests.

## Current limitations

- GitHub's API has rate limits, especially for search.
- Live search is still dependent on GitHub returning useful candidates before the local reranker can compare them.
- Large repositories can take a while to download, store, and embed.
- Search results are similar historical issues, not guaranteed fixes.
- The JSON uploader expects GitHub issue-style data rather than any random JSON file.

## Why I made it

I wanted a SQL project that did more than run queries on a static dataset. While working on it, I kept expanding it into something I could actually use.

The project now covers collecting real public data, designing a PostgreSQL database, writing SQL, building search and ranking logic, evaluating the results, and putting everything behind a small web app.
