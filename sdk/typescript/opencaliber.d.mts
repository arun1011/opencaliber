export type Provider = 'openai-responses' | 'openai-chat' | 'anthropic';
export type Assessment = 'clear' | 'review' | 'violation';
export interface ToolMapping {
  tool: string;
  resource?: string;
  resource_from?: string;
  arguments?: {records?: string; command?: string; destination?: string};
  data_class: 'public' | 'internal' | 'pii' | 'secret';
}
export interface IntegrationContext {
  policy: {version: string; tools: Record<string, ToolMapping>};
  agent: {id: string; version: string};
  task: {goal: string; allowed_tools?: string[]; allowed_resources?: string[]; read_only?: boolean; approved_action_ids?: string[]};
  session_id: string;
  workflow_id?: string;
}
export interface Trace {
  name?: string;
  agent: IntegrationContext['agent'];
  task: IntegrationContext['task'];
  context: {provider: Provider; response_id: string; session_id: string; policy_version: string; policy_sha256: string};
  workflow_id?: string;
  actions: Array<{id: string; source_tool: string; tool: string; resource: string; arguments?: Record<string,unknown>; data_class?: string; resource_version?: string; outcome?: {status: 'succeeded' | 'failed' | 'unknown'; source: 'application' | 'agent' | 'unknown'}}>;
}
export interface EvaluationResult {
  assessment: Assessment; risk_score: number; score_type: 'heuristic_not_probability';
  storage_mode: 'raw' | 'redacted'; replayable: boolean; config_sha256: string;
  actions: Array<{action_id: string; source_tool: string; findings: Array<{code: string; message: string; remediation: {change: string; verify: string; basis: string}}>}>;
}
export type Observation = {status: 'evaluated'; id: string; result: EvaluationResult; mode: 'observe'; execution_decision: 'application_owned'; elapsed_ms: number}
  | {status: 'error'; assessment: null; error: 'evaluation_unavailable'; mode: 'observe'; execution_decision: 'application_owned'};
export function normalizeResponse(provider: Provider, response: unknown, context: IntegrationContext): Trace;
export class Client {
  constructor(options?: {endpoint?: string; timeoutMs?: number; failureMode?: 'return_error' | 'raise'});
  observe(trace: Trace, options?: {storage?: 'redacted' | 'raw'}): Promise<Observation>;
  observeResponse(provider: Provider, response: unknown, context: IntegrationContext, options?: {storage?: 'redacted' | 'raw'}): Promise<Observation>;
}
