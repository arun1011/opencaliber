# Enterprise integration building blocks

This release adds profiles, an application-owned execution wrapper, offline MCP/Databricks importers, CI reports and a coverage view. It does not add SSO, tenant isolation, cloud IAM synchronization or automatic datasource/vector-index inspection.

## Policy profiles

In Configuration choose a profile, preview it in the form, review every boundary and save explicitly. Import and export use the envelope {schema_version:1,name,config}. Profile JSON lives in profiles/. These are examples, not organizational policies. Read-only analytics denies canonical write tools; callers must also set truthful read_only task scope. Arbitrary shell and unknown tools remain review signals unless explicitly denied. Sensitive-data-transfer uses example hostnames that you must change. backup-before-delete enables sequence rules for file and database backups. Legacy saved settings remain supported.

## Guarded execution

Run python examples/enterprise/guarded_execution.py for a no-side-effect demonstration. GuardedExecutor maintains one synchronous trace in memory. Its run method evaluates a copied completed prefix plus a proposed action before invoking a supplied callback. Observe mode is the default and may execute flagged actions; enforce mode refuses review and violation results. Evaluator failure or malformed assessment prevents dispatch in both modes. The wrapper requires application callbacks for execution and success validation; it does not infer success from generated text. Callback errors preserve an unknown outcome and are not retried. Neither the wrapper nor metadata is a sandbox, permission service or authenticated source of evidence. Secure the executor and prevent parallel changes to the resource; no atomic snapshot or distributed lock is provided.

## MCP execution records

The console Adoption and coverage page imports a bounded array of {id,name,arguments,result,resource_version?}. This is an application execution-log envelope around actual MCP tools/call results, not an automatic MCP transport interceptor. Supply an application-owned policy, agent, task and workflow_id in the context. Optional success_selectors maps source tool names to dotted paths in result, for example structuredContent.success. Only literal true establishes success; isError true wins over any success selector. isError false or an absent result flag alone is unknown. Unknown tools become unmapped.tool and are reviewable. Never populate result from model-generated claims. Instrument actual executor results. Raw tool payloads are not copied into normalized actions.

```sh
python -m opencaliber.enterprise_cli import-mcp --input examples/enterprise/mcp-events.json --context examples/enterprise/mcp-context.json --output artifacts/mcp-trace.json
python -m opencaliber.agent_cli evaluate --input artifacts/mcp-trace.json --config examples/sequence_config.json
```

## Databricks audit exports

Export selected rows from system.access.audit under your existing permissions. Use request_id, event_time, service_name, action_name, request_params and response. Decode map/JSON columns into objects before import. Rows must contain timezone-aware ISO event_time in strictly increasing order; ties and ambiguous concurrent order are rejected. An audit timestamp is not proof of completed execution order. Do not use this importer to authorize a dependent operation. Map service_name.action_name explicitly to a canonical tool and resource selector. The included getTable example inspects metadata; it does not demonstrate reading table data.

HTTP status 200 remains unknown. Error status codes at least 400 mark failure. This prevents audit transport success from satisfying backup-before-delete. Audit entries and supplied context are not cryptographically authenticated. Mapping an operation incorrectly can produce incorrect assessments. Query texts, secrets and table contents are not required and are not copied into the normalized trace. Offline files remain on disk; protect them yourself.

```sh
python -m opencaliber.enterprise_cli import-databricks --input examples/enterprise/databricks-rows.json --context examples/enterprise/databricks-context.json --output artifacts/databricks-trace.json
```

No Databricks credentials, live connector, table-content scan, row-level entitlement validation or retrieval/vector relevance evaluation is included.

## CI evaluation reports

python -m opencaliber.ci --suite examples/enterprise/ci-suite.json --config examples/sequence_config.json writes artifacts/ci/report.json and report.md. A suite contains version and cases; every case has id, trace, expected_assessment and required_codes. Exit status 1 means mismatched expectations. --fail-on violation or review additionally gates on assessment severity. An expected violation is a passing regression by default. The workflow .github/workflows/evaluation.yml uses only synthetic cases, no secrets or cloud connections, and uploads report artifacts for seven days. Reports omit trace payloads and resource paths but include action/evidence IDs; inspect whether IDs disclose sensitive names before publishing artifacts. Do not put private production traces into a public repository or public Actions job.

## Coverage view

Adoption and coverage shows mapped/unmapped tool names, declared resource scope, missing conclusive application outcomes, enabled rules and tool inventory entries not observed. These describe supplied evidence, not statistical detection effectiveness. Inventory is caller-supplied; no automatic discovery occurs. The view does not persist imports or coverage reports. To save an imported trace, review it on Evaluate a trace and explicitly evaluate/save. The desktop and hosted APIs expose authenticated or loopback adoption routes with the same handlers; existing size and origin boundaries apply.

Static GitHub Pages hosts public documentation and package downloads only. The full adoption console requires the Python application or authenticated Elastic Beanstalk deployment.
