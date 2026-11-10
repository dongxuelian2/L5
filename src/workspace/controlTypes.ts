import type { ModelConfig, Scenario } from "./modelTypes";

export type ControllerKind = "open-loop" | "pi" | "mpc";
export type ControllerSettings = { kind: ControllerKind; [key: string]: number | boolean | string | Record<string, unknown> };
export type ControlProtocol = {
  sampleInterval: number; reference: { time: number; level: number }[];
  constraints: Record<string, number | null>; controllers: ControllerSettings[];
  disturbances: { start: number; end: number; inletFactor: number; outletFactor: number }[];
  settlingBand: number; settlingDwell: number;
};
export type ControlDecision = { time: number; measurement: Record<string, number>; command: { pump: number; valve: number }; reference: number; durationMs: number;
  solver: { status: string; fallback?: boolean; iterations?: number; primalResidual?: number; stationarityResidual?: number; predictedSlack?: number[]; prediction?: number[][]; targets?: number[]; plan?: number[][]; integral?: number } };
export type ControlBranch = { controller: ControllerKind; settings: ControllerSettings; rows: Record<string, number>[]; physical: Record<string, number>[];
  decisions: ControlDecision[]; metrics: Record<string, number | null | {time:number;through:number;settlingSeconds:number|null}[]> };
export type ControlSummary = { id: string; name: string; workspaceId: string; createdAt: string };
export type ControlExperiment = ControlSummary & { format: string; modelId: string; modelVersion: string; config: ModelConfig; scenarioSnapshot: Scenario | null;
  protocol: ControlProtocol; results: ControlBranch[]; datasets: Record<string, string>; metricDefinitions: {key:string;label:string;unit:string}[];
  noiseFingerprint: string; solver: Record<string,string|number>; informationPolicy: string };

export const piDefaults: ControllerSettings = { kind:"pi", kp:180, ki:2, actuateValve:false, valveKp:.5, valveBias:1 };
export const mpcDefaults: ControllerSettings = { kind:"mpc", predictionHorizon:25, controlHorizon:8, trackingWeight:10, moveWeight:.08, effortWeight:.002, levelWeight:1000, maxIterations:1200, tolerance:.00001, preview:true, actuateValve:false };
export const defaultProtocol = (): ControlProtocol => ({ sampleInterval:2, reference:[{time:0,level:1},{time:60,level:1.2}],
  constraints:{pumpMin:0,pumpMax:150,pumpRate:10,valveMin:.01,valveMax:1,valveRate:.1,levelMin1:0,levelMax1:2.3,levelMin2:0,levelMax2:2.3},
  controllers:[{kind:"open-loop"},{...piDefaults},{...mpcDefaults}],disturbances:[],settlingBand:.02,settlingDwell:20 });
export const controllerName = (kind: ControllerKind) => ({"open-loop":"Open loop",pi:"PI control",mpc:"Model predictive control"})[kind];
