<img src="web/assets/logo.svg" alt="OpenCaliber logo" width="64" height="64">

# OpenCaliber

Advisory risk evaluation of AI agent actions, with a local dashboard, findings, configurable rules, evidence export and 70 labeled regression scenarios. The evaluation engine and desktop console require no external inference, subscriptions or API keys and use the Python 3.10+ standard library. Optional live agent starters require provider credentials and may incur charges; hosted deployment uses the dependencies in requirements.txt.

## Watch the walkthrough

[![Watch the OpenCaliber walkthrough: download, evaluate agent actions, inspect findings and verify corrections](web/media/opencaliber-poster.jpg)](https://github.com/arun1011/opencaliber/blob/main/web/media/opencaliber-walkthrough.mp4)

A six-minute walkthrough of setup, tool policies, sequence checks, integrations, enforcement and interpreting findings, with narration and English captions.

## Start

For a fresh Git clone, first generate the downloadable agent packs (Python standard library only):

```sh
python tools/build_agent_library.py
```


Clone or download this repository. On Windows double-click `start-windows.cmd`, or run:

```powershell
python run.py
```

On macOS/Linux: `sh start-macos-linux.sh` or `python3 run.py`.

Open http://127.0.0.1:8787/console . The home page is http://127.0.0.1:8787/ . Stop with Ctrl+C. If port 8787 is in use, run `python -m opencaliber.agent_server --port 8788` and open the corresponding URL.

## Integrate with an agent

Normalize tool events to the schema in `examples/agent_trace.json`. The engine is model-neutral: it can evaluate Gemini, Claude or any other agent's supplied events, but does not automatically discover or intercept them.

### Python, no server required

From the repository directory:

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

Scope, approval and sensitivity labels are caller-supplied and unauthenticated. The evaluator does not execute tools. The optional Python GuardedExecutor can reject callbacks before dispatch in enforce mode. No network firewall, DNS resolution, sandbox or automatic live-agent connector is included. Resource budgets cover one trace only. Shell inspection uses incomplete patterns. Normalize paths to absolute POSIX paths. Untrusted text checks do not establish prompt injection or causality.

The 70 synthetic cases test implemented rules, not independent security effectiveness. The suite uses active configuration plus fixture-specific overrides; inspect mismatches after changing policies.

History and configuration are stored in `artifacts/agent-console.sqlite3` under the extracted folder. The server binds only to loopback, checks host/origin, and serves the `web/` directory. It has no multi-user authentication or at-rest encryption. Do not expose it to a network. Redact sensitive traces and protect the local files.

The downloadable ZIP is assembled from a fixed source allowlist and excludes your database, private traces, model weights and credentials. OpenCaliber original software is licensed under Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [licensing scope](LICENSING.md). Every downloadable runtime and agent pack includes these files.

## Project and contribution

OpenCaliber is an independent personal open-source project. See [contribution guidance](CONTRIBUTING.md) and [security reporting](SECURITY.md).

The current release is a deterministic evaluation toolkit; it does not include a trained anomaly model.

## Walkthrough

The home page includes a captioned walkthrough. Media and branding reuse have separate considerations described in LICENSING.md.

## Developer documentation

- [Integrating agents and provider tool calls](ADOPTION.md)
- [Configuring and running evaluations](LOCAL_TOOL.md)
- [Deployment instructions](docs/elastic-beanstalk.md)
- [Contributing and testing changes](CONTRIBUTING.md)

## Sequence-dependent checks

Engine 0.4 supports opt-in rules such as backup-before-delete for the same resource. Configure them in the console, supply application-recorded execution outcomes, and inspect matched or missing prerequisite evidence. [Configuration, runnable examples and trust limits](docs/sequence-rules.md).

## Adoption utilities

Use policy profiles, the application execution wrapper, offline MCP and Databricks audit imports, coverage reports and CI evaluations. Start at [enterprise integration building blocks](docs/enterprise-adoption.md) or the console Adoption and coverage page. These utilities do not add cloud authorization or datasource inspection.

## Per-tool resource and argument policies

Engine 0.5 adds exact-value allowlists, POSIX directory boundaries, exact URL hostnames and inclusive numeric limits per canonical tool. Rules narrow existing global/task restrictions. Configure them in Console Configuration or import [the example config](examples/tool-policy-config.json). See [policy semantics, integration and execution limits](docs/tool-policies.md). Custom flat scalar arguments are supported by Python and Node projections and removed from redacted history.

## Database search and summarization example

See [examples/database_summary](examples/database_summary/README.md) for a runnable SQLite-to-mock-LLM workflow with OpenCaliber checks before each callback, policy JSON, five scenarios and tests. It demonstrates blocked transfers and operational failures without credentials or network calls.

## Creator & Open Source Lead

**[Arun Kumar](https://www.linkedin.com/in/arunkumar1011/)**\
*Causal Inference & AI Research*

I created OpenCaliber as an open-source project to learn and collaborate with developers on evaluating AI agent actions and inspecting policy findings. [Connect on LinkedIn](https://www.linkedin.com/in/arunkumar1011/) to discuss the project and collaboration.
