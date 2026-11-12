import { useEffect, useRef, useState, type FormEvent } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { forecastStatus, modelName } from "./prognosticLabels";
import { PrognosticEvaluation, PrognosticResults } from "./PrognosticResults";
import type { Evaluation, FitResult, MaintenanceCosts, MaintenanceEvent, Method, PrognosticConfig, Session, SessionSummary } from "./prognosticTypes";
import { dateLabel, signalLabel, timeLabel, type Dataset } from "./types";
import "./prognostics.css";

type Numeric = number | null | undefined;
type NumericFieldProps = {
  label: string;
  value: Numeric;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  required?: boolean;
};
function NumericField({ label, value, onChange, min, max, step, required }: NumericFieldProps) {
  return <label>{label}<input type="number" step={step ?? "any"} min={min} max={max} value={value ?? ""}
    required={required} onChange={event => onChange(event.target.value === "" ? null : event.target.valueAsNumber)} /></label>;
}

type Draft = Omit<PrognosticConfig, "indicator" | "maintenance" | "events" | "operatingPeriods" | "horizon"> & {
  indicator: Omit<PrognosticConfig["indicator"], "failure_threshold"> & { failure_threshold: number | null };
  maintenance: { [K in keyof MaintenanceCosts]: MaintenanceCosts[K] | null };
  events: { time: number | null; action: MaintenanceEvent["action"] }[];
  operatingPeriods: [number | null, number | null][];
  horizon: number | null;
};
const costFields = [
  ["preventive_cost", "Preventive restoration cost"],
  ["corrective_cost", "Corrective maintenance cost"],
  ["replacement_cost", "Replacement cost"],
  ["downtime_cost", "Downtime cost per second"],
  ["failure_consequence", "Additional failure consequence cost"],
  ["preventive_duration", "Restoration downtime (s)"],
  ["corrective_duration", "Corrective downtime (s)"],
  ["replacement_duration", "Replacement downtime (s)"],
] as const;
const exampleCosts = {
  preventive_cost: 500, corrective_cost: 2000, replacement_cost: 1300, downtime_cost: 2,
  failure_consequence: 1500, preventive_duration: 30, corrective_duration: 180, replacement_duration: 45,
};
function newDraft(dataset?: Dataset): Draft {
  const { start, end } = dataset?.metadata.time || { start: 0, end: 0 };
  const draft: Draft = {
    datasetId: dataset?.id || "", assetId: "", assetName: "",
    indicator: { signal: "", definition: "", unit: "", direction: "increasing", failure_threshold: null, operating_threshold: null },
    loadSignal: null, start, cutoff: end, horizon: Math.max(1, Math.ceil((end - start) / 2)),
    method: "stochastic", maintenance: { ...exampleCosts },
    events: [], operatingPeriods: [], endStatus: "censored", failureTime: null,
  };
  const benchmark = dataset?.metadata.prognosticBenchmark;
  return benchmark ? {
    ...draft, assetId: "coupled-tanks-pump", assetName: "Coupled-tank inlet pump",
    indicator: benchmark.indicator, loadSignal: benchmark.load_signal, events: benchmark.events,
    operatingPeriods: benchmark.operating_periods ?? [], endStatus: benchmark.end_status,
    cutoff: benchmark.cutoff ?? end, horizon: benchmark.horizon ?? 360,
  } : draft;
}
function fromConfig(config: PrognosticConfig): Draft {
  return { ...config, events: config.events ?? [], operatingPeriods: config.operatingPeriods ?? [] };
}
function parseDraft(draft: Draft, horizonText: string): PrognosticConfig {
  const { horizon, indicator, maintenance, events, operatingPeriods } = draft;
  const { failure_threshold } = indicator;
  const costs = costFields.map(([key]) => maintenance[key]);
  if (!horizon || failure_threshold == null || costs.some(value => value == null)) {
    throw new Error("Complete the threshold, horizon and cost inputs.");
  }
  if (events.some(event => event.time == null) || operatingPeriods.some(period => period.some(value => value == null))) {
    throw new Error("Complete each event time and operating period.");
  }
  const probabilityHorizons = horizonText.trim() ? horizonText.split(",").map(text => text.trim() === "" ? NaN : Number(text.trim())) : [];
  if (probabilityHorizons.length > 20 || probabilityHorizons.some(value => !Number.isFinite(value) || value < 0 || value > horizon)) {
    throw new Error("Enter up to 20 comma-separated probability horizons within the forecast horizon.");
  }
  // Native number inputs check required fields before submission. The casts below
  // follow the additional checks above for editable lists and optional values.
  return { ...draft, horizon, indicator: { ...indicator, failure_threshold },
    maintenance: { ...maintenance, discount_rate: maintenance.discount_rate ?? undefined } as MaintenanceCosts,
    events: events as MaintenanceEvent[], operatingPeriods: operatingPeriods as [number, number][],
    probabilityHorizons: probabilityHorizons.length ? probabilityHorizons : undefined };
}

function HistoryControls({ draft, edit, dataset }: { draft: Draft; edit: (patch: Partial<Draft>) => void; dataset?: Dataset }) {
  const min = dataset?.metadata.time.start, max = dataset?.metadata.time.end;
  return <details>
    <summary>{tr("Operating periods, maintenance and history outcome")}</summary>
    <p>{tr("Enter event times and operating periods in dataset seconds.")}</p>
    <div className="ws-form-grid">
      <label>{tr("History outcome")}<select value={draft.endStatus ?? "censored"} onChange={event => edit({ endStatus: event.target.value as Draft["endStatus"], failureTime: null })}>
        <option value="censored">{tr("Observation ended before confirmed failure")}</option>
        <option value="failed">{tr("Confirmed failure")}</option>
      </select></label>
      {draft.endStatus === "failed" && <NumericField label={tr("Confirmed failure time (dataset s)")} value={draft.failureTime} min={min} max={max} required onChange={failureTime => edit({ failureTime })} />}
    </div>
    <h3>{tr("Past restorations and replacements")}</h3>
    {draft.events.map((entry, index) => <div className="pm-history-row" key={index}>
      <NumericField label={tr("Event time (dataset s)")} value={entry.time} min={min} max={max} required
        onChange={time => edit({ events: draft.events.map((item, i) => i === index ? { ...item, time } : item) })} />
      <label>{tr("Event action")}<select value={entry.action}
        onChange={event => edit({ events: draft.events.map((item, i) => i === index ? { ...item, action: event.target.value as MaintenanceEvent["action"] } : item) })}>
        <option value="restore">{tr("Restoration")}</option><option value="replace">{tr("Replacement")}</option>
      </select></label>
      <button type="button" className="ws-outlined" onClick={() => edit({ events: draft.events.filter((_, i) => i !== index) })}>{tr("Remove event")}</button>
    </div>)}
    <button type="button" className="ws-outlined" onClick={() => edit({ events: [...draft.events, { time: null, action: "restore" }] })}>{tr("Add event")}</button>
    <h3>{tr("Known operating periods")}</h3>
    {draft.operatingPeriods.map(([from, until], index) => <div className="pm-history-row" key={index}>
      <NumericField label={tr("Period start (dataset s)")} value={from} min={min} max={max} required
        onChange={time => edit({ operatingPeriods: draft.operatingPeriods.map((item, i) => i === index ? [time, until] : item) })} />
      <NumericField label={tr("Period end (dataset s)")} value={until} min={from ?? min} max={max} required
        onChange={time => edit({ operatingPeriods: draft.operatingPeriods.map((item, i) => i === index ? [from, time] : item) })} />
      <button type="button" className="ws-outlined" onClick={() => edit({ operatingPeriods: draft.operatingPeriods.filter((_, i) => i !== index) })}>{tr("Remove period")}</button>
    </div>)}
    <button type="button" className="ws-outlined" onClick={() => edit({ operatingPeriods: [...draft.operatingPeriods, [null, null]] })}>{tr("Add period")}</button>
  </details>;
}

type DemoOptions = {
  duration?: number;
  sample_interval?: number;
  initial_condition?: number;
  degradation_rate?: number;
  load_effect?: number;
  load_profile?: "constant" | "variable";
  flow_noise?: number;
  missing_fraction?: number;
  jitter?: number;
  failure_threshold?: number;
  seed?: number;
};
const demoFields = [
  ["duration", "Simulation duration (s)", 20, 1800, 1],
  ["sample_interval", "Sampling interval (s)", 1, 120],
  ["initial_condition", "Initial pump capacity fraction", .05, 1],
  ["degradation_rate", "Capacity loss per second", 0, .02],
  ["load_effect", "Load sensitivity", 0, 4],
  ["flow_noise", "Flow measurement noise (m³/s)", 0, .005],
  ["missing_fraction", "Missing observation fraction", 0, .85],
  ["jitter", "Sampling jitter fraction", 0, .4],
  ["failure_threshold", "Failure threshold (capacity loss fraction)", .01, .99],
  ["seed", "Simulation seed", 0, 2147483647, 1],
] as const;

function PumpBenchmark({ busy, generate, hasScenario }: { busy: boolean; generate: (options: DemoOptions) => void; hasScenario: boolean }) {
  const [options, setOptions] = useState<DemoOptions>({});
  return <details className="ws-panel pm-demo" open={hasScenario || undefined}>
    <summary>{tr("Create a simulated pump dataset")}</summary>
    <form onSubmit={event => { event.preventDefault(); generate(options); }}>
      <p>{tr("Simulate gradual capacity loss in the coupled-tank pump. Blank fields use the benchmark defaults.")}</p>
      {hasScenario && <p>{tr("The selected coupled-tank scenario supplies the hydraulic settings.")}</p>}
      <fieldset disabled={busy}>
        <div className="ws-form-grid">
          <label>{tr("Pump load profile")}<select value={options.load_profile ?? ""} onChange={event => setOptions({ ...options, load_profile: event.target.value as DemoOptions["load_profile"] || undefined })}>
            <option value="">{tr("Benchmark default")}</option><option value="constant">{tr("Constant load")}</option><option value="variable">{tr("Variable load")}</option>
          </select></label>
          {demoFields.map(([key, label, min, max, step]) => <NumericField key={key} label={tr(label)} value={options[key]} min={min} max={max} step={step}
            onChange={value => setOptions({ ...options, [key]: value ?? undefined })} />)}
        </div>
        <button className="ws-outlined">{tr("Generate pump dataset")}</button>
      </fieldset>
    </form>
  </details>;
}

export function PrognosticWorkspace({ workspaceId, datasets, sessionId, initialDatasetId, benchmarkScenario, onGenerated }: {
  workspaceId: string;
  datasets: Dataset[];
  sessionId?: string;
  initialDatasetId?: string;
  benchmarkScenario?: { id: string; version: number };
  onGenerated: (dataset: Dataset) => void;
}) {
  useLocale();
  const base = `/workspaces/${workspaceId}/prognostics`;
  const route = `workspaces/${workspaceId}/maintenance`;
  const [draft, setDraft] = useState<Draft>(() => newDraft(datasets.find(dataset => dataset.id === initialDatasetId) || datasets[0]));
  const [generated, setGenerated] = useState<Dataset | null>(null);
  const [result, setResult] = useState<FitResult | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [saved, setSaved] = useState<Session | null>(null);
  const [name, setName] = useState("");
  const [horizonText, setHorizonText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [incident, setIncident] = useState(false);
  const [loadingSession, setLoadingSession] = useState(Boolean(sessionId));
  const [busy, setBusy] = useState<"fit" | "benchmark" | "evaluate" | "save" | null>(null);
  const active = useRef(false);
  const datasetsAvailable = generated && !datasets.some(dataset => dataset.id === generated.id) ? [...datasets, generated] : datasets;
  const dataset = datasetsAvailable.find(item => item.id === draft.datasetId);
  const resultDataset = datasetsAvailable.find(item => item.id === result?.config.datasetId);
  const savedAxis = datasetsAvailable.find(item => item.id === saved?.config.datasetId)?.metadata.time;
  const columns = dataset?.metadata.columns ?? [];
  const assetNames = [...new Set([...columns.map(column => column.device), ...sessions.map(session => session.assetName)].filter((value): value is string => Boolean(value)))];
  const disabled = Boolean(busy) || loadingSession;

  useEffect(() => {
    const controller = new AbortController();
    active.current = true;
    api<{ sessions: SessionSummary[] }>(`${base}/sessions`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setSessions(data.sessions); })
      .catch(cause => { if (!controller.signal.aborted) setError(message(cause)); });
    if (sessionId) {
      api<Session>(`${base}/sessions/${sessionId}`, undefined, "GET", controller.signal)
        .then(session => {
          if (controller.signal.aborted) return;
          setSaved(session); setResult(session); setDraft(fromConfig(session.config));
          setHorizonText(session.config.probabilityHorizons?.join(", ") ?? "");
          setEvaluation(session.evaluation ?? null); setName(session.name);
        })
        .catch(cause => { if (!controller.signal.aborted) setError(message(cause)); })
        .finally(() => { if (!controller.signal.aborted) setLoadingSession(false); });
    }
    return () => { active.current = false; controller.abort(); };
  }, [base, sessionId]);

  function edit(patch: Partial<Draft>) {
    setDraft(previous => ({ ...previous, ...patch }));
    setDirty(true);
  }
  async function run(operation: NonNullable<typeof busy>, action: () => Promise<void>) {
    setBusy(operation);
    setError("");
    try { await action(); }
    catch (cause) { if (active.current) setError(message(cause)); }
    finally { if (active.current) setBusy(null); }
  }
  function fit(event: FormEvent) {
    event.preventDefault();
    void run("fit", async () => {
      const response = await api<FitResult>(`${base}/fit`, parseDraft(draft, horizonText));
      if (active.current) { setResult(response); setDirty(false); }
    });
  }
  function save(event: FormEvent) {
    event.preventDefault();
    if (!result || dirty) return;
    void run("save", async () => {
      const session = await api<Session>(`${base}/sessions`, { ...result.config, name: name.trim(), includeEvaluation: Boolean(evaluation) });
      if (active.current) go(`${route}/${session.id}`);
    });
  }
  function generate(options: DemoOptions) {
    void run("benchmark", async () => {
      const body = benchmarkScenario ? { ...options, scenarioId: benchmarkScenario.id, scenarioVersion: benchmarkScenario.version } : options;
      const data = await api<{ dataset: Dataset; defaults: PrognosticConfig }>(`${base}/benchmark`, body);
      if (!active.current) return;
      setGenerated(data.dataset);
      setDraft(fromConfig(data.defaults)); setHorizonText(data.defaults.probabilityHorizons?.join(", ") ?? "");
      setResult(null); setName(""); setDirty(false); onGenerated(data.dataset);
    });
  }
  function evaluate() {
    void run("evaluate", async () => {
      const data = await api<Evaluation>(`${base}/evaluate`, {});
      if (active.current) setEvaluation(data);
    });
  }
  function chooseSignal(signal: string) {
    const column = columns.find(item => item.name === signal);
    edit({
      assetName: draft.assetName || column?.device || "",
      assetId: draft.assetId || column?.device || "",
      indicator: { ...draft.indicator, signal, definition: column?.description || "", unit: column?.unit || "", failure_threshold: null, operating_threshold: null },
      loadSignal: draft.loadSignal === signal ? null : draft.loadSignal,
    });
  }

  return <div className="pm-workspace">
    <div className="ws-page-title">
      <div><h1>{tr("Predictive Maintenance")}<span className="ws-accent">.</span></h1>
        <p>{tr("Forecast measured asset degradation and compare maintenance costs against an engineering failure threshold.")}</p></div>
      {sessionId && <a className="ws-outlined pm-action" href={`#/${route}`}>{tr("New prognostic session")}</a>}
    </div>
    <PumpBenchmark busy={disabled} generate={generate} hasScenario={Boolean(benchmarkScenario)} />
    <section className="ws-panel pm-section" aria-labelledby="pm-saved">
      <h2 id="pm-saved">{tr("Saved prognostic sessions")}</h2>
      {sessions.length ? <ul className="pm-session-list">{sessions.map(session => <li key={session.id}>
        <a className="ws-link" aria-current={session.id === sessionId ? "page" : undefined} href={`#/${route}/${session.id}`}>{session.name}</a>
        <span>{session.assetName} · {dateLabel(session.created_at)}</span><span>{forecastStatus(session.status)}</span>
      </li>)}</ul> : <p>{tr("Saved fits will appear here.")}</p>}
    </section>
    {loadingSession && <p role="status">{tr("Opening prognostic session…")}</p>}
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {busy && <p className="ws-notice" role="status">{tr({
      fit: "Fitting the degradation model…", benchmark: "Generating the pump dataset…",
      evaluate: "Running the held-out evaluation…", save: "Saving the prognostic session…",
    }[busy])}</p>}

    <form className="ws-panel pm-section" onSubmit={fit}>
      <h2>{tr("Asset, indicator and model")}</h2>
      {datasetsAvailable.length === 0 && <p><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>{tr("Import a dataset")}</a>{" · "}{tr("Or create a simulated pump dataset above.")}</p>}
      {!dataset && draft.datasetId && <p className="ws-notice">{tr("The original dataset is unavailable. The saved forecast remains available below.")}</p>}
      <fieldset disabled={disabled || !datasetsAvailable.length}>
        <legend>{tr("Measurement source")}</legend>
        <div className="ws-form-grid">
          <label>{tr("Dataset")}<select required value={draft.datasetId}
            onChange={event => { setDraft(newDraft(datasetsAvailable.find(item => item.id === event.target.value))); setHorizonText(""); setDirty(true); }}>
            <option value="">{tr("Choose a dataset")}</option>
            {datasetsAvailable.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label>{tr("Asset name")}<input list="pm-asset-names" required maxLength={160} value={draft.assetName} onChange={event => edit({ assetName: event.target.value })} /></label>
          <datalist id="pm-asset-names">{assetNames.map(asset => <option key={asset} value={asset} />)}</datalist>
          <label>{tr("Asset ID")}<input required maxLength={160} value={draft.assetId} onChange={event => edit({ assetId: event.target.value })} /></label>
          <label>{tr("Degradation signal")}<select required value={draft.indicator.signal} onChange={event => chooseSignal(event.target.value)}>
            <option value="">{tr("Choose a measured signal")}</option>{columns.map(signal => <option key={signal.name} value={signal.name}>{signalLabel(signal)}</option>)}
          </select></label>
          <label>{tr("Operating load signal (optional)")}<select value={draft.loadSignal ?? ""} onChange={event => edit({ loadSignal: event.target.value || null })}>
            <option value="">{tr("No load signal")}</option>{columns.filter(signal => signal.name !== draft.indicator.signal).map(signal => <option key={signal.name} value={signal.name}>{signalLabel(signal)}</option>)}
          </select></label>
          <label>{tr("Engineering unit")}<input required maxLength={80} value={draft.indicator.unit} onChange={event => edit({ indicator: { ...draft.indicator, unit: event.target.value } })} /></label>
        </div>
        <label>{tr("Indicator definition")}<textarea rows={2} required maxLength={500} value={draft.indicator.definition}
          onChange={event => edit({ indicator: { ...draft.indicator, definition: event.target.value } })} placeholder={tr("Describe what this measurement represents and why it tracks physical degradation.")} /></label>
        <p>{tr("Load measurements and operating periods provide context. The fit uses elapsed time and assumes a comparable future operating regime.")}</p>
      </fieldset>

      <fieldset disabled={disabled || !dataset}>
        <legend>{tr("Thresholds and fitting interval")}</legend>
        <div className="ws-form-grid">
          <label>{tr("Direction toward failure")}<select value={draft.indicator.direction} onChange={event => edit({ indicator: { ...draft.indicator, direction: event.target.value as Draft["indicator"]["direction"] } })}>
            <option value="increasing">{tr("Increasing condition value")}</option><option value="decreasing">{tr("Decreasing condition value")}</option>
          </select></label>
          <NumericField label={tr("Operational threshold (optional)")} value={draft.indicator.operating_threshold}
            onChange={operating_threshold => edit({ indicator: { ...draft.indicator, operating_threshold } })} />
          <NumericField label={tr("Failure threshold")} value={draft.indicator.failure_threshold} required
            onChange={failure_threshold => edit({ indicator: { ...draft.indicator, failure_threshold } })} />
          <NumericField label={tr("Training start (dataset s)")} value={draft.start} min={dataset?.metadata.time.start} max={draft.cutoff ?? dataset?.metadata.time.end} required onChange={start => edit({ start })} />
          <NumericField label={tr("Forecast cutoff (dataset s)")} value={draft.cutoff} min={draft.start ?? dataset?.metadata.time.start} max={dataset?.metadata.time.end} required onChange={cutoff => edit({ cutoff })} />
          <NumericField label={tr("Forecast horizon (s)")} value={draft.horizon} min={Number.MIN_VALUE} max={1e9} required onChange={horizon => edit({ horizon })} />
          <label>{tr("Prognostic model")}<select value={draft.method} onChange={event => edit({ method: event.target.value as Method })}>
            <option value="stochastic">{modelName("stochastic")}</option><option value="linear">{modelName("linear")}</option>
          </select></label>
          <label>{tr("Probability horizons (s, comma-separated)")}<input value={horizonText} onChange={event => { setHorizonText(event.target.value); setDirty(true); }} placeholder={tr("Defaults to 25%, 50% and 100% of the horizon")} /></label>
        </div>
        {dataset?.metadata.time.origin && <p>{tr("Dataset time is measured in seconds since {0}.", { 0: dataset.metadata.time.origin })}</p>}
        <HistoryControls draft={draft} edit={edit} dataset={dataset} />
      </fieldset>

      <fieldset disabled={disabled || !dataset}>
        <legend>{tr("Maintenance costs and downtime")}</legend>
        <p>{tr("Use the same currency for all costs. Durations are measured in seconds. Edit the example costs for your asset.")}</p>
        <div className="ws-form-grid">
          {costFields.map(([key, label]) => <NumericField key={key} label={tr(label)} min={0} required value={draft.maintenance[key]}
            onChange={value => edit({ maintenance: { ...draft.maintenance, [key]: value } })} />)}
          <NumericField label={tr("Planning horizon (s, optional)")} min={Number.MIN_VALUE} max={draft.horizon ?? undefined} value={draft.maintenance.planning_horizon}
            onChange={planning_horizon => edit({ maintenance: { ...draft.maintenance, planning_horizon } })} />
          <NumericField label={tr("Compare restoration at (s after cutoff)")} min={0} max={draft.maintenance.planning_horizon ?? draft.horizon ?? undefined} value={draft.maintenance.scheduled_time}
            onChange={scheduled_time => edit({ maintenance: { ...draft.maintenance, scheduled_time } })} />
          <NumericField label={tr("Discount rate per planning horizon (optional)")} min={0} value={draft.maintenance.discount_rate}
            onChange={discount_rate => edit({ maintenance: { ...draft.maintenance, discount_rate } })} />
        </div>
      </fieldset>
      <button className="ws-primary" disabled={disabled || !dataset}>{tr("Fit model and compare strategies")}</button>
    </form>

    {result && <>
      {dirty && <p className="ws-notice">{tr("These results reflect the last fit. Fit the model again to apply your edits.")}</p>}
      <PrognosticResults result={result} axis={resultDataset?.metadata.time} />
    </>}

    <section className="ws-panel pm-section" aria-labelledby="pm-validation">
      <div className="pm-heading"><h2 id="pm-validation">{tr("Retrospective validation")}</h2>
        <button type="button" className="ws-outlined" disabled={disabled} onClick={evaluate}>{tr("Run held-out pump evaluation")}</button></div>
      <p>{tr("Compare both models across synthetic pump histories using only observations available at each historical cutoff. These results describe simulated equipment.")}</p>
      {evaluation && <PrognosticEvaluation evaluation={evaluation} />}
    </section>

    {result && <form className="ws-panel pm-section" onSubmit={save}>
      <h2>{tr("Save forecast and maintenance comparison")}</h2>
      <div className="pm-heading">
        <label>{tr("Session name")}<input required maxLength={160} value={name} onChange={event => setName(event.target.value)} /></label>
        <button className="ws-primary" disabled={disabled || dirty || !name.trim()}>{tr(saved ? "Save as new session" : "Save session")}</button>
      </div>
      {evaluation && <p>{tr("The saved session includes the retrospective evaluation.")}</p>}
      {saved && <div className="pm-actions">
        <a className="ws-link" href={`/api${base}/sessions/${saved.id}/forecast.csv`}>{tr("Download saved forecast CSV")}</a>
        <a className="ws-link" href={`/api${base}/sessions/${saved.id}/maintenance.csv`}>{tr("Download saved maintenance CSV")}</a>
        <a className="ws-link" href={`/api${base}/sessions/${saved.id}/session.json`}>{tr("Download saved session JSON")}</a>
        <button type="button" className="ws-outlined" disabled={disabled} onClick={() => setIncident(true)}>{tr("Link saved forecast to an incident")}</button>
      </div>}
    </form>}
    {incident && saved && <IncidentLinkDialog workspaceId={workspaceId} source={{ kind: "prognostic", sessionId: saved.id }} draft={{
      title: saved.name, origin: savedAxis?.origin,
      start: saved.config.start, end: saved.forecast.cutoff,
      description: tr("Prognostic forecast for {0} at cutoff {1}.", {
        0: saved.config.assetName, 1: timeLabel(savedAxis ?? { kind: "numeric", origin: null, start: 0, end: 0, column: null }, saved.forecast.cutoff),
      }),
    }} onClose={() => setIncident(false)} />}
  </div>;
}
