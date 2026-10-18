# Phase 5, step 3: evaluation runner

Run from `backend/`. No PostgreSQL database is required: this benchmark uses the
production chunker and either the embedding service with exact cosine ranking or
the shared BM25 scorer (`--strategy bm25`; default `--strategy vector`).
`--strategy hybrid` combines both candidate lists through the production RRF
function, recording each list alongside the fused results. Candidate count and
rank constant come from `HYBRID_CANDIDATES` and `HYBRID_RRF_K`.
It does not replace the separate real PostgreSQL integration smoke test.

Phase 14 step 3 keeps the JSON report as the default artifact and adds optional
terminal database persistence. After applying migration `0007`, set an explicit
`DATABASE_URL` and pass `--persist` to insert one append-only `experiment_runs`
row when every question has been processed. Interrupted or incomplete reports
remain JSON checkpoints and are not inserted. Existing report files are never
overwritten; a repeated run gets a new run ID and a new output path.

## Commands

Retrieval only (default split is development):

```sh
uv run --locked python scripts/evaluate_retrieval.py --output experiments/evaluation/runs/vector-dev-new.json
```

To include generation, configure the chat provider/model route and its optional
API key in the backend environment, then add `--generate`. This explicitly
sends the synthetic questions and top-five passages to that provider. The recorded
baseline uses local Ollama `llama3.1:8b`; no external service is needed.

```sh
uv run --locked python scripts/evaluate_retrieval.py --generate --output experiments/evaluation/runs/vector-dev-new.json
```

To store the completed result in a migrated database, keep the same command and
add `--persist`. Set `DATABASE_URL` explicitly in the process environment; this
guard prevents an accidental write to the default local SQLite database. The
database row includes dataset/code fingerprints, configuration, Recall@5, P95
end-to-end question latency, and token totals. Citation accuracy and answer quality
remain null until reviewed/scored in a later step. Per-question details remain in
the JSON artifact, linked by the same run UUID. The database does not store API
keys or raw credentials.

Each generated question records the provider and model actually used, including
fallbacks, and the provider-reported prompt/completion tokens when available.
The summary and stored configuration count the actual provider/model pairs so a
fallback is visible even when the declared route stays unchanged.
Token totals remain null if any attempted generation lacks complete usage data;
`token_usage_coverage` shows how many attempts reported both counts. A question
that skips the provider for empty context uses zero tokens. P95 total latency
includes local retrieval and generation for each question, but not corpus build,
model warmup, JSON writes, HTTP API overhead, or network queueing outside the
provider call. It is not production endpoint P95.

Use `HF_HUB_OFFLINE=1` when the embedding model is already cached and network access
is unnecessary. Chunk size and overlap use `CHUNK_SIZE` and `CHUNK_OVERLAP`; the
recorded run explicitly sets 1024 and 64. Evaluation always returns five chunks,
regardless of the application's configurable chat top-k. Existing output files
are refused, preserving earlier runs. Use a fresh filename for another run.

The historical held-out split requires both `--split held_out` and `--allow-held-out`.
It was already scored in Phase 5 and is now a regression split. Structural dataset validation reads
both splits, but only the selected split is embedded, retrieved, generated, or scored.

## Metric definitions fixed before comparisons

**Recall@5** is macro-averaged annotated evidence coverage over answerable questions.
For each question, divide the number of distinct required evidence strings wholly
contained in at least one top-five chunk by the number of required strings. A match
must also have the annotated document and page. Duplicate hits do not increase the
numerator. This is evidence-unit recall, not relevant-chunk recall, and each question
has equal weight even if its number of evidence units differs.

**MRR** averages 1/rank of the first chunk containing any complete annotated evidence
unit on the correct document/page. It uses the full corpus ranking, not a cutoff
at five. No match contributes zero. A high MRR alone does not mean all evidence
needed to answer the question was retrieved.

For hybrid, the ranking covers the entire fused candidate union, bounded by the
configured per-branch candidate count. Evidence outside that union contributes
zero. The default twenty-candidate window contains this fixture's full ten-chunk
corpus; do not describe hybrid MRR as full-corpus MRR on a larger dataset.

BM25 rankings exclude zero-score chunks, matching the API. The chunking ceiling
is computed over the entire corpus, including chunks with no lexical overlap,
so retrieval misses do not get mislabeled as chunking failures.

Additional diagnostics:

- `complete_evidence_at_5`: fraction of answerable questions with every evidence
  unit covered by the top five chunks.
- `page_hit_at_5`: fraction with the right page among the first five, regardless of
  whether the required text is present. This weaker metric can hide chunking errors.
- `chunking_evidence_ceiling`: evidence coverage over the entire chunk corpus.
  If below 1, the current chunk boundaries split an evidence string so it cannot
  match under this strict criterion, even with perfect ranking.
- `unanswerable_abstention_rate`: abstentions / all unanswerable generation attempts.
  Provider/validation errors remain in the denominator and are not abstentions.
- `answerable_abstention_rate` and generation status counts expose false abstentions
  and failed requests separately. Unanswerable questions never enter Recall/MRR.
- `retrieval_ms_median` and nearest-rank `retrieval_ms_p95` include query embedding,
  cosine scoring, sorting, and result construction. Corpus embedding/model load is
  recorded separately. These are single-run local timings, not database/API latency
  or a production performance claim. Generation duration is recorded per question.

## Citation accuracy review

Generation produces `*.citations.json` alongside the run. It contains one review
unit for each claim-citation pair; a citation reused for two claims is reviewed
twice. Uncited claims are retained with a null source. Each item includes the claim,
cited document/page, and quote. The full report includes the question, expected
answer, required evidence, complete ranking, and the actual context sent to the LLM.

Read the claim and cited quote in context. Set `judgment` to `supported` only when
the cited evidence supports that claim; use `unsupported` when it does not and
`uncertain` if a reviewer cannot decide. Fill `reviewer` and add explanatory `notes`.
Review each citation independently, including claims with several citations.
Do not mark a citation correct merely because its quote is an exact substring.
Reference answers are guidance, not exact wording requirements.

Save a separate reviewed copy to preserve the unfilled template, then run:

```sh
uv run --locked python scripts/score_citation_review.py --report experiments/evaluation/runs/vector-dev-new.json --review experiments/evaluation/runs/vector-dev-new.reviewed.json
```

The scorer checks the report fingerprint, run ID, and every claim/source identity.
Only judgment/notes may change. Final `citation_accuracy` is the fraction of
claim-citation units marked supported, and is null until every unit has a definitive
supported/unsupported judgment. Partial support fraction and review coverage are
reported separately. No emitted citations means undefined accuracy, not 100%.
Abstentions and errors are excluded from citation precision but remain visible in
generation counts. This precision does not measure answer completeness or recall;
an accurate citation can accompany an incomplete answer.

Manual agent review, if recorded, must identify itself as agent review and is not
independent human annotation. Human review remains useful before drawing conclusions.

For combined answer-quality and citation review, follow [Phase 14 step 4](PHASE14_STEP4.md).

## Reproducibility and failure handling

Run files include dataset ID, corpus/split hashes, code and lockfile hashes, Git commit,
platform/Python, model names, chunk settings, prompt hash, full rankings, and timings.
The code hashes capture uncommitted implementation changes that a commit alone
would miss. Fixture UUIDs are deterministic; equal cosine scores use UUID order,
matching the application's tie-breaking form but not its randomly generated IDs.
In-memory float64 arithmetic can differ slightly from PostgreSQL vector arithmetic.
Model weights/package builds and nondeterministic LLM decoding can also affect reruns.

Results are checkpointed after each question and have `status: running` until the
run completes. Generation errors are recorded per question and do not stop later
examples. An interrupted run remains visibly incomplete; there is no automatic
resume or silent overwrite. Do not present partial-run metrics as final results.

Vector, BM25, and hybrid retrieval are implemented. The frozen annotations and
metric functions are intended to support later reranker comparisons
without redefining relevance after seeing their results.


## Step 6: reranked strategy

Use `--strategy hybrid_reranked` to fuse both candidate lists, keep at most
`RERANK_CANDIDATES` (default 20), and run the production cross-encoder before
selecting five passages. Warmup is recorded separately and excluded from query
latencies; index-build time includes warmup. Each row retains pre-rerank order,
final scores, reranking time and applied/fallback status. Summary status counts
make degraded runs visible. MRR is over the returned reranked shortlist, not all
corpus chunks. Empty lists skip scoring. Warmup errors stop evaluation; later
inference errors retain marked hybrid fallback results and must not be described
as successful reranking. See [step 6 results](RERANK_RESULTS.md).


## Step 7 completed

The approved held-out comparison and per-strategy citation reviews are recorded
in [FINAL_RESULTS.md](FINAL_RESULTS.md). The original held-out split is no longer
unseen. Reproduction should use a new output name and preserve all failures;
future tuning requires new evaluation data.
