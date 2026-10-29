# Sequence-dependent rules (engine 0.4)

Configure `sequence_rules` in the console Configuration page or in the configuration passed to Python/CLI/HTTP. The default is an empty array, preserving existing behavior. Existing pre-0.4 saved settings are normalized with an empty array; sequence rules do not turn on automatically.

```json
[{"id":"backup-before-delete","tool":"file.delete","requires_tool":"file.backup","invalidate_on":["file.write"]}]
```

Each target action requires an earlier prerequisite for the exact same resource in the same trace. The latest relevant prerequisite must have `outcome: {"status":"succeeded","source":"application"}` and a clear evaluation. A failed, unknown, omitted or agent-reported outcome cannot satisfy it. Outcomes accept statuses succeeded/failed/unknown and sources application/agent/unknown. Do not map a model's arguments or provider response status into application execution outcomes.

A later prerequisite cannot justify an earlier action. Any intervening action from invalidate_on invalidates the prerequisite, conservatively even if it failed or lacks an outcome. The target tool also always invalidates/consumes its prerequisite, so two deletes require two backups. A newer failed backup supersedes an older successful backup. Other resources do not affect it. Multiple rules on a target must all pass. No hidden cross-trace state is maintained.

Use `resource_version` on both backup and target if your system provides versions. If either action has a version, both must have the exact same value. When neither is versioned, only declared intervening actions can establish staleness; changes omitted from the trace cannot be detected. File aliases and database scope containment are not inferred. Use stable canonical identifiers before submitting data.

Trace array order MUST reflect actual completed execution order. Do not use plan order or parallel dispatch order to assert a successful prerequisite. Instrument your executor to finish the backup, check the real tool response, then append its outcome before evaluating a proposed delete. Completion timestamps, event signatures, backup artifacts and cross-workflow dependencies are not verified by this engine. A string labeled application is still supplied metadata, not cryptographic proof.

## Try a working example

```sh
python -m opencaliber.agent_cli evaluate --input examples/sequence_trace.json --config examples/sequence_config.json
python -m opencaliber.agent_cli evaluate --input examples/sequence_failed_trace.json --config examples/sequence_config.json
```

The first trace satisfies the backup-before-delete rule. The second returns SEQUENCE_PREREQUISITE_MISSING, linked to backup-01 and delete-01, with rule_id, reason and correction guidance. Result actions include sequence_checks for both satisfied and failed requirements. Agent identity is preserved.

The file.backup and database.backup canonical tools describe application-recorded backup operations; OpenCaliber performs neither. If using provider adapters, map tool names as usual, then combine execution records across turns in your application and attach real outcomes. The adapters only normalize proposed client-tool calls and deliberately do not invent execution success.

## Enforcement and privacy

Evaluation is advisory. To prevent a delete, the executor must evaluate the prefix of completed actions plus the proposed delete and refuse dispatch when the result is not clear or evaluation is unavailable. Calling the evaluator after deletion cannot undo it. Require approvals independently; a backup does not substitute for an approved_action_id.

Raw stored traces include resource versions and outcomes. Redacted storage minimizes resource_version after evaluation and is not replayable. Same resource/version labels across redacted actions must not be used to re-evaluate freshness.

The shipped 70-case contract suite remains unchanged; tests/test_sequence_rules.py adds separate sequence regressions, not independent security-effectiveness evidence.
