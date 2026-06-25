#!/usr/bin/env python3
"""Create/update the shared qwen-asr environment for Rimagination note skills."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SHARED_CACHE = Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes")).expanduser()
SHARED_VENV = SHARED_CACHE / "qwen3-asr-venv"
LEGACY_VENVS = (
    Path.home() / ".cache" / "dy-note" / "qwen3-asr-venv",
    Path.home() / ".cache" / "douyin-note" / "qwen3-asr-venv",
)


def default_venv() -> Path:
    if SHARED_VENV.exists():
        return SHARED_VENV
    for legacy in LEGACY_VENVS:
        if legacy.exists():
            return legacy
    return SHARED_VENV


def run(cmd: list[str], dry_run: bool) -> None:
    print(" ".join(str(part) for part in cmd))
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def venv_python(venv: Path) -> Path:
    candidate = venv / "Scripts" / "python.exe"
    if candidate.exists() or sys.platform == "win32":
        return candidate
    return venv / "bin" / "python"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up shared qwen-asr for Bili Note and DyNote.")
    parser.add_argument("--venv", type=Path, default=default_venv())
    parser.add_argument("--python", default=sys.executable, help="Python executable used to create the venv.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    args.venv.parent.mkdir(parents=True, exist_ok=True)
    if not venv_python(args.venv).exists():
        run([args.python, "-m", "venv", "--system-site-packages", str(args.venv)], args.dry_run)
    py = venv_python(args.venv)
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], args.dry_run)
    run([str(py), "-m", "pip", "install", "qwen-asr", "accelerate", "qwen-omni-utils", "pandas>=2.3"], args.dry_run)
    if not args.dry_run:
        probe = "import torch, qwen_asr; print(torch.__version__, torch.cuda.is_available()); print(qwen_asr.__file__)"
        run([str(py), "-c", probe], args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
