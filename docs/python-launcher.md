# Connect a Python agent without tool wrappers

Start the console with `python run.py`. Keep it running. In the agent's Python
environment, make the downloaded OpenCaliber package importable (place it alongside
the project or add its root to PYTHONPATH). No new dependency is required.

Replace the startup command, leaving the agent source unchanged:

```sh
# Before
python my_agent.py --my-option value
# Observe this invocation
python -m opencaliber.connect --agent-id support-agent --version v1 -- my_agent.py --my-option value
# Working example included in the download
python -m opencaliber.connect --agent-id sqlite-demo -- examples/observe_agent/agent.py
```

Open Agents Dashboard, search for the agent, then Inspect run and Detected problems.
The connection label is **Observe · Python launcher**. Existing console policies
evaluate observed calls after execution. They never block this connection, even
if the platform uses Block violations. Remove monitoring by restoring the original
startup command. No tool functions need editing to add or remove this connection.

For multiple workers, put this command in a shared job template and use distinct
agent IDs. Use a stable tracking ID for each logical agent, optionally overriding
it with `--tracking-id`. Each process invocation creates a new run. Versions share
identity when the same tracking ID is used. Threads share that invocation's run.
Child processes need their own launcher. Restart workers after changing startup.
The launcher is not an installable tracing daemon and does not attach to running jobs.

## What is captured

- Default `sqlite3.connect` connections: execute, executemany and executescript
  through their default cursors. Simple SELECT/INSERT/UPDATE/DELETE statements map
  to database actions. Other statements and scripts remain unmapped for review.
- `urllib.request`, synchronous `requests.Session.send` and `httpx.Client.send`
  HTTP(S) requests (the latter two only when already installed): method and scheme/hostname only. Redirect
  destinations are observed when urllib dispatches them through its opener.
- Agent/version/tracking identity, per-invocation run ID, dispatch order,
  process elapsed time, lifecycle and bounded exception type.

No SQL text, parameters, database paths, rows, URL paths/queries, headers, bodies,
prompts or generated text are collected. Hostnames can still be sensitive.
Up to 200 actions are captured; stderr reports additional dropped calls.
Snapshots are cumulative, so transport/storage overhead grows with run length.
Measure overhead before fleet rollout. Tracking uses bounded network timeouts
but is synchronous, not a zero-overhead background collector.

## What remains unknown

Async HTTPX clients, direct HTTP clients, files, shell commands, existing
connections, custom SQLite factories and subprocess activity are outside coverage.
Provider SDK calls using these synchronous clients are observed as HTTP operations,
not model-specific actions. HTTPX internal redirects/retries and custom transports
are not reconstructed; only the submitted URL is observed. A successful API call does not establish committed changes, fetched row counts or
business correctness. Action outcomes and task success remain unknown. Statement
classification is conservative, not a SQL parser. Transactions, stored procedures,
agent/subagent handoffs, retries and causal dependencies are not reconstructed.
Parallel dispatch order is not proof of dependency order.

The dashboard may flag missing scope, contracts or output evidence. These are real
limits; do not grant permissions by deriving allowlists from observed behavior.
Use explicit TrackedExecutor integration for pre-dispatch enforcement, selected
output capture, task-success assertions, matched comparisons and multi-agent links.
Do not wrap an already instrumented library agent in this launcher unless duplicate
observations are desired. Use either connection path per operation.

## Remote delivery and failures

Set OPENCALIBER_ENDPOINT to the authenticated HTTPS console and OPENCALIBER_TOKEN
to its token. Loopback refers to the agent's machine; the public GitHub Pages site
does not receive tracking events. Standard tracking queues minimized events under
outputs/.opencaliber-tracking if delivery fails. After connectivity returns, replay
with TrackingClient().flush(force=True) from the same working directory. Offline
events are labeled agent-reported and cannot be faithfully re-evaluated. Keep that
folder private. Failed delivery never prevents the agent from executing.

OPENCALIBER_TRACKING=off disables delivery; restoring the original command also
removes instrumentation. The launcher preserves script arguments, imports and
exceptions and restores its hooks at exit. It is intended for a standalone Python
process, not concurrent embedded launchers or isolation from hostile agent code.

Existing telemetry import (OTLP) and MCP gateway enforcement are separate future
connection paths, not features provided by this launcher.
