import type { DetectionMetrics, LabelSet, TaskMetrics } from "./experimentTypes";
import type { Dataset, Interval } from "./types";

export type RegimeReference = { datasetId: string; range: [number, number]; labelSetId?: string };
export type RegimeAlgorithm = "robust-maxz" | "pca-q" | "pca-t2";
export type RegimeDetector = { algorithm: RegimeAlgorithm; alpha: number; variance: number };
export type RegimeDefinition = {
  id: string;
  label: string;
  fit: RegimeReference[];
  calibration: RegimeReference[];
  detector?: Partial<RegimeDetector>;
};
export type RegimeConfig = {
  name: string;
  signals: string[];
  modes: RegimeDefinition[];
  detector: RegimeDetector;
  gapThreshold?: number | null;
  recognition: {
    recognitionSignals: string[];
    recognitionAlpha: number;
    shrinkage: number;
    minMargin: number;
    dwell: number;
    persistence: number;
    referenceMode: string;
  };
};
export type RegimeModelSummary = { id: string; name: string; createdAt: string; config: RegimeConfig };
type FittedDetector = RegimeDetector & { threshold: number };
type FittedMode = {
  center: number[];
  covariance: number[][];
  regularizedCovariance: number[][];
  distanceThreshold: number;
  fitSamples: number;
  calibrationSamples: number;
  detector: FittedDetector;
};
type RegimeComparison = {
  fromMode: string;
  toMode: string;
  meanDistance: number;
  covarianceDistance: number;
  signals: { signal: string; meanDifference: number; standardizedDifference: number }[];
};
export type RegimeModel = RegimeModelSummary & {
  sources: Record<string, Dataset>;
  referenceDatasetId: string;
  model: {
    version: string;
    modes: Record<string, FittedMode>;
    globalDetector: FittedDetector;
    singleDetector: FittedDetector;
    comparisons: RegimeComparison[];
  };
};
export type RegimeStatus = "normal" | "transition" | "abnormal" | "unknown";
export type RegimeRecognition = "supported" | "ambiguous" | "unknown" | "insufficient";
export type RegimeEvidence = { distance: number; threshold: number; discriminant: number; supported: boolean };
export type RegimeDecision = {
  time: number;
  mode: string | null;
  activeMode: string | null;
  candidateMode: string | null;
  scoringMode: string | null;
  recognition: RegimeRecognition;
  evidence: Record<string, RegimeEvidence>;
  margin: number | null;
  status: RegimeStatus;
  transition: boolean;
  candidateSamples: number;
  alarm: boolean;
  score: number | null;
  threshold: number | null;
  globalScore: number | null;
  globalAlarm: boolean;
  globalThreshold: number | null;
  singleScore: number | null;
  singleAlarm: boolean;
  singleThreshold: number | null;
};
export type RegimeTransition = {
  fromMode: string;
  toMode: string;
  startTime: number;
  candidateTime: number;
  confirmedTime: number | null;
  endTime: number | null;
  resolvedTime: number | null;
  initialMargin: number | null;
  candidateSamples: number;
  outcome: "confirmed" | "transient" | "pending";
};
export type RegimeInterval = Interval & { mode?: string | null; kind?: string };
export type RegimeApproach = "regime" | "global" | "single";
export type RegimeRunSummary = {
  id: string;
  name: string;
  modelId: string;
  datasetId: string;
  createdAt: string;
};
export type RegimeRun = RegimeRunSummary & {
  evaluation: RegimeReference;
  model: RegimeModel;
  source: Dataset;
  analysisId: string;
  times: number[];
  decisions: RegimeDecision[];
  transitions: RegimeTransition[];
  intervals: RegimeInterval[];
  series: { time: number[]; values: Record<string, (number | null)[]> };
  labelSet: LabelSet | null;
  protocol: "chronological-holdout" | "distinct-dataset";
  gapThreshold: number | null;
  metrics: Record<RegimeApproach, TaskMetrics & { detection: DetectionMetrics }>;
};
