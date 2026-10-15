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

- CORS (Cross‑Origin Resource Sharing):
  - Used to let a web server explicitly allow browsers to load resources or make requests from a different origin (domain, protocol, or port) than the one serving the page.
  - Browsers enforce the Same-Origin Policy by default and dispatch preflight `OPTIONS` requests for non-simple cross-origin requests.
  - The server answers with `Access-Control-Allow-Origin`, `Access-Control-Allow-Headers`, and `Access-Control-Allow-Methods` to permit the browser to proceed.

- Authentication: Tokens (localStorage) vs Cookies (HttpOnly):
  - Bearer Tokens in `localStorage`: Easy to implement and inspect for SPAs, decoupled across different domains, but vulnerable to Cross-Site Scripting (XSS).
  - `HttpOnly` Cookies: Browser stores and attaches the cookie automatically; inaccessible to JavaScript, providing strong protection against XSS, but requires protection against Cross-Site Request Forgery (CSRF) and strict SameSite configurations.

- Frontend → REST API Data Lifecycle:
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
Chat generation is a later phase: retrieved passages alone are not an answer.

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
