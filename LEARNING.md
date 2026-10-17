**Phase 1**

- REST -> representational state transfer is a architectural style for designing networked applications that allows server and client communication

- when we request resources from a server using HTTP methods, the server returns a representation of that resource

- REST follows 6 constraints
  1. Client-Server Architecture
  2. Stateless
  3. Cacheable
  4. Uniform Interface
  5. Layered System
  6. Code on Demand (optional)

- HTTP methods
  1. GET -> used to retrieve data
  2. POST -> used to create data
  3. PUT -> used to update data
  4. DELETE -> used to delete data
  5. PATCH -> used to partially update data

- JSON -> JavaScript Object Notation is a lightweight data-interchange format that is easy for humans to read and write and easy for machines to parse and generate

- Pydantic -> used for data validation and settings management in Python

- Async -> Concurrency multiple things can happen at once
- Sync -> sequential

- PostgreSQL basics:
  1. Database cluster : collection of databases managed by a single postgresql server instance
  2. Database : collection of tables
  3. Table : collection of rows and columns
  4. Row : collection of columns
  5. Column : collection of rows
  6. Schema : how tables are connected
  7. Data types : int uuid string boolean

- ORM : framework that connects object-oriented code to relational database
  1. models (classes)
  2. attributes (properties)
  3. instances (objects)

  and has relationship types

- Stateful : Stores information about client between requests
- Stateless : Doesn't store information about client between requests

- Why FastAPI?
  - High performance built on Starlette and Pydantic with ASGI
  - Native async and concurrency support for fast I/O and LLM operations
  - Automatic request validation and response serialization using Pydantic
  - Auto-generated interactive API docs with Swagger UI and ReDoc
  - Dependency injection system for modular auth and database session handling

- Why PostgreSQL instead of MongoDB?
  - Strict relational integrity with ACID compliance and foreign key constraints
  - Supports vector search natively using pgvector extension for embeddings
  - JSONB support provides document-style flexibility for semi-structured data
  - Faster and simpler joins across relational models like users, workspaces, and documents
  - Prevents schema drift and enforces consistent data types

- Why migrations?
  - Version control for database schema changes over time
  - Keeps local, test, staging, and production databases consistent
  - Allows team members to easily synchronize database updates
  - Safe schema updates without dropping tables or losing data
  - Supports rollbacks if a database update causes issues

**PHASE 2**

- Client/Server Architecture:
  - Clear separation of concerns: The client (Next.js) handles UI presentation, user interactions, and local state. The server (FastAPI) handles business logic, database persistence, and authorization.
  - Decoupled development: Either client or server can be refactored, scaled, or replaced independently as long as the REST API contract is preserved.

- CORS (Crossâ€‘Origin Resource Sharing):
  - Used to let a web server explicitly allow browsers to load resources or make requests from a different origin (domain, protocol, or port) than the one serving the page.
  - Browsers enforce the Same-Origin Policy by default and dispatch preflight `OPTIONS` requests for non-simple cross-origin requests.
  - The server answers with `Access-Control-Allow-Origin`, `Access-Control-Allow-Headers`, and `Access-Control-Allow-Methods` to permit the browser to proceed.

- Authentication: Tokens (localStorage) vs Cookies (HttpOnly):
  - Bearer Tokens in `localStorage`: Easy to implement and inspect for SPAs, decoupled across different domains, but vulnerable to Cross-Site Scripting (XSS).
  - `HttpOnly` Cookies: Browser stores and attaches the cookie automatically; inaccessible to JavaScript, providing strong protection against XSS, but requires protection against Cross-Site Request Forgery (CSRF) and strict SameSite configurations.

- Frontend â†’ REST API Data Lifecycle:
  - Client dispatches HTTP request (method, headers with `Authorization: Bearer <token>`, JSON body).
  - Server routes request, authenticates credentials, executes database queries, and returns HTTP status code (200 OK, 201 Created, 204 No Content, 401 Unauthorized, 422 Unprocessable Entity).
  - Client deserializes response JSON, updates React state, or intercepts errors (e.g. 401 triggers token cleanup and redirection to `/login`).

- Loading & Error States:
  - Loading states (skeletons, spinners, disabled buttons) provide immediate visual feedback, preventing duplicate submissions and layout shift.
  - Error states (inline banners, field validation messages, network fallbacks) handle operational failures gracefully without crashing the app.

- Production Environment Variables:
  - Client-side variables in Next.js MUST start with `NEXT_PUBLIC_` (e.g. `NEXT_PUBLIC_API_URL`) so they are bundled into the browser bundle at build time.
  - Server-side secrets (like database credentials, `SECRET_KEY`, JWT keys) omit the prefix and only exist in server memory, keeping sensitive keys secure from the public web.

## Phase 3: document ingestion and semantic retrieval

### Follow one PDF through the system

1. The API authenticates the user and checks workspace ownership.
2. It saves a bounded PDF under a server-generated UUID path and creates a
   `documents` row with status `processing`.
3. pypdf extracts text one page at a time. Cleaning normalizes Unicode and
   whitespace and removes NUL characters. Empty pages are skipped, preserving the
   original page numbers of readable pages.
4. Fixed-size character windows split each page, with overlap between neighbors.
5. A local CPU embedding model converts each chunk into 384 floating-point values.
6. All chunks and the document's `ready` status commit in one database transaction.
   Failure rolls back the chunk writes and records `failed` plus a safe error.
7. A query is embedded by the same model. PostgreSQL ranks eligible chunks using
   cosine distance and returns the closest top-k passages with their source pages.

The relevant code is `backend/app/services/text.py`, `embeddings.py`, `ingestion.py`,
and `backend/app/api/documents.py`. The model is lazy-loaded once per server process.
The first request can include a model download. Later requests reuse it.

### What an embedding actually is

An embedding is the output of a learned function `f(text) -> vector`:

```text
"A puppy is learning a command."
              |
      model's tokenizer
              |
       token ID sequence
              |
  neural-network inference on CPU
              |
 [0.24, -0.81, 0.17, ..., 0.42]  <-- illustrative values, not measured output
```

The tokenizer converts text into IDs. Model layers apply learned numerical
operations to those IDs' representations, and a pooling step produces a fixed-size
sentence/passage representation. Padding helps run batches of different lengths.
The 384 coordinates jointly encode information; individual coordinates are not
reliable human labels such as "animal" or "finance".

Training and inference are different. During training, an objective adjusts model
weights so useful semantic relationships emerge. During our ingestion, the weights
are fixed: we compute outputs but do not train the model on uploaded documents.
Storing a document therefore does not teach the model new facts; it gives retrieval
new passages to select from.

"The GPU executes the model" is only true when GPU hardware and a GPU execution
provider are selected. A GPU can accelerate large parallel matrix operations, but
the same model can run on a CPU. This repository explicitly uses ONNX Runtime's
`CPUExecutionProvider`, with FastEmbed and two inference threads by default. It
needs no GPU and no external embedding API key. Downloading model weights is a
network operation; subsequent inference runs locally.

Our model is `BAAI/bge-small-en-v1.5`, an English model with 384 output dimensions
and a 512-input-token limit. A chunk of 1024 characters is not necessarily 1024
tokens. Character/token ratios depend on language, punctuation, and text content.
The pipeline counts tokens without truncation and rejects over-limit chunks instead
of silently losing their ending. Changing models requires re-embedding documents;
vectors from unrelated models are not interchangeable, even with equal dimensions.

### Why "dog" and "puppy" can be close

Lexical matching compares words or character sequences. Learned embeddings instead
reflect patterns acquired during model training: related words and passages occur
in related contexts and can satisfy related training pairs. A puppy is a young dog,
so their representations can be nearby without sharing any letters in common.
This is a tendency, not a logical guarantee. Context matters: "hot dog" may refer
to food, and a model can mishandle negation, ambiguity, or specialized vocabulary.

Our actual CPU run measured:

- cosine(`dog`, `puppy`) approximately **0.867**
- cosine(`dog`, `screwdriver`) approximately **0.595**

The second score is still positive. Embedding spaces have their own score
distributions. Similarity is not a probability that two texts mean the same thing.

### Cosine similarity, step by step

For vectors `a` and `b`:

```text
dot(a, b) = sum(a[i] * b[i])
norm(a) = sqrt(sum(a[i] * a[i]))
cosine_similarity(a, b) = dot(a, b) / (norm(a) * norm(b))
cosine_distance(a, b) = 1 - cosine_similarity(a, b)
```

Consider illustrative two-dimensional vectors `a = [1, 0]` and `b = [0.8, 0.6]`.
Both have length 1, their dot product is 0.8, and their cosine similarity is 0.8.
Multiplying `b` by 10 leaves cosine unchanged: cosine measures direction, not
magnitude. Identical directions score 1; perpendicular vectors score 0; opposite
directions score -1. Zero vectors have undefined cosine and are rejected here.

For normalized vectors, the dot product equals cosine. pgvector's `<=>` operator
returns cosine **distance**, so ascending order gives the nearest neighbors. The
API reports `1 - distance` as similarity. It is easy to accidentally reverse a sort
or present a distance as a similarity; the real PostgreSQL test checks this path.

### Chunk size and overlap

A document is usually longer than a model input window. Embedding the entire file
would either fail, truncate it, or compress many unrelated topics into one vector.
Chunks provide smaller retrieval units and source locations.

Our fixed windows use Unicode character counts and stay within each page. For
size 512 and overlap 64, starts are 0, 448, 896, ... on that page. A final short
chunk keeps the remaining text. The chunk index is global within the document,
while `start_char`/`end_char` refer to cleaned text on its page, not original PDF
byte offsets. No overlap crosses a page boundary in this first implementation.

Small chunks are more focused and produce less context per hit, but they can split
sentences or separate a question from its explanation. Large chunks preserve more
context but may dilute a passage's main topic and return irrelevant material.
Overlap repeats boundary text, which can preserve a complete explanation in at
least one chunk. It also adds embedding work, storage, and near-duplicate results.

Fixed-size chunking may split words or sentences. That is deliberate for this first
baseline. Later compare sentence-aware or token-aware chunking using the same
evaluation queries instead of assuming a more complex splitter must be better.

### Metadata and schema

`documents` stores `id`, `workspace_id`, `filename`, `storage_path`, `status`,
`error`, and `created_at`. Legacy documents may have no storage path.

`chunks` stores `id`, `document_id`, `content`, `page`, `chunk_index`,
`embedding vector(384)`, and JSON `metadata`. The ORM calls the JSON attribute
`chunk_metadata` because SQLAlchemy already reserves `metadata` on model classes.

Metadata records the model name/dimensions, chunk unit/size/overlap, cleaned offsets,
parser, and cleaning version. This makes a result traceable and an experiment
reproducible. Page and document identifiers support citations; a bare vector does
not explain where an answer came from. Authorization comes from workspace ownership
and SQL filters, not from trusting caller-provided metadata.

### Semantic retrieval and top-k

The retrieval flow is query -> same embedding model -> cosine distance -> sort ->
take k. This finds passages that are semantically related even without exact word
overlap. It can also miss exact identifiers or invent relevance where little exists;
later compare lexical or hybrid retrieval on queries involving names, codes, and dates.

Top-k means "return up to this many nearest passages." It does not mean "return
this many correct passages." Increasing k can recover evidence ranked below the
first result, but adds noise and more text for a future language model to consume.
If none of the documents answer the question, the system can still return nearest
neighbors. A calibrated threshold or a later answerability check requires evaluation.

The API filters by owned workspace and `ready` status before limiting results.
Inspect filename, page, source content, and score in the workspace search panel.
Phase 4 adds chat generation on top of this retrieval step; passages alone are not an answer.

### Vector indexing: start exact, measure first

pgvector provides a vector data type, distance operators, and optional indexes.
We currently use **exact search**: evaluate distance for eligible vectors and sort.
The B-tree index on `document_id` and the unique `(document_id, chunk_index)`
constraint are ordinary relational structures, not vector-neighbor indexes.

HNSW builds a graph of nearby vectors and can make large searches faster while
trading recall for speed and consuming extra memory. IVFFlat partitions vectors
and searches selected partitions; its training/data distribution and probe settings
matter. Neither repairs poor chunking or a mismatched embedding model. Preserve
exact search as a ground-truth baseline, then measure approximate recall and latency
before adding an index. See the primary pgvector documentation:
https://github.com/pgvector/pgvector.

### What the 256 / 512 / 1024 experiment taught us

The repository contains a small authored corpus of 5 pages and 8 evidence-annotated
queries. With overlap fixed at 64 characters, the measured results were:

| Size (characters) | Chunks | Hit@1 | Hit@3 | Mean reciprocal rank |
|---|---|---|---|---|
| 256 | 37 | 50.0% | 100% | 0.729 |
| 512 | 17 | 62.5% | 100% | 0.812 |
| 1024 | 10 | 75.0% | 100% | 0.875 |

Hit@3 measures whether a complete annotated evidence string is present in the first
three returned chunks. Reciprocal rank is 1/rank of the first complete evidence
chunk, averaged across questions, with zero for missing evidence. This criterion
favors larger windows, and should be supplemented with human relevance judgments.

All sizes found evidence within three results, so choosing based only on hit@3
would hide meaningful ranking differences. The 1024 setting produced fewer vectors
and better first-result ranking here; it is our provisional default. It is not a
universal optimum. Fixed overlap means overlap ratios vary, and larger hits carry
more unrelated text. The full recorded passages allow you to inspect that tradeoff.

Run `uv run --locked python scripts/chunk_experiment.py` from `backend`. Read
`backend/experiments/RESULTS.md` and `results.json`. Repeat with your own PDFs and
independent queries, varying overlap and top-k. Record retrieval quality, returned
context length, duplicate hits, CPU time, storage, and failure cases. Keep final
evaluation queries separate from the questions used to choose settings.

Primary references: FastEmbed supported models
(https://qdrant.github.io/fastembed/examples/Supported_Models/), pgvector SQLAlchemy
integration (https://github.com/pgvector/pgvector-python), and pypdf extraction
(https://pypdf.readthedocs.io/en/stable/user/extract-text.html).


## Phase 4: retrieval versus generation

Retrieval selects evidence; generation turns that evidence into an answer. Our
`POST /workspaces/{id}/chat` first embeds the question and searches the authenticated
workspace's ready documents. It then sends up to `RAG_TOP_K` passages (default 5)
to the configured LLM. The source list is resolved by the server, never accepted
as a model-authored filename or page number.

The generation contract is a list of claims, each with an exact supporting quote
and retrieved source ID. Validation rejects unknown sources, missing evidence,
quotes absent from the context, invalid JSON, and truncated model responses.
Every accepted claim receives a numbered citation. The UI displays the cited
filename, page, and quote alongside the answer. Exact substring validation proves
the quote exists, but cannot prove that it logically supports the model's claim.
That distinction is the reason citation accuracy still needs an evaluation dataset.

If the question asks about limitations but the retrieved chunks describe only the
introduction, investigate retrieval first. If the chunks explicitly describe a
small sample but the answer claims a large sample, generation failed despite good
retrieval. Inspect `retrieved_chunks` in the response or expand the Chat tab's
retrieved passages. For a provider failure, the same `/search` question and top-k
let you examine retrieval independently. Stage-specific errors and timing logs
help distinguish infrastructure failures too.

No passages means no LLM call. Insufficient evidence produces a fixed abstention
and no citations. Nearest-neighbor results are not necessarily relevant, so there
is no arbitrary similarity threshold. Each question is independent: chat history
is neither persisted nor passed to the model in this first RAG implementation.

The next phase compares dense, lexical, hybrid, and reranked retrieval on the same
annotated questions. It should begin only after the real PostgreSQL-plus-LLM path
is verified and the Phase 4 review is approved.

## Phase 5, step 3: measuring retrieval and generation separately

The development evaluator uses 33 questions: 30 with annotated evidence and three
that cannot be answered from the corpus. Evidence Recall@5 is the fraction of
required evidence strings found in the top five chunks, averaged per answerable
question. MRR measures how early the first evidence-bearing chunk appears in the
full ranking. Unanswerable questions have no relevant evidence target and are
excluded from both metrics; their abstention behavior is measured separately.

The vector baseline reached Recall@5 0.9833 and MRR 0.9000. One HNSW explanation
crosses a chunk boundary, preventing a complete string match anywhere in the
corpus. Even perfect ranking cannot fix that under the current metric. Page-hit
accuracy was 100%, illustrating why page identity alone is insufficient.

The same run produced six generation validation errors. Of three unanswerable
questions, only one abstained; another failed validation and a third produced an
unsupported claim. Exact quote matching proves provenance but does not guarantee
the claim follows from the quote. An explicit agent review judged 45 of 50 emitted
claim-citation pairs supported. Independent human review remains pending, and
citation precision excludes errors and abstentions, so it must be read alongside
generation status counts. Supported but irrelevant claims and incomplete answers
also require separate quality review.

See `backend/experiments/evaluation/RUNNER.md` for definitions and commands, and
`RESULTS.md` in the same directory for the raw artifacts and limitations. Default
runs use development only; held-out scoring requires an explicit opt-in. Freeze
the metric definitions before comparing BM25, hybrid retrieval, and reranking.

## Phase 5, step 4: BM25 lexical retrieval

Dense retrieval compares learned representations of meaning. BM25 instead scores
overlapping tokens: rare terms contribute more, repeated terms saturate, and chunk
length adjusts the score. Our fixed baseline uses k1=1.2 and b=0.75, with Unicode
normalization, case-folding, and alphanumeric tokens. It does not stem words or
expand synonyms: `dog` and `puppy` do not match without another shared token.

BM25 searches the same stored chunks as dense retrieval. Ownership and ready status
filter the corpus before computing term frequencies and average chunk length;
filtering only after scoring would let other workspaces influence the statistics.
Scores are positive lexical relevance values, not cosine similarity or confidence.
No overlap returns no hits rather than filling the result list with zero-score text.

The development comparison kept corpus, questions, chunks, and metrics fixed.
Both methods achieved evidence Recall@5 of 0.9833, while BM25 MRR was 0.9833 versus
vector MRR of 0.9000. Five questions moved their first evidence hit from rank 2 to
rank 1. The corpus is small and synthetic, so this does not establish that keyword
search is universally superior. Shared exact terms can help BM25, while paraphrases
without token overlap remain a weakness.

The API currently rebuilds a workspace-local BM25 index per request and caps it at
20,000 ready chunks. This keeps the baseline simple and current after mutations,
but an indexed lexical backend is needed for larger collections. Benchmark query
timings exclude this build cost and are not API latency measurements.

See `backend/experiments/evaluation/BM25_RESULTS.md` for the formula, API contract,
tests, and recorded comparison. Step 5 will combine the two ranked lists after
review; it should not add raw BM25 and cosine scores because their scales differ.

## Phase 5, step 5: reciprocal rank fusion

Hybrid retrieval asks both dense and BM25 retrieval for candidates, then merges
their rankings. Our RRF score sums `1 / (60 + rank)` for each branch containing a
chunk. A chunk ranked first in both receives `2/61`; one ranked first in only one
branch receives `1/61`. Raw cosine and BM25 scores remain diagnostics rather than
inputs to the sum. Duplicate chunk IDs merge, but distinct chunks with the same
text keep their separate provenance.

Candidate retrieval and final context limits are separate: by default, each
branch supplies up to 20 candidates, fusion ranks their union, and five chunks
are returned. The per-branch limit can lose evidence before fusion on a larger
corpus. Neither fusion nor a later reranker can recover chunks never retrieved.

On the current development set, hybrid MRR was 0.9500 versus vector 0.9000 and BM25
0.9833; all had evidence Recall@5 0.9833. Combining methods did not beat the stronger
individual method on this small synthetic corpus. Preserve these results instead
of adjusting parameters until hybrid appears best. Held-out evaluation remains
reserved for the final frozen comparison.

See `backend/experiments/evaluation/HYBRID_RESULTS.md` for configuration, source
rank fields, failures, and the recorded candidate lists. Chat can opt into hybrid
through `RAG_RETRIEVAL_METHOD`, while the default remains vector until the broader
comparison is reviewed.


## Phase 5, step 6: cross-encoder reranking

Dense retrieval encodes query and passage separately. A cross-encoder reads the
query/passage pair together and scores its relevance. This is more expensive,
so apply it only after hybrid retrieval has produced a shortlist: up to 20 fused
candidates, then the best five for generation. It cannot recover missing evidence
outside that shortlist or repair a claim made incorrectly by the LLM.

The local MiniLM cross-encoder returns raw relevance scores, including negative
values. They are not confidence probabilities. Keep cosine, BM25, RRF and reranker
scores separate; use the reranker score for final order and stable chunk UUIDs
for ties. Preserve original text, document IDs and page numbers for citations.
Oversized query/passage pairs, model failures and invalid scores explicitly fall
back to hybrid order. Empty candidates skip inference.

On the fixed development split, reranking improved hybrid MRR from 0.9500 to
0.9833 but left evidence Recall@5 at 0.9833. Three questions moved first evidence
from rank two to one; one regressed from one to two. CPU reranking added a median
657 ms for ten corpus chunks. This illustrates a quality/latency tradeoff, not a
universal improvement: BM25 already matched the resulting MRR on this dataset.
See [the results and reproduction steps](backend/experiments/evaluation/RERANK_RESULTS.md).
The held-out split and final four-strategy generation/citation comparison remain
reserved for step 7 after approval.


## Phase 5, step 7: why the final comparison matters

The final fixed held-out comparison reverses the development-set preference:
vector, hybrid and reranked hybrid reach MRR 1.00, while BM25 reaches 0.90. All
four have evidence Recall@5 0.95. A method that wins on development examples need
not win on unseen questions, especially with only one small synthetic document.

Reranking adds latency (753 ms median retrieval versus vector's 16 ms) without
improving held-out retrieval. Keep vector as the default for now; retain the
other modes for experiments. Do not generalize this result to larger collections.

Distinguish three failure types. A sentence split across chunks limits complete
quoted evidence under this metric. A model can then produce invalid evidence
format or an absent quote even with the right chunk retrieved. Finally, it can
produce a valid exact quote that does not support the claim, or supported claims
that do not answer the question. Retrieval scores, provenance validation and
semantic answer quality measure different things.

Across 48 generation attempts, 19 failed validation, 27 returned answers and two
abstained. Agent citation review found 58/63 supported claim?citation pairs;
this does not imply 58/63 correct answers. Claims differ in number per answer,
and errors have no accepted claims. Review notes record unsupported, irrelevant,
incomplete and repetitive output separately. Independent human review remains
pending. See [the final report](backend/experiments/evaluation/FINAL_RESULTS.md)
for per-strategy results, raw artifacts and reproduction steps.

The original held-out split has now been used. Preserve its annotations and
results, and collect new questions and representative documents before tuning.


## Phase 6, step 2: a queue is not a worker

Redis stores queued work; an RQ worker is a separate Python process that executes
it. Enqueueing a function does not run its code in the producer. The smoke test
checks different process identities and a shared file hash, demonstrating both
execution separation and storage access across containers. Queue arguments are
small JSON values, not open files or request-bound database sessions.

A Redis ping proves broker availability; a recent worker heartbeat proves that
a consumer has checked in. Neither proves a PDF will index successfully. Redis
persistence improves restart behavior, but durable dispatch, idempotency and
retry/recovery policies belong to the next steps.


## Phase 6, step 3: accept work durably before dispatch

The upload endpoint writes a PDF and, in the same database transaction, the
queued document plus an outbox dispatch record. It can return before Redis is
available. A dispatcher publishes the record to RQ and retries on broker errors.
PostgreSQL status lets the system recover intent even if Redis loses a message.

There is no atomic transaction spanning PostgreSQL and Redis. A crash after
publishing but before marking the outbox can publish the same work twice. Design
for at-least-once delivery: the worker atomically claims a queued row, checks the
dispatch ID, and uses a lease token before publishing. Duplicate or stale jobs
become no-ops. The full chunk set and `ready` status commit together so retrieval
cannot see a partial index.

The database stores the chunk settings and embedding model used at acceptance,
so a delayed worker does not silently process a PDF with changed defaults. Old
in-progress rows lack these inputs; the migration marks them interrupted instead
of guessing. New jobs allow three processing attempts by default; abandoned-lease
recovery is an upcoming step. See the [step 3 review](docs/PHASE6_STEP3_REVIEW.md)
for the migration, tests, operations and review boundary.


## Phase 6, step 4: show job state without confusing it with network state

The panel polls while at least one document is queued or processing, then stops
at a terminal state. Polling errors get their own notice and back off; they do
not change the document to failed. Hidden tabs pause network requests and refresh
immediately when visible. Workspace changes cancel the prior polling loop and
ignore any late response.

Stages are useful indicators, not guaranteed percentage progress: a worker may
move through a stage between polls. ?Uploading? covers the HTTP transfer and
request; this UI does not report byte-level percentage. Search becomes available
once the server reports an indexed document, consistent with ready-only retrieval.
See the [step 4 review](docs/PHASE6_STEP4_REVIEW.md).

## Phase 6, step 5: retry failed attempts without duplicating work

The worker retries classified transient database and embedding transport failures,
with three attempts and waits of 30 then 120 seconds by default. PostgreSQL stores
the attempt count and next retry time. The dispatcher only releases a retry after
that time; duplicate RQ deliveries cannot claim a retrying document or consume an
extra attempt. Invalid PDFs, limits, and unknown errors fail immediately.

The failure transition and dispatch reschedule commit together. The final chunk
set and ready status also commit together, so a failed publish leaves no partial
index. A killed worker may leave an active lease behind; lease recovery belongs
to step 6. See the [step 5 review](docs/PHASE6_STEP5_REVIEW.md).

## Phase 6, step 6: recover work after a worker disappears

An RQ worker can die without running the exception handler. The dispatcher scans
expired PostgreSQL leases every 30 seconds and transitions abandoned attempts to
`retrying` or `failed` according to the existing attempt budget. A stale worker
cannot renew its old token or publish chunks after recovery. The outbox remains
the source for republishing queued jobs lost from Redis; multiple workers may see
duplicate messages, but only one can claim the document.

An upload may leave a file behind if the process dies between writing the PDF
and committing its database row. The separate cleanup command lists only old,
server-named PDFs without a matching row and requires `--apply` to remove them.
The [step 6 review](docs/PHASE6_STEP6_REVIEW.md) records the disposable database,
Redis, kill, concurrency, deletion, and lost-message probes.

## Phase 6, step 7: measure acceptance and indexing separately

The final disposable probe submitted a real PDF through the API while the Redis
dispatcher and RQ worker were running. Acceptance returned 202 in 0.021 seconds;
the document reached `ready` in 2.072 seconds on that run. Real FastEmbed vectors
were stored as 384-dimensional pgvector values, then retrieved through vector
search. A local deterministic OpenAI-compatible provider exercised `/chat` and
the server's document, page, exact-quote, and citation checks. Fabricated
provider evidence produced HTTP 502, and a malformed PDF failed once without
partial chunks. These timings are one local sample, not a latency benchmark.

The [step 7 review](docs/PHASE6_STEP7_REVIEW.md) includes commands, validation,
and the boundary between tested citation mechanics and untested LLM quality.

## Phase 7: orchestrate research as durable stages

A research job uses one deterministic state machine. Planning and drafting are
bounded structured LLM calls; retrieval, stage transitions, retries, and citation
checks are application code. Each completed stage saves its output, so a worker
that dies during synthesis resumes from synthesis rather than repeating planning
and retrieval. PostgreSQL stores the authoritative job state and dispatch intent;
Redis/RQ only delivers work. A separate research worker prevents reports from
blocking document ingestion.

The report's references point to server-owned document, page, chunk, and exact
quote metadata. That verifies provenance and quote presence, not whether the
quote truly supports the claim. Gaps remain visible where a planned question has
no supported claim. See the [research job design and probe](docs/PHASE7_RESEARCH_JOBS.md).

## Phase 8: checkpointing and failure recovery

Stage checkpoints now have explicit database records. A completed step and its
next-stage transition commit together. VERIFY saves a checked report; SAVE
publishes that report atomically and can retry without repeating the earlier
work. Worker leases fence stale attempts, and the dispatcher resumes the last
unfinished stage after a crash. Retry delays grow from 30 to 120 seconds, while
malformed model JSON gets only one replay.

Fault-injection tests distinguish a failed stage from a failed job and show the
limit of durable execution: an external call may run twice if the worker crashes
before committing its output. See [the failure matrix and guarantees](docs/PHASE8_CHECKPOINTING.md).

## Phase 9: a model gateway

The application now specifies a task and a generation request instead of an HTTP
provider contract. Separate adapters translate that request for OpenAI-compatible
or Gemini endpoints. Configuration routes chat, planning, and drafting
independently; embeddings stay pinned to the existing local vector model.
Normalized usage and errors make provider behavior observable, while bounded
retry and explicit fallback handle temporary failures. Internal streaming stops
on incomplete output and never switches providers after emitting a chunk. See
[the gateway design](docs/PHASE9_MODEL_GATEWAY.md).
