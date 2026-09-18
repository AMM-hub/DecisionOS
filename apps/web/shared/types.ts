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

// ---- api error ------------------------------------------------------------
export interface ApiErrorBody {
  status: number
  message: string
  code?: string
  detail?: unknown
}
