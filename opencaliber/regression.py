"""Application-owned provider regression suites; no network or model calls."""
from .sdk import evaluate_response


def run_suite(suite, config=None):
    if not isinstance(suite, dict) or set(suite) != {'version', 'cases'} or not isinstance(suite['version'], str):
        raise ValueError('Suite requires version and cases')
    if not isinstance(suite['cases'], list) or not 1 <= len(suite['cases']) <= 1000:
        raise ValueError('Provide 1–1000 regression cases')
    rows = []
    seen = set()
    for case in suite['cases']:
        if not isinstance(case, dict) or set(case) != {'id', 'provider', 'response', 'context', 'expected_assessment', 'required_codes'}:
            raise ValueError('Invalid regression case')
        if not isinstance(case['id'], str) or not case['id'] or case['id'] in seen:
            raise ValueError('Case IDs must be unique strings')
        seen.add(case['id'])
        if case['expected_assessment'] not in ('clear', 'review', 'violation') or not isinstance(case['required_codes'], list) or any(not isinstance(x,str) for x in case['required_codes']):
            raise ValueError('Invalid regression expectation')
        result = evaluate_response(case['provider'], case['response'], config=config, **case['context'])['result']
        codes = sorted({f['code'] for a in result['actions'] for f in a['findings']})
        rows.append({'id': case['id'], 'agent': result['agent'], 'context': result['context'],
                     'config_sha256': result['config_sha256'], 'engine_version': result['engine_version'],
                     'expected': case['expected_assessment'], 'actual': result['assessment'],
                     'codes': codes, 'risk_score': result['risk_score'],
                     'passed': result['assessment'] == case['expected_assessment'] and set(case['required_codes']) <= set(codes)})
    return {'suite_version': suite['version'], 'total': len(rows), 'passed': sum(r['passed'] for r in rows),
            'failed': sum(not r['passed'] for r in rows), 'cases': rows,
            'limitations': 'Recorded response regression checks; not an independent security benchmark.'}
