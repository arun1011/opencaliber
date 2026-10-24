// Provider fixtures and mapping editor. Never calls a model or dispatches a tool.
export function integrationPage(esc) {
  return `<div class="page-heading"><div><h1>Connect a tool-call workflow</h1><p>Normalize completed provider responses, map custom tools and save evaluation findings.</p></div></div>
  <div class="notice">Observe only: this console does not call OpenAI or Anthropic, intercept requests, execute tools or decide whether your application should proceed. Fixtures below are synthetic. Use completed client-tool responses; streaming deltas and hosted tools are unsupported.</div>
  <form id="integration-form"><div class="split"><section class="panel"><div class="panel-content">
  <label class="field">Response format<select id="integration-provider"><option value="openai-responses">OpenAI Responses</option><option value="openai-chat">OpenAI Chat Completions</option><option value="anthropic">Anthropic Messages</option></select></label>
  <div class="actions"><button type="button" class="btn" data-action="integration-unsafe">Load unsafe fixture</button><button type="button" class="btn" data-action="integration-corrected">Load corrected fixture</button></div>
  <label class="field">Completed response JSON<textarea id="integration-response" rows="13" spellcheck="false" required></textarea></label>
  <label class="field">Application context JSON · agent, version, task, session and workflow<textarea id="integration-context" rows="13" spellcheck="false" required></textarea></label>
  </div></section><section class="panel"><div class="panel-content text-content">
  <h3>Custom tool mappings</h3><p>Map your tool names to supported semantics. Dotted selectors read arguments; only selected values enter the trace. Set sensitivity in your application policy. Do not take scope or approvals from model output.</p>
  <label class="field">Versioned mapping policy JSON<textarea id="integration-policy" rows="20" spellcheck="false" required></textarea></label>
  <label class="field">Evidence storage<select id="integration-storage"><option value="redacted">Redacted · SDK default</option><option value="raw">Raw · retains replay inputs</option></select></label>
  <p>Evaluation occurs before storage redaction. Redacted history removes goals, commands, untrusted text and resource paths. Hosts, agent IDs, tool names, record counts and session labels remain. Supply opaque identifiers. Redacted runs cannot be replayed.</p>
  <div class="actions"><button type="button" class="btn" data-action="integration-preview">Preview normalized trace</button><button class="btn primary">Evaluate response & save</button></div><div id="integration-error" class="error" role="alert"></div>
  <details><summary>Normalized trace preview · not saved</summary><pre id="integration-preview">Load a fixture or supply a completed response, then preview.</pre></details>
  </div></section></div></form>
  <section class="panel integration-quickstart"><div class="panel-content text-content"><h3>Run the packaged examples</h3><pre>python examples/adoption/provider_demo.py --provider openai-responses
python examples/adoption/provider_demo.py --provider anthropic --save
node examples/adoption/provider_demo.mjs openai-chat
python -m opencaliber.agent_cli regression --input examples/adoption/regression-suite.json --output report.json</pre>
  <p>The Python fixture example runs offline by default. <code>--save</code> and the Node example need the console server. Compare demo-v1 (external sensitive transfer) with demo-v2 (approved destination). No company tool executes. The six-case provider suite exits nonzero on a mismatch.</p>
  <h3>Use a real provider response in your application</h3><pre>from opencaliber.sdk import Client

observation = Client(timeout=2, failure_mode="raise").observe_response(
    "openai-responses", response.model_dump(mode="json"),
    policy=policy, agent={"id": "invoice-agent", "version": "v1"},
    task=task, session_id="session-104", workflow_id="invoice-review")
# Your executor owns authorization and what to do with findings.</pre>
  <p>For Anthropic use <code>"anthropic"</code>; for Chat Completions use <code>"openai-chat"</code>. Python supports completed SDK objects directly too. Node/TypeScript helpers are in <code>sdk/typescript/opencaliber.mjs</code> with type declarations. Full instructions: <code>ADOPTION.md</code> in the ZIP. Optional live mock-tool example: <code>examples/adoption/live_agent.py</code>.</p>
  <h3>Failure and coverage</h3><p>Timeouts and evaluator errors are errors, never clear assessments. SDK helpers never execute or approve a call. Python uses a socket timeout; Node uses an abort deadline. No retries are performed. Unmapped tools produce review; malformed mappings or unsupported response types are rejected. A session ID is a label: cumulative budgets apply only to actions submitted together.</p></div></section>`;
}

export function fillIntegrationFixture(bundle, scenario) {
  const provider=document.querySelector('#integration-provider').value;
  const {policy,agent,task,session_id,workflow_id}=bundle;
  document.querySelector('#integration-policy').value=JSON.stringify(policy,null,2);
  document.querySelector('#integration-context').value=JSON.stringify({agent:{...agent,version:scenario==='unsafe'?'demo-v1':'demo-v2'},task,session_id,workflow_id},null,2);
  document.querySelector('#integration-response').value=JSON.stringify(bundle.responses[provider][scenario],null,2);
}

export function integrationInput() {
  const context=JSON.parse(document.querySelector('#integration-context').value);
  return {provider:document.querySelector('#integration-provider').value,
    response:JSON.parse(document.querySelector('#integration-response').value),
    context:{...context,policy:JSON.parse(document.querySelector('#integration-policy').value)}};
}
