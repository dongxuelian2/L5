import type { Signal, TimeAxis } from "./types";

export type SafetyKind = "value" | "rate" | "relationship";
export type SafetyState = "normal" | "warning" | "violation" | "unavailable";
export type SafetyDefinition = {
  id: string; name: string; kind: SafetyKind; unit: string; terms: { signalId: string; coefficient?: number }[];
  lower?: number | null; upper?: number | null; warningLower?: number | null; warningUpper?: number | null;
  dwellSeconds?: number | null; hysteresis?: number | null; maxGapSeconds?: number | null; absolute?: boolean; equipment?: string;
};
export type SafetyConfiguration = {
  id: string; workspaceId: string; datasetId: string; name: string; revision: number;
  constraints: SafetyDefinition[]; createdAt: string; updatedAt: string;
};
export type SafetyAssessmentSummary = { id: string; workspaceId: string; datasetId: string; name: string; createdAt: string };
export type SafetyInterval = {
  state: SafetyState; start: number; end: number; duration: number; samples: number; confirmedAt?: number | null;
  peakTime?: number | null; peakValue?: number | null; minimumMargin?: number | null; maximumExceedance?: number | null;
};
export type SafetySeries = {
  times: number[]; values: (number | null)[]; measurements?: Record<string, (number | null)[]>;
  measurementObserved?: Record<string, boolean[]>;
  margins: (number | null)[]; states: SafetyState[]; rawStates: SafetyState[]; segmentIds?: number[];
};
export type SafetyObservation = {
  constraint: SafetyDefinition; signalIds: string[]; marginUnit: string; sourceUnits: Record<string, string>;
  quality: {
    gapThreshold: number | null; gaps: { start: number; end: number; duration: number }[];
    duplicateCount: number; missingSamples: number; unobservedSamples: number; rateUnavailableSamples: number; numericalUnavailableSamples: number;
  };
  coverage: { totalSamples: number; evaluatedSamples: number; sampleFraction: number | null; observedDuration: number; durationFraction: number | null };
  current: { time: number; value: number | null; margin: number | null; state: SafetyState; rawState: SafetyState; measurements: Record<string, number | null>; duplicateTimestamp?: boolean } | null;
  intervals: SafetyInterval[]; rawViolationIntervals: SafetyInterval[]; maximumExceedance: number | null; violationDuration: number; minimumMargin: number | null; series: SafetySeries;
};

export const uncertaintyParameters = ["level1", "level2", "pumpRateFraction", "connectionFraction", "outletFraction", "pumpCommand", "valveOpening", "outletValve", "leakCoefficient"] as const;
export const forecastParameters = ["area1", "area2", "pumpRate", "connection", "outlet", "outletValve", "tankHeight", "integrationStep"] as const;
export type ForecastParameter = typeof forecastParameters[number];
export type UncertaintyParameter = typeof uncertaintyParameters[number];
export type ForecastOptions = {
  asOf?: number; horizonSeconds?: number; stepSeconds?: number; maxObservationAgeSeconds?: number;
  input?: { mode: "hold" | "override"; pumpCommand?: number; valveOpening?: number; leakCoefficient?: number };
  parameters?: Partial<Record<ForecastParameter, number>>;
  uncertainty?: { samples?: number; seed?: number; ranges?: Partial<Record<UncertaintyParameter, [number, number]>> };
};
type ForecastConstraintSummary = {
  constraintId: string; status: "crossing" | "no-crossing" | "unavailable"; timeToViolation: number | null; firstCrossingTime: number | null;
  minimumMargin: number | null; maximumExceedance: number | null; violationDuration: number | null;
  currentMargin?: number | null; currentState?: SafetyState; reasonCode?: string; marginUnit?: string; startedInViolation?: boolean;
};
export type ForecastConstraint = ForecastConstraintSummary & { intervals: SafetyInterval[]; series: SafetySeries | null };
export type Sensitivity = { parameter: UncertaintyParameter; lowerValue: number; upperValue: number; lowerMargin: number | null; upperMargin: number | null; marginChange: number | null };
export type SafetyForecast = {
  status: "available" | "unavailable" | "unreliable"; reason?: string; reasonCode?: string;
  model: { id: string; version: string; parameters: Record<string, number> } | null;
  observedThrough: number | null; requestedAsOf: number | null;
  assumptions: Record<string, unknown> & { observedInputComparison?: { measuredInlet: number | null; modeledInlet: number; measuredMinusModeledInlet: number | null; unit: string } };
  inputMeasurements: unknown;
  trajectory: { times: number[]; values: Record<string, number[]>; units?: Record<string, string> } | null;
  constraints: ForecastConstraint[];
  uncertainty: {
    samples: number; seed: number; ranges: Partial<Record<UncertaintyParameter, [number, number]>>;
    scenarios: { id: string | number; perturbations: Partial<Record<UncertaintyParameter, number>>; status: string; reason?: string; reasonCode?: string; constraints: ForecastConstraintSummary[] }[];
    constraints: {
      constraintId: string; evaluatedScenarios: number; unavailableScenarios: number; crossingScenarios: number; violationFraction: number | null;
      earliestCrossingTime: number | null; latestCrossingTime: number | null; worstMargin: number | null; sensitivity: Sensitivity[];
    }[];
  } | null;
};
export type SafetyAssessment = Omit<SafetyAssessmentSummary, "id"> & {
  id?: string; configuration: { id?: string | null; name?: string | null; revision?: number | null; constraints: SafetyDefinition[] };
  source: { datasetName: string; time: TimeAxis; signals: Signal[] };
  observed: SafetyObservation[]; forecast: SafetyForecast | null; forecastOptions?: ForecastOptions | null;
};
export type SafetyEvidence = { constraintId: string; kind: "observed" | "predicted"; intervalIndex: number; raw?: boolean };
