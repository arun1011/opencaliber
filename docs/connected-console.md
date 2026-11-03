# Connected-agent console

The console provides Agents Dashboard, Connect an Agent, Compare agent versions, Detection capabilities, Regression tests, Advanced settings and Developer Guide. All monitoring and comparisons use connected agents and their recorded runs. No run uploads are required.

## 1. Agents Dashboard

Lists every registered agent with its mode, latest workflow status, explicit business outcome, run history, findings, recommendations and monitoring gaps. The displayed history is bounded to the latest 1,000 saved records. Agents whose recent run falls outside that window remain listed with a refresh notice. Completed is a workflow state, not inferred task success.

Inspect latest run for actions, blocked attempts, policy evidence and remediation. Diagnose run loads opted-in objective and selected output context against the saved run policy. Multi-agent jobs group explicit trajectory IDs and show graph findings. Graph-only participants without a registered executor are identified; graph participation alone does not establish policy monitoring.

Gaps include unsupported tools, absent argument constraints, missing scope, contract examples, outputs, task-success assertions, experiment metadata and missing graph evidence. The latest scope is application-reported. These checks cannot discover hidden branches or prove that all actions are wrapped. Test allowed, denied, failed, retry and handoff paths.

## 2. Connect an Agent

Start `python run.py`, then run `python examples/connected_versions/run.py` in another terminal from the repository or runtime package. It creates two tracked versions with three common synthetic cases. Real SQLite reads are wrapped; v1 intentionally selects resolved tickets instead of unresolved ones. The example sends outputs, business assertions, zero estimated provider cost, elapsed run time and related graph spans automatically.

Use TrackedExecutor around every external operation. Supply agent ID/version, a stable tracking ID, the authorized task tool/resource scope and per-tool interface contracts. Advanced settings controls approved values, limits and prerequisites. Local config and contract_mode are independent guards and may be stricter than central policy.

Enable diagnosis=True and a capture_output callback to retain selected output fields. It also retains objective/action context in the console database. Redact sensitive values. Configure diagnosis_verifications for explicit expected-output checks. Standard minimized tracking cannot recover absent original outputs later. Ordinary offline queues omit diagnosis context; graph delivery has no durable queue. Check delivery status.

Before leaving the executor, call:

```python
agent.record_outcome(task_success=business_assertion,
                     cost_usd=reported_cost,
                     cost_source="provider_reported")
```

Use estimated only for estimates, and not_reported with no cost when unavailable. The wrapper measures total elapsed workflow time, including instrumentation overhead; this is not isolated model latency. Missing success remains unknown. A callback returning normally or a 200 response does not establish task completion.

For multi-agent jobs, propagate a unique trajectory_id and parent span ID in your own task messages. Pass trajectory_id to each TrackedExecutor and use Trajectory for agent, handoff and tool spans. Report depends_on, retry_of and dependency_status at dispatch as applicable. Each worker has its own executor identity and policy evaluation. Cross-agent graph dependencies are diagnostic and do not grant tool permission or share executor sequence state. Keep destructive prerequisite chains within one coordinator-owned executor unless a reviewed shared-state design exists.

Remote workers need the authenticated internal HTTPS endpoint and token. TrackedExecutor reads OPENCALIBER_ENDPOINT and OPENCALIBER_TOKEN. Pass them explicitly to Trajectory. Do not send telemetry to the static public website.

## 3. Compare agent versions

Select baseline and candidate from connected tracking-ID/version cohorts. Only completed workflows are included. Overall metrics are descriptive: task success with its reported denominator, policy violations, output-diagnosis failures, known tool-step validity, cost provenance, latency and linked whole-job trajectory findings. Missing evidence stays unknown.

Supply evaluation metadata at executor creation:

```python
evaluation={
    "experiment_id": "release-test-42",
    "case_id": "billing-ticket",
    "input_sha256": canonical_input_sha256,
    "success_criterion": "expected-ticket-id-v1",
    "assignment": "paired",  # paired, randomized, or observational
}
```

Matching requires identical experiment, case, input fingerprint, success criterion, policy fingerprint, tool-contract fingerprint and initial-state fingerprint. The latest repeated case per cohort is selected; earlier repeats remain in overall results. Both cohorts must contain the same actual inputs, environment and evaluation criteria for a meaningful comparison. Hashes alone cannot validate that claim.

The matched result reports observed success differences and failure examples to support review. No randomized assignment is performed by OpenCaliber. Your application must implement traffic assignment, isolation, timeouts and side-effect handling. Randomized labels are caller-supplied, not verified. Results are not a causal estimate or significance test. Small samples, mixed cost provenance and changed environments must be considered before promotion. No automatic winner is inferred when outcomes or matched evidence are missing.

## Shared settings and regression APIs

One window contains shared policy settings, a per-tool check builder, sequence-rule configuration, connected-run contracts, regression tests and gap reports. New registrations inherit the platform mode. Saved changes apply to subsequent online actions; history retains its policy snapshots.

Legacy agent overrides remain active unless the explicit replace-overrides checkbox is selected when saving. The dashboard and configuration window identify them. Replacing overrides resets those agents to the platform policy. Application-local guards remain independent.

The check builder supports exact allowed values, URL hosts, POSIX path roots and numeric bounds on canonical tool fields. Allowed values from the builder are strings; use the JSON review field for numeric or Boolean values. Adding a field rule replaces that field's previous rule in the draft. Review before saving. New unsupported tool semantics require reviewed evaluator implementation and tests; a label or natural-language request does not install a detector.

Contracts are created from original context captured by an existing connected run. Select the run, give the case a unique ID/name, choose expected assessment and required codes, preview and save. This retains original action metadata, so use appropriate synthetic or approved evidence. Redacted historical traces are rejected as contract sources. New contracts use current platform settings with no frozen override; included legacy cases may carry their own explicit overrides. Required codes are a subset, not an exact finding list.

Run contract tests in the same window and review mismatches. Passing tests do not establish independent security assurance. They test evaluator behavior on captured action metadata, not rerun external tools. Expected-output verifications and per-tool runtime contracts remain application-declared; missing relevant tests and arguments are highlighted.

## Diagnosis and interpretation

After each captured run, deterministic and expected-output diagnosis runs automatically. Semantic review is requested from that run and requires the configured local model. It is advisory and cannot erase failed checks or change execution policies. Unknown context, outputs or model failures remain unknown. See context-diagnosis.md, trajectories.md and step-reliability.md for schemas and limitations.

## Add a missing detection capability

Each gap in Detection capabilities opens a guided next step. Use the four-step detector wizard for new supported code checks, or the evidence instructions when integration changes are needed. [Develop custom checks](custom-checks.md) covers optional coding models, test expectations, activation and evidence verification.

See [Console guide](console-guide.md) for current sidebar navigation and screenshots.
