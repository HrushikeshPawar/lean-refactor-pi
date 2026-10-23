import json
from pathlib import Path
from tempfile import TemporaryDirectory

from arena import recovery_usage, run_control


def test_retained_actual_usage_reconciliation():
    with TemporaryDirectory() as tmp:
        directory = Path(tmp)
        identity = {'run_id': 'run', 'actor_id': 'worker', 'session_id': 'session', 'job_id': 'job'}
        for request in ('zero', 'late', 'group-a', 'group-b', 'session-request', 'open'):
            run_control.begin_dispatch(directory, {**identity, 'request_id': request, 'attempt_id': request}, lambda: None)
        run_control.settle_usage(directory, {**identity, 'settlement_id': 'unknown:late',
            'covered_request_ids': ['late'], 'state': 'unknown'})
        costs = [
            {'kind': 'settle', 'id': 'zero', 'usd': 0, 'usage_known': True},
            {'kind': 'settle', 'id': 'late', 'usd': 0, 'usage_known': False},
            {'kind': 'settle', 'id': 'late', 'usd': 0.2, 'usage_known': True},
            {'kind': 'settle', 'id': 'group-b', 'covered_request_ids': ['group-a', 'group-b'],
             'usd': 0.05, 'usage_known': True, 'source': 'compaction'},
        ]
        (directory / 'cost-ledger.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in costs))
        (directory / 'trace-journal.jsonl').write_text(json.dumps({
            'kind': 'response', 'request_id': 'session-request', 'response_id': 'response-123',
        }) + '\n')
        saved = directory / 'sessions' / 'session'
        saved.mkdir(parents=True)
        (saved / 'retained.jsonl').write_text(json.dumps({'type': 'message', 'id': 'entry', 'message': {
            'role': 'assistant', 'responseId': 'response-123', 'usage': {'cost': {'total': 0.04}},
        }}) + '\n')
        with (saved / 'retained.jsonl').open('a') as stream:
            stream.write(json.dumps({'type': 'message', 'request_id': 'open', 'message': {
                'role': 'assistant', 'stopReason': 'error', 'usage': {'totalTokens': 0, 'cost': {'total': 0}},
            }}) + '\n')
        journals, sessions = recovery_usage.retained_evidence(directory)
        result = recovery_usage.reconcile_usage(directory, journals, sessions, {'session'})
        assert result['issues'] == []
        view = run_control.read_state(directory)
        assert view['total'] == '0.29'
        assert view['unknown_requests'] == []
        assert view['by_actor'] == {'worker': '0.29'}
        again = recovery_usage.reconcile_usage(directory, journals, sessions, {'session'})
        assert again['issues'] == []
        assert run_control.read_state(directory)['total'] == '0.29'
        settlements = run_control._settlement_rows(run_control._control_rows(directory))
        assert any(row.get('reconciles') == 'unknown:late' for row in settlements)
        assert any(row.get('counted_amount') == '0' and row['covered_request_ids'] == ['zero'] for row in settlements)
        absent = recovery_usage.reconcile_usage(directory, journals, sessions, set())
        assert absent['issues'] == []
        assert run_control.read_state(directory)['unknown_requests'] == ['open']
        # A torn UTF-8 record remains a diagnostic while valid earlier usage survives.
        with (directory / 'cost-ledger.jsonl').open('ab') as stream:
            stream.write(b'{"kind":"settle","x":"\xf0\x9f')
        journals, sessions = recovery_usage.retained_evidence(directory)
        broken = recovery_usage.reconcile_usage(directory, journals, sessions, set())
        assert any(issue['recovery_issue'] == 'malformed_retained_record' for issue in broken['issues'])
        assert run_control.read_state(directory)['total'] == '0.29'
        incompatible = recovery_usage.reconcile_usage(directory, [
            {'covered_request_ids': ['zero', 'late'], 'usage': {'cost': {'total': 0.2}}},
        ], [], set())
        assert any(issue['recovery_issue'] == 'settled_coverage_conflict' for issue in incompatible['issues'])
        assert run_control.read_state(directory)['total'] == '0.29'
