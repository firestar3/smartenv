# Security policy

Security fixes target the latest 1.x release. Update to its latest patch before reporting
a problem. Compatibility with Python 3.8 does not extend the support lifetime of Python
itself or any optional cloud SDK; maintainers must choose supported runtimes and dependencies
for their deployment.

## Report a vulnerability

Use [GitHub's private vulnerability reporting page](https://github.com/firestar3/smartenv/security/advisories/new)
if private reporting is enabled for the repository. Include the affected version, a minimal
reproduction using dummy values, impact, and suggested mitigation. Do not include real
passwords, tokens, environment dumps, or production configuration.

If that page is unavailable, open a minimal public issue requesting a private contact
channel without disclosing the vulnerability or secrets. Private reporting availability
is a repository setting; this file does not assert that it is enabled. Response times
are not guaranteed.

## Configuration and logging boundaries

smartenv loads secrets into application memory. It does not encrypt configuration, rotate
credentials, enforce provider permissions, or prevent application code from exposing
values. Attribute access, item access, `get()`, and unredacted `dict()` / `json()` deliberately
return the actual values.

`repr(env)`, `env.dict(redact=True)`, `env.json(redact=True)`, CLI listing, and supported
cast/validator diagnostic messages use key-name matching. The case-insensitive markers are
`AUTH`, `CERT`, `CREDENTIAL`, `KEY`, `PASS`, `PRIVATE`, `SECRET`, and `TOKEN`. Python display
masks use `***`; CLI listings use `*****`.

This is a display aid with both false positives and false negatives. For example, a password
embedded in `DATABASE_URL` is not detected by its name. Nested dictionaries under an ordinary
key and values under custom names are not scanned for secrets. A sensitive top-level key
masks its entire value. Review output before logging or sharing it.

Structured exception fields such as `CastError.value` and `CastError.reason`, chained
exceptions in tracebacks, SDK errors, parser errors, and custom callback errors may contain
unmasked values. Custom casters and validators can also log whatever they receive. Avoid
returning exception objects, stack traces, or source contents in public application errors.

## Trust and lifecycle

- CLI schema files are executable Python. Load only files you trust.
- Grant cloud identities access only to the secrets needed by the application. Omitting
  GCP secret IDs or Azure secret names enables list-and-fetch behavior and needs list access.
- Cloud caching is per source instance. `cache_ttl` refreshes on the next load after expiry;
  it is not a rotation service or background poll. `cache_clear()` and `cache=False` provide
  explicit refresh control. SDK networking and retry policies still apply.
- A failed strict reload keeps the last valid in-memory configuration. That can include
  previously loaded credentials, so the application must decide when a stale configuration
  should cause readiness checks to fail or the process to exit.
- Keep `.env` files outside version control and deployment artifacts unless they contain
  only public examples. Avoid granting writable config paths to untrusted users.
- Tagged releases use PyPI Trusted Publishing from the configured GitHub `pypi` environment.
  Protect repository access and release tags; publishing permissions are release authority.

See [the release guide](docs/RELEASING.md) for the repository's publishing configuration.
