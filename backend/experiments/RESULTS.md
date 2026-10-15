# Chunk-size experiment

Measured with real `BAAI/bge-small-en-v1.5` CPU embeddings on Windows/Python 3.14.6.
The authored corpus contains 5 pages, 7,122 cleaned characters, and 8 queries with
explicit expected evidence. Full provenance, timings, and retrieved passages are
in `results.json`; the input is in `corpus.json`. No user documents were used.

| Window (characters) | Overlap | Chunks | Embedded characters | Vector payload* | Warm embed seconds | Hit@1 | Hit@3 | MRR |
|---|---|---|---|---|---|---|---|---|
| 256 | 64 | 37 | 9,170 | 56,832 bytes | 0.669 | 50.0% | 100% | 0.729 |
| 512 | 64 | 17 | 7,890 | 26,112 bytes | 0.501 | 62.5% | 100% | 0.812 |
| 1024 | 64 | 10 | 7,442 | 15,360 bytes | 0.597 | 75.0% | 100% | 0.875 |

*384 float32 values per vector, excluding database row/index overhead.

Hit@k means a returned chunk contains the entire annotated evidence string within
the first k results. MRR is the mean of 1/(first relevant rank), or zero if no chunk
contains the complete evidence. This criterion deliberately exposes split evidence
at chunk boundaries, but favors larger windows. It is not a human relevance rating.

The 1024-character setting ranks complete evidence first more often and uses fewer
vectors here, so it is the provisional application default. The 512 setting had the
shortest elapsed embedding time in this run, despite having more chunks: attention
cost, padding, and batching also matter. Single-run timings are noisy and too small
to establish a latency winner. Larger chunks also return more context, including
potentially irrelevant material; inspect the recorded passages, not just the scores.

Keeping overlap at 64 means overlap fractions differ: 25%, 12.5%, and 6.25%. The
256 setting embeds about 29% more characters than the source, versus about 4.5%
for 1024. This experiment varies absolute chunk size with fixed overlap; it does
not isolate size from overlap ratio. Run a second comparison using equal ratios.

The real model measured cosine(dog, puppy) = 0.867 and cosine(dog, screwdriver) =
0.595. The unrelated word pair still has positive similarity. Scores are model-
and corpus-dependent; do not interpret 0.6 as a universal relevance threshold.

Limits: small synthetic English corpus, one timing run after model warmup, no
human judgments, no multilingual/scanned/table-heavy documents. Search timings in
JSON are in-memory exact cosine computations, not PostgreSQL latency. A separate
disposable PostgreSQL smoke test verified actual vector storage and cosine retrieval.

Next experiments:

1. Replace the corpus with real documents and 20–50 independently written queries.
2. Annotate supporting passages before inspecting retrieval outputs.
3. Compare overlap 0/64/128 and constant-overlap-ratio settings.
4. Repeat timing runs, randomize order, and report median/p95 on deployment hardware.
5. Compare top-k 1/3/5/10, irrelevant-query behavior, returned context length, and
   evidence split across chunks. Keep a held-out query set for the final choice.
6. Measure exact PostgreSQL retrieval at realistic scale before adding HNSW.
