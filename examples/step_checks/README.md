# Tool step checks

OpenCaliber records every emitted wrapper call, including rejections and retries. It checks explicit tool interfaces, returned-value references and state requirements, alongside the separate policy and task-result checks.

## First run

Start the console, then run:
```
python examples/step_checks/agent.py
```
The example creates a synthetic in-memory SQLite database and writes a generated report inside the chosen output directory. Version v1 attempts to write before obtaining a record ID. That callback is rejected, then the agent looks up the record and successfully retries. Version v2 looks up first. Both tasks succeed, but the earlier invalid call is retained for v1. Import outputs/step-checks/comparison-input.json in Compare agent versions to inspect the difference.

There are no provider calls. The reported zero API cost is an estimate for this local example. Each version uses its own database and output subdirectory. Logical /workspace resources are application mappings, not an OS sandbox. The optional output path argument must be a directory you intend for this synthetic example.

## Add contracts to a wrapper

```python
with TrackedExecutor(
    agent={"id": "ticket-agent", "version": "1"},
    task={"goal": "Look up a record before writing", "allowed_tools": ["database.read", "file.write"],
          "allowed_resources": ["tickets", "/workspace/reports/report.txt"]},
    tool_contracts=CONTRACTS,
    initial_state={"record_loaded": False},
    contract_mode="enforce",
) as agent:
    row = agent.run(read_action, read_ticket, success=lambda value: value is not None,
        extract_outputs=lambda value: {"record_id": value[0]},
        state_updates=lambda value: {"record_loaded": True})
    producer = agent.attempts[-1]["attempt_id"]
    agent.run(write_action, write_report, success=lambda count: count > 0,
        references={"record_id": {"attempt_id": producer, "output": "record_id"}})
# Export only after leaving the with block, so complete is true.
evidence = agent.execution_evidence()
```

The referenced argument must contain the exact typed value produced by the named earlier attempt. Forward, missing and consumed references fail. A prior producer with unknown completion remains unknown; the system does not invent its output. Contracts define flat scalar arguments/outputs using string, integer, number or boolean, required arguments, scalar equality preconditions, expected state effects, availability and optional consumed reference names. This is a bounded contract format, not a full JSON Schema implementation or automatic cloud permission discovery.

`contract_mode="observe"` records problems while allowing the application to proceed; `"enforce"` rejects invalid or unknown preconditions before dispatch. Central policy enforcement remains separate and can be stricter. A policy-only rejection is not automatically evidence that a tool could not execute.

A successful callback and business-success predicate record application-confirmed transition acceptance. Typed output values and state updates are collected only through explicit extractors, and only declared fields are retained locally. Missing output/state evidence is unknown, not proof of success. Post-operation contract failures cannot undo execution.

## Exceptions

- ActionBlocked means the rejected callback was not dispatched. Inspect whether the cause was a policy or tool contract.
- EvaluationFailed means pre-dispatch evaluation was unavailable.
- ExecutionEvidenceFailed means the callback ran but evidence extraction or post-operation confirmation failed. Reconcile external state before retrying; do not treat it as an unexecuted action.
- Other callback exceptions can leave partial effects. Their type is recorded; exception text is not collected automatically.

## Reports and privacy

The console shows task outcome, policy findings and tool-step evidence separately. It records the first confirmed invalid call, all attempts and calls with missing evidence. A later successful retry does not erase an earlier invalid call. Comparison reports include the fraction of fully confirmed runs, validated progress, recovery outcomes and step-by-step views, alongside costs and latency. Recovery has no percentage when no run had an invalid call. Incomplete logs or unknown transitions do not become successful runs; bounds and unknown values are shown instead. Short completed runs stop contributing at later steps in the all-runs view, while the active-runs view includes only runs that reached that step.

Contracts, state facts, produced IDs, transition acceptance and task success are application-supplied evidence. They are not independently verified replay of your external systems. An operation can be runnable yet violate policy or fail its business goal. No reliability score certifies security or correctness.

Live tracking sends only minimized attempt summaries: IDs, tool names, statuses and reason codes, plus hashes of contracts/state. Raw callback data, extracted output values and state facts are not sent by this feature. Explicit execution_evidence exports contain those scalar values and must be protected. Never use credentials or sensitive record contents as identifiers. Only wrapped calls are captured; logs are bounded to 200 attempts and delivery remains best effort.

Library packs include minimal tool contracts that check the declared interface and callback completion. Extend them with the business-state evidence your agent actually needs; a minimal contract is not complete coverage. After updating source, rebuild downloadable agent packs so the new wrapper module is included.
