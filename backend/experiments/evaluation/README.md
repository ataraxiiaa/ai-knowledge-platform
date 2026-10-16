# Phase 5, step 2: evaluation dataset v1

Status: step 2 accepted for progression to step 3; independent human annotation
review remains pending. The [evaluation runner](RUNNER.md) now evaluates the
development split. Held-out questions remain unscored.

## Contents

| Split | Answerable | Unanswerable | Total |
|---|---|---|---|
| `dev.json` | 30 | 3 | 33 |
| `held-out.json` | 10 | 2 | 12 |
| Total | 40 | 5 | 45 |

There are eight answerable questions per source page: six development and two
held-out. Categories cover exact terms (including HNSW), paraphrases, and contextual
explanations requiring one or several evidence sentences. Unanswerable questions
ask for names, quantities, or parameter values absent from the entire corpus.
The corpus contains no real numeric specifications; none were invented to create
answerable numeric questions.

`corpus.json` freezes the existing five authored pages from `../corpus.json`, under
the logical document identifier `authored-learning-notes`. It is a text fixture,
not a filename for an existing PDF. Page numbers preserve the original corpus's
1–5 numbering. A future ingestion adapter must map this logical identifier to the
actual uploaded document ID/filename while preserving page numbering. Do not
silently score an unrelated upload with a matching display name.

`manifest.json` records the exact corpus byte hash, split counts, origin, and
limitations. Existing eight-question baseline files remain unchanged.

## Annotation contract

- `id`: stable example identifier; do not renumber when adding examples.
- `question`: the input query, within the chat endpoint's 1024-character limit.
- `expected_document`, `expected_page`: source identity and original page number.
- `expected_answer`: reference meaning, not an exact-string generation target.
- `required_evidence`: exact source substrings supporting the reference answer.
  All listed evidence is needed for a complete answer; no chunk IDs are frozen,
  allowing later chunk-size comparisons. A chunk can contain several evidence units.
- `split`, `category`, `answerable`: evaluation grouping metadata.
- Unanswerable examples have null document/page, no positive evidence, a fixed
  abstention reference, and an `unanswerable_reason` explaining what is missing.

For future Recall@5, distinguish document/page hits from coverage of annotated
evidence. Merely retrieving the right page is insufficient to prove that the
necessary passage reached the model. Define aggregation and evidence coverage in
the [runner specification](RUNNER.md) before interpreting metrics. Unanswerable examples have no relevant retrieval
target: exclude them from positive-target Recall/MRR and report abstention behavior
separately. Citation accuracy requires checking claim support, not merely a matching
document/page or an exact quote. Metric implementation is documented in the runner specification.

## Split discipline

Use development questions for tuning. Open and score held-out questions only for
the final fixed comparison; do not tune prompts, chunking, fusion, or rerankers on
their results. If held-out results influence tuning, retire that split and create
new held-out questions. Both files are visible for review, so this is a procedural
holdout, not a secret benchmark.

Held-out questions target evidence sentences not annotated in development, and
the validator rejects exact evidence overlap across splits. This is a question-level
split, not a document-disjoint split: the same five pages appear in both. Related
concepts still overlap. Some development topics appeared in the earlier eight-query
smoke experiment; they are deliberately not claimed as unseen evaluation topics.

## Validation and review

From `backend/`:

```sh
uv run --locked python scripts/validate_evaluation_dataset.py
```

This standard-library-only validator checks corpus hash and source preservation,
IDs, duplicate questions, split counts, source/page existence, exact evidence,
cross-split evidence reuse, and abstention annotation shape. It performs no network,
model, database, or retrieval calls. It does not establish semantic correctness.

Validation on 2026-10-16 passed for all 45 examples: 10 paraphrase, 16 context,
14 exact-term, and five unanswerable questions. Five negative checks also passed:
the validator rejected a missing quote, a nonexistent page, a duplicate question,
cross-split evidence reuse, and a changed corpus fingerprint in temporary copies.
`git diff --check` passed. Application code and retrieval settings were unchanged.

The author checked each reference answer against its evidence and each unanswerable
rationale against the full five-page corpus. Independent human review is still
pending. Review the expected answers and evidence, especially contextual questions,
before freezing this dataset for comparisons.

## Limits

This is a reproducible starter benchmark, not representative research papers.
It has one document, five synthetic English pages, short passages, no layout/OCR
challenges, and no cross-document questions. Document-only retrieval accuracy is
trivial with one document; page and evidence discrimination are meaningful but
limited. More questions do not compensate for the small corpus. Extend to multiple
representative documents before drawing production-quality conclusions.

Step 3 results are recorded separately from the frozen dataset. Do not revise these
annotations in response to retrieval scores without versioning the dataset and
documenting the reason.


## Final comparison status

Step 7 scored the held-out split after explicit approval. See [final results](FINAL_RESULTS.md)
for the frozen four-strategy comparison and agent citation review. Statements
about unscored held-out questions in earlier step reports and the frozen manifest
describe their status at dataset creation; this split is now consumed. Source
annotations and the original manifest have not been rewritten after scoring.
