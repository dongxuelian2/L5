import type { DatasetClock, IncidentAxis, Contribution } from "./types";

export type AlarmSignal = { datasetId: string; signal: string };
export type AlarmMapping = AlarmSignal & { equipment?: string; priority?: string };
export type SignalRelationship = { left: AlarmSignal; right: AlarmSignal };
export type AlarmPolicy = {
  priorities: { id: string; label: string }[];
  defaultPriority: string;
  mappings: AlarmMapping[];
  relationships: SignalRelationship[];
  proximitySeconds: number;
  repeatWindowSeconds: number;
  groupByEquipment: boolean;
  minSamples: number;
  minDurationSeconds: number;
  maxShelveSeconds: number;
  escalationSeconds: number | null;
  floodWindowSeconds: number;
};
export const defaultAlarmPolicy: AlarmPolicy = {
  priorities: [
    { id: "high", label: "High" }, { id: "medium", label: "Medium" },
    { id: "low", label: "Low" }, { id: "unclassified", label: "Unclassified" },
  ],
  defaultPriority: "unclassified", mappings: [], relationships: [],
  proximitySeconds: 0, repeatWindowSeconds: 0, groupByEquipment: false,
  minSamples: 1, minDurationSeconds: 0, maxShelveSeconds: 86400,
  escalationSeconds: null, floodWindowSeconds: 60,
};

export type AlarmAudit = {
  id: string; kind: string; actor: string; recordedAt: string;
  eventId?: string; groupId?: string; note?: string; expiresAt?: string; incidentId?: string;
};
export type AlarmAction = { kind: "acknowledge" | "shelve" | "unshelve" | "note"; actor?: string; note?: string; expiresAt?: string };
export type AlarmEvent = {
  id: string; datasetId: string; datasetName: string; analysisId: string; analysisName: string;
  detector: string; detectorLabel: string; axisId: string; offset: number; intervalIndex: number;
  start: number; end: number; peakTime: number; nativeStart: number; nativeEnd: number; nativePeakTime: number;
  startIndex: number; endIndex: number; peakIndex: number;
  signals: string[]; affectedSignals: string[]; contributions: Contribution[]; samples: number; peakScore: number; threshold: number;
  peakAboveThreshold: number; peakMagnitude: number | null; clearTime?: number | null; nativeContributionTime?: number;
  measuredState: "active" | "cleared" | "unknown"; endReason: string;
  observedSpan: [number, number]; observedFraction: number | null;
  quality: { gapThreshold: number | null; coverageFraction: number | null; abstainedSamples: number | null };
  provenance: { contributionMetric?: string; experiment?: unknown; transformation?: unknown };
  durationSeconds: number; priority: string; equipment: string[]; policyEligible: boolean;
  operator: { acknowledgedAt: string | null; shelvedUntil: string | null; incidentIds: string[]; escalated: boolean };
};
export type AlarmRelationship = {
  leftId: string; rightId: string; temporal: "overlap" | "proximity"; gapSeconds: number;
  reasons: string[]; signals: AlarmSignal[]; equipment: string[]; explicitPairs?: SignalRelationship[];
};
export type AlarmGroup = {
  id: string; axisId: string; start: number; end: number; eventIds: string[];
  relationships: AlarmRelationship[]; priority: string;
};
export type AlarmBin = { start: number; end: number; arrivals: number; groupArrivals: number; peakConcurrent: number; arrivalsPerHour: number; windowCount: number };
export type AlarmFloodAxis = {
  axisId: string; windowSeconds: number; anchor: number; start: number; end: number; bins: AlarmBin[];
  peakArrivalCount: number; peakArrivalsPerHour: number; peakConcurrent: number; repeatedEventCount: number;
  byEquipment: { equipment: string | null; count: number }[];
  bySignal: (AlarmSignal & { count: number })[];
  totalDurationSeconds: number; meanDurationSeconds: number | null;
  acknowledgedCount: number; meanAcknowledgementDelaySeconds: number | null;
};
export type AlarmSessionSummary = {
  id: string; name: string; createdAt: string; updatedAt: string; eventCount?: number; groupCount?: number;
};
export type AlarmSessionSource = {
  analysisId: string; analysisName: string; datasetId: string; datasetName: string;
  detector: string; detectorLabel: string; clock: DatasetClock; start: number; end: number;
  coverageFraction: number | null; abstainedSamples: number | null;
};
export type AlarmSession = AlarmSessionSummary & {
  workspaceId: string; analysisIds: string[]; policy: AlarmPolicy; events: AlarmEvent[]; groups: AlarmGroup[];
  axes: IncidentAxis[]; sources?: AlarmSessionSource[]; flood: { rawEventCount: number; groupCount: number; axes: AlarmFloodAxis[] };
  audit: AlarmAudit[]; asOf: string;
};
