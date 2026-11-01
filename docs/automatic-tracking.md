# Automatic agent tracking

## Daily workflow
1. Extract the console ZIP. Install Python 3.10+ and run `python run.py` (macOS/Linux: `python3 run.py`). Keep it running and open http://127.0.0.1:8787/console.
2. Run a downloaded library agent with `python agent.py --demo`, or wrap your project operations with `TrackedExecutor`. The agent registers its tracking ID on its first event.
3. Open **Monitored agents**. Select **Edit policy** to set rules for that agent, or **Rules & policies** for the shared default.
4. Open **Activity** and **Problems**. Select a workflow to inspect action IDs, triggered rules, evidence and suggested changes. Fix the application or policy and run again.

**Trace actions** lists tool names from example traces and lets you create/test JSON traces. It does not install or execute tools. Advanced provider imports, contract tests and detailed API documentation are under **Developer tools**.

## Add to a Python agent
Copy the `opencaliber` module from a downloaded agent pack into your project. No published pip package is assumed.

```python
from opencaliber import TrackedExecutor

with TrackedExecutor(
    agent={"id": "support-reader", "version": "1"},
    tracking_id="support-dev",
    task={"goal": "Read approved tickets", "allowed_tools": ["database.read"]},
) as agent:
    rows = agent.run(
        {"id": "read-1", "tool": "database.read", "resource": "tickets",
         "arguments": {"records": 100}},
        lambda: read_tickets(limit=100),  # your application's function
        success=lambda value: isinstance(value, list),
    )
```

Use a stable tracking ID per agent/project; use versions to distinguish releases. Each executor creates a workflow ID. Wrap every operation that needs checking. Code outside these wrappers is not observed. `evaluate_trace` alone returns an evaluation and does not send console history.

## Modes and rules
Newly discovered agents start in **Report only**: the central policy records findings without stopping the callback. Select an agent to enable **Enforce**: the tracking wrapper requires a clear central evaluation before dispatch. Application-local guard rules may still block actions independently. Configure paths, hosts, record limits, denied tools and, under Advanced, per-argument or sequence rules. An agent override replaces the default policy, rather than merging it. Returning to the default removes the override.

For enforcement from the first action, set `OPENCALIBER_MODE=enforce` on the agent. An unavailable console prevents dispatch in enforce mode. Report-only events queue minimized metadata for later delivery; queued results are labeled agent-reported and cannot be faithfully re-evaluated from redacted values. Stop tracking explicitly with `OPENCALIBER_TRACKING=off` only when intended; local guards remain independent.

## Company internal domains
GitHub Pages publishes only HTML, video and downloads. It cannot host Python or a shared evaluation database. Its `/console/` page is setup guidance, not a blocked evaluation service. For a shared console deploy `application.py` using the authenticated hosted runtime and point an internal HTTPS domain at that service.

Set on the console server:
```
OPENCALIBER_PUBLIC_ORIGIN=https://opencaliber.internal.example
OPENCALIBER_ADMIN_TOKEN=<random secret of at least 32 characters>
OPENCALIBER_DATA_DIR=<absolute persistent data directory>
OPENCALIBER_STORAGE_MODE=retained
```
Retained mode requires the parent data volume to be mounted. `instance` is an explicit disposable staging alternative. Use Python 3.11+ and install `requirements.txt`. Run one worker, for example `uvicorn application:application --host 0.0.0.0 --port 8000`, behind an HTTPS reverse proxy. See `docs/elastic-beanstalk.md` for the AWS storage and proxy setup. Trust forwarded protocol headers only from the actual proxy, not arbitrary clients. Preserve the configured Host header and use one canonical origin with no URL subpath. Internal DNS and TLS trust must work on every agent machine.

Open `https://opencaliber.internal.example/console` and authenticate with username `admin` and the configured token as password. On remote agent machines set:
```
OPENCALIBER_ENDPOINT=https://opencaliber.internal.example
OPENCALIBER_TOKEN=<same workspace token, stored privately>
OPENCALIBER_TRACKING_ID=support-production
OPENCALIBER_MODE=enforce
```
Do not point agents at the public GitHub Pages domain. Loopback always refers to the machine running that agent. Remote HTTP, redirects, wrong Host/Origin and unauthenticated workspace access are refused. This is a single shared workspace, without per-user roles or tenant isolation. Do not expose `run.py` to the network or disable origin checks to enable internal hosting.

## Data and troubleshooting
Online evaluation receives declared tool metadata: IDs, resource paths/URLs, selected scalar arguments and application-reported outcomes. History is minimized after evaluation. Callback contents, database rows, prompts and model responses are not automatically collected. Never put credentials into trace fields. Protect SQLite history, backups and private environment files.

If the console reports a missing endpoint, stop the old server, launch `python run.py` from the updated package and refresh. If an agent does not appear, check endpoint reachability, TLS certificate trust, token, tracking ID and that operations use `TrackedExecutor`. Report-only queues are under `outputs/.opencaliber-tracking`; flush with `python -m opencaliber.tracking flush --spool outputs/.opencaliber-tracking`. Rule scores are severity, not calibrated probabilities. Clear is not a security guarantee.

## Add workspace contract cases

Open **Developer tools → Add contract cases**. Enter a unique case ID and name, choose an example or paste a synthetic trace, and set the expected assessment and required finding codes. Optional configuration overrides replace selected fields of the current default policy. Use a full policy snapshot when you need a reproducible test independent of future defaults. Preview before saving. A mismatch may be saved deliberately to document a failing regression test. Preview does not persist an evaluation or case.

Saved cases appear alongside the 70 included cases in **Run contract tests**. The suite checks the expected assessment and that required codes are present; additional finding codes are allowed. Cases are rule regression tests, not a security certification. Up to 500 workspace cases are stored in the console SQLite database, preserved across restarts and excluded from release ZIPs. Traces and policy overrides are stored as entered; use synthetic values, never credentials. Export workspace cases as JSON for version control or review. Adding cases does not change the shipped fixture file or your agent's rules. The current editor adds cases; replacing or deleting an existing case is not supported.

Actionable developer tools have expandable purpose, when-to-use and how-to-use help and a sidebar tooltip. Developer Guide has its own chapter navigation instead.

## Automatic policy assignment and scope review

**Configure agent checks** replaces the earlier Rules & policies label. The wrapper's tracking ID selects an individual policy or the workspace default. An individual policy is complete and replaces the default; it is not an incremental overlay. A different agent ID cannot reuse that tracking ID. The environment variable OPENCALIBER_TRACKING_ID takes precedence over an explicit tracking_id parameter, then the agent ID is the fallback.

The response includes a policy assignment with source, mode and config fingerprint. Inspect `executor.policy_status` after initialization or an operation. The console compares the current configuration and mode with the last recorded online contact. Saving does not push into a running callback; the next online action uses the saved policy. Current-scope metadata is taken only from accepted online events, not minimized offline replays.

The selected-agent coverage view lists declared tools, observed/proposed tools, applicable checks, missing metadata, unsupported semantics and agent-tagged workspace cases. Resource values and argument values are not copied into the scope summary. It flags tools not exercised in the latest workflow. Matching cases are identified by trace.agent.id and tool; their presence is not a passing result or a completeness guarantee. Contract tests use default-plus-case-overrides, so snapshot the intended individual policy when testing it.

Declare the full authorized task.allowed_tools and task.allowed_resources at wrapper creation. Review custom arguments, destructive prerequisites and data classifications, then test allowed and failure paths before enabling enforcement. The engine cannot infer hidden agent capabilities or business requirements from a natural-language goal.

**Developer Guide** is a separate sidebar link after Developer tools. It includes deployment, wrapper setup, policy assignment, coverage, a runnable multi-step workflow, provider-neutral LLM integration, exceptions, queues, tests, multi-agent correlation and synthetic console screenshots. The generic tool-summary box is deliberately omitted from this documentation page.

Run `python examples/controlled_workflow/agent.py --delete-after-backup` for a synthetic SQLite → report → verified backup → guarded deletion workflow. Its README explains missing-backup and callback-failure paths, local-versus-central policies, explicit approval and exit codes.

The console sidebar keeps three developer tools: Test a trace, Add contract cases and Run contract tests. Scope coverage is part of Configure agent checks. Advanced importer APIs remain available for programmatic integrations but do not have separate sidebar screens.
