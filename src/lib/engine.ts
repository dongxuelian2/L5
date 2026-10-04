import rawScenario from "../data/scenario.json";
import type {
  Alarm,
  IncidentBrief,
  Point,
  Scenario,
  SignalKey,
} from "../types";

export const scenario = rawScenario as unknown as Scenario;
export const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
export const wallClock = (seconds: number) =>
  `14:${String(20 + Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
export const alarmsAt = (time: number): Alarm[] =>
  scenario.alarms.filter((event) => event.t <= time);
export const pointAt = (time: number): Point =>
  scenario.points[Math.min(scenario.duration, Math.max(0, Math.floor(time)))];
export const detectedAt = (key: SignalKey, time: number) =>
  time >= scenario.detections[key].time;
export const formatValue = (key: SignalKey, point: Point) =>
  point[key].toFixed(scenario.tags.find((tag) => tag.key === key)!.precision);

/** The model boundary is a single JSON response, independent of the UI. */
export interface AnalystProvider {
  analyze(prompt: string, signal?: AbortSignal): Promise<IncidentBrief>;
}

export function validateBrief(value: unknown): IncidentBrief {
  if (!value || typeof value !== "object")
    throw new Error("The analyst returned an empty response.");
  const brief = value as IncidentBrief;
  if (
    brief.schemaVersion !== 1 ||
    brief.incidentId !== scenario.id ||
    !["local", "model"].includes(brief.provider) ||
    typeof brief.prompt !== "string" ||
    typeof brief.summary !== "string" ||
    typeof brief.limitation !== "string" ||
    !scenario.candidates.some((c) => c.id === brief.candidateId) ||
    !Array.isArray(brief.evidenceTags) ||
    !brief.evidenceTags.every((k) =>
      scenario.tags.some((tag) => tag.key === k),
    ) ||
    !Array.isArray(brief.steps) ||
    !brief.steps.length ||
    !brief.steps.every(
      (s) =>
        s &&
        typeof s.action === "string" &&
        typeof s.tool === "string" &&
        typeof s.result === "string",
    )
  ) {
    throw new Error(
      "The analyst response does not match the incident brief schema.",
    );
  }
  return brief;
}

export const localAnalyst: AnalystProvider = {
  async analyze(prompt, signal) {
    signal?.throwIfAborted();
    return validateBrief({
      schemaVersion: 1,
      incidentId: scenario.id,
      provider: "local",
      prompt,
      steps: scenario.analyst.steps,
      summary: scenario.analyst.summary,
      limitation: scenario.analyst.limitation,
      candidateId: "valve",
      evidenceTags: ["valve", "flow", "temperature", "pressure"],
    });
  },
};

export const modelAnalyst: AnalystProvider = {
  async analyze(prompt, signal) {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ incidentId: scenario.id, prompt }),
      signal,
    });
    if (!response.ok)
      throw new Error(
        `Analyst unavailable (${response.status}). Please retry.`,
      );
    return validateBrief(await response.json());
  },
};

export const analyst =
  import.meta.env.VITE_ANALYST_PROVIDER === "http"
    ? modelAnalyst
    : localAnalyst;

export function downloadFile(
  name: string,
  data: string,
  type = "application/json",
) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function briefMarkdown(brief: IncidentBrief): string {
  return (
    `# TripLens · ${scenario.id}\n\n## ${scenario.title}\n\n${brief.summary}\n\n` +
    brief.steps
      .map((step) => `### ${step.action}\n\n${step.result}\n`)
      .join("\n") +
    `\n## Evidence boundary\n\n${brief.limitation}\n\nSource: ${scenario.provenance.model}. Analyst: ${brief.provider}.\n`
  );
}
