import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale, type Message } from "../i18n";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, go, message } from "./api";
import { AlgorithmParameters, algorithmParameters, algorithms } from "./AlgorithmControls";
import { ExperimentComparison } from "./ExperimentComparison";
import { ExperimentLabels } from "./ExperimentLabels";
import { ExperimentReport } from "./ExperimentReport";
import { TransformationLineage } from "./TransformationWorkspace";
import { dateLabel, number, signalLabel, type Config, type Dataset, type IncidentSummary } from "./types";
import { taskParameters, type AlgorithmPlan, type Experiment, type ExperimentComparisonData, type ExperimentConfig, type ExperimentRun, type ExperimentTask } from "./experimentTypes";
import { IndependentTraining } from "./IndependentTraining";
import { TEPBenchmark } from "./TEPBenchmark";
import { ExternalProvenance } from "./TEPWorkspace";
import "./experiments.css";

type Draft = Pick<Experiment, "name" | "description" | "config" | "notes" | "conclusion" | "conclusion_run_ids">;
function draftOf(experiment: Experiment): Draft {
  const { name, description, config, notes, conclusion, conclusion_run_ids } = experiment;
  return { name, description, config, notes, conclusion, conclusion_run_ids };
}
export function newExperimentConfig(dataset: Dataset, initialSignals?: string[]): ExperimentConfig {
  const time = dataset.metadata.time, span = time.end-time.start;
  const signals = initialSignals?.length ? initialSignals.filter(name => dataset.metadata.columns.some(c => c.name === name)) : dataset.metadata.columns.slice(0,4).map(c => c.name);
  return { datasetId: dataset.id, signals,
    ...(dataset.metadata.suggestedRanges || { baselineRange: [time.start, time.start+span*.3], analysisRange: [time.start+span*.3+(time.typicalInterval || time.sampleInterval || span/dataset.metadata.rowCount), time.end] }),
    alpha: .01, fitFraction: .7, minCoverage: .9, persistence: 1, requiredSignals: [], observationPolicy: "measured",
    algorithms: [{ algorithm: "robust-maxz", parameters: {}, study: {} }, ...(signals.length >= 2 ? [{ algorithm: "pca-q" as const, parameters: {}, study: {} }] : [])] };
}
function initialDraft(dataset: Dataset, signals?: string[]): Draft { return { name: tr("Untitled experiment"), description: "", config: newExperimentConfig(dataset, signals), notes: "", conclusion: "", conclusion_run_ids: [] }; }

function CandidateValues({ name, values, onChange }: { name: string; values?: number[]; onChange: (values: number[]) => void }) {
  useLocale();
  const [text, setText] = useState(values?.join(", ") || "");
  useEffect(() => { setText(values?.join(", ") || ""); }, [name]);
  return <label>{name}{" "}{tr("candidates")}<input aria-label={tr("{0} candidates", {0: name})} value={text} placeholder={tr("Single value above, or e.g. 0.7, 0.85, 0.95")} onChange={e => {
    const raw = e.target.value; setText(raw);
    const values = raw.trim() ? raw.split(",").filter(v => v.trim()).map(Number) : [];
    e.target.setCustomValidity(values.some(v => !Number.isFinite(v)) ? tr("Enter finite comma-separated numeric candidates.") : values.length > 8 ? tr("At most eight candidates per parameter.") : "");
    onChange(values);
  }} /></label>;
}

export function ExperimentWorkspace({ workspaceId, datasets, experimentId, initialDatasetId, initialSignals, onChanged }: { workspaceId: string; datasets: Dataset[]; experimentId?: string; initialDatasetId?: string; initialSignals?: string[]; onChanged: () => void }) {
  useLocale();
  const [list, setList] = useState<Experiment[]>([]), [saved, setSaved] = useState<Experiment | null>(null), [draft, setDraft] = useState<Draft | null>(null);
  const [data, setData] = useState<ExperimentComparisonData | null>(null), [selected, setSelected] = useState<string[]>([]), [runFilter, setRunFilter] = useState("");
  const [algorithmFilter, setAlgorithmFilter] = useState(""), [statusFilter, setStatusFilter] = useState(""), [parameterFilter, setParameterFilter] = useState("");
  const [preview, setPreview] = useState<{ taskCount: number; tasks: Config[] } | null>(null), [snapshot, setSnapshot] = useState<ExperimentRun | null>(null);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]), [incidentId, setIncidentId] = useState(""), [linked, setLinked] = useState<IncidentSummary | null>(null), [intervals, setIntervals] = useState<Record<string, number>>({});
  const [error, setError] = useState(""), [loading, setLoading] = useState(false), [busy, setBusy] = useState(false), [tick, setTick] = useState(0), [notice, setNotice] = useState<Message | null>(null);
  const form = useRef<HTMLFormElement>(null), previouslyRunning = useRef(false), context = useRef(0);
  const existingId = experimentId && experimentId !== "new" ? experimentId : undefined;
  useEffect(() => {
    const controller = new AbortController();
    api<{ experiments: Experiment[] }>(`/workspaces/${workspaceId}/experiments`, undefined, "GET", controller.signal).then(result => { if (!controller.signal.aborted) setList(result.experiments); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    api<{ incidents: IncidentSummary[] }>(`/workspaces/${workspaceId}/incidents`, undefined, "GET", controller.signal).then(result => { if (!controller.signal.aborted) setIncidents(result.incidents); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId, saved?.id, saved?.revision, saved?.runs.length, saved?.runs[0]?.id, linked?.id]);
  useEffect(() => {
    const controller = new AbortController(); context.current++; setBusy(false); setError(""); setNotice(null); setSaved(null); setData(null); setSelected([]); setRunFilter(""); setPreview(null); setSnapshot(null); setLinked(null); setIntervals({});
    if (!existingId) { setLoading(false); setDraft(datasets.length ? initialDraft(datasets.find(d => d.id === initialDatasetId) || datasets[0], initialSignals) : null); return () => { controller.abort(); context.current++; }; }
    setLoading(true); setDraft(null);
    api<Experiment>(`/experiments/${existingId}`, undefined, "GET", controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (result.workspace_id !== workspaceId) throw new Error("Experiment belongs to another workspace.");
      setSaved(result); setDraft(draftOf(result));
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); context.current++; };
  }, [workspaceId, existingId, initialDatasetId, initialSignals?.join("\0")]);
  useEffect(() => {
    if (!saved || saved.id !== existingId) return;
    const controller = new AbortController();
    api<ExperimentComparisonData>(`/experiments/${saved.id}/comparison`, { taskIds: selected }, "POST", controller.signal).then(result => { if (!controller.signal.aborted) { setData(result); setSaved(result.experiment); } }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [existingId, saved?.id, selected.join(","), tick]);
  const running = Boolean(saved?.runs.some(run => ["queued", "running"].includes(run.status)));
  useEffect(() => {
    if (previouslyRunning.current && !running) onChanged();
    previouslyRunning.current = running;
    if (!running) return;
    const timer = setInterval(() => setTick(v => v+1), 800);
    return () => clearInterval(timer);
  }, [running]);
  const dataset = datasets.find(d => d.id === draft?.config.datasetId);
  const inputDataset = datasets.find(d => d.id === draft?.config.training?.fit.datasetId) || dataset;
  const dirty = Boolean(draft && (!saved || JSON.stringify(draft) !== JSON.stringify(draftOf(saved))));
  function configure(changes: Partial<ExperimentConfig>) {
    setDraft(value => {
      if (!value) return value;
      const config = { ...value.config, ...changes };
      if (changes.signals) {
        const trim = (mapping?: Record<string, string>) => mapping ? Object.fromEntries(changes.signals!.map(s => [s, mapping[s] || s])) : undefined;
        if (config.training) config.training = { fit: { ...config.training.fit, signalMapping: trim(config.training.fit.signalMapping) }, calibration: { ...config.training.calibration, signalMapping: trim(config.training.calibration.signalMapping) } };
        if (config.testDatasets) config.testDatasets = config.testDatasets.map(test => ({ ...test, signalMapping: trim(test.signalMapping) }));
        config.requiredSignals = config.requiredSignals?.filter(s => changes.signals!.includes(s));
      }
      return { ...value, config };
    }); setPreview(null);
  }
  function plan(index: number, changes: Partial<AlgorithmPlan>) { if (draft) configure({ algorithms: draft.config.algorithms.map((item, i) => i === index ? { ...item, ...changes } : item) }); }
  async function save(andRun = false) {
    if (!draft || !form.current?.reportValidity()) return;
    const request = context.current; setBusy(true); setError(""); setNotice(null);
    try {
      const result = await api<Experiment>(saved ? `/experiments/${saved.id}` : `/workspaces/${workspaceId}/experiments`, { ...draft, ...(saved ? { revision: saved.revision } : {}) }, saved ? "PATCH" : "POST");
      if (request !== context.current) return;
      setSaved(result); setDraft(draftOf(result));
      if (andRun) {
        const run = await api<ExperimentRun>(`/experiments/${result.id}/runs`, {});
        if (request !== context.current) return;
        setRunFilter(run.id); setSaved({ ...result, runs: [run, ...result.runs] }); setNotice(["Batch queued: {0} tasks. Completed results are saved as each task finishes.", {0: run.task_count}]);
      } else setNotice(["Experiment definition and research notes saved."]);
      setTick(v => v+1); onChanged();
      if (!existingId) go(`workspaces/${workspaceId}/experiments/${result.id}`);
    } catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  async function previewTasks() {
    if (!draft || !form.current?.reportValidity()) return;
    const request = context.current; setError(""); setBusy(true);
    try { const result = await api<{ taskCount: number; tasks: Config[] }>(`/workspaces/${workspaceId}/experiments/preview`, { config: draft.config }); if (request === context.current) setPreview(result); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  async function copy() {
    if (!saved) return; const request = context.current; setBusy(true); setError("");
    try { const result = await api<Experiment>(`/experiments/${saved.id}/copy`, {}); if (request === context.current) go(`workspaces/${workspaceId}/experiments/${result.id}`); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  async function retry(runId: string) {
    if (!saved) return; const request = context.current; setBusy(true); setError("");
    try { const run = await api<ExperimentRun>(`/experiments/${saved.id}/runs`, { retryRunId: runId }); if (request !== context.current) return; setSaved(value => value ? { ...value, runs: [run, ...value.runs] } : value); setRunFilter(run.id); setTick(v => v+1); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  const tasks = data?.tasks || [];
  const visible = tasks.filter(task => (!runFilter || task.run_id === runFilter) && (!algorithmFilter || task.algorithm === algorithmFilter) && (!parameterFilter || taskParameters(task).toLowerCase().includes(parameterFilter.toLowerCase())) && (!statusFilter || (statusFilter === "alarm" ? Boolean(task.metrics?.behavior.alarmSamples) : statusFilter === "no-alarm" ? task.status === "succeeded" && !task.metrics?.behavior.alarmSamples : task.status === statusFilter)));
  const methodCount = draft?.config.algorithms.reduce((sum, item) => sum + Object.values(item.study).reduce((product, values) => product*Math.max(1, new Set(values).size), 1), 0) || 0;
  const count = methodCount * (draft?.config.testDatasets?.length || 1), taskLimit = draft?.config.training ? 256 : 64;
  const selectedTasks = tasks.filter(task => selected.includes(task.id) && task.status === "succeeded");
  const linkRun = selectedTasks[0]?.run_id;
  const sameRun = selectedTasks.length > 0 && selectedTasks.every(task => task.run_id === linkRun && task.datasetId === selectedTasks[0].datasetId);
  async function link() {
    if (!sameRun) return; const request = context.current; setBusy(true); setError("");
    try { const incident = await api<IncidentSummary>(`/experiment-runs/${linkRun}/incidents`, { taskIds: selectedTasks.map(t => t.id), intervals: Object.fromEntries(Object.entries(intervals).filter(([id]) => selectedTasks.some(t => t.id === id))), ...(incidentId ? { incidentId } : { title: saved?.name }) }); if (request === context.current) setLinked(incident); }
    catch (e) { if (request === context.current) setError(message(e)); } finally { if (request === context.current) setBusy(false); }
  }
  return <div className="experiment-workspace notranslate" translate="no">
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("RESEARCH / ANALYSIS EXPERIMENTS")}</div><h1>{tr("One question. Many methods")}<span className="ws-accent">.</span></h1><p>{tr("Save the setup, run a batch, compare the evidence and retain the research.")}</p></div><span className="ws-badge">{running ? tr("BATCH IN PROGRESS") : tr("PERSISTENT EXPERIMENTS")}</span></div>
    <nav className="experiment-nav" aria-label={tr("Experiment sections")}>{[["definition", tr("Configure")], ["execution", tr("Execution")], ...(draft?.config.training ? [["benchmark", tr("TEP benchmark")]] : []), ["comparison", tr("Comparison")], ["report", tr("Report")]].map(([id, title]) => <button type="button" key={id} onClick={() => document.getElementById(`experiment-${id}`)?.scrollIntoView({ block: "start" })}>{title}</button>)}</nav>
    <section className="ws-panel experiment-library" aria-label={tr("Saved experiments")}><div className="ws-section-heading"><h2>{tr("Your experiments")}</h2><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/new`}>{tr("＋ New experiment")}</a></div>
      <label>{tr("Open saved experiment")}<select value={existingId || ""} onChange={e => go(`workspaces/${workspaceId}/experiments/${e.target.value || "new"}`)}><option value="">{tr("New experiment")}</option>{list.map(item => <option key={item.id} value={item.id}>{item.name} · {item.run_count || 0}{" "}{tr("runs ·")}{" "}{item.historical_task_count || 0}{" "}{tr("tasks")}</option>)}</select></label>
      {saved && <div className="ws-inline ws-between"><span className="ws-muted">{saved.id}{" "}{tr("· revision")}{" "}{saved.revision}{" "}{tr("· updated")}{" "}{dateLabel(saved.updated_at)}{list.find(item => item.id === saved.id)?.last_run_at ? tr(" · last run {0}", {0: dateLabel(list.find(item => item.id === saved.id)!.last_run_at!)}) : ""}</span><button disabled={busy || dirty} onClick={() => void copy()}>{tr("Duplicate experiment")}</button></div>}
    </section>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{notice && <p className="ws-notice" role="status">{tr(...notice)}</p>}
    {loading ? <p role="status">{tr("Opening saved experiment…")}</p> : !draft || !dataset ? <p className="ws-notice">{tr("Import a dataset to configure an experiment.")}</p> : <>
      <form id="experiment-definition" ref={form} className="ws-panel experiment-editor" inert={busy} aria-busy={busy} onSubmit={(e: FormEvent) => { e.preventDefault(); void save(); }} aria-label={tr("Experiment definition")}>
        <div className="ws-section-heading"><h2>{tr("01 / Define the experiment")}</h2><span className="ws-muted">{dirty ? tr("Unsaved changes") : tr("Saved definition")}</span></div>
        <div className="ws-form-grid"><label>{tr("Experiment name")}<input maxLength={160} required value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label><label>{tr("Experiment dataset")}<select value={dataset.id} onChange={e => { const next = datasets.find(d => d.id === e.target.value)!; configure({ ...newExperimentConfig(next), labelSetId: undefined }); }} >{datasets.map(d => <option key={d.id} value={d.id}>{d.name}{d.metadata.external ? tr(" · TEP external") : d.metadata.transformation ? tr(" · derived") : d.metadata.model ? ` · ${d.metadata.model.name || d.metadata.model.id}` : " · CSV"}</option>)}</select></label></div>
        <label>{tr("Research question / description")}<textarea value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} /></label>
        {dataset.metadata.model && <p><a className="ws-link" href={`#/workspaces/${workspaceId}/simulations/${dataset.metadata.model.simulationId}`}>{tr("Open source model investigation ↗")}</a> · {tr(dataset.metadata.model.name || dataset.metadata.model.id)} {dataset.metadata.model.version && `v${dataset.metadata.model.version}`} {dataset.metadata.model.scenarioVersion && tr("· scenario v{0}", {0: dataset.metadata.model.scenarioVersion})}</p>}
        {dataset.metadata.transformation && <TransformationLineage dataset={dataset} />}
        <IndependentTraining datasets={datasets} config={draft.config} onChange={configure} /><ExternalProvenance dataset={dataset} />
        <fieldset><legend>{tr("Input signals ·")}{" "}{draft.config.signals.length}{" "}{tr("selected")}</legend><div className="ws-inline"><button type="button" onClick={() => configure({ signals: inputDataset!.metadata.columns.map(c => c.name) })}>{tr("Select all signals")}</button><button type="button" onClick={() => configure({ signals: [], requiredSignals: [] })}>{tr("Clear signals")}</button></div><div className="ws-signal-list">{inputDataset!.metadata.columns.map(column => <label key={column.name}><input type="checkbox" checked={draft.config.signals.includes(column.name)} onChange={e => { const signals = e.target.checked ? [...draft.config.signals, column.name] : draft.config.signals.filter(s => s !== column.name); configure({ signals, requiredSignals: draft.config.requiredSignals?.filter(s => signals.includes(s)) }); }} />{signalLabel(column)}</label>)}</div></fieldset>
        {!draft.config.training && <div className="ws-window-grid">{(["baselineRange", "analysisRange"] as const).map(key => <fieldset key={key}><legend>{key === "baselineRange" ? tr("Assumed normal baseline") : tr("Analysis window")}</legend><div className="ws-form-grid">{([0,1] as const).map(i => <label key={i}>{key === "baselineRange" ? tr("Baseline") : tr("Analysis")} {i === 0 ? tr("start") : tr("end")} (s)<input type="number" step="any" required min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={draft.config[key][i]} onChange={e => configure({ [key]: i === 0 ? [Number(e.target.value), draft.config[key][1]] : [draft.config[key][0], Number(e.target.value)] })} /></label>)}</div></fieldset>)}</div>}
        <p className="ws-muted">{tr("Dataset-native seconds")}{dataset.metadata.time.origin ? tr(" from {0}", {0: dataset.metadata.time.origin}) : ""}{tr(". Each normal fit and calibration partition requires at least 30 observations. A single-dataset baseline must end before its analysis window. Truth labels are used for evaluation only.")}</p>
        <div className="ws-form-grid ws-three"><label>{tr("Shared calibration alpha")}<input type="number" step="any" min={.000001} max={.499999} required value={draft.config.alpha} onChange={e => configure({ alpha: Number(e.target.value) })} /></label>{!draft.config.training && <label>{tr("Fit fraction")}<input type="number" step="any" min={.5} max={.9} value={draft.config.fitFraction} onChange={e => configure({ fitFraction: Number(e.target.value) })} /></label>}<label>{tr("Minimum observed fraction")}<input type="number" step="any" min={.000001} max={1} value={draft.config.minCoverage} onChange={e => configure({ minCoverage: Number(e.target.value) })} /></label><label>{tr("Alarm persistence (samples)")}<input type="number" step={1} min={1} value={draft.config.persistence} onChange={e => configure({ persistence: Number(e.target.value) })} /></label><label>{tr("Observation policy")}<select value={draft.config.observationPolicy} onChange={e => configure({ observationPolicy: e.target.value as "measured" | "processed" })}><option value="measured">{tr("Original observations only")}</option><option value="processed">{tr("Include processed values explicitly")}</option></select></label></div>
        <details><summary>{tr("Required observed signals")}</summary><div className="ws-option-grid">{draft.config.signals.map(signal => <label key={signal}><input type="checkbox" checked={draft.config.requiredSignals?.includes(signal) || false} onChange={e => configure({ requiredSignals: e.target.checked ? [...(draft.config.requiredSignals || []), signal] : draft.config.requiredSignals?.filter(s => s !== signal) })} />{signal}</label>)}</div></details>
        <fieldset><legend>{tr("Detection methods")}</legend><div className="ws-inline"><button type="button" onClick={() => configure({ algorithms: Object.keys(algorithms).map(algorithm => draft.config.algorithms.find(item => item.algorithm === algorithm) || { algorithm, parameters: {}, study: {} }) })}>{tr("Select all nine algorithms")}</button><span className="ws-muted">{draft.config.algorithms.length}{" "}{tr("methods ·")}{" "}{count}{" "}{tr("tasks /")}{" "}{taskLimit}{" "}{tr("maximum")}</span></div><div className="ws-option-grid">{Object.entries(algorithms).map(([id, label]) => <label key={id}><input type="checkbox" checked={draft.config.algorithms.some(item => item.algorithm === id)} onChange={e => configure({ algorithms: e.target.checked ? [...draft.config.algorithms, { algorithm: id, parameters: {}, study: {} }] : draft.config.algorithms.filter(item => item.algorithm !== id) })} />{tr(label)}</label>)}</div></fieldset>
        <div className="experiment-plans">{draft.config.algorithms.map((item, index) => <fieldset key={item.algorithm}><legend>{algorithms[item.algorithm]}</legend><div className="ws-form-grid ws-three"><AlgorithmParameters config={{ ...draft.config, algorithm: item.algorithm, variance: .9, ...item.parameters } as Config} onChange={value => plan(index, { parameters: Object.fromEntries(algorithmParameters(item.algorithm).filter(([key]) => value[key] !== undefined).map(([key]) => [key, value[key] as number])) })} /></div>{item.algorithm === "adaptive-maxz" && <p className="ws-notice">{tr("Experimental adaptation can absorb a slow fault. Compare with a fixed reference detector.")}</p>}<details><summary>{tr("Parameter study ·")}{" "}{Object.values(item.study).reduce((n, values) => n*values.length, 1)}{" "}{tr("combinations")}</summary><p className="ws-muted">{tr("Finite candidate values form a Cartesian product. Leave blank for the single configured value. At most 8 values per parameter and the task budget shown above.")}</p><div className="ws-form-grid">{["alpha", ...algorithmParameters(item.algorithm).map(([key]) => key)].map(key => <CandidateValues key={`${existingId}-${item.algorithm}-${key}`} name={`${algorithms[item.algorithm]} ${key}`} values={item.study[key]} onChange={values => { const study = { ...item.study }; if (values.length) study[key] = values; else delete study[key]; plan(index, { study }); }} />)}</div></details></fieldset>)}</div>
        {!draft.config.training && <ExperimentLabels key={dataset.id} dataset={dataset} value={draft.config.labelSetId} onChange={labelSetId => configure({ labelSetId })} />}
        <div className="ws-section-heading"><h2>{tr("Research record")}</h2><span className="ws-muted">{tr("Conclusions retain references to the selected saved runs")}</span></div><label>{tr("Experiment notes")}<textarea value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label><label>{tr("Experiment conclusion")}<textarea value={draft.conclusion} onChange={e => setDraft({ ...draft, conclusion: e.target.value })} /></label>
        {saved && <fieldset><legend>{tr("Runs supporting this conclusion")}</legend><div className="ws-option-grid">{saved.runs.map(run => <label key={run.id}><input type="checkbox" checked={draft.conclusion_run_ids.includes(run.id)} onChange={e => setDraft({ ...draft, conclusion_run_ids: e.target.checked ? [...draft.conclusion_run_ids, run.id] : draft.conclusion_run_ids.filter(id => id !== run.id) })} />{run.id.slice(0,8)} · {tr(run.status)} · {dateLabel(run.created_at)}</label>)}</div></fieldset>}
        <div className="ws-inline experiment-actions"><button type="button" disabled={busy || count > taskLimit || !count} onClick={() => void previewTasks()}>{tr("Preview")}{" "}{count}{" "}{tr("tasks")}</button><button disabled={busy || count > taskLimit || !count}>{tr("Save experiment")}</button><button type="button" className="ws-primary" disabled={busy || running || count > taskLimit || !count} onClick={() => void save(true)}>{busy ? tr("Saving…") : tr("Save & run all tasks ↗")}</button></div>
        {preview && <details open><summary>{tr("Validated task preview ·")}{" "}{preview.taskCount}</summary><div className="ws-table-scroll"><table><thead><tr><th>{tr("Task")}</th><th>{tr("Algorithm")}</th><th>{tr("Parameters")}</th></tr></thead><tbody>{preview.tasks.map((task, i) => <tr key={i}><td>{i+1}</td><td>{algorithms[task.algorithm]}</td><td>{JSON.stringify(task)}</td></tr>)}</tbody></table></div></details>}
      </form>
      {saved?.records?.length ? <details className="ws-panel"><summary>{tr("Saved research record history ·")}{" "}{saved.records.length}{" "}{tr("revisions")}</summary>{saved.records.map(record => <article key={record.id}><h3>{tr("Revision")}{" "}{record.revision} · {dateLabel(record.created_at)}</h3><p className="incident-prose">{record.notes}</p><p className="incident-prose">{record.conclusion}</p><p className="ws-muted">{tr("Run references:")}{" "}{record.run_ids.join(", ") || tr("None recorded")}{" "}{tr("· record")}{" "}{record.id}</p></article>)}</details> : null}
      {saved && <><section id="experiment-execution" className="ws-panel" aria-label={tr("Experiment execution history")}><h2>{tr("02 / Execution & results")}</h2><p className="ws-muted">{tr("Each execution keeps its own dataset hash, clock, label version and configuration. Editing above does not change earlier runs.")}</p>
        {!saved.runs.length && <p>{tr("No executions yet. Save & run the configured batch above.")}</p>}
        <div className="experiment-runs">{saved.runs.map(run => <article key={run.id} className="experiment-run"><div><strong>{run.id.slice(0,8)} · {tr(run.status)}</strong><small>{dateLabel(run.created_at)} · {run.duration_ms == null ? tr("Awaiting completion") : `${number(run.duration_ms)} ms`}</small><progress aria-label={tr("Run {0} progress", {0: run.id.slice(0,8)})} max={run.task_count} value={run.completed} /><span>{run.completed} / {run.task_count}{" "}{tr("completed ·")}{" "}{run.succeeded || 0}{" "}{tr("succeeded ·")}{" "}{run.failed || 0}{" "}{tr("failed")}</span></div><div className="ws-inline"><button onClick={() => setRunFilter(run.id)}>{tr("View tasks")}</button><button onClick={() => { void api<ExperimentRun>(`/experiment-runs/${run.id}`).then(setSnapshot).catch(e => setError(message(e))); }}>{tr("Input snapshot")}</button>{["partial", "failed", "interrupted"].includes(run.status) && <button disabled={busy} onClick={() => void retry(run.id)}>{tr("Retry unfinished tasks")}</button>}</div></article>)}</div>
        {snapshot && <details open><summary>{tr("Saved input snapshot ·")}{" "}{snapshot.id.slice(0,8)}</summary><pre className="experiment-json">{JSON.stringify(snapshot.snapshot, null, 2)}</pre></details>}
        <div className="ws-form-grid ws-three"><label>{tr("Filter run batch")}<select value={runFilter} onChange={e => setRunFilter(e.target.value)}><option value="">{tr("All batches")}</option>{saved.runs.map(run => <option key={run.id} value={run.id}>{run.id.slice(0,8)} · {tr(run.status)}</option>)}</select></label><label>{tr("Filter algorithm")}<select value={algorithmFilter} onChange={e => setAlgorithmFilter(e.target.value)}><option value="">{tr("All algorithms")}</option>{Object.entries(algorithms).map(([id,label]) => <option key={id} value={id}>{tr(label)}</option>)}</select></label><label>{tr("Filter task / detection status")}<select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}><option value="">{tr("All statuses")}</option>{["queued", "running", "succeeded", "failed", "interrupted", "alarm", "no-alarm"].map(status => <option key={status}>{tr(status)}</option>)}</select></label><label>{tr("Filter parameter text")}<input value={parameterFilter} onChange={e => setParameterFilter(e.target.value)} placeholder={tr("e.g. variance=0.9")} /></label></div>
        <div className="ws-inline"><button onClick={() => setSelected(visible.filter(task => task.status === "succeeded").slice(0,12).map(task => task.id))}>{tr("Compare completed tasks (up to 12)")}</button><button onClick={() => setSelected([])}>{tr("Clear comparison")}</button><span className="ws-muted">{selected.length}{" "}{tr("selected ·")}{" "}{visible.length}{" "}{tr("visible tasks")}</span></div>
        <div className="ws-table-scroll"><table className="experiment-results"><thead><tr><th>{tr("Compare / method")}</th><th>{tr("Batch / parameters")}</th><th>{tr("Dataset / window")}</th><th>{tr("Status / result")}</th><th>{tr("First alarm (native s)")}</th><th>{tr("Alarm intervals / seconds")}</th><th>{tr("Alarm / valid / abstain")}</th><th>{tr("Coverage / alarm fraction")}</th><th>{tr("Compute / wall ms")}</th><th>{tr("Main variables")}</th><th>{tr("Truth evaluation")}</th></tr></thead><tbody>{visible.map(task => <TaskRow key={task.id} task={task} workspaceId={workspaceId} checked={selected.includes(task.id)} disabled={!selected.includes(task.id) && selected.length >= 12} onSelect={checked => setSelected(ids => checked ? [...ids,task.id] : ids.filter(id => id !== task.id))} />)}</tbody></table></div>
      </section>
      {data && <><TEPBenchmark data={data} datasets={datasets} onSelect={setSelected} /><ExperimentComparison data={data} /></>}
      {selectedTasks.length > 0 && <section className="ws-panel" aria-label={tr("Experiment incident integration")}><h2>{tr("03 / Continue into investigation")}</h2><p>{tr("Associate selected results from one saved run with an incident. Each source retains its experiment, run, task and AnalysisResult IDs.")}</p>{!sameRun && <p className="ws-notice">{tr("Select tasks for one independent test dataset from a single batch to create its incident.")}</p>}
        <label>{tr("Target incident")}<select value={incidentId} onChange={e => setIncidentId(e.target.value)}><option value="">{tr("Create a new incident from this batch")}</option>{incidents.map(incident => <option key={incident.id} value={incident.id}>{incident.title}</option>)}</select></label>
        {selectedTasks.map(task => <label key={task.id}>{tr("Source scope ·")}{" "}{algorithms[task.algorithm]} {task.id.slice(0,6)}<select value={intervals[task.id] ?? "all"} onChange={e => setIntervals(values => { const next = { ...values }; if (e.target.value === "all") delete next[task.id]; else next[task.id] = Number(e.target.value); return next; })}><option value="all">{tr("Entire analysis result")}</option>{data?.analyses.find(a => a.id === task.id)?.result.intervals.map((interval, index) => <option key={index} value={index}>{tr("Alarm interval")}{" "}{index+1}: {number(interval.start)}–{number(interval.end)} s</option>)}</select></label>)}
        <button disabled={busy || !sameRun} onClick={() => void link()}>{incidentId ? tr("Link selected results to incident") : tr("Create incident from selected results")}</button>{linked && <p><a className="ws-link" href={`#/workspaces/${workspaceId}/incidents/${linked.id}`}>{tr("Open incident:")}{" "}{linked.title} ↗</a></p>}
      </section>}
      <ExperimentReport experiment={saved} dirty={dirty} /></>}
    </>}
  </div>;
}

function TaskRow({ task, workspaceId, checked, disabled, onSelect }: { task: ExperimentTask; workspaceId: string; checked: boolean; disabled: boolean; onSelect: (checked: boolean) => void }) {
  useLocale();
  const behavior = task.metrics?.behavior, labelled = task.metrics?.labelled;
  const value = (v: number | null | undefined) => v == null ? "—" : number(v);
  return <tr><td><label><input type="checkbox" aria-label={tr("Compare task {0}", {0: task.id.slice(0,8)})} checked={checked} disabled={disabled || task.status !== "succeeded"} onChange={e => onSelect(e.target.checked)} />{algorithms[task.algorithm]}</label><small>{task.id.slice(0,8)}</small></td><td>{task.run_id.slice(0,8)}{" "}{tr("· revision")}{" "}{task.experimentRevision}<small>{taskParameters(task)}</small></td><td>{task.datasetName}<small>{task.config.analysisRange.join("–")} s</small></td><td><span className={`experiment-status ${task.status}`}>{tr(task.status)}</span>{task.result_id && <a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${task.result_id}`}>{tr("Open AnalysisResult ↗")}</a>}{task.error && <p className="ws-error">{task.error}</p>}</td><td>{value(behavior?.firstDetection)}</td><td>{behavior ? `${behavior.alarmIntervalCount} / ${number(behavior.alarmDuration)} s` : "—"}</td><td>{behavior ? `${behavior.alarmSamples} / ${behavior.validSamples} / ${behavior.abstainedSamples}` : "—"}</td><td>{value(behavior?.coverageFraction)} / {value(behavior?.alarmFraction)}</td><td>{value(behavior?.durationMs)} / {value(task.duration_ms)}</td><td>{behavior?.relatedSignals.slice(0,3).join(" · ")}</td><td>{labelled ? <details><summary>{tr("Labels v")}{labelled.version}{" "}{tr("· sample F1")}{" "}{value(labelled.sample.f1)}</summary><p>{tr("Sample TP / FP / TN / FN:")}{" "}{labelled.sample.TP} / {labelled.sample.FP} / {labelled.sample.TN} / {labelled.sample.FN}</p><p>{tr("Precision")}{" "}{value(labelled.sample.precision)}{" "}{tr("· recall")}{" "}{value(labelled.sample.recall)} · F1 {value(labelled.sample.f1)}{" "}{tr("· false alarm rate")}{" "}{value(labelled.sample.falseAlarmRate)}</p><p>{labelled.sample.evaluatedSamples}{" "}{tr("evaluated ·")}{" "}{labelled.sample.unlabelledSamples}{" "}{tr("unknown ·")}{" "}{labelled.sample.labelledAbstainedSamples}{" "}{tr("labelled abstain")}</p><p>{tr("Events:")}{" "}{labelled.event.detectedEvents}{" "}{tr("detected /")}{" "}{labelled.event.missedEvents}{" "}{tr("missed /")}{" "}{labelled.event.unobservedEvents}{" "}{tr("unobserved ·")}{" "}{labelled.event.falseAlarmEvents}{" "}{tr("false alarm events · first delay")}{" "}{value(labelled.event.firstDetectionDelay)} s</p><small>{labelled.source}</small></details> : behavior ? tr("Unlabelled · behavior only") : "—"}</td></tr>;
}
