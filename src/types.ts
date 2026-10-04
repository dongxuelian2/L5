export type SignalKey =
  "valve" | "flow" | "temperature" | "pressure" | "separator" | "purity";
export type Tone = "mint" | "amber" | "coral" | "violet";
export type Point = Record<SignalKey, number> & { t: number };
export interface Tag {
  key: SignalKey;
  tag: string;
  name: string;
  unit: string;
  baseline: number;
  precision: number;
  color: Tone;
  chain: string;
}
export interface Alarm {
  id: string;
  t: number;
  tag: string;
  key: SignalKey;
  severity: string;
  value: number;
  chain: string;
  message: string;
  repeat: boolean;
}
export interface Candidate {
  id: string;
  name: string;
  tag: string;
  score: number;
  status: string;
  support: string;
  against: string;
  evidence: string[];
}
export interface AnalysisStep {
  action: string;
  tool: string;
  result: string;
}
export interface IncidentBrief {
  schemaVersion: 1;
  incidentId: string;
  provider: "local" | "model";
  prompt: string;
  steps: AnalysisStep[];
  summary: string;
  limitation: string;
  candidateId: string;
  evidenceTags: SignalKey[];
}
export interface Scenario {
  schemaVersion: number;
  id: string;
  title: string;
  duration: number;
  faultTime: number;
  provenance: {
    kind: string;
    model: string;
    source: string;
    stepSeconds: number;
    isTEP: boolean;
    analyst: string;
  };
  tags: Tag[];
  edges: [SignalKey, SignalKey][];
  points: Point[];
  detections: Record<
    SignalKey,
    { time: number; onset: number; z: number; median: number; mad: number }
  >;
  alarms: Alarm[];
  branches: {
    time: number;
    points: Point[];
    alarms: number;
    peakPressure: number;
    finalPressure: number;
    trip: boolean;
  }[];
  tripTime: number;
  firstAlarm: number;
  leadTime: number;
  checks: { name: string; passed: boolean; detail: string }[];
  chains: { id: string; name: string; path: SignalKey[]; color: Tone }[];
  candidates: Candidate[];
  analyst: {
    prompt: string;
    steps: AnalysisStep[];
    summary: string;
    limitation: string;
  };
  diagnostics: {
    matrix: number[][];
    paths: {
      source: SignalKey;
      target: SignalKey;
      lag: number;
      correlation: number;
      ordered: boolean;
    }[];
    streams: {
      t: number;
      signals: Record<SignalKey, { z: number; cusum: number; delta: number }>;
    }[];
    ranking: Record<
      string,
      {
        score: number;
        parts: Record<string, number>;
        explained: number;
        paths: number;
      }
    >;
    formula: string;
  };
}
