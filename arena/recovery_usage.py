"""Read retained provider evidence and reconcile it through the existing actual-cost ledger."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from arena import run_control


def jsonl_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    try:
        with path.open('rb') as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    if not line.endswith(b'\n'):
                        raise ValueError('incomplete record')
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('non-object record')
                except (ValueError, UnicodeDecodeError):
                    rows.append({'recovery_issue': 'malformed_retained_record', 'path': str(path), 'line': number})
                    continue
                rows.append(row)
    except OSError:
        rows.append({'recovery_issue': 'unreadable_retained_artifact', 'path': str(path)})
    return rows


def _amount(value: object) -> Decimal | None:
    return run_control._decimal_amount(str(value)) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def _reported(row: dict) -> dict:
    usage = row.get('usage')
    if isinstance(usage, dict) and run_control._usage_amount(usage) is not None:
        return row
    value = row.get('usd') if row.get('usage_known') is True else row.get('settled_usd')
    amount = _amount(value)
    if amount is None:
        return row
    return {**row, 'usage': {'cost': {'total': format(amount, 'f')}}}


def retained_evidence(directory: Path) -> tuple[list[dict], list[dict]]:
    journals = jsonl_rows(directory / 'cost-ledger.jsonl') + jsonl_rows(directory / 'cost-journal.jsonl')
    trace = jsonl_rows(directory / 'trace-journal.jsonl')
    responses = [row for row in trace if row.get('kind') == 'response']
    responses += [row for row in journals if row.get('kind') == 'usage_evidence']
    sessions = jsonl_rows(directory / 'session-evidence.jsonl')
    response_ids: dict[str, set[str]] = {}
    entry_coverage: dict[str, list[str]] = {}
    for row in responses:
        request_id = row.get('request_id') or row.get('id')
        covered = row.get('covered_request_ids') or ([request_id] if request_id else [])
        if isinstance(request_id, str) and isinstance(row.get('response_id'), str) and covered == [request_id]:
            response_ids.setdefault(row['response_id'], set()).add(request_id)
        if isinstance(row.get('session_entry_id'), str):
            entry_coverage[row['session_entry_id']] = row.get('covered_request_ids') or ([request_id] if request_id else [])
        sessions.append({**_reported(row), 'request_id': request_id, 'phase': 'response'})
    sessions.extend(row for row in trace if row.get('recovery_issue'))
    paths = set((directory / 'session').glob('*.jsonl')) | set((directory / 'sessions').glob('**/*.jsonl'))
    for row in run_control._control_rows(directory):
        path = row.get('session_path')
        if path:
            saved = Path(path)
            if not saved.is_absolute():
                saved = directory / saved
            paths.update(saved.glob('*.jsonl') if saved.is_dir() else [saved])
    for path in sorted(paths):
        for row in jsonl_rows(path):
            if row.get('recovery_issue'):
                sessions.append(row)
                continue
            message = row.get('message') if row.get('type') == 'message' else row
            if not isinstance(message, dict) or not isinstance(message.get('usage'), dict):
                continue
            if row.get('type') == 'message' and message.get('role') != 'assistant':
                continue
            request_id = row.get('request_id') or message.get('request_id')
            response_id = message.get('responseId')
            matches = response_ids.get(response_id, set()) if isinstance(response_id, str) else set()
            if not request_id and len(matches) == 1:
                request_id = next(iter(matches))
            entry_id = row.get('id')
            by_entry = entry_coverage.get(entry_id) if isinstance(entry_id, str) else None
            covered = row.get('covered_request_ids') or by_entry or ([request_id] if request_id else [])
            if not covered:
                sessions.append({'recovery_issue': 'uncorrelated_session_usage', 'path': str(path), 'entry_id': row.get('id')})
                continue
            usage = message['usage']
            if message.get('stopReason') in ('error', 'aborted') and not usage.get('totalTokens'):
                usage = None
            sessions.append({**row, 'usage': usage, 'phase': 'response', 'covered_request_ids': covered})
    return journals, sessions


def journal_charges(journals: list[dict], sessions: list[dict]) -> list[dict]:
    charges = []
    for raw in journals + sessions:
        if raw.get('recovery_issue'):
            charges.append(raw)
            continue
        if raw.get('estimate') or (raw.get('kind') not in (None, 'settle', 'accounting_failure', 'response', 'usage_evidence') and raw.get('phase') != 'response'):
            continue
        row = _reported(raw)
        covered = row.get('covered_request_ids') or ([row.get('request_id') or row.get('id')] if row.get('request_id') or row.get('id') else [])
        if not isinstance(covered, list) or not covered or any(not isinstance(item, str) or not item for item in covered):
            continue
        charges.append({**row, 'covered_request_ids': sorted(set(covered))})
    return charges


def reconcile_usage(directory: Path, journals: list[dict], sessions: list[dict], open_sessions: set[str] | None) -> dict:
    issues = []
    charges: dict[tuple[str, ...], dict] = {}
    for charge in journal_charges(journals, sessions):
        if charge.get('recovery_issue'):
            issues.append(charge)
            continue
        key = tuple(charge['covered_request_ids'])
        previous = charges.get(key)
        amount = run_control._usage_amount(charge.get('usage'))
        prior_amount = run_control._usage_amount(previous.get('usage')) if previous else None
        if previous is not None and amount is not None and prior_amount is not None and amount != prior_amount:
            issues.append({'recovery_issue': 'conflicting_actual_usage', 'covered_request_ids': list(key)})
            continue
        if previous is None or amount is not None:
            charges[key] = charge
    selected = []
    for key, charge in sorted(charges.items(), key=lambda pair: -len(pair[0])):
        overlapping = [item for item in selected if set(key).intersection(item['covered_request_ids'])]
        if overlapping:
            parent = overlapping[0]
            group = set(parent['covered_request_ids'])
            amount = run_control._usage_amount(charge.get('usage'))
            group_amount = run_control._usage_amount(parent.get('usage'))
            if not set(key).issubset(group) or (amount is not None and (group_amount is None or amount > group_amount)):
                issues.append({'recovery_issue': 'overlapping_actual_usage', 'covered_request_ids': sorted(set(key) | group)})
            continue
        selected.append(charge)
    for group in selected:
        covered = set(group['covered_request_ids'])
        if len(covered) == 1:
            continue
        amount = run_control._usage_amount(group.get('usage'))
        singles = {key[0]: run_control._usage_amount(row.get('usage')) for key, row in charges.items()
                   if len(key) == 1 and key[0] in covered and run_control._usage_amount(row.get('usage')) is not None}
        subtotal = sum(singles.values(), Decimal('0'))
        if amount is not None and (subtotal > amount or (len(singles) == len(covered) and subtotal != amount)):
            issues.append({'recovery_issue': 'conflicting_group_usage', 'covered_request_ids': sorted(covered)})
    conflict_ids = {request for issue in issues for request in issue.get('covered_request_ids', [])}
    for charge in selected:
        covered = charge['covered_request_ids']
        if conflict_ids.intersection(covered):
            continue
        rows = run_control._control_rows(directory)
        prepared = run_control._prepared(rows)
        coverage = run_control._apply_coverage(rows)
        owner = prepared.get(covered[0])
        if owner is None or any(item not in prepared for item in covered):
            issues.append({'recovery_issue': 'unprepared_usage', 'covered_request_ids': covered})
            continue
        if any(charge.get(field) is not None and charge[field] != owner.get(field)
               for field in ('run_id', 'actor_id', 'session_id', 'job_id')):
            issues.append({'recovery_issue': 'usage_ownership_conflict', 'covered_request_ids': covered})
            continue
        if any(any(prepared[item].get(field) != owner.get(field) for field in ('run_id', 'actor_id', 'session_id', 'job_id')) for item in covered):
            issues.append({'recovery_issue': 'mixed_usage_ownership', 'covered_request_ids': covered})
            continue
        originals = [row for row in coverage['originals'].values() if set(covered).intersection(row['covered_request_ids'])]
        amount = run_control._usage_amount(charge.get('usage'))
        reconciles = None
        if originals:
            if len(originals) != 1 or set(originals[0]['covered_request_ids']) != set(covered):
                issues.append({'recovery_issue': 'settled_coverage_conflict', 'covered_request_ids': covered})
                continue
            original = originals[0]
            if not set(covered).intersection(coverage['unknown']):
                known_row = next((row for row in reversed(rows) if row.get('reconciles') == original['settlement_id']), original)
                if amount is not None and _amount(known_row.get('counted_amount')) != amount:
                    issues.append({'recovery_issue': 'settled_amount_conflict', 'covered_request_ids': covered})
                continue
            if amount is None:
                continue
            reconciles = original['settlement_id']
            covered = original['covered_request_ids']
        if amount is None and owner.get('session_id') in (open_sessions or set()):
            continue
        payload = {field: owner.get(field) for field in ('run_id', 'actor_id', 'session_id', 'job_id')}
        payload.update(settlement_id='recovered:' + run_control.argument_digest([covered, reconciles])[:32],
                       covered_request_ids=covered, state='known' if amount is not None else 'unknown',
                       usage=charge.get('usage'), irreconcilable=amount is None)
        if reconciles:
            payload['reconciles'] = reconciles
        if amount is not None:
            payload['amount'] = format(amount, 'f')
        try:
            result = run_control.settle_usage(directory, payload)
            if not result.get('ok'):
                issues.append({'recovery_issue': 'settlement_conflict', 'covered_request_ids': covered})
        except run_control.OperationRejected as error:
            issues.append({'recovery_issue': 'settlement_rejected', 'covered_request_ids': covered, 'category': str(error)})
    rows = run_control._control_rows(directory)
    prepared = run_control._prepared(rows)
    coverage = run_control._apply_coverage(rows)
    latest = {}
    for row in rows:
        if row.get('kind') in ('dispatch_intent', 'dispatch') and row.get('attempt_id'):
            latest[row['attempt_id']] = row
    for row in latest.values():
        request_id = row.get('request_id')
        if (not request_id or request_id in coverage['covered'] or row.get('sent') == 'unsent'
                or row.get('status') in ('rejected_before_dispatch', 'failed_before_start')
                or row.get('session_id') in (open_sessions or set())):
            continue
        owner = prepared.get(request_id, row)
        run_control.settle_usage(directory, {
            **{field: owner.get(field) for field in ('run_id', 'actor_id', 'session_id', 'job_id')},
            'settlement_id': 'unknown:' + request_id, 'covered_request_ids': [request_id],
            'state': 'unknown', 'irreconcilable': True,
        })
    return {'issues': issues, 'latest': latest}
