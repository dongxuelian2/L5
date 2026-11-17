import { useEffect, useState } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, message } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { IncidentReport } from "./IncidentReport";
import { Contributions } from "./Results";
import type { ExperimentRun, ExperimentTask } from "./experimentTypes";
import { number, signalLabel, timeLabel, type AnalysisResult, type Dataset, type Incident } from "./types";
import "./guided-demo.css";

type Plan = {
  baselineRange: [number, number]; analysisRange: [number, number]; onset: number; step: number;
  signals: string[]; contextSignals: string[]; persistence: number;
};
type Session = { workspaceId: string; datasetId: string; experimentId: string; runId: string | null; incidentId: string | null };
type DemoState = { plan: Plan; session: Session | null };
type SavedResult = { task: ExperimentTask; result: AnalysisResult };

const endpoint = "/guided-demo";
const stepTitles = ["Observe the process", "Compare detectors", "Investigate the incident", "Generate the report"];
const running = (run: ExperimentRun) => run.status === "queued" || run.status === "running";
const rangeLabel = ([start, end]: [number, number]) => `${number(start)}–${number(end)} s`;
const modelLabels: Record<string, string> = {
  level1: "Tank 1 measured level", level2: "Tank 2 measured level", inlet: "Inlet flow", pump: "Pump command",
};

function demoSignalLabel(dataset: Dataset, name: string) {
  const signal = dataset.metadata.columns.find(column => column.name === name);
  if (!signal) return name;
  return signalLabel(signal.displayName && signal.displayName === modelLabels[name]
    ? { ...signal, displayName: tr(signal.displayName) } : signal);
}

function goToStep(step: number) {
  const section = document.getElementById(`guided-step-${step}`);
  section?.focus({ preventScroll: true });
  section?.scrollIntoView({ block: "start" });
}

function StepHeading({ step }: { step: number }) {
  return <h2 className="guided-step-heading"><span aria-hidden="true">0{step}</span>{tr(stepTitles[step - 1])}</h2>;
}

function StepNav({ current, available }: { current: number; available: number }) {
  return <ol className="guided-steps" aria-label={tr("Investigation steps")}>
    {stepTitles.map((title, i) => <li key={title} data-current={i + 1 === current}>
      <button type="button" aria-current={i + 1 === current ? "step" : undefined} disabled={i + 1 > available}
        onClick={() => goToStep(i + 1)}>
        <span aria-hidden="true">0{i + 1}</span>{tr(title)}
      </button>
    </li>)}
  </ol>;
}

export default function GuidedDemo({ onPrepared }: { onPrepared: () => void }) {
  const locale = useLocale();
  const [state, setState] = useState<DemoState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api<DemoState>(endpoint, undefined, "GET", controller.signal).then(setState).catch(e => {
      if (!controller.signal.aborted) setError(message(e));
    });
    return () => controller.abort();
  }, [revision]);

  async function update(action: "" | "/run" | "/incident") {
    setError(""); setBusy(true);
    try {
      setState(await api<DemoState>(endpoint + action, { locale }));
      if (action === "") onPrepared();
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  return <main className="ws-main guided-demo">
    <header className="guided-hero" data-ready={Boolean(state?.session)}>
      <div className="ws-kicker">{tr("BUILT-IN CASE · COUPLED TANKS")}</div>
      <h1>{tr("Guided Investigation Demo")}</h1>
      <p className="guided-question">{tr("Why did inlet flow fall while the pump command held steady?")}</p>
      <p>{tr("Follow a simulated supply loss from the original measurements to a saved incident and an offline report.")}</p>
      <div className="guided-tags"><span className="ws-badge">{tr("SEEDED SIMULATION")}</span><span className="ws-badge">{tr("NO EXTERNAL DATA")}</span><span className="ws-badge">{tr("SAVED LOCALLY")}</span></div>
      {state && !state.session && <div className="guided-actions">
        <button type="button" className="ws-primary" disabled={busy} onClick={() => void update("")}>{busy ? tr("Simulating and saving…") : tr("Load the scenario")}</button>
        <span className="ws-muted">{tr("Creates a dedicated workspace you can resume later.")}</span>
      </div>}
      {!state && !error && <p role="status">{tr("Loading guided demo…")}</p>}
      {!state?.session && error && <div className="guided-actions">
        <p className="ws-error" role="alert">{errorMessage(error)}</p>
        {!state && <button type="button" onClick={() => { setError(""); setRevision(v => v + 1); }}>{tr("Reconnect")}</button>}
      </div>}
    </header>
    {state && (state.session
      ? <DemoCase key={state.session.datasetId} session={state.session} plan={state.plan} busy={busy} error={error} update={update} />
      : <StepNav current={1} available={0} />)}
  </main>;
}

function DemoCase({ session, plan, busy, error, update }: {
  session: Session; plan: Plan; busy: boolean; error: string; update: (action: "/run" | "/incident") => Promise<void>;
}) {
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [run, setRun] = useState<ExperimentRun | null>(null);
  const [results, setResults] = useState<SavedResult[]>([]);
  const [loadError, setLoadError] = useState("");
  const [revision, setRevision] = useState(0);
  const [cursor, setCursor] = useState(plan.onset);
  const [context, setContext] = useState(false);
  const { datasetId, workspaceId, runId, experimentId, incidentId } = session;
  const workspace = `#/workspaces/${workspaceId}`;
  const markers = [{ time: plan.onset, label: tr("Injected onset") }];

  useEffect(() => {
    const controller = new AbortController();
    api<Dataset>(`/datasets/${datasetId}`, undefined, "GET", controller.signal).then(setDataset).catch(e => {
      if (!controller.signal.aborted) setLoadError(message(e));
    });
    return () => controller.abort();
  }, [datasetId, revision]);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await api<ExperimentRun>(`/experiment-runs/${runId}`, undefined, "GET", controller.signal);
        if (controller.signal.aborted) return;
        setRun(next);
        if (running(next)) { timer = setTimeout(load, 450); return; }
        const saved = await Promise.all(next.tasks.filter(task => task.status === "succeeded" && task.result_id)
          .map(async task => ({ task, result: await api<AnalysisResult>(`/analyses/${task.result_id}`, undefined, "GET", controller.signal) })));
        if (!controller.signal.aborted) setResults(saved);
      } catch (e) { if (!controller.signal.aborted) setLoadError(message(e)); }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, revision]);

  const currentRun = run?.id === runId ? run : null;
  const saved = currentRun ? results : [];
  const finished = currentRun !== null && !running(currentRun);
  const canRun = !runId || (finished && !currentRun.tasks.some(task => task.result_id));
  const progress = incidentId ? 4 : saved.length ? 3 : runId ? 2 : 1;
  return <>
    <StepNav current={progress} available={incidentId ? 4 : saved.length ? 3 : 2} />
    {loadError && <div className="guided-actions">
      <p className="ws-error" role="alert">{errorMessage(loadError)}</p>
      <button type="button" onClick={() => { setLoadError(""); setRevision(v => v + 1); }}>{tr("Retry loading saved demo")}</button>
    </div>}
    <section id="guided-step-1" className="ws-panel guided-step" tabIndex={-1}>
      <StepHeading step={1} />
      <p>{tr("Two connected tanks receive water from an inlet pump. At {0} s the simulation reduces pump efficiency while holding the command fixed.", {0: number(plan.onset)})}</p>
      <dl className="guided-facts">
        <div><dt>{tr("Normal fit and calibration")}</dt><dd>{rangeLabel(plan.baselineRange)}</dd></div>
        <div><dt>{tr("Scored window")}</dt><dd>{rangeLabel(plan.analysisRange)}</dd></div>
        <div><dt>{tr("Injected onset")}</dt><dd>{number(plan.onset)} s</dd></div>
      </dl>
      {dataset && <><div className="guided-actions" role="group" aria-label={tr("Process signals")}>
        <button type="button" aria-pressed={!context} onClick={() => setContext(false)}>{tr("Tank levels")}</button>
        <button type="button" aria-pressed={context} onClick={() => setContext(true)}>{tr("Inlet flow and pump command")}</button>
      </div>
      <SignalPlots dataset={dataset} signals={context ? plan.contextSignals : plan.signals} markers={markers}
        selectedTime={cursor} onSelectTime={setCursor} label={name => demoSignalLabel(dataset, name)} />
      <p className="ws-muted">{tr("The blue line marks simulator truth. The pump and flow are contextual measurements. Both detectors use the two tank levels.")}</p>
      <div className="guided-actions">
        <button type="button" className="ws-outlined" onClick={() => goToStep(2)}>{tr("Continue to detectors ↓")}</button>
        <a className="ws-link" href={`${workspace}/datasets/${datasetId}`}>{tr("Open dataset ↗")}</a>
        {dataset.metadata.model && <a className="ws-link" href={`${workspace}/simulations/${dataset.metadata.model.simulationId}`}>{tr("Open model session ↗")}</a>}
      </div></>}
      {!dataset && !loadError && <p role="status">{tr("Loading saved measurements…")}</p>}
    </section>
    <section id="guided-step-2" className="ws-panel guided-step" tabIndex={-1}>
      <StepHeading step={2} />
      <p>{tr("Robust Max-Z responds to the largest current deviation. EWMA smooths deviations over time. Both learn from the same normal baseline and require {0} consecutive exceedances.", {0: plan.persistence})}</p>
      {error && !saved.length && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      {canRun && <div className="guided-actions">
        <button type="button" className="ws-primary" disabled={busy || !dataset} onClick={() => void update("/run")}>{busy ? tr("Starting detectors…") : runId ? tr("Retry detectors") : tr("Run both detectors")}</button>
      </div>}
      {runId && !finished && !loadError && <p className="guided-status" role="status">{tr("Running saved detector tasks…")}{currentRun && ` ${currentRun.completed} / ${currentRun.task_count}`}</p>}
      {finished && currentRun.tasks.filter(task => task.status !== "succeeded").map(task => <p key={task.id} className="ws-error" role="alert">
        {tr(task.algorithm)} · {errorMessage(task.error || task.status)}
      </p>)}
      {dataset && saved.length > 0 && <DetectorResults key={runId} results={saved} dataset={dataset} plan={plan} cursor={cursor} setCursor={setCursor} />}
      {finished && <div className="guided-actions"><a className="ws-link" href={`${workspace}/experiments/${experimentId}`}>{tr("Open saved experiment ↗")}</a></div>}
    </section>
    {saved.length > 0 && <section id="guided-step-3" className="ws-panel guided-step" tabIndex={-1}>
      <StepHeading step={3} />
      <p>{tr("Carry the raw measurements, model provenance and all completed detector results into one incident. Use its timeline to add a hypothesis, record evidence and save your conclusion.")}</p>
      <div className="guided-actions">
        {incidentId
          ? <a className="ws-primary" href={`${workspace}/incidents/${incidentId}`}>{tr("Open incident workspace ↗")}</a>
          : <button className="ws-primary" type="button" disabled={busy} onClick={() => void update("/incident")}>{busy ? tr("Saving the incident…") : tr("Create linked incident")}</button>}
        {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      </div>
    </section>}
    {incidentId && <ReportStep incidentId={incidentId} />}
  </>;
}

function DetectorResults({ results, dataset, plan, cursor, setCursor }: {
  results: SavedResult[]; dataset: Dataset; plan: Plan; cursor: number; setCursor: (at: number) => void;
}) {
  const [selected, setSelected] = useState<{ id: string; index: number } | null>(null);
  const active = results.find(({ result }) => result.id === selected?.id) ?? results[0];
  const result = active.result;
  const initial = result.intervals.findIndex(interval => interval.end >= plan.onset);
  const index = selected?.index ?? Math.max(0, initial);
  const interval = result.intervals[index];
  const axis = dataset.metadata.time;
  const time = (value: number | null | undefined) => value == null ? "—" : timeLabel(axis, value);
  const markers = [{ time: plan.onset, label: tr("Injected onset") }];
  return <>
    <div className="guided-results" aria-label={tr("Detector comparison")}>
      {results.map(({ task, result: item }) => {
        const event = task.metrics?.labelled?.event;
        return <article key={item.id} className="guided-result" data-selected={item.id === result.id}>
          <h3>{tr(item.algorithmLabel)}</h3>
          <dl>
            <div><dt>{tr("First alarm")}</dt><dd>{time(item.summary.firstDetection)}</dd></div>
            <div><dt>{tr("Delay from injected onset")}</dt><dd>{event?.firstDetectionDelay == null ? tr("未检出") : `${number(event.firstDetectionDelay)} s`}</dd></div>
            <div><dt>{tr("Alarm intervals")}</dt><dd>{item.intervals.length}</dd></div>
            <div><dt>{tr("Pre-fault alarm intervals")}</dt><dd>{event?.falseAlarmEvents ?? "—"}</dd></div>
          </dl>
          <button type="button" aria-pressed={item.id === result.id} aria-label={tr("Inspect {0}", {0: tr(item.algorithmLabel)})}
            onClick={() => {
              const first = Math.max(0, item.intervals.findIndex(candidate => candidate.end >= plan.onset));
              setSelected({ id: item.id, index: first });
              setCursor(item.intervals[first]?.start ?? plan.onset);
            }}>{tr("Inspect timeline")}</button>
        </article>;
      })}
    </div>
    <p className="ws-muted">{tr("Compare alarm timing on this simulated run. Each method has its own score scale and threshold. Delay uses the labelled fault window; pre-fault intervals use the labelled normal part of the scored window.")}</p>
    <Plot title={tr(result.algorithmLabel)} times={result.times}
      values={result.scores.map((score, i) => result.states?.[i] === "abstain" ? null : score)}
      axis={axis} threshold={result.threshold} intervals={result.intervals} markers={markers} selectedTime={cursor} onSelectTime={setCursor} />
    <label className="guided-cursor">{tr("Shared cursor")}{` · ${time(cursor)}`}
      <input type="range" min={axis.start} max={axis.end} step={plan.step}
        value={cursor} onChange={e => setCursor(Number(e.target.value))} />
    </label>
    <div className="guided-evidence">
      <div>
        <h3>{tr("Alarm intervals")}</h3>
        {result.intervals.length ? <ul>{result.intervals.map((item, i) => <li key={i}>
          <button type="button" aria-pressed={i === index} onClick={() => { setSelected({ id: result.id, index: i }); setCursor(item.peakTime); }}>
            {time(item.start)} → {time(item.end)}
          </button>
        </li>)}</ul> : <p>{tr("No confirmed alarm intervals.")}</p>}
        <a className="ws-link" href={`#/workspaces/${result.workspaceId}/analysis/${result.id}${interval ? `/${index}` : ""}`}>{tr("Open saved analysis ↗")}</a>
      </div>
      <div>
        <h3>{tr("Signals contributing at the peak")}</h3>
        <p className="ws-muted">{interval ? tr("Alarm peak at {0}", {0: time(interval.peakTime)}) : tr("Highest score at {0}", {0: time(result.peakTime)})}</p>
        <Contributions values={interval?.contributions ?? result.signalContributions} signals={interval?.signals ?? result.relatedSignals}
          metric={result.contributionMetric} label={signal => demoSignalLabel(dataset, signal)} />
      </div>
    </div>
    <details>
      <summary>{tr("Align tank levels with the selected detector")}</summary>
      <SignalPlots dataset={dataset} signals={plan.signals} range={plan.analysisRange} intervals={result.intervals}
        markers={markers} selectedTime={cursor} onSelectTime={setCursor} label={name => demoSignalLabel(dataset, name)} />
    </details>
  </>;
}

function ReportStep({ incidentId }: { incidentId: string }) {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<Incident>(`/incidents/${incidentId}`, undefined, "GET", controller.signal).then(setIncident).catch(e => {
      if (!controller.signal.aborted) setError(message(e));
    });
    return () => controller.abort();
  }, [incidentId, revision]);
  return <section id="guided-step-4" className="guided-step" tabIndex={-1}>
    <StepHeading step={4} />
    {incident ? <IncidentReport incident={incident} /> : error
      ? <div className="guided-actions"><p className="ws-error" role="alert">{errorMessage(error)}</p><button type="button"
        onClick={() => { setError(""); setRevision(v => v + 1); }}>{tr("Retry loading saved demo")}</button></div>
      : <p role="status">{tr("Loading saved incident…")}</p>}
  </section>;
}
