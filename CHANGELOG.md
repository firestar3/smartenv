# Changelog

## [0.1.0] - 2026-09-21

### Added

- A Python 3.8+ configuration library with zero mandatory runtime dependencies and typed public APIs.
- Isolated `Env` instances with explicit schemas, ordered per-key source precedence, attribute and mapping access, iteration, dictionary snapshots, and JSON serialization.
- Environment, dotenv, JSON, TOML, and YAML sources with lazy optional dependency imports and a source resolver.
- Dotenv parsing for quotes, exports, comments, multiline values, escapes, UTF-8, and byte order marks.
- Recursive structured-source flattening using uppercase keys and double-underscore paths, with JSON-encoded arrays.
- Type casting for strings, integers, floats, booleans, bytes, lists, dictionaries, typed containers, Optional, Union, Literal, None, Any, and custom callables.
- Required-key checks, aggregate validation errors, custom validators receiving cast values, strict startup validation, and non-strict error and warning reports.
- Structured exception classes for validation, casting, missing keys, missing sources, source loading, and cloud provider failures.
- Schema normalization from dictionaries and Pydantic model field annotations, plus placeholder helpers.
- AWS Secrets Manager, Google Secret Manager, and Azure Key Vault sources with environment-based configuration and lazy SDK imports.
- Cloud payload handling, per-instance thread-safe caches, explicit cache invalidation, cache bypass, and asynchronous loading wrappers.
- Thread-safe configuration refresh, manual reloads, callbacks, lifecycle management, and masked debug representations.
- Optional watchdog file observation with event debouncing, validated reloads, and graceful watcher shutdown.
- An argparse CLI for schema validation, `.env.example` generation, masked configuration listing, and source connection checks.
- Unit and integration tests covering source precedence, casting, validation, cloud SDK behavior, CLI commands, file watching, and concurrency.
- A complete README with cloud, hot reload, FastAPI, Django, and CLI examples, plus a sample environment file and MIT license.
- GitHub Actions CI for Python 3.8–3.12 with Ruff, mypy, pytest, and coverage reporting.
- A tag-triggered distribution build and PyPI publishing workflow.
