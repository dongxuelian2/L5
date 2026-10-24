import type { DatasetClock, Metadata, Series } from "./types";

export type MissingPolicy = { method: "keep" | "linear" | "previous" | "fixed" | "statistic"; value?: number; statistic?: "mean" | "median" | "min" | "max"; computedValue?: number | null };
export type TransformSource = { signalId: string; key: string; displayName: string; unit: string; sourceUnit?: string; datasetId?: string; column?: string; clock?: DatasetClock; resampling: "nearest" | "linear" | "previous" | "mean" | "min" | "max"; maxGapSeconds: number; duplicatePolicy: "first" | "last" | "mean" | "error"; missing: MissingPolicy; rotational?: boolean };
export type DerivedSignal = { key: string; displayName: string; expression: string; unit: string; description?: string };
export type TransformationConfig = { version: 1; sources: TransformSource[]; derived: DerivedSignal[]; grid: { mode: "intersection" | "union" | "custom"; intervalSeconds: number; start?: number; end?: number; axisId?: string } };
export type Transformation = { id: string; workspace_id: string; name: string; config: TransformationConfig; revision: number; created_at: string; updated_at: string };
export type TransformCounts = { samples: number; validCount: number; missingCount: number; missingFraction: number; min: number | null; max: number | null };
export type TransformQuality = { key: string; before: TransformCounts; after: TransformCounts; provenance: Record<string, number>; observedCount: number; duplicatesResolved?: number; missingPolicy?: MissingPolicy; outputUnit?: string };
export type TransformationLineage = { definitionId?: string; definitionName?: string; revision?: number; executionId?: string; createdAt?: string; config: TransformationConfig; sources: { datasetId: string; datasetName: string; sha256: string; simulationId: string | null; sourceSimulations: string[] }[]; sourceSimulations: string[]; grid: { start: number; end: number; requestedEnd: number; intervalSeconds: number; samples: number }; quality: TransformQuality[] };
export type TransformPreview = { metadata: Metadata; series: Series; samples: { time: number; values: Record<string, number | null>; provenance: Record<string, string>; observed: Record<string, boolean> }[] };
export type EngineeringUnit = { name: string; dimension: string; requiresRotationalMeaning: boolean };
