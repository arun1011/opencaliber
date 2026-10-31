# Per-tool field policies

Engine `agent-rules-0.5` adds optional `tool_policies` to the existing configuration.
Older configurations receive `{}` and retain their existing checks. Unknown config
keys and malformed policies are rejected. No executable policy code is loaded.

## Configure

Open Console → Configuration → Per-tool field policies. Paste the object below
and save. The full runnable configuration is `examples/tool-policy-config.json`.
Profiles can import/export the same configuration without dropping these rules.

```json
{
  "file.read": {"resource": {"path_roots": ["/workspace/reports"]}},
  "file.write": {"resource": {"path_roots": ["/workspace/exports"]}},
  "http.send": {
    "arguments": {
      "destination": {"hosts": ["api.company.test"]},
      "account_id": {"allowed_values": ["approved-account"]},
      "amount": {"min": 0, "max": 100}
    }
  }
}
```

`tool_policies` keys are supported **canonical** tool names, not provider function
names. Each tool has `resource`, `arguments`, or both. `arguments` maps flat field
names to rules. Each configured field is required. Missing fields, wrong types,
or disallowed values produce `TOOL_FIELD_NOT_ALLOWED`, severity 90, an explicit
violation, the action ID and the `field` to fix. Findings do not echo input values.
An unconfigured tool or argument gets no additional restriction from this feature;
all existing engine rules still apply. Extra arguments are not automatically denied.

## Operators and precedence

| Operator | Meaning |
| --- | --- |
| `allowed_values` | Exact, case-sensitive scalar equality, including type. Python integer `1` differs from float `1.0` and boolean `true`; send consistent JSON types. |
| `path_roots` | Absolute POSIX directory or descendants, respecting component boundaries. `/reports2` is outside `/reports`. Rejects backslashes, NUL, double-leading slashes and traversal segments. |
| `hosts` | HTTP(S) URL with an exact case-insensitive hostname. No wildcard/subdomain expansion, credentials, whitespace, backslashes or invalid port. Paths and ports are not restricted beyond URL/port validity. |
| `min`, `max` | Inclusive finite numeric bounds. Booleans and numeric strings do not qualify. |

All operators on a field are ANDed. `allowed_values` may accompany one other
operator family. Path, host and numeric families cannot be mixed. Empty allowlists
deny every value; empty field rules are invalid. Rules are bounded: 100 tools,
50 argument rules per tool, 100 allowlist entries, argument names up to 80 ASCII
identifier characters. Numeric values/bounds are within ±1 trillion; strings up to
8,000 characters (roots 300, hosts 253). Trace arguments are flat non-null scalars;
objects, arrays, NaN and infinity are rejected. Existing `records` integer and
`command`/`destination` string constraints remain in effect.

Global deny rules, task scope, global path/host limits and tool-specific rules all
apply together. **No tool policy grants permission or overrides a denial.** In the
example, global roots must include `/workspace` and global hosts must include
`api.company.test`. Per-tool rules can narrow those boundaries. Empty
`tool_policies` disables only the extra field checks.

## Integrations and privacy

Provider adapters, MCP imports and Databricks imports project only application-mapped
arguments. To inspect `account_id`, add `"account_id": "payload.account_id"` to
the tool mapping's `arguments` object. Dotted selectors navigate source objects;
the destination key is flat. Missing source selectors fail normalization rather
than silently bypassing a rule. Python and Node adapters support these projections.
Configure both actual path arguments and resource if a tool can use both: a resource
label is not proof of the path the callback will use.

The existing execution wrapper applies these policies when evaluating a proposed
action. In `enforce` mode, a violation prevents callback dispatch; `observe` still
executes. Custom arguments are removed from redacted history after evaluation.
Raw history retains them. Policy exports can contain sensitive account IDs/paths;
do not publish real values. Coverage reports list configured fields, not their values.

## Limits and extension points

Checks inspect declared values. They do not resolve symlinks, decode URL/path
escapes, resolve DNS, follow redirects, authenticate callers or verify callback
arguments match the trace. The application must enforce actual filesystem, network
and authorization boundaries at dispatch. No nested field policies, regex, scripts,
cross-trace state, wildcard domains, automatic IAM synchronization or per-source-tool
override is provided. Tools sharing a canonical name share that tool policy.

Implementation: `tool_policies.py` owns validation/matching; `agent_engine.py`
normalizes legacy configs and emits findings. `adapters.py` and the Node SDK map
scalar fields; `privacy.py` minimizes them; `coverage.py` reports configured checks;
`console.js` saves the policy JSON, `adoption.js` preserves it in profile previews.
When adding an operator, change validation and matching together, add boundary
and bypass tests in `tests/test_tool_policies.py`, and update these docs and guide.

Run `python -m unittest discover -s tests -p test_tool_policies.py -v`.
