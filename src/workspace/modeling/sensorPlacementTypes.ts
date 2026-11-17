export type SensorMode = "available" | "required" | "excluded";
export type Objective = "separation" | "detectability" | "isolability" | "information";
export type Profile = "nominal" | "mean" | "worst";
export type Sensor = { key: string; label: string; unit: string; tag: string };
export type Setup = {
  modelId: string; horizon: number; step: number; onset: number; duration: number | null;
  sensors: { key: string; noise: number; cost: number; mode: SensorMode }[];
  correlations: number[][]; hypotheses: string[]; intensities: Record<string, number>;
  conditions: { id: string; parameters: Record<string, number> }[];
  budget: number; maxSensors: number; objective: Objective; aggregation: Profile;
};
export type SavedRun = { id: string; name: string; created_at: string };
export type Options = {
  runs: SavedRun[]; defaults: Setup; sensors: Sensor[]; conditions: string[];
  models: { id: string; version: string; name: string }[];
  modelFields: { key: string; label: string; unit: string; min: number; max: number }[];
};
export type Spectrum = { singularValues: number[]; tolerance: number; rank: number; condition: number | null };
export type Scores = Record<Objective, number>;
export type Evidence = Scores & { distances: number[][]; spectrum: Spectrum; signatureSpectrum: Spectrum; sensitivityNorms: number[][] };
export type Subset = Record<Profile, Scores> & { sensors: string[]; cost: number; pareto: boolean; conditions: Evidence[] };
export type Condition = {
  id: string; times: number[]; templates: number[][][]; signatures: number[][][]; sensitivities: number[][][];
  noiseScale: number; covariance: number[][]; model: Record<string, unknown>;
  derivativeStability: { fault: string; relativeL2: number[]; absoluteL2: number[] }[];
};
export type Comparison = {
  id: string; trialsPerHypothesis: number; falseAlarmRate: number; detectionRate: number; detectionByFault: number[];
  classificationAccuracy: number; accuracyAmongClassified: number | null; ambiguousRate: number;
  unclassifiedRate: number; counts: number[][]; trueMinimumSeparation: number;
  pairwise: { faults: string[]; accuracy: number; ambiguousRate: number }[];
};
export type Evaluation = {
  calibrationSeed: number; holdoutSeed: number; calibrationTrials: number; targetFalseAlarm: number;
  fitQuantile: number; logLikelihoodMargin: number; chosenLayout: string;
  cohorts: { id: string; representative: number[][][]; model: Record<string, unknown> }[];
  layouts: { id: string; sensors: string[]; cost: number; runtimeMs: number; minimumSeparation: number;
    threshold: number; fitLimit: number; cohorts: Comparison[] }[];
};
export type Cancellation = {
  times: number[]; hypotheses: string[]; templates: number[][][]; tank1Rms: number[];
  cases: { id: string; pumpIntensity: number; valveIntensity: number; noiseScale: number; templates: number[][][];
    metrics: { sensors: string[]; detectability: number; isolability: number; competitor: string;
      detectionPower: number; nearestPairError: number }[] }[];
};
export type Analysis = {
  config: Setup; sensors: Sensor[]; hypotheses: string[]; parameters: string[];
  conditions: Condition[]; subsets: Subset[]; winners: Record<Profile, string[]>;
  runtimeMs: number; weakDistance: number; sensitivityStep: number; informationPriorSd: number;
  cancellation: Cancellation; evaluation: Evaluation;
};
export type Run = SavedRun & { analysis: Analysis };
export type TrajectoryRequest = { condition: string; hypothesis: string; sensors: string[]; cohort?: string };
export const objectives: Objective[] = ["separation", "detectability", "isolability", "information"];
export const profiles: Profile[] = ["nominal", "mean", "worst"];
