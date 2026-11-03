# Multi-agent workflows

Open **Execution graphs** to inspect one workflow across agents and tools. Select a workflow, review findings, then follow the referenced span IDs to their relationships. Old single-agent runs remain in Overview; a graph is available only after graph instrumentation is added.

## Run a working example

Start the console with `python run.py`. From the repository root run:

```sh
python examples/multi_agent/run.py
```

The example reads the actual project README. Timeout, repeated delegation and missing-source branches are deliberate test scenarios. It shows duplicate work, retry, circular delegation, a dependency that had failed at dispatch, missing evidence, and an explicitly attributed downstream failure. Nothing is inferred from hidden agent conversations.

## Instrument an existing agent

```python
from opencaliber.trajectory import Trajectory

graph = Trajectory(trajectory_id="job-unique-123")
with graph.span("Process order", "coordinator", kind="agent") as root:
    with graph.span("Ask lookup agent", "coordinator", kind="handoff",
                    parent_id=root["id"]) as handoff:
        with graph.span("Lookup", "lookup-agent", kind="agent",
                        parent_id=handoff["id"]) as child:
            with graph.span("Read tickets", "lookup-agent",
                            parent_id=child["id"], work_key="tickets-job-123"):
                rows = tracked_agent.run(action, read_tickets,
                                         success=lambda rows: bool(rows))
```

`tracked_agent` is your configured TrackedExecutor and `action` describes the actual operation. Trajectory records relationships; TrackedExecutor continues policy evaluation and execution gating. Neither automatically observes unwrapped code. A successful context exit records success unless you explicitly set the yielded span's status to failed, blocked or unknown. If your callback returns an unsuccessful value without raising, set that status explicitly. Exceptions record failed (ActionBlocked records blocked) and are re-raised. Graph failures warn and appear in `delivery_errors`; they do not grant or revoke tool permissions. Check this list before treating a graph as fully delivered. There is no automatic durable graph queue in this version.

For another process, pass the same trajectory_id and parent span ID through your own task message. Create a Trajectory with the authenticated HTTPS endpoint and token on that worker. Use unique IDs per workflow. Record retries with retry_of, dependencies with depends_on, and an explicit dependency_status map from the orchestration system at dispatch. Remote dependency status defaults to unknown when unavailable. Do not use current completion status as historical dispatch evidence. Parent means nested execution; handoff explicitly records transfer of responsibility.

Set error_source to an upstream span ID only when your application attributes the downstream outcome to that failure. This is attribution, not proof of causality. Supply a stable, non-sensitive work_key only for work that you consider equivalent; repetition is a review candidate, not automatically waste. Retries are excluded from duplicate-work suggestions. No input contents or credentials are required. IDs and labels are stored as supplied: avoid personal data in them.

## Interpretation and limits

- Possible redundant work: successful non-retry spans share kind, name and explicit work_key.
- Circular delegation: a descendant agent returns to an ancestor's agent ID. Intentional recursion can trigger it.
- Missing evidence: a referenced span has not arrived. Reload after late events arrive; this is not proof the action never ran.
- Dependency not ready: the supplied status at dispatch was not succeeded.
- Error propagation: an explicit error_source links failed, blocked or unknown outcomes.
- Parent/dependency cycles: inconsistent hierarchy or impossible prerequisite ordering.

Graphs include only reported spans, capped at 500 per workflow. Arrival order is not wall-clock execution order. There is no cross-machine timing inference, automatic causal discovery, semantic duplicate detection, policy rewriting or agent modification. Hosted collection uses the same authentication boundary as other console APIs. Loopback collection is intended for a trusted local user. Reusing a span ID with conflicting evidence is rejected; older sequence updates are ignored and terminal spans cannot be overwritten.

Start with Connect an agent → Agents Dashboard → Inspect latest run. Configure Advanced settings for each agent. Use Execution graphs when a job crosses agents; use Compare agent versions to compare versions on a fixed set of cases. Regression tests holds saved-run policy tests; Detection capabilities holds the custom check wizard.
