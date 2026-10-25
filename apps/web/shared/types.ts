// Types mirror the Python control-plane contract (services/analytics/.../api.py
// and packages/contracts/openapi.yaml). Field names are snake_case to match the
// wire format one-to-one; the composable does not rename them.

// ---- health ---------------------------------------------------------------
export interface HealthResponse {
  status: 'ok'
  service: string
  mode: string
  time: string
}

// ---- uploads --------------------------------------------------------------
export interface UploadInitRequest {
  filename: string
  size_bytes?: number
  workspace_id?: string
}

export interface UploadInitResponse {
  upload_id: string
  method: 'PUT'
  target_path: string
  expires_at: string
  status: 'initiated'
}

export interface PutContentResponse {
  upload_id: string
  status: 'quarantined'
  sha256: string
}

export interface ScanResult {
  verdict: 'clean' | 'suspicious' | 'rejected'
  reasons: string[]
}

export interface UploadFinalizeResponse {
  upload_id: string
  status: 'scanned' | 'rejected'
  scan: ScanResult
  dataset_id?: string
  revision?: number
  revision_state?: 'validated' | 'failed' | 'staged'
}

export type UploadStatus =
  | 'initiated' | 'quarantined' | 'scanned' | 'rejected' | 'parsed' | 'cancelled'

export interface UploadListItem {
  id: string
  filename: string
  status: UploadStatus
  dataset_id: string | null
  created_at: string
}

export interface ColumnProfile {
  name: string
  inferred_type: 'string' | 'integer' | 'float'
  null_rate: number
  sample: string[]
}

export interface RejectedRow {
  line: number
  reason: string
}

export interface ParsePreview {
  upload_id: string
  detected: {
    delimiter: string
    encoding: string
    header_row: number
    dialect_confidence: 'high' | 'needs_confirmation'
  }
  columns: ColumnProfile[]
  row_count: number
  rejected_rows: RejectedRow[]
  issues: string[]
  raw_retention_key?: string
}

// ---- grain ----------------------------------------------------------------
export interface GrainCandidate {
  key_columns: string[]
  unique_over_full_data: boolean
  null_components: number
  duplicate_examples: Array<Record<string, string | number>>
  business_meaning: 'unconfirmed' | 'confirmed'
}

// ---- datasets -------------------------------------------------------------
export interface Dataset {
  dataset_id: string
  name: string
  revision: number | null
  latest_revision: number | null
  latest_revision_state: 'staged' | 'validating' | 'validated' | 'failed' | 'published' | null
  grain_confirmed: boolean
  grain: string[] | null
  row_count: number | null
}

export interface DatasetSchema {
  dataset_id: string
  revision: number
  columns: Record<string, string>
}

export interface GrainConfirmationResponse {
  dataset_id: string
  grain_confirmed: boolean
  key_columns: string[]
}

export interface PublishResponse {
  dataset_id: string
  published_revision: number
  status: 'published'
}

// ---- semantics ------------------------------------------------------------
export type PredicateOp =
  | 'is_not_null' | 'is_null' | 'eq' | 'not_in' | 'in' | 'lt' | 'gte'

export interface Predicate {
  op: PredicateOp
  field: string
  value?: unknown
}

export interface RatioExpression {
  kind: 'ratio'
  numerator: 'count'
  numerator_predicates: Predicate[]
  denominator_predicates: Predicate[]
}

export interface DurationPercentileExpression {
  kind: 'duration_percentile'
  start_field: string
  end_field: string
  unit: 'hours' | 'minutes' | 'days'
  quantile: number
}

export interface CountExpression {
  kind: 'count'
  predicates: Predicate[]
}

export type Expression =
  | RatioExpression
  | DurationPercentileExpression
  | CountExpression

export interface MetricDefinitionContent {
  metric_id: string
  name: string
  kind: 'ratio' | 'count' | 'duration_percentile'
  expression: Expression
  eligibility: Predicate[]
  time_basis: string
  timezone: string
  unit?: string | null
  zero_denominator?: 'null_with_flag'
  dataset_id: string
}

export type DefinitionStatus =
  | 'proposed' | 'approved' | 'withdrawn' | 'superseded' | 'rejected'

export interface MetricDefinition extends MetricDefinitionContent {
  version: number
  status: DefinitionStatus
}

export interface ApproveResponse extends MetricDefinitionContent {
  metric_id: string
  version: number
  status: 'approved'
}

export interface WithdrawResponse {
  metric_id: string
  withdrawn_version: number
  status: 'withdrawn'
}

// ---- metric query ---------------------------------------------------------
export interface Window {
  start: string
  end: string
  timezone: string
}

export interface MetricQueryRequest {
  schema_version: '1.0'
  metric_id: string
  semantic_release_id?: string | null
  dimensions?: string[]
  filters?: Predicate[]
  window: Window
  limit?: number
}

export type MetricRow = Record<string, string | number | null>

export interface MetricQueryAnswered {
  request_id: string
  status: 'answered'
  artifact_id: string
  metric_id: string
  definition_version: number
  semantic_release_id: string
  window: Window
  row_count: number
  rows: MetricRow[]
  quality_flags: string[]
  evidence_ref: string
  permissions_checked_at: string
}

export interface MetricQueryInsufficient {
  request_id: string
  status: 'insufficient_data'
  reason_code: string
  missing_requirements: string[]
  next_actions: string[]
}

export type MetricQueryResult = MetricQueryAnswered | MetricQueryInsufficient

// ---- outbox ---------------------------------------------------------------
export interface OutboxEvent {
  event_id: string
  event_type: string
  tenant_id: string
  aggregate_id: string
  aggregate_version: number
  occurred_at: string
  payload: string
}

// ---- forecasting (M2, spec §16) -------------------------------------------
export type ForecastFrequency = 'D' | 'W' | 'MS' | 'H'

export interface ForecastSuitability {
  sufficient: boolean
  reason: string | null
  observations?: number
  coverage?: number | null
  warnings?: string[]
  recommended_actions: string[]
  missing_requirements?: string[]
  frequency?: ForecastFrequency
}

export interface ForecastComparison {
  model_name: string
  mape: number | null
  mase: number | null
  rmse: number | null
  error?: string
}

export interface ForecastEvaluation {
  comparisons: ForecastComparison[]
  holdout_size: number
  train_size: number
  season_length: number
  frequency: ForecastFrequency
  baseline_model: string | null
}

export interface ForecastTrainRequest {
  dataset_id: string
  metric_id: string
  time_basis?: string
  horizon: number
  frequency: ForecastFrequency
  season_length?: number
}

export interface ForecastTrainResponse {
  status: 'trained' | 'insufficient_data'
  model_spec_id: string | null
  model_name?: string
  baseline_model?: string | null
  training_points?: number
  training_end?: string
  horizon?: number
  history?: Array<{ ds: string; y: number }>
  evaluation?: {
    metrics: { mape: number | null; mase: number | null; rmse: number | null }
    holdout_size: number
    comparisons: ForecastComparison[]
  }
  suitability?: ForecastSuitability
  assumptions?: string[]
  limitations?: string[]
  reason?: string
  reason_code?: string
  missing_requirements?: string[]
  next_actions?: string[]
}

export interface ForecastPredictRequest {
  model_spec_id: string
  horizon?: number
  prediction_intervals?: boolean
}

export interface ForecastPredictionPoint {
  ds: string
  yhat: number | null
  yhat_lower: number | null
  yhat_upper: number | null
  yhat_lower_80?: number | null
  yhat_upper_80?: number | null
}

export interface ForecastModelInfo {
  model_name: string
  frequency: ForecastFrequency
  season_length: number
  training_end: string
  training_points: number
  evaluation_metrics: { mape: number | null; mase: number | null; rmse: number | null }
  assumptions: string[]
  limitations: string[]
}

export interface ForecastPredictResponse {
  status: 'answered' | 'insufficient_data'
  model_spec_id?: string
  model_info?: ForecastModelInfo
  predictions?: ForecastPredictionPoint[]
  evidence_ref?: string
  reason?: string
  missing_requirements?: string[]
  next_actions?: string[]
}

// ---- workflow analytics (M3, spec §15) ------------------------------------
export interface WorkflowBottleneck {
  activity: string
  count: number
  median: number | null
  avg: number | null
  waiting_time: number | null
}

export interface WorkflowBottleneckResponse {
  status: 'answered' | 'insufficient_data'
  bottlenecks: WorkflowBottleneck[]
  unit: string
  revision: number
  evidence_ref: string
  reason?: string
}

export interface WorkflowVariant {
  path: string[]
  simplified_path: string[]
  case_count: number
  frequency: number
}

export interface WorkflowVariantResponse {
  status: 'answered'
  variants: WorkflowVariant[]
  total_variants: number
  total_cases: number
  revision: number
  evidence_ref: string
}

export interface WorkflowConformanceRule {
  from_activity: string
  to_activity: string
}

export interface WorkflowConformanceResponse {
  status: 'answered'
  fitness: number
  precision: number
  violated_cases: number
  total_cases: number
  example_violations: Array<{ case_id: string; from: string; to: string }>
  unknown_activities: string[]
  revision: number
  evidence_ref: string
}

export interface WorkflowCaseMetric {
  case_id: string
  duration: number | null
  age: number | null
  stage_count: number
  current: string
  closed: boolean
  overdue: boolean
  sla_status: 'met' | 'in_progress' | 'breached'
}

export interface WorkflowCaseMetricsResponse {
  status: 'answered'
  metrics: WorkflowCaseMetric[]
  sla_hours: number
  unit: string
  as_of: string
  summary: {
    total_cases: number
    met: number
    in_progress: number
    breached: number
  }
  revision: number
  evidence_ref: string
}

export interface WorkflowThroughputStage {
  stage: string
  count: number
  min: number | null
  median: number | null
  max: number | null
  p90: number | null
  from_activities: Record<string, number>
  to_activities: Record<string, number>
}

export interface WorkflowThroughputResponse {
  status: 'answered'
  stages: WorkflowThroughputStage[]
  unit: string
  revision: number
  evidence_ref: string
}

// ---- workflow analytics (M3, spec §15) ------------------------------------
export interface WorkflowBottleneck {
  activity: string
  count: number
  median: number | null
  avg: number | null
  waiting_time: number | null
}

export interface WorkflowBottleneckResponse {
  status: 'answered' | 'insufficient_data'
  bottlenecks: WorkflowBottleneck[]
  unit: string
  revision: number
  evidence_ref: string
  reason?: string
}

export interface WorkflowVariant {
  path: string[]
  simplified_path: string[]
  case_count: number
  frequency: number
}

export interface WorkflowVariantResponse {
  status: 'answered'
  variants: WorkflowVariant[]
  total_variants: number
  total_cases: number
  revision: number
  evidence_ref: string
}

export interface WorkflowConformanceRule {
  from_activity: string
  to_activity: string
}

export interface WorkflowConformanceResponse {
  status: 'answered'
  fitness: number
  precision: number
  violated_cases: number
  total_cases: number
  example_violations: Array<{ case_id: string; from: string; to: string }>
  unknown_activities: string[]
  revision: number
  evidence_ref: string
}

export interface WorkflowCaseMetric {
  case_id: string
  duration: number | null
  age: number | null
  stage_count: number
  current: string
  closed: boolean
  overdue: boolean
  sla_status: 'met' | 'in_progress' | 'breached'
}

export interface WorkflowCaseMetricsResponse {
  status: 'answered'
  metrics: WorkflowCaseMetric[]
  sla_hours: number
  unit: string
  as_of: string
  summary: {
    total_cases: number
    met: number
    in_progress: number
    breached: number
  }
  revision: number
  evidence_ref: string
}

export interface WorkflowThroughputStage {
  stage: string
  count: number
  min: number | null
  median: number | null
  max: number | null
  p90: number | null
  from_activities: Record<string, number>
  to_activities: Record<string, number>
}

export interface WorkflowThroughputResponse {
  status: 'answered'
  stages: WorkflowThroughputStage[]
  unit: string
  revision: number
  evidence_ref: string
}

// ---- scenario studio (M4, spec §17) --------------------------------------
export interface ScenarioTemplate {
  template_id: string
  name: string
  description: string
  sections: string[]
}

export interface ScenarioSolveResponse {
  status: 'optimal' | 'feasible_time_limited' | 'infeasible' | 'unbounded' | 'no_feasible_solution_found' | 'failed' | 'cancelled'
  template: string
  objective: number | null
  bound: number | null
  gap: number | null
  solver: string | null
  solver_version: string | null
  runtime: number | null
  variable_count: number
  infeasibility_report: { method: string; conflict_constraints?: string[]; note?: string } | null
}

// ---- api error ------------------------------------------------------------
export interface ApiErrorBody {
  status: number
  message: string
  code?: string
  detail?: unknown
}

// ---- monitoring (M5, spec §14) --------------------------------------------
export interface MonitoringHealthDataset {
  dataset_id: string
  freshness_hours: number | null
  revision_count: number
  latest_revision: number | null
  last_ingested_at: string | null
  status: 'healthy' | 'stale' | 'suspended' | 'unknown'
  revision_history: Array<{ revision: number; created_at: string; object_count: number }>
}

export interface MonitoringAlertRule {
  tenant_id: string
  id: string
  name: string
  dataset_id: string
  metric_id: string
  method: string
  season_length: number
  threshold: number
  min_effect_size: number
  persistence: number
  owner: string
  escalation: string
  runbook: string
  enabled: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export interface MonitoringCreateRuleRequest {
  name: string
  dataset_id: string
  metric_id: string
  method?: string
  season_length?: number
  threshold?: number
  min_effect_size?: number
  persistence?: number
  owner?: string
  escalation?: string
  runbook?: string
}

export interface MonitoringRuleListResponse {
  rules: MonitoringAlertRule[]
}

export interface MonitoringEvaluateResponse {
  status: string
  evaluated: number
  anomalies_fired: number
  episodes: Array<{
    episode_id: string
    rule_id: string
    condition_id: string
    workflow_status: string
    observed_value: number
    expected_lower: number
    expected_upper: number
    method: string
  }>
}

export interface MonitoringConditionState {
  id: string
  rule_id: string
  rule_name: string | null
  condition: string
  started_at: string | null
  recovered_at: string | null
}

export interface MonitoringAlertEpisode {
  tenant_id: string
  id: string
  rule_id: string
  episode_identity: string
  condition_id: string
  workflow_status: string
  observed_value: number | null
  expected_lower: number | null
  expected_upper: number | null
  scoring_method: string | null
  training_window: string | null
  effect_size: number | null
  persistence_count: number | null
  started_at: string
  resolved_at: string | null
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolution_notes: string | null
}

export interface MonitoringEpisodeListResponse {
  episodes: MonitoringAlertEpisode[]
}

// ---- investigations & evidence (D2, spec §10, §19) -----------------------
export type InvestigationStatus = 'open' | 'in_progress' | 'resolved' | 'closed'
export type SourceType = 'monitoring_episode' | 'workflow_bottleneck' | 'ad_hoc'
export type EvidenceType = 'observed' | 'estimated' | 'simulated' | 'causal_estimate' | 'hypothesis'
export type SupportStatus = 'supporting' | 'counter' | 'neutral' | 'unverified'
export type ExactnessClass = 'exact' | 'numerically_equivalent' | 'stochastically_reproducible' | 'presentation_reproducible'
export type ReproducibilityStatus = 'reproducible' | 'partially_reproducible' | 'unavailable_after_erasure'
export type BindingRole = 'primary_support' | 'contributing' | 'counter_evidence'

export interface StructuredFact {
  metric_id: string
  value: unknown
  unit?: string
  segment?: Record<string, unknown>
  period?: string
  comparison?: string | null
  lineage?: Record<string, unknown>
}

export interface EvidenceArtifact {
  artifact_id: string
  tenant_id: string
  investigation_id: string
  parent_artifact_ids: string[]
  evidence_type: EvidenceType
  support_status: SupportStatus
  quality_flags: string[]
  metric_id: string
  definition_version: number
  dataset_id: string
  dataset_revision: number
  resolved_plan: Record<string, unknown>
  query_params: Record<string, unknown>
  canonical_digest: string
  storage_format: 'json' | 'parquet'
  payload_json?: string | null
  parquet_key?: string | null
  row_count: number
  exactness_class: ExactnessClass
  reproducibility_status: ReproducibilityStatus
  created_by: string
  created_at: string
}

export interface InvestigationClaim {
  id: string
  tenant_id: string
  investigation_id: string
  evidence_id?: string | null
  statement: string
  evidence_type: EvidenceType
  support_status: SupportStatus
  quality_flags: string[]
  structured_fact: StructuredFact
  created_by: string
  created_at: string
}

export interface Investigation {
  id: string
  tenant_id: string
  title: string
  question: string
  source_type: SourceType
  source_id?: string | null
  status: InvestigationStatus
  owner: string
  analytical_state: Record<string, unknown>
  alternative_explanations: string[]
  created_by: string
  created_at: string
  updated_at: string
  claims?: InvestigationClaim[]
  evidence?: EvidenceArtifact[]
}

export type DecisionStatus =
  | 'draft' | 'proposed' | 'accepted' | 'implementation_pending'
  | 'active' | 'review_due' | 'evaluated' | 'closed'
  | 'rejected' | 'deferred' | 'abandoned' | 'superseded'

export interface DecisionBrief {
  problem: string
  relevant_findings: string[]
  proposed_action: string
  baseline_option: string
  scope: string
  owner: string
  trade_offs: string[]
  assumptions: string[]
  evidence_coverage: string[]
  validation_plan: string
  counter_metrics: string[]
  expected_effect: 'unknown' | 'deterministic' | 'estimated' | 'simulated'
}

export interface CounterevidenceCheck {
  hypothesis: string
  state: 'detected' | 'not_detected' | 'not_testable' | 'not_run'
  detail?: string | null
}

export interface DecisionAmendment {
  version: number
  author: string
  reason: string
  scope: string
  previous_version: number
  created_at: string
  changes?: Record<string, unknown> | null
}

export interface OutcomeRecord {
  observed_results: Record<string, unknown>
  pinned_definition_version?: number | null
  data_revision?: number | null
  measurement_window: string
  expectation: string
  estimated_effect?: Record<string, unknown> | null
  study_run?: string | null
  data_quality_caveats: string[]
  review_verdict: 'supported_improvement' | 'no_clear_change' | 'deterioration' | 'inconclusive' | 'not_evaluable'
  verdict_evidence: string
}

export interface DecisionEvidenceBinding {
  id: string
  tenant_id: string
  decision_id: string
  evidence_id: string
  binding_role: BindingRole
  bound_by: string
  bound_at: string
  evidence?: Partial<EvidenceArtifact>
}

export interface DecisionRecord {
  id: string
  tenant_id: string
  title: string
  status: DecisionStatus
  brief: DecisionBrief
  counterevidence: CounterevidenceCheck[]
  amendments: DecisionAmendment[]
  outcome?: OutcomeRecord | null
  created_by: string
  created_at: string
  updated_at: string
  evidence_bindings?: DecisionEvidenceBinding[]
}

// ---- analytics studio (P1b) -----------------------------------------------
export type AnalyticsAggregation = 'count' | 'sum' | 'avg' | 'min' | 'max' | 'count_distinct'

export type AnalyticsFilterOperator =
  | 'eq' | 'neq' | 'in' | 'not_in' | 'gt' | 'gte' | 'lt' | 'lte' | 'is_null' | 'is_not_null'

export interface AnalyticsMeasure {
  column: string
  agg: AnalyticsAggregation
  alias?: string | null
}

export interface AnalyticsFilter {
  column: string
  op: AnalyticsFilterOperator
  value?: unknown
}

export interface AnalyticsQuery {
  dataset_id: string
  revision?: number | null
  dimensions: string[]
  measures: AnalyticsMeasure[]
  filters: AnalyticsFilter[]
  time_column?: string | null
  time_from?: string | null
  time_to?: string | null
  limit?: number
  order_by?: string | null
  order_dir?: 'asc' | 'desc'
}

export interface AnalyticsColumn {
  name: string
  type: string
}

export interface AnalyticsQueryResponse {
  dataset_id: string
  revision: number
  columns: AnalyticsColumn[]
  rows: Array<Array<string | number | boolean | null>>
  row_count: number
  truncated: boolean
  evidence_ref: string
  executed_at: string
  took_ms: number
}

export interface AnalysisArtifact {
  id: string
  name: string
  dataset_id: string
  revision: number
  query: AnalyticsQuery
  result_digest: string | null
  row_count: number
  created_by: string
  created_at: string
  updated_at: string
  last_result?: AnalyticsQueryResponse | null
}

// ---- AI intelligence (P2b, spec §P2) --------------------------------------
export type AiProviderStatus = 'active' | 'error'
export type AiProviderKind = 'openai_compatible'

export type AiModelRole =
  | 'primary' | 'fast' | 'reasoning' | 'coding' | 'embedding' | 'fallback'

export interface AiProvider {
  id: string
  name: string
  kind: AiProviderKind | string
  base_url: string
  models: string[]
  status: AiProviderStatus
  last_tested_at: string | null
  last_error: string | null
  key_suffix: string
  key_fingerprint: string
  created_by?: string
  created_at?: string
  updated_at?: string
}

export interface AiModelRoleMapping {
  provider_id: string
  provider_name: string
  provider_status: AiProviderStatus | string
  model_id: string
}

export type AiModelMapping = Record<AiModelRole, AiModelRoleMapping | null> & {
  roles: Record<AiModelRole, AiModelRoleMapping | null>
}

export interface AiToolCall {
  name: string
  input: Record<string, unknown>
  ok: boolean
  evidence_ref: string | null
  refused: boolean
  code: string | null
  error: string | null
}

export interface AiChatUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface AiUsageEvent {
  model_id: string
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number | null
  round: number
}

export interface AiChatWarning {
  ungrounded_numbers: string[]
}

export interface AiChatResponse {
  answer: string
  tool_calls: AiToolCall[]
  usage: AiChatUsage
  usage_events: AiUsageEvent[]
  latency_ms: number
  conversation_id: string
  message_id: string
  provider_id: string
  model_id: string
  warning?: AiChatWarning
  ungrounded_numbers?: string[]
}

export interface AiConversationSummary {
  id: string
  title: string
  created_by: string
  created_at: string
  updated_at: string
  archived: boolean
  message_count: number
}

export interface AiMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  tool_trace: AiToolCall[]
  usage: Partial<AiChatUsage>
  created_at: string
}

export interface AiConversationDetail {
  id: string
  title: string
  created_by: string
  created_at: string
  updated_at: string
  archived: boolean
  messages: AiMessage[]
}

export interface AiUsageTotals {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
  latency_ms: number
}

export interface AiUsageByProvider {
  provider_id: string
  provider_name: string | null
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
}

export interface AiUsageByModel {
  provider_id: string
  model_id: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
}

export interface AiUsageByDay {
  day: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
}

export interface AiUsageByProviderModelDay extends AiUsageByDay {
  provider_id: string
  model_id: string
}

export interface AiUsageReport {
  totals: AiUsageTotals
  by_provider: AiUsageByProvider[]
  by_model: AiUsageByModel[]
  by_day: AiUsageByDay[]
  by_provider_model_day: AiUsageByProviderModelDay[]
}
