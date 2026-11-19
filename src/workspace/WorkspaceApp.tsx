import { errorMessage, t as tr } from "../lib/text";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { analysisPath, api, go, message, withPlantRun } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { ResultView } from "./monitoring/Results";
import { AlgorithmControls } from "./monitoring/AlgorithmControls";
import { AnalysisComparison } from "./monitoring/AnalysisComparison";
import { IncidentsPage } from "./investigation/Incidents";
import { ReplayWorkspace } from "./monitoring/ReplayWorkspace";
import { SignalWorkspace } from "./data/SignalWorkspace";
import { TransformationWorkspace, TransformationLineage } from "./data/TransformationWorkspace";
import { TEPWorkspace, ExternalProvenance } from "./investigation/TEPWorkspace";
import { ExperimentWorkspace } from "./investigation/ExperimentWorkspace";
import { PlantWorkspace } from "./investigation/PlantWorkspace";
import { SensorHealthWorkspace } from "./monitoring/SensorHealthWorkspace";
import { EstimationProvenance } from "./modeling/EstimationProvenance";
import { LiveWorkspace } from "./data/LiveWorkspace";
const AlarmWorkspace = lazy(() => import("./monitoring/AlarmWorkspace").then(m => ({ default: m.AlarmWorkspace })));
const ExperimentDesign = lazy(() => import("./modeling/ExperimentDesign").then(m => ({ default: m.ExperimentDesign })));
const ModelWorkspace = lazy(() => import("./modeling/ModelWorkspace").then(m => ({ default: m.ModelWorkspace })));
const ControlWorkspace = lazy(() => import("./modeling/ControlWorkspace").then(m => ({ default: m.ControlWorkspace })));
const CalibrationWorkspace = lazy(() => import("./modeling/CalibrationWorkspace").then(m => ({ default: m.CalibrationWorkspace })));
const EstimationWorkspace = lazy(() => import("./modeling/EstimationWorkspace").then(m => ({ default: m.EstimationWorkspace })));
const RegimeWorkspace = lazy(() => import("./monitoring/RegimeWorkspace").then(m => ({ default: m.RegimeWorkspace })));
const PrognosticWorkspace = lazy(() => import("./reliability/PrognosticWorkspace").then(m => ({ default: m.PrognosticWorkspace })));
const SafetyWorkspace = lazy(() => import("./reliability/SafetyWorkspace").then(m => ({ default: m.SafetyWorkspace })));
const ResilienceWorkspace = lazy(() => import("./reliability/ResilienceWorkspace").then(m => ({ default: m.ResilienceWorkspace })));
const SensorPlacementWorkspace = lazy(() => import("./modeling/SensorPlacementWorkspace").then(m => ({ default: m.SensorPlacementWorkspace })));
const ReachabilityWorkspace = lazy(() => import("./reliability/ReachabilityWorkspace").then(m => ({ default: m.ReachabilityWorkspace })));
import { dateLabel, number, signalLabel, timeLabel, type AnalysisResult, type Config, type Dataset, type Job, type Metadata, type Series, type Signal, type Workspace } from "./types";
import "./workspace.css";

function ErrorText({ error }: { error: string }) {
  return error ? <p className="ws-error" role="alert">{errorMessage(error)}</p> : null; }
function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="ws-empty"><span className="ws-empty-icon">⌗</span><h2>{title}</h2><p>{children}</p></div>; }
function Stats({ metadata }: { metadata: Metadata }) {
  return <div className="ws-stats"><div><strong>{metadata.rowCount.toLocaleString("en")}</strong><span>samples</span></div><div><strong>{metadata.columns.length}</strong><span>numeric signals</span></div><div><strong>{metadata.missingCount.toLocaleString("en")}</strong><span>missing values</span></div><div><strong>{number(metadata.time.end - metadata.time.start)} s</strong><span>duration</span></div></div>;
}

function SignalPicker({ columns, selected, onChange, title = "Analysis signals" }: { columns: Signal[]; selected: string[]; onChange: (signals: string[]) => void; title?: string }) {
  const [search, setSearch] = useState("");
  return <fieldset className="ws-signal-picker"><legend>{title} <span className="ws-muted">{selected.length} / {columns.length}</span></legend>
    <div className="ws-inline"><input aria-label={tr("Filter {0}", {0: title.toLowerCase()})} placeholder={"Filter signals…"} value={search} onChange={e => setSearch(e.target.value)} /><button type="button" onClick={() => onChange(columns.map(c => c.name))}>Select all</button><button type="button" onClick={() => onChange([])}>Clear</button></div>
    <div className="ws-signal-list">{columns.filter(c => `${c.name} ${c.displayName}`.toLowerCase().includes(search.toLowerCase())).map(c => <label key={c.name}><input type="checkbox" checked={selected.includes(c.name)} onChange={e => onChange(e.target.checked ? [...selected, c.name] : selected.filter(s => s !== c.name))} /><span>{signalLabel(c)}</span>{c.missing > 0 && <small>{c.missing}{" "}missing</small>}</label>)}</div>
  </fieldset>;
}

function WorkspaceHome({ workspaces, refresh }: { workspaces: Workspace[]; refresh: () => void }) {
  const [name, setName] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [manage, setManage] = useState<Workspace | null>(null), [newName, setNewName] = useState(""), [deleting, setDeleting] = useState(false);
  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const workspace = await api<Workspace>("/workspaces", { name: name.trim() || "Plant investigations" }); refresh(); go(`workspaces/${workspace.id}/plants`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function update(e: FormEvent) {
    e.preventDefault(); if (!manage) return; setBusy(true); setError("");
    try { await api(`/workspaces/${manage.id}`, deleting ? undefined : { name: newName }, deleting ? "DELETE" : "PATCH"); setManage(null); refresh(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <main className="ws-main ws-home">
    <div className="ws-page-title"><div><h1>Industrial workstation</h1><p>Run Tennessee Eastman or the stirred-tank reactor cascade. Open saved process measurements and investigations in the same workspace.</p></div></div>
    <form className="ws-create" onSubmit={create}><label htmlFor="workspace-name">Workspace name</label><div className="ws-inline"><input id="workspace-name" placeholder="Plant investigations" maxLength={160} value={name} onChange={e => setName(e.target.value)} /><button className="ws-primary" disabled={busy}>Create workspace</button></div></form>
    <ErrorText error={error} />
    <div className="ws-section-heading"><h2>Your projects</h2><span className="ws-muted">{tr(workspaces.length === 1 ? "{0} workspace" : "{0} workspaces", {0: workspaces.length})}</span></div>
    {workspaces.length > 0 && <div className="ws-projects">{workspaces.map(workspace => <article className="ws-project" key={workspace.id}>
      <div className="ws-project-menu"><button aria-label={`Manage ${workspace.name}`} onClick={() => { setManage(workspace); setNewName(workspace.name); setDeleting(false); }}>Manage</button></div>
      <a href={`#/workspaces/${workspace.id}/plants`}><h2>{workspace.name}</h2><p>{workspace.dataset_count || 0}{" "}datasets{" "}<span> / </span> {workspace.analysis_count || 0}{" "}analyses</p><div className="ws-inline ws-between"><small>Updated{" "}{dateLabel(workspace.updated_at)}</small><span className="ws-accent">Open workspace ↗</span></div></a>
    </article>)}</div>}
    {manage && <div className="ws-modal-backdrop"><form className="ws-modal" role="dialog" aria-modal="true" aria-label={"Manage workspace"} onSubmit={update}><h2>{deleting ? "Delete this workspace?" : "Manage workspace"}</h2>
      {deleting ? <p>“{manage.name}”, its datasets and analysis history will be permanently removed from this machine.</p> : <label>Workspace name<input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={160} autoFocus /></label>}
      <ErrorText error={error} /><div className="ws-inline"><button type="button" onClick={() => setManage(null)}>Cancel</button>{!deleting && <button type="button" className="ws-danger" onClick={() => setDeleting(true)}>Delete workspace</button>}<button disabled={busy} className={deleting ? "ws-danger ws-outlined" : "ws-primary"}>{deleting ? "Delete permanently" : "Save name"}</button></div>
    </form></div>}
  </main>;
}

export function ImportDataset({ workspaceId, onImport }: { workspaceId: string; onImport: (dataset: Dataset, open: boolean) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const fileVersion = useRef(0);
  const [csv, setCsv] = useState(""), [filename, setFilename] = useState(""), [name, setName] = useState("");
  const [plantName, setPlantName] = useState("");
  const [timeColumn, setTimeColumn] = useState("__auto"), [timeKind, setTimeKind] = useState("auto"), [timeUnit, setTimeUnit] = useState("seconds"), [interval, setInterval] = useState("1");
  const [timezone, setTimezone] = useState("UTC");
  const [preview, setPreview] = useState<{ metadata: Metadata; series: Series } | null>(null), [columns, setColumns] = useState<string[]>([]);
  const [error, setError] = useState(""), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const options = { ...(timeColumn === "__auto" ? {} : { timeColumn: timeColumn === "__generated" ? null : timeColumn }), timeKind, timeUnit, timezone, sampleInterval: Number(interval) };
  const optionKey = JSON.stringify(options);
  useEffect(() => {
    setPreview(null);
    if (!csv) return;
    setError("");
    const controller = new AbortController(); setLoading(true);
    const timer = setTimeout(() => {
      api<{ metadata: Metadata; series: Series }>("/datasets/preview", { csv, ...JSON.parse(optionKey) }, "POST", controller.signal)
        .then(data => { if (!controller.signal.aborted) { setPreview(data); setColumns(data.metadata.sourceColumns); } })
        .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [csv, optionKey]);
  async function chooseFile(file?: File) {
    if (!file) return;
    const version = ++fileVersion.current;
    setFilename(file.name); setName(file.name); setColumns([]); setCsv(""); setError(""); setTimeColumn("__auto"); setTimeKind("auto"); setTimeUnit("seconds"); setTimezone("UTC");
    try {
      const data = await file.arrayBuffer();
      if (version !== fileVersion.current) return;
      let text: string;
      try { text = new TextDecoder("utf-8", { fatal: true }).decode(data); }
      catch { text = new TextDecoder("gb18030").decode(data); }
      if (!text.trim()) throw new Error("Choose a nonempty CSV file.");
      setCsv(text);
    } catch (e) { if (version === fileVersion.current) setError(message(e)); }
  }
  async function save(e: FormEvent) {
    e.preventDefault(); setSaving(true); setError("");
    const route = window.location.hash;
    try {
      const dataset = await api<Dataset>(`/workspaces/${workspaceId}/datasets`, { csv, filename, name, plantName, ...options });
      onImport(dataset, window.location.hash === route);
    }
    catch (e) { setError(message(e)); } finally { setSaving(false); }
  }
  return <form className="ws-import ws-panel" onSubmit={save}>
    <div className="ws-section-heading"><h2>Import a CSV</h2><span className="ws-kicker">01 / DATA IN</span></div>
    <div className="ws-file"><input ref={fileInput} aria-label={"Choose CSV file"} type="file" hidden accept=".csv,.tsv,.txt,text/csv" onChange={e => void chooseFile(e.target.files?.[0])} />
      <div className="ws-inline"><button type="button" className="ws-file-button" onClick={() => fileInput.current?.click()} aria-describedby="csv-filename csv-help">Choose file</button><span id="csv-filename" className="ws-file-name" aria-live="polite">{filename || "No file selected"}</span></div>
      <span id="csv-help">CSV / TSV · named numeric signals</span>
    </div>
    {csv && <>
      <div className="ws-form-grid"><label>Dataset name<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} /></label><label>Recorded plant (optional)<input value={plantName} onChange={e => setPlantName(e.target.value)} maxLength={160} /></label><label>Time axis<select value={timeColumn} onChange={e => setTimeColumn(e.target.value)}><option value="__auto">Auto-detect time column</option><option value="__generated">Generate from sampling interval</option>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></label>
        {timeColumn === "__generated" ? <label>Sampling interval (seconds)<input type="number" min="0.000001" step="any" value={interval} onChange={e => setInterval(e.target.value)} required /></label> : <><label>Time format<select value={timeKind} onChange={e => setTimeKind(e.target.value)}><option value="auto">Auto · numeric or date/time</option><option value="numeric">Relative numeric time</option><option value="datetime">ISO date / timestamp</option><option value="unix">Unix epoch time</option></select></label><label>Numeric time unit<select value={timeUnit} onChange={e => setTimeUnit(e.target.value)}>{["seconds", "milliseconds", "minutes", "hours"].map(v => <option key={v}>{v}</option>)}</select></label>{(timeKind === "auto" || timeKind === "datetime") && <label>Timezone for dates without timezone<input value={timezone} onChange={e => setTimezone(e.target.value)} placeholder={"UTC or Asia/Shanghai"} /></label>}</>}
      </div>
      {loading && <p role="status">Parsing and previewing CSV…</p>}
      {preview && <><Stats metadata={preview.metadata} /><p className="ws-muted">Time interpretation:{" "}{tr(preview.metadata.time.kind)} · {preview.metadata.time.sourceUnit || preview.metadata.time.naiveTimezone || "seconds"} · {preview.metadata.time.column || "generated"} · {timeLabel(preview.metadata.time, preview.metadata.time.start)} → {timeLabel(preview.metadata.time, preview.metadata.time.end)}</p><p className="ws-muted">Numeric time is relative unless you explicitly choose Unix epoch time. Relative sources are independent until a time relationship is saved.</p>
        {preview.metadata.notes.map(note => <p key={note} className="ws-notice">{note}</p>)}
        <details><summary>Inspect columns and sample rows</summary><div className="ws-table-scroll"><table><thead><tr><th>Signal</th><th>Minimum</th><th>Maximum</th><th>Missing</th></tr></thead><tbody>{preview.metadata.columns.map(c => <tr key={c.name}><td>{c.name}</td><td>{c.min == null ? "—" : number(c.min)}</td><td>{c.max == null ? "—" : number(c.max)}</td><td>{c.missing}</td></tr>)}</tbody></table><table><thead><tr><th>Time (s)</th>{Object.keys(preview.series.values).map(s => <th key={s}>{s}</th>)}</tr></thead><tbody>{preview.series.times.slice(0, 5).map((t, i) => <tr key={i}><td>{number(t)}</td>{Object.keys(preview.series.values).map(s => <td key={s}>{preview.series.values[s][i] == null ? "missing" : number(preview.series.values[s][i]!)}</td>)}</tr>)}</tbody></table></div>{preview.metadata.ignoredColumns.length > 0 && <p className="ws-muted">Non-numeric columns:{" "}{preview.metadata.ignoredColumns.join(", ")}</p>}</details>
        <Plot times={preview.series.times} values={Object.values(preview.series.values)[0]} title={preview.metadata.columns[0].name} axis={preview.metadata.time} />
      </>}
      <ErrorText error={error} /><button className="ws-primary" disabled={!preview || loading || saving || !name.trim()}>{saving ? "Saving dataset…" : "Import and save dataset ↗"}</button>
    </>}
    {!csv && <ErrorText error={error} />}
  </form>;
}

function DatasetPage({ workspaceId, datasets, onImport, selected, setSelected, preferences, setPreferences, datasetId, range, search }: {
  workspaceId: string; datasets: Dataset[]; onImport: (dataset: Dataset, open: boolean) => void; selected: string; setSelected: (id: string) => void;
  preferences: Record<string, string[]>; setPreferences: (id: string, signals: string[]) => void; datasetId?: string; range?: [number, number]; search: string;
}) {
  const [importing, setImporting] = useState(false);
  const [signalOverride, setSignalOverride] = useState<string[]>();
  const dataset = datasets.find(d => d.id === (datasetId || selected)) || (datasetId ? undefined : datasets[0]);
  if (datasetId && !dataset) return <p role="alert">This dataset is unavailable in this workspace. <a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>View saved datasets</a></p>;
  const incoming = new URLSearchParams(search);
  const routeSignals = incoming.getAll("signal");
  const chosen = dataset ? signalOverride ?? (routeSignals.length ? routeSignals.filter(signal => dataset.metadata.columns.some(column => column.name === signal)) :
    preferences[dataset.id] ?? dataset.metadata.columns.slice(0, 4).map(column => column.name)) : [];
  const query = incoming.has("plantRun") ? incoming : new URLSearchParams();
  if (dataset) query.set("dataset", dataset.id);
  query.delete("signal");
  chosen.forEach(signal => query.append("signal", signal));
  return <>
    <div className="ws-page-title"><div><h1>Process measurements</h1><p><a className="ws-link" href={`#/workspaces/${workspaceId}/plants`}>Open plants and runs ↗</a> · <a className="ws-link" href={`#/workspaces/${workspaceId}/tep`}>Import Tennessee Eastman histories ↗</a></p></div>{datasets.length > 0 && <button className="ws-primary" onClick={() => setImporting(!importing)}>{importing ? "Close import" : "Import CSV or TSV"}</button>}</div>
    {(importing || datasets.length === 0) && <ImportDataset workspaceId={workspaceId} onImport={(d, open) => { onImport(d, open); setImporting(false); }} />}
    {dataset && <>
      <div className="ws-section-heading"><h2>Saved datasets{" "}<span className="ws-muted">/ {datasets.length}</span></h2><label className="ws-inline">Dataset<select aria-label={"Saved dataset"} value={dataset.id} onChange={e => setSelected(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div>
      <section className="ws-panel"><h2>{dataset.name}</h2><Stats metadata={dataset.metadata} /><p className="ws-muted">{timeLabel(dataset.metadata.time, dataset.metadata.time.start)} → {timeLabel(dataset.metadata.time, dataset.metadata.time.end)}{dataset.metadata.time.origin && " · Window inputs use seconds since the first timestamp."}</p>
        <SignalPicker columns={dataset.metadata.columns} selected={chosen} onChange={signals => { setSignalOverride(signals); setPreferences(dataset.id, signals); }} title={"Signals to plot and analyze"} />
        {range && <p className="ws-muted">Plot window {timeLabel(dataset.metadata.time, range[0])} to {timeLabel(dataset.metadata.time, range[1])}</p>}
        <SignalPlots dataset={dataset} signals={chosen} range={range} />
        {dataset.metadata.processRun && <p>{dataset.metadata.processRun.plant} · {dataset.metadata.processRun.type} · {dataset.metadata.processRun.role} · <a className="ws-link" href={`#/workspaces/${workspaceId}/plants${dataset.metadata.processRun.operationId ? "/" + dataset.metadata.processRun.operationId : ""}`}>Open plant run ↗</a></p>}
        {dataset.metadata.processIdentity && <p>Recorded plant · {dataset.metadata.processIdentity.name}</p>}
        <TransformationLineage dataset={dataset} /><ExternalProvenance dataset={dataset} /><EstimationProvenance dataset={dataset} />
        {dataset.metadata.model?.control && <a className="ws-link" href={`#/workspaces/${workspaceId}/control/${dataset.metadata.model.control.experimentId}`}>Open saved control comparison ↗</a>}
        {dataset.metadata.acquisition && <p className="ws-notice">
          <code>{dataset.metadata.acquisition.endpoint}</code>{" · "}
          <a className="ws-link" href={`#/workspaces/${workspaceId}/live/${dataset.metadata.acquisition.sessionId}`}>Open raw OPC UA recording ↗</a>
        </p>}
        {dataset.metadata.recovery && <p className="ws-muted"><a className="ws-link" href={`#/workspaces/${workspaceId}/reachability/${dataset.metadata.recovery.studyId}`}>Open source recovery study</a>{" · "}{tr("reach." + dataset.metadata.recovery.strategy)}</p>}
        <div className="ws-dataset-actions"><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/new/${dataset.id}?${query}`}>Create a multi-algorithm experiment ↗</a>
        {!dataset.metadata.transformation && <a className="ws-link" href={`#/workspaces/${workspaceId}/monitoring/${dataset.id}?${query}`}>Replay and monitor ↗</a>}
        {!dataset.metadata.processRun && <a className="ws-link" href={`#/workspaces/${workspaceId}/maintenance?${query}`}>Forecast a degradation indicator ↗</a>}
        <a className="ws-link" href={`#/workspaces/${workspaceId}/safety?${query}`}>Assess operating limits ↗</a>
        {dataset.metadata.model && <a className="ws-primary" href={`#/workspaces/${workspaceId}/simulations/${dataset.metadata.model.simulationId}`}>Open process investigation &amp; interventions ↗</a>}</div>
        <div className="ws-inline"><a className="ws-link" href={`#/workspaces/${workspaceId}/explorer/${dataset.metadata.columns.filter(c => chosen.includes(c.name)).map(c => c.id).filter(Boolean).join(",")}?${query}`}>Open Signal Explorer ↗</a>
          <a className="ws-link" href={`/api/datasets/${dataset.id}/series.csv`}>Download CSV</a>
          {dataset.metadata.processRun && <a className="ws-link" href={`/api/datasets/${dataset.id}/series.npz`}>Download numerical trace</a>}
          <button className="ws-primary" onClick={() => { setPreferences(dataset.id, chosen); go(`workspaces/${workspaceId}/analysis?${query}`); }} disabled={!chosen.length}>Configure analysis ↗</button></div>
      </section>
    </>}
  </>;
}

export function AnalysisPage({ workspaceId, datasets, selected, setSelected, preferences, jobId, refresh, intervalIndex, initialRange, initialDatasetId, initialSignals }: {
  workspaceId: string; datasets: Dataset[]; selected: string; setSelected: (id: string) => void; preferences: Record<string, string[]>; jobId?: string; refresh: () => void; intervalIndex?: number; initialRange?: [number, number]; initialDatasetId?: string; initialSignals?: string[];
}) {
  const [config, setConfig] = useState<Config | null>(null), [result, setResult] = useState<AnalysisResult | null>(null);
  const sourceId = jobId ? result?.datasetId : initialDatasetId;
  const dataset = datasets.find(d => d.id === (sourceId || selected)) || (sourceId ? undefined : datasets[0]);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const resultPanel = useRef<HTMLDivElement>(null);
  const context = useRef(0);
  useEffect(() => { context.current++; setBusy(false); return () => { context.current++; }; }, [dataset?.id, jobId, initialSignals, initialRange]);
  useEffect(() => {
    if (!dataset || jobId) return;
    const ranges = dataset.metadata.suggestedRanges || { baselineRange: [dataset.metadata.time.start, dataset.metadata.time.end] as [number, number], analysisRange: [dataset.metadata.time.start, dataset.metadata.time.end] as [number, number] };
    setConfig({ datasetId: dataset.id, signals: initialSignals?.length ? initialSignals.filter(name => dataset.metadata.columns.some(c => c.name === name)) : preferences[dataset.id] ?? dataset.metadata.columns.map(c => c.name), algorithm: "robust-maxz", alpha: .01, variance: .9, ...ranges, ...(initialRange ? { analysisRange: initialRange, baselineRange: [dataset.metadata.time.start, Math.max(dataset.metadata.time.start, Math.min(ranges.baselineRange[1], initialRange[0]-(dataset.metadata.time.typicalInterval || 1)))] as [number, number] } : {}) });
    setResult(null); setError("");
  }, [dataset?.id, jobId, initialRange, initialSignals]);
  useEffect(() => {
    if (!jobId || result?.id === jobId) { setLoading(false); return; }
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null); setConfig(null);
    api<AnalysisResult>(`/analyses/${jobId}`, undefined, "GET", controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.workspaceId !== workspaceId) throw new Error("Analysis belongs to another workspace.");
      setResult(data); setConfig(data.config); setSelected(data.datasetId);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [jobId]);
  useEffect(() => {
    if (jobId && result?.id === jobId) resultPanel.current?.scrollIntoView({ behavior: "instant", block: "start" });
  }, [jobId, result?.id]);
  useEffect(() => {
    if (result?.regimeRunId) window.location.replace(`#/workspaces/${workspaceId}/regimes/runs/${result.regimeRunId}${intervalIndex !== undefined ? `/${intervalIndex}` : ""}`);
  }, [workspaceId, result?.regimeRunId, intervalIndex]);
  async function run(e: FormEvent) {
    e.preventDefault(); if (!config) return; const request = context.current; setBusy(true); setError("");
    try { const data = await api<AnalysisResult>(`/workspaces/${workspaceId}/analyses`, config); if (request !== context.current) return; setResult(data); refresh(); go(withPlantRun(`workspaces/${workspaceId}/analysis/${data.id}`)); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  function set<K extends keyof Config>(key: K, value: Config[K]) { setConfig(c => c ? { ...c, [key]: value } : c); }
  if (result?.regimeRunId) return <p role="status">Opening saved regime session…</p>;
  if (sourceId && !dataset) return <p role="alert">This analysis source is unavailable in this workspace. <a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>Choose a dataset</a></p>;
  if (!dataset) return <Empty title={"Import data to start analyzing"}><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>Go to datasets →</a></Empty>;
  const resultDataset = result && datasets.find(d => d.id === result.datasetId);
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">02 / ANALYSIS ENGINE</div><h1>Find what changed<span className="ws-accent">.</span></h1><p>Fit a normal baseline, then score a later window of your measurements.</p></div><span className="ws-badge">FULL-RESOLUTION COMPUTATION</span></div>
    {loading ? <p role="status">Opening saved analysis…</p> : config?.training ? <section className="ws-panel"><h2>Saved independent dataset analysis</h2><p>Review the normal training, calibration and test sources with the saved result below.</p><a className="ws-link" href={withPlantRun(`#/workspaces/${workspaceId}/experiments/${result?.experiment?.experimentId || "new"}`)}>Configure independent sources and rerun in Experiments ↗</a></section> : config && <form className="ws-panel ws-analysis-form" onSubmit={run}>
      <div className="ws-form-grid"><label>Dataset<select value={dataset.id} onChange={e => { const next = datasets.find(d => d.id === e.target.value)!; setSelected(next.id); go(analysisPath(workspaceId, next.id, preferences[next.id] ?? next.metadata.columns.map(c => c.name))); }}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label>Analysis name (optional)<input maxLength={160} value={config.name || ""} onChange={e => set("name", e.target.value)} placeholder={"e.g. Temperature excursion review"} /></label></div>
      <SignalPicker columns={dataset.metadata.columns} selected={config.signals} onChange={signals => setConfig({ ...config, signals, requiredSignals:config.requiredSignals?.filter(s=>signals.includes(s)), stress:{ ...config.stress, missingSignals:config.stress?.missingSignals?.filter(s=>signals.includes(s)) } })} />
      <div className="ws-window-grid">{(["baselineRange", "analysisRange"] as const).map(key => <fieldset key={key}><legend>{key === "baselineRange" ? "Normal baseline · assumed healthy" : "Analysis window · target data"}</legend><div className="ws-form-grid"><label>{key === "baselineRange" ? "Baseline start (s)" : "Analysis start (s)"}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][0]} onChange={e => set(key, [Number(e.target.value), config[key][1]])} required /></label><label>{key === "baselineRange" ? "Baseline end (s)" : "Analysis end (s)"}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][1]} onChange={e => set(key, [config[key][0], Number(e.target.value)])} required /></label></div></fieldset>)}</div>
      <p className="ws-notice">Choose a baseline you believe is normal, ending before the analysis window. Use at least 30 fit and 30 calibration observations; the fit fraction can be configured below.{dataset.metadata.time.origin && tr(" Times are elapsed seconds from {0}.", {0: timeLabel(dataset.metadata.time, 0)})}</p>
      <AlgorithmControls config={config} onChange={setConfig} />
      <ErrorText error={error} /><div className="ws-inline ws-between"><span className="ws-muted">Every completed run is saved automatically to History.</span><button className="ws-primary" disabled={busy || loading || !config.signals.length}>{busy ? "Computing and saving…" : result ? "Run again with these parameters ↗" : "Run analysis and save ↗"}</button></div>
    </form>}
    {!config && <ErrorText error={error} />}
    {result && resultDataset && <div ref={resultPanel} className="ws-result-anchor"><ResultView key={result.id} result={result} dataset={resultDataset} initialIntervalIndex={intervalIndex} signalPicker={(selected, onChange) => <SignalPicker title={"Raw signals in view"} columns={resultDataset.metadata.columns.filter(c => (result.config.signalMapping ? Object.values(result.config.signalMapping) : result.config.signals).includes(c.name))} selected={selected} onChange={onChange} />} /></div>}
  </>;
}

function HistoryPage({ jobs, datasets, workspaceId }: { jobs: Job[]; datasets: Dataset[]; workspaceId: string }) {
  return <><div className="ws-page-title"><div><div className="ws-kicker">03 / HISTORY</div><h1>Every run, retained<span className="ws-accent">.</span></h1><p>Reopen a result or use its saved parameters for another analysis.</p></div><span className="ws-badge">{jobs.length}{" "}SAVED RUNS</span></div>
    {jobs.length > 1 && <AnalysisComparison jobs={jobs} datasets={datasets} />}
    {jobs.length === 0 ? <Empty title={"Your analyses will appear here"}><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis`}>Start an analysis →</a></Empty> : <div className="ws-history">{jobs.map(job => <a href={`#/workspaces/${workspaceId}/${job.config.regimeRunId ? `regimes/runs/${job.config.regimeRunId}` : `analysis/${job.id}`}`} className="ws-history-row" key={job.id}><div><span className="ws-kicker">{job.config.regimeRunId ? "Regime-aware monitoring" : job.config.algorithm} / {dateLabel(job.created_at)}</span><h2>{job.name}</h2><p>{datasets.find(d => d.id === job.dataset_id)?.name} · {job.config.signals.length}{" "}signals ·{" "}{number(job.config.analysisRange[0])}–{number(job.config.analysisRange[1])} s</p></div><div><strong className={job.summary.flaggedSamples ? "ws-coral" : "ws-accent"}>{job.summary.flaggedSamples.toLocaleString("en")}{" "}flagged</strong><span>Open result ↗</span></div></a>)}</div>}
  </>;
}

const workspaceNavigation = [
  ["Operation", [["plants", "Plants and runs"], ["models", "Hydraulic and TripLens simulation"]]],
  ["Data", [["datasets", "Datasets"], ["signals", "Signal catalog"], ["quality", "Data quality"],
    ["explorer", "Signal explorer"], ["transformations", "Transformations"], ["live", "Live data"]]],
  ["Monitoring", [["analysis", "Analysis"], ["monitoring", "Replay and monitoring"],
    ["regimes", "Operating regimes"], ["alarms", "Alarm management"], ["sensor-health", "Sensor health"]]],
  ["Investigation", [["incidents", "Incidents"], ["history", "Analysis history"],
    ["experiments", "Experiments"], ["tep", "Tennessee Eastman histories"]]],
  ["Coupled-tank specialists", [["calibration", "Digital twin calibration"],
    ["estimations", "State estimation"], ["control", "PI and MPC control"],
    ["sensor-placement", "Sensor placement"], ["experiment-designs", "Experiment design"],
    ["resilience", "Resilience testing"], ["reachability", "Recovery and reachability"]]],
  ["Reliability", [["maintenance", "Predictive maintenance"], ["safety", "Operating limits and forecasts"]]],
] as const;

export default function WorkspaceApp({ path, search = "" }: { path: string[]; search?: string }) {
  const workspaceId = path[0] === "workspaces" ? path[1] : undefined, tab = path[2] || "plants", jobId = path[3];
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]), [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]), [jobs, setJobs] = useState<Job[]>([]), [selected, setSelected] = useState("");
  const routeContext = useMemo(() => {
    const query = new URLSearchParams(search), start = query.get("start"), end = query.get("end");
    const range = start !== null && end !== null && Number.isFinite(Number(start)) && Number.isFinite(Number(end)) && Number(start) <= Number(end) ? [Number(start), Number(end)] as [number, number] : undefined;
    const scenarioId = query.get("scenario"), scenarioVersion = Number(query.get("scenarioVersion"));
    const benchmarkScenario = scenarioId && Number.isSafeInteger(scenarioVersion) && scenarioVersion > 0 ? { id: scenarioId, version: scenarioVersion } : undefined;
    return { datasetId: query.get("dataset") || undefined, experimentId: query.get("experiment") || undefined, signals: query.getAll("signal"), range, benchmarkScenario };
  }, [search]);
  const [preferences, setPreferences] = useState<Record<string, string[]>>({}), [error, setError] = useState(""), [loading, setLoading] = useState(true), [revision, setRevision] = useState(0);
  function refresh() { setRevision(v => v + 1); }
  useEffect(() => {
    if (workspaceId) return;
    const controller = new AbortController(); setError("");
    api<{ workspaces: Workspace[] }>("/workspaces", undefined, "GET", controller.signal).then(data => setWorkspaces(data.workspaces)).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted && !workspaceId) setLoading(false); });
    return () => controller.abort();
  }, [revision, workspaceId]);
  useEffect(() => { if (tab === "datasets" && jobId) setSelected(jobId); }, [tab, jobId]);
  useEffect(() => {
    if (tab === "analysis" && !jobId && routeContext.datasetId) {
      setSelected(routeContext.datasetId);
      if (routeContext.signals.length) setPreferences(p => ({ ...p, [routeContext.datasetId!]: routeContext.signals }));
    }
  }, [tab, jobId, routeContext]);
  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController(); setError("");
    Promise.all([api<Workspace>(`/workspaces/${workspaceId}`, undefined, "GET", controller.signal), api<{ datasets: Dataset[] }>(`/workspaces/${workspaceId}/datasets`, undefined, "GET", controller.signal), api<{ jobs: Job[] }>(`/workspaces/${workspaceId}/analyses`, undefined, "GET", controller.signal)])
      .then(([w, d, j]) => { if (controller.signal.aborted) return; setWorkspace(w); setDatasets(d.datasets); setJobs(j.jobs); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId, revision, tab === "history"]);
  const query = new URLSearchParams(search);
  const dataMode = tab === "signals" || tab === "quality" || tab === "explorer" ? tab : null;
  const content = loading ? <p role="status">Opening workspace…</p> : !workspace ? null :
    tab === "plants" ? <PlantWorkspace workspaceId={workspaceId!} runId={jobId} datasets={datasets} onChanged={refresh} /> :
    tab === "monitoring" ? <ReplayWorkspace key={`${workspaceId}/${jobId || ""}`} workspaceId={workspaceId!} datasets={datasets} initialDatasetId={jobId} /> :
    tab === "sensor-health" ? <SensorHealthWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} diagnosticId={jobId} onChanged={refresh} /> :
    tab === "control" ? <Suspense fallback={<p>Loading tank model…</p>}><ControlWorkspace key={workspaceId} workspaceId={workspaceId!} experimentId={jobId} onSaved={d=>{setSelected(d.id);refresh();}}/></Suspense> :
    tab === "calibration" ? <Suspense fallback={<p>Loading calibration workspace…</p>}><CalibrationWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets.filter(dataset => !dataset.metadata.processRun)} runId={jobId} initialDatasetId={routeContext.datasetId} experimentId={query.has("plantRun") ? undefined : routeContext.experimentId} /></Suspense> :
    tab === "live" ? <LiveWorkspace key={workspaceId} workspaceId={workspaceId!} sessionId={jobId} onDataset={dataset => { setSelected(dataset.id); refresh(); }} /> :
    tab === "safety" ? <Suspense fallback={<p role="status">Loading safety workspace…</p>}><SafetyWorkspace key={`${workspaceId}/${routeContext.datasetId || ""}`} workspaceId={workspaceId!} datasets={datasets} initialDatasetId={routeContext.datasetId} assessmentId={jobId} onDataset={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "sensor-placement" ? <Suspense fallback={<p role="status">Loading</p>}><SensorPlacementWorkspace key={workspaceId} workspaceId={workspaceId!} runId={jobId} onChanged={refresh} /></Suspense> :
    tab === "reachability" ? <Suspense fallback={<p>Opening recovery workspace…</p>}><ReachabilityWorkspace key={workspaceId + "/" + (jobId || "")} workspaceId={workspaceId!} studyId={jobId} onDataset={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "experiments" ? <ExperimentWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} experimentId={jobId} initialDatasetId={path[4]} initialSignals={routeContext.signals} onChanged={refresh} /> :
    tab === "regimes" ? <Suspense fallback={<p role="status">Opening regime monitoring…</p>}><RegimeWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} section={jobId} itemId={path[4]} intervalIndex={path[5] === undefined ? undefined : Number(path[5])} /></Suspense> :
    tab === "alarms" ? <Suspense fallback={<p>Opening alarm session…</p>}><AlarmWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} jobs={jobs} sessionId={jobId} /></Suspense> :
    tab === "maintenance" ? <Suspense fallback={<p role="status">Opening Predictive Maintenance…</p>}><PrognosticWorkspace key={`${workspaceId}/${jobId || ""}/${search}`} workspaceId={workspaceId!} datasets={datasets} sessionId={jobId} initialDatasetId={routeContext.datasetId} benchmarkScenario={routeContext.benchmarkScenario} onGenerated={dataset => { setSelected(dataset.id); refresh(); }} /></Suspense> :
    tab === "resilience" ? <Suspense fallback={<p role="status">Opening resilience workspace…</p>}><ResilienceWorkspace key={workspaceId} workspaceId={workspaceId!} section={jobId} recordId={path[4]} caseId={path[5]} onExport={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "experiment-designs" ? <Suspense fallback={<p role="status">Opening input designs…</p>}><ExperimentDesign key={`${workspaceId}/${jobId || ""}`} workspaceId={workspaceId!} experimentId={jobId} onPublished={refresh} /></Suspense> :
    tab === "transformations" ? <TransformationWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} definitionId={jobId} initialSignalIds={path[4]} onGenerated={dataset => { setSelected(dataset.id); refresh(); }} /> :
    dataMode ? <SignalWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} jobs={jobs} mode={dataMode} initialSignalIds={jobId} initialDatasetId={routeContext.datasetId} initialRange={routeContext.range} onChanged={refresh} onAnalyze={(datasetId, signals, range) => {
      setSelected(datasetId); setPreferences(p => ({ ...p, [datasetId]: signals })); go(withPlantRun(analysisPath(workspaceId!, datasetId, signals, range)));
    }} /> : tab === "tep" ? <TEPWorkspace workspaceId={workspaceId!} search={search} onChanged={refresh} /> : tab === "incidents" ? <IncidentsPage workspaceId={workspaceId!} incidentId={jobId} datasets={datasets} jobs={jobs} /> :
    (tab === "simulations" || tab === "models") ? <Suspense fallback={<p>Opening process simulator…</p>}><ModelWorkspace key={workspaceId} workspaceId={workspaceId!} simulationId={tab === "simulations" ? jobId : undefined} runId={path[4] === "window" ? undefined : path[4]} initialWindow={path[4] === "window" ? { windowStart: Number(path[5]), asOf: Number(path[6]), hypothesis: path[7] } : undefined} onSaved={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "estimations" ? <Suspense fallback={<p>Computing or opening estimation…</p>}><EstimationWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets.filter(dataset => !dataset.metadata.processRun)} runId={jobId} onSaved={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "history" ? <HistoryPage jobs={jobs} datasets={datasets} workspaceId={workspaceId!} /> :
    tab === "analysis" ? <AnalysisPage key={workspaceId} workspaceId={workspaceId!} datasets={datasets} selected={selected} setSelected={setSelected} preferences={preferences} jobId={jobId} initialDatasetId={routeContext.datasetId} initialSignals={routeContext.signals} initialRange={routeContext.range} intervalIndex={path[4] === undefined ? undefined : Number(path[4])} refresh={refresh} /> :
    <DatasetPage key={`${jobId || selected}/${search}`} range={routeContext.range} search={search} workspaceId={workspaceId!} datasetId={jobId} datasets={datasets} onImport={(dataset, open) => {
      setDatasets(previous => [dataset, ...previous.filter(d => d.id !== dataset.id)]);
      if (open) {
        setSelected(dataset.id); go(`workspaces/${workspaceId}/datasets/${dataset.id}`);
      }
      refresh();
    }} selected={selected} setSelected={id => { setSelected(id); go(`workspaces/${workspaceId}/datasets/${id}`); }} preferences={preferences} setPreferences={(id, signals) => setPreferences(p => ({ ...p, [id]: signals }))} />;
  const originRun = query.get("plantRun");
  const investigationLinks = originRun || (query.has("incident") && query.has("analysis") && query.has("experiment")) ? (
    <nav className="ws-inline ws-investigation-nav" aria-label="Plant investigation">
      <a className="ws-link" href={`#/workspaces/${workspaceId}/plants${originRun ? "/" + encodeURIComponent(originRun) : ""}`}>← Plant run</a>
      {([["datasets", "dataset", "Measurements"], ["analysis", "analysis", "Detection"],
        ["experiments", "experiment", "Experiment"], ["incidents", "incident", "Incident"]] as const)
        .filter(([section, key]) => section !== tab && query.get(key)).map(([section, key, label]) => <a key={key} className="ws-link"
          href={`#/workspaces/${workspaceId}/${section}/${encodeURIComponent(query.get(key)!)}?${query}`}>{label}</a>)}
    </nav>) : null;
  const activeTab = tab === "simulations" ? "models" : tab;
  const currentDataset = datasets.find(d => d.id === ((tab === "datasets" ? jobId : undefined) || routeContext.datasetId || selected));
  function workspaceRoute(key: string) {
    const base = `workspaces/${workspaceId}/${key}`;
    if (key === "plants" && originRun) return `${base}/${encodeURIComponent(originRun)}`;
    if (originRun && ["datasets", "analysis", "experiments", "incidents"].includes(key)) {
      const record = query.get(key === "analysis" ? key : key.slice(0, -1));
      if (record) return `${base}/${encodeURIComponent(record)}?${query}`;
    }
    if (!currentDataset) return base;
    if (key === "datasets" || (key === "monitoring" && !currentDataset.metadata.transformation)) return `${base}/${currentDataset.id}${originRun ? `?${query}` : ""}`;
    if (key === "experiments") {
      const signals = preferences[currentDataset.id] || [];
      const query = new URLSearchParams(signals.map(signal => ["signal", signal]));
      return `${base}/new/${currentDataset.id}${signals.length ? `?${query}` : ""}`;
    }
    if (["maintenance", "safety"].includes(key)) return `${base}?${originRun ? query : new URLSearchParams({ dataset: currentDataset.id })}`;
    if (key === "calibration" && !currentDataset.metadata.processRun && !originRun) return `${base}?dataset=${currentDataset.id}`;
    return originRun ? `${base}?${query}` : base;
  }
  return <div className="ws-shell">
    <header className="ws-header">
      <a className="ws-brand" href="#/" aria-label="L5 home"><b>L5</b></a>
      <nav aria-label="Application">
        <a href="#/" className="ws-active">Workspaces</a>
      </nav>
    </header>
    {workspaceId ? <div className="ws-layout"><aside className="ws-sidebar">
      <a href="#/" className="ws-back">← All workspaces</a>
      <h2>{workspace?.name || "Opening…"}</h2>
      <label className="ws-mobile-navigation">Workspace section
        <select value={activeTab} onChange={event => go(workspaceRoute(event.target.value))}>
          {workspaceNavigation.map(([group, items]) => <optgroup key={group} label={group}>
            {items.map(([key, title]) => <option key={key} value={key}>{title}</option>)}
          </optgroup>)}
        </select>
      </label>
      <nav aria-label="Workspace">{workspaceNavigation.map(([group, items]) => <section key={group}>
        <h3>{group}</h3>
        {items.map(([key, title]) => {
          const active = key === activeTab;
          return <a key={key} className={active ? "ws-active" : ""}
            href={`#/${workspaceRoute(key)}`}
            aria-current={active ? "page" : undefined}>{title}</a>;
        })}
      </section>)}</nav>
    </aside>
      <main className="ws-main"><ErrorText error={error} />{investigationLinks}{content}</main>
    </div> : <><div className="ws-home-error"><ErrorText error={error} />{error && <button className="ws-outlined" onClick={refresh}>Reconnect</button>}</div>{loading ? <main className="ws-main" role="status">Loading workspaces…</main> : <WorkspaceHome workspaces={workspaces} refresh={refresh} />}</>}
  </div>;
}
