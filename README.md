# Payload Cache Service

A FastAPI service that builds a payload from two lists of strings. Each string
is passed through a "transformer" that stands in for a slow external service,
and the results are interleaved into one output string.

The expensive part is the transformer, so the service caches its results in a
database and never asks for the same string twice.

```
POST /payload   {"list_1": [...], "list_2": [...]}   ->  201 {"id": ..., "message": ..., "created": true}
GET  /payload/{id}                                   ->  200 {"output": "FIRST STRING, OTHER STRING, ..."}
GET  /health                                         ->  200 {"status": "ok"}
```

## Quickstart

With Docker:

```bash
docker compose up --build
```

Locally, with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
make run          # uvicorn on http://localhost:8000
make check        # ruff, mypy and pytest, the same commands CI runs
```

The default database is SQLite at `./data/cache.db`, created on first start.
Point `DATABASE_URL` at `postgresql+asyncpg://...` to use PostgreSQL instead;
no code changes are needed. See `.env.example` for every setting.

## The API

```bash
curl -X POST localhost:8000/payload -H 'content-type: application/json' -d '{
  "list_1": ["first string", "second string", "third string"],
  "list_2": ["other string", "another string", "last string"]
}'
# 201 {"id":"355d6975-...","message":"payload created","created":true}

curl localhost:8000/payload/355d6975-...
# 200 {"output":"FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"}
```

Sending the same input again returns the **same id** with `200` and
`"created": false` — a repeat is not a creation, and nothing is recomputed.

| Status | When |
|---|---|
| 201 | a new payload was generated |
| 200 | an identical payload already existed, its id is reused |
| 404 | no payload with that id |
| 422 | lists of different length, empty lists, or a request over the size limit |
| 502 | the transformer broke its contract (wrong number of results) |
| 504 | the transformer did not answer in time |

## The CLI

```bash
cache-cli [-h] [-H|--host URL] [-r|--repeat N] [-i|--input FILE|-] [-j|--json JSON] [-o|--output FILE|-]
```

Arguments are parsed and validated by Pydantic Settings, so bad input is
rejected before any request is sent. Every flag also reads from the
environment with a `CACHE_CLI_` prefix.

```bash
echo '{"list_1":["first string"],"list_2":["other string"]}' | cache-cli -i - -r 3
```

`--repeat` is the quickest way to see the cache work:

```json
{
  "iterations": [
    {"iteration": 1, "payload_id": "355d6975-...", "created": true,  "post_ms": 178.95},
    {"iteration": 2, "payload_id": "355d6975-...", "created": false, "post_ms": 5.73},
    {"iteration": 3, "payload_id": "355d6975-...", "created": false, "post_ms": 5.65}
  ],
  "summary": {"unique_payload_ids": 1, "payloads_created": 1}
}
```

Exit codes: `0` success, `1` the service could not be reached or answered an
error, `2` bad arguments or unreadable input.

**On `-h`:** the task's spec gives `-h` to both `--host` and `--help`, which
cannot both exist. `-h` is help, as everywhere else, and the short flag for
`--host` is `-H`.

## How the caching works

For one `POST /payload`:

1. **Fingerprint the request.** A sha256 over the canonicalised input. If a
   payload with that fingerprint exists, its id is returned and nothing else
   happens — no database writes, no transformer call.
2. **Deduplicate inside the request.** `dict.fromkeys` over both lists, so a
   string that appears twice, or in both lists, is only handled once.
3. **One query for the cache.** A single `SELECT ... WHERE source_hash IN (...)`
   for the whole batch, never one query per string.
4. **One call for the misses.** The transformer interface takes a list, so
   everything not cached goes out in a single call. Nothing left to do means no
   call at all.
5. **Store and answer.** New cache entries and the payload are committed in one
   transaction.

Measured on the example above: the first request takes ~180 ms, a repeat ~6 ms.

## Project layout

```
app/
  main.py          app factory and lifespan
  schemas.py       the HTTP contract and its limits
  api/             routes and dependency providers
  core/            settings and logging
  db/              SQLModel tables and async session wiring
  domain/          interleaving and hashing; no FastAPI, no SQLAlchemy
  services/        transformer, cache, and the payload use case
cli/               cache-cli: settings, http client, entry point
tests/
  unit/            domain, transformer, CLI parsing — no I/O
  integration/     real SQLite and the real ASGI app
  doubles.py       transformer stand-ins
```

`domain/` is framework-free on purpose: the interleaving and hashing rules are
the parts most likely to change. `cli/` never imports `app/` — it is a client
that only speaks HTTP.

## Design decisions and trade-offs

**Hashes are the cache keys, not the strings.** Input is arbitrary user text,
and a PostgreSQL btree index rejects values over roughly 2.7 KB. A sha256 hex
digest is always 64 characters, so `source_hash` is the primary key.

**The fingerprint is JSON, not a concatenation.** With a separator, `["a,b"]`
and `["a", "b"]` would hash to the same value. It also carries a version
prefix, so changing the output format invalidates old payloads instead of
serving stale ones.

**Payload ids are UUIDs, not the fingerprint.** The id is public, the
fingerprint is internal. This keeps the hashing scheme changeable and does not
leak anything about the input.

**The rendered output is stored.** A read is a single row lookup rather than
re-joining cached parts on every request. The original lists are stored too, so
the output could be re-rendered if the format changes, at the cost of keeping
the text twice.

**Duplicate payloads are prevented by the database.** `fingerprint` is unique.
Two identical concurrent requests both try to insert; one wins, the other
catches the integrity error and returns the winner's id. Correctness comes from
the constraint, not from application logic.

**No single-flight lock.** Concurrent requests for the same *new* string can
each call the transformer. A lock would only help within one process; doing it
properly needs an advisory lock or Redis, which is a bigger change than this
task calls for. Data stays correct either way — this is a cost, not a bug.

**The transformer interface is a batch.** The requirement is to minimise calls,
so the service hands over every miss at once. It is a `Protocol`, so the test
doubles in `tests/doubles.py` are a few lines each and need no mocking library.

**The call timeout is applied in the dependency**, not when the app is built,
so a transformer injected by a test runs under the same policy as the real one.

**`create_all` instead of Alembic.** Two tables, one setup step. A real
deployment would run migrations; this is the documented shortcut.

**Request limits live with the schema.** 1000 items per list, 4096 characters
per item, and 200 000 characters per request in total. The per-item limits
alone would still allow about 8 MB of text in a single call, which the service
would hash, transform and store twice.

## Security and operations

Deliberate choices:

- Every query is parameterised; no SQL is built from strings.
- CORS is not enabled.
- Logs contain counts and ids, never the payload text.
- Payload ids are UUID4, so they cannot be enumerated.
- The `IN` list is bounded by the schema: 2 × 1000 parameters stays well under
  asyncpg's limit of 32767.
- The container runs as a non-root user and writes only to a mounted volume.

Known gaps, deliberately left to the deployment:

- **No authentication and no rate limiting.** Anyone who can reach the service
  can fill the cache table. This belongs in a gateway in front of it.
- **No body size limit at the ASGI layer.** uvicorn has none; the schema limit
  applies only after the JSON has been parsed. A reverse proxy should cap the
  request body.
- **The cache grows without bound.** No TTL and no eviction. A production
  deployment needs a job that deletes old entries.
- **A payload id is a bearer capability.** Anyone holding the UUID can read the
  payload; there is no ownership model.
- **`/docs` is open.** Fine for an internal service, should be protected
  otherwise.
- **Unknown environment variables are ignored**, so a typo such as
  `DATABSE_URL` silently falls back to the default.

## Tests

```bash
make test
```

56 tests. The ones that matter most:

- `test_render_output_matches_the_example_from_the_task` — the literal example
  from the task description.
- `test_repeating_a_request_reuses_the_id_and_calls_nobody` and
  `test_only_strings_that_are_new_reach_the_transformer` — assert on which
  strings reached the transformer, not just that the cache "works".
- `test_get_many_uses_one_query_for_the_whole_batch` — records every SQL
  statement and asserts that 50 strings cost one SELECT, so the cache does not
  trade N upstream calls for N queries.
- `test_concurrent_identical_requests_produce_one_payload` — five racing
  requests, one payload, one id.
- `test_a_missing_sqlite_directory_is_created` — a regression test for a real
  bug: the default `DATABASE_URL` points at `./data`, which a fresh checkout
  does not have, and the service failed to start.

## What I would do next

Alembic migrations; an in-process LRU in front of the database for hot strings;
single-flight so racing requests share one transformer call; authentication and
rate limiting at the edge; a TTL and eviction job for the cache; and metrics for
cache hit ratio and transformer latency.
