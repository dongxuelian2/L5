import { useEffect, useState, type FormEvent } from "react";
import { downloadFile } from "../../lib/download";
import { api, go, message } from "../api";
import { Plot } from "../Charts";
import { number, type Series, type Signal, type TimeAxis } from "../types";

type Settings = Record<"durationSeconds" | "onsetSeconds" | "interventionSeconds" | "seed", number> & { gain?: number };
type Scenario = { id: string; title: string; mechanism: string; comparison: string; settings: Settings };
type Plant = {
  id: string; name: string; equipment: string[]; connection: string; mode: string; version: string;
  sampleSeconds: number; signals: Signal[]; scenarios: Scenario[]; limits: Record<string, unknown>;
};
type Report = {
  title: string; diagnosis: { hypothesis: string; start: number; cutoff: number } | null;
  threshold: number; signals: string[]; signatureDistances: Record<string, number>;
  comparison: Record<string, Record<string, number>>; comparisonColumns: Record<string, string>;
  detection: { normal: { alarmSamples: number; observedSamples: number }; events: { delay: number | null }[] };
};
type Result = {
  signals: string[]; datasets: Record<string, string>; analysisId: string; experimentId: string;
  incidentId: string; report: Report;
};
type Run = {
  id: string; plantId: string; scenarioId: string; title: string; updatedAt: string; modelVersion: string;
  status: string; role?: string; latestSeconds?: number; sampleCount?: number; evaluationId?: string;
  analysisId?: string; experimentId?: string; settings: Settings; signalDefinitions: Signal[]; error?: string; result?: Result;
};

const active = new Set(["configured", "running", "measurements_available", "analysis_available"]);
const stateLabel: Record<string, string> = {
  configured: "Queued", running: "Initializing plant", measurements_available: "Measurements available",
  measurements_ready: "Measurements saved", analysis_available: "Analysis available", completed: "Investigation complete", interrupted: "Interrupted",
  cancelled: "Cancelled", failed: "Run failed",
};
const roleLabel: Record<string, string> = {
  evaluation: "Simulating the selected scenario", fit: "Running the independent normal fit",
  calibration: "Running the independent normal calibration", intervention: "Simulating the matched intervention",
  monitoring: "Scoring the measured channels",
};
const metric = (value: number) => value.toLocaleString("en", { maximumFractionDigits: 4 });
const hypothesis = (value: string) => value.replace(/-reference$/, "").replaceAll("-", " ");

export function PlantWorkspace({ workspaceId, runId, onChanged }: { workspaceId: string; runId?: string; onChanged: () => void }) {
  const path = `/workspaces/${workspaceId}/plants`;
  const route = `workspaces/${workspaceId}/plants`;
  const [plants, setPlants] = useState<Plant[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [plantId, setPlantId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [settings, setSettings] = useState<Settings>();
  const [run, setRun] = useState<Run>();
  const [series, setSeries] = useState<Series>();
  const [intervention, setIntervention] = useState<Series>();
  const [cursor, setCursor] = useState<number>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [pollRevision, setPollRevision] = useState(0);
  const plant = plants.find(item => item.id === plantId) ?? plants[0];
  const scenario = plant?.scenarios.find(item => item.id === scenarioId) ?? plant?.scenarios[0];
  const selectedRun = run?.id === runId ? run : undefined;
  const comparisonDataset = selectedRun?.result?.datasets.intervention;
  const comparisonSignals = selectedRun?.signalDefinitions.slice(0, 2).map(item => item.name).join(",") ?? "";

  useEffect(() => {
    setIntervention(undefined);
    if (!comparisonDataset) return;
    const controller = new AbortController();
    const query = new URLSearchParams(comparisonSignals.split(",").map(signal => ["signal", signal]));
    void api<Series>(`/datasets/${comparisonDataset}/series?${query}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setIntervention(data); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [comparisonDataset, comparisonSignals]);

  useEffect(() => {
    const controller = new AbortController();
    void api<{ plants: Plant[]; runs: Run[] }>(path, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) { setPlants(data.plants); setRuns(data.runs); } })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [path, revision]);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let previousKey = "";
    let wasActive = false;
    setSeries(undefined);
    setCursor(undefined);
    setError("");
    async function poll() {
      try {
        const endpoint = `${path}/runs/${runId}`;
        const saved = await api<Run>(endpoint, undefined, "GET", controller.signal);
        if (controller.signal.aborted) return;
        setRun(saved);
        setPlantId(saved.plantId);
        setScenarioId(saved.scenarioId);
        setSettings(saved.settings);
        const key = `${saved.evaluationId || ""}/${saved.sampleCount || 0}`;
        if (key !== previousKey && (saved.evaluationId || saved.sampleCount || saved.status === "interrupted")) {
          const response = await api<{ series: Series | null }>(`${endpoint}/observations`, undefined, "GET", controller.signal);
          if (controller.signal.aborted) return;
          setSeries(response.series || undefined);
          previousKey = key;
        }
        if (active.has(saved.status)) {
          wasActive = true;
          timer = setTimeout(() => void poll(), 500);
        } else if (wasActive) {
          onChanged();
          setRevision(value => value + 1);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(message(e));
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [path, runId, pollRevision]);

  function select(item: Plant, selected = item.scenarios[0]) {
    setPlantId(item.id);
    setScenarioId(selected.id);
    setSettings(selected.settings);
    setSeries(undefined);
    setCursor(undefined);
    setError("");
    if (runId) go(route);
  }

  async function start(stage = "investigation") {
    setError("");
    setBusy(true);
    try {
      const next = await api<Run>(`${path}/runs`, { scenarioId: scenario.id, settings: settings ?? scenario.settings, stage });
      setRun(next);
      setRuns(items => [next, ...items.filter(item => item.id !== next.id)]);
      if (next.id !== runId) go(`${route}/${next.id}`);
      else setPollRevision(value => value + 1);
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!selectedRun) return;
    setBusy(true);
    try { await api(`${path}/runs/${selectedRun.id}/cancel`, {}); }
    catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  if (!plant || !scenario) return <p role={error ? "alert" : "status"}>{error || "Opening plant workspace…"}</p>;
  const values = settings ?? scenario.settings;
  const isRunning = !!selectedRun && active.has(selectedRun.status);
  const result = selectedRun?.result;
  const report = result?.report;
  const delay = report?.detection.events[0]?.delay;
  const observations = runId ? series : undefined;
  const context = new URLSearchParams((result?.signals || []).map(signal => ["signal", signal]));
  if (report && result) Object.entries({ plantRun: runId!, dataset: result.datasets.evaluation, analysis: result.analysisId,
    experiment: result.experimentId, incident: result.incidentId }).forEach(([key, value]) => context.set(key, value));
  if (report?.diagnosis) {
    context.set("start", String(report.diagnosis.start));
    context.set("end", String(report.diagnosis.cutoff));
  }
  const workspace = `#/workspaces/${workspaceId}`;
  const clock: TimeAxis = { kind: "numeric", column: null, origin: null, start: observations?.times[0] ?? 0, end: observations?.times.at(-1) ?? 0 };
  const sameVersion = !selectedRun || selectedRun.modelVersion === plant.version;
  return <>
    <div className="ws-page-title"><div><h1>{plant.name}</h1><p>{plant.mode}</p></div></div>
    <section className="ws-panel ws-plant" aria-label="Plant operation">
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); void start(); }}>
        <div className="ws-plant-settings">
          <label>Plant<select value={plant.id} onChange={e => select(plants.find(item => item.id === e.target.value)!)}>{plants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Operating scenario<select value={scenario.id} onChange={e => select(plant, plant.scenarios.find(item => item.id === e.target.value)!)}>{plant.scenarios.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          <button className="ws-primary" disabled={busy || isRunning || !sameVersion}>
            {selectedRun?.status === "completed" ? "Run with these settings" : selectedRun?.status === "measurements_ready" ?
              "Complete investigation" : selectedRun && !isRunning ? "Resume investigation" : "Run investigation"}
          </button>
        </div>
        <p>{scenario.mechanism} {scenario.comparison} is the comparison intervention.</p>
        <details><summary>Run settings and plant equipment</summary>
          <div className="ws-plant-settings">
            {([["durationSeconds", "Duration (s)"], ["onsetSeconds", "Disturbance onset (s)"],
              ["interventionSeconds", "Intervention time (s)"], ["seed", "Evaluation seed"],
              ...(values.gain === undefined ? [] : [["gain", "Reactor loop gain multiplier"]])] as [keyof Settings, string][])
              .map(([key, label]) => <label key={key}>{label}<input type="number" required disabled={isRunning || !sameVersion}
                step={key === "gain" ? "any" : key === "seed" ? 1 : plant.sampleSeconds}
                value={values[key] ?? ""} onChange={e => setSettings({ ...values, [key]: e.target.valueAsNumber })} /></label>)}
          </div>
          <p>{plant.connection}</p><p>{plant.equipment.join(" · ")}</p>
          <p>Observation interval {plant.sampleSeconds} s · Model <code>{(selectedRun?.modelVersion || plant.version).slice(0, 12)}</code></p>
          <button type="button" disabled={busy || isRunning || !sameVersion} onClick={() => void start("measurements")}>Run measurements only</button>{" "}
          {plant.id === "tep" && <a className="ws-link" href={`${workspace}/tep`}>Published Tennessee Eastman histories ↗</a>}
        </details>
      </form>
      {error && <p className="ws-error" role="alert">{error}</p>}
      {selectedRun && <div className="ws-plant-status">
        <p role="status"><strong>{stateLabel[selectedRun.status]}</strong>
          {isRunning && selectedRun.role && ` · ${roleLabel[selectedRun.role] ?? "Simulating a diagnosis reference"}`}
          {selectedRun.latestSeconds !== undefined && isRunning && ` · simulated through ${number(selectedRun.latestSeconds)} s`}</p>
        {isRunning && <button onClick={() => void cancel()} disabled={busy}>Cancel run</button>}
        {selectedRun.error && <p className="ws-error" role="alert">{selectedRun.error}</p>}
      </div>}
    </section>
    {report && result && <section className="ws-panel" aria-label="Investigation results">
      <h2>{delay == null ? "No confirmed event alarm" : `Alarm confirmed after ${number(delay)} s`}</h2>
      <p>{report.detection.normal.alarmSamples} alarm samples in {report.detection.normal.observedSamples} normal observations.
        {report.diagnosis && <> Closest trajectory <strong>{hypothesis(report.diagnosis.hypothesis)}</strong> through {number(report.diagnosis.cutoff)} s.</>}</p>
      <div className="ws-inline">
        <a className="ws-primary ws-plant-export" download href={`/api/incidents/${result.incidentId}/report.html?download=1`}>Export investigation report</a>
        <a className="ws-link" href={`${workspace}/incidents/${result.incidentId}?${context}`}>Open incident ↗</a>
        <a className="ws-link" href={`${workspace}/analysis/${result.analysisId}?${context}`}>Detection evidence ↗</a>
        <a className="ws-link" href={`${workspace}/experiments/${result.experimentId}?${context}`}>Experiment ↗</a>
      </div>
      <h3>Matched intervention</h3>
      <div className="ws-table-scroll"><table><thead><tr><th>Metric</th><th>Baseline</th><th>Intervention</th></tr></thead>
        <tbody>{Object.entries(report.comparisonColumns).map(([key, title]) => <tr key={key}>
          <th scope="row">{title}</th><td>{metric(report.comparison.evaluation[key])}</td><td>{metric(report.comparison.intervention[key])}</td>
        </tr>)}</tbody></table></div>
      <details><summary>Diagnostic residuals and exports</summary>
        <ul>{Object.entries(report.signatureDistances).map(([key, value]) => <li key={key}>{hypothesis(key)} · {metric(value)}</li>)}</ul>
        <div className="ws-inline">
          <a className="ws-link" href={`${workspace}/datasets/${result.datasets.intervention}?${context}`}>Intervention measurements ↗</a>
          <button onClick={() => downloadFile(`${selectedRun.scenarioId}-evidence.json`, JSON.stringify(report, null, 2))}>Export evidence JSON</button>
        </div>
      </details>
    </section>}
    {observations && selectedRun && <section className="ws-panel" aria-label="Operating measurements"><h2>Operating measurements</h2>
      {(result?.datasets.evaluation || selectedRun.evaluationId) && <a className="ws-link" href={`${workspace}/datasets/${result?.datasets.evaluation || selectedRun.evaluationId}?${context}`}>Open full measurement record ↗</a>}
      {selectedRun.signalDefinitions.slice(0, 2).map(signal => <Plot key={signal.name}
        title={`${signal.device} · ${signal.displayName} (${signal.unit})`} times={observations.times}
        values={observations.values[signal.name]} axis={clock} selectedTime={cursor} onSelectTime={setCursor}
        overlays={intervention ? [{ times: intervention.times, values: intervention.values[signal.name],
          title: "Matched intervention", color: "#86cce6", dash: "4 4" }] : []}
        markers={[{ time: selectedRun.settings.onsetSeconds, label: "Scheduled disturbance" }]} />)}
    </section>}
    {runs.length > 0 && <section className="ws-panel"><h2>Saved runs</h2><ul className="ws-plant-runs">
      {runs.map(item => <li key={item.id}><a className="ws-link" aria-current={item.id === runId ? "page" : undefined}
        href={`#/${route}/${item.id}`}>{item.title}</a><span>{stateLabel[item.status]} · {new Date(item.updatedAt).toLocaleString("en")}</span></li>)}
    </ul></section>}
  </>;
}
