# Migrating from 0.1 to 1.0

The source priority model, zero-dependency core, Python 3.8 compatibility, and existing
cloud source names remain available. This guide covers intentional behavior changes that
can affect existing applications.

## Strict reloads keep the last good state

In 0.1, a failed strict reload could publish invalid values and replace the validation
report before raising. In 1.0, loading and validation finish before a snapshot is committed.
Strict validation failures and source loading failures preserve the previous values,
provenance, errors, and warnings. Inspect the raised exception for the rejected report:

```python
from smartenv import ValidationError

try:
    env.reload()
except ValidationError as rejected:
    report_errors(rejected.errors)  # Application-defined reporting function.
    # env still contains the last successfully loaded configuration.
```

The watcher adds its own warning when a reload fails and does not call the success callback.
A subsequent valid edit can recover. Non-strict validation still publishes its latest
values and validation report. Source errors always raise. Callback errors happen after a
successful update and do not undo it.

## Reload waits for the save to settle

File events are now coalesced until 0.5 seconds have passed without another matching event.
Code should not expect an immediate callback on the first write. Reload callbacks run on
one background worker and must be thread-safe. `close()` cancels pending work and waits
for an active reload; a callback can close its own environment without a deadlock.

## Missing-key exceptions follow Python conventions

`MissingKeyError` remains a `SmartEnvError` and now also inherits from `AttributeError`
and `KeyError`. `hasattr(env, "MISSING")` returns `False`; `getattr(env, "MISSING", default)`
returns the default. Existing `except MissingKeyError` handlers still work, but broader
`except AttributeError` or `except KeyError` blocks now also catch it.

## Returned containers are isolated

Builtin container values are deep-copied on access and export. Mutating a returned list
or dictionary no longer modifies the active configuration. Change its source or reconstruct
the `Env`, then reload as appropriate. Custom objects returned by user casters are not
reconstructed and should be treated as immutable.

Each declared value is now cast once per refresh, then passed to its validator and stored.
Custom casters should not depend on the previous duplicate invocation or mutate external
state. Separate attribute reads can still span a reload; use one `env.dict()` snapshot
when reading related values together.

## Sensitive diagnostics reveal less detail

Sensitive key names use the same matching rules across Python representations, CLI listing,
and cast/validator display errors. Secret values and validator details may now be replaced
by masks or generic messages. Prefer structured exception types and fields over matching
the full error string, but do not log raw attributes or chained exceptions indiscriminately.
See [SECURITY.md](../SECURITY.md) for the exact scope and limitations.

## GCP plaintext secret names in fetch-all mode

When neither `secret_id` nor `GCP_SECRET_ID` is provided, GCP loads all listed secrets.
Previously, multiple plaintext payloads competed for the same `SECRET` key. They now use
their uppercased secret IDs, so a secret named `api_token` resolves as `API_TOKEN`.
Loading one explicit secret still uses `SECRET` for a plaintext payload. JSON payloads
still merge their flattened keys; choose non-overlapping keys or explicit secret IDs.

## CLI output files and publishing

`generate-example` refuses to overwrite an existing destination. Use `--force` when that
replacement is intentional. `validate` and `list` now support `--format json`, and
`python -m smartenv` is equivalent to the console command.
CLI schema modules may define `defaults = {"PORT": 8000}`; these keys must be declared
in `schema`, and source values take priority.

The publish workflow now uses PyPI Trusted Publishing with a GitHub environment named
`pypi`. An old `PYPI_TOKEN` repository secret is not used by this workflow. Follow
[RELEASING.md](RELEASING.md) before pushing a release tag.

## New options you can adopt independently

- `defaults={...}` supplies typed and validated fallback values after all source values.
- `get_source(key)` reports which source supplied a resolved value, or `"defaults"`.
- `dict(redact=True)` and `json(redact=True)` provide key-based masked exports.
- `cache_ttl=300` expires a cloud source cache after five minutes; the next load refreshes it.
- `Path(".env.production")` and the string `".env.production"` can be passed directly as sources.

The default cloud cache remains indefinite. Set a TTL, disable caching, or explicitly clear
it if an application needs to observe secret rotation during its lifetime.
