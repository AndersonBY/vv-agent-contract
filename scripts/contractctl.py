#!/usr/bin/env python3
"""Validate and package the language-neutral vv-agent contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_LINE_RE = re.compile(r"^([0-9a-f]{64})  (.+)$")
ALLOWED_ADOPTION_STATES = {"pending-adoption", "in-progress", "verified", "superseded"}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read valid JSON from {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture_files(fixtures: Path) -> list[Path]:
    return sorted(
        (path for path in fixtures.rglob("*") if path.is_file() and path.name != "SHA256SUMS"),
        key=lambda path: path.relative_to(fixtures).as_posix(),
    )


def expected_manifest_lines(fixtures: Path) -> list[str]:
    return [f"{sha256_file(path)}  {path.relative_to(fixtures).as_posix()}" for path in fixture_files(fixtures)]


def parse_manifest(fixtures: Path) -> dict[str, str]:
    manifest_path = fixtures / "SHA256SUMS"
    if not manifest_path.is_file():
        raise ContractError(f"missing fixture manifest: {manifest_path}")

    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    if lines != sorted(lines, key=lambda line: line.split("  ", 1)[-1]):
        raise ContractError("fixtures/SHA256SUMS must be sorted by relative path")

    entries: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = MANIFEST_LINE_RE.fullmatch(line)
        if match is None:
            raise ContractError(f"invalid SHA256SUMS line {line_number}: {line!r}")
        digest, relative = match.groups()
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or "\\" in relative:
            raise ContractError(f"unsafe fixture path in SHA256SUMS: {relative}")
        if relative == "SHA256SUMS" or relative in entries:
            raise ContractError(f"duplicate or self-referential fixture path: {relative}")
        entries[relative] = digest

    actual = {path.relative_to(fixtures).as_posix() for path in fixture_files(fixtures)}
    declared = set(entries)
    if actual != declared:
        missing = sorted(actual - declared)
        stale = sorted(declared - actual)
        raise ContractError(f"fixture manifest coverage mismatch: missing={missing}, stale={stale}")

    for relative, expected_digest in entries.items():
        actual_digest = sha256_file(fixtures / relative)
        if actual_digest != expected_digest:
            raise ContractError(
                f"fixture digest mismatch for {relative}: expected {expected_digest}, got {actual_digest}"
            )
    return entries


def validate_fixture_syntax(fixtures: Path, intentional_invalid: Any) -> None:
    if not isinstance(intentional_invalid, dict):
        raise ContractError("fixtures.intentional_invalid_jsonl_records must be an object")
    allowed_invalid: dict[str, set[int]] = {}
    for relative, line_numbers in intentional_invalid.items():
        if not isinstance(relative, str) or not isinstance(line_numbers, list):
            raise ContractError("intentional invalid JSONL records must map paths to line-number arrays")
        if not all(isinstance(line_number, int) and line_number > 0 for line_number in line_numbers):
            raise ContractError(f"invalid intentional JSONL line list for {relative}")
        allowed_invalid[relative] = set(line_numbers)
    observed_invalid: dict[str, set[int]] = {}
    for path in fixture_files(fixtures):
        suffix = path.suffix.lower()
        if suffix == ".json":
            load_json(path)
        elif suffix == ".jsonl":
            relative = path.relative_to(fixtures).as_posix()
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    raise ContractError(f"blank JSONL record in {path}:{line_number}")
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    if line_number not in allowed_invalid.get(relative, set()):
                        raise ContractError(f"invalid JSONL record in {path}:{line_number}: {exc}") from exc
                    observed_invalid.setdefault(relative, set()).add(line_number)
    if observed_invalid != allowed_invalid:
        raise ContractError(
            "intentional invalid JSONL declaration does not match observed records: "
            f"declared={allowed_invalid}, observed={observed_invalid}"
        )


def validate_contract(root: Path) -> dict[str, Any]:
    root = root.resolve()
    contract = load_json(root / "contract.json")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ContractError("contract.json must be a schema_version=1 object")
    if contract.get("name") != "vv-agent-contract":
        raise ContractError("contract.json name must be vv-agent-contract")
    version = contract.get("version")
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise ContractError(f"invalid contract version: {version!r}")
    repository = contract.get("repository")
    if not isinstance(repository, str) or not repository.startswith("https://github.com/"):
        raise ContractError("contract repository must be an HTTPS GitHub URL")

    fixture_config = contract.get("fixtures")
    if not isinstance(fixture_config, dict):
        raise ContractError("contract.json fixtures must be an object")
    fixture_path = fixture_config.get("path")
    if fixture_path != "fixtures" or fixture_config.get("manifest") != "fixtures/SHA256SUMS":
        raise ContractError("canonical fixture paths must remain fixtures/ and fixtures/SHA256SUMS")
    fixtures = root / fixture_path
    entries = parse_manifest(fixtures)
    validate_fixture_syntax(fixtures, fixture_config.get("intentional_invalid_jsonl_records", {}))
    manifest_digest = sha256_file(fixtures / "SHA256SUMS")
    if fixture_config.get("manifest_sha256") != manifest_digest:
        raise ContractError(
            "contract.json fixture manifest digest does not match fixtures/SHA256SUMS; "
            "run contractctl.py manifest"
        )

    domains = contract.get("domains")
    if not isinstance(domains, list) or len(domains) != 19 or len(set(domains)) != len(domains):
        raise ContractError("contract.json must list 19 unique domain ids")
    if not all(isinstance(domain, str) and domain for domain in domains):
        raise ContractError("contract domain ids must be non-empty strings")

    matrix = load_json(root / "support-matrix.json")
    if not isinstance(matrix, dict) or matrix.get("schema_version") != 1:
        raise ContractError("support-matrix.json must be a schema_version=1 object")
    if matrix.get("contract_version") != version:
        raise ContractError("support matrix contract_version must match contract.json")
    if matrix.get("status") not in ALLOWED_ADOPTION_STATES:
        raise ContractError(f"invalid support matrix status: {matrix.get('status')!r}")
    implementations = matrix.get("implementations")
    if not isinstance(implementations, dict) or set(implementations) != {"python", "rust"}:
        raise ContractError("support matrix must contain exactly python and rust implementations")
    for language, implementation in implementations.items():
        if not isinstance(implementation, dict):
            raise ContractError(f"support matrix {language} entry must be an object")
        if implementation.get("status") not in ALLOWED_ADOPTION_STATES:
            raise ContractError(f"invalid {language} adoption status: {implementation.get('status')!r}")
    if matrix["status"] == "verified":
        for language, implementation in implementations.items():
            revision = implementation.get("verified_revision")
            if implementation.get("status") != "verified" or not isinstance(revision, str):
                raise ContractError(f"verified support matrix requires a verified {language} revision")
            if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
                raise ContractError(f"verified {language} revision must be a full Git commit")
        if not isinstance(matrix.get("last_verified_at"), str) or not matrix["last_verified_at"]:
            raise ContractError("verified support matrix requires last_verified_at")
        run_url = matrix.get("cross_repository_run")
        if not isinstance(run_url, str) or not run_url.startswith("https://github.com/"):
            raise ContractError("verified support matrix requires a GitHub cross_repository_run URL")

    required_docs = [
        root / "README.md",
        root / "README_ZH.md",
        root / "CHANGELOG.md",
        root / "docs" / "parity-contract.md",
        root / "docs" / "change-workflow.md",
        root / "docs" / "compatibility-policy.md",
        root / "docs" / "run-budgets.md",
        root / "docs" / "checkpoint-resume.md",
    ]
    missing_docs = [str(path.relative_to(root)) for path in required_docs if not path.is_file()]
    if missing_docs:
        raise ContractError(f"missing contract documentation: {missing_docs}")

    return {
        "version": version,
        "domains": len(domains),
        "fixture_files": len(entries) + 1,
        "manifest_entries": len(entries),
        "manifest_sha256": manifest_digest,
        "adoption_status": matrix["status"],
    }


def rebuild_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    contract_path = root / "contract.json"
    contract = load_json(contract_path)
    fixtures = root / "fixtures"
    lines = expected_manifest_lines(fixtures)
    (fixtures / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    contract.setdefault("fixtures", {})["manifest_sha256"] = sha256_file(fixtures / "SHA256SUMS")
    write_json(contract_path, contract)
    return {
        "manifest_entries": len(lines),
        "manifest_sha256": contract["fixtures"]["manifest_sha256"],
    }


def bundle_paths(root: Path) -> list[Path]:
    fixed = [root / "contract.json", root / "CHANGELOG.md", root / "README.md", root / "README_ZH.md"]
    generated = [
        path
        for directory in (root / "docs", root / "fixtures")
        for path in directory.rglob("*")
        if path.is_file()
    ]
    return sorted(fixed + generated, key=lambda path: path.relative_to(root).as_posix())


def build_bundle(root: Path, output_dir: Path, revision: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    report = validate_contract(root)
    contract = load_json(root / "contract.json")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = f"vv-agent-contract-{report['version']}.zip"
    artifact_path = output_dir / artifact_name
    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in bundle_paths(root):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    artifact_digest = sha256_file(artifact_path)
    checksum_path = output_dir / f"{artifact_name}.sha256"
    checksum_path.write_text(f"{artifact_digest}  {artifact_name}\n", encoding="ascii")

    metadata_path = None
    if revision is not None:
        if SHA256_RE.fullmatch(revision) is None and re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ContractError("release revision must be a full hexadecimal Git commit")
        metadata = {
            "schema_version": 1,
            "contract_version": report["version"],
            "contract_revision": revision,
            "source_repository": contract["repository"],
            "artifact_name": artifact_name,
            "artifact_url": f"{contract['repository']}/releases/download/v{report['version']}/{artifact_name}",
            "artifact_sha256": artifact_digest,
            "fixture_manifest_sha256": report["manifest_sha256"],
        }
        metadata_path = output_dir / f"vv-agent-contract-{report['version']}.release.json"
        write_json(metadata_path, metadata)

    return {
        **report,
        "artifact": str(artifact_path),
        "artifact_sha256": artifact_digest,
        "checksum": str(checksum_path),
        "release_metadata": str(metadata_path) if metadata_path is not None else None,
    }


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description=__doc__)
    command_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = command_parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate metadata, fixtures, and documentation")
    subparsers.add_parser("manifest", help="rebuild SHA256SUMS and update contract.json")
    build = subparsers.add_parser("build", help="build a deterministic release bundle")
    build.add_argument("--output-dir", type=Path, default=Path("dist"))
    build.add_argument("--revision", help="full Git revision for release metadata")
    return command_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            report = validate_contract(args.root)
        elif args.command == "manifest":
            report = rebuild_manifest(args.root)
            validate_contract(args.root)
        else:
            report = build_bundle(args.root, args.output_dir, revision=args.revision)
    except ContractError as exc:
        print(f"contract error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
