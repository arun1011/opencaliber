# Controlled report workflow

This standard-library example reads synthetic tickets from an in-memory SQLite database, writes a deterministic report, verifies a backup, and optionally deletes only its generated report after a successful backup. It does not call a model or production database.

Start the console with `python run.py`, then run:
```
python examples/controlled_workflow/agent.py --delete-after-backup
```
The explicit --delete-after-backup flag records application approval for deleting only this generated report. A production app must obtain its own real approval before supplying approved_action_ids; those labels are not independently authenticated.

The stable tracking ID is `controlled-report-dev`. Select it in Configure agent checks. Review the declared scope, inspect applicable controls, and set an individual central policy. `policy.json` is the separate application-local guard policy, not an automatic upload or replacement of the central policy.

The default central policy does not automatically acquire the sample's backup requirement. Copy its `sequence_rules` and `tool_policies` into the selected central policy if you want the console to enforce those requirements too. Keep the backup path under the approved root. Changes to central checks apply on the next online action.

Test local blocking of an unsafe sequence:
```
python examples/controlled_workflow/agent.py --delete-after-backup --skip-backup
```
The delete callback is not dispatched and the process exits 2. Test backup failure with `--fail-backup`: the workflow stops before deletion and exits 4. Console-unavailable enforcement exits 3. For central enforcement from the first action set `OPENCALIBER_MODE=enforce`; the console must be reachable and its policy must allow the intended operations. With report-only central mode, application-local guards can still reject operations.

Output is confined by this example's callbacks to the directory supplied with `--output`; it contains generated summary.txt and summary.bak. Logical /workspace paths in metadata must be mapped consistently to the real filesystem by the application. The evaluator is not an OS sandbox. Use a fresh output folder when testing backup failures so old files cannot be mistaken for a new successful backup.

Wrap provider or database client operations in the same way when adapting the example. Supply actual records, destinations and sensitivity metadata and a business-specific success predicate. Avoid retrying unknown side effects automatically. Direct in-memory formatting is not separately tracked here.
