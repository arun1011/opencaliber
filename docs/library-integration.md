# Library monitoring and comparison

## Start and inspect

Start your own OpenCaliber console, then run `python agent.py --demo`. The pack sends its config.json tracking_id, agent_id and version. Agents Dashboard shows status, explicit outcome and counted detected problems/monitoring coverage. Review details opens inspection/history/graphs; Evaluate opens diagnosis/comparison. Use Advanced settings for boundaries and mode; Detection capabilities for new detectors; Regression tests for saved-run policy tests; Developer Guide for full instructions.

Default output capture is enabled and contains only result type and length. Set diagnosis_enabled=false to omit objective/output diagnosis context. capture_fields maps tool names to explicitly approved dictionary keys, for example {"http.get":["status"]}. It cannot extract arbitrary nested strings or rows; adapt capture() in opencaliber/library_runtime.py for application-specific evidence. Never include credentials. Required output paths must match your enabled checks, otherwise monitoring coverage correctly remains incomplete. API-key/model settings in the console belong to its coding assistant, not this agent's runtime provider.

Draft task success verifies that the saved text matches the draft and meets success_checks.minimum_characters and success_checks.required_phrases. This is artifact/expected-text validation, not model accuracy or complete semantic correctness. Adapt these expectations or implement independent verification for your domain. Computer workflows use their configured assertions; completing a UI workflow does not prove an unstated business goal. Failed workflows report false; absent independent assertions should remain unknown rather than be guessed.

## Compare real versions

For a quick demo comparison, extract a second copy, make your candidate changes, keep the console running, then run `python compare_versions.py --candidate ../candidate-folder`. The helper uses isolated copies, fingerprints actual fixture inputs, tags the versions, saves tracked outcomes and writes outputs/comparison.json. It compares offline fixtures; test live model/browser behavior separately. Different inputs, policies or contracts remain unmatched. Keep success_checks and expected UI assertions equivalent across versions.

Change config.json version when changing your agent. Keep its agent_id and tracking_id stable for versions of the same agent. Run versions against isolated copies of the same input. Set evaluation to a JSON object in both configs:

```json
{"experiment_id":"ticket-search-v1-v2","case_id":"fixture-1","input_sha256":"REPLACE_WITH_ACTUAL_64_HEX_SHA256","success_criterion":"saved-draft-matches-required-phrases","assignment":"paired"}
```

The example hash is intentionally a placeholder: replace it with SHA-256 of the actual canonical input used by both versions. Keep success criteria and policy/tool contracts fixed for matched comparisons. Leave evaluation null for ordinary monitoring; those runs remain observational. For live websites, hashing only the URL does not establish identical content. Capture shared fixtures or provide an application-owned input fingerprint. A/B assignment is owned by your application, not automatically performed by the console. Set the same independently justified success checks for both versions. Provider cost is not inferred; report actual usage/cost through record_outcome only when known.

Each workflow emits a graph root and one span for every wrapped tool, including blocked calls. Set trajectory_id to the shared job ID and parent_span_id to an emitted parent when coordinating workers. Leave both null for a new standalone job. Do not reuse a completed job ID for unrelated executions. Sequence state is not shared across processes. Graph delivery is best effort and has no durable offline spool; action snapshots use the standard minimized offline queue. Restarting the console retains accepted data, not events it never received.

Optional allowed_resources provides an exact task resource allowlist. Null leaves it undeclared; console coverage will request review rather than assume coverage. Local policy, tool contracts and console policies remain separate checks. Enabled console custom detectors apply to online events automatically; direct offline evaluate_trace does not load the console database or its custom checks.

Set OPENCALIBER_ENDPOINT to your own console origin and OPENCALIBER_TOKEN privately for a remote HTTPS service. Set OPENCALIBER_MODE=enforce for blocking from the first action. New agents inherit the console default and existing assignments are preserved. Set OPENCALIBER_TRACKING=off only for an intentionally disconnected run. Only wrapped actions and emitted spans are observed.
