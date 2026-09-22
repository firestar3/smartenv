"""Install and exercise a built wheel in a fresh environment without extras."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Install the wheel without dependencies and exercise its entry points.

    Args:
        argv: Optional CLI argument sequence.

    Returns:
        Zero after the isolated wheel checks pass.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args(argv)
    wheels = list(args.dist_dir.resolve().glob("*.whl"))
    if len(wheels) != 1:
        parser.error("the distribution directory must contain exactly one wheel")
    with tempfile.TemporaryDirectory(dir=args.work_dir) as temporary:
        root = Path(temporary).resolve()
        environment = root / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = [str(python), "-I"]
        subprocess.run(
            command + ["-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])],
            cwd=root,
            check=True,
        )
        subprocess.run(
            command
            + [
                "-c",
                "from smartenv import Env, __version__; "
                "env = Env({'PORT': int}, sources=[], defaults={'PORT': '8080'}, strict=True); "
                "assert env.PORT == 8080; assert env.get_source('PORT') == 'defaults'; "
                "print('Installed wheel', __version__, 'works without extras')",
            ],
            cwd=root,
            check=True,
        )
        subprocess.run(command + ["-m", "smartenv", "--version"], cwd=root, check=True)
        cli = environment / ("Scripts/smartenv.exe" if os.name == "nt" else "bin/smartenv")
        subprocess.run([str(cli), "check-source", "--source", "os"], cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
