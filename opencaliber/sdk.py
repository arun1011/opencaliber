"""Observe-only helpers. Never dispatch tools or grant permission."""
import copy
import json
import math
import time
import urllib.request
from urllib.parse import urlsplit
from .adapters import normalize_response
from .agent_engine import evaluate_trace


class EvaluationUnavailable(RuntimeError):
    pass


class Client:
    def __init__(self, endpoint='http://127.0.0.1:8787', *, timeout=2.0, failure_mode='return_error'):
        url = urlsplit(endpoint)
        if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise ValueError('Use the local loopback HTTP endpoint')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('timeout must be 0–30 seconds, exclusive of zero')
        if failure_mode not in ('return_error', 'raise'): raise ValueError('Invalid failure_mode')
        self.endpoint, self.timeout, self.failure_mode = endpoint.rstrip('/'), timeout, failure_mode

    def observe(self, trace, *, storage='redacted'):
        """Bounded socket timeout; no retries, no execution, no authorization decision."""
        if storage not in ('redacted', 'raw'): raise ValueError('Invalid storage mode')
        request = urllib.request.Request(self.endpoint + '/api/evaluate',
            data=json.dumps({'trace': trace, 'storage': storage}, allow_nan=False).encode(),
            headers={'Content-Type': 'application/json'})
        start = time.monotonic()
        try:
            # Ignore proxy env and reject redirects so traces stay on the selected local server.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                data = json.loads(response.read(4 * 1024 * 1024 + 1))
            if not isinstance(data, dict) or not isinstance(data.get('id'), str) or not isinstance(data.get('result'), dict) or data['result'].get('assessment') not in ('clear', 'review', 'violation'):
                raise ValueError('Invalid evaluator response')
            return {'status': 'evaluated', 'mode': 'observe', 'execution_decision': 'application_owned',
                    'elapsed_ms': round((time.monotonic() - start) * 1000), **data}
        except Exception:
            # Do not echo server errors, URLs or input data into application logs.
            if self.failure_mode == 'raise': raise EvaluationUnavailable('Local evaluation unavailable; no execution decision made') from None
            return {'status': 'error', 'mode': 'observe', 'assessment': None,
                    'execution_decision': 'application_owned', 'error': 'evaluation_unavailable'}

    def observe_response(self, provider, response, **context):
        storage = context.pop('storage', 'redacted')
        trace = normalize_response(provider, response, **context)
        return self.observe(trace, storage=storage)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise EvaluationUnavailable('Redirects are not followed')


def evaluate_response(provider, response, *, config=None, **context):
    """In-process evaluation. No network or persistence; config is application-owned."""
    trace = normalize_response(provider, response, **context)
    return {'trace': copy.deepcopy(trace), 'result': evaluate_trace(trace, config)}
