"""Check distribution contents, version agreement and optional-only dependencies."""

from __future__ import annotations

import argparse
import email
import os
import runpy
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Validate archives and, on tag builds, the requested version.

    Args:
        argv: Optional CLI argument sequence.

    Returns:
        Zero when every release invariant is satisfied.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--tag")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    version = runpy.run_path(str(root / "smartenv" / "_version.py"))["__version__"]
    tag = args.tag
    if tag is None and os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
        tag = os.environ.get("GITHUB_REF_NAME")
    if tag is not None and tag != f"v{version}":
        parser.error(f"tag {tag!r} does not match package version v{version}")
    wheels = list(args.dist_dir.glob("*.whl"))
    sdists = list(args.dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser.error("the distribution directory must contain exactly one wheel and one sdist")
    expected = f"smartenv_config-{version}"
    assert wheels[0].name == f"{expected}-py3-none-any.whl", "Unexpected wheel name"
    assert sdists[0].name == f"{expected}.tar.gz", "Unexpected source archive name"
    with zipfile.ZipFile(wheels[0]) as wheel:
        metadata = email.message_from_bytes(wheel.read(f"{expected}.dist-info/METADATA"))
        assert metadata["Name"] == "smartenv-config"
        assert metadata["Version"] == version
        assert metadata["Description-Content-Type"] == "text/markdown"
        assert all(
            "extra ==" in value for value in metadata.get_all("Requires-Dist", [])
        ), "The core must not acquire mandatory runtime dependencies"
        assert "smartenv/py.typed" in wheel.namelist()
        assert any(name.endswith("/LICENSE") for name in wheel.namelist())
        entry_points = wheel.read(f"{expected}.dist-info/entry_points.txt").decode("utf-8")
        assert "smartenv = smartenv.cli:main" in entry_points
    with tarfile.open(sdists[0]) as sdist:
        names = set(sdist.getnames())
        for path in ("pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", "smartenv/py.typed"):
            assert f"{expected}/{path}" in names, f"Missing source archive member: {path}"
        assert not any("/.venv/" in name or name.endswith("/.env") for name in names)
    print(f"Release {version}: wheel, source archive, metadata and tag checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
