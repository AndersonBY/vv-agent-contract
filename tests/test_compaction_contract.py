"""Consistency checks for executable history-preserving compaction vectors."""
import base64
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import unittest

FIXTURES = Path(os.environ.get('CONTRACT_FIXTURE_ROOT', Path(__file__).resolve().parents[1] / 'fixtures'))


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def canonical(value):
    # These vectors contain only strings, booleans and JSON-safe integers.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def project(message):
    result = copy.deepcopy(message)
    result.pop('artifact_ref', None)
    if 'image_url' in result:
        del result['image_url']
        result['content'] = '[image omitted from summary input: ' + (result['content'] or 'image') + ']'
    if 'metadata' in result:
        result['metadata'].pop('_vv_agent_compaction', None)
        if not result['metadata']:
            del result['metadata']
    return result


def render_prompt(contract, language, event_limit, summary_input):
    values = {key + '_jcs': canonical(value) for key, value in summary_input.items()}
    values['event_limit'] = str(max(event_limit, 1))
    template = contract['prompt_templates'].get(language, contract['prompt_templates']['en-US'])
    return re.sub(r'\{(previous_summary_jcs|conversation_prefix_jcs|event_limit)\}',
                  lambda match: values[match[1]], template)


def normalized_summary(raw, contract):
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip().startswith('```'):
            lines.pop()
        cleaned = '\n'.join(lines).strip()
    cleaned = re.sub(r'<analysis>.*?</analysis>', '', cleaned, flags=re.S | re.I).strip()
    wrapper = re.search(r'<summary>\s*(.*?)\s*</summary>', cleaned, flags=re.S | re.I)
    if wrapper:
        cleaned = wrapper[1].strip()
    obj = None
    for index, char in enumerate(cleaned):
        if char != '{':
            continue
        try:
            candidate, _ = json.JSONDecoder().raw_decode(cleaned[index:])
        except ValueError:
            continue
        if isinstance(candidate, dict):
            obj = candidate
            break
    if obj is None:
        return None
    result = copy.deepcopy(contract['model_output_normalization']['empty_summary'])
    for key in result:
        value = obj.get(key)
        if key == 'summary_version':
            continue
        if key == 'current_work_state':
            result[key] = value if isinstance(value, str) else ''
        elif key in ('files_examined_or_modified', 'errors_and_fixes'):
            fields = contract['file_action_fields'] if key == 'files_examined_or_modified' else contract['error_fix_fields']
            for record in value if isinstance(value, list) else []:
                if not isinstance(record, dict):
                    continue
                if key == 'files_examined_or_modified':
                    if not isinstance(record.get('path'), str) or not record['path'].strip() or record.get('action') not in contract['file_action_values']:
                        continue
                elif not isinstance(record.get('error'), str):
                    continue
                result[key].append({field: record[field] if isinstance(record.get(field), str) else '' for field in fields})
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[key] = value
    return result


class CompactionContractTests(unittest.TestCase):
    def test_localized_prompts_render_exactly(self):
        contract = fixture('memory_local.json')['summary_compaction']
        self.assertEqual(set(contract['prompt_templates']), {'zh-CN', 'en-US'})
        case = contract['prompt_cases'][0]
        source = next(c for c in contract['cases'] if c['name'] == case['source_case'])
        for language in ('zh-CN', 'en-US'):
            actual = render_prompt(contract, language, case['event_limit'], source['expected_summary_input'])
            self.assertEqual(actual.encode(), case['expected_prompts'][language].encode())
            self.assertIn('<analysis>', actual)
            schema = json.loads(actual.split('JSON Schema:\n')[1])
            self.assertEqual(set(schema), set(contract['summary_required_fields']))
            self.assertNotIn('<Conversation History>', actual)
        literal = {'previous_summary': [], 'conversation_prefix': [{'role': 'user', 'content': '{event_limit} {previous_summary_jcs}'}]}
        rendered = render_prompt(contract, 'en-US', 0, literal)
        self.assertIn(canonical(literal['conversation_prefix']), rendered)
        self.assertIn('Preserve up to 1 critical events', rendered)
        self.assertEqual(render_prompt(contract, 'other', 10, literal), render_prompt(contract, 'en-US', 10, literal))

    def test_model_output_normalization_accepts_harmless_variants(self):
        contract = fixture('memory_local.json')['summary_compaction']
        group = contract['accepted_normalization_cases']
        self.assertTrue(contract['written_summary_objects_closed'])
        self.assertNotIn('summary_objects_closed', contract)
        for variant in group['variants']:
            with self.subTest(variant=variant['name']):
                normalized = normalized_summary(variant['summary_response'], contract)
                self.assertEqual(normalized, variant['expected_normalized_summary'])
                self.assertTrue(any(normalized[k] for k in contract['model_output_normalization']['effective_content_fields']))
                expected = variant['expected']
                self.assertTrue(expected['changed'])
                self.assertEqual(expected['summary_calls'], 1)
                self.assertEqual(expected['messages'][0], group['input']['messages'][0])
                self.assertEqual(expected['messages'][2:], group['input']['messages'][-2:])
                summary = expected['messages'][1]
                self.assertEqual(summary['metadata'], group['expected_evidence_metadata'])
                written = copy.deepcopy(normalized)
                paths = {r['path'] for r in written['files_examined_or_modified']}
                for record in group['expected_prefix_file_actions']:
                    if record['path'] not in paths:
                        written['files_examined_or_modified'].append(record)
                        paths.add(record['path'])
                self.assertEqual(summary['content'], '<Original User Request>\n' + '\n\n'.join(written['original_user_messages']) + '\n</Original User Request>\n\n<Compressed Agent Memory>\n' + canonical(written) + '\n</Compressed Agent Memory>\n\n' + group['expected_evidence_section'])
        for raw in ('{}', '{"user_constraints":["constraint only"]}'):
            normalized = normalized_summary(raw, contract)
            self.assertFalse(any(normalized[k] for k in contract['model_output_normalization']['effective_content_fields']))
        for raw in ('', '<analysis>{"current_work_state":"hidden"}</analysis>', '{broken'):
            self.assertIsNone(normalized_summary(raw, contract))

    def test_exact_prefix_tail_and_summary_output(self):
        memory = fixture('memory_local.json')
        contract = memory['summary_compaction']
        self.assertEqual(contract['keep_recent_messages_default'], 10)
        self.assertFalse(contract['local_fallback_may_replace_history'])
        cases = contract['cases'] + fixture('memory_lifecycle.json')['emergency_cases']
        for case in cases:
            with self.subTest(case=case['name']):
                messages = case['input']['messages']
                expected = case['expected']
                if not expected['changed']:
                    self.assertEqual(expected['messages'], messages)
                summary_input = case.get('expected_summary_input')
                if summary_input is None:
                    continue
                raw = [m for m in messages if m['role'] != 'system' and m.get('name') != 'memory_summary']
                previous = [project(m) for m in messages if m.get('name') == 'memory_summary']
                self.assertEqual(summary_input['previous_summary'], previous)
                prefix = summary_input['conversation_prefix']
                self.assertEqual(prefix, [project(m) for m in raw[:len(prefix)]])
                tail = raw[len(prefix):]
                if 'raw_tail' in expected:
                    self.assertEqual(expected['raw_tail'], tail)
                if not expected['changed']:
                    continue
                self.assertTrue(tail)
                self.assertNotEqual(tail[0]['role'], 'tool')
                target = case['input'].get('emergency_keep', case['input']['keep_recent_messages'])
                self.assertGreaterEqual(len(tail), target)
                systems = [m for m in messages if m['role'] == 'system']
                self.assertEqual(expected['messages'][:len(systems)], systems)
                self.assertEqual(expected['messages'][len(systems) + 1:], tail)
                summary = expected['messages'][len(systems)]
                self.assertEqual((summary['role'], summary['name']), ('user', 'memory_summary'))
                text = summary['content'].split('<Compressed Agent Memory>\n')[1].split('\n</Compressed Agent Memory>')[0]
                payload = json.loads(text)
                self.assertEqual(set(payload), set(contract['summary_required_fields']))
                self.assertEqual(text, canonical(payload))
                self.assertEqual(payload['summary_version'], '2.0')
                for forbidden in ('sha256', 'size_bytes', 'original_bytes', 'visible_bytes'):
                    self.assertNotIn(forbidden, summary['content'])
                self.assertLess(case['token_estimator']['candidate_messages'], case['token_estimator']['input_messages'])

    def test_image_prefix_projection_and_unfinished_tail(self):
        contract = fixture('memory_local.json')['summary_compaction']
        cases = {case['name']: case for case in contract['cases']}
        self.assertNotIn('unsupported_prefix_image_preserves_history', cases)
        for name, count in (('prefix_image_uses_text_placeholder', 1),
                            ('computer_agent_image_prefix_uses_placeholders', 6)):
            case = cases[name]
            self.assertFalse(case['input']['summary_accepts_images'])
            prefix = case['expected_summary_input']['conversation_prefix']
            placeholders = [m for m in prefix if m['content'].startswith('[image omitted from summary input: ')]
            self.assertEqual(len(placeholders), count)
            self.assertNotIn('image_url', canonical(prefix))
            self.assertNotIn('data:image/', canonical(prefix))
            self.assertEqual(case['expected']['raw_tail'], case['input']['messages'][-2:])
        pending = cases['trailing_incomplete_block_stays_in_tail']
        self.assertTrue(pending['expected']['changed'])
        self.assertTrue(pending['expected']['raw_tail'][-1]['tool_calls'])
        self.assertEqual(pending['expected']['raw_tail'], pending['input']['messages'][-2:])
        missing = next(c for c in contract['invalid_block_cases'] if c['name'] == 'missing_result_in_middle')
        self.assertEqual(missing['messages'][-1]['role'], 'user')

    def test_manifest_is_complete_stable_merge_and_exact_projection(self):
        memory = fixture('memory_local.json')
        spec = memory['evidence_manifest']
        self.assertTrue(spec['closed'])
        self.assertEqual(spec['required_fields'], ['artifacts', 'cursors'])
        for case in memory['summary_compaction']['cases']:
            if not case['expected']['changed']:
                continue
            with self.subTest(case=case['name']):
                source = case['input']['messages']
                prefix_len = len(case['expected_summary_input']['conversation_prefix'])
                raw = [m for m in source if m['role'] != 'system' and m.get('name') != 'memory_summary']
                collected = dict(artifacts=[], cursors=[])
                for message in source:
                    prior = message.get('metadata', {}).get('_vv_agent_compaction')
                    if prior:
                        for key in collected:
                            collected[key].extend(prior[key])
                block = {}
                for message in raw[:prefix_len]:
                    if message.get('tool_calls'):
                        block = {c['id']: c['function'] for c in message['tool_calls']}
                    if message['role'] != 'tool':
                        continue
                    call = block[message['tool_call_id']]
                    record = dict(tool_call_id=message['tool_call_id'], tool_name=call['name'], arguments=call['arguments'])
                    if 'artifact_ref' in message:
                        collected['artifacts'].append(dict(record, artifact_ref=message['artifact_ref']))
                    last = message['content'].split('\n')[-1]
                    if last.startswith('{'):
                        recovery = json.loads(last).get('vv_agent_recovery', {})
                        if 'cursor' in recovery:
                            collected['cursors'].append(dict(record, cursor=recovery['cursor']))
                for key, records in collected.items():
                    collected[key] = list({canonical(r): r for r in records}.values())
                summary = next(m for m in case['expected']['messages'] if m.get('name') == 'memory_summary')
                self.assertEqual(summary['metadata'], {'_vv_agent_compaction': collected})
                lines = []
                for record in collected['artifacts']:
                    self.assertEqual(set(record), set(spec['artifact_record_fields']))
                    lines.append('- ' + canonical(dict(tool_call_id=record['tool_call_id'], tool_name=record['tool_name'], arguments=record['arguments'], artifact_path=record['artifact_ref']['path'], retrieval_hint='use read_file on artifact_path if needed')))
                for record in collected['cursors']:
                    self.assertEqual(set(record), set(spec['cursor_record_fields']))
                    lines.append('- ' + canonical(dict(tool_call_id=record['tool_call_id'], tool_name=record['tool_name'], arguments=record['arguments'], path=record['cursor']['path'], offset_chars=record['cursor']['offset_chars'], retrieval_hint='use read_file on path if needed')))
                section = '\n'.join(['<Persisted Artifacts>', *lines, '</Persisted Artifacts>'])
                self.assertTrue(summary['content'].endswith(section))

    def test_failure_vectors_and_strict_session_metadata(self):
        memory = fixture('memory_local.json')
        failures = next(c for c in memory['summary_compaction']['cases'] if c['name'] == 'summarizer_failure_preserves_history')
        self.assertEqual(failures['input']['messages'], failures['expected']['messages'])
        self.assertEqual({v['name'] for v in failures['variants']}, {'empty', 'analysis_only', 'invalid_json', 'no_effective_content', 'callback_exception', 'no_callback', 'summary_input_window_too_small', 'manifest_over_budget', 'recovery_surface_unavailable'})
        for case in memory['summary_compaction']['invalid_block_cases']:
            self.assertEqual(case['messages'], case['expected']['messages'])
            self.assertEqual(case['expected']['summary_calls'], 0)
        codec = fixture('session_codec.json')
        case = next(c for c in codec['canonical_cases'] if c['name'] == 'summary_evidence_round_trips')
        self.assertEqual(case['input'], case['canonical'])
        self.assertEqual(project(case['canonical']), case['model_projection'])
        self.assertEqual(codec['model_projection']['strip_host_only_metadata_keys'], ['_vv_agent_compaction'])
        invalid = [c for c in codec['invalid_cases'] if c['name'].startswith('summary_evidence_')]
        self.assertEqual(len(invalid), 9)
        for case in invalid:
            self.assertIn('_vv_agent_compaction', case['input']['metadata'])


    def test_accounting_and_emergency_reuse_existing_shapes(self):
        usage = fixture('token_usage.json')
        for case in usage['compaction_cases']:
            calls = case['expected']['model_calls']
            for call in calls:
                self.assertEqual(call['schema_version'], 'vv-agent.model-call.v2')
                self.assertEqual(call['operation'], 'memory_compaction')
            if case['name'] == 'summary_receipt_replay':
                self.assertEqual(case['expected']['new_model_dispatches'], 0)
                self.assertEqual(case['expected']['new_budget_total_tokens'], 0)
            else:
                values = [call['usage']['total_tokens'] for call in calls]
                self.assertEqual(case['expected']['new_budget_total_tokens'],
                                 None if any(v is None for v in values) else sum(values))
        lifecycle = fixture('memory_lifecycle.json')
        emergency = lifecycle['provider_attempts']['strategies'][1]
        self.assertTrue(emergency['requires_summary'])
        self.assertFalse(emergency['drops_without_summary'])
        self.assertEqual(lifecycle['compaction_events']['completed']['mode_values'], ['none', 'micro', 'structural', 'summary', 'emergency'])
        for case in lifecycle['emergency_cases']:
            inp = case['input']
            self.assertEqual(inp['emergency_keep'], max(1, int(inp['keep_recent_messages'] * (1 - min(max(inp['drop_ratio'], 0), .95)))))
        micro = fixture('memory_local.json')['microcompact']
        self.assertEqual(micro['schema_version'], 'vv-agent.microcompaction.v3')
        self.assertTrue(micro['preserves_call_result_skeleton'])
        self.assertTrue(micro['summary_tail_is_protected'])
        self.assertEqual([c['expected']['candidate_message_indices'] for c in micro['transcript_cases']], [[2], [2]])


if __name__ == '__main__':
    unittest.main()
