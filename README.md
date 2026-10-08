# Payload Cache Service

FastAPI microservice that builds payloads from two string lists, caching the
results of an expensive "transformer" call so repeated work is never redone.

> Status: scaffolding. See [Project layout](#project-layout) for where things go.

## Project layout

```
app/
  main.py                  # app factory: settings, lifespan, router registration
  schemas.py               # Pydantic request/response models (the HTTP contract)
  api/
    routes.py              # POST /payload, GET /payload/{id}, GET /health
    deps.py                # DI providers (session, transformer, service)
  core/
    config.py              # Settings (pydantic-settings): db url, latency, log level
    logging.py             # structured logging setup
  db/
    models.py              # SQLModel tables: TransformedString, Payload
    session.py             # async engine + session factory
  domain/
    interleave.py          # interleaving of two lists -> output string
    fingerprint.py         # content hashing: payload fingerprint, source hash
  services/
    transformer.py         # Transformer protocol + simulated external service
    cache.py               # batched cache lookup + conflict-safe upsert
    payload.py             # use case: dedupe, reuse ids, minimise transformer calls
cli/
  __main__.py              # entrypoint: `python -m cli` / `cache-cli`
  settings.py              # CLI arg parsing & validation via pydantic-settings
  client.py                # httpx client against the service
tests/
  unit/                    # domain, transformer, CLI parsing — no I/O
  integration/             # ASGI + real SQLite: endpoints, caching, concurrency
  conftest.py              # fixtures: temp db, fake transformer, async client
.github/workflows/         # CI: ruff, mypy, pytest
```

### Why this split

- `domain/` imports neither FastAPI nor SQLAlchemy. The interleaving and hashing
  rules are the parts most likely to change, so they stay framework-free and
  trivially testable.
- `services/` holds the use cases. The transformer is a `Protocol`, so tests
  inject a counting fake and assert how often the "external service" was hit —
  that count is the core requirement of this task.
- `api/` only translates HTTP to use cases, which keeps request handling thin.
- `cli/` is a separate package: it talks to the service over HTTP only, never
  imports `app/`, so it exercises the same surface a real client would.

## Quickstart

_To be filled in once the service is runnable (Docker and local paths)._

## Design decisions & trade-offs

_To be filled in as decisions are made._
