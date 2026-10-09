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

Compose and CI run SQLite only, so the PostgreSQL path is covered by compiling
its upsert in a unit test rather than by running against a server. Standing one
up in CI would be the next step if the service were deployed on PostgreSQL.

## The API

```bash
curl -X POST localhost:8000/payload -H 'content-type: application/json' -d '{
  "list_1": ["first string", "second string", "third string"],
  "list_2": ["other string", "another string", "last string"]
}'
# 201 {"id":"355d6975-...","message":"payload created","created":true}
# Location: /payload/355d6975-...

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
| 413 | the request body is larger than the ceiling, refused before parsing |
| 422 | lists of different length, empty lists, unknown fields, or a request over the size limit |
| 502 | the transformer broke its contract (wrong count, or a value that is not a string) |
| 503 | the database is busy — SQLite has one writer, so a write burst is a retry |
| 504 | the transformer did not answer in time |

Every one of these is declared in the OpenAPI schema, so `/docs` shows the
whole contract rather than just the happy path.

## The CLI

```bash
cache-cli [-h] [-H|--host URL] [-r|--repeat N] [-i|--input FILE|-] [-j|--json JSON] [-o|--output FILE|-]
```

Arguments are parsed and validated by Pydantic Settings, so bad input is
rejected before any request is sent. Exactly one of `--input` and `--json` is
required.

```bash
echo '{"list_1":["first string"],"list_2":["other string"]}' | cache-cli -i - -r 3
```

`--repeat` is the quickest way to see the cache work:

```json
{
  "iterations": [
    {"iteration": 1, "payload_id": "73d3f62c-...", "created": true,  "post_ms": 181.75},
    {"iteration": 2, "payload_id": "73d3f62c-...", "created": false, "post_ms": 7.68},
    {"iteration": 3, "payload_id": "73d3f62c-...", "created": false, "post_ms": 5.31}
  ],
  "summary": {
    "unique_payload_ids": 1,
    "payloads_created": 1,
    "fastest_post_ms": 5.31,
    "slowest_post_ms": 181.75
  }
}
```

One id across all three iterations is the point. The first number is not all
cache saving: it also carries one-off client and connection warm-up. The
cache's own contribution is measured below.

If an iteration fails, the report keeps the iterations that already succeeded
and carries an `error` field, and the tool exits non-zero. A report that cannot
be written to `--output` is printed instead, so a finished run is never lost.

Exit codes: `0` success, `1` the service could not be reached or answered an
error, `2` bad arguments or unreadable input.

Two notes on the specification:

- **`-h`** is given to `--help`, as everywhere else, and the short flag for
  `--host` is `-H`. The task's spec assigns `-h` to both; honouring it for
  `--host` would mean taking `-h` away from `--help`.
- **No environment variables.** The short flags are declared as aliases, and
  Pydantic Settings matches aliases in the environment too, so a stray
  one-letter variable such as `H` would silently override `--host`. The CLI
  therefore reads the command line only.

## How the caching works

For one `POST /payload`:

1. **Fingerprint the request.** A sha256 over the canonicalised input. If a
   payload with that fingerprint exists, its id is returned and nothing else
   happens — no database writes, no transformer call.
2. **Deduplicate inside the request.** `dict.fromkeys` over both lists, so a
   string that appears twice, or in both lists, is only handled once.
3. **One query for the cache.** A single `SELECT ... WHERE source_hash IN (...)`
   for the whole batch, never one query per string.
4. **Release the connection.** The pooled connection goes back before the
   remote call, so slow upstream work does not occupy the pool.
5. **One call for the misses.** The transformer interface takes a list, so
   everything not cached goes out in a single call. Nothing left to do means no
   call at all.
6. **Store and answer.** New cache entries and the payload are committed in one
   transaction.

Measured with a warm client and the default 50 ms transformer latency: a first
request takes ~73 ms, of which 50 ms is the transformer, and a repeat takes
~6 ms. A repeat costs exactly one SELECT, no writes and no transformer call,
which `test_a_repeat_costs_one_query_and_no_writes` asserts over HTTP.

## Project layout

```
app/
  main.py          app factory, lifespan and error handlers
  schemas.py       the HTTP contract and its limits
  api/             routes and dependency providers
  core/            settings and logging
  db/              SQLModel tables and async session wiring
  domain/          interleaving and hashing; no FastAPI, no SQLAlchemy
  services/        transformer, cache, errors, and the payload use case
cli/               cache-cli: settings, http client, entry point
tests/
  unit/            domain, transformer, CLI parsing and SQL building
  integration/     real SQLite and the real ASGI app
  conftest.py      throwaway database, fake transformer, in-process client
  doubles.py       transformer stand-ins
```

`domain/` is framework-free on purpose: the interleaving and hashing rules are
the parts most likely to change. `cli/` never imports `app/` — it is a client
that only speaks HTTP. Both boundaries are checked, not just intended.

`mypy --strict` covers `tests/` as well as the application, so a test double
that stops matching the `Transformer` protocol fails the type check rather than
drifting silently.

## Design decisions and trade-offs

**Hashes are the cache keys, not the strings.** Input is arbitrary user text,
and a PostgreSQL btree index rejects values over roughly 2.7 KB. A sha256 hex
digest is always 64 characters, so `source_hash` is the primary key.

**The fingerprint is JSON, not a concatenation.** With a separator, `["a,b"]`
and `["a", "b"]` would hash to the same value. A version prefix is part of both
keys, so bumping it supersedes old payloads *and* old cached transforms.

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

**The database connection is released before the remote call.** Holding a
session across the transformer call caps concurrent transformer calls at the
pool size — measured at 15 with the default pool — and makes the health probe
compete for the pool exactly when the service is busy. Under a heavy burst of
*new* strings the write that follows can still contend on SQLite's single
writer; PostgreSQL does not have that limit.

**No single-flight lock.** Concurrent requests for the same *new* string can
each call the transformer. A lock would only help within one process; doing it
properly needs an advisory lock or Redis, which is a bigger change than this
task calls for. Data stays correct either way — this is a cost, not a bug.

**The transformer interface is a batch.** The requirement is to minimise calls,
so the service hands over every miss at once. It is a `Protocol`, so the test
doubles in `tests/doubles.py` are a few lines each and need no mocking library.

**The call timeout is applied in the dependency**, not when the app is built,
so a transformer injected by a test runs under the same policy as the real one.

**A broken upstream is a gateway error.** A wrong result count, a value that is
not a string, or no answer at all becomes 502 or 504 rather than a 500 that
blames this service.

**`create_all` instead of Alembic.** Two tables, one setup step. A real
deployment would run migrations; this is the documented shortcut. It also means
startup is only safe for a single process: several workers calling `create_all`
against the same SQLite file at once can collide, which is one more reason
migrations belong in a release step rather than in the application.

**The service does not take the request model.** `PayloadService.create` takes
the two lists, not `PayloadCreate`, so the use case does not depend on the HTTP
layer's contract and can be driven from a worker or a script.

**Empty lists are rejected.** The task only requires the two lists to be the
same length, so two empty lists would technically be valid input for an empty
payload. Storing one is not useful, so the schema requires at least one item.

**Request limits live with the schema.** 1000 items per list, 4096 characters
per item, and 200 000 bytes per request in total. The limit counts bytes rather
than code points, because the same character count in non-ASCII text is up to
four times the storage. The per-item limits alone would still allow about 8 MB
of text in a single call, which the service would hash, transform and store
twice.

## Security and operations

Deliberate choices:

- Every query is parameterised; no SQL is built from strings.
- `hide_parameters` is set on the engine, so a failing statement is not logged
  with the user's payload text bound to it.
- A rejected request is never echoed back. FastAPI's default validation
  response includes the input, which at the size limit meant returning
  hundreds of kilobytes to the caller and writing them to the access log.
- Error responses carry fixed messages; internal exception text is logged, not
  returned.
- Unknown fields are rejected, so a typo is an error the caller sees.
- CORS is not enabled.
- Application logs contain counts and ids, never the payload text.
- Payload ids are UUID4, so they cannot be enumerated.
- The `IN` list is bounded by the schema: 2 × 1000 parameters stays well under
  asyncpg's limit of 32767.
- The container runs as a non-root user, cannot write to its own code, and
  writes only to a mounted volume.
- `/health` touches the database under a 5 second timeout, so a probe neither
  lies about a dead database nor hangs instead of failing.
- The request body is capped at 512 KB and refused on `Content-Length` before
  anything is parsed. Without it a 57 MB body took the process from 65 MB to
  243 MB of resident memory before the schema rejected it.
- A busy database answers 503 with `Retry-After` rather than 500: SQLite allows
  one writer, so a burst of writes is a retry, not a server fault. Measured
  with 200 concurrent requests of 400 new strings each: 176 succeeded, 24 got
  503, no unhandled exceptions, and `/health` stayed 200 throughout.
- Application and uvicorn logs share one format, so the stream can be parsed.

Known gaps, deliberately left to the deployment:

- **No authentication and no rate limiting.** Anyone who can reach the service
  can fill the cache table. This belongs in a gateway in front of it.
- **A chunked request carries no `Content-Length`**, so the body ceiling cannot
  be applied to it before reading. A reverse proxy or an ASGI server limit is
  still the complete answer; the in-process check covers the ordinary case.
- **The cache grows without bound.** No TTL and no eviction. A production
  deployment needs a job that deletes old entries.
- **A payload id is a bearer capability.** Anyone holding the UUID can read the
  payload; there is no ownership model.
- **Deduplication is global.** Reusing an id for an identical input is what the
  task asks for, but it does mean a caller who guesses an exact input learns
  that someone already submitted it, and receives that payload's id.
- **`/docs` is open.** Fine for an internal service, should be protected
  otherwise.
- **Unknown environment variables are ignored**, so a typo such as
  `DATABSE_URL` silently falls back to the default.

## Tests

```bash
make test
```

76 tests. The ones that matter most:

- `test_render_output_matches_the_example_from_the_task` — the literal example
  from the task description.
- `test_repeating_a_request_reuses_the_id_and_calls_nobody` and
  `test_only_strings_that_are_new_reach_the_transformer` — assert on which
  strings reached the transformer, not just that the cache "works".
- `test_a_repeat_costs_one_query_and_no_writes` — records every SQL statement
  behind a real HTTP request and asserts a repeat costs one SELECT and no
  writes.
- `test_get_many_uses_one_query_for_the_whole_batch` — 50 strings, one SELECT,
  so the cache does not trade N upstream calls for N queries.
- `test_concurrent_identical_requests_produce_one_payload` — five racing
  requests, one payload, one id.
- `test_both_dialects_ignore_conflicts` — compiles the upsert for SQLite and
  for PostgreSQL, so the PostgreSQL branch is covered without a server.
- `test_a_missing_sqlite_directory_is_created` and
  `test_health_fails_when_the_database_is_unreachable` — regression tests for
  two real bugs: the default `DATABASE_URL` pointed at a `./data` directory a
  fresh checkout does not have, and `/health` reported "ok" without touching
  the database.

The suite was checked by mutation: breaking the fingerprint so it ignored
`list_2`, removing the database touch from `/health`, and making every POST
answer 502 each left the suite green, and each now fails a named test.

## What I would do next

Alembic migrations; an in-process LRU in front of the database for hot strings;
single-flight so racing requests share one transformer call; authentication and
rate limiting at the edge; a TTL and eviction job for the cache; and metrics for
cache hit ratio and transformer latency.
