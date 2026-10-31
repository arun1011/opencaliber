"""Completed client-tool calls only. No provider SDK or model calls required."""
import copy
import hashlib
import json
from .tool_policies import argument_name
from .agent_engine import KNOWN_TOOLS, validate_trace

PROVIDERS = ('openai-responses', 'openai-chat', 'anthropic')


def object_value(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {'version', 'tools'}:
        raise ValueError('Policy requires version and tools')
    if not isinstance(policy['version'], str) or not 0 < len(policy['version']) <= 120:
        raise ValueError('Policy version must be 1–120 characters')
    if not isinstance(policy['tools'], dict) or len(policy['tools']) > 100:
        raise ValueError('Policy tools must be a dictionary of at most 100 mappings')
    for name, spec in policy['tools'].items():
        if not isinstance(name, str) or not name or not isinstance(spec, dict):
            raise ValueError('Invalid tool mapping')
        if set(spec) - {'tool', 'resource', 'resource_from', 'arguments', 'data_class'}:
            raise ValueError('Unsupported tool mapping field')
        if spec.get('tool') not in KNOWN_TOOLS:
            raise ValueError('Mappings must use a supported canonical tool')
        if ('resource' in spec) == ('resource_from' in spec):
            raise ValueError('Choose resource or resource_from')
        for field in ('resource', 'resource_from'):
            if field in spec and (not isinstance(spec[field], str) or not spec[field]):
                raise ValueError('Resource selector must be a nonempty string')
        if spec.get('data_class') not in ('public', 'internal', 'pii', 'secret'):
            raise ValueError('Each mapping requires an application-owned data_class')
        args = spec.get('arguments', {})
        if not isinstance(args, dict) or len(args) > 50 or any(not argument_name(k) for k in args):
            raise ValueError('Only supported argument projections may be configured')
        if any(not isinstance(v, str) or not v for v in args.values()):
            raise ValueError('Argument selectors must be nonempty dotted paths')
    return copy.deepcopy(policy)


def select(value, path):
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise ValueError('Required mapped argument is missing')
        value = value[part]
    return value


def tool_calls(provider, response):
    response = object_value(response)
    if provider not in PROVIDERS or not isinstance(response, dict):
        raise ValueError('Unsupported provider or response object')
    if provider == 'openai-responses':
        if response.get('status') not in (None, 'completed'):
            raise ValueError('Use a completed, non-streaming response')
        blocks = response.get('output')
        if not isinstance(blocks, list): raise ValueError('Missing response output')
        calls = []
        for block in blocks:
            if not isinstance(block, dict): raise ValueError('Invalid response block')
            if block.get('type') == 'function_call':
                if block.get('status') not in (None, 'completed'): raise ValueError('Incomplete call')
                calls.append((block.get('call_id'), block.get('name'), block.get('arguments')))
            elif block.get('type') not in ('message', 'reasoning'):
                raise ValueError('Unsupported output type; hosted tools are not intercepted')
    elif provider == 'openai-chat':
        choices = response.get('choices')
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError('Supply one completed Chat Completions choice')
        if not isinstance(choices[0], dict) or not isinstance(choices[0].get('message'), dict):
            raise ValueError('Invalid choice message')
        if choices[0].get('finish_reason') != 'tool_calls':
            raise ValueError('No completed tool_calls choice')
        blocks = choices[0].get('message', {}).get('tool_calls', [])
        if not isinstance(blocks, list): raise ValueError('Invalid tool_calls list')
        calls = []
        for block in blocks:
            if not isinstance(block, dict): raise ValueError('Invalid response block')
            if block.get('type') != 'function': raise ValueError('Unsupported call type')
            f = block.get('function', {})
            if not isinstance(f, dict): raise ValueError('Invalid function block')
            calls.append((block.get('id'), f.get('name'), f.get('arguments')))
    else:
        if response.get('stop_reason') != 'tool_use': raise ValueError('No completed tool_use turn')
        blocks = response.get('content')
        if not isinstance(blocks, list): raise ValueError('Missing message content')
        calls = []
        for block in blocks:
            if not isinstance(block, dict): raise ValueError('Invalid response block')
            if block.get('type') == 'tool_use':
                if block.get('toolset_name'): raise ValueError('Toolset member calls are unsupported')
                calls.append((block.get('id'), block.get('name'), block.get('input')))
            elif block.get('type') not in ('text', 'thinking', 'redacted_thinking'):
                raise ValueError('Unsupported content type; server tools are not intercepted')
    if not calls or len(calls) > 200: raise ValueError('Expected 1–200 completed client-tool calls')
    output = []
    for call_id, name, args in calls:
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
            raise ValueError('Tool call requires id and name')
        if isinstance(args, str): args = json.loads(args)
        if not isinstance(args, dict): raise ValueError('Tool arguments must decode to an object')
        output.append((call_id, name, args))
    return response, output


def normalize_response(provider, response, *, policy, agent, task, session_id, workflow_id=None):
    policy = validate_policy(policy)
    response, calls = tool_calls(provider, response)
    actions = []
    for call_id, name, args in calls:
        spec = policy['tools'].get(name)
        if spec is None:
            # Never guess semantics from the tool name. UNKNOWN_TOOL produces review.
            action = {'id': call_id, 'tool': 'unmapped.' + name, 'resource': '[unmapped]'}
        else:
            resource = spec.get('resource') if 'resource' in spec else select(args, spec['resource_from'])
            action = {'id': call_id, 'tool': spec['tool'], 'resource': resource,
                      'data_class': spec['data_class'],
                      'arguments': {key: select(args, path) for key, path in spec.get('arguments', {}).items()}}
        action['source_tool'] = name
        actions.append(action)
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    trace = {'name': provider + ' tool calls', 'agent': copy.deepcopy(agent), 'task': copy.deepcopy(task),
             'context': {'provider': provider, 'response_id': response.get('id', 'not-supplied'),
                         'session_id': session_id, 'policy_version': policy['version'], 'policy_sha256': digest},
             'actions': actions}
    if workflow_id is not None: trace['workflow_id'] = workflow_id
    validate_trace(trace)
    return trace
