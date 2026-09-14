"""Offline contract tests; these do not evaluate live model judgment quality."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import ValidationError, Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('validate_artifact', ROOT / 'scripts/validate_artifact.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SCHEMAS = {name: json.loads((ROOT / f'{name}.schema.json').read_text())
           for name in ('findings', 'judgment', 'verification')}
EVIDENCE = {'file': '/example/spec.md', 'location': 'Timeouts', 'quote': 'Requests time out after 30 seconds.'}


def finding(fid='F1', source='item-a'):
    return {
        'finding_id': fid, 'origin': 'review', 'source_item_ids': [source],
        'prior_finding_ids': [], 'title': 'Contradictory timeout',
        'root_cause': 'Inconsistent timeout values', 'affected_component': 'Timeouts',
        'evidence': [copy.deepcopy(EVIDENCE)], 'severity': 'medium',
        'architectural_reversal': False,
        'validity': 'The target specifies both 30 and 60 seconds for the same request.',
        'consequence': 'Implementers may choose incompatible client and server limits.',
        'remedy_assessment': 'Use the 30-second limit required by the reference.',
        'disposition': 'fix_now', 'disposition_reason': 'The reference establishes the intended limit.',
        'recommendation': 'Change the conflicting 60-second limit to 30 seconds.',
        'acceptance_criteria': ['Every limit for this request is 30 seconds.'], 'depends_on': [],
        'edit_scope': [{'file': '/example/spec.md', 'component': 'Timeouts'}],
    }


def judgment(*items):
    return {'findings': list(items),
            'fix_order': [f['finding_id'] for f in items if f['disposition'] == 'fix_now'],
            'ordering_reason': 'Resolve prerequisite contradictions before dependent instructions.'}


class ContractTests(unittest.TestCase):
    def check(self, name, artifact):
        module.validate(SCHEMAS[name], artifact)

    def rejects(self, name, artifact):
        with self.assertRaises((ValueError, ValidationError)):
            self.check(name, artifact)

    def test_schemas_are_valid(self):
        for schema in SCHEMAS.values():
            Draft202012Validator.check_schema(schema)

    def test_complete_empty_review_is_success(self):
        self.check('findings', {'review_status': 'complete', 'reviewed_files': ['/example/spec.md'],
                                'limitations': [], 'findings': []})

    def test_incomplete_empty_review_is_failure(self):
        self.rejects('findings', {'review_status': 'incomplete', 'reviewed_files': ['/example/spec.md'],
                                  'limitations': ['Reference did not fit.'], 'findings': []})

    def test_claimed_complete_with_limitations_is_failure(self):
        self.rejects('findings', {'review_status': 'complete', 'reviewed_files': ['/example/spec.md'],
                                  'limitations': ['One section unreadable.'], 'findings': []})

    def test_empty_judgment_and_verification_are_valid(self):
        self.check('judgment', judgment())
        self.check('verification', {'results': [], 'regressions': []})

    def test_single_critic_finding_can_be_approved(self):
        self.check('judgment', judgment(finding()))

    def test_judge_origin_needs_no_fabricated_vote(self):
        item = finding()
        item.update(origin='judge', source_item_ids=[])
        self.check('judgment', judgment(item))

    def test_duplicate_source_cannot_support_multiple_findings(self):
        self.rejects('judgment', judgment(finding(), finding('F2')))

    def test_deferred_ledger_item_survives_without_current_votes(self):
        item = finding()
        item.update(source_item_ids=[], prior_finding_ids=['old-F1'], disposition='needs_verification',
                    acceptance_criteria=[], edit_scope=[])
        self.check('judgment', judgment(item))

    def test_reversal_cannot_be_approved_even_with_three_sources(self):
        item = finding()
        item.update(architectural_reversal=True, source_item_ids=['a', 'b', 'c'])
        self.rejects('judgment', judgment(item))
        item['disposition'] = 'needs_decision'
        item['edit_scope'] = []
        self.check('judgment', judgment(item))

    def test_fix_requires_acceptance_criteria(self):
        item = finding()
        item['acceptance_criteria'] = []
        self.rejects('judgment', judgment(item))

    def test_fix_requires_explicit_edit_scope(self):
        item = finding()
        item['edit_scope'] = []
        self.rejects('judgment', judgment(item))

    def test_rank_must_include_all_approved_fixes(self):
        artifact = judgment(finding())
        artifact['fix_order'] = []
        self.rejects('judgment', artifact)

    def test_rank_cannot_include_deferred_finding(self):
        item = finding()
        item['disposition'] = 'needs_decision'
        item['edit_scope'] = []
        artifact = judgment(item)
        artifact['fix_order'] = ['F1']
        self.rejects('judgment', artifact)

    def test_dependency_order_and_cycles(self):
        first, second = finding(), finding('F2', 'item-b')
        second['depends_on'] = ['F1']
        artifact = judgment(first, second)
        self.check('judgment', artifact)
        artifact['fix_order'].reverse()
        self.rejects('judgment', artifact)
        first['depends_on'] = ['F2']
        self.rejects('judgment', judgment(first, second))

    def test_unknown_and_deferred_dependencies_block_fix(self):
        first, second = finding(), finding('F2', 'item-b')
        first['depends_on'] = ['missing']
        self.rejects('judgment', judgment(first))
        first['depends_on'] = ['F2']
        second['disposition'] = 'needs_decision'
        second['edit_scope'] = []
        self.rejects('judgment', judgment(first, second))

    def test_verified_resolution_requires_evidence(self):
        result = {'finding_id': 'F1', 'status': 'verified_resolved', 'reason': 'The values now match.',
                  'evidence': []}
        self.rejects('verification', {'results': [result], 'regressions': []})
        result['evidence'] = [copy.deepcopy(EVIDENCE)]
        self.check('verification', {'results': [result], 'regressions': []})

    def test_uncertain_and_unapplied_are_distinct_from_resolution(self):
        for status in ('uncertain', 'unresolved', 'unapplied'):
            self.check('verification', {'results': [{'finding_id': 'F1', 'status': status,
                'reason': 'Resolution was not established.', 'evidence': []}], 'regressions': []})

    def test_legacy_scores_rejected(self):
        item = finding()
        item['score'] = 150
        self.rejects('judgment', judgment(item))

    def test_quote_length_enforced(self):
        item = finding()
        item['evidence'][0]['quote'] = ' '.join(['word'] * 41)
        self.rejects('judgment', judgment(item))

    def test_cli_returns_failure_for_invalid_artifact_and_success_for_clean_review(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / 'review.json'
            artifact.write_text(json.dumps({'review_status': 'complete',
                'reviewed_files': ['/example/spec.md'], 'limitations': [], 'findings': []}))
            command = [sys.executable, str(ROOT / 'scripts/validate_artifact.py'),
                       str(ROOT / 'findings.schema.json'), str(artifact)]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            artifact.write_text('{broken')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)


if __name__ == '__main__':
    unittest.main()
