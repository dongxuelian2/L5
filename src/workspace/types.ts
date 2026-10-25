import type { TransformationLineage } from "./transformationTypes";
export type Workspace = { id: string; name: string; created_at: string; updated_at: string; dataset_count?: number; analysis_count?: number };
export type TimeAxis = { kind: "numeric" | "datetime" | "generated" | "unix"; column: string | null; origin: string | null; start: number; end: number; sampleInterval?: number; sourceUnit?: string; naiveTimezone?: string; typicalInterval?: number | null; gapCount?: number; duplicateCount?: number; invalidTimeCount?: number; irregularCount?: number };
export type Signal = { name: string; missing: number; min: number | null; max: number | null; id?: string; displayName?: string; unit?: string; description?: string; category?: string; device?: string; tags?: string[]; logicalKey?: string };
export type TimeReference = { mode: "independent" | "reference" | "utc" | "native"; offsetSeconds?: number; referenceDatasetId?: string; utcOrigin?: string };
export type DatasetClock = { key: string; axisId: string; offset: number; label: string; reference: TimeReference };
export type QualitySpan = { start: number; end: number; count: number };
export type SignalQuality = { totalCount: number; validCount: number; finiteCount: number; missing: number; missingFraction: number; invalidTimeMeasurements: number; min: number | null; max: number | null; mean: number | null; std: number | null; missingSpans: QualitySpan[]; availableSpans: QualitySpan[] };
export type DataQuality = { totalCount: number; timedCount: number; invalidTimeCount: number; invalidTimes: { row: number; raw: string; nearbyTime?: number }[]; start: number; end: number; typicalInterval: number | null; gapThreshold: number | null; gaps: { start: number; end: number; duration: number }[]; gapCount: number; irregularCount: number; irregular: boolean; duplicateCount: number; duplicates: { time: number; count: number }[]; signals: Record<string, SignalQuality> };
export type CatalogSignal = Signal & { id: string; datasetId: string; workspaceId: string; datasetName: string; source: string; simulationId?: string; time: TimeAxis; clock: DatasetClock; quality: SignalQuality };
export type ExplorerWindow = { start: number; end: number; at: number };
export type ExplorerView = { id: string; workspaceId: string; name: string; signalIds: string[]; windows: Record<string, ExplorerWindow>; displayMode: "separate" | "overlay"; updatedAt: string };
export type ExplorerAxis = { id: string; label: string; origin: string | null; start: number; end: number; window: ExplorerWindow };
export type ExplorerSeries = { signal: CatalogSignal; times: number[]; nativeTimes: number[]; values: (number | null)[]; segmentIds: number[]; sourceRows: number; displayRows: number };
export type ExplorerData = { axes: ExplorerAxis[]; series: ExplorerSeries[] };
export type ExplorerSample = { signalId: string; status: "measured" | "processed" | "gap" | "outside" | "missing"; value: number | null; time: number; nativeTime: number; sourceIndex: number; deltaSeconds: number; duplicateCount: number; provenance?: string; observed?: boolean };
export type Ranges = { baselineRange: [number, number]; analysisRange: [number, number] };
export type Metadata = { rowCount: number; columns: Signal[]; sourceColumns: string[]; ignoredColumns: string[]; missingCount: number; time: TimeAxis; notes: string[]; suggestedRanges?: Ranges; filename?: string; model?: { id: string; simulationId: string; capabilities: string[]; version?: string; name?: string; scenarioId?: string | null; scenarioVersion?: number | null; config?: Record<string, unknown>; groundTruth?: unknown }; quality?: DataQuality; clock?: DatasetClock; transformation?: TransformationLineage };
export type Dataset = { id: string; workspace_id: string; name: string; metadata: Metadata; created_at: string };
export type Series = { times: number[]; values: Record<string, (number | null)[]>; segmentIds?: Record<string, number[]>; sourceRows: number; displayRows: number };
export type Config = Ranges & { datasetId: string; signals: string[]; algorithm: string; alpha: number; variance: number; name?: string; smoothing?: number; reference?: number; window?: number; lags?: number; rate?: number; guard?: number; maxShift?: number; fitFraction?: number; minCoverage?: number; persistence?: number; requiredSignals?: string[]; observationPolicy?: "measured" | "processed"; stress?: { missingFraction?: number; noise?: number; offset?: number; seed?: number; missingSignals?: string[] } };
export type Contribution = { signal: string; value: number };
export type ExperimentSource = { experimentId: string; runId: string; taskId: string };
export type ContributionMetric = "absolute-robust-z" | "squared-residual" | "model-leverage" | "history-contribution";
export type Interval = { start: number; end: number; samples: number; peakScore: number; peakTime: number; signals: string[]; contributions?: Contribution[] };
export type Summary = { analysisSamples: number; baselineSamples: number; fitSamples: number; calibrationSamples: number; flaggedSamples: number; peakScore: number; firstDetection: number | null; imputedValues: { baseline: number; analysis: number }; abstainedSamples?: number; coverageFraction?: number };
export type AnalysisResult = { experiment?: ExperimentSource; id: string; workspaceId: string; datasetId: string; name: string; createdAt: string; completedAt: string; durationMs: number; config: Config; algorithmLabel: string; times: number[]; scores: number[]; threshold: number; intervals: Interval[]; relatedSignals: string[]; summary: Summary; model: Record<string, unknown>; signalContributions?: Contribution[]; peakTime?: number; contributionMetric?: ContributionMetric; states?: ("normal" | "alarm" | "abstain")[]; observedFraction?: number[] };
export type Job = { id: string; workspace_id: string; dataset_id: string; name: string; config: Config; summary: Summary; created_at: string };

export type IncidentStatus = "open" | "investigating" | "resolved" | "archived";
export type IncidentSummary = { id: string; workspace_id: string; title: string; description: string; start_time: number | null; end_time: number | null; time_origin: string | null; time_axis_key?: string | null; status: IncidentStatus; conclusion: string; created_at: string; updated_at: string; analysis_count?: number; interval_count?: number };
export type IncidentSource = { kind: "dataset" | "analysis" | "interval" | "simulation" | "run"; datasetId?: string; analysisId?: string; intervalIndex?: number; simulationId?: string; runId?: string; hypothesis?: string; asOf?: number; windowStart?: number };
export type RuntimeRun = { modelId?: string; modelVersion?: string; scenarioId?: string | null; scenarioVersion?: number | null; id: string; kind: string; request: Record<string, unknown>; result: unknown; createdAt: string };
export type IncidentLink = { id: string; incident_id: string; kind: IncidentSource["kind"]; reference_id: string; selector: string; created_at: string; details: { experiment?: ExperimentSource; title: string; datasetId?: string; analysisId?: string; algorithmLabel?: string; analysisRange?: [number, number]; signals?: string[]; contributionMetric?: ContributionMetric; intervalIndex?: number; interval?: Interval; simulationId?: string; modelId?: string; modelVersion?: string; modelName?: string; scenarioId?: string | null; scenarioVersion?: number | null; run?: RuntimeRun; observationWindow?: { asOf: number; windowStart: number; hypothesis?: string } } };
export type IncidentEntry = { id: string; incident_id: string; kind: "note" | "evidence" | "hypothesis"; title: string; content: string; hypothesis_id: string | null; stance: "neutral" | "support" | "oppose"; source_link_id: string | null; observed_at: number | null; observed_axis_key?: string | null; created_at: string; updated_at: string };
export type Incident = IncidentSummary & { links: IncidentLink[]; entries: IncidentEntry[] };

export type IncidentAxis = { id: string; label: string; origin: string | null; start: number; end: number };
export type TimelineEvent = { id: string; kind: string; title: string; axisId: string | null; start: number | null; end: number | null; peakTime?: number; peakScore?: number; analysisId?: string; intervalIndex?: number; linkId?: string | null; entryId?: string; recordedAt?: string; updatedAt?: string; content?: string; signals?: string[]; stance?: string; observationWindow?: [number, number]; actionAt?: number; changes?: Record<string, { before: unknown; after: unknown }>; target: string };
export type LinkedInterval = Interval & { index: number; linkId: string };
export type IncidentAnalysis = { id: string; result: AnalysisResult; datasetId: string; datasetName: string; axisId: string; offset: number; scope: string; linkId: string; intervals: LinkedInterval[]; observedSpans: [number, number][] };
export type ComparisonSegment = { start: number; end: number; kind: "common" | "unique" | "partial" | "uncompared"; analysisIds: string[] };
export type IncidentComparisonGroup = { axisId: string; analysisIds: string[]; segments: ComparisonSegment[]; common: ComparisonSegment[]; unique: ComparisonSegment[]; firstDetection: number | null; firstAlarmSpread: number | null };
export type IncidentView = { incident: Incident; workspace: Workspace; generatedAt: string; axes: IncidentAxis[]; primaryAxisId: string; events: TimelineEvent[]; analyses: IncidentAnalysis[]; comparisons: IncidentComparisonGroup[]; datasets: Dataset[] };
export type IncidentSelection = { axisId: string; start: number; end: number; at: number; eventId?: string; analysisId?: string; intervalIndex?: number; linkId?: string };
export function incidentAxis(axis: IncidentAxis): TimeAxis { return { ...axis, kind: axis.origin ? "datetime" : "numeric", column: null }; }
export function datasetClock(dataset: Dataset) {
  if (dataset.metadata.clock) return dataset.metadata.clock;
  const origin = dataset.metadata.time.origin;
  return { axisId: origin ? "utc" : dataset.metadata.model ? `simulation:${dataset.metadata.model.simulationId}` : `dataset:${dataset.id}`, offset: origin ? new Date(origin).getTime() / 1000 : 0 };
}

export function signalLabel(signal: Signal) { return `${signal.displayName || signal.name}${signal.unit ? ` (${signal.unit})` : ""}`; }
export function namedSignal(dataset: Dataset, name: string) { const signal = dataset.metadata.columns.find(c => c.name === name); return signal ? signalLabel(signal) : name; }
export function datasetTimeLabel(dataset: Dataset, value: number) {
  const clock = datasetClock(dataset);
  return clock.axisId === "utc" ? timeLabel({ ...dataset.metadata.time, origin: "1970-01-01T00:00:00Z" }, value+clock.offset) : timeLabel(dataset.metadata.time, value);
}

export function number(value: number) {
  return value === 0 ? "0" : Math.abs(value) >= 10000 || Math.abs(value) < .001 ? value.toExponential(2) : Number(value.toPrecision(5)).toLocaleString();
}
export function timeLabel(axis: TimeAxis, value: number) {
  if (axis.origin) return new Date(new Date(axis.origin).getTime() + value * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");
  return `${number(value)} s`;
}
export function dateLabel(value: string) { return new Date(value).toLocaleString(); }
