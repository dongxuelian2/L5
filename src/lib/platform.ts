export type Row = { t: number } & Record<string, number | null>;
export type Candidate = {
  id: string;
  name: string;
  score: number;
  confidence: string;
  support: string[];
  against: string[];
  unresolved: string[];
  topology: number;
  parts: { signal: string; weight: number; contribution: number }[];
};
export type Health = {
  status: string;
  usable: boolean;
  missing: number;
  detail: string;
  freshness: number | null;
};
export type Diagnosis = {
  candidates: Candidate[];
  status: string;
  firstDetection: number | null;
  detections: Record<
    string,
    { time: number; onset: number; direction: number }
  >;
  health: Record<string, Health>;
  changes: Record<string, number>;
  clock: { regular: boolean; gaps: number; step?: number };
  paths: {
    source: string;
    target: string;
    kind: string;
    lag: number;
    correlation: number;
    trusted: boolean;
  }[];
  controllers: {
    id: string;
    sp: number | null;
    pv: number | null;
    op: number | null;
    feedback: number | null;
    limit: number | null;
    mismatch: number | null;
  }[];
  nextMeasurements: {
    signal: string;
    tag: string;
    value: number;
    distinguishes: string[];
    reason: string;
  }[];
};
export type Alarms = {
  eventCount: number;
  uniqueConditions: number;
  reannunciations: number;
  firstAlarm: number | null;
  clusters: string[];
  floods: { start: number; end: number }[];
  events: { t: number; condition: string; kind: string; chain: string }[];
  conditions: {
    id: string;
    signal: string;
    chain: string;
    first: number;
    activations: number;
    duration: number;
    classification: string;
    events: number;
    actionable: boolean;
  }[];
  rationalization: {
    condition: string;
    kind: string;
    recommendation: string;
    repeats: number;
  }[];
};
export type Trace = {
  index: number;
  tool: string;
  args: unknown;
  result: unknown;
  status: string;
};
export type Sop = {
  id: string;
  title: string;
  revision: string;
  preconditions: { name: string; satisfied: boolean }[];
  applicable: boolean;
  action: string;
  status: string;
  conflict: string;
};
export type Analysis = {
  diagnosis: Diagnosis;
  alarms: Alarms;
  trace: Trace[];
  sop: Sop;
};
