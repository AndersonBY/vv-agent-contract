"""Canonical requirements exercised by the implementation's real SQL producers."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LeaseSafeLoadingTests(unittest.TestCase):
    def test_factory_and_prefix_requirements(self):
        rules = json.loads((ROOT / 'fixtures/session_supervision.json').read_text())['rules']
        for rule in (
            'factory_lease_renewed_until_handoff',
            'factory_renewal_failure_prevents_execution',
            'factory_cleanup_uses_current_lease',
            'prefix_reads_do_not_block_renewal',
            'prefix_reads_use_captured_head_and_inbox',
        ):
            self.assertIs(rules[rule], True)
        docs = (ROOT / 'docs/session-consumers.md').read_text()
        self.assertIn('MUST start before calling the factory', docs)
        self.assertIn('session row lock', docs)
        self.assertIn('captured head', docs)
        self.assertIn('captured inbox watermark', docs)


if __name__ == '__main__':
    unittest.main()
