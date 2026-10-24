"""Offline provider fixtures -> mapped evaluation -> fix -> verify. No tool execution."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from opencaliber.sdk import Client, evaluate_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['openai-responses', 'openai-chat', 'anthropic'], default='openai-responses')
    parser.add_argument('--save', action='store_true', help='Save minimized evidence to the running local console')
    args = parser.parse_args()
    bundle = json.loads(Path(__file__).with_name('bundle.json').read_text(encoding='utf-8'))
    context = {key: bundle[key] for key in ('policy', 'task', 'agent', 'session_id', 'workflow_id')}
    results = []
    for scenario in ('unsafe', 'corrected'):
        context['agent'] = {**bundle['agent'], 'version': 'demo-v1' if scenario == 'unsafe' else 'demo-v2'}
        response = bundle['responses'][args.provider][scenario]
        if args.save:
            observation = Client(failure_mode='raise').observe_response(args.provider, response, **context)
            result = observation['result']
        else:
            result = evaluate_response(args.provider, response, **context)['result']
        assert result['assessment'] == ('violation' if scenario == 'unsafe' else 'clear')
        results.append({'scenario': scenario, 'agent': result['agent'], 'assessment': result['assessment'],
                        'findings': [f for a in result['actions'] for f in a['findings']]})
    print(json.dumps({'provider': args.provider, 'source': 'recorded synthetic fixtures; no live provider request',
                      'executed_tools': False, 'results': results}, indent=2))


if __name__ == '__main__': main()
