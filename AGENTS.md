# Repository Guidelines

## Project Structure & Module Organization

The harness is a Python FastAPI service packaged as one container. Core code lives in `api/`: `server.py` exposes REST, job, streaming, and orchestration endpoints; `schedules.py` manages cron-backed runs; and `slack_bot.py` connects Slack Socket Mode to the API. Matching `test_*.py` files sit beside each module. Container startup is defined by `Dockerfile`, `docker-compose.yml`, and `entrypoint.sh`. Bob runtime policy lives under `.bob/`. Keep API examples in `httpie/`, Slack configuration in `slack/`, and user-created persistent data in the gitignored `workspace/` volume.

## Build, Test, and Development Commands

- `podman compose up --build`: build the pinned Bob image and start the API plus optional Slack bot.
- `podman compose logs -f bob`: follow service logs during development.
- `curl http://localhost:8080/health`: verify API readiness and resolved configuration.
- `cd api && pip install -r requirements-dev.txt`: install runtime and test dependencies locally.
- `cd api && pytest -v`: run the complete offline unit suite.
- `podman compose down`: stop and remove the development container. Docker users may substitute `docker` for `podman`.

## Coding Style & Naming Conventions

Use Python 3.12+, four-space indentation, PEP 8 naming, and type annotations for public interfaces and non-obvious data structures. Use `snake_case` for functions and variables, `UPPER_CASE` for environment-derived constants, and leading underscores for internal helpers. Keep endpoint handlers thin and move independently testable logic into modules or helpers. No formatter or linter is configured; follow the existing import grouping and line-wrapping style.

## Testing Guidelines

Tests use pytest and FastAPI's `TestClient`. Name files `test_<module>.py` and tests `test_<behavior>`. Mock Bob subprocesses, Slack/network calls, cron, and filesystem persistence so tests remain fast and offline. Add regression tests for changed endpoints, command construction, validation, and failure paths. There is no enforced coverage threshold.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style subjects such as `fix(slack): ...`, `fix(bob): ...`, `docs: ...`, and `chore: ...`. Use an imperative, concise subject and add a scope when useful. Pull requests should explain the behavior change, list verification commands, link relevant issues, and include request/response examples or Slack screenshots for user-visible changes.

## Security & Configuration

Copy `.env.example` to `.env`; never commit Bob API keys or Slack tokens. Treat changes to `.bob/` and unrestricted mode as security-sensitive, and rebuild the image after modifying runtime policy.
