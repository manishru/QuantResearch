#!/usr/bin/env python3
"""Write a SHA-256 manifest for the local data and report archive."""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    rows = []
    for directory in (root / "data", root / "reports"):
        for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.resolve() != output):
            rows.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": digest(path)})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader(); writer.writerows(rows)
    print(f"wrote {len(rows)} entries to {output}")


if __name__ == "__main__":
    main()
