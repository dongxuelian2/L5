import { useEffect, useRef, useState, type FormEvent } from "react";
import { downloadFile } from "../../lib/download";
import { api, go, message } from "../api";
import { number, type Dataset, type Series, type Signal } from "../types";
import { PlantMeasurements, type OperatingPlot } from "./PlantMeasurements";

type Settings = Record<"durationSeconds" | "onsetSeconds" | "interventionSeconds" | "seed", number> & { gain?: number };
type Scenario = { id: string; title: string; mechanism: string; comparison: string; settings: Settings; operatingPlots: OperatingPlot[] };
type Plant = {
  id: string; name: string; equipment: string[]; connection: string; mode: string; version: string;
  sampleSeconds: number; scenarios: Scenario[];
};
type Report = {
  diagnosis: { hypothesis: string; start: number; cutoff: number } | null;
  signatureDistances: Record<string, number>;
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
  settings: Settings; signalDefinitions: Signal[]; operatingPlots?: OperatingPlot[]; error?: string; result?: Result;
};

const active = new Set(["configured", "running", "measurements_available", "analysis_available"]);
const stateLabel: Record<string, string> = {
  configured: "Queued", running: "Running plant", measurements_available: "Measurements available",
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

export function PlantWorkspace({ workspaceId, runId, datasets, onChanged }: {
  workspaceId: string; runId?: string; datasets: Dataset[]; onChanged: () => void;
}) {
  const path = `/workspaces/${workspaceId}/plants`;
  const route = `workspaces/${workspaceId}/plants`;
  const [plants, setPlants] = useState<Plant[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [plantId, setPlantId] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [settings, setSettings] = useState<Settings>();
  const [run, setRun] = useState<Run>();
  const [series, setSeries] = useState<{ runId: string; data: Series }>();
  const [intervention, setIntervention] = useState<{ datasetId: string; data: Series }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [pollRevision, setPollRevision] = useState(0);
  const findings = useRef<HTMLElement>(null);
  const selectedRun = run?.id === runId ? run : undefined;
  const plant = plants.find(item => item.id === (selectedRun?.plantId ?? plantId)) ?? plants[0];
  const scenario = plant?.scenarios.find(item => item.id === (selectedRun?.scenarioId ?? scenarioId)) ?? plant?.scenarios[0];
  const plots = selectedRun?.operatingPlots ?? scenario?.operatingPlots ?? [];
  const operatingSignals = [...new Set(plots.flatMap(plot => plot.signals.map(signal => signal.name)))];
  const comparisonDataset = selectedRun?.result?.datasets.intervention;
  const comparisonSignals = new URLSearchParams(operatingSignals.map(signal => ["signal", signal])).toString();

  useEffect(() => {
    if (!comparisonDataset || !comparisonSignals) return;
    const controller = new AbortController();
    void api<Series>(`/datasets/${comparisonDataset}/series?${comparisonSignals}`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setIntervention({ datasetId: comparisonDataset, data }); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [comparisonDataset, comparisonSignals, pollRevision]);

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
    setError("");
    let readyDataset: string | undefined;
    async function poll() {
      try {
        const endpoint = `${path}/runs/${runId}`;
        const saved = await api<Run>(endpoint, undefined, "GET", controller.signal);
        if (controller.signal.aborted) return;
        setRun(saved);
        const key = `${saved.evaluationId || ""}/${saved.sampleCount || 0}`;
        if (key !== previousKey && (saved.evaluationId || saved.sampleCount || saved.status === "interrupted" || saved.status === "cancelled")) {
          const response = await api<{ series: Series | null }>(`${endpoint}/observations?view=operating`, undefined, "GET", controller.signal);
          if (controller.signal.aborted) return;
          setSeries(response.series ? { runId: saved.id, data: response.series } : undefined);
          previousKey = key;
        }
        if (saved.evaluationId && saved.evaluationId !== readyDataset) {
          readyDataset = saved.evaluationId;
          if (active.has(saved.status)) onChanged();
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
    setSettings(undefined);
    setSeries(undefined);
    setError("");
    if (runId) go(route);
  }

  async function start(stage = "investigation") {
    if (!scenario) return;
    setError("");
    setBusy(true);
    try {
      const next = await api<Run>(`${path}/runs`, { scenarioId: scenario.id, settings: values, stage });
      setSettings(undefined);
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
  if (runId && !selectedRun) return <>
    <p role={error ? "alert" : "status"}>{error || "Opening saved run…"}</p>
    {error && <div className="ws-inline"><button onClick={() => setPollRevision(value => value + 1)}>Retry</button><a className="ws-link" href={`#/${route}`}>Open plants and runs</a></div>}
  </>;
  const values = settings ?? selectedRun?.settings ?? scenario.settings;
  const isRunning = !!selectedRun && active.has(selectedRun.status);
  const unchanged = selectedRun && Object.entries(selectedRun.settings).every(([key, value]) => values[key as keyof Settings] === value);
  const result = selectedRun?.result;
  const report = result?.report;
  const delay = report?.detection.events[0]?.delay;
  const observations = series?.runId === runId ? series?.data : undefined;
  const matched = intervention?.datasetId === comparisonDataset ? intervention?.data : undefined;
  const gain = selectedRun?.settings.gain;
  const interventionName = `${scenario.comparison}${gain === undefined ? "" : ` ×${metric(gain)}`}`;
  const evaluationId = result?.datasets.evaluation ?? selectedRun?.evaluationId;
  const dataset = datasets.find(item => item.id === evaluationId);
  const signalIds = dataset?.metadata.columns.filter(column => operatingSignals.includes(column.name)).map(column => column.id).filter(Boolean);
  const context = new URLSearchParams();
  if (selectedRun) {
    context.set("plantRun", selectedRun.id);
    context.set("plant", selectedRun.plantId);
    context.set("modelVersion", selectedRun.modelVersion);
    if (evaluationId) context.set("dataset", evaluationId);
    (result?.signals ?? selectedRun.signalDefinitions.map(signal => signal.name)).forEach(signal => context.append("signal", signal));
    if (report && result) Object.entries({ analysis: result.analysisId, experiment: result.experimentId, incident: result.incidentId })
      .forEach(([key, value]) => context.set(key, value));
    if (report?.diagnosis) {
      context.set("start", String(report.diagnosis.start));
      context.set("end", String(report.diagnosis.cutoff));
    }
  }
  const interventionContext = new URLSearchParams(context);
  if (comparisonDataset) interventionContext.set("dataset", comparisonDataset);
  const explorerContext = new URLSearchParams(context);
  explorerContext.delete("signal");
  operatingSignals.forEach(signal => explorerContext.append("signal", signal));
  const workspace = `#/workspaces/${workspaceId}`;
  const sameVersion = !selectedRun || selectedRun.modelVersion === plant.version;
  return <>
    <div className="ws-page-title ws-plant-title"><div><h1>{plant.name}</h1><p>{selectedRun?.title ?? scenario.title}</p></div></div>
    <section className="ws-panel ws-plant" aria-label="Plant operation">
      <form onSubmit={(event: FormEvent) => { event.preventDefault(); void start(); }}>
        <div className="ws-plant-settings">
          <label>Plant<select aria-label="Plant" value={plant.id} onChange={e => select(plants.find(item => item.id === e.target.value)!)}>{plants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Operating scenario<select aria-label="Operating scenario" value={scenario.id} onChange={e => select(plant, plant.scenarios.find(item => item.id === e.target.value)!)}>{plant.scenarios.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
          {!(unchanged && selectedRun.status === "completed") && <button className="ws-primary" disabled={busy || isRunning || !sameVersion}>
            {isRunning ? "Running…" : busy ? "Submitting…" : unchanged && selectedRun.status === "measurements_ready" ? "Complete investigation" :
              unchanged && !isRunning ? "Resume investigation" : "Run investigation"}
          </button>}
        </div>
        <p>{scenario.mechanism}</p>
        <details><summary>Run settings and plant equipment</summary>
          <div className="ws-plant-settings">
            {([["durationSeconds", "Duration (s)"], ["onsetSeconds", "Disturbance onset (s)"],
              ["interventionSeconds", "Intervention time (s)"], ["seed", "Evaluation seed"],
              ...(values.gain === undefined ? [] : [["gain", "Cooling-loop gain multiplier"]])] as [keyof Settings, string][])
              .map(([key, label]) => <label key={key}>{label}<input type="number" required disabled={isRunning || !sameVersion}
                step={key === "gain" ? "any" : key === "seed" ? 1 : plant.sampleSeconds}
                value={Number.isFinite(values[key]) ? values[key] : ""} onChange={e => setSettings({ ...values, [key]: e.target.valueAsNumber })} /></label>)}
          </div>
          <p>{plant.mode} · {plant.connection}</p><p>{plant.equipment.join(" · ")}</p>
          <p>Observation interval {plant.sampleSeconds} s · Model <code>{(selectedRun?.modelVersion || plant.version).slice(0, 12)}</code></p>
          {!(unchanged && (selectedRun.status === "completed" || selectedRun.status === "measurements_ready")) &&
            <button type="button" disabled={busy || isRunning || !sameVersion} onClick={event => {
              if (event.currentTarget.form?.reportValidity()) void start("measurements");
            }}>Run measurements only</button>}{" "}
          {plant.id === "tep" && <a className="ws-link" href={`${workspace}/tep`}>Published Tennessee Eastman histories ↗</a>}
        </details>
      </form>
      {error && <p className="ws-error" role="alert">{error}{selectedRun && <button type="button" onClick={() => setPollRevision(value => value + 1)}>Reload run data</button>}</p>}
      {selectedRun && <div className="ws-plant-status">
        <p role="status"><strong>{stateLabel[selectedRun.status]}</strong>
          {isRunning && selectedRun.role && ` · ${roleLabel[selectedRun.role] ?? "Simulating a diagnosis reference"}`}
          {selectedRun.latestSeconds !== undefined && isRunning && ` · simulated through ${number(selectedRun.latestSeconds)} s`}</p>
        {isRunning && <button onClick={() => void cancel()} disabled={busy}>Cancel run</button>}
        {report && result && <><a className="ws-primary" download href={`/api/incidents/${result.incidentId}/report.html?download=1`}>Export investigation report</a>
          <button type="button" className="ws-link" onClick={() => findings.current?.focus()}>Investigation findings ↓</button></>}
        {selectedRun.error && <p className="ws-error" role="alert">{selectedRun.error}</p>}
      </div>}
    </section>
    {observations?.times.length && selectedRun ? <PlantMeasurements key={selectedRun.id} plots={plots} measured={observations} matched={matched}
      onset={selectedRun.settings.onsetSeconds} action={selectedRun.settings.interventionSeconds} interventionName={interventionName}>
      {signalIds?.length ? <a className="ws-link" href={`${workspace}/explorer/${signalIds.join(",")}?${explorerContext}`}>Explore signals ↗</a> : null}
      {evaluationId && <a className="ws-link" href={`${workspace}/datasets/${evaluationId}?${context}`}>Inspect measurements ↗</a>}
      {comparisonDataset && !matched && !error && <span role="status">Loading matched intervention…</span>}
    </PlantMeasurements> : selectedRun?.evaluationId && !error ? <p role="status">Loading operating measurements…</p> : null}
    {report && result && <section className="ws-panel" ref={findings} tabIndex={-1} aria-label="Investigation results">
      <h2>{delay == null ? "No confirmed event alarm" : `Alarm confirmed after ${number(delay)} s`}</h2>
      <p>{report.detection.normal.alarmSamples} alarm samples in {report.detection.normal.observedSamples} normal observations.
        {report.diagnosis && <> Closest reference <strong>{hypothesis(report.diagnosis.hypothesis)}</strong> from {metric(report.diagnosis.start)} to {metric(report.diagnosis.cutoff)} s.</>}</p>
      <h3>Matched intervention</h3>
      <div className="ws-table-scroll"><table><thead><tr><th>Metric</th><th>Baseline</th><th>Intervention</th></tr></thead>
        <tbody>{Object.entries(report.comparisonColumns).map(([key, title]) => <tr key={key}>
          <th scope="row">{title}</th><td>{metric(report.comparison.evaluation[key])}</td><td>{metric(report.comparison.intervention[key])}</td>
        </tr>)}</tbody></table></div>
      <div className="ws-dataset-actions">
        <a className="ws-link" href={`${workspace}/incidents/${result.incidentId}?${context}`}>Open incident ↗</a>
        <a className="ws-link" href={`${workspace}/analysis/${result.analysisId}?${context}`}>Open detection analysis ↗</a>
        <a className="ws-link" href={`${workspace}/experiments/${result.experimentId}?${context}`}>Open experiment ↗</a>
        <a className="ws-link" href={`${workspace}/safety?${context}`}>Assess operating limits ↗</a>
      </div>
      <details><summary>Diagnostic residuals and exports</summary>
        <ul>{Object.entries(report.signatureDistances).map(([key, value]) => <li key={key}>{hypothesis(key)} · {metric(value)}</li>)}</ul>
        <div className="ws-inline">
          <a className="ws-link" href={`${workspace}/datasets/${result.datasets.intervention}?${interventionContext}`}>Intervention measurements ↗</a>
          <button onClick={() => downloadFile(`${selectedRun.scenarioId}-evidence.json`, JSON.stringify(report, null, 2))}>Export evidence JSON</button>
        </div>
      </details>
    </section>}
    {runs.length > 0 && <section className="ws-panel"><h2>Saved runs</h2><ul className="ws-plant-runs">
      {runs.map(item => <li key={item.id}><a className="ws-link" aria-current={item.id === runId ? "page" : undefined}
        href={`#/${route}/${item.id}`}>{item.title}</a><span>{stateLabel[item.status]} · {new Date(item.updatedAt).toLocaleString("en")}</span></li>)}
    </ul></section>}
  </>;
}
