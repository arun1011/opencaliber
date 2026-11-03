# Context-aware failure diagnosis

Open **Agents Dashboard → Diagnose run**, or open a run and select **Diagnose this run**. The console loads its captured objective, ordered actions, selected outputs and recorded central policy. You do not upload evidence files or paste JSON.

Enable capture once in the agent wrapper:

```python
with TrackedExecutor(
    agent={"id": "ticket-reader", "version": "1"},
    tracking_id="ticket-reader",
    task=authorized_task,
    diagnosis=True,
    capture_output=lambda action, rows: {
        "statuses": [row["status"] for row in rows],
        "count": len(rows),
    } if action["tool"] == "database.read" else None,
    diagnosis_constraints=["Only unresolved billing tickets are relevant"],
) as agent:
    rows = agent.run(action, query, success=lambda value: bool(value))
```

Your application supplies authorized_task, action and query. capture_output receives the completed action and callback result; return selected JSON evidence or None. Capture exceptions warn and leave evidence unavailable without changing callback results. Keep selected output under 100 KB per run. diagnosis=True explicitly opts into storing the actual objective, declared action arguments, selected output and constraints in the console database. Redact sensitive fields before returning them. Without this opt-in, standard tracking retains its existing minimized history. The offline tracking spool strips diagnosis context; offline events cannot restore missing outputs.

At completion, the console automatically saves deterministic and supplied expected-output verification results. Semantic review runs only when requested from the run, using the configured local model. Model results are retained with that captured run snapshot. The run policy snapshot is used even if someone subsequently edits the current policy. Policy can change during a workflow: the captured snapshot reflects the latest accepted context event, not a claim that all earlier actions used identical settings.

Old runs without captured context still show recorded policy findings. Their redacted action metadata is never replayed as original evidence. Enable capture and run the agent again to obtain output-aware diagnosis. Only reported actions and selected outputs are available; exceptions or unwrapped operations may have no output evidence.

Agent Library config.json now supports diagnosis_enabled. It defaults to false. Setting it true sends objective/action context and conservative output type/length summaries. For domain-specific diagnosis, customize capture_output to return reviewed fields such as statuses or totals; type/length alone cannot establish business correctness.

## Evidence

Use `trace` with the user objective in `trace.task.goal` and ordered actions, `outputs` keyed by action ID, textual `constraints`, and `verifications`. A verification has `id`, `action_id`, `path` (JSON object keys), `expected` and `source`. The engine compares selected output with a separately supplied expected value using type-sensitive JSON equality. Missing output is unknown. Expected values and source labels are supplied by the developer, not authenticated truth. Do not generate expected values from the same agent response you are checking.

For connected runs, the console supplies the recorded policy snapshot automatically. For standalone Python diagnose(bundle) experiments, optional config is a complete snapshot and omission uses engine defaults. The bundle is limited to 200 KB, 200 actions, 50 constraints and 50 expected-output checks.

## Local semantic model

Install and run Ollama and pull a model suitable for your hardware. Before starting the console, set the name of an installed model:

```powershell
$env:OPENCALIBER_DIAGNOSIS_MODEL = "your-installed-model"
$env:OPENCALIBER_DIAGNOSIS_ENDPOINT = "http://127.0.0.1:11434"
python run.py
```

The endpoint is server-configured and restricted to loopback HTTP; browser requests cannot choose a host. Requests use `/api/chat`, a JSON output schema, no tool access, temperature zero, bounded output and a 60-second request timeout. The model receives the objective, ordered arguments, selected outputs, constraints and verification expectations only when requested. Its system instruction treats embedded instructions as untrusted evidence. This reduces risk but does not eliminate prompt injection or incorrect reasoning. Model findings are always review hypotheses. Unknown action references, malformed/contradictory responses and model failures produce unavailable/unknown, never a semantic pass.

On a hosted deployment, loopback refers to that server. The model must run there or be exposed through an operator-managed loopback service. No model weights are bundled and no paid provider is called automatically.

## Independent verification in Python

```python
from opencaliber.diagnosis import diagnose

def verify_actual_records(bundle):
    expected_ids = trusted_database_query()  # separate query implementing the objective
    return bundle["outputs"]["read-tickets"]["ids"] == expected_ids

report = diagnose(bundle, use_semantic=True,
                  verifiers={"actual-records": verify_actual_records})
```

These are trusted application-owned callables, never code loaded from JSON or model output. Return True, False or None. Exceptions become unknown. Callbacks can verify database state, recompute arithmetic or check a sandbox artifact. The application must set timeouts, permissions and side-effect boundaries. Configure diagnosis_verifications on the wrapper for automatic expected-output checks at completion. Application-owned callbacks still run only through Python integration. A second model opinion alone is not independent verification.

Run `python examples/context_diagnosis/run.py` for a real SQLite example. It executes an incorrect but policy-permitted query and checks results against a separate objective-based query. Add `--semantic` after configuring a model. The example writes evidence and a report under outputs/context-diagnosis. The example also runs through TrackedExecutor: open connected-support-summary in Agents Dashboard and select Diagnose run. The additional Python-only independent query result is printed separately and is not silently represented as a server-executed verification.

## Interpret results

- `failure_detected`: a policy violation or verification failure exists; inspect its scope and source.
- `review`: rules or semantic hypotheses require inspection.
- `insufficient_evidence`: missing model assessment or verification prevents a combined conclusion.
- `no_issue_found`: configured checks found no issue; not proof of task completion.

Semantic review can disagree with verification. Both results are retained; model agreement cannot erase a failed check. Model identity and prompt version are reported for reproducibility. There is no calibrated accuracy claim or probability score. Evaluate on held-out examples from your own domain before relying on the diagnosis.
