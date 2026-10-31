"""SQLite search + mock summarizer with real OpenCaliber pre-dispatch checks.

No network request, model inference or credentials. The mock is deliberately
deterministic; replace MockLLM.summarize with an application-owned LLM client.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import sys

# Also works from the extracted OpenCaliber runtime package.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from opencaliber.agent_engine import evaluate_trace, validate_config
from opencaliber.execution import ActionBlocked, EvaluationFailed, GuardedExecutor

APPROVED_ENDPOINT = 'https://llm.company.test/summarize'
SCENARIOS = ('success', 'blocked-transfer', 'record-limit', 'database-failure', 'llm-failure')


def demo_database():
    """Only synthetic tickets in a private, in-memory SQLite database."""
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
    connection.executemany('INSERT INTO support_tickets VALUES (?, ?)', [
        (1, 'Payment failed at checkout. The customer retried.'),
        (2, 'Payment failed after a gateway timeout.'),
        (3, 'Password reset link expired.'),
        (4, 'Payment confirmation is delayed.')
    ])
    connection.commit()
    # Database permissions complement the evaluator; the agent cannot mutate data.
    connection.execute('PRAGMA query_only = ON')
    return connection


def search_records(connection, *, table, term, limit, policy_limit):
    """Trusted executor validates real inputs, not just trace labels."""
    if table != 'support_tickets':
        raise ValueError('The database executor permits only support_tickets')
    if not isinstance(term, str) or not term.strip() or len(term) > 200:
        raise ValueError('Supply a nonempty search term of at most 200 characters')
    if type(limit) is not int or not 0 <= limit <= policy_limit:
        raise ValueError('Requested rows exceed the executor limit')
    # Fixed SQL/table, parameterized term and LIMIT. instr treats % and _ literally.
    rows = connection.execute(
        'SELECT id, body FROM support_tickets '
        'WHERE instr(lower(body), lower(?)) > 0 ORDER BY id LIMIT ?',
        (term, limit)
    ).fetchall()
    return {'ok': True, 'records': [dict(row) for row in rows]}


class MockLLM:
    """No model/API call. Provides a runnable stand-in for your LLM client."""
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = 0

    def summarize(self, *, destination, records):
        # Use the same destination that was evaluated; do not substitute a URL here.
        self.calls += 1
        if self.fail:
            raise TimeoutError('Simulated LLM timeout')
        return {
            'ok': True,
            'summary': f"DEMO summary: {len(records)} matching support tickets; "
                       f"ticket IDs: {', '.join(str(row['id']) for row in records)}. "
                       'This is a deterministic mock, not an LLM-generated summary.'
        }


def run_workflow(scenario='success', *, term='payment', config_path=None, evaluator=evaluate_trace):
    if scenario not in SCENARIOS:
        raise ValueError('Unknown scenario')
    config_path = config_path or Path(__file__).with_name('policy.json')
    config = validate_config(json.loads(Path(config_path).read_text(encoding='utf-8')))
    task = {
        'goal': 'Find matching support tickets and summarize them using the approved endpoint',
        'allowed_tools': ['database.read', 'http.send'],
        'allowed_resources': ['support_tickets', APPROVED_ENDPOINT],
        'read_only': False  # The workflow reads the DB but also sends an HTTP request.
    }
    executor = GuardedExecutor(
        agent={'id': 'ticket-summary-agent', 'version': 'example-v1'},
        task=task, workflow_id='ticket-summary-' + scenario,
        config=config, mode='enforce', evaluator=evaluator
    )
    connection = demo_database()
    llm = MockLLM(fail=scenario == 'llm-failure')
    calls = {'database': 0, 'llm': 0}
    events = []
    proposed = None
    summary = None
    error = None
    status = 'completed'

    def make_report():
        return _report(executor, config, proposed, calls, events, status, summary, error)

    try:
        # AGENT ACTION 1: propose a database read.
        requested = config['max_records'] + 1 if scenario == 'record-limit' else min(3, config['max_records'])
        proposed = {'id': 'query-01', 'tool': 'database.read', 'resource': 'support_tickets',
                    'arguments': {'records': requested}, 'data_class': 'public'}
        events.append('CHECK query-01: evaluate table, tool scope and requested record limit')

        def query_callback():
            calls['database'] += 1
            if scenario == 'database-failure':
                raise sqlite3.OperationalError('Simulated database connection failure')
            return search_records(connection, table=proposed['resource'], term=term,
                                  limit=proposed['arguments']['records'], policy_limit=config['max_records'])

        # OPENCALIBER CHECKPOINT 1: callback runs only after a clear assessment.
        query_result = executor.run(proposed, query_callback,
                                    success=lambda result: result.get('ok') is True)
        events.append(f"EXECUTED query-01: {len(query_result['records'])} records returned")
        if not query_result['records']:
            events.append('No matching records; application skips the LLM call')
            return make_report()

        # AGENT ACTION 2: propose sending the matched records to the summarizer.
        destination = 'https://unapproved.test/summarize' if scenario == 'blocked-transfer' else APPROVED_ENDPOINT
        proposed = {'id': 'summarize-01', 'tool': 'http.send', 'resource': destination,
                    'arguments': {'destination': destination, 'records': len(query_result['records']),
                                  'purpose': 'summarize'},
                    'data_class': 'public'}  # Synthetic demo data; NOT automatic PII detection.
        events.append('CHECK summarize-01: evaluate destination, purpose, scope and data label')

        def llm_callback():
            calls['llm'] += 1
            # REAL LLM INTEGRATION POINT:
            # Replace this mock with your LLM client, using the checked destination
            # and these exact records. Enforce timeout, payload limits, redaction,
            # destination/redirect policy and authentication inside that client.
            return llm.summarize(destination=proposed['arguments']['destination'],
                                 records=query_result['records'])

        # OPENCALIBER CHECKPOINT 2: checks completed prefix + this proposed transfer.
        response = executor.run(proposed, llm_callback,
                                success=lambda result: result.get('ok') is True)
        summary = response['summary']
        events.append('EXECUTED summarize-01: mock response received')
    except ActionBlocked:
        status = 'blocked'
        events.append('BLOCKED: the rejected action callback was not invoked')
    except EvaluationFailed:
        status = 'evaluation_unavailable'
        error = 'Evaluator unavailable; proposed callback was not invoked'
        events.append(error)
    except (sqlite3.Error, TimeoutError, ValueError) as exc:
        status = 'execution_failed'
        error = str(exc)
        events.append('EXECUTION FAILED: workflow stops; no automatic retry')
    finally:
        connection.close()

    return make_report()

def _report(executor, config, proposed, calls, events, status, summary, error):
    attempted_trace = copy.deepcopy(executor.trace)
    # GuardedExecutor deliberately does not append a blocked/unevaluated proposal.
    if proposed and not any(a['id'] == proposed['id'] for a in attempted_trace['actions']):
        attempted_trace['actions'].append(copy.deepcopy(proposed))
    return {'status': status, 'summary': summary, 'error': error, 'events': events,
            'callback_counts': calls, 'config': config, 'trace': attempted_trace,
            'last_pre_dispatch_evaluation': executor.last_evaluation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS, default='success')
    parser.add_argument('--term', default='payment')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('policy.json'))
    parser.add_argument('--output', type=Path, help='Optional JSON evidence file; may contain input metadata')
    args = parser.parse_args()
    report = run_workflow(args.scenario, term=args.term, config_path=args.config)
    for event in report['events']:
        print(event)
    print('Status:', report['status'])
    print('Callbacks:', json.dumps(report['callback_counts']))
    if report['summary']:
        print(report['summary'])
    result = report['last_pre_dispatch_evaluation']
    if result:
        for action in result['actions']:
            for finding in action['findings']:
                print(action['action_id'], finding['code'], finding['message'])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('Evidence:', args.output)
    return 0 if report['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
