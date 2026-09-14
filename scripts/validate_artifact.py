#!/usr/bin/env python3
"""Validate one critic, judge, or verifier artifact, including local policy invariants.

Source truth, cross-artifact coverage, and filesystem checks belong to the
orchestrator. This command makes no provider calls and never modifies artifacts.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, SchemaError, ValidationError


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(values, label):
    require(len(values) == len(set(values)), f"duplicate {label}")


def validate(schema, artifact):
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(artifact)
    if 'review_status' in artifact:
        require(artifact['review_status'] == 'complete', 'critic review is incomplete')
        require(not artifact['limitations'], 'critic review has limitations')
        unique([f['finding_id'] for f in artifact['findings']], 'critic finding ID')
        for finding in artifact['findings']:
            require(len(finding['evidence']['quote'].split()) <= 40, 'evidence exceeds 40 words')
    elif 'fix_order' in artifact:
        findings = artifact['findings']
        unique([f['finding_id'] for f in findings], 'judge finding ID')
        unique([i for f in findings for i in f['source_item_ids']], 'source item ID')
        unique([i for f in findings for i in f['prior_finding_ids']], 'prior finding ID')
        approved = {f['finding_id']: f for f in findings if f['disposition'] == 'fix_now'}
        order = artifact['fix_order']
        require(set(order) == set(approved), 'fix_order must contain every and only fix_now ID')
        positions = {fid: n for n, fid in enumerate(order)}
        for finding in findings:
            has_sources = bool(finding['source_item_ids'] or finding['prior_finding_ids'])
            require(has_sources == (finding['origin'] == 'review'), 'origin does not match provenance')
            for evidence in finding['evidence']:
                require(len(evidence['quote'].split()) <= 40, 'evidence exceeds 40 words')
            if finding['architectural_reversal']:
                require(finding['disposition'] == 'needs_decision', 'architectural reversal requires a decision')
            if finding['disposition'] == 'fix_now':
                require(bool(finding['acceptance_criteria']), 'fix_now needs acceptance criteria')
                require(bool(finding['edit_scope']), 'fix_now needs explicit edit scope')
                for dependency in finding['depends_on']:
                    require(dependency in positions, 'fix depends on a non-actionable or unknown finding')
                    require(positions[dependency] < positions[finding['finding_id']], 'dependency must precede fix')
            else:
                require(not finding['edit_scope'], 'non-actionable findings cannot authorize edits')
    elif 'results' in artifact:
        unique([r['finding_id'] for r in artifact['results']], 'verification finding ID')
        for result in artifact['results']:
            if result['status'] == 'verified_resolved':
                require(bool(result['evidence']), 'verified resolution needs evidence')
        for entry in artifact['results'] + artifact['regressions']:
            for evidence in entry['evidence']:
                require(len(evidence['quote'].split()) <= 40, 'evidence exceeds 40 words')


def main():
    if len(sys.argv) != 3:
        print('Usage: validate_artifact.py SCHEMA ARTIFACT', file=sys.stderr)
        return 2
    try:
        schema, artifact = [json.loads(Path(path).read_text()) for path in sys.argv[1:]]
        validate(schema, artifact)
    except (ValueError, OSError, SchemaError, ValidationError) as exc:
        # jsonschema supplies detailed validation errors as well as schema errors.
        print(f'Invalid artifact: {exc}', file=sys.stderr)
        return 1
    print('Artifact is valid; source evidence and cross-artifact checks still required.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
