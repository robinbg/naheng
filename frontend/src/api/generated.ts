// Generated from actual FastAPI OpenAPI; run tools/generate_api_types.py after contracts change.
export interface ForecastQuery {
  schema_version?: number;
  snapshot_id: string;
  future_policy_id: string;
  environment_id: string;
  horizon_s: number;
  endpoint_protocol: string;
  sample_budget?: number;
  current_A?: number;
  ambient_K?: number;
  seed?: number;
}
export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}
export interface LifecycleRequest {
  profile?: string;
  mode?: "interactive" | "batch";
  sell_price_per_kWh?: number;
  buy_price_per_kWh?: number;
  replacement_cost_CNY?: number;
}
export interface ModelPackage {
  schema_version?: number;
  package_id: string;
  chemistry_id: string;
  parameter_revision: string;
  state_definition: Record<string, unknown>;
  dynamics_ast: Record<string, unknown>;
  readout_ast: Record<string, unknown>;
  reduction_map: Record<string, unknown>;
  lifting_map: Record<string, unknown>;
  domain: Record<string, unknown>;
  error_contracts: Array<Record<string, unknown>>;
  evidence_refs: Array<string>;
  validity_monitor: Record<string, unknown>;
  fallback_refs: Array<string>;
  artifact_hashes: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  package_hash?: string | null;
}
export interface RegisteredModelPackage {
  schema_version?: number;
  package_id: string;
  chemistry_id: string;
  parameter_revision: string;
  state_definition: Record<string, unknown>;
  dynamics_ast: Record<string, unknown>;
  readout_ast: Record<string, unknown>;
  reduction_map: Record<string, unknown>;
  lifting_map: Record<string, unknown>;
  domain: Record<string, unknown>;
  error_contracts: Array<Record<string, unknown>>;
  evidence_refs: Array<string>;
  validity_monitor: Record<string, unknown>;
  fallback_refs: Array<string>;
  artifact_hashes: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  package_hash?: string | null;
  validation_status: "metadata_only" | "executable";
  execution_binding: string;
  parameter_hash: string | null;
  binding_hashes: Record<string, unknown>;
  evidence_validity: string;
}
export interface RunRef {
  run_id: string;
}
export interface RunRequest {
  scenario_id?: string;
  ambient_K?: number;
  initial_soc?: number;
  sell_price_per_kWh?: number;
  buy_price_per_kWh?: number;
  duration_s?: number;
  stored_sodium_rate_upper_mol_per_s?: number | null;
  mode?: string;
}
export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
  input?: Record<string, unknown>;
  ctx?: Record<string, unknown>;
}
