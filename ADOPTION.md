# Integrate OpenCaliber with a tool executor

OpenCaliber evaluates completed client-side tool requests. It does not automatically instrument an agent framework or provider SDK. Your application owns authorization, execution and error handling. The current runtime is for local development and staging evaluation; it has no team authentication or production service controls.

## Start with recorded responses

Extract the runtime ZIP. Python 3.10+ is sufficient; no provider package or API key is needed for these commands:

```sh
python examples/adoption/provider_demo.py --provider openai-responses
python examples/adoption/provider_demo.py --provider openai-chat
python examples/adoption/provider_demo.py --provider anthropic
```

Each command evaluates two synthetic responses: demo-v1 transfers declared sensitive data outside the host policy and returns violation; demo-v2 uses an approved destination and returns clear under the implemented rules. These are regression fixtures, not recorded live-provider benchmark results. No tool is dispatched. The examples deliberately supply a task resource list that includes both destinations so that the separate host policy detects the unsafe transfer.

Start `python run.py`, then open the console's **Connect agents** page. Load either fixture, inspect its mapping and context, preview the trace, and evaluate it. Or save both versions from Python:

```sh
python examples/adoption/provider_demo.py --provider anthropic --save
node examples/adoption/provider_demo.mjs openai-responses
```

The Node example requires Node 18+ and the local server. Search the Overview or Findings page for `invoice-agent`, `demo-v1`, `demo-v2`, or the session/workflow ID. A finding shows the original tool name, canonical check, provider call ID, rule, suggested change and verification steps.

## Map application tools explicitly

`examples/adoption/context.json` contains an editable integration context. The mapping policy is application-owned and versioned:

```json
{
  "version": "invoice-tools-v1",
  "tools": {
    "send_invoice_report": {
      "tool": "http.send",
      "resource_from": "url",
      "arguments": {"destination": "url"},
      "data_class": "pii"
    }
  }
}
```

`resource` is a fixed resource; `resource_from` selects a value from tool arguments. Choose exactly one. Dotted selectors such as `request.url` work for nested objects. Supported argument projections are `records`, `command`, and `destination`. Missing mapped fields reject normalization. A tool mapping assigns a supported canonical semantic operation, not arbitrary validation code. Review that the mapping describes what your tool actually does. Unmapped tools become `unmapped.<name>` and produce review. Unsupported hosted tools/toolsets and incomplete responses are rejected rather than labeled clear.

Sensitivity comes from your application mapping, not the model's claim. Task tool/resource allowlists and approvals must come from the authorized task. Do not generate allowlists from observed model requests. For mixed sensitivities, classify conservatively or construct a normalized trace with application-owned labels. Raw prompts, report bodies and unused arguments are not copied by the adapter. This projection also means unselected content is not inspected for prompt injection.

## Python: after a completed provider response, before your executor

```python
from opencaliber.sdk import Client, evaluate_response

# policy, task and identities are supplied by your application.
context = dict(policy=policy, agent={"id": "invoice-agent", "version": "commit-123"},
               task=task, session_id="session-104", workflow_id="invoice-review")
client = Client(timeout=2, failure_mode="return_error")
observation = client.observe_response("openai-responses", response, **context)
# Other formats: "openai-chat" and "anthropic".
# Completed SDK objects with model_dump(mode="json") and plain dictionaries are accepted.

if observation["status"] == "error":
    # Application policy chooses whether to defer execution, queue review, or continue observation.
    # Never label an evaluator outage as a clear assessment.
    pass
else:
    result = observation["result"]
    # Your executor inspects per-action findings and enforces its own authorization.
```

The helper never invokes your dispatcher or decides permission. It waits for evaluation, so observe-only still adds latency. No automatic retries are made. `failure_mode="raise"` raises `EvaluationUnavailable`; the default returns a structured error without an assessment. The Python timeout is a socket timeout, not a hard end-to-end deadline; use your application's deadline/cancellation mechanism where required. Endpoints are loopback-only, proxy environment variables are ignored, and redirects are not followed.

For in-process use with no network or persistence:

```python
evaluated = evaluate_response("anthropic", response, config=config, **context)
trace, result = evaluated["trace"], evaluated["result"]
```

For saved provider JSON:

```sh
python examples/adoption/live_response.py --provider openai-responses --response response.json --context examples/adoption/context.json
```

## TypeScript / Node

Copy `sdk/typescript/opencaliber.mjs` and its adjacent `opencaliber.d.mts` into your project. These are local source helpers, not a published npm package. In a TypeScript project using NodeNext module resolution:

```ts
import {Client, type IntegrationContext} from './opencaliber.mjs';
const context: IntegrationContext = /* application-owned context */;
const client = new Client({timeoutMs: 2000, failureMode: 'return_error'});
const observation = await client.observeResponse('anthropic', response, context);
if (observation.status === 'evaluated') {
  console.log(observation.id, observation.result.assessment);
}
```

Node uses `AbortController` for the HTTP operation deadline and follows no redirects. Both languages send normalized traces to the same Python engine; there is no second JavaScript evaluator.

## Optional live model example

The recorded fixtures above work without provider access. To test an actual model, install only the provider SDK you need (`pip install openai` or `pip install anthropic`), set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in your environment, and supply a model available to your account:

```sh
python examples/adoption/live_agent.py --live --provider openai-responses --model YOUR_MODEL --scenario unsafe
python examples/adoption/live_agent.py --live --provider anthropic --model YOUR_MODEL --scenario corrected
```

Each invocation makes one paid provider request, evaluates its actual returned calls through the running local console, and dispatches only local mocks for calls the example application's policy accepts. It prints correctly correlated tool-result blocks for a follow-up turn but does not send that turn. It never sends reports to external destinations or reads company data. Provider model choices are nondeterministic; this is a wiring example, not an asserted detection benchmark. Live provider requests were not run during development of this package.

Format references: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling), [Anthropic tool-call handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls). These adapters support completed function/tool-use blocks, not streaming fragments, OpenAI Agents SDK tracing hooks, MCP discovery, or provider-hosted tools. Accumulate streaming events using the provider SDK before calling the adapter. Responses API `call_id` and Anthropic/Chat Completions call `id` become action IDs.

## Privacy and history

SDK HTTP observations default to `storage="redacted"`. The server evaluates the complete normalized trace in memory, then minimizes it before writing SQLite or returning evidence. It removes task goal, commands, untrusted content, non-URL resources, and URL paths/queries/fragments/credentials. Hosts, canonical/original tool names, record counts, finding codes, run names, agent IDs, session/workflow/response IDs, and mapping/configuration hashes remain. These labels must be opaque and must not contain credentials or customer data. This is field minimization, not general PII detection. The active configuration snapshot is also stored; keep configuration labels free of secrets.

Redacted runs cannot be replayed from the console. Replay the original response from your application. Raw storage is available explicitly with `storage="raw"`; manual JSON trace evaluations still use raw storage. Direct `/api/evaluate` callers must select storage explicitly if they need minimization. Raw legacy records are not retroactively scrubbed. SQLite is not encrypted. The local service has no authentication. Do not expose it on a public/network interface.

## Session, policy and release checks

Context records provider, response ID, session ID, mapping version and SHA-256. Results also include the evaluator configuration SHA-256 and engine version. These are provenance labels, not signed attestations. Review mapping/configuration changes in source control. The console configuration governs HTTP evaluations; use an explicit config file for reproducible CI evaluation.

```sh
python -m opencaliber.agent_cli regression --input examples/adoption/regression-suite.json --output regression-report.json
python -m opencaliber.agent_cli benchmark --output rule-report.json
python -m opencaliber.agent_cli evaluate --input examples/agent_trace.json --fail-on review
```

Regression and benchmark commands exit 1 on expected-result mismatches; invalid input also fails. `evaluate --fail-on violation` fails on violations, `--fail-on review` fails on review or violation, and the default only writes the assessment. Add `--config policy-config.json` to pin the evaluator rules. Reports include case IDs, expected/actual assessment, finding codes, score and version fingerprints. Archive reports as your CI artifacts. A green report does not establish that an agent is secure.

Each trace contains one agent and task. Session/workflow IDs support lookup only. Budgets aggregate within a submitted trace, not across responses or agents. If collecting several responses into one trace, preserve unique call IDs and one consistent authorized task; there is no automatic cross-response accumulator. Multi-agent correlation, agent authentication, automatic containment, retention administration, and team workspaces remain future work.
