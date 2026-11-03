# Develop a detection check in the console

Open **Detection capabilities → Missing checks and evidence**. Select **Add missing check** for a detection gap or **Resolve step by step** for an evidence, policy or contract gap. You can also start with **Create a detection check**.

## 1. Define the requirement

Name a concrete failure condition, choose one tool and choose the tracking IDs that need it. Leave tracking IDs empty to apply to all agents using that tool, including future registrations. Give a useful finding message and recommended fix.

Choose **Before action** for checks over arguments, resource, task and earlier successful actions. A failed or unknown result can prevent dispatch when the console assignment is enforce. Choose **After action** for output or outcome checks: they detect problems after an action and cannot undo it. Findings on previous actions can also affect the next dispatch in enforce mode.

## 2. Develop the code

The starter detects a record-budget violation. Replace it with your requirement:

```python
def check(ctx):
    return field("action.arguments.records") > 25
```

Declare `action.arguments.records` as required evidence. Return `True` for a problem and `False` for a pass. Missing or invalid evidence produces **unknown**, never a pass.

For an exact-match business requirement:

```python
def check(ctx):
    return field("action.arguments.match_mode") != "exact"
```

For a prerequisite over earlier reported actions:

```python
def check(ctx):
    return not previous_succeeded("file.backup", field("action.resource"))
```

The helper considers only preceding actions with a succeeded outcome and the same resource. It does not establish backup freshness; configure a sequence rule with invalidating writes when freshness matters.

For an output check, choose After action:

```python
def check(ctx):
    return field("output.matched_records") != field("output.expected_records")
```

The expected value must come from an independently defined expectation in the integration. Repeating an agent's prediction as its expected value does not independently verify correctness.

Supported helpers are `field(path)`, `contains(container, value)`, `lower(text)`, `count(value)` and `previous_succeeded(tool, resource)`. Comparisons, literal lists and boolean operators are supported. The evaluator interprets a bounded syntax tree; it never calls Python `eval` or `exec`. Imports, loops, comprehensions, arbitrary functions, attributes, filesystem, network and shell access are not supported. A capability needing those operations requires a reviewed backend extension outside this wizard.

### Optional coding model

Open **Optional coding model** in Detection capabilities. Choose:

- **Model Service:** OpenAI, Claude / Anthropic or Google / Gemini; enter the exact model name and API key, enable and save.
- **Local Model:** Hugging Face; enter an `owner/model` ID, download it, then enable and save. Install `requirements-models.txt` in the same Python environment as the console first. Public Transformers-compatible causal language models with Safetensors weights are supported. Models requiring custom Python code, GGUF-only models and gated repositories requiring a token are not supported in this manager.

In step 2, review the draft and test examples, select the consent checkbox, and click **Run coding model to draft code**. Only that draft and its test examples are submitted. No automatic run-history collection or credential inclusion occurs. Model-generated code remains a draft; it cannot install dependencies, modify agents or enable itself. Provider failures leave manual development available.

Service API keys are encrypted server-side using Windows account protection. Linux/macOS services require the optional `cryptography` dependency and `OPENCALIBER_SECRET_KEY`, a Fernet key supplied through the service environment. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep that key stable across service restarts. API responses never return the stored key. **Remove saved API key** disables the assistant and clears the credential.

Local model downloads are stored alongside the database under `check-models/`, pinned to the resolved Hugging Face revision. Downloads are bounded to 8 GiB of selected model files. Inference uses a short-lived subprocess, runs on available CUDA or CPU, and unloads afterward. Generation has a three-minute timeout; download has a fifteen-minute timeout. A model that is too large for available memory, incompatible or too slow reports an error. Deleting a model removes its managed files and disables it if selected. Restarting during download may leave partial files; download again to resume, or delete that model ID.

## 3. Test the saved revision

Edit the synthetic test examples to match your requirement. Include at least one expected pass and one expected failure. Each example supplies an `action` with the chosen tool, optional `output`, `task` and preceding `history`.

```json
[
  {"name":"Exact search", "context":{"action":{"tool":"database.read","arguments":{"match_mode":"exact"}}}, "expected":"passed"},
  {"name":"Broad search", "context":{"action":{"tool":"database.read","arguments":{"match_mode":"substring"}}}, "expected":"failed"}
]
```

Select **Save and run tests**. OpenCaliber also removes each required field from the passing example to verify an unknown result. These tests establish behavior on the supplied examples, not general detection accuracy. The LLM can be wrong; independently review the requirement and expected outcomes.

## 4. Enable and verify

Enable the tested revision. It is stored immediately in SQLite and used on subsequent online events without a server restart. Edit a check through **Open wizard**; saving edits disables it and invalidates its test result until you test and enable the new revision. Concurrent stale edits are rejected. Disable or delete stops future evaluation; previous findings and the revision audit remain.

The dashboard refreshes its structural gaps. A custom field check counts as observed only after a scoped run evaluates that field with the enabled revision. Until then it says **awaiting new run evidence**. Missing output capture, unexecuted tools and missing outcomes do not disappear merely because a check was created. A custom check does not turn an unknown tool into fully implemented canonical semantics.

Enable `diagnosis=True` and supply `capture_output` for output checks. Select safe fields rather than returning complete sensitive documents:

```python
with TrackedExecutor(
    agent={"id": "ticket-reader", "version": "2.0"},
    tracking_id="ticket-reader",
    task={"goal": "Read exact login tickets", "allowed_tools": ["database.read"], "allowed_resources": ["tickets"]},
    diagnosis=True,
    capture_output=lambda action, rows: {"matched_records": len(rows), "expected_records": 2},
) as agent:
    rows = agent.run(
        {"id":"lookup", "tool":"database.read", "resource":"tickets",
         "arguments":{"records":2, "match_mode":"exact"}},
        query_exact_login_tickets,
        success=lambda rows: len(rows) == 2,
    )
    agent.record_outcome(len(rows) == 2)
```

Here `query_exact_login_tickets` is your application-owned database function; `2` is an illustrative fixture expectation, not a universal rule. Production expectations must come from your task contract. Original selected outputs are retained only through the explicit diagnosis capture path. Offline minimized events are not evaluated as if they contained the original values.

## Internals and deployment

- `custom_checks.py`: specification validation, restricted interpreter, tests, revision persistence, audit and application to online trace results.
- `check_gaps.py`: maps current check results back to structural evidence gaps.
- `check_api.py`: shared local and authenticated hosted endpoints.
- `check_models.py`: encrypted configuration, fixed provider endpoints, generation, managed downloads and deletion.
- `check_model_worker.py`: optional isolated-process model download/inference lifecycle. Downloaded model Python is never executed.
- `web/check-wizard.js`: four-step check wizard, per-gap guidance and model settings.

The normal console works without model dependencies. Custom checks are console-side capabilities; agents using only the offline `evaluate_trace` function do not load them. Custom-check fingerprints are included when matching version-comparison runs, preventing runs under different custom capabilities from being paired. Saved checks, tests, credentials and models are runtime data, excluded from source and downloadable packages.
