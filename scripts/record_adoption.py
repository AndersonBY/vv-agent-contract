#!/usr/bin/env python3
"""Record a successful vv-agent cross-repository conformance run."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def record_adoption(
    root: Path,
    python_revision: str,
    rust_revision: str,
    run_url: str,
    verified_at: str | None = None,
) -> dict[str, Any]:
    for name, revision in (("python", python_revision), ("rust", rust_revision)):
        if REVISION_RE.fullmatch(revision) is None:
            raise ValueError(f"{name} revision must be a full hexadecimal Git commit")
    if not run_url.startswith("https://github.com/"):
        raise ValueError("cross-repository run URL must be a GitHub HTTPS URL")

    contract = load_json(root / "contract.json")
    matrix_path = root / "support-matrix.json"
    matrix = load_json(matrix_path)
    if matrix.get("contract_version") != contract.get("version"):
        raise ValueError("support matrix version does not match contract.json")

    timestamp = verified_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    matrix["status"] = "verified"
    matrix["last_verified_at"] = timestamp
    matrix["cross_repository_run"] = run_url
    matrix["implementations"]["python"]["status"] = "verified"
    matrix["implementations"]["python"]["verified_revision"] = python_revision
    matrix["implementations"]["rust"]["status"] = "verified"
    matrix["implementations"]["rust"]["verified_revision"] = rust_revision
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--python-revision", required=True)
    parser.add_argument("--rust-revision", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--verified-at")
    args = parser.parse_args()
    matrix = record_adoption(
        args.root.resolve(),
        args.python_revision,
        args.rust_revision,
        args.run_url,
        verified_at=args.verified_at,
    )
    print(json.dumps(matrix, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
