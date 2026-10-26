"""Independent assertions over real App Server A2 producer vectors."""

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AppServerA2Tests(unittest.TestCase):
    def test_context_and_compaction_receipts(self):
        c = json.loads((ROOT / 'fixtures/app_server_a2.json').read_text())
        self.assertEqual(c['protocol_version'], 'v4')
        self.assertNotEqual(c['before']['contextVersion'], c['after']['contextVersion'])
        for view in (c['before'], c['after']):
            self.assertTrue(view['estimates']['estimated'])
            self.assertEqual(set(view['estimates']['parts']), {'instructions', 'tools', 'history', 'summary', 'pendingInput'})
            self.assertEqual(view['estimates']['total'], sum(view['estimates']['parts'].values()))
            self.assertEqual(view['limits']['contextWindow'], 128000)
            self.assertEqual(view['limits']['outputReserve'], 16000)
            self.assertEqual(view['limits']['compactionThreshold'], 99000)
        self.assertGreater(c['after']['lastCompaction']['replacedMessageCount'], 0)
        self.assertIn('Continue', c['after']['lastCompaction']['summary'])
        self.assertEqual(c['before']['counts']['rawHistoryMessages'], c['after']['counts']['rawHistoryMessages'])
        self.assertGreater(c['after']['counts']['rawHistoryMessages'], c['after']['counts']['modelVisibleHistoryMessages'])
        identity = hashlib.sha256(b'["a2","compact"]').hexdigest()
        self.assertEqual(c['receipt']['requestId'], 'compaction/' + identity)
        self.assertEqual(c['replay'], c['receipt'] | {'replayed': True})
        self.assertEqual(c['conflict']['code'], -32024)
        self.assertEqual(c['stale']['code'], -32028)
        self.assertEqual(c['modelCalls'], ['primary', 'compaction'])
        self.assertEqual([e['method'] for e in c['lifecycle']], ['contextCompaction/started', 'contextCompaction/completed'])
        self.assertEqual({e['params']['requestId'] for e in c['lifecycle']}, {c['receipt']['requestId']})

    def test_fork_identity_lineage_and_summary_seed(self):
        c = json.loads((ROOT / 'fixtures/app_server_a2.json').read_text())
        f = c['fork']
        expected_id = hashlib.sha256(b'["a2","branch"]').hexdigest()
        self.assertEqual(f['receipt']['threadId'], 'fork/' + expected_id)
        self.assertEqual(f['replay'], f['receipt'] | {'replayed': True})
        self.assertEqual(f['conflict']['code'], -32024)
        self.assertEqual(set(f['seed']), {'messages', 'shared_state'})
        self.assertEqual(f['seed']['shared_state'], {})
        encoded = json.dumps(f['seed']['messages'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(f['receipt']['lineage']['contextDigest'], hashlib.sha256(encoded).hexdigest())
        self.assertEqual(f['context']['lineage'], f['receipt']['lineage'])
        self.assertEqual(f['context']['lastCompaction'], c['after']['lastCompaction'])
        self.assertEqual(f['context']['counts']['pendingInputs'], 0)
        self.assertEqual(f['context']['counts']['rawRecordCount'], 1)
        self.assertEqual(sum(m.get('name') == 'memory_summary' for m in f['seed']['messages']), 1)
        self.assertEqual(f['receipt']['lineage']['cutTurnId'], c['after']['lastCompaction']['turnId'])
        schema = json.loads(json.loads((ROOT / 'fixtures/app_server_protocol.json').read_text())['schemas']['jsonSchema']['ClientRequest'])
        params = schema['$defs']['ThreadForkParams']
        self.assertFalse(params['additionalProperties'])
        self.assertEqual(params['required'], ['threadId', 'forkId'])
        self.assertEqual(params['not'], {'required': ['throughTurnId', 'beforeTurnId']})
        self.assertNotIn('model', params['properties'])

    def test_catalog_unknowns_are_not_defaults(self):
        models = json.loads((ROOT / 'fixtures/app_server_a2.json').read_text())['models']
        known, unknown = models
        fields = {'contextLength', 'maxOutputTokens', 'supportsTools', 'supportsVision', 'inputModalities',
                  'supportsReasoning', 'supportedReasoningEfforts', 'defaultReasoningEffort',
                  'supportsPromptCache', 'supportsContinuation'}
        self.assertTrue(fields <= known.keys())
        self.assertTrue(all(unknown[key] is None for key in fields))
        self.assertEqual(known['supportedReasoningEfforts'], ['low', 'high'])
        self.assertEqual(known['defaultReasoningEffort'], 'high')
        self.assertIs(known['supportsPromptCache'], False)
        self.assertIs(known['supportsContinuation'], True)


if __name__ == '__main__':
    unittest.main()
