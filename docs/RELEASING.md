# Releasing smartenv to GitHub and PyPI

The prepared release is **1.0.0**. A commit, local distribution build, or GitHub repository
does not publish a package to PyPI. This repository publishes when a `v*.*.*` tag is pushed
and the verification and publishing jobs succeed.

The examples below use the existing Windows checkout and virtual environment. On other
machines, replace `.\.venv\Scripts\python.exe` with your environment's Python interpreter.

The PyPI distribution name is **`smartenv-config`** because PyPI rejected `smartenv`
as too similar to an existing project. The GitHub repository, Python import package
and CLI command remain `smartenv`. An absent PyPI project page does not guarantee
that a name will pass its registration rules.

## 1. Verify the release locally

`smartenv/_version.py` is the version source for runtime and package metadata. Update it
and `CHANGELOG.md` together for future releases. Use a separate output directory for each
release so old archives cannot be uploaded accidentally.

```powershell
cd C:\Users\aarav\smartenv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,yaml,toml,watch,pydantic]"
.\.venv\Scripts\python.exe -m black --check smartenv tests scripts
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy smartenv tests scripts
.\.venv\Scripts\python.exe -m pytest tests/ -v --tb=short --cov=smartenv
.\.venv\Scripts\python.exe -m pytest --doctest-modules smartenv -q
.\.venv\Scripts\python.exe -m build --outdir dist/smartenv-config/1.0.0
.\.venv\Scripts\python.exe -m twine check --strict dist/smartenv-config/1.0.0/*
.\.venv\Scripts\python.exe scripts/check_release.py --dist-dir dist/smartenv-config/1.0.0 --tag v1.0.0
.\.venv\Scripts\python.exe scripts/smoke_wheel.py --dist-dir dist/smartenv-config/1.0.0 --work-dir .venv
```

## 2. Push the implementation to GitHub

The existing remote should be `https://github.com/firestar3/smartenv.git`. Check the
current branch, remote, and staged changes before committing:

```powershell
cd C:\Users\aarav\smartenv
git status
git remote -v
git branch --show-current
git add .
git diff --cached --stat
git commit -m "feat: prepare smartenv 1.0.0"
git push origin main
```

These commands assume you are on `main`. If you work on another branch, push that branch
and merge its pull request into `main` before tagging. Git can use its saved credential
manager login; GitHub authentication is separate from the PyPI account created below.

Wait for the latest commit on the [GitHub Actions page](https://github.com/firestar3/smartenv/actions)
to pass. CI checks Linux on Python 3.8–3.14, Windows and macOS on Python 3.12, code quality,
coverage, doctests, package metadata, and installation of the built wheel without runtime
dependencies. Hosted results are authoritative for those matrix platforms.

## 3. Configure PyPI Trusted Publishing once

Create or sign in to your [PyPI account](https://pypi.org/account/register/), verify your
email, and enable two-factor authentication. Save its recovery codes privately.
[PyPI account documentation](https://pypi.org/help/#twofa) explains the available methods.

In [the repository's environment settings](https://github.com/firestar3/smartenv/settings/environments),
create an environment named exactly **`pypi`**. If you configure approval or deployment-tag
rules, allow the release tag and approve the job when GitHub requests it.

For a first release, open [PyPI account → Publishing](https://pypi.org/manage/account/publishing/)
and add a pending GitHub publisher with these exact values:

| Field | Value |
| --- | --- |
| PyPI project name | `smartenv-config` |
| Owner | `firestar3` |
| Repository name | `smartenv` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

The first successful publication creates the project. A pending publisher does not reserve
the name. If `smartenv-config` is already a project you own, add the publisher in that project's
Publishing settings instead. If another account owns the name, choose an available package
name and update the metadata and release configuration before proceeding.
[PyPI's new-project guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
describes this setup.

The workflow uses GitHub's identity with job-scoped `id-token: write`; no PyPI password or
API token belongs in repository secrets for this flow. The workflow filename and environment
must match the publisher registration.
[PyPI's publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
explains the authentication.

## 4. Publish version 1.0.0

After the `main` commit passes CI and the publisher is configured:

```powershell
git switch main
git pull --ff-only origin main
git status
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

Make sure `git status` is clean and `main` contains the intended release before creating
the tag. **Pushing this tag is the publication trigger.** The publish workflow reruns CI
on the tagged commit, verifies that the tag and distribution version match, and uploads
the validated artifacts with publication attestations. It does not rebuild a different
package in the upload job.

Watch [Publish to PyPI](https://github.com/firestar3/smartenv/actions/workflows/publish.yml).
If your GitHub environment requires approval, approve its waiting deployment. A failed
verification or publishing job means the release has not completed; inspect that job's
logs rather than assuming that creating the tag was sufficient.

## 5. Verify the published package

Confirm the version and project links on [smartenv's PyPI page](https://pypi.org/project/smartenv-config/).
Use a fresh environment with isolated imports for the final installation check:

```powershell
.\.venv\Scripts\python.exe -m venv .venv\pypi-check-1.0.0
.\.venv\pypi-check-1.0.0\Scripts\python.exe -m pip install --index-url https://pypi.org/simple "smartenv-config==1.0.0"
.\.venv\pypi-check-1.0.0\Scripts\python.exe -I -c "import smartenv; print(smartenv.__version__)"
.\.venv\pypi-check-1.0.0\Scripts\python.exe -I -m smartenv --version
```

The isolated interpreter flag prevents imports from this checkout from masking a packaging
problem. Once publication succeeds, other users can run:

```bash
python -m pip install smartenv-config
python -m pip install "smartenv-config[aws,yaml]"
```

Optionally create a GitHub Release for `v1.0.0` and copy the corresponding changelog section.
That release page is for release notes; the tag push already triggered PyPI publication.

## Future releases and recovery

Bump the version, update the changelog, verify, push the commit, then push the matching tag.
Use a fresh version for changed release files. If publishing fails, first check the exact
owner, repository, workflow filename, environment, and PyPI project registration. A check
that found no project before release does not guarantee that the name is still available.
See [PyPI's troubleshooting guide](https://docs.pypi.org/trusted-publishers/troubleshooting/)
for identity errors. Keep earlier local builds separate from the new release's directory.
