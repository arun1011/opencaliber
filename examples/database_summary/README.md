# Database search and summarization agent

A runnable example of exactly where OpenCaliber fits into an agent workflow:

```text
Search term
  -> proposed database.read
  -> OpenCaliber enforce check
  -> parameterized SQLite query
  -> application records outcome
  -> proposed http.send with actual returned row count
  -> OpenCaliber enforce check
  -> mock LLM summary
  -> application records outcome
```

The database is real SQLite, in memory, populated with four synthetic tickets.
The LLM is a deterministic mock: **no network traffic, credentials or model calls**.
The endpoint is an example policy label. The code uses the actual OpenCaliber
engine and `GuardedExecutor`; it does not duplicate policy decisions in the agent.
Run on Python 3.10+ from the repository root (the inner `opencaliber` folder).

## Run the examples

```shell
python examples/database_summary/agent.py
python examples/database_summary/agent.py --scenario blocked-transfer
python examples/database_summary/agent.py --scenario record-limit
python examples/database_summary/agent.py --scenario database-failure
python examples/database_summary/agent.py --scenario llm-failure
python examples/database_summary/agent.py --term password
```

| Scenario | Database callback | LLM callback | Result |
| --- | --- | --- | --- |
| `success` | Runs | Runs | Three matched tickets; mock summary |
| `blocked-transfer` | Runs | Never called | Unapproved destination rejected before dispatch |
| `record-limit` | Never called | Never called | Proposed four-row read exceeds three-row policy |
| `database-failure` | Raises simulated error | Never called | Application stops; query outcome remains unknown |
| `llm-failure` | Runs | Raises simulated timeout | Application stops; no retry; LLM outcome unknown |

Completed workflows exit 0. Blocked or failed workflows exit 2; this is expected
when running the negative examples. No matches is a successful empty query and
the application skips summarization.

## What each file does

- `agent.py`: proposes actions, places both callbacks behind enforcement, records
  execution results and prints the workflow outcome. Search for **CHECKPOINT 1**,
  **CHECKPOINT 2** and **REAL LLM INTEGRATION POINT**.
- `policy.json`: saved engine configuration. Allows at most three records and two
  actions; scopes reads to `support_tickets`; requires the approved LLM hostname,
  the `summarize` purpose and a bounded outgoing record count.
- `test_agent.py`: verifies allowed dispatch, blocked callbacks, failure handling,
  no-match behavior, parameterized search and evaluator unavailability.

The task contract in `run_workflow` also fixes the exact permitted resources.
For a real project, derive it from application authorization, never agent output.
Changing the hostname in the policy does not override an exact task resource list.
`read_only` is false for the overall workflow because an outbound `http.send` is a
mutating tool; separate database controls still keep the connection read-only.

## Replace the mock with your LLM client

Replace `MockLLM.summarize` or the call in `llm_callback` with your application's
provider client. Use the **same destination and records that were evaluated**.
Do not put the real client call before `executor.run`. Configure the real host
and exact task URL, credential handling, sensitivity labels, timeouts and payload
limits in your application. Keep credentials out of traces and configuration.
Apply real database permissions, read limits and network/redirect restrictions too.

This example labels the synthetic records `public`. OpenCaliber does not discover
PII, parse arbitrary SQL, validate summary correctness or inspect hidden operations
inside callbacks. An allowlisted LLM host alone does not establish permission to
send a particular dataset. Review/redact real records before transfer.

The workflow stops after database failure through ordinary Python control flow.
It does **not** use a sequence rule for database-read-before-HTTP-send: those
actions use different resources, while current sequence rules require the same
exact resource. Callback exceptions remain unknown because the generic wrapper
cannot establish whether side effects occurred; it never retries automatically.

## Evidence and console review

```shell
python examples/database_summary/agent.py --scenario blocked-transfer --output artifacts/database-summary/blocked.json
python -m unittest discover -s examples/database_summary -v
```

The evidence contains the attempted trace (including a blocked proposal without
an outcome), policy, callback counts and last **pre-dispatch** evaluation. The last
evaluation is a decision snapshot, not proof the final callback succeeded; inspect
the application outcomes in `trace` for execution status. No ticket bodies or search
term are written into the trace, but metadata and policy constants may be sensitive.

Console history is not populated automatically by this example. For manual review,
save the `config` object through Configuration (or `POST /api/config`), then paste
the evidence's `trace` object into Evaluate a trace. Use an isolated demo workspace
if you do not want to replace existing configuration. Re-evaluation uses current
saved policy, so retain the exported config when reproducing a result.
