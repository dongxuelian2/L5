export type Pair = [number, number];
export type Box = [Pair, Pair];
export type PlantKey = "area1" | "area2" | "connection" | "outlet" | "pumpRate" | "outletValve" | "tankHeight";
export type Config = {
  modelId: string; plant: Record<PlantKey, number>; safe: Box; target: Box; pump: Pair; valve: Pair;
  slew: Pair; actionCounts: Pair; grid: Pair; horizon: number; controlSeconds: number; integrationStep: number;
  mode: "nominal" | "robust"; disturbances: string[];
};
export type Analysis = {
  config: Config; modelVersion: string;
  numerical: { axes: [number[], number[]]; spacing: Pair; actions: Pair[]; scenarios: Record<string, object>;
    horizonSeconds: number; viabilityIterations: number; nominalViabilityIterations: number; convergence: boolean;
    seconds: number; graphBytes: number; safeAugmentedStates: number; boundaryAugmentedStates: number };
  ranks: number[][]; nominalRanks: number[][]; viableTargetRanks: number[][]; policy: number[][];
  safe: boolean[]; target: boolean[]; viable: boolean[][]; nominalViable: boolean[][]; boundary: boolean[][];
};
export type Strategy = "policy" | "hold" | "drain" | "fill";
export type Initial = { heads: Pair; previousAction: number; disturbance: string };
export type Point = { t: number; level1: number; level2: number; safetyMargin: number; pump: number; valve: number };
export type Replay = { strategy: Strategy; status: string; recoverySeconds: number | null; minimumMargin: number;
  effort: Pair; movement: Pair; violations: { t: number; margin: number }[]; trajectory: Point[];
  actions: { t: number; pump: number; valve: number; disturbance: string }[] };
export type Evaluation = { initial: Initial; replays: Record<Strategy, Replay>; integrationStep: number };
export type Scenario = { id: string; name: string; version: number; config: Record<PlantKey, number> };
export type Incident = { id: string; title: string };
export type Study = { id?: string; name?: string; analysis: Analysis; evaluation: Evaluation | null; scenario: Scenario | null; incident: Incident | null };
export type Index = { studies: { id: string; name: string }[]; defaults: Config;
  disturbances: Record<string, Record<string, number>>; scenarios: Scenario[]; incidents: Incident[] };
