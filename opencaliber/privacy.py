"""Minimize persisted evidence AFTER evaluation. Not a general PII detector."""
import copy
from urllib.parse import urlsplit


def resource_label(value):
    try:
        url = urlsplit(value)
        if url.scheme in ('http', 'https') and url.hostname:
            return url.scheme + '://' + url.hostname + '/[redacted-path]'
    except ValueError:
        pass
    return '[redacted-resource]'


def minimize_evidence(trace, result):
    trace, result = copy.deepcopy(trace), copy.deepcopy(result)
    trace['task']['goal'] = '[redacted]'
    if 'allowed_resources' in trace['task']:
        trace['task']['allowed_resources'] = [resource_label(x) for x in trace['task']['allowed_resources']]
    for action in trace['actions']:
        action['resource'] = resource_label(action['resource'])
        if 'resource_version' in action: action['resource_version'] = '[redacted-version]'
        if 'untrusted_text' in action: action['untrusted_text'] = '[redacted]'
        args = action.get('arguments', {})
        if 'command' in args: args['command'] = '[redacted]'
        if 'destination' in args: args['destination'] = resource_label(args['destination'])
    for action in result['actions']:
        action['resource'] = resource_label(action['resource'])
    result['storage_mode'] = 'redacted'
    result['replayable'] = False
    return trace, result
