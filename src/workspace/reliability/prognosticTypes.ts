export type Method = "linear" | "stochastic";
export type ForecastStatus = "ok" | "insufficient_data" | "not_identifiable" | "numerical_failure" | "threshold_reached" | "beyond_horizon";
export type MaintenanceCosts = {
  preventive_cost: number;
  corrective_cost: number;
  downtime_cost: number;
  preventive_duration: number;
  corrective_duration: number;
  failure_consequence: number;
  replacement_cost: number;
  replacement_duration: number;
  scheduled_time?: number | null;
  discount_rate?: number | null;
  planning_horizon?: number | null;
};
export type MaintenanceEvent = { time: number; action: "restore" | "replace" };
export type PrognosticConfig = {
  datasetId: string;
  assetId: string;
  assetName: string;
  indicator: {
    signal: string;
    definition: string;
    unit: string;
    failure_threshold: number;
    operating_threshold?: number | null;
    direction: "increasing" | "decreasing";
  };
  loadSignal?: string | null;
  start?: number | null;
  cutoff?: number | null;
  horizon: number;
  method: Method;
  seed?: number;
  probabilityHorizons?: number[] | null;
  maintenance: MaintenanceCosts;
  events?: MaintenanceEvent[];
  operatingPeriods?: [number, number][];
  endStatus?: "censored" | "failed";
  failureTime?: number | null;
};
export type Forecast = {
  status: ForecastStatus;
  method: Method;
  model_version: string;
  cutoff: number;
  horizon: number;
  history: { time: number; value: number | null; load: number | null; fitted: number | null }[];
  trajectory: { time: number; offset: number; median: number; lower: number; upper: number }[];
  distribution: { time: number; probability: number }[];
  rul: {
    median: number | null;
    lower: number | null;
    upper: number | null;
    confidence: number;
    probabilities: { horizon: number; probability: number | null }[];
    probability_not_reached_by_horizon: number | null;
    probability_never_reached_under_model: number | null;
  };
  diagnostics: Record<string, number | string | boolean | null | number[] | number[][] | MaintenanceEvent>;
  assumptions: string[];
  assumption_keys?: string[];
};
export type MaintenanceOption = {
  action: "continue" | "preventive" | "schedule" | "replace" | "corrective";
  time: number | null;
  failure_probability: number;
  expected_cost: number;
  expected_failure_cost: number;
  expected_intervention_cost: number;
};
export type Maintenance = {
  status: string;
  horizon: number;
  recommended: MaintenanceOption | null;
  options: MaintenanceOption[];
  curve: MaintenanceOption[];
  assumptions: string[];
  assumption_keys?: string[];
};
export type FitResult = {
  config: PrognosticConfig;
  forecast: Forecast;
  maintenance: Maintenance;
  source: { datasetId?: string; datasetName?: string; loadSignal?: { displayName: string; name: string; unit: string } | null };
};
export type Session = FitResult & {
  id: string;
  name: string;
  created_at: string;
  evaluation?: Evaluation | null;
};
export type SessionSummary = Pick<Session, "id" | "name" | "created_at"> & {
  datasetId: string;
  assetName: string;
  status: ForecastStatus;
};
type Reliability = {
  horizon: number;
  count: number;
  brier: number | null;
  predicted: number | null;
  observed: number | null;
  bins: { lower: number; upper: number; count: number; predicted: number | null; observed: number | null }[];
};
export type EvaluationGroup = {
  case_count: number;
  statuses: Partial<Record<ForecastStatus, number>>;
  rul: {
    count: number;
    median_available: number;
    mae: number | null;
    bias: number | null;
    interval_count: number;
    coverage: number | null;
  };
  reliability: Reliability[];
  stability: { count: number; mean_absolute_revision: number | null };
  maintenance: {
    count: number;
    policy: number | null;
    continue: number | null;
    immediate: number | null;
    fixed_midpoint: number | null;
  };
};
export type Evaluation = {
  protocol: {
    id: string;
    development_seed: number;
    evaluation_seeds: number[];
    cutoffs: number[];
    horizons: number[];
    planning_horizon: number;
    interval_coverage: string;
    censoring: string;
  };
  trajectories: {
    scenario: string;
    replicate: number;
    observation_end: number;
    failure_time: number | null;
    observations: number;
    missing: number;
  }[];
  models: (EvaluationGroup & { method: Method; by_scenario: (EvaluationGroup & { scenario: string })[] })[];
};
