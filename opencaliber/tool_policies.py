"""Bounded declarative policies over canonical resources and flat scalar arguments."""
import math
import posixpath
import re
from urllib.parse import urlsplit


def argument_name(name):
    return isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) is not None


def scalar(value):
    return (type(value) is bool or
            (type(value) is str and len(value) <= 8000) or
            (type(value) in (int, float) and abs(value) <= 10**12 and math.isfinite(value)))


def validate_tool_policies(policies, known_tools):
    if not isinstance(policies, dict) or len(policies) > 100:
        raise ValueError('tool_policies must be an object with at most 100 tools')
    for tool, policy in policies.items():
        if tool not in known_tools or not isinstance(policy, dict) or not policy or set(policy) - {'resource', 'arguments'}:
            raise ValueError('Tool policies require a supported canonical tool and resource or arguments')
        args = policy.get('arguments', {})
        if not isinstance(args, dict) or len(args) > 50 or any(not argument_name(k) for k in args):
            raise ValueError('Policy arguments must be at most 50 flat identifier keys')
        rules = list(args.values()) + ([policy['resource']] if 'resource' in policy else [])
        if not rules:
            raise ValueError('Tool policy must contain at least one field rule')
        for rule in rules:
            if not isinstance(rule, dict) or not rule or set(rule) - {'allowed_values', 'path_roots', 'hosts', 'min', 'max'}:
                raise ValueError('Unsupported or empty tool field rule')
            for key in ('allowed_values', 'path_roots', 'hosts'):
                if key in rule and (not isinstance(rule[key], list) or len(rule[key]) > 100):
                    raise ValueError('Field allowlists must contain at most 100 entries')
            if 'allowed_values' in rule and any(not scalar(v) for v in rule['allowed_values']):
                raise ValueError('allowed_values requires bounded non-null JSON scalars')
            for root in rule.get('path_roots', []):
                if not isinstance(root, str) or not 0 < len(root) <= 300 or not root.startswith('/') or root.startswith('//') or '\\' in root or '\x00' in root or posixpath.normpath(root) != root:
                    raise ValueError('Use canonical absolute POSIX path roots')
            for host in rule.get('hosts', []):
                if not isinstance(host, str) or len(host) > 253 or re.fullmatch(r'[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*', host) is None:
                    raise ValueError('Use exact hostnames without scheme, port, path or wildcard')
            for key in ('min', 'max'):
                if key in rule and (type(rule[key]) not in (int, float) or not scalar(rule[key])):
                    raise ValueError('Numeric bounds must be finite numbers within one trillion')
            if 'min' in rule and 'max' in rule and rule['min'] > rule['max']:
                raise ValueError('min must not exceed max')
            if sum(('path_roots' in rule, 'hosts' in rule, bool({'min', 'max'} & set(rule)))) > 1:
                raise ValueError('Path, host and numeric rules cannot be mixed for one field')


def matches(value, rule):
    if 'allowed_values' in rule and not any(type(value) is type(v) and value == v for v in rule['allowed_values']):
        return False
    if 'path_roots' in rule:
        if not isinstance(value, str) or not value.startswith('/') or value.startswith('//') or '\\' in value or '\x00' in value or '..' in value.split('/'):
            return False
        path = posixpath.normpath(value)
        if not any(path == root or path.startswith(root.rstrip('/') + '/') for root in rule['path_roots']):
            return False
    if 'hosts' in rule:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
            return False
        try:
            url = urlsplit(value)
            port = url.port
            if url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or url.password is not None or (port is not None and not 1 <= port <= 65535):
                return False
            if url.hostname.lower() not in {h.lower() for h in rule['hosts']}:
                return False
        except ValueError:
            return False
    if {'min', 'max'} & set(rule):
        if type(value) not in (int, float) or not scalar(value):
            return False
        if 'min' in rule and value < rule['min'] or 'max' in rule and value > rule['max']:
            return False
    return True


def violations(action, policies):
    policy = policies.get(action['tool'], {})
    if 'resource' in policy and not matches(action['resource'], policy['resource']):
        yield 'resource'
    for key, rule in policy.get('arguments', {}).items():
        if key not in action.get('arguments', {}) or not matches(action['arguments'][key], rule):
            yield 'arguments.' + key
