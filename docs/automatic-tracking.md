# Automatic agent tracking

## Daily workflow
1. Extract the console ZIP. Install Python 3.10+ and run `python run.py` (macOS/Linux: `python3 run.py`). Keep it running and open http://127.0.0.1:8787/console.
2. Run a downloaded library agent with `python agent.py --demo`, or wrap your project operations with `TrackedExecutor`. The agent registers its tracking ID on its first event.
3. Open **Agents Dashboard** to inspect the run. Use **Advanced settings** to review shared policy defaults and existing overrides.
4. Open **Activity** and **Problems**. Select a workflow to inspect action IDs, triggered rules, evidence and suggested changes. Fix the application or policy and run again.


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

## Regression tests and custom capabilities

Open **Regression tests** to select a captured run, set expected policy assessment/codes, preview, save and run tests. No uploads are needed. Open **Detection capabilities** for missing-check guidance, the detector wizard and optional coding models. Custom detector tests are separate from saved-run policy tests.

Use **Advanced settings** for shared policy boundaries and mode. A tracking ID selects the existing override or workspace default; overrides are complete policies rather than incremental overlays. Changes affect subsequent online events. Scope and coverage gaps appear in Agents Dashboard and Detection capabilities.

See [Console guide](console-guide.md) for every menu, current screenshots, wrapper examples and troubleshooting.
