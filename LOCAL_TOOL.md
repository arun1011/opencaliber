# OpenCaliber local developer tool

Advisory risk evaluation of AI agent actions, with a local dashboard, findings, configurable rules, evidence export and 70 labeled regression scenarios. No external inference, subscriptions or API keys required. Python 3.10+ standard library only.

## Start

Extract the ZIP to a new folder. On Windows double-click `start-windows.cmd`, or run:

```powershell
python run.py
```

On macOS/Linux: `sh start-macos-linux.sh` or `python3 run.py`.

Open http://127.0.0.1:8787/console . The home page is http://127.0.0.1:8787/ . Stop with Ctrl+C. If port 8787 is in use, run `python -m opencaliber.agent_server --port 8788` and open the corresponding URL.

## Narrated user walkthrough

The home page has a ten-chapter video covering setup, agent identity, findings, result interpretation, provider mappings, corrections, configuration, regression checks, SDKs and redacted storage. It uses current console screenshots, labeled illustrations and Microsoft David synthetic narration at a moderate instructional pace. English captions are burned in; WebVTT captions and a transcript are available on the home page. The runtime ZIP excludes the marketing page and video files.

## Integrate with an agent

Normalize tool events to the schema in `examples/agent_trace.json`. The engine is model-neutral: it can evaluate Gemini, Claude or any other agent's supplied events, but does not automatically discover or intercept them.

### Python, no server required

From the extracted directory:

```powershell
python examples/integrate_agent.py
```

For another Python project, add the extracted directory to its PYTHONPATH, then:

```python
from opencaliber import evaluate_trace
result = evaluate_trace(trace)
if result['assessment'] != 'clear':
    # Route to your review workflow; do not execute here.
    pass
```

`evaluate_trace(trace, config)` accepts an optional complete configuration dictionary. Import `DEFAULT_CONFIG` from `opencaliber.agent_engine` as a starting point. Direct Python evaluation does not save a dashboard record; use the HTTP API for persistence.

### HTTP, any language

Start the server, then POST JSON `{ "trace": ... }` to `/api/evaluate` with `Content-Type: application/json`. The response includes an evaluation ID and structured results; the dashboard updates when refreshed.

```python
import json, urllib.request
request = urllib.request.Request(
    'http://127.0.0.1:8787/api/evaluate',
    data=json.dumps({'trace': trace}).encode(),
    headers={'Content-Type':'application/json'})
result = json.load(urllib.request.urlopen(request))
```

### CLI and tests

```powershell
python -m opencaliber.agent_cli evaluate --input examples/agent_trace.json
python -m opencaliber.agent_cli benchmark --output report.json
python -m unittest discover -s tests -v
```

## Review model and limitations

`violation`: an explicit declared task or policy rule triggered. `review`: uncertainty or a review signal. `clear`: no implemented rule triggered, never a guarantee of safety. Scores are heuristic severities, not calibrated probabilities. The current engine does not semantically infer arbitrary goals and has no trained LLM connection.

Scope, approval and sensitivity labels are caller-supplied and unauthenticated. There is no tool execution, network firewall, DNS resolution, sandbox, live-agent connector or automatic containment. Resource budgets cover one trace only. Shell inspection uses incomplete patterns. Normalize paths to absolute POSIX paths. Untrusted text checks do not establish prompt injection or causality.

The 70 synthetic cases test implemented rules, not independent security effectiveness. The suite uses active configuration plus fixture-specific overrides; inspect mismatches after changing policies.

History and configuration are stored in `artifacts/agent-console.sqlite3` under the extracted folder. The server binds only to loopback, checks host/origin, and serves the `web/` directory. It has no multi-user authentication or at-rest encryption. Do not expose it to a network. Redact sensitive traces and protect the local files.

The downloadable ZIP is assembled from a fixed source allowlist and excludes your database, private traces, model weights and credentials. It does not include the separate model-training research. Original software is licensed under Apache-2.0. See LICENSE, NOTICE and LICENSING.md in every package; third-party materials retain their own terms.

## Agent attribution and fix guidance

New console evaluations require an agent ID and version. API/Python/CLI callers can include `"agent": {"id": "invoice-agent", "version": "v0.3.2"}` and an optional `"workflow_id"`. Missing identity is displayed as unattributed, including historical runs. Identity is caller-supplied, not authenticated.

Search evaluations and findings by agent, version or workflow. Each new finding includes rule-based remediation with what to change and how to verify. Inspect the action, task scope and configuration before choosing a change. Older findings require replay to generate this guidance. Replay preserves the submitted agent version; update it when testing a changed agent. Exported evidence retains identity and remediation. Workflow IDs are labels, not cross-agent correlation. Each trace still uses one task scope for one agent.

## Provider integration helpers

Use the console Connect agents page for completed OpenAI Responses, OpenAI Chat Completions and Anthropic Messages tool calls. Versioned custom tool mappings, Python and typed Node helpers, redacted storage and runnable provider examples are included. Start with `python examples/adoption/provider_demo.py`. See [ADOPTION.md](ADOPTION.md) for setup, limitations, optional live mock tools, privacy and CI commands.

## Sequence rules

In Configuration, use the backup-before-delete sample or enter a sequence_rules JSON array. See docs/sequence-rules.md and examples/sequence_config.json. Instrument outcomes in your executor; model responses alone do not prove tool success. These checks evaluate only the supplied ordered trace and do not execute or block actions.
