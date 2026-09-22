# smartenv

[![PyPI](https://img.shields.io/pypi/v/smartenv)](https://pypi.org/project/smartenv/)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/firestar3/smartenv/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/firestar3/smartenv/actions/workflows/ci.yml)
[![Coverage floor: 90%](https://img.shields.io/badge/coverage_floor-90%25-blue)](pyproject.toml)

**One library to load, validate, and manage all your config — everywhere.**

Combine environment variables, local files, and cloud secrets in one explicit priority chain.
Declare your types once, catch configuration errors at startup, and access real Python values.
The core uses only the standard library; optional integrations load when you use them.

Version 1.0 adds atomic reload rollback, explicit defaults, source provenance, expiring cloud
caches, and safer diagnostics. Python 3.8–3.14 is covered by the CI configuration, with
Windows and macOS checks on Python 3.12. The coverage badge describes the enforced minimum;
the CI and PyPI badges report their respective services.

Upgrading from 0.1? Read [the migration guide](docs/MIGRATING.md).

## Why smartenv?

smartenv is for applications that need several configuration sources, an explicit schema,
and the same loading rules in development and production.

| Feature | smartenv | python-dotenv | dynaconf | environs | raw `os.environ` |
| --- | --- | --- | --- | --- | --- |
| Multi-source fallback | Ordered files, environment, and cloud | Environment + dotenv; merge dictionaries yourself | Layered files, environment, and loaders | Environment + dotenv | Write your own |
| Type casting | Schema types and callables | Strings | Automatic parsing and converters | Typed parser methods | Write your own |
| Startup validation | Required keys, types, custom validators | Write your own | Validators | Parser validation; `seal()` collects errors | Write your own |
| Cloud secrets | AWS, GCP, Azure extras | Custom integration | Vault / Redis extras; custom loaders | Custom integration; secret files supported | Custom integration |
| Hot reload | File watcher extra | Call loading code again | Reload API / fresh settings reads | Call loading code again | No file loading |
| CLI tools | Validate, generate, list, check-source | Optional CLI extra | Built-in CLI | No dedicated config CLI | No config CLI |
| Zero deps | Yes, core | Yes, core | Yes, core with vendored helpers | No | Standard library |

“Write your own” and “custom integration” mean application code is needed. The comparison
describes documented built-in features, not what each library can support through extensions.
Sources: [python-dotenv documentation](https://bbc2.github.io/python-dotenv/),
[Dynaconf documentation](https://www.dynaconf.com/),
[Dynaconf fresh settings](https://www.dynaconf.com/configuration/#fresh_vars),
[Dynaconf dependencies](https://github.com/dynaconf/dynaconf/blob/master/pyproject.toml),
[environs documentation](https://pypi.org/project/environs/),
[environs dependencies](https://github.com/sloria/environs/blob/main/pyproject.toml), and
[`os.environ`](https://docs.python.org/3/library/os.html#os.environ).

## Install

After the package is published to PyPI:

```bash
pip install smartenv
pip install "smartenv[yaml,aws]"
pip install "smartenv[all]"
```

To use this checkout now, run `python -m pip install -e .` from the project directory.

| Extra | Enables |
| --- | --- |
| `yaml` | YAML files through PyYAML |
| `toml` | TOML on Python 3.8–3.10 through tomli; Python 3.11+ uses `tomllib` |
| `watch` | File watching through watchdog |
| `aws` | AWS Secrets Manager through boto3 |
| `gcp` | Google Secret Manager |
| `azure` | Azure Key Vault and DefaultAzureCredential |
| `pydantic` | Pydantic models as schema declarations |
| `all` | Every optional integration above |
| `dev` | Test, coverage, formatting, linting, and type-checking tools |

## Quick Start

Create a `.env` file in your working directory:

```dotenv
DATABASE_URL=sqlite:///app.db
PORT=8000
DEBUG=false
MAX_RETRIES=3
```

Then run this Python example. Existing environment variables take priority over the file:

```python
from smartenv import Env

schema = {
    "DATABASE_URL": str,
    "PORT": int,
    "DEBUG": bool,
    "MAX_RETRIES": int,
}
env = Env(
    schema=schema,
    sources=["os", ".env"],
    required=["DATABASE_URL", "PORT"],
    strict=True,
)
print(env.PORT)                    # 8000 (int)
print(env["DEBUG"])                # False (bool)
print(env.get("MAX_RETRIES", 3))    # 3
print(env.valid)                   # True
```

Only keys declared in `schema` are exposed. Keys become required only when named in
`required`; `Optional[int]` describes an allowed value type, not presence. `Env(schema)`
defaults to the `os` source. Use `env.dict()` for a snapshot and `env.json()` for JSON
serialization of JSON-compatible values. These exports contain the actual values.
Use `env.dict(redact=True)` or `env.json(redact=True)` for key-based masking when inspecting
configuration. See [Security](SECURITY.md) for the limits of that masking.

Explicit defaults are cast and validated like source values, with the lowest priority:

```python
env = Env(
    {"PORT": int, "DEBUG": bool},
    sources=["os"],
    defaults={"PORT": 8000, "DEBUG": False},
    strict=True,
)
print(env.get_source("PORT"))  # "os" if set there, otherwise "defaults"
```

`get_source(key)` returns the winning source's name. A missing resolved key raises
`MissingKeyError`, which is also an `AttributeError` and `KeyError`, so `hasattr`,
`getattr(env, "MISSING", fallback)`, and standard missing-key handling work normally.
Use brackets for keys that overlap API names such as `env["sources"]` or contain dashes.
Returned builtin containers are copied; custom objects returned by casters should be
treated as immutable.

## Source Fallback Chain

Sources have **left-to-right priority for each key**. The first source defining a key wins;
later sources fill gaps. An empty value still counts as defined, so it does not fall through.

```text
sources=["os", ".env", "defaults.json"]

highest priority                                  lowest priority
   os.environ         .env           defaults.json
  PORT=9000        PORT=8000           PORT=3000
                   DEBUG=true         DEBUG=false
                                      MAX_RETRIES=3
       |                |                  |
       +----------------+------------------+
                        v
           PORT=9000, DEBUG=True, MAX_RETRIES=3
```

Built-in source strings are `os`, `.env` paths, `.json`, `.toml`, `.yaml` / `.yml`,
`aws_secrets`, `gcp_secrets`, and `azure_secrets`. Named dotenv variants such as
`.env.production`, `pathlib.Path` instances, and source objects are also accepted.
Custom `BaseSource` subclasses need a `name` property and a `load()` method returning
a flat mapping of key names to string values.

JSON, TOML, and YAML mappings are flattened into uppercase keys separated by `__`.
For example, `{"database": {"host": "localhost"}}` becomes `DATABASE__HOST=localhost`.
Arrays become JSON text and can be cast with `List[T]`.

By default, missing files produce warnings; with `strict=True` they raise
`MissingSourceError`. A malformed source raises `SourceLoadError`. All sources are loaded,
even when earlier sources already supply every schema key: this is value precedence,
not an outage failover mechanism. Reading sources does not mutate `os.environ`.

## Type Casting

Use `typing` generics for examples that also run on Python 3.8:

| Schema type | Raw input | Result |
| --- | --- | --- |
| `str` | `"hello"` | `"hello"` |
| `int` | `"8080"` | `8080` |
| `float` | `"0.75"` | `0.75` |
| `bool` | `"yes"` / `"off"` | `True` / `False` |
| `bytes` | `"hello"` | `b"hello"` (UTF-8) |
| `list` / `List[str]` | `"red, blue"` | `["red", "blue"]` |
| `List[int]` | `"[1, 2, 3]"` | `[1, 2, 3]` |
| `dict` | `'{"enabled": true}'` | `{"enabled": True}` |
| `Dict[str, int]` | `'{"workers": "4"}'` | `{"workers": 4}` |
| `Optional[int]` | `"null"` / `"42"` | `None` / `42` |
| `Union[int, str]` | `"42"` / `"auto"` | `42` / `"auto"` |
| `Literal["dev", "prod"]` | `"prod"` | `"prod"`; other choices fail |
| `type(None)` | `"none"` | `None` |
| `Any` / `object` / `None` | Any value | Passed through unchanged |
| Callable, e.g. `Decimal` or an enum class | Text accepted by the callable | Callable result |

Boolean text accepts `true`, `1`, `yes`, `on`, `false`, `0`, `no`, and `off`, ignoring
case and surrounding whitespace. Optional targets recognize empty text, `null`, and `none`
as `None`. Comma-separated lists trim entries and omit empty entries. Unions try members
in declaration order. A direct `cast(value, type_hint)` call raises `CastError` on failure.

Missing keys remain absent, even when their type is `Optional`. Empty values are ignored
by validation unless required; `Env` preserves an empty Optional value as `None`.
Pydantic model schemas contribute field annotations only; model defaults and Pydantic
validators are not executed. Supply `required` and `validators` to `Env` explicitly.

## Validation

Use `strict=True` to reject invalid startup configuration and report every validation
problem in one exception:

```python
from smartenv import Env, ValidationError

try:
    Env(
        schema={"DATABASE_URL": str, "API_KEY": str},
        sources=[],
        required=["DATABASE_URL", "API_KEY"],
        strict=True,
    )
except ValidationError as error:
    print(error)
```

```text
environment validation failed with 2 errors
errors:
  - missing required key 'DATABASE_URL'
  - missing required key 'API_KEY'
```

Without strict mode, inspect `env.valid`, `env.errors`, and `env.warnings`.
Custom validators receive the cast value:

```python
env = Env(
    {"PORT": int},
    sources=["os", ".env"],
    required=["PORT"],
    validators={"PORT": lambda value: 1 <= value <= 65535},
    strict=True,
)
```

A validator can return `True` or `None` for success, `False` for failure, or an explanatory
string. Exceptions from validators become validation errors. Each schema value is cast
once per load, and that result is passed to its validator and exposed by `Env`.
Sensitive key names are masked in cast and validator display messages. Raw exception
attributes, chained exceptions, and values under unrecognized names may still contain
secrets; keep full exception reports out of public responses. See [Security](SECURITY.md).

## Cloud Secrets

Install the matching extra and configure credentials using the provider SDK's normal
credential discovery. Cloud sources import their SDKs lazily and wrap provider failures
in `CloudAuthError`, including a useful install hint when an SDK is missing.

**AWS Secrets Manager** — a JSON object supplies schema keys; plain text uses `AWS_SECRET`:

```python
from smartenv import Env
from smartenv.sources import AwsSource

aws = AwsSource(secret_name="production/myapp", region="us-east-1", cache_ttl=300)
env = Env({"DATABASE_URL": str}, sources=["os", aws],
          required=["DATABASE_URL"], strict=True)
```

With no explicit arguments, `AwsSource()` reads `AWS_SECRET_NAME` and `AWS_REGION`;
the region defaults to `us-east-1`. Both `SecretString` and UTF-8 `SecretBinary` payloads
are supported; arbitrary binary secrets that are not UTF-8 text are rejected.

**Google Secret Manager** — decode a secret version as a JSON object or expose plain text
as `SECRET`:

```python
from smartenv import Env
from smartenv.sources import GcpSource

gcp = GcpSource(project_id="my-project", secret_id="myapp-config", version="latest")
env = Env({"DATABASE_URL": str}, sources=[gcp],
          required=["DATABASE_URL"], strict=True)
```

`GCP_PROJECT_ID` and `GCP_SECRET_ID` provide constructor fallbacks. JSON object payloads
in AWS and GCP are flattened with the same rules as JSON files.
Without an explicit secret ID or `GCP_SECRET_ID`, GCP lists and fetches the project's
secrets. In this mode, plain payloads use each secret's uppercased ID; JSON payloads merge
their flattened keys. Prefer explicit IDs to limit listing permissions and ambiguous keys.

**Azure Key Vault** — secret names become uppercase keys; values remain their stored text:

```python
from smartenv import Env
from smartenv.sources import AzureSource

azure = AzureSource(vault_url="https://myvault.vault.azure.net",
                    secret_names=["database-url"])
env = Env({"DATABASE-URL": str}, sources=[azure],
          required=["DATABASE-URL"], strict=True)
database_url = env["DATABASE-URL"]
```

`AzureSource()` reads `AZURE_VAULT_URL` and uses `DefaultAzureCredential`. Omit
`secret_names` to list and fetch all secrets; this also requires list access. Dashes in
Azure secret names are preserved, so use bracket access for those keys.

Every cloud source supports `await source.aload()`, using a thread-backed wrapper around
the synchronous SDK. Successful results are cached per instance by default; returned
dictionaries are copies and failed fetches are not cached. Set `cache=False` to fetch on
every load, or call `source.cache_clear()` before `env.reload()` to refresh cached secrets.
Set `cache_ttl` to a positive number of seconds to expire cached results. Expiration triggers
a fetch on the next load, not a background poll. The default `cache_ttl=None` caches
indefinitely. Failed refreshes raise instead of silently serving expired secrets; strict
`Env` reloads retain their previous configuration. SDK timeouts and retries follow the
provider's configuration. An async wrapper does not make the SDK itself asynchronous.

## Hot Reload

Install `smartenv[watch]`, then enable file watching and keep the process running:

```python
import time
from smartenv import Env

def on_reload(config: Env) -> None:
    print("New port:", config.PORT)

with Env(
    {"PORT": int},
    sources=[".env"],
    required=["PORT"],
    strict=True,
    hot_reload=True,
    on_reload=on_reload,
) as env:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
```

The daemon observer watches each file's parent directory. Reload starts after 0.5 seconds
without another matching event, including editor saves that replace the file atomically.
A single worker serializes reloads and callbacks. Reload reads all sources, validates and
casts them, and atomically publishes the new configuration. The callback runs after a
successful reload, on the worker thread; keep callbacks short and thread-safe. Cloud caches
still apply. Use `env.close()` or the context manager to cancel pending reloads and wait for
active work to finish. A callback may safely call `env.close()` itself.
Without watchdog, `hot_reload=True` records a warning; check `env.warnings` and `env.watcher`.
If strict validation or source loading fails, the previous values, provenance, and validation
report remain intact. The watcher records a warning and skips the callback; a later valid
save can recover. Direct `env.reload()` raises the error for the caller to inspect.
Non-strict validation continues to publish its latest values and error report.
Use `env.dict()` when several keys must come from the same snapshot: separate attribute
reads can span a concurrent reload. Callback failures occur after the update and do not
roll back a successfully published configuration.

## CLI

The `smartenv` command is included in the base installation. A schema module defines a
`schema` dictionary and optional `required`, `validators`, and `defaults` values:

```python
# schema.py
schema = {"DATABASE_URL": str, "PORT": int}
required = ["DATABASE_URL"]
validators = {"PORT": lambda value: 1 <= value <= 65535}
defaults = {"PORT": 8000}
```

Schema files run as Python code when loaded. Use schema modules you trust. Install the
`yaml` extra to include `config.yaml` in these examples.
CLI defaults must name declared schema keys and are validated after source values take
priority. Generated examples keep values blank, even when defaults are defined.

**Validate** sources against the schema. All validation errors are listed; success exits
with status 0 and failure with status 1:

```console
$ smartenv validate --schema schema.py --sources .env config.yaml
✓ Validation passed
```

Use `--format json` on `validate` or `list` for machine-readable output:

```console
$ smartenv validate --schema schema.py --sources .env --format json
{"valid": true, "errors": [], "warnings": []}
$ python -m smartenv --version
smartenv 1.0.0
```

If `DATABASE_URL` is absent, the validation output includes:

```text
✗ missing required key 'DATABASE_URL'
```

**Generate an example** with type and presence comments. Values are intentionally blank
for the application owner to fill in:

```console
$ smartenv generate-example --schema schema.py --output .env.example
✓ Wrote .env.example
```

```dotenv
# DATABASE_URL (str) [REQUIRED]
DATABASE_URL=
# PORT (int) [optional]
PORT=
```

Existing output files are protected. Pass `--force` to intentionally replace one.

**List** all source values without needing a schema. Earlier sources win. For a file with
`PORT=8000`, `DEBUG=false`, and `API_KEY` set, representative output is:

```console
$ smartenv list --sources .env config.yaml
API_KEY=*****
DEBUG=false
PORT=8000
```

Any key containing `AUTH`, `CERT`, `CREDENTIAL`, `KEY`, `PASS`, `PRIVATE`, `SECRET`, or `TOKEN`
(case-insensitive) is masked as `*****`. Values under other names are printed as-is.

**Check a source** using environment-based provider configuration and credentials:

```console
$ smartenv check-source --source aws_secrets
✓ Connected to aws_secrets
```

On a connection or loading error it prints `✗ Failed: ...` and exits with status 1.
Use `smartenv --help` or `python -m smartenv --help` for command usage. Invalid command
syntax exits with status 2. The CLI loads every explicitly named source and fails when
one cannot be loaded, including a missing file.

## Framework Integration

**FastAPI:** create configuration once during application startup, then return it from a
dependency. The dependency pattern follows the
[FastAPI settings guide](https://fastapi.tiangolo.com/advanced/settings/).

```python
from fastapi import Depends, FastAPI
from smartenv import Env

settings = Env(
    {"PORT": int, "DEBUG": bool},
    sources=["os", ".env"],
    required=["PORT"],
    strict=True,
)
app = FastAPI()

def get_settings() -> Env:
    return settings

@app.get("/health")
def health(config: Env = Depends(get_settings)) -> dict:
    return {"status": "ok", "debug": config.get("DEBUG", False)}
```

**Django:** put typed values into the existing `settings.py` module, which is how
[Django loads settings](https://docs.djangoproject.com/en/5.2/topics/settings/):

```python
# settings.py (alongside the rest of your Django settings)
from pathlib import Path
from typing import List
from smartenv import Env

BASE_DIR = Path(__file__).resolve().parent.parent
config = Env(
    {"SECRET_KEY": str, "DEBUG": bool, "ALLOWED_HOSTS": List[str]},
    sources=["os", str(BASE_DIR / ".env")],
    required=["SECRET_KEY"],
    strict=True,
)
SECRET_KEY = config.SECRET_KEY
DEBUG = config.get("DEBUG", False)
ALLOWED_HOSTS = config.get("ALLOWED_HOSTS", ["localhost"])
```

Frameworks are installed separately. These examples use ordinary Python integration;
smartenv does not require a framework plugin.

## Contributing

Fork the repository, clone your fork, and create a branch for the change:

```bash
git switch -c feat/my-change
python -m pip install -e ".[dev,yaml,toml,watch,pydantic]"
python -m black smartenv tests scripts
python -m ruff check .
python -m mypy smartenv tests scripts
python -m pytest tests/ -v --tb=short --cov=smartenv
```

Read `.clinerules` and `cline_todo.md`, keep Python 3.8 compatibility, and add focused
tests for behavior changes. Cloud tests use fake SDK clients and require no credentials.
Use conventional commit messages and open a pull request describing the change and
the checks you ran. CI covers Python 3.8 through 3.14 on Linux and Python 3.12 on Windows
and macOS, with formatting, lint, strict type checks, doctests, a 90% coverage floor,
and an isolated wheel installation check. See [CONTRIBUTING.md](CONTRIBUTING.md).

Release maintainers can follow [the release guide](docs/RELEASING.md). The tagged release
workflow runs CI and publishes verified distributions through PyPI Trusted Publishing;
it does not use a stored `PYPI_TOKEN`. A local build does not publish the package.

## License

MIT © 2026 smartenv contributors. See [LICENSE](LICENSE).
