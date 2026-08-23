# Evaluation Results

## Multi-Repository Retrieval Benchmark

The current evaluation compares semantic retrieval against a lightweight title-aware reranker across two repositories:

- `pandas-dev/pandas`
- `open-metadata/OpenMetadata`

The benchmark contains 20 labeled search queries.

The reranker uses:

- 85% semantic similarity
- 15% query/title term overlap

## Overall Results

| Method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic | 70.0% | 90.0% | 90.0% | 0.783 |
| Title rerank | 80.0% | 100.0% | 100.0% | 0.868 |

## pandas-dev/pandas

| Method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic | 50.0% | 80.0% | 80.0% | 0.633 |
| Title rerank | 70.0% | 100.0% | 100.0% | 0.803 |

The pandas dataset was noticeably harder for the embedding-only search.

Adding title-term overlap improved:

- Hit@1 from 50% to 70%
- Hit@5 from 80% to 100%
- Hit@10 from 80% to 100%
- MRR@10 from 0.633 to 0.803

## open-metadata/OpenMetadata

| Method | Hit@1 | Hit@5 | Hit@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Semantic | 90.0% | 100.0% | 100.0% | 0.933 |
| Title rerank | 90.0% | 100.0% | 100.0% | 0.933 |

The reranker did not improve the OpenMetadata results, but it also did not reduce performance.

## Main Result

Across both repositories, title-aware reranking improved top-1 retrieval accuracy from 70% to 80% and MRR@10 from 0.783 to 0.868.

This suggests that semantic similarity works well for finding related bugs, while exact technical terms in issue titles can still provide useful ranking information.

## Notes

The benchmark is still relatively small, so these results should not be treated as production-level performance estimates.

The queries are manually written paraphrases of known historical bugs.

The main purpose of the evaluation is to compare retrieval approaches under the same conditions rather than claim that the system will retrieve every possible software bug correctly.