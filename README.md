# recql-mongodb

Standalone RecQL backend for MongoDB **8.2+** with native Search / Vector Search
(`$search`, `$vectorSearch` via `mongot`).

Document store — **no SQL dialect**. Conformance uses ``DOCUMENT_BACKEND_FEATURES``.

## Native search

Indexes (created by the pack after demo data is loaded):

| Collection | Index | Stage |
|------------|-------|-------|
| `text_embeddings` | vector (`embedding`, filter `embedding_name`) | `$vectorSearch` |
| `als_item_embeddings` / `als_user_embeddings` | vector | `$vectorSearch` |
| `items` | lucene text on `search_text` / `title` / `description` | `$search` |

Index readiness is verified by polling **probe queries** every second (tiny
`$vectorSearch` / `$search` aggregations), not a fixed sleep.

## Install

```bash
pip install "recql @ git+https://github.com/recql/recql-python-core.git"
pip install "recql-mongodb @ git+https://github.com/recql/recql-python-mongodb.git"
```

## Conformance tests

**Atlas Local (default — one container, good for CI):**

```bash
make test-conformance-docker   # recommended
# or: make up && make test-conformance
```

Uses [`mongodb/mongodb-atlas-local:8.2`](https://hub.docker.com/r/mongodb/mongodb-atlas-local)
(bundles `mongod` + `mongot`).

**Community Server + mongot (self-hosted parity):**

```bash
make test-conformance-docker-community
# or: make up-community && make test-conformance-community
```

Uses [`mongodb/mongodb-community-server:8.2`](https://hub.docker.com/r/mongodb/mongodb-community-server)
plus [`mongodb/mongodb-community-search`](https://hub.docker.com/r/mongodb/mongodb-community-search).
Config lives under `docker/community/`.

Host port defaults to **27018** (`MONGO_PORT`). DSN uses `directConnection=true`
for the single-node replica set. Community auth user: `recql` / `recql`.
