# smartenv

[![PyPI: release pending](https://img.shields.io/badge/PyPI-release_pending-lightgrey)](#install)
![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI: workflow configured](https://img.shields.io/badge/CI-workflow_configured-blue)](.github/workflows/ci.yml)
[![Coverage: 92% local](https://img.shields.io/badge/coverage-92%25_local-brightgreen)](#contributing)

**One library to load, validate, and manage all your config — everywhere.**

Combine environment variables, local files, and cloud secrets in one explicit priority chain.
Declare your types once, catch configuration errors at startup, and access real Python values.
The core uses only the standard library; optional integrations load when you use them.

Version 0.1.0 is an initial release. The badges above describe the supplied release tooling;
they do not claim a completed PyPI publication or a passing hosted CI run.
The local release check passed 353 tests with 92% combined statement and branch coverage
on Python 3.12.14 (Windows); the CI matrix covers Python 3.8–3.12.

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
`aws_secrets`, `gcp_secrets`, and `azure_secrets`. For named dotenv variants such as
`.env.production`, pass `DotenvSource(".env.production")` directly. Source objects are
also accepted, making custom `BaseSource` subclasses straightforward to add.

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
string. Exceptions from validators become validation errors. Configuration and cast errors
may include raw values; keep exception reports out of public responses.

## Cloud Secrets

Install the matching extra and configure credentials using the provider SDK's normal
credential discovery. Cloud sources import their SDKs lazily and wrap provider failures
in `CloudAuthError`, including a useful install hint when an SDK is missing.

**AWS Secrets Manager** — a JSON object supplies schema keys; plain text uses `AWS_SECRET`:

```python
from smartenv import Env
from smartenv.sources import AwsSource

aws = AwsSource(secret_name="production/myapp", region="us-east-1")
env = Env({"DATABASE_URL": str}, sources=["os", aws],
          required=["DATABASE_URL"], strict=True)
```

With no explicit arguments, `AwsSource()` reads `AWS_SECRET_NAME` and `AWS_REGION`;
the region defaults to `us-east-1`.

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
There is no automatic cloud polling or cache expiry.

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

The daemon observer watches each file's parent directory and debounces repeated events
for 0.5 seconds. A reload reads all sources, validates and casts them, and updates the
configuration under a lock. The callback runs after a successful reload. Cloud caches
still apply. Use `env.close()` or the context manager to stop and join the watcher.
Without watchdog, `hot_reload=True` records a warning; check `env.warnings` and `env.watcher`.
If strict validation fails during a reload, the new values and validation errors remain
available, the watcher records a warning, and the callback is skipped. A failed validation
does not restore the previous configuration.

## CLI

The `smartenv` command is included in the base installation. A schema module defines a
`schema` dictionary, an optional `required` list, and optional `validators` mapping:

```python
# schema.py
schema = {"DATABASE_URL": str, "PORT": int}
required = ["DATABASE_URL"]
validators = {"PORT": lambda value: 1 <= value <= 65535}
```

Schema files run as Python code when loaded. Use schema modules you trust. Install the
`yaml` extra to include `config.yaml` in these examples.

**Validate** sources against the schema. All validation errors are listed; success exits
with status 0 and failure with status 1:

```console
$ smartenv validate --schema schema.py --sources .env config.yaml
✓ Validation passed
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

**List** all source values without needing a schema. Earlier sources win. For a file with
`PORT=8000`, `DEBUG=false`, and `API_KEY` set, representative output is:

```console
$ smartenv list --sources .env config.yaml
API_KEY=*****
DEBUG=false
PORT=8000
```

Any key containing `SECRET`, `KEY`, `TOKEN`, `PASSWORD`, `PASS`, or `CREDENTIAL`
(case-insensitive) is masked as `*****`. Values under other names are printed as-is.

**Check a source** using environment-based provider configuration and credentials:

```console
$ smartenv check-source --source aws_secrets
✓ Connected to aws_secrets
```

On a connection or loading error it prints `✗ Failed: ...` and exits with status 1.
Use `smartenv --help` or `python -m smartenv.cli --help` for command usage.

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
python -m black smartenv tests
python -m ruff check .
python -m mypy smartenv
python -m pytest tests/ -v --tb=short --cov=smartenv
```

Read `.clinerules` and `cline_todo.md`, keep Python 3.8 compatibility, and add focused
tests for behavior changes. Cloud tests use fake SDK clients and require no credentials.
Use conventional commit messages and open a pull request describing the change and
the checks you ran. CI runs lint, type checks, and tests on Python 3.8 through 3.12.

Release maintainers can build distributions with `python -m build`. The supplied publish
workflow uploads tagged `v*.*.*` releases with the repository's `PYPI_TOKEN` secret.

## License

MIT © 2026 smartenv contributors. See [LICENSE](LICENSE).
