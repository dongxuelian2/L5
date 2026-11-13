import type { AnalysisResult, Config } from "./types";

export type FaultEvent = {
  id: string;
  type: string;
  target: string;
  onset: number;
  recovery: number | null;
  severity: number;
  profile: string;
  parameters: Record<string, number | null>;
};
export type FaultSchedule = FaultEvent & { intervals: { start: number; end: number }[] };
export type Scenario = {
  name?: string;
  model_id: string;
  initial: Record<string, number>;
  parameters: Record<string, number>;
  duration: number;
  sample_interval: number;
  integration_step: number;
  seed: number;
  measurement: { noise: number; missing_fraction: number; physical_noise: number; signals: string[] };
  faults: FaultEvent[];
};
export type SavedScenario = { id: string; name: string; scenario: Scenario };
export type NumberField = {
  key: string;
  label: string;
  default: number | null;
  min: number;
  max: number;
  unit?: string;
  type?: "integer" | "number";
  nullable?: boolean;
};
export type Signal = { key: string; tag: string; unit: string; label: string };
export type Model = { id: string; name: string; version: string; signals: Signal[]; initial: NumberField[]; parameters: NumberField[] };
export type Detector = Partial<Omit<Config, "training">> & {
  algorithm: string;
  training?: { seed?: number; initial?: Record<string, number>; parameters?: Record<string, number>; noise?: number };
};
export type Catalog = {
  models: Model[];
  fault_types: { id: string; targets: string[]; parameters: NumberField[] }[];
  profiles: { id: string; parameters: NumberField[] }[];
  defaults: Scenario;
  limits: { max_faults: number; max_samples: number };
  algorithms: Record<string, string>;
  default_detectors: Detector[];
  objectives: string[];
  max_cases: number;
  max_search_cases: number;
  benchmark_version: string;
  benchmark_detectors: Detector[];
};
export type Observation = {
  t: number;
  values: Record<string, number | null>;
  quality: Record<string, string>;
  source_times: Record<string, number | null>;
  acquisition_times: Record<string, number | null>;
};
export type Simulation = {
  scenario: Scenario;
  model_version: string;
  signals: Signal[];
  observations: Observation[];
  observation_packets: { signal: string; sample_time: number; source_time: number | null; acquisition_time: number | null; value: number | null; quality: string; flags: string[] }[];
  schedule: FaultSchedule[];
  truth: { physical: (Record<string, number> & { t: number })[]; events: FaultSchedule[]; severities: Record<string, number[]> };
};
export type RunSummary = { id: string; name: string; created_at: string; dataset_id: string | null };
export type Run = Simulation & RunSummary;
export type Burden = {
  samples: number;
  observedSamples: number;
  alarmSamples: number;
  alarmFraction: number | null;
  alarmEvents: number;
  alarmDuration: number;
};
export type EventMetric = {
  id: string;
  type: string;
  target: string;
  onset: number;
  recovery: number | null;
  observedSamples: number;
  presenceDetected: boolean;
  detected: boolean;
  firstDetection: number | null;
  delay: number | null;
};
export type Metrics = {
  totalEvents: number;
  detectedEvents: number;
  missedEvents: number;
  unobservedEvents: number;
  eventDetectionRate: number | null;
  meanDelay: number | null;
  presenceDetected: boolean | null;
  allEventsMatched: boolean | null;
  coverage: number;
  meanObservationFraction: number;
  normal: Burden;
  preFault: Burden | null;
  events: EventMetric[];
  simultaneousSamples: number;
  simultaneousObservedSamples: number;
  simultaneousAlarmSamples: number;
  searchScores: Record<string, number>;
  suppression?: {
    events: { id: string; isolatedPresence: boolean; combinedPresence: boolean; isolatedMatched: boolean; combinedMatched: boolean; isolatedDelay: number | null; combinedDelay: number | null }[];
    lostPresenceEvents: number;
    lostMatches: number;
  };
};
export type Evaluation = { analysis: AnalysisResult; metrics: Metrics };
export type CaseSummary = {
  id: string;
  index: number;
  name: string;
  phase: string;
  family: string;
  objective?: string | null;
  detector: Detector;
  status: string;
  metrics?: Omit<Metrics, "events"> | null;
  runtime_ms?: number | null;
  error?: string | null;
  dataset_id?: string | null;
};
export type CaseDetail = CaseSummary & { simulation?: Simulation | null; evaluation?: Evaluation | null };
export type CampaignSummary = {
  id: string;
  name: string;
  status: string;
  total: number;
  completed: number;
  created_at: string;
  updated_at: string;
  error?: string | null;
};
export type Campaign = CampaignSummary & { cases: CaseSummary[] };
export type CampaignSpec = {
  name: string;
  mode: "grid" | "search" | "benchmark";
  scenario?: Scenario;
  detectors?: Detector[];
  axes?: ({ path: string; values: unknown[] } | { path: string; min: number; max: number })[];
  seed?: number;
  budget?: number;
  objective?: string;
};
export type EvidenceRef = { run_id: string } | { campaign_id: string; case_id: string };
