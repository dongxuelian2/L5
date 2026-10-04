import raw from "../data/platform.json";
import { downloadFile } from "./engine";

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
  clock: { regular: boolean; gaps: number };
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
export type Trial = {
  time: number;
  peak: number;
  safe: boolean;
  productionLoss: number;
  qualityLoss: number;
  utilityCost: number;
};
export type Action = {
  id: string;
  name: string;
  severity: number;
  cost: number;
  latest: number | null;
  intervals: number[][];
  selectedTime: number;
  margin: number;
  peak: number;
  trip: number | null;
  pressure: number[];
  productionLoss: number;
  qualityLoss: number;
  utilityCost: number;
  trials: Trial[];
};
export type Recovery = {
  threshold: number;
  resolution: number;
  horizon: number;
  evaluated: number;
  base: { pressure: number[]; peak: number; trip: number | null };
  actions: Action[];
  safest: string | null;
  lowestLoss: string | null;
  latest: string | null;
};
export type Incident = Analysis & {
  id: string;
  title: string;
  rows: Row[];
  snapshots: (Analysis & { time: number })[];
  fit: { hypothesis: string; parameters: unknown; error: number };
  recovery: Recovery;
  similar: {
    id: string;
    similarity: number;
    shared: string[];
    leading: string;
  }[];
};
export type Platform = {
  schemaVersion: number;
  model: string;
  signals: {
    key: string;
    tag: string;
    unit: string;
    nominal: number;
    scale: number;
  }[];
  edges: { source: string; target: string; kind: string }[];
  faults: Record<string, string>;
  cases: Incident[];
  benchmark: {
    source: string;
    scenarioCount: number;
    faultCoverage: number;
    top1: number;
    top3: number;
    medianDelay: number;
    healthyRuns: number;
    falsePositiveRuns: number;
    records: {
      fault: string;
      variant: number;
      top1: boolean;
      top3: boolean;
      predicted: string;
      delay: number | null;
    }[];
    limitation: string;
  };
  limitations: string[];
};
export const platform = raw as unknown as Platform;
export const signalMeta = Object.fromEntries(
  platform.signals.map((s) => [s.key, s]),
);
export const num = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : n.toFixed(digits);
export function exportDossier(
  incident: Incident,
  analysis: Analysis,
  time: number,
  format: "md" | "json",
  notes: string[],
) {
  const payload = {
    schemaVersion: 2,
    incidentId: incident.id,
    asOf: time,
    model: platform.model,
    analysis,
    counterfactual:
      time === 240 ? { fit: incident.fit, recovery: incident.recovery } : null,
    similar: time === 240 ? incident.similar : [],
    notes,
    limitations: platform.limitations,
  };
  if (format === "json")
    return downloadFile(
      `${incident.id}-dossier.json`,
      JSON.stringify(payload, null, 2),
      "application/json",
    );
  const d = analysis.diagnosis,
    a = analysis.alarms;
  const text = [
    `# TripLens · ${incident.id}`,
    `As of +${time}s · ${platform.model}`,
    "## Executive summary",
    `${d.status}. Leading hypothesis: ${d.candidates[0].name}, evidence score ${d.candidates[0].score}/100 (not a probability).`,
    "## Timeline",
    `First detection: ${d.firstDetection ?? "none"} s. First alarm: ${a.firstAlarm ?? "none"} s.`,
    "## Plant & controllers",
    ...d.controllers.map(
      (c) =>
        `${c.id}: SP ${num(c.sp)} / PV ${num(c.pv)} / OP ${num(c.op)} / feedback ${num(c.feedback)} / limit ${num(c.limit)}`,
    ),
    "## Alarm flood",
    `${a.eventCount} events, ${a.uniqueConditions} unique conditions, ${a.reannunciations} reannunciations, ${a.clusters.length} clusters.`,
    ...a.floods.map((f) => `Flood +${f.start}…${f.end}s (≥10 events / 30s).`),
    "## Hypotheses",
    ...d.candidates
      .slice(0, 4)
      .flatMap((c) => [
        `### ${c.name} · ${c.score}/100`,
        ...c.support.map((s) => `- Supports: ${s}`),
        ...c.against.map((s) => `- Against: ${s}`),
        ...c.unresolved.map((s) => `- Unresolved: ${s}`),
      ]),
    "## Propagation",
    ...d.paths.map(
      (p) =>
        `- ${p.source} → ${p.target}: ${p.kind}, lag ${p.lag}s, r=${p.correlation}, trusted=${p.trusted}.`,
    ),
    "## Counterfactual verification",
    ...(time === 240
      ? [
          `Conditioned on fitted ${incident.fit.hypothesis}; normalized RMSE ${incident.fit.error}. Exhaustive 1s grid, horizon 240s.`,
          ...incident.recovery.actions.map(
            (r) =>
              `- ${r.name}: latest safe start ${r.latest == null ? "none" : `${r.latest}s`}; peak ${r.peak} kPa, production loss ${r.productionLoss}%, quality loss ${r.qualityLoss} percentage points.`,
          ),
        ]
      : ["Unavailable at this partial snapshot; no future evidence included."]),
    "## Procedure alignment",
    `${analysis.sop.id}: ${analysis.sop.applicable ? "preconditions satisfied" : "preconditions not satisfied"}. ${analysis.sop.status}.`,
    ...analysis.sop.preconditions.map(
      (p) => `- ${p.satisfied ? "[x]" : "[ ]"} ${p.name}`,
    ),
    "## Next measurements",
    ...d.nextMeasurements.map(
      (m) =>
        `- ${m.tag}: ${m.reason}. Distinguishes ${m.distinguishes.join(" / ")}.`,
    ),
    "## Evidence health",
    ...Object.entries(d.health).map(
      ([key, h]) => `- ${signalMeta[key].tag}: ${h.status}. ${h.detail}`,
    ),
    "## Similar sessions",
    ...(time === 240
      ? incident.similar.map(
          (s) =>
            `- ${s.id}: ${s.similarity}/100 fingerprint similarity; shared ${s.shared.join(", ")}.`,
        )
      : ["Not retrieved at partial snapshot."]),
    "## Operator notes",
    ...notes.map((n) => `- ${n}`),
    "## Alarm rationalization",
    ...a.rationalization.map((r) => `- ${r.condition}: ${r.recommendation}`),
    "## Tool audit",
    ...analysis.trace.map(
      (t) => `- ${t.index}. ${t.tool}(${JSON.stringify(t.args)})`,
    ),
    "## Limitations",
    ...platform.limitations.map((l) => `- ${l}`),
  ];
  downloadFile(`${incident.id}-dossier.md`, text.join("\n\n"), "text/markdown");
}
export function csvFor(incident: Incident) {
  const keys = ["t", ...platform.signals.map((s) => s.key)];
  return (
    keys.join(",") +
    "\n" +
    incident.rows.map((r) => keys.map((k) => r[k] ?? "").join(",")).join("\n")
  );
}
export type SavedIncident = {
  id: string;
  hypothesis: string;
  score: number;
  events: number;
  savedAt: string;
  note: string;
  fingerprint: Record<string, number>;
};
export function readMemory(): SavedIncident[] {
  try {
    const data: unknown = JSON.parse(
      localStorage.getItem("triplens-memory-v2") || "[]",
    );
    return Array.isArray(data)
      ? data.filter(
          (v) =>
            v &&
            typeof v.id === "string" &&
            platform.cases.some((c) => c.id === v.id) &&
            typeof v.hypothesis === "string" &&
            typeof v.score === "number" &&
            typeof v.events === "number" &&
            typeof v.savedAt === "string" &&
            typeof v.note === "string" &&
            v.fingerprint &&
            typeof v.fingerprint === "object",
        )
      : [];
  } catch {
    return [];
  }
}
