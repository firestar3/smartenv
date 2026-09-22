# SMARTENV Build Tracker

## Current release: 1.0.0 — IMPLEMENTATION COMPLETE (2026-09-21)

This release section supersedes the historical behavior and tooling notes below.
The release is built and verified locally; GitHub push/tag and PyPI publication are
maintainer steps documented in docs/RELEASING.md, and have not been performed.

- [x] Core reliability — serialize refreshes, atomically commit valid snapshots, preserve last-good state on rejected strict reloads, cast once, isolate builtin mutable values, and follow Python missing-key conventions.
- [x] Configuration ergonomics — typed defaults, source provenance via get_source(), optional redacted dict/JSON exports, PathLike sources and named dotenv files.
- [x] Sensitive diagnostics — shared key-name masking for representations, CLI listings and cast/validator display errors; document raw exception and heuristic limitations.
- [x] Cloud reliability — monotonic cache TTLs, serialized refreshes, explicit expired-cache failures, context-preserving async loads on Python 3.8, AWS binary secrets, GCP fetch-all key preservation, and clearer configuration/payload failures.
- [x] Hot reload — trailing debounce, serialized reload worker, atomic-save events, changes queued during active reloads, startup cleanup, cancellation and safe callback shutdown.
- [x] CLI — Python 3.8 type-label correction, module entry point, version output, JSON validation/listing, schema defaults and overwrite protection with --force.
- [x] Packaging — single 1.0.0 version source, zero mandatory runtime dependencies, PEP 561 marker, metadata/license checks, tag/version agreement and fresh-environment wheel checks.
- [x] CI — Python 3.8–3.14 on Linux, Windows/macOS on Python 3.12, formatting/lint/strict typing, doctests, a 90% coverage floor, distribution checks and wheel installation.
- [x] Publishing — full CI before upload, verified artifact reuse, commit-pinned actions, Dependabot and PyPI Trusted Publishing through the pypi environment with job-scoped OIDC permissions.
- [x] Documentation — 1.0 README/changelog plus contributor, security, migration and step-by-step GitHub/PyPI release guides.
- [x] Python 3.12.14 and 3.14.7 full suites — 447 passed on each; 93.03% combined statement/branch coverage.
- [x] Python 3.8.10 full suite — 446 passed, 1 skipped (Python 3.10 union syntax only); 93.61% coverage. Optional watchdog and Pydantic tests were exercised.
- [x] Doctests — 18 passed. Ruff, Black and strict mypy passed for all 31 package/test/release-script files. Final import succeeds.
- [x] Distribution verification — built wheel and sdist in dist/1.0.0; strict Twine and archive/version checks passed. Installed wheel into a fresh environment without extras and verified typed defaults, provenance, module/console entry points and OS source loading.

Cloud tests use SDK doubles; real provider credentials were not exercised. Local runs
used Windows. The expanded hosted Linux/macOS matrix will run after the commit is pushed.
No implementation tasks remain for the prepared 1.0.0 release.

## Phase 1: Foundation — COMPLETE (moved to DONE)

## Phase 2: Sources — COMPLETE (moved to DONE)

## Phase 3: Core — COMPLETE (moved to DONE)

## Phase 4: Cloud — COMPLETE (moved to DONE)

## Phase 5: Advanced — COMPLETE (moved to DONE)

## Phase 6: Ship — COMPLETE (moved to DONE)

## DONE

### Python 3.8 CI correction — COMPLETE (2026-09-21)
- [x] Diagnosed the initial GitHub Actions failure in run 35681862191: Python 3.8 renders Optional[int] as Union[int, NoneType], breaking the CLI example-file label assertion. Installation, lint and type checking passed; Python 3.9–3.12 jobs passed.
- [x] smartenv/cli.py — derive Union/Optional labels from typing.get_origin/get_args, including nested list/dict types, instead of relying on Python-version-specific representations. Preserve unsubscripted container labels and support Python 3.10 union notation.
- [x] tests/test_cli.py — added 11 regression cases for nullable unions, member order, nested containers, Literal, bare containers, and modern union notation.
- [x] Full Python 3.12.14 regression suite: 364 passed. Black, Ruff, strict mypy (25 source/test files), and git diff --check passed.
- [x] Full Python 3.8.10 regression suite with coverage: 360 passed, 4 skipped, 92% coverage. Skips are two optional Pydantic tests, one optional watchdog test, and Python 3.10 union notation. The previously failing test now passes on a real Python 3.8 runtime.
- Local compatibility runtime and dependencies are isolated in ignored .venv/ci-runtimes/python38/. Changes are ready to commit and push; the updated hosted CI run has not occurred yet.

### Phase 6: Ship — COMPLETE (2026-09-21)
- [x] README.md — all requested sections, comparison with primary-source references, installation, verified examples, cloud/reload semantics, CLI output, FastAPI/Django integration, contributing and MIT license. Badges distinguish local coverage from hosted CI/publication.
- [x] pyproject.toml — README registered as project metadata; example environment and workflow files included in source distribution.
- [x] CHANGELOG.md — full 0.1.0 feature inventory dated 2026-09-21.
- [x] LICENSE — MIT, 2026 smartenv contributors.
- [x] .env.example — DATABASE_URL, PORT, DEBUG, API_KEY, SECRET_KEY, MAX_RETRIES.
- [x] .github/workflows/ci.yml — push/PR to main, Python 3.8/3.9/3.10/3.11/3.12, install .[dev,yaml,toml], Ruff, mypy, pytest coverage.
- [x] .github/workflows/publish.yml — v*.*.* tag pushes, build, strict Twine metadata check, upload with PYPI_TOKEN and __token__ username.
- [x] smartenv/py.typed — PEP 561 marker included in wheel; .gitignore excludes environments, caches, builds, and local secrets.
- [x] Final tests — python -m pytest tests/ -v --tb=short --cov=smartenv: 353 passed; 92% combined statement/branch coverage.
- [x] Final import — python -c "from smartenv import Env; print('OK')": OK. Zero-dependency import also verified with -S.
- [x] Release packaging — python -m build --no-isolation built wheel and sdist; python -m twine check --strict dist/* passed for both. Inspected archive contents, optional-only dependency metadata, README, license, and console entry point; imported the wheel with -I -S and ran its check-source command.

### Phase 5: Advanced — COMPLETE (2026-09-21)
- [x] smartenv/watcher.py — FileWatcher with lazy watchdog imports and installation hint, deduplicated parent directory watches, daemon observer, per-file 0.5-second debounce, modification/creation/move/deletion handling, reload via Env's locked state update, callbacks, recoverable event errors, idempotent stop/join and safe close from a reload callback.
- [x] smartenv/core.py — hot_reload now instantiates FileWatcher for file sources; removed the obsolete EnvWatcher import and missing-module type ignore. Env invokes its own reload callback once.
- [x] smartenv/cli.py — argparse console/module entry point; validate, generate-example, masked list, check-source; UTF-8 schema reads/writes; optional module-level required/validators; first-source priority; useful errors and exit statuses; Unicode status output on Windows.
- [x] tests/test_cli.py — 32 tests covering validation, required keys, full error reporting, custom validators, exact generated examples, all six sensitive key markers, ordinary values, priorities, malformed schemas, source failures, and subprocess exit codes.
- [x] tests/test_watcher.py — 10 tests covering lifecycle, directory deduplication, typed reloads, callbacks, debounce, ignored events, atomic editor saves, error recovery, missing dependency hints, and real watchdog delivery/closing from the observer callback.
- [x] Required python -m pytest tests/ -x -v run — 353 passed after implementation.

### Phase 4: completion audit — COMPLETE (2026-09-21)
These corrections supersede the earlier Phase 4 implementation details below.
- [x] AWS/GCP/Azure constructors accept explicit None defaults and environment fallbacks. AWS validates a missing secret name when loaded so resolve_source remains lazy.
- [x] CloudSource.aload uses run_in_executor for Python 3.8 compatibility. All fetches are serialized per source, including cache=False; successful cache results remain isolated copies.
- [x] parse_secret_payload preserves plaintext whitespace and accepts a configurable fallback key; AWS no longer renames a legitimate JSON SECRET entry to AWS_SECRET.
- [x] GCP reads the real SDK response.payload.data object and wraps client initialization failures in CloudAuthError. Existing explicit-secret and fetch-all modes remain supported.
- [x] Azure returns unchanged secret values at uppercased names, preserves dashes, reuses its client, and distinguishes None (list all) from [] (fetch none).
- [x] Cloud classes/helpers included in sources.__all__; optional SDKs remain lazy.
- [x] Cloud regression suite expanded from 59 to 66 tests, including deterministic missing-SDK checks; all pass without cloud credentials or network calls.

### Final verification and operating notes
- Local runtime: Python 3.12.14 on Windows, using .venv/Scripts/python.exe because python is absent from PATH and the existing py launcher points to an unavailable Store installation.
- python -m black --check --workers 1 smartenv tests: 25 files unchanged.
- python -m ruff check . --no-cache: all checks passed.
- python -m mypy (strict): 25 source/test files passed; mypy smartenv: 18 modules passed.
- python -m pytest --doctest-modules smartenv -q: 18 passed (sandbox cache-write warning only).
- Python 3.8 grammar check: all 18 package modules parsed successfully. Other Python runtimes are configured in CI but were not executed locally.
- Cloud tests use SDK doubles. Real cloud authentication and hosted GitHub Actions have not been exercised in this checkout.
- Wheel and source archive are in dist/. The publishing workflow is configured; no release has been uploaded to PyPI.
- Cloud caches have no expiry or polling: use cache_clear() or cache=False for refreshes. Strict failed reloads expose the new validation state, skip the callback, and do not restore an earlier configuration. These semantics are documented in README.md.
- There are no outstanding implementation tasks for phases 1–6.

### Phase 4: Cloud — COMPLETE
- [x] smartenv/sources/base.py — CloudSource (BaseSource subclass): thread-safe per-instance result cache behind `cache=True` (failures are NOT cached; load() returns fresh copies; cache_clear()), abstract `_fetch()` implemented by providers, aload() via asyncio.to_thread (3.8-compatible), plus parse_secret_payload() (JSON object -> flattened via flatten_mapping; non-object/broken-JSON/plain string -> {"SECRET": value})
- [x] smartenv/sources/aws_source.py — AwsSource(secret_name="", region="", cache=True): env fallbacks AWS_SECRET_NAME / AWS_REGION (default "us-east-1"), lazy `import boto3` -> CloudAuthError with "pip install smartenv[aws]" hint, boto3.client created once per instance, get_secret_value(SecretId=...), JSON payload flattened / plain string served as {"AWS_SECRET": ...}, all API errors wrapped in CloudAuthError(provider="aws"), name="aws_secrets"
- [x] smartenv/sources/gcp_source.py — GcpSource(project_id="", secret_id="", version="latest", cache=True): env fallbacks GCP_PROJECT_ID / GCP_SECRET_ID; with secret_id -> access_secret_version on `<secret>/versions/<version>`; without -> list_secrets(project) + access each; lazy import of google.cloud.secretmanager -> CloudAuthError with "pip install smartenv[gcp]", payload decoded from response.payload.data bytes; client created once; name="gcp_secrets"
- [x] smartenv/sources/azure_source.py — AzureSource(vault_url="", secret_names=None, cache=True): env fallback AZURE_VAULT_URL; lazy imports of azure.keyvault.secrets.SecretClient + azure.identity.DefaultAzureCredential -> CloudAuthError with "pip install smartenv[azure]"; named secrets fetched individually, else list_properties_of_secrets + fetch all; keys are uppercased secret names (JSON payload -> `NAME__SUBKEY`); name="azure_secrets"
- [x] smartenv/sources/__init__.py — cloud classes exposed via PEP 562 _LAZY_ATTRIBUTES (AwsSource, GcpSource, AzureSource, CloudSource, parse_secret_payload); resolve_source("aws_secrets"|"gcp_secrets"|"azure_secrets", case-insensitive) unchanged from Phase 2 wiring — Phase 2 tests needed no changes
- [x] tests/test_cloud_sources.py — 59 tests, no network: fake boto3/google.cloud.secretmanager/azure.* modules injected into sys.modules (RecordingClient call logs, FakeSecretBundle attr holder, fixture cleanup via uninstall_fake_modules); covers parse_secret_payload (9 parametrized cases), CloudSource cache semantics (per-instance, off, clear, failure-not-cached, copies, 5-thread concurrent single-fetch, concurrent failure-then-success), aload (values + error propagation), per-provider happy paths (JSON + plain payload, env fallbacks, defaults, region/version, fetch-all, listing), API error wrapping, ImportError pip-install hints, resolve_source cloud paths

### Phase 4 verification
- python -m pytest tests/ -q -> 304 passed (245 + 59)
- python -m pytest tests/test_cloud_sources.py -q -> 59 passed
- python -m pytest --doctest-modules smartenv -q -> 18 passed (was 17; base.py parse_secret_payload doctest added)
- python -m black smartenv tests -> all files unchanged (black --check on full tree times out in this shell; per-file check of the 6 touched files: 6 files left unchanged)
- python -m ruff check smartenv tests -> All checks passed
- python -m mypy (strict) -> Success: no issues found in 21 source files
- python -m build --wheel -> smartenv-0.1.0-py3-none-any.whl includes aws/gcp/azure sources

### Phase 4 decisions worth remembering
- CloudSource lives in sources/base.py (not a new module) so the cloud sources share one thread-safe cache/aload implementation; parse_secret_payload is module-level and shared by all three providers.
- CloudAuthError(provider=..., message=...) is reused for missing-SDK cases (message carries the pip install hint) — it is not only for auth failures; str(exc) therefore always mentions the extra to install.
- boto3/google/azure clients are created lazily ONCE per source instance (self._client) — recreating per fetch broke the cache=False call-count tests and is wasteful; SDK import still happens on every _fetch so uninstalling the fake module in tests keeps the ImportError path testable.
- mypy: the optional SDK imports need NO `# type: ignore` because pyproject mypy overrides already set ignore_missing_imports = true for boto3.*/google.*/azure.*; adding one makes the comment "unused" and fails strict mode.
- In tests, `from google.cloud import X` resolves through the google.cloud package attribute, so the fake fixture must install `google.cloud` AND set `.secretmanager` on it to the fake submodule (plain sys.modules registration of the submodule alone is not enough).
- mypy flags dynamically assigned attrs (client.region, client.credential) — declare them as typed instance attributes on the fake client classes (region: Optional[str], credential: Any).
- The fake AWS fixture yields a zero-arg callable returning the pre-created client (the source creates the client inside _fetch, so yield-at-setup cannot return the client object directly).

### Phase 1: Foundation — COMPLETE
- [x] pyproject.toml — hatchling backend, zero mandatory deps, extras (yaml/toml/watch/aws/gcp/azure/pydantic/all/dev), `smartenv` console script, PyPI classifiers, black/ruff/mypy/pytest/coverage config
- [x] smartenv/exceptions.py — SmartEnvError base + ValidationError, CastError, MissingKeyError, MissingSourceError, SourceLoadError, CloudAuthError, each with structured attributes and an informative `__str__`
- [x] smartenv/casters.py — cast() for str/int/float/bool/bytes/list/List[X]/dict/Dict[K,V]/Optional[X]/Union/Literal/NoneType/Any plus a callable fallback; can_cast() helper; `key` context on errors
- [x] smartenv/validators.py — validate() + validate_or_raise() + ValidationResult (is_valid/errors/warnings, `raise_if_invalid()`); reports every problem, never raises
- [x] tests/test_casters.py — 80 tests (every type, all truthy/falsy bool strings, CastError cases, list, dict, Optional, Literal, Union, error context) — passing
- [x] tests/test_validators.py — 26 tests (missing required, wrong type, custom validators pass/fail/raise, empty required value, all-valid) — passing
- [x] smartenv/__init__.py — v0 public API exports so `import smartenv` works; Phase 3 extends it with the Env façade

### Phase 1 verification (Python 3.12.10, pytest 9.1.1, hatchling 1.32.4, mypy 2.3.1)
- `python -m pytest tests/test_casters.py -x -v` → 80 passed
- `python -m pytest tests/test_validators.py -x -v` → 26 passed
- `python -m pytest tests/ -q` → 106 passed
- `python -m pytest --doctest-modules smartenv -q` → 5 passed
- `python -m black --check smartenv tests` → 6 files left unchanged
- `python -m ruff check smartenv tests` → All checks passed
- `python -m mypy` (strict) → Success: no issues found in 6 source files
- `python -c "import smartenv"` → ok, version 0.1.0
- hatchling wheel build → smartenv-0.1.0-py3-none-any.whl containing smartenv/{__init__,casters,exceptions,validators}.py and the `smartenv = smartenv.cli:main` entry point

### Phase 1 decisions worth remembering
- `readme` is deliberately absent from [project] until Phase 6 writes README.md (hatchling rejects a missing readme file); the sdist include list already references it.
- `[tool.ruff.lint.pyupgrade] keep-runtime-typing = true`: annotations keep typing.List/Dict/Optional/Union so they stay evaluable at runtime on Python 3.8/3.9 (dataclasses + get_type_hints).
- mypy uses `python_version = "3.10"` because recent mypy no longer accepts 3.8 targets; the 3.8 syntax surface is enforced by ruff's `target-version = "py38"`.
- Casting rules: text is trimmed, empty comma-list entries are dropped, `""`/`null`/`none` (any case) become None only for Optional/NoneType targets; bool accepts only true/1/yes/on and false/0/no/off before raising CastError.
- Validation rules: required keys must be present and non-empty (None/whitespace count as empty), empty optional values are skipped, custom validators receive the cast value, a validator for an unset key produces a warning, duplicate required keys are reported once.

### Phase 2: Sources — COMPLETE
- [x] smartenv/sources/base.py — `BaseSource` (abstract `name` property + `load()`), `FileSource` (Path handling, `exists()`, UTF-8 `read_text()` with BOM stripping, `MissingSourceError`/`SourceLoadError`) and `flatten_mapping()` (recursive, uppercase `__` separator, stringifies every leaf)
- [x] smartenv/sources/os_source.py — `OsSource`, `name == "os"`, `load()` returns an isolated `dict(os.environ)` snapshot
- [x] smartenv/sources/dotenv_source.py — `DotenvSource` + `parse_dotenv()`: `KEY=VALUE`, `"double"` (multi-line, `\n \r \t \\ \" \'` escapes), `'single'`, `export`, comments/blank lines, inline comments after unquoted values, UTF-8 (+BOM), malformed lines skipped silently, last definition wins
- [x] smartenv/sources/json_source.py — `JsonSource` via `json.loads`, recursive flattening, all values converted to strings
- [x] smartenv/sources/toml_source.py — `TomlSource` using `tomllib` (3.11+) or `tomli`, resolved through importlib; `ImportError: ... pip install smartenv[toml]` when neither is available
- [x] smartenv/sources/yaml_source.py — `YamlSource` via `yaml.safe_load`; `ImportError: ... pip install smartenv[yaml]` when PyYAML is missing
- [x] smartenv/sources/__init__.py — `resolve_source()` factory (`os`, cloud names, `.env`/`.json`/`.toml`/`.yaml`/`.yml`, `ValueError` otherwise), lazy cloud imports with `pip install smartenv[aws|gcp|azure]` hints, PEP 562 `__getattr__` for `TomlSource`/`YamlSource`
- [x] tests/test_sources.py — 60 tests (dotenv syntax matrix, JSON/TOML/YAML flattening, `os.environ` monkeypatching, `flatten_mapping` units, factory + lazy-import checks) — passing

### Phase 2 verification
- `python -m pytest tests/test_sources.py -x -v` → 60 passed
- `python -m pytest tests/ -q` → 166 passed (106 Phase 1 + 60 Phase 2)
- `python -m pytest --doctest-modules smartenv -q` → 12 passed
- `python -m black --check smartenv tests` → 14 files left unchanged
- `python -m ruff check smartenv tests` → All checks passed
- `python -m mypy` (strict) → Success: no issues found in 14 source files
- `python -c "import smartenv, smartenv.sources"` → ok

### Phase 2 decisions worth remembering
- The three structured sources share one `flatten_mapping()`: keys are uppercased and joined with `__`, lists are JSON encoded (`'["a","b"]'`) so `cast()` round-trips them, booleans become `"true"/"false"`, `None` becomes `""`, nesting works to any depth and empty nested mappings contribute no keys.
- `FileSource.read_text()` strips a UTF-8 BOM and raises `MissingSourceError` for absent paths/directories and `SourceLoadError` for unreadable or unparsable files; nothing touches the disk until `load()` is called.
- Dotenv edge cases: `#` only starts a comment at the start of a value or after whitespace (`http://host/#frag` survives), an unterminated quote skips just that line and parsing resumes on the next one, unknown escapes keep their backslash (`\d` stays `\d`) so Windows paths and regexes are not corrupted.
- Optional sources are imported lazily — a subprocess test asserts PyYAML/`tomllib` never enter `sys.modules` on a plain `import smartenv.sources`, preserving the zero mandatory dependency rule.
- `resolve_source("aws_secrets"|"gcp_secrets"|"azure_secrets")` currently raises `ImportError` naming the missing module and the right `pip install smartenv[...]` extra (Phase 4 modules); the test accepts either that or a real `BaseSource` so Phase 4 needs no test change.
- Doctest examples avoid embedded `\n` inside single-line examples: in a docstring a single backslash is consumed by the Python compiler, so multi-line examples must be written as separate calls or with `\\n`.

### Phase 3: Core - COMPLETE
- [x] smartenv/schema.py - normalize_schema() (dicts copied as-is; pydantic BaseModel subclasses via model_fields (v2) / __fields__ (v1), lazy import guarded by ImportError -> TypeError with pip install smartenv[pydantic] hint) + get_default_value() (valid placeholder per type: 0/0.0/""/[]/{}/None/first Literal member/None for Optional/{} for Any)
- [x] smartenv/core.py - Env: resolve_source()-built source chain (first source wins per key, later sources fill gaps), strict mode raising ValidationError/MissingSourceError, non-strict collecting errors/warnings with valid, _coerce() (empty->None for Optional, cast failures and unset keys omitted), required keys (deduped tuple; schema-less names warn), custom validators (receive the cast value; False/string = problem), __getattr__/__getitem__/get()/dict()/json(**dumps_kwargs)/__contains__/__len__/__iter__/sorted masked __repr__ (Env(PORT=8080, SECRET_KEY='***')), MissingKeyError with key-specific messages (_-prefixed names raise AttributeError), reload() (+on_reload callback, re-validates, re-raises in strict), close() idempotent, context manager, _start_watcher() lazily importing smartenv.watcher with graceful warning, RLock around load/reload/access
- [x] smartenv/__init__.py - full Phase 3 exports (Env, all sources + resolve_source, schema helpers, all exceptions; 24-entry __all__)
- [x] tests/test_core.py - 79 tests: normalize_schema (incl. pydantic v2 create_model), get_default_value (parametrized), construction/loading (default OsSource, source priority os-vs-.env both orders, casting incl. List[str]/Literal, JSON flattening, undeclared keys hidden, empty optional->None, empty required reported, TypeError/ValueError/MissingSourceError/SourceLoadError), access patterns (attr/item/get/dict-copy/json/contains/len/iter/masked repr/MissingKeyError messages/private AttributeError/hasattr quirk), strictness (missing required, bad cast, validator failures, required-without-schema warning, hot_reload watcher-or-warning), lifecycle (reload file changes, on_reload, strict reload re-raise, error refresh, close idempotent, context manager, schema/required properties), thread safety (4 readers + reload writer behind Barrier), end-to-end multi-source + pydantic-model schema - passing

### Phase 3 verification
- python -m pytest tests/test_core.py -x -v -> 79 passed
- python -m pytest tests/ -q -> 245 passed (106 + 60 + 79)
- python -m pytest --doctest-modules smartenv -q -> 17 passed
- python -m black --check smartenv tests -> exit 0
- python -m ruff check smartenv tests -> All checks passed
- python -m mypy (strict) -> Success: no issues found in 17 source files
- python -c "import smartenv" -> ok
- python -m build --wheel -> smartenv-0.1.0-py3-none-any.whl built successfully

### Phase 3 decisions worth remembering
- MemorySource in tests subclasses BaseSource: name is an abstract property with no setter, so it is implemented as a @property over self._name; an instance attribute (self.name: str = ...) does not satisfy mypy's abstract check.
- Env._build_source() duck-types source objects (callable(getattr(spec, "load", None))); mypy strict needs `source: BaseSource = candidate` assignment (not `return cast(...)` on the same line) to silence no-any-return for duck-typed candidates.
- `from smartenv.watcher import EnvWatcher` needs `# type: ignore[import-not-found]` until Phase 5 adds the module - remove the ignore comment when it lands.
- mypy does not narrow index expressions (env.sources[0]) - bind `source = env.sources[0]` then `assert isinstance(source, FileSource)` before using `.path`.
- Env semantics locked by tests: only schema-declared keys exposed; first-source-wins per key; missing non-strict source file -> warning ("skipped"), strict -> MissingSourceError; corrupt source raises SourceLoadError in both modes; hasattr(env, "KEY") propagates MissingKeyError for public names (False for _-prefixed) - documented quirk.
