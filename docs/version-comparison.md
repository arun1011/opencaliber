# Version comparison and review driven improvement

OpenCaliber compares two agent versions against the same case IDs, input fingerprints, expected rule outcomes and policy snapshot. Task success is supplied by an application assertion; it is separate from policy compliance and contract matching. Proposals identify evidence to investigate and tests to add. They never mutate a policy, agent, prompt or deployment.

## Run your agents

Use Python 3.10+. Import the module from the console distribution or source checkout. These callbacks are application-owned synchronous functions. Configure their provider/database timeouts and side effects yourself; the runner is not a sandbox.

```python
from opencaliber.comparison import run_versions, compare
from opencaliber.agent_engine import DEFAULT_CONFIG
import json

cases = [{
    "id": "invoice-summary",
    "input": {"terms": ["invoice"], "limit": 100},
    "expected": {"assessment": "clear", "required_codes": []},
}]

def version_one(payload):
    output, trace, usage = your_v1_agent(payload)
    return {"trace": trace,
            "task_success": assert_summary_contract(output, payload),
            "cost_usd": usage.get("cost_usd"),
            "cost_source": "provider_reported" if usage.get("cost_usd") is not None else "not_reported"}

def version_two(payload):
    output, trace, usage = your_v2_agent(payload)
    return {"trace": trace,
            "task_success": assert_summary_contract(output, payload),
            "cost_usd": usage.get("cost_usd"),
            "cost_source": "provider_reported" if usage.get("cost_usd") is not None else "not_reported"}

bundle = run_versions(cases, version_one, version_two,
    agent_id="invoice-agent", baseline_version="v1", candidate_version="v2",
    config=DEFAULT_CONFIG)
report = compare(bundle)
with open("comparison-input.json", "w", encoding="utf-8") as f:
    json.dump(bundle, f, indent=2)
```

Your agent functions and assertion must be implemented by your application. Return the actual canonical trace and an independent business-success assertion. Use TrackedExecutor.trace when appropriate, but include failed/rejected proposals from your application evidence when they are relevant; executed traces alone do not contain every rejected attempt. Do not fabricate successful outcomes from model response completion. The runner adds agent identity only if absent; supplied identities must match the declared version.

The runner deep-copies inputs, hashes the original JSON and alternates baseline/candidate order by case. One run is recorded per version/case. A callback exception records only its type, a failed task assertion and elapsed time; cost remains unknown and no trace is invented. Partial external effects may exist. Invalid result schemas fail the comparison rather than silently turning them into successful cases. There is no automatic retry or timeout termination. Input copies do not isolate external state: use independent databases, provider sessions, files and caches, control randomness, and reset fixtures between versions and repetitions.

## Use the console

For connected runs, open **Compare agent versions**, select baseline/candidate cohorts and compare their shared cases. See [Console guide](console-guide.md). The bundle APIs documented below remain available for programmatic/offline comparisons; the console no longer requires importing a result bundle.

Saved reports are in the console SQLite comparisons table and survive restart. The source bundle's raw inputs and traces are not persisted in that table, but case IDs and minimized finding text remain sensitive. Keep original inputs/configuration securely for reproduction. Exported input bundles can contain raw trace metadata. Stored comparisons are excluded from downloadable releases. Only POST /api/comparisons creates a report; it does not update configuration, review notes or agent code. Hosted endpoints retain the existing HTTPS, origin and workspace-authentication boundaries.

GET /api/comparisons lists recent reports; GET /api/comparisons/ID retrieves one; GET /api/comparisons/example produces an illustrative synthetic bundle. POST /api/comparisons accepts {"comparison": bundle}. Reports can also be generated offline with compare(bundle); direct calls do not save console history.

## Interpret metrics

- Task success rate requires every case to report true or false. Unknown assertions make the aggregate unknown, rather than counting them as failures or successes.
- Policy violations count evaluated traces whose assessment is violation. Execution errors without traces are shown separately; absence of a trace is not a clean evaluation. The violation-count delta is not comparable when either version lacks any paired trace.
- Contract match means the expected assessment and required codes matched. A deliberately negative test can match its contract while recording a policy violation.
- Cost is USD, with provider_reported, estimated or not_reported provenance. A complete total and delta require all costs. Zero is valid only when explicitly reported. Partial reported sums are available in exported metrics and are not presented as comparable full totals.
- Callback latency uses perf_counter in the runner. Imported results can declare reported timing. Means/deltas require every case to report latency. This is not automatically end-to-end user latency.
- Input hashes establish recorded pairing, not independent proof that a client ran the same inputs. Success assertions, timing provenance and costs are application-supplied.

The demo runs synthetic in-memory callbacks, produces simulated action metadata and estimates API cost at zero. It deliberately shows v2 reducing policy violations while failing a summary-quality case. Its measured Python callback latency does not benchmark real models or external systems.

## Adaptive proposals

The initial engine uses deterministic comparison evidence. It proposes boundary/sequence tests for candidate findings, outcome regression investigation, exception/idempotency tests and missing-measurement work. Higher complete reported costs can prompt review. Latency proposals require an observed mean increase above both 10 ms and 10 percent, and still request repeated measurements. It does not claim to train a model or establish a cause.

Every proposal records evidence case IDs, its basis, a suggested change, review_required=true and applied=false. Review success assertions and failure examples before acting. Test allowed/denied paths and use held-out cases so proposals do not overfit the suite. Keep code, policy and release changes in your own review process. No endpoint applies these proposals automatically.

## Tool-step evidence and recovery

Return `execution_evidence` from each wrapper after its with block has finished. The comparison evaluates declared contracts, initial facts and all attempted calls, including rejected operations. It separates task outcomes from policy and tool-step checks. Missing evidence stays unknown, and a changed contract/state fingerprint prevents treating the valid-run delta as a controlled comparison.

The report shows runs with every call confirmed, the first observed invalid step, validated progress, recovery after an invalid call and step-by-step views. Earlier unknown evidence can prevent an exact first-invalid position. No recovery percentage is shown when there are no eligible failures. Short completed runs stop contributing at later steps in the all-runs view; the active-runs view includes only cases reaching that step. Missing evidence yields bounds, not an invented point estimate.

Use `python examples/step_checks/agent.py` for a runnable, isolated SQLite-to-file example. Register real tool interfaces and use explicit extractors for typed values/state. These are application-supplied checks, not independent replay of live systems. See docs/step-reliability.md for the contract format, enforcement and post-operation exception handling.
