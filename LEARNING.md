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

- CORS (Cross‑Origin Resource Sharing) is used to let a web server explicitly allow browsers to load resources or make requests from a different origin (domain, protocol, or port) than the one serving the page. It works by adding HTTP headers such as Access-Control-Allow-Origin to safely relax the browser’s same‑origin policy.
