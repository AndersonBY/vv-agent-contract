from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "clients")]
import contractctl  # noqa: E402
import contract_snapshot  # noqa: E402
import record_adoption  # noqa: E402


class SupportMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = contractctl.load_json(ROOT / "support-matrix.json")
        self.matrix["status"] = "verified"
        self.matrix["implementations"]["python"].update(status="verified", verified_revision="a" * 40)

    def test_current_python_adoption_is_pending_with_frozen_rust(self) -> None:
        matrix = contractctl.load_json(ROOT / "support-matrix.json")
        self.assertEqual(matrix["contract_version"], "24.0.0")
        self.assertEqual(matrix["status"], "pending-adoption")
        self.assertEqual(matrix["required_implementations"], ["python"])
        self.assertEqual(matrix["implementations"]["python"]["status"], "pending-adoption")
        self.assertIsNone(matrix["implementations"]["python"]["verified_revision"])
        rust = matrix["implementations"]["rust"]
        self.assertEqual((rust["contract_version"], rust["package_series"], rust["status"]),
                         ("23.0.0", "0.21.x", "frozen"))
        self.assertEqual(rust["verified_revision"], "00f4240786f1adea1dc0c4730da8ddd06a5ab8ac")
        contractctl.validate_support_matrix(matrix, "24.0.0")

    def test_future_python_adoption_preserves_entire_frozen_record(self) -> None:
        frozen = copy.deepcopy(self.matrix["implementations"]["rust"])
        self.matrix.update(contract_version="24.0.0", status="pending-adoption")
        self.matrix["implementations"]["python"].update(
            contract_version="24.0.0", status="pending-adoption", verified_revision=None,
        )
        contractctl.validate_support_matrix(self.matrix, "24.0.0")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contractctl.write_json(root / "contract.json", {"version": "24.0.0"})
            contractctl.write_json(root / "support-matrix.json", self.matrix)
            recorded = record_adoption.record_adoption(
                root, "a" * 40, "https://github.com/AndersonBY/vv-agent-contract/actions/runs/123",
            )
            self.assertEqual(recorded["status"], "verified")
            self.assertEqual(recorded["implementations"]["rust"], frozen)
            self.assertEqual(recorded["implementations"]["python"]["verified_revision"], "a" * 40)
            contractctl.validate_support_matrix(recorded, "24.0.0")

    def test_only_required_implementations_must_be_verified(self) -> None:
        self.matrix["implementations"]["rust"].update(status="in-progress", contract_version="24.0.0", verified_revision=None)
        contractctl.validate_support_matrix(self.matrix, "24.0.0")
        self.matrix["required_implementations"].append("rust")
        with self.assertRaisesRegex(contractctl.ContractError, "verified rust"):
            contractctl.validate_support_matrix(self.matrix, "24.0.0")

    def test_invalid_matrix_boundaries_are_rejected(self) -> None:
        mutations = [
            ((), "schema_version", value) for value in (None, 1, 3, "2", True, 2.0, [])
        ] + [
            ((), "required_implementations", value)
            for value in (None, [], "python", ["python", "python"], ["go"], [{}], ["python", "rust"])
        ] + [
            ((), "unexpected", True),
            ((), "status", "frozen"),
            ((), "status", []),
            (("implementations", "rust"), "contract_version", None),
            (("implementations", "rust"), "contract_version", "latest"),
            (("implementations", "rust"), "package_series", None),
            (("implementations", "rust"), "package_series", "0.21.2"),
            (("implementations", "rust"), "verified_revision", None),
            (("implementations", "rust"), "verified_revision", "00f4240"),
            (("implementations", "rust"), "status", []),
            (("implementations", "rust"), "unexpected", True),
            (("implementations", "python"), "contract_version", "25.0.0"),
            (("implementations", "python"), "status", "in-progress"),
        ]
        for path, key, value in mutations:
            with self.subTest(path=path, key=key, value=value):
                matrix = copy.deepcopy(self.matrix)
                target = matrix
                for part in path:
                    target = target[part]
                target[key] = value
                with self.assertRaises(contractctl.ContractError):
                    contractctl.validate_support_matrix(matrix, "24.0.0")
        for path, key in (((), "schema_version"), ((), "required_implementations"),
                          (("implementations", "rust"), "contract_version")):
            matrix = copy.deepcopy(self.matrix)
            target = matrix
            for part in path:
                target = target[part]
            del target[key]
            with self.assertRaises(contractctl.ContractError):
                contractctl.validate_support_matrix(matrix, "24.0.0")

    def test_recording_invalid_matrix_never_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contractctl.write_json(root / "contract.json", {"version": "24.0.0"})
            for field, value in (("schema_version", 1), ("required_implementations", ["rust"])):
                matrix = copy.deepcopy(self.matrix)
                matrix[field] = value
                path = root / "support-matrix.json"
                contractctl.write_json(path, matrix)
                before = path.read_bytes()
                with self.assertRaises((contractctl.ContractError, ValueError)):
                    record_adoption.record_adoption(root, "a" * 40, "https://github.com/test/run/1")
                self.assertEqual(path.read_bytes(), before)

    def test_adoption_reader_never_reports_newer_contract_for_frozen_rust(self) -> None:
        self.matrix.update(contract_version="24.0.0", status="pending-adoption")
        self.matrix["implementations"]["python"].update(
            contract_version="24.0.0", status="pending-adoption", verified_revision=None,
        )
        lock = {
            "schema_version": 1, "contract_version": "23.0.0", "contract_revision": "a" * 40,
            "source_repository": "https://github.com/AndersonBY/vv-agent-contract",
            "artifact_url": "https://example.invalid/v23.zip", "artifact_sha256": "b" * 64,
            "snapshot_path": "fixtures", "fixture_manifest_sha256": "c" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "support-matrix.json"
            contractctl.write_json(path, self.matrix)
            contractctl.write_json(root / "contract.lock.json", lock)
            report = contract_snapshot.verify_adoption(root, "contract.lock.json", "rust", str(path))
            self.assertEqual(report["contract_version"], "23.0.0")
            self.assertEqual(report["status"], "frozen")
            self.assertIsNone(report["cross_repository_run"])
            lock["contract_version"] = "24.0.0"
            contractctl.write_json(root / "contract.lock.json", lock)
            with self.assertRaisesRegex(contract_snapshot.SnapshotError, "pinned version"):
                contract_snapshot.verify_adoption(root, "contract.lock.json", "rust", str(path))
            self.matrix["schema_version"] = 1
            contractctl.write_json(path, self.matrix)
            with self.assertRaisesRegex(contract_snapshot.SnapshotError, "schema_version=2"):
                contract_snapshot.verify_adoption(root, "contract.lock.json", "rust", str(path))


if __name__ == "__main__":
    unittest.main()
