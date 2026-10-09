# Thin wrappers over uv so CI, Docker and local runs use identical commands.
.PHONY: install lint fmt typecheck test check run up down clean

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy app cli

test:
	uv run pytest

# What CI runs, so a green `make check` locally means a green pipeline.
check: lint typecheck test

run:
	uv run uvicorn app.main:app --reload

up:
	docker compose up --build

# Stops the service but keeps the volume: compose describes it as durable.
down:
	docker compose down

# Removes the volume as well, when a clean database is what you want.
clean:
	docker compose down -v
