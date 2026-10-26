import { errorMessage } from "../i18n/errors";
import { LanguageSwitch, t as tr, useLocale } from "../i18n";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { analysisPath, api, go, message } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { ResultView } from "./Results";
import { AlgorithmControls } from "./AlgorithmControls";
import { AnalysisComparison } from "./AnalysisComparison";
import { IncidentsPage } from "./Incidents";
import { SignalWorkspace } from "./SignalWorkspace";
import { TransformationWorkspace, TransformationLineage } from "./TransformationWorkspace";
import { TEPWorkspace, ExternalProvenance } from "./TEPWorkspace";
import { ExperimentWorkspace } from "./ExperimentWorkspace";
const ModelWorkspace = lazy(() => import("./ModelWorkspace").then(m => ({ default: m.ModelWorkspace })));
import { dateLabel, number, signalLabel, timeLabel, type AnalysisResult, type Config, type Dataset, type Job, type Metadata, type Series, type Signal, type Workspace } from "./types";
import "./workspace.css";

function ErrorText({ error }: { error: string }) {
  useLocale(); return error ? <p className="ws-error" role="alert">{errorMessage(error)}</p> : null; }
function Empty({ title, children }: { title: string; children: ReactNode }) {
  useLocale(); return <div className="ws-empty"><span className="ws-empty-icon">⌗</span><h2>{title}</h2><p>{children}</p></div>; }
function Stats({ metadata }: { metadata: Metadata }) {
  useLocale();
  return <div className="ws-stats"><div><strong>{metadata.rowCount.toLocaleString()}</strong><span>{tr("samples")}</span></div><div><strong>{metadata.columns.length}</strong><span>{tr("numeric signals")}</span></div><div><strong>{metadata.missingCount.toLocaleString()}</strong><span>{tr("missing values")}</span></div><div><strong>{number(metadata.time.end - metadata.time.start)} s</strong><span>{tr("duration")}</span></div></div>;
}

function SignalPicker({ columns, selected, onChange, title = tr("Analysis signals") }: { columns: Signal[]; selected: string[]; onChange: (signals: string[]) => void; title?: string }) {
  useLocale();
  const [search, setSearch] = useState("");
  return <fieldset className="ws-signal-picker"><legend>{title} <span className="ws-muted">{selected.length} / {columns.length}</span></legend>
    <div className="ws-inline"><input aria-label={tr("Filter {0}", {0: title.toLowerCase()})} placeholder={tr("Filter signals…")} value={search} onChange={e => setSearch(e.target.value)} /><button type="button" onClick={() => onChange(columns.map(c => c.name))}>{tr("Select all")}</button><button type="button" onClick={() => onChange([])}>{tr("Clear")}</button></div>
    <div className="ws-signal-list">{columns.filter(c => `${c.name} ${c.displayName}`.toLowerCase().includes(search.toLowerCase())).map(c => <label key={c.name}><input type="checkbox" checked={selected.includes(c.name)} onChange={e => onChange(e.target.checked ? [...selected, c.name] : selected.filter(s => s !== c.name))} /><span>{signalLabel(c)}</span>{c.missing > 0 && <small>{c.missing}{" "}{tr("missing")}</small>}</label>)}</div>
  </fieldset>;
}

function WorkspaceHome({ workspaces, refresh }: { workspaces: Workspace[]; refresh: () => void }) {
  useLocale();
  const [name, setName] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [manage, setManage] = useState<Workspace | null>(null), [newName, setNewName] = useState(""), [deleting, setDeleting] = useState(false);
  async function create(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const workspace = await api<Workspace>("/workspaces", { name }); refresh(); go(`workspaces/${workspace.id}/datasets`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function update(e: FormEvent) {
    e.preventDefault(); if (!manage) return; setBusy(true); setError("");
    try { await api(`/workspaces/${manage.id}`, deleting ? undefined : { name: newName }, deleting ? "DELETE" : "PATCH"); setManage(null); refresh(); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <main className="ws-main ws-home">
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("YOUR DATA / YOUR INVESTIGATION")}</div><h1>{tr("Workspaces")}<span className="ws-accent">.</span></h1><p>{tr("Import process data. Establish normal. Find what changed.")}</p></div><span className="ws-badge">{tr("LOCAL · PERSISTENT")}</span></div>
    <form className="ws-create" onSubmit={create}><label htmlFor="workspace-name">{tr("Start an analysis project")}</label><div className="ws-inline"><input id="workspace-name" placeholder={tr("e.g. Reactor 02 · October campaign")} maxLength={160} value={name} onChange={e => setName(e.target.value)} required /><button className="ws-primary" disabled={busy || !name.trim()}>{tr("Create workspace ↗")}</button></div></form>
    <ErrorText error={error} />
    <div className="ws-section-heading"><h2>{tr("Your projects")}</h2><span className="ws-muted">{tr(workspaces.length === 1 ? "{0} workspace" : "{0} workspaces", {0: workspaces.length})}</span></div>
    {workspaces.length === 0 ? <Empty title={tr("A workspace starts with your data")}>{tr("Create a project above, then import a CSV. Datasets and completed analyses are saved on this machine.")}</Empty> : <div className="ws-projects">{workspaces.map((workspace, i) => <article className="ws-project" key={workspace.id}>
      <div className="ws-inline ws-between"><span className="ws-kicker">{tr("PROJECT")}{" "}{String(i + 1).padStart(2, "0")}</span><button aria-label={tr("Manage {0}", {0: workspace.name})} onClick={() => { setManage(workspace); setNewName(workspace.name); setDeleting(false); }}>{tr("Manage")}</button></div>
      <a href={`#/workspaces/${workspace.id}/datasets`}><h2>{workspace.name}</h2><p>{workspace.dataset_count || 0}{" "}{tr("datasets")}{" "}<span> / </span> {workspace.analysis_count || 0}{" "}{tr("analyses")}</p><div className="ws-inline ws-between"><small>{tr("Updated")}{" "}{dateLabel(workspace.updated_at)}</small><span className="ws-accent">{tr("Open workspace ↗")}</span></div></a>
    </article>)}</div>}
    <a className="ws-examples-card" href="#/examples"><div><span className="ws-kicker">{tr("BUILT-IN EXAMPLES")}</span><h2>{tr("Explore TripLens")}</h2><p>{tr("12 fault templates · runtime investigation · intervention search")}</p></div><span>{tr("Open examples ↗")}</span></a>
    {manage && <div className="ws-modal-backdrop"><form className="ws-modal" role="dialog" aria-modal="true" aria-label={tr("Manage workspace")} onSubmit={update}><h2>{deleting ? tr("Delete this workspace?") : tr("Manage workspace")}</h2>
      {deleting ? <p>“{manage.name}{tr("”, its datasets and analysis history will be permanently removed from this machine.")}</p> : <label>{tr("Workspace name")}<input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={160} autoFocus /></label>}
      <ErrorText error={error} /><div className="ws-inline"><button type="button" onClick={() => setManage(null)}>{tr("Cancel")}</button>{!deleting && <button type="button" className="ws-danger" onClick={() => setDeleting(true)}>{tr("Delete workspace")}</button>}<button disabled={busy} className={deleting ? "ws-danger ws-outlined" : "ws-primary"}>{deleting ? tr("Delete permanently") : tr("Save name")}</button></div>
    </form></div>}
  </main>;
}

export function ImportDataset({ workspaceId, onImport }: { workspaceId: string; onImport: (dataset: Dataset) => void }) {
  useLocale();
  const fileInput = useRef<HTMLInputElement>(null);
  const [csv, setCsv] = useState(""), [filename, setFilename] = useState(""), [name, setName] = useState("");
  const [timeColumn, setTimeColumn] = useState("__auto"), [timeKind, setTimeKind] = useState("auto"), [timeUnit, setTimeUnit] = useState("seconds"), [interval, setInterval] = useState("1");
  const [timezone, setTimezone] = useState("UTC");
  const [preview, setPreview] = useState<{ metadata: Metadata; series: Series } | null>(null), [columns, setColumns] = useState<string[]>([]);
  const [error, setError] = useState(""), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const options = { ...(timeColumn === "__auto" ? {} : { timeColumn: timeColumn === "__generated" ? null : timeColumn }), timeKind, timeUnit, timezone, sampleInterval: Number(interval) };
  const optionKey = JSON.stringify(options);
  useEffect(() => {
    setPreview(null); setError("");
    if (!csv) return;
    const controller = new AbortController(); setLoading(true);
    const timer = setTimeout(() => {
      api<{ metadata: Metadata; series: Series }>("/datasets/preview", { csv, ...JSON.parse(optionKey) }, "POST", controller.signal)
        .then(data => { setPreview(data); setColumns(data.metadata.sourceColumns); })
        .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [csv, optionKey]);
  async function chooseFile(file?: File) {
    if (!file) return;
    setFilename(file.name); setName(file.name); setColumns([]); setCsv(""); setError(""); setTimeColumn("__auto"); setTimeKind("auto"); setTimeUnit("seconds"); setTimezone("UTC");
    try {
      const data = await file.arrayBuffer();
      let text: string;
      try { text = new TextDecoder("utf-8", { fatal: true }).decode(data); }
      catch { text = new TextDecoder("gb18030").decode(data); }
      setCsv(text);
    } catch (e) { setError(message(e)); }
  }
  async function save(e: FormEvent) {
    e.preventDefault(); setSaving(true); setError("");
    try { onImport(await api<Dataset>(`/workspaces/${workspaceId}/datasets`, { csv, filename, name, ...options })); }
    catch (e) { setError(message(e)); } finally { setSaving(false); }
  }
  return <form className="ws-import ws-panel" onSubmit={save}>
    <div className="ws-section-heading"><h2>{tr("Import a CSV")}</h2><span className="ws-kicker">{tr("01 / DATA IN")}</span></div>
    <div className="ws-file"><input ref={fileInput} aria-label={tr("Choose CSV file")} type="file" hidden accept=".csv,.tsv,.txt,text/csv" onChange={e => void chooseFile(e.target.files?.[0])} />
      <div className="ws-inline"><button type="button" className="ws-file-button" onClick={() => fileInput.current?.click()} aria-describedby="csv-filename csv-help">{tr("Choose file")}</button><span id="csv-filename" className="ws-file-name" aria-live="polite">{filename || tr("No file selected")}</span></div>
      <span id="csv-help">{tr("CSV / TSV · named numeric signals")}</span>
    </div>
    {csv && <>
      <div className="ws-form-grid"><label>{tr("Dataset name")}<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} /></label><label>{tr("Time axis")}<select value={timeColumn} onChange={e => setTimeColumn(e.target.value)}><option value="__auto">{tr("Auto-detect time column")}</option><option value="__generated">{tr("Generate from sampling interval")}</option>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></label>
        {timeColumn === "__generated" ? <label>{tr("Sampling interval (seconds)")}<input type="number" min="0.000001" step="any" value={interval} onChange={e => setInterval(e.target.value)} required /></label> : <><label>{tr("Time format")}<select value={timeKind} onChange={e => setTimeKind(e.target.value)}><option value="auto">{tr("Auto · numeric or date/time")}</option><option value="numeric">{tr("Relative numeric time")}</option><option value="datetime">{tr("ISO date / timestamp")}</option><option value="unix">{tr("Unix epoch time")}</option></select></label><label>{tr("Numeric time unit")}<select value={timeUnit} onChange={e => setTimeUnit(e.target.value)}>{["seconds", "milliseconds", "minutes", "hours"].map(v => <option key={v}>{v}</option>)}</select></label>{(timeKind === "auto" || timeKind === "datetime") && <label>{tr("Timezone for dates without timezone")}<input value={timezone} onChange={e => setTimezone(e.target.value)} placeholder={tr("UTC or Asia/Shanghai")} /></label>}</>}
      </div>
      {loading && <p role="status">{tr("Parsing and previewing CSV…")}</p>}
      {preview && <><Stats metadata={preview.metadata} /><p className="ws-muted">{tr("Time interpretation:")}{" "}{tr(preview.metadata.time.kind)} · {preview.metadata.time.sourceUnit || preview.metadata.time.naiveTimezone || "seconds"} · {preview.metadata.time.column || "generated"} · {timeLabel(preview.metadata.time, preview.metadata.time.start)} → {timeLabel(preview.metadata.time, preview.metadata.time.end)}</p><p className="ws-muted">{tr("Numeric time is relative unless you explicitly choose Unix epoch time. Relative sources are independent until a time relationship is saved.")}</p>
        {preview.metadata.notes.map(note => <p key={note} className="ws-notice">{note}</p>)}
        <details><summary>{tr("Inspect columns and sample rows")}</summary><div className="ws-table-scroll"><table><thead><tr><th>{tr("Signal")}</th><th>{tr("Minimum")}</th><th>{tr("Maximum")}</th><th>{tr("Missing")}</th></tr></thead><tbody>{preview.metadata.columns.map(c => <tr key={c.name}><td>{c.name}</td><td>{c.min == null ? "—" : number(c.min)}</td><td>{c.max == null ? "—" : number(c.max)}</td><td>{c.missing}</td></tr>)}</tbody></table><table><thead><tr><th>{tr("Time (s)")}</th>{Object.keys(preview.series.values).map(s => <th key={s}>{s}</th>)}</tr></thead><tbody>{preview.series.times.slice(0, 5).map((t, i) => <tr key={i}><td>{number(t)}</td>{Object.keys(preview.series.values).map(s => <td key={s}>{preview.series.values[s][i] == null ? tr("missing") : number(preview.series.values[s][i]!)}</td>)}</tr>)}</tbody></table></div>{preview.metadata.ignoredColumns.length > 0 && <p className="ws-muted">{tr("Non-numeric columns:")}{" "}{preview.metadata.ignoredColumns.join(", ")}</p>}</details>
        <Plot times={preview.series.times} values={Object.values(preview.series.values)[0]} title={preview.metadata.columns[0].name} axis={preview.metadata.time} />
      </>}
      <ErrorText error={error} /><button className="ws-primary" disabled={!preview || loading || saving || !name.trim()}>{saving ? tr("Saving dataset…") : tr("Import and save dataset ↗")}</button>
    </>}
    {!csv && <ErrorText error={error} />}
  </form>;
}

function DatasetPage({ workspaceId, datasets, refresh, selected, setSelected, preferences, setPreferences }: {
  workspaceId: string; datasets: Dataset[]; refresh: () => void; selected: string; setSelected: (id: string) => void;
  preferences: Record<string, string[]>; setPreferences: (id: string, signals: string[]) => void;
}) {
  useLocale();
  const [importing, setImporting] = useState(false);
  const dataset = datasets.find(d => d.id === selected) || datasets[0];
  const chosen = dataset ? preferences[dataset.id] ?? dataset.metadata.columns.slice(0, 4).map(c => c.name) : [];
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("01 / DATASETS")}</div><h1>{tr("Your process data")}<span className="ws-accent">.</span></h1><p>{tr("Bring a new dataset into this workspace. Every column keeps its own meaning.")}{" "}<a className="ws-link" href={`#/workspaces/${workspaceId}/models`}>{tr("Generate process data ↗")}</a> · <a className="ws-link" href={`#/workspaces/${workspaceId}/tep`}>{tr("Import TEP benchmark ↗")}</a></p></div>{datasets.length > 0 && <button className="ws-primary" onClick={() => setImporting(!importing)}>{importing ? tr("Close import") : tr("+ Import CSV")}</button>}</div>
    {(importing || datasets.length === 0) && <ImportDataset workspaceId={workspaceId} onImport={d => { setSelected(d.id); setImporting(false); refresh(); }} />}
    {dataset && <>
      <div className="ws-section-heading"><h2>{tr("Saved datasets")}{" "}<span className="ws-muted">/ {datasets.length}</span></h2><label className="ws-inline">{tr("Dataset")}<select aria-label={tr("Saved dataset")} value={dataset.id} onChange={e => setSelected(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div>
      <section className="ws-panel"><h2>{dataset.name}</h2><Stats metadata={dataset.metadata} /><p className="ws-muted">{timeLabel(dataset.metadata.time, dataset.metadata.time.start)} → {timeLabel(dataset.metadata.time, dataset.metadata.time.end)}{dataset.metadata.time.origin && tr(" · Window inputs use seconds since the first timestamp.")}</p>
        <SignalPicker columns={dataset.metadata.columns} selected={chosen} onChange={signals => setPreferences(dataset.id, signals)} title={tr("Signals to plot and analyze")} />
        <SignalPlots dataset={dataset} signals={chosen} />
        <TransformationLineage dataset={dataset} /><ExternalProvenance dataset={dataset} />
        <div className="ws-dataset-actions"><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/new/${dataset.id}?${new URLSearchParams(chosen.map(signal => ["signal", signal]))}`}>{tr("Create a multi-algorithm experiment from this dataset ↗")}</a>
        {dataset.metadata.model && <a className="ws-primary" href={`#/workspaces/${workspaceId}/simulations/${dataset.metadata.model.simulationId}`}>{tr("Open process investigation & interventions ↗")}</a>}</div>
        <div className="ws-inline ws-between"><a className="ws-link" href={`#/workspaces/${workspaceId}/explorer/${dataset.metadata.columns.filter(c => chosen.includes(c.name)).map(c => c.id).filter(Boolean).join(",")}`}>{tr("Open Signal Explorer ↗")}</a><span className="ws-muted">{tr("Original CSV and numeric data are saved locally.")}</span><button className="ws-primary" onClick={() => { setPreferences(dataset.id, chosen); go(analysisPath(workspaceId, dataset.id, chosen)); }} disabled={!chosen.length}>{tr("Configure analysis ↗")}</button></div>
      </section>
    </>}
  </>;
}

export function AnalysisPage({ workspaceId, datasets, selected, setSelected, preferences, jobId, refresh, intervalIndex, initialRange, initialDatasetId, initialSignals }: {
  workspaceId: string; datasets: Dataset[]; selected: string; setSelected: (id: string) => void; preferences: Record<string, string[]>; jobId?: string; refresh: () => void; intervalIndex?: number; initialRange?: [number, number]; initialDatasetId?: string; initialSignals?: string[];
}) {
  useLocale();
  const dataset = datasets.find(d => d.id === (initialDatasetId || selected)) || datasets[0];
  const [config, setConfig] = useState<Config | null>(null), [result, setResult] = useState<AnalysisResult | null>(null);
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
    if (!jobId || result?.id === jobId) return;
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null); setConfig(null);
    api<AnalysisResult>(`/analyses/${jobId}`, undefined, "GET", controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.workspaceId !== workspaceId) throw new Error(tr("Analysis belongs to another workspace."));
      setResult(data); setConfig(data.config); setSelected(data.datasetId);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [jobId]);
  useEffect(() => {
    if (jobId && result?.id === jobId) resultPanel.current?.scrollIntoView({ behavior: "instant", block: "start" });
  }, [jobId, result?.id]);
  async function run(e: FormEvent) {
    e.preventDefault(); if (!config) return; const request = context.current; setBusy(true); setError("");
    try { const data = await api<AnalysisResult>(`/workspaces/${workspaceId}/analyses`, config); if (request !== context.current) return; setResult(data); refresh(); go(`workspaces/${workspaceId}/analysis/${data.id}`); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  function set<K extends keyof Config>(key: K, value: Config[K]) { setConfig(c => c ? { ...c, [key]: value } : c); }
  if (!dataset) return <Empty title={tr("Import data to start analyzing")}><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>{tr("Go to datasets →")}</a></Empty>;
  const resultDataset = result && datasets.find(d => d.id === result.datasetId);
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("02 / ANALYSIS ENGINE")}</div><h1>{tr("Find what changed")}<span className="ws-accent">.</span></h1><p>{tr("Fit a normal baseline, then score a later window of your measurements.")}</p></div><span className="ws-badge">{tr("FULL-RESOLUTION COMPUTATION")}</span></div>
    {loading ? <p role="status">{tr("Opening saved analysis…")}</p> : config?.training ? <section className="ws-panel"><h2>{tr("Saved independent dataset analysis")}</h2><p>{tr("Review the normal training, calibration and test sources with the saved result below.")}</p><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${result?.experiment?.experimentId || "new"}`}>{tr("Configure independent sources and rerun in Experiments ↗")}</a></section> : config && <form className="ws-panel ws-analysis-form" onSubmit={run}>
      <div className="ws-form-grid"><label>{tr("Dataset")}<select value={dataset.id} onChange={e => { const next = datasets.find(d => d.id === e.target.value)!; setSelected(next.id); go(analysisPath(workspaceId, next.id, preferences[next.id] ?? next.metadata.columns.map(c => c.name))); }}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label>{tr("Analysis name (optional)")}<input maxLength={160} value={config.name || ""} onChange={e => set("name", e.target.value)} placeholder={tr("e.g. Temperature excursion review")} /></label></div>
      <SignalPicker columns={dataset.metadata.columns} selected={config.signals} onChange={signals => setConfig({ ...config, signals, requiredSignals:config.requiredSignals?.filter(s=>signals.includes(s)), stress:{ ...config.stress, missingSignals:config.stress?.missingSignals?.filter(s=>signals.includes(s)) } })} />
      <div className="ws-window-grid">{(["baselineRange", "analysisRange"] as const).map(key => <fieldset key={key}><legend>{key === "baselineRange" ? tr("Normal baseline · assumed healthy") : tr("Analysis window · target data")}</legend><div className="ws-form-grid"><label>{key === "baselineRange" ? tr("Baseline start (s)") : tr("Analysis start (s)")}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][0]} onChange={e => set(key, [Number(e.target.value), config[key][1]])} required /></label><label>{key === "baselineRange" ? tr("Baseline end (s)") : tr("Analysis end (s)")}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][1]} onChange={e => set(key, [config[key][0], Number(e.target.value)])} required /></label></div></fieldset>)}</div>
      <p className="ws-notice">{tr("Choose a baseline you believe is normal, ending before the analysis window. Use at least 30 fit and 30 calibration observations; the fit fraction can be configured below.")}{dataset.metadata.time.origin && tr(" Times are elapsed seconds from {0}.", {0: timeLabel(dataset.metadata.time, 0)})}</p>
      <AlgorithmControls config={config} onChange={setConfig} />
      <ErrorText error={error} /><div className="ws-inline ws-between"><span className="ws-muted">{tr("Every completed run is saved automatically to History.")}</span><button className="ws-primary" disabled={busy || loading || !config.signals.length}>{busy ? tr("Computing and saving…") : result ? tr("Run again with these parameters ↗") : tr("Run analysis and save ↗")}</button></div>
    </form>}
    {!config && <ErrorText error={error} />}
    {result && resultDataset && <div ref={resultPanel} className="ws-result-anchor"><ResultView key={result.id} result={result} dataset={resultDataset} initialIntervalIndex={intervalIndex} signalPicker={(selected, onChange) => <SignalPicker title={tr("Raw signals in view")} columns={resultDataset.metadata.columns.filter(c => (result.config.signalMapping ? Object.values(result.config.signalMapping) : result.config.signals).includes(c.name))} selected={selected} onChange={onChange} />} /></div>}
  </>;
}

function HistoryPage({ jobs, datasets, workspaceId }: { jobs: Job[]; datasets: Dataset[]; workspaceId: string }) {
  useLocale();
  return <><div className="ws-page-title"><div><div className="ws-kicker">{tr("03 / HISTORY")}</div><h1>{tr("Every run, retained")}<span className="ws-accent">.</span></h1><p>{tr("Reopen a result or use its saved parameters for another analysis.")}</p></div><span className="ws-badge">{jobs.length}{" "}{tr("SAVED RUNS")}</span></div>
    {jobs.length > 1 && <AnalysisComparison jobs={jobs} datasets={datasets} />}
    {jobs.length === 0 ? <Empty title={tr("Your analyses will appear here")}><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis`}>{tr("Start an analysis →")}</a></Empty> : <div className="ws-history">{jobs.map(job => <a href={`#/workspaces/${workspaceId}/analysis/${job.id}`} className="ws-history-row" key={job.id}><div><span className="ws-kicker">{job.config.algorithm} / {dateLabel(job.created_at)}</span><h2>{job.name}</h2><p>{datasets.find(d => d.id === job.dataset_id)?.name} · {job.config.signals.length}{" "}{tr("signals ·")}{" "}{number(job.config.analysisRange[0])}–{number(job.config.analysisRange[1])} s</p></div><div><strong className={job.summary.flaggedSamples ? "ws-coral" : "ws-accent"}>{job.summary.flaggedSamples.toLocaleString()}{" "}{tr("flagged")}</strong><span>{tr("Open result ↗")}</span></div></a>)}</div>}
  </>;
}

export default function WorkspaceApp({ path, search = "" }: { path: string[]; search?: string }) {
  useLocale();
  const workspaceId = path[0] === "workspaces" ? path[1] : undefined, tab = path[2] || "datasets", jobId = path[3];
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]), [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]), [jobs, setJobs] = useState<Job[]>([]), [selected, setSelected] = useState("");
  const routeContext = useMemo(() => {
    const query = new URLSearchParams(search), start = query.get("start"), end = query.get("end");
    const range = start !== null && end !== null && Number.isFinite(Number(start)) && Number.isFinite(Number(end)) && Number(start) <= Number(end) ? [Number(start), Number(end)] as [number, number] : undefined;
    return { datasetId: query.get("dataset") || undefined, signals: query.getAll("signal"), range };
  }, [search]);
  const [preferences, setPreferences] = useState<Record<string, string[]>>({}), [error, setError] = useState(""), [loading, setLoading] = useState(true), [revision, setRevision] = useState(0);
  function refresh() { setRevision(v => v + 1); }
  useEffect(() => {
    const controller = new AbortController(); setError("");
    api<{ workspaces: Workspace[] }>("/workspaces", undefined, "GET", controller.signal).then(data => setWorkspaces(data.workspaces)).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted && !workspaceId) setLoading(false); });
    return () => controller.abort();
  }, [revision, workspaceId]);
  useEffect(() => { setWorkspace(null); setDatasets([]); setJobs([]); setSelected(""); setLoading(Boolean(workspaceId)); }, [workspaceId]);
  useEffect(() => { if (tab === "datasets" && jobId) setSelected(jobId); }, [tab, jobId]);
  useEffect(() => {
    if (tab === "analysis" && routeContext.datasetId) {
      setSelected(routeContext.datasetId);
      if (routeContext.signals.length) setPreferences(p => ({ ...p, [routeContext.datasetId!]: routeContext.signals }));
    }
  }, [tab, routeContext]);
  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController();
    Promise.all([api<Workspace>(`/workspaces/${workspaceId}`, undefined, "GET", controller.signal), api<{ datasets: Dataset[] }>(`/workspaces/${workspaceId}/datasets`, undefined, "GET", controller.signal), api<{ jobs: Job[] }>(`/workspaces/${workspaceId}/analyses`, undefined, "GET", controller.signal)])
      .then(([w, d, j]) => { if (controller.signal.aborted) return; setWorkspace(w); setDatasets(d.datasets); setJobs(j.jobs); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId, revision, tab === "history"]);
  const dataMode = tab === "signals" || tab === "quality" || tab === "explorer" ? tab : null;
  const content = loading ? <p role="status">{tr("Opening workspace…")}</p> : !workspace ? null :
    tab === "experiments" ? <ExperimentWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} experimentId={jobId} initialDatasetId={path[4]} initialSignals={routeContext.signals} onChanged={refresh} /> :
    tab === "transformations" ? <TransformationWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} definitionId={jobId} initialSignalIds={path[4]} onGenerated={dataset => { setSelected(dataset.id); refresh(); }} /> :
    dataMode ? <SignalWorkspace key={workspaceId} workspaceId={workspaceId!} datasets={datasets} jobs={jobs} mode={dataMode} initialSignalIds={jobId} onChanged={refresh} onAnalyze={(datasetId, signals, range) => {
      setSelected(datasetId); setPreferences(p => ({ ...p, [datasetId]: signals })); go(analysisPath(workspaceId!, datasetId, signals, range));
    }} /> : tab === "tep" ? <TEPWorkspace workspaceId={workspaceId!} search={search} onChanged={refresh} /> : tab === "incidents" ? <IncidentsPage workspaceId={workspaceId!} incidentId={jobId} datasets={datasets} jobs={jobs} /> :
    (tab === "simulations" || tab === "models") ? <Suspense fallback={<p>{tr("Opening process simulator…")}</p>}><ModelWorkspace key={workspaceId} workspaceId={workspaceId!} simulationId={tab === "simulations" ? jobId : undefined} runId={path[4] === "window" ? undefined : path[4]} initialWindow={path[4] === "window" ? { windowStart: Number(path[5]), asOf: Number(path[6]), hypothesis: path[7] } : undefined} onSaved={d => { setSelected(d.id); refresh(); }} /></Suspense> :
    tab === "history" ? <HistoryPage jobs={jobs} datasets={datasets} workspaceId={workspaceId!} /> :
    tab === "analysis" ? <AnalysisPage key={workspaceId} workspaceId={workspaceId!} datasets={datasets} selected={selected} setSelected={setSelected} preferences={preferences} jobId={jobId} initialDatasetId={routeContext.datasetId} initialSignals={routeContext.signals} initialRange={routeContext.range} intervalIndex={path[4] === undefined ? undefined : Number(path[4])} refresh={refresh} /> :
    <DatasetPage workspaceId={workspaceId!} datasets={datasets} refresh={refresh} selected={selected} setSelected={id => { setSelected(id); go(`workspaces/${workspaceId}/datasets/${id}`); }} preferences={preferences} setPreferences={(id, signals) => setPreferences(p => ({ ...p, [id]: signals }))} />;
  return <div className="ws-shell notranslate" translate="no">
    <header className="ws-header"><a className="ws-brand" href="#/"><b>L5</b><span>{tr("WORKSPACE")}</span><small>2.0</small></a><nav aria-label={tr("Application")}><a href="#/" className="ws-active">{tr("Workspaces")}</a><a href="#/examples">{tr("TripLens examples ↗")}</a></nav><span className="ws-connection"><i />{tr("LOCAL ENGINE")}</span><LanguageSwitch /></header>
    {workspaceId ? <div className="ws-layout"><aside className="ws-sidebar"><a href="#/" className="ws-back">{tr("← All workspaces")}</a><span className="ws-kicker">{tr("CURRENT PROJECT")}</span><h2>{workspace?.name || "Opening…"}</h2><nav aria-label={tr("Workspace")}>{[["datasets", "01", tr("Datasets"), datasets.length], ["signals", "02", tr("Signal catalog"), "↗"], ["quality", "03", tr("Data quality"), "↗"], ["explorer", "04", tr("Signal Explorer"), "↗"], ["transformations", "05", tr("Transformations"), "↗"], ["analysis", "06", tr("Analysis"), "↗"], ["experiments", "07", tr("Experiments"), "↗"], ["history", "08", tr("History"), jobs.length], ["models", "09", tr("Models"), "↗"], ["incidents", "10", tr("事件"), "↗"], ["tep", "11", tr("TEP case study"), "↗"]].map(([key, index, title, count]) => <a key={key} className={tab === key || key === "models" && tab === "simulations" ? "ws-active" : ""} href={`#/workspaces/${workspaceId}/${key}${key === "datasets" && selected ? `/${selected}` : ""}`} aria-current={tab === key || key === "models" && tab === "simulations" ? "page" : undefined}><span>{index}</span>{title}<small>{count}</small></a>)}</nav><div className="ws-sidebar-note">{tr("A durable place for your data and the questions you ask of it.")}</div></aside>
      <main className="ws-main"><ErrorText error={error} />{content}</main>
    </div> : <><div className="ws-home-error"><ErrorText error={error} />{error && <button className="ws-outlined" onClick={refresh}>{tr("Reconnect")}</button>}</div>{loading ? <main className="ws-main" role="status">{tr("Loading workspaces…")}</main> : <WorkspaceHome workspaces={workspaces} refresh={refresh} />}</>}
    <footer className="ws-footer"><span>{tr("L5 / OPEN INDUSTRIAL ANALYSIS")}</span><span>{tr("DATA → EXPERIMENT → EVIDENCE → INVESTIGATION")}</span></footer>
  </div>;
}
