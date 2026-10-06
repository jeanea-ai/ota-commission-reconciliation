#!/usr/bin/env python3
"""Build or verify the marketplace source manifest."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


EXCLUDED_FILES = {"BUILD.json", "SOURCE-MANIFEST.sha256"}
EXCLUDED_PARTS = {".git", "__pycache__", ".clawhub", "tmp"}


def included(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.name not in EXCLUDED_FILES
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts)
        and path.suffix not in {".pyc", ".pyo"}
    )


def records(root: Path) -> list[str]:
    return [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}"
        for path in included(root)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = root / "SOURCE-MANIFEST.sha256"
    expected = "\n".join(records(root)) + "\n"
    if args.verify:
        if not manifest.is_file() or manifest.read_text(encoding="utf-8") != expected:
            print("source manifest mismatch")
            return 2
        print(f"source manifest verified: {len(records(root))} files")
        return 0
    manifest.write_text(expected, encoding="utf-8", newline="\n")
    print(f"source manifest written: {len(records(root))} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

