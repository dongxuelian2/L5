export type Workspace = { id: string; name: string; created_at: string; updated_at: string; dataset_count?: number; analysis_count?: number };
export type TimeAxis = { kind: "numeric" | "datetime" | "generated"; column: string | null; origin: string | null; start: number; end: number; sampleInterval?: number; sourceUnit?: string };
export type Signal = { name: string; missing: number; min: number; max: number };
export type Ranges = { baselineRange: [number, number]; analysisRange: [number, number] };
export type Metadata = { rowCount: number; columns: Signal[]; sourceColumns: string[]; ignoredColumns: string[]; missingCount: number; time: TimeAxis; notes: string[]; suggestedRanges?: Ranges; filename?: string; model?: { id: string; simulationId: string; capabilities: string[] } };
export type Dataset = { id: string; workspace_id: string; name: string; metadata: Metadata; created_at: string };
export type Series = { times: number[]; values: Record<string, (number | null)[]>; sourceRows: number; displayRows: number };
export type Config = Ranges & { datasetId: string; signals: string[]; algorithm: string; alpha: number; variance: number; name?: string; smoothing?: number; reference?: number; window?: number; lags?: number; rate?: number; guard?: number; maxShift?: number; fitFraction?: number; minCoverage?: number; persistence?: number; requiredSignals?: string[]; stress?: { missingFraction?: number; noise?: number; offset?: number; seed?: number; missingSignals?: string[] } };
export type Contribution = { signal: string; value: number };
export type ContributionMetric = "absolute-robust-z" | "squared-residual" | "model-leverage" | "history-contribution";
export type Interval = { start: number; end: number; samples: number; peakScore: number; peakTime: number; signals: string[]; contributions?: Contribution[] };
export type Summary = { analysisSamples: number; baselineSamples: number; fitSamples: number; calibrationSamples: number; flaggedSamples: number; peakScore: number; firstDetection: number | null; imputedValues: { baseline: number; analysis: number }; abstainedSamples?: number; coverageFraction?: number };
export type AnalysisResult = { id: string; workspaceId: string; datasetId: string; name: string; createdAt: string; completedAt: string; durationMs: number; config: Config; algorithmLabel: string; times: number[]; scores: number[]; threshold: number; intervals: Interval[]; relatedSignals: string[]; summary: Summary; model: Record<string, unknown>; signalContributions?: Contribution[]; peakTime?: number; contributionMetric?: ContributionMetric; states?: ("normal" | "alarm" | "abstain")[]; observedFraction?: number[] };
export type Job = { id: string; workspace_id: string; dataset_id: string; name: string; config: Config; summary: Summary; created_at: string };

export function number(value: number) {
  return value === 0 ? "0" : Math.abs(value) >= 10000 || Math.abs(value) < .001 ? value.toExponential(2) : Number(value.toPrecision(5)).toLocaleString();
}
export function timeLabel(axis: TimeAxis, value: number) {
  if (axis.origin) return new Date(new Date(axis.origin).getTime() + value * 1000).toISOString().replace("T", " ").replace(".000Z", " UTC");
  return `${number(value)} s`;
}
export function dateLabel(value: string) { return new Date(value).toLocaleString(); }
