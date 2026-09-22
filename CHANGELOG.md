# Changelog

## [1.0.0] - 2026-09-21

### Added

- Explicit `Env(defaults=...)` fallbacks, validated with the schema after all sources.
- `Env.get_source(key)` to identify the source of a resolved value.
- `Env.dict(redact=True)` and `Env.json(redact=True)` for masked inspection.
- Optional positive `cache_ttl` on AWS, GCP, Azure, and custom cloud sources; expiration is checked on load.
- AWS UTF-8 binary secret support and validation of malformed provider responses.
- `pathlib.Path` source specifications and direct recognition of `.env.local`, `.env.production`, and other named dotenv variants.
- `python -m smartenv`, `--version`, JSON output for CLI `validate` and `list`, and `generate-example --force`.
- Migration, contributor, security, and PyPI release guides.
- A single version definition shared by runtime and distribution metadata.
- CI for Python 3.8–3.14 on Linux and Python 3.12 on Windows and macOS; formatting, strict typing, doctests, a 90% coverage minimum, distribution validation, and isolated installation checks.
- Tag-triggered PyPI Trusted Publishing after the complete CI suite, using verified wheel/source artifacts and publication attestations.
- Commit-pinned GitHub Actions and Dependabot configuration for workflow maintenance.

### Fixed

- Strict failed reloads and source loading failures preserve the last successful configuration and validation report.
- Refreshes are serialized; casting is performed once per schema value, so custom casters are not invoked twice.
- Copies of builtin mutable values isolate readers, defaults, and source state.
- Sensitive key names are consistently masked in debug representations, CLI listings, and cast/validator display errors.
- File observation uses a trailing 0.5-second quiet period, handles atomic saves, queues edits received during a reload, and cancels pending work on shutdown.
- Watcher startup failures clean up threads; callbacks may close their own environment safely.
- GCP fetch-all retains individual plaintext secrets under their uppercased secret IDs.
- Cloud refresh failures do not extend expired caches or silently return stale data; async loading preserves context variables on Python 3.8+.
- Existing example files are protected from accidental overwrite.

### Compatibility notes

- `MissingKeyError` now also inherits from `AttributeError` and `KeyError`; missing attributes work with `hasattr` and `getattr` defaults.
- Failed strict reload reports are carried by the exception, rather than replacing `env.errors` and the active snapshot.
- In-place edits to containers returned by `Env` no longer mutate its internal configuration.
- Sensitive diagnostic text and GCP fetch-all plaintext keys intentionally differ from 0.1.
- Example generation requires `--force` when the destination already exists.
- Publishing uses a configured PyPI Trusted Publisher and GitHub `pypi` environment instead of a `PYPI_TOKEN` secret.
- See [the migration guide](docs/MIGRATING.md) before updating existing applications.

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
