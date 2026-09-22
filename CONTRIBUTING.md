# Contributing to smartenv

Fork [firestar3/smartenv](https://github.com/firestar3/smartenv), clone your fork, and create
a focused branch. Report bugs with a minimal reproduction, expected behavior, Python
version, and operating system. Replace credentials and production values with examples.
For vulnerabilities, follow [SECURITY.md](SECURITY.md).

## Set up a development environment

These commands work with a Python interpreter available as `python`:

```bash
git switch -c fix/describe-the-change
python -m venv .venv
```

On Windows PowerShell, use the interpreter directly; activation is optional:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,yaml,toml,watch,pydantic]"
```

On Linux or macOS:

```bash
.venv/bin/python -m pip install -e ".[dev,yaml,toml,watch,pydantic]"
```

The remaining examples use `python` from the virtual environment. In PowerShell, substitute
`.\.venv\Scripts\python.exe` if you have not activated it. Cloud unit tests supply fake SDK
clients and do not need cloud credentials or network access.

## Make and verify the change

Read [.clinerules](.clinerules) and [cline_todo.md](cline_todo.md). Keep the core free of
mandatory runtime dependencies, optional imports lazy, file reads and writes explicitly
UTF-8, and every public API documented and type annotated. Preserve Python 3.8 syntax.
Add focused regression tests for changed behavior, including failure paths where relevant.

```bash
python -m black smartenv tests scripts
python -m ruff check .
python -m mypy smartenv tests scripts
python -m pytest tests/ -v --tb=short --cov=smartenv
python -m pytest --doctest-modules smartenv -q
python -c "from smartenv import Env; print('OK')"
```

CI runs these checks across Python 3.8–3.14 on Linux, with additional Windows and macOS
jobs on Python 3.12. The coverage minimum is 90%. The quality job runs on Python 3.12;
all matrix jobs run the tests and doctests. Dependency resolution selects compatible
versions on older interpreters.

Build and inspect the package when changing metadata, exports, dependency declarations,
or release tooling:

```bash
python -m build --outdir dist/1.0.0
python -m twine check --strict dist/1.0.0/*
python scripts/check_release.py --dist-dir dist/1.0.0
python scripts/smoke_wheel.py --dist-dir dist/1.0.0 --work-dir .venv
```

The smoke check creates an isolated environment and verifies installation of the wheel
without runtime dependencies. Keep local credentials, virtual environments, and build
outputs out of commits.

## Open a pull request

Use a conventional commit message such as `fix: preserve final file edits during reload`.
Describe the problem, final behavior, and verification in the pull request. Update the
README and changelog for user-visible changes, and include migration guidance for
intentional behavior changes. Public 1.x APIs should retain compatibility in patch and
minor updates; discuss changes that require a new major version before implementing them.

The maintainer release procedure is in [docs/RELEASING.md](docs/RELEASING.md).
