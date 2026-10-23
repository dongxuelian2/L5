import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, go, message } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { ResultView } from "./Results";
import { dateLabel, number, timeLabel, type AnalysisResult, type Config, type Dataset, type Job, type Metadata, type Series, type Signal, type Workspace } from "./types";
import "./workspace.css";

function ErrorText({ error }: { error: string }) { return error ? <p className="ws-error" role="alert">{error}</p> : null; }
function Empty({ title, children }: { title: string; children: ReactNode }) { return <div className="ws-empty"><span className="ws-empty-icon">⌗</span><h2>{title}</h2><p>{children}</p></div>; }
function Stats({ metadata }: { metadata: Metadata }) {
  return <div className="ws-stats"><div><strong>{metadata.rowCount.toLocaleString()}</strong><span>samples</span></div><div><strong>{metadata.columns.length}</strong><span>numeric signals</span></div><div><strong>{metadata.missingCount.toLocaleString()}</strong><span>missing values</span></div><div><strong>{number(metadata.time.end - metadata.time.start)} s</strong><span>duration</span></div></div>;
}

function SignalPicker({ columns, selected, onChange, title = "Analysis signals" }: { columns: Signal[]; selected: string[]; onChange: (signals: string[]) => void; title?: string }) {
  const [search, setSearch] = useState("");
  return <fieldset className="ws-signal-picker"><legend>{title} <span className="ws-muted">{selected.length} / {columns.length}</span></legend>
    <div className="ws-inline"><input aria-label={`Filter ${title.toLowerCase()}`} placeholder="Filter signals…" value={search} onChange={e => setSearch(e.target.value)} /><button type="button" onClick={() => onChange(columns.map(c => c.name))}>Select all</button><button type="button" onClick={() => onChange([])}>Clear</button></div>
    <div className="ws-signal-list">{columns.filter(c => c.name.toLowerCase().includes(search.toLowerCase())).map(c => <label key={c.name}><input type="checkbox" checked={selected.includes(c.name)} onChange={e => onChange(e.target.checked ? [...selected, c.name] : selected.filter(s => s !== c.name))} /><span>{c.name}</span>{c.missing > 0 && <small>{c.missing} missing</small>}</label>)}</div>
  </fieldset>;
}

function WorkspaceHome({ workspaces, refresh }: { workspaces: Workspace[]; refresh: () => void }) {
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
    <div className="ws-page-title"><div><div className="ws-kicker">YOUR DATA / YOUR INVESTIGATION</div><h1>Workspaces<span className="ws-accent">.</span></h1><p>Import process data. Establish normal. Find what changed.</p></div><span className="ws-badge">LOCAL · PERSISTENT</span></div>
    <form className="ws-create" onSubmit={create}><label htmlFor="workspace-name">Start an analysis project</label><div className="ws-inline"><input id="workspace-name" placeholder="e.g. Reactor 02 · October campaign" maxLength={160} value={name} onChange={e => setName(e.target.value)} required /><button className="ws-primary" disabled={busy || !name.trim()}>Create workspace ↗</button></div></form>
    <ErrorText error={error} />
    <div className="ws-section-heading"><h2>Your projects</h2><span className="ws-muted">{workspaces.length} workspace{workspaces.length === 1 ? "" : "s"}</span></div>
    {workspaces.length === 0 ? <Empty title="A workspace starts with your data">Create a project above, then import a CSV. Datasets and completed analyses are saved on this machine.</Empty> : <div className="ws-projects">{workspaces.map((workspace, i) => <article className="ws-project" key={workspace.id}>
      <div className="ws-inline ws-between"><span className="ws-kicker">PROJECT {String(i + 1).padStart(2, "0")}</span><button aria-label={`Manage ${workspace.name}`} onClick={() => { setManage(workspace); setNewName(workspace.name); setDeleting(false); }}>Manage</button></div>
      <a href={`#/workspaces/${workspace.id}/datasets`}><h2>{workspace.name}</h2><p>{workspace.dataset_count || 0} datasets <span> / </span> {workspace.analysis_count || 0} analyses</p><div className="ws-inline ws-between"><small>Updated {dateLabel(workspace.updated_at)}</small><span className="ws-accent">Open workspace ↗</span></div></a>
    </article>)}</div>}
    <a className="ws-examples-card" href="#/examples"><div><span className="ws-kicker">BUILT-IN EXAMPLES</span><h2>Explore TripLens</h2><p>12 simulated incidents · evidence investigation · intervention search</p></div><span>Open examples ↗</span></a>
    {manage && <div className="ws-modal-backdrop"><form className="ws-modal" role="dialog" aria-modal="true" aria-label="Manage workspace" onSubmit={update}><h2>{deleting ? "Delete this workspace?" : "Manage workspace"}</h2>
      {deleting ? <p>“{manage.name}”, its datasets and analysis history will be permanently removed from this machine.</p> : <label>Workspace name<input value={newName} onChange={e => setNewName(e.target.value)} required maxLength={160} autoFocus /></label>}
      <ErrorText error={error} /><div className="ws-inline"><button type="button" onClick={() => setManage(null)}>Cancel</button>{!deleting && <button type="button" className="ws-danger" onClick={() => setDeleting(true)}>Delete workspace</button>}<button disabled={busy} className={deleting ? "ws-danger ws-outlined" : "ws-primary"}>{deleting ? "Delete permanently" : "Save name"}</button></div>
    </form></div>}
  </main>;
}

export function ImportDataset({ workspaceId, onImport }: { workspaceId: string; onImport: (dataset: Dataset) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [csv, setCsv] = useState(""), [filename, setFilename] = useState(""), [name, setName] = useState("");
  const [timeColumn, setTimeColumn] = useState("__auto"), [timeKind, setTimeKind] = useState("auto"), [timeUnit, setTimeUnit] = useState("seconds"), [interval, setInterval] = useState("1");
  const [preview, setPreview] = useState<{ metadata: Metadata; series: Series } | null>(null), [columns, setColumns] = useState<string[]>([]);
  const [error, setError] = useState(""), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const options = { ...(timeColumn === "__auto" ? {} : { timeColumn: timeColumn === "__generated" ? null : timeColumn }), timeKind, timeUnit, sampleInterval: Number(interval) };
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
    setFilename(file.name); setName(file.name); setColumns([]); setCsv(""); setError(""); setTimeColumn("__auto");
    try {
      if (file.size > 45 * 1024 * 1024) throw new Error("Choose a CSV smaller than 45 MiB.");
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
    <div className="ws-section-heading"><h2>Import a CSV</h2><span className="ws-kicker">01 / DATA IN</span></div>
    <div className="ws-file"><input ref={fileInput} aria-label="Choose CSV file" type="file" hidden accept=".csv,.tsv,.txt,text/csv" onChange={e => void chooseFile(e.target.files?.[0])} />
      <div className="ws-inline"><button type="button" className="ws-file-button" onClick={() => fileInput.current?.click()} aria-describedby="csv-filename csv-help">Choose file</button><span id="csv-filename" className="ws-file-name" aria-live="polite">{filename || "No file selected"}</span></div>
      <span id="csv-help">CSV / TSV · named numeric signals · up to 45 MiB</span>
    </div>
    {csv && <>
      <div className="ws-form-grid"><label>Dataset name<input value={name} onChange={e => setName(e.target.value)} required maxLength={160} /></label><label>Time axis<select value={timeColumn} onChange={e => setTimeColumn(e.target.value)}><option value="__auto">Auto-detect time column</option><option value="__generated">Generate from sampling interval</option>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></label>
        {timeColumn === "__generated" ? <label>Sampling interval (seconds)<input type="number" min="0.000001" step="any" value={interval} onChange={e => setInterval(e.target.value)} required /></label> : <><label>Time format<select value={timeKind} onChange={e => setTimeKind(e.target.value)}><option value="auto">Auto · numeric or date/time</option><option value="numeric">Numeric</option><option value="datetime">Date / timestamp</option></select></label><label>Numeric time unit<select value={timeUnit} onChange={e => setTimeUnit(e.target.value)}>{["seconds", "milliseconds", "minutes", "hours"].map(v => <option key={v}>{v}</option>)}</select></label></>}
      </div>
      {loading && <p role="status">Parsing and previewing CSV…</p>}
      {preview && <><Stats metadata={preview.metadata} /><p className="ws-muted">Time: {preview.metadata.time.column || "generated"} · {timeLabel(preview.metadata.time, preview.metadata.time.start)} → {timeLabel(preview.metadata.time, preview.metadata.time.end)}</p>
        {preview.metadata.notes.map(note => <p key={note} className="ws-notice">{note}</p>)}
        <details><summary>Inspect columns and sample rows</summary><div className="ws-table-scroll"><table><thead><tr><th>Signal</th><th>Minimum</th><th>Maximum</th><th>Missing</th></tr></thead><tbody>{preview.metadata.columns.map(c => <tr key={c.name}><td>{c.name}</td><td>{number(c.min)}</td><td>{number(c.max)}</td><td>{c.missing}</td></tr>)}</tbody></table><table><thead><tr><th>Time (s)</th>{Object.keys(preview.series.values).map(s => <th key={s}>{s}</th>)}</tr></thead><tbody>{preview.series.times.slice(0, 5).map((t, i) => <tr key={i}><td>{number(t)}</td>{Object.keys(preview.series.values).map(s => <td key={s}>{preview.series.values[s][i] == null ? "missing" : number(preview.series.values[s][i]!)}</td>)}</tr>)}</tbody></table></div>{preview.metadata.ignoredColumns.length > 0 && <p className="ws-muted">Non-numeric columns: {preview.metadata.ignoredColumns.join(", ")}</p>}</details>
        <Plot times={preview.series.times} values={Object.values(preview.series.values)[0]} title={preview.metadata.columns[0].name} axis={preview.metadata.time} />
      </>}
      <ErrorText error={error} /><button className="ws-primary" disabled={!preview || loading || saving || !name.trim()}>{saving ? "Saving dataset…" : "Import and save dataset ↗"}</button>
    </>}
    {!csv && <ErrorText error={error} />}
  </form>;
}

function DatasetPage({ workspaceId, datasets, refresh, selected, setSelected, preferences, setPreferences }: {
  workspaceId: string; datasets: Dataset[]; refresh: () => void; selected: string; setSelected: (id: string) => void;
  preferences: Record<string, string[]>; setPreferences: (id: string, signals: string[]) => void;
}) {
  const [importing, setImporting] = useState(false);
  const dataset = datasets.find(d => d.id === selected) || datasets[0];
  const chosen = dataset ? preferences[dataset.id] ?? dataset.metadata.columns.slice(0, 4).map(c => c.name) : [];
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">01 / DATASETS</div><h1>Your process data<span className="ws-accent">.</span></h1><p>Bring a new dataset into this workspace. Every column keeps its own meaning.</p></div>{datasets.length > 0 && <button className="ws-primary" onClick={() => setImporting(!importing)}>{importing ? "Close import" : "+ Import CSV"}</button>}</div>
    {(importing || datasets.length === 0) && <ImportDataset workspaceId={workspaceId} onImport={d => { setSelected(d.id); setImporting(false); refresh(); }} />}
    {dataset && <>
      <div className="ws-section-heading"><h2>Saved datasets <span className="ws-muted">/ {datasets.length}</span></h2><label className="ws-inline">Dataset<select aria-label="Saved dataset" value={dataset.id} onChange={e => setSelected(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div>
      <section className="ws-panel"><h2>{dataset.name}</h2><Stats metadata={dataset.metadata} /><p className="ws-muted">{timeLabel(dataset.metadata.time, dataset.metadata.time.start)} → {timeLabel(dataset.metadata.time, dataset.metadata.time.end)}{dataset.metadata.time.origin && " · Window inputs use seconds since the first timestamp."}</p>
        <SignalPicker columns={dataset.metadata.columns} selected={chosen} onChange={signals => setPreferences(dataset.id, signals)} title="Signals to plot and analyze" />
        <SignalPlots dataset={dataset} signals={chosen} />
        <div className="ws-inline ws-between"><span className="ws-muted">Original CSV and numeric data are saved locally.</span><button className="ws-primary" onClick={() => { setSelected(dataset.id); setPreferences(dataset.id, chosen); go(`workspaces/${workspaceId}/analysis`); }} disabled={!chosen.length}>Configure analysis ↗</button></div>
      </section>
    </>}
  </>;
}

function AnalysisPage({ workspaceId, datasets, selected, setSelected, preferences, jobId, refresh }: {
  workspaceId: string; datasets: Dataset[]; selected: string; setSelected: (id: string) => void; preferences: Record<string, string[]>; jobId?: string; refresh: () => void;
}) {
  const dataset = datasets.find(d => d.id === selected) || datasets[0];
  const [config, setConfig] = useState<Config | null>(null), [result, setResult] = useState<AnalysisResult | null>(null);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const resultPanel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!dataset || jobId) return;
    const ranges = dataset.metadata.suggestedRanges || { baselineRange: [dataset.metadata.time.start, dataset.metadata.time.end] as [number, number], analysisRange: [dataset.metadata.time.start, dataset.metadata.time.end] as [number, number] };
    setConfig({ datasetId: dataset.id, signals: preferences[dataset.id] ?? dataset.metadata.columns.map(c => c.name), algorithm: "robust-maxz", alpha: .01, variance: .9, ...ranges });
    setResult(null); setError("");
  }, [dataset?.id, jobId]);
  useEffect(() => {
    if (!jobId || result?.id === jobId) return;
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null);
    api<AnalysisResult>(`/analyses/${jobId}`, undefined, "GET", controller.signal).then(data => { setResult(data); setConfig(data.config); setSelected(data.datasetId); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [jobId]);
  useEffect(() => {
    if (jobId && result?.id === jobId) resultPanel.current?.scrollIntoView({ behavior: "instant", block: "start" });
  }, [jobId, result?.id]);
  async function run(e: FormEvent) {
    e.preventDefault(); if (!config) return; setBusy(true); setError("");
    try { const data = await api<AnalysisResult>(`/workspaces/${workspaceId}/analyses`, config); setResult(data); refresh(); go(`workspaces/${workspaceId}/analysis/${data.id}`); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  function set<K extends keyof Config>(key: K, value: Config[K]) { setConfig(c => c ? { ...c, [key]: value } : c); }
  if (!dataset) return <Empty title="Import data to start analyzing"><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets`}>Go to datasets →</a></Empty>;
  const resultDataset = result && datasets.find(d => d.id === result.datasetId);
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">02 / ANALYSIS ENGINE</div><h1>Find what changed<span className="ws-accent">.</span></h1><p>Fit a normal baseline, then score a later window of your measurements.</p></div><span className="ws-badge">FULL-RESOLUTION COMPUTATION</span></div>
    {loading ? <p role="status">Opening saved analysis…</p> : config && <form className="ws-panel ws-analysis-form" onSubmit={run}>
      <div className="ws-form-grid"><label>Dataset<select value={dataset.id} onChange={e => { setSelected(e.target.value); if (jobId) go(`workspaces/${workspaceId}/analysis`); }}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label>Analysis name (optional)<input maxLength={160} value={config.name || ""} onChange={e => set("name", e.target.value)} placeholder="e.g. Temperature excursion review" /></label></div>
      <SignalPicker columns={dataset.metadata.columns} selected={config.signals} onChange={signals => set("signals", signals)} />
      <div className="ws-window-grid">{(["baselineRange", "analysisRange"] as const).map(key => <fieldset key={key}><legend>{key === "baselineRange" ? "Normal baseline · assumed healthy" : "Analysis window · target data"}</legend><div className="ws-form-grid"><label>{key === "baselineRange" ? "Baseline start (s)" : "Analysis start (s)"}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][0]} onChange={e => set(key, [Number(e.target.value), config[key][1]])} required /></label><label>{key === "baselineRange" ? "Baseline end (s)" : "Analysis end (s)"}<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={config[key][1]} onChange={e => set(key, [config[key][0], Number(e.target.value)])} required /></label></div></fieldset>)}</div>
      <p className="ws-notice">Choose a baseline you believe is normal, ending before the analysis window. At least 100 baseline samples: first 70% for fitting, final 30% for threshold calibration.{dataset.metadata.time.origin && ` Times are elapsed seconds from ${timeLabel(dataset.metadata.time, 0)}.`}</p>
      <div className="ws-form-grid ws-three"><label>Detection algorithm<select value={config.algorithm} onChange={e => set("algorithm", e.target.value)}><option value="robust-maxz">Robust Max-Z</option><option value="pca-q" disabled={config.signals.length < 2}>PCA-Q · residual deviation</option><option value="pca-t2" disabled={config.signals.length < 2}>PCA-T² · model-space deviation</option></select></label><label>Calibration alpha<input type="number" min="0.000001" max="0.499999" step="any" value={config.alpha} onChange={e => set("alpha", Number(e.target.value))} required /></label>{config.algorithm !== "robust-maxz" && <label>PCA retained variance<input type="number" min="0.5" max="0.999999" step="any" value={config.variance} onChange={e => set("variance", Number(e.target.value))} required /></label>}</div>
      <ErrorText error={error} /><div className="ws-inline ws-between"><span className="ws-muted">Every completed run is saved automatically to History.</span><button className="ws-primary" disabled={busy || loading || !config.signals.length}>{busy ? "Computing and saving…" : result ? "Run again with these parameters ↗" : "Run analysis and save ↗"}</button></div>
    </form>}
    {!config && <ErrorText error={error} />}
    {result && resultDataset && <div ref={resultPanel} className="ws-result-anchor"><ResultView key={result.id} result={result} dataset={resultDataset} signalPicker={(selected, onChange) => <SignalPicker title="Raw signals in view" columns={resultDataset.metadata.columns.filter(c => result.config.signals.includes(c.name))} selected={selected} onChange={onChange} />} /></div>}
  </>;
}

function HistoryPage({ jobs, datasets, workspaceId }: { jobs: Job[]; datasets: Dataset[]; workspaceId: string }) {
  return <><div className="ws-page-title"><div><div className="ws-kicker">03 / HISTORY</div><h1>Every run, retained<span className="ws-accent">.</span></h1><p>Reopen a result or use its saved parameters for another analysis.</p></div><span className="ws-badge">{jobs.length} SAVED RUNS</span></div>
    {jobs.length === 0 ? <Empty title="Your analyses will appear here"><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis`}>Start an analysis →</a></Empty> : <div className="ws-history">{jobs.map(job => <a href={`#/workspaces/${workspaceId}/analysis/${job.id}`} className="ws-history-row" key={job.id}><div><span className="ws-kicker">{job.config.algorithm} / {dateLabel(job.created_at)}</span><h2>{job.name}</h2><p>{datasets.find(d => d.id === job.dataset_id)?.name} · {job.config.signals.length} signals · {number(job.config.analysisRange[0])}–{number(job.config.analysisRange[1])} s</p></div><div><strong className={job.summary.flaggedSamples ? "ws-coral" : "ws-accent"}>{job.summary.flaggedSamples.toLocaleString()} flagged</strong><span>Open result ↗</span></div></a>)}</div>}
  </>;
}

export default function WorkspaceApp({ path }: { path: string[] }) {
  const workspaceId = path[0] === "workspaces" ? path[1] : undefined, tab = path[2] || "datasets", jobId = path[3];
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]), [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]), [jobs, setJobs] = useState<Job[]>([]), [selected, setSelected] = useState("");
  const [preferences, setPreferences] = useState<Record<string, string[]>>({}), [error, setError] = useState(""), [loading, setLoading] = useState(true), [revision, setRevision] = useState(0);
  function refresh() { setRevision(v => v + 1); }
  useEffect(() => {
    const controller = new AbortController(); setError("");
    api<{ workspaces: Workspace[] }>("/workspaces", undefined, "GET", controller.signal).then(data => setWorkspaces(data.workspaces)).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted && !workspaceId) setLoading(false); });
    return () => controller.abort();
  }, [revision, workspaceId]);
  useEffect(() => { setWorkspace(null); setDatasets([]); setJobs([]); setSelected(""); setLoading(Boolean(workspaceId)); }, [workspaceId]);
  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController();
    Promise.all([api<Workspace>(`/workspaces/${workspaceId}`, undefined, "GET", controller.signal), api<{ datasets: Dataset[] }>(`/workspaces/${workspaceId}/datasets`, undefined, "GET", controller.signal), api<{ jobs: Job[] }>(`/workspaces/${workspaceId}/analyses`, undefined, "GET", controller.signal)])
      .then(([w, d, j]) => { setWorkspace(w); setDatasets(d.datasets); setJobs(j.jobs); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId, revision]);
  return <div className="ws-shell">
    <header className="ws-header"><a className="ws-brand" href="#/"><b>L5</b><span>WORKSPACE</span><small>2.0</small></a><nav aria-label="Application"><a href="#/" className="ws-active">Workspaces</a><a href="#/examples">TripLens examples ↗</a></nav><span className="ws-connection"><i />LOCAL ENGINE</span></header>
    {workspaceId ? <div className="ws-layout"><aside className="ws-sidebar"><a href="#/" className="ws-back">← All workspaces</a><span className="ws-kicker">CURRENT PROJECT</span><h2>{workspace?.name || "Opening…"}</h2><nav aria-label="Workspace">{[["datasets", "01", "Datasets", datasets.length], ["analysis", "02", "Analysis", "↗"], ["history", "03", "History", jobs.length]].map(([key, index, title, count]) => <a key={key} className={tab === key ? "ws-active" : ""} href={`#/workspaces/${workspaceId}/${key}`} aria-current={tab === key ? "page" : undefined}><span>{index}</span>{title}<small>{count}</small></a>)}</nav><div className="ws-sidebar-note">A durable place for your data and the questions you ask of it.</div></aside>
      <main className="ws-main"><ErrorText error={error} />{loading ? <p role="status">Opening workspace…</p> : workspace && (tab === "history" ? <HistoryPage jobs={jobs} datasets={datasets} workspaceId={workspaceId} /> : tab === "analysis" ? <AnalysisPage key={workspaceId} workspaceId={workspaceId} datasets={datasets} selected={selected} setSelected={setSelected} preferences={preferences} jobId={jobId} refresh={refresh} /> : <DatasetPage workspaceId={workspaceId} datasets={datasets} refresh={refresh} selected={selected} setSelected={setSelected} preferences={preferences} setPreferences={(id, signals) => setPreferences(p => ({ ...p, [id]: signals }))} />)}</main>
    </div> : <><div className="ws-home-error"><ErrorText error={error} />{error && <button className="ws-outlined" onClick={refresh}>Reconnect</button>}</div>{loading ? <main className="ws-main" role="status">Loading workspaces…</main> : <WorkspaceHome workspaces={workspaces} refresh={refresh} />}</>}
    <footer className="ws-footer"><span>L5 / OPEN INDUSTRIAL ANALYSIS</span><span>CSV → BASELINE → ANALYSIS → HISTORY</span></footer>
  </div>;
}
