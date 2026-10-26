import { errorMessage } from "../i18n/errors";
import { t as tr, runtimeText, useLocale } from "../i18n";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { EvidenceView, AlarmView, TraceView, EvidenceResult } from "../components/ProcessEvidence";
import type { Analysis, Row, Trace } from "../lib/platform";
import { downloadFile } from "../lib/download";
import { api, message } from "./api";
import { Plot } from "./Charts";
import { dateLabel, number, type Dataset, type Workspace, type RuntimeRun, type IncidentSource } from "./types";
import { IncidentLinkDialog, type IncidentDraft } from "./IncidentLinkDialog";
import "./workspace.css";
import "./runtime.css";
import { observationKey, useObservation, type Observation, type ObservationContext } from "./useObservation";
import { isModelForecast, ModelForecastView, ModelToolResult } from "./ModelResults";

type SimulationConfig = { fault: string; start: number; severity: number; operating: number; noise: number; response: number; delay: number; seed: number | null; duration: number; step: number };
type Session = { id: string; modelId?: string; title: string; config: SimulationConfig; rows: Row[]; createdAt: string; workspaceId: string | null; datasetId: string | null };
type Catalog = { faults: Record<string, string>; defaults: SimulationConfig; signals: { key: string; tag: string }[]; actions: { id: string; name: string }[]; actionParameters: Record<string, { default: number; min: number; max: number }>; tools: string[] };
type ForecastPath = { times: number[]; pressure: number[]; physicalPeak: number; trip: number | null; productionLoss: number; qualityLoss: number; utilityCost: number; safe: boolean; action?: string };
type Forecast = { mode: string; hypothesis: string; observedThrough: number; at: number; horizon: number; threshold: number; fitError: number | null; baseline: ForecastPath; branches: ForecastPath[]; search?: { resolution: number; evaluated: number; actions: {id:string;name:string;latest:number|null;intervals:number[][]}[] } };
type Run = RuntimeRun;
type Tab = "evidence" | "alarms" | "tools" | "interventions" | "compare" | "history";
const labels: Record<Tab, string> = { get evidence() { return tr("Evidence & topology"); }, get alarms() { return tr("Alarm history"); }, get tools() { return tr("Investigation tools"); }, get interventions() { return tr("Interventions"); }, get compare() { return tr("Compare sessions"); }, get history() { return tr("Saved experiments"); } };
const fields: [keyof SimulationConfig, string, number, number, number][] = [
  ["start", "Fault onset (s)", 0, Infinity, .1], ["severity", "Fault severity multiplier", 0, Infinity, .05],
  ["operating", "Initial temperature offset (°C)", -20, 20, .1], ["noise", "Measurement noise multiplier", 0, Infinity, .1],
  ["response", "Controller response multiplier", .05, Infinity, .05], ["delay", "Actuator delay (s)", 0, Infinity, .1],
  ["duration", "Simulation duration (s)", 1, Infinity, .1], ["step", "Integration step (s)", .05, 1, .05],
];
const parameterLabels: Record<string, string> = { get feedReduction() { return tr("Feed reduction fraction"); }, get setpointDrop() { return tr("Setpoint reduction (°C)"); }, get bypassFlow() { return tr("Bypass cooling flow (%)"); }, get pumpSpeed() { return tr("Backup pump speed (%)"); }, get emergencyFlow() { return tr("Emergency cooling flow (%)"); } };
const applicable: Record<string, string[]> = { feed_reduce: ["feedReduction"], setpoint: ["setpointDrop"], bypass: ["bypassFlow"], backup_pump: ["pumpSpeed"], emergency: ["emergencyFlow"], shutdown: [], combined: ["feedReduction", "bypassFlow"] };
function ErrorText({ error }: { error: string }) {
  useLocale(); return error ? <p className="ws-error" role="alert">{errorMessage(error)}</p> : null; }
function exportJSON(name: string, value: unknown) {
  downloadFile(name, JSON.stringify(value, null, 2));
}

export function RuntimeWorkbench({ workspaceId, simulationId, runId, initialWindow, onSaved, initialTab = "evidence", embedded = false }: { workspaceId?: string; simulationId?: string; runId?: string; initialWindow?: { windowStart: number; asOf: number; hypothesis?: string }; onSaved?: (d: Dataset) => void; initialTab?: Tab; embedded?: boolean }) {
  useLocale();
  const [catalog, setCatalog] = useState<Catalog | null>(null), [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null), [chosen, setChosen] = useState(simulationId || "");
  const [config, setConfig] = useState<SimulationConfig | null>(null), [title, setTitle] = useState("");
  const [configOpen, setConfigOpen] = useState(true);
  const [time, setTime] = useState(93), [windowStart, setWindowStart] = useState(0);
  const [hypothesis, setHypothesis] = useState<{key:string;id:string} | null>(null), [tab, setTab] = useState<Tab>(initialTab), [runs, setRuns] = useState<Run[]>([]), [restore, setRestore] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]), [saveWorkspace, setSaveWorkspace] = useState(workspaceId || "");
  const [linking, setLinking] = useState<{ source: IncidentSource; draft: IncidentDraft } | null>(null);
  const sessionReady = Boolean(session && session.id === chosen);
  const context: ObservationContext | null = session && sessionReady ? { sessionId: session.id, asOf: time, windowStart } : null;
  const observation = useObservation(context);
  const analysis = observation.analysis;
  const displayedAnalysis = observation.retained && observation.retained.context.sessionId === session?.id ? observation.retained.analysis : null;
  const contextKey = observation.key;
  const activeChoice = useRef(chosen);
  activeChoice.current = chosen;
  const activeSession = useRef<string | null>(null);
  activeSession.current = session?.id ?? null;
  useEffect(() => { if (simulationId) setChosen(simulationId); }, [simulationId]);
  useEffect(() => { setTab(initialTab); }, [initialTab]);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<Catalog>("/simulations/catalog", undefined, "GET", controller.signal), api<{ simulations: Session[] }>(`/simulations${workspaceId ? `?workspaceId=${workspaceId}` : ""}`, undefined, "GET", controller.signal), api<{workspaces:Workspace[]}>("/workspaces", undefined, "GET", controller.signal)])
      .then(([c, s, w]) => { if (controller.signal.aborted) return; setCatalog(c); setConfig(current => current ?? { ...c.defaults, step: .2, seed: null }); const compatible = s.simulations.filter(session => !session.modelId || session.modelId === "triplens-synthetic-18-v2"); setSessions(compatible); setWorkspaces(w.workspaces); setSaveWorkspace(workspaceId || w.workspaces[0]?.id || ""); if (!simulationId && compatible.length) setChosen(current => current || compatible[0].id); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [workspaceId]);
  useEffect(() => {
    if (!chosen) return;
    const controller = new AbortController(); setError("");
    Promise.all([api<Session>(`/simulations/${chosen}`, undefined, "GET", controller.signal), api<{runs:Run[]}>(`/simulations/${chosen}/runs`, undefined, "GET", controller.signal)])
      .then(([s, r]) => { if (controller.signal.aborted || activeChoice.current !== chosen) return; setSession(s); setConfig(s.config); setConfigOpen(false); setTitle(s.title); setTime(Math.min(93, s.config.duration)); setWindowStart(0); setHypothesis(null); setRestore(null); setRuns(r.runs); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [chosen]);
  useEffect(() => {
    if (runId && sessionReady && session) {
      const run = runs.find(r => r.id === runId);
      if (run) reopen(run);
    }
  }, [runId, session?.id, sessionReady]);
  useEffect(() => {
    if (initialWindow && sessionReady && session) {
      setTime(initialWindow.asOf); setWindowStart(initialWindow.windowStart);
      if (initialWindow.hypothesis) setHypothesis({ key: observationKey({ sessionId: session.id, ...initialWindow }), id: initialWindow.hypothesis });
      setTab("evidence");
    }
  }, [session?.id, sessionReady, initialWindow?.asOf, initialWindow?.windowStart, initialWindow?.hypothesis]);
  function reopen(r: Run) {
    if (!session) return;
    const asOf = Number(r.request.asOf ?? session.config.duration), start = Number(r.request.windowStart || 0);
    setTime(asOf); setWindowStart(start);
    if (typeof r.request.hypothesis === "string") setHypothesis({ key: observationKey({ sessionId: session.id, asOf, windowStart: start }), id: r.request.hypothesis });
    setRestore(r); setTab(r.kind === "intervention" ? "interventions" : "tools");
  }
  function linkRun(r: Run) {
    if (!session) return;
    setLinking({ source: { kind: "run", simulationId: session.id, runId: r.id, ...(typeof r.request.hypothesis === "string" ? { hypothesis: r.request.hypothesis } : {}) }, draft: { title: tr("{0} · 调查", {0: session.title}), start: Number(r.request.windowStart || 0), end: Number(r.request.asOf ?? session.config.duration), description: tr("{0} · {1} · 观察至 {2}s。", {0: r.kind === "intervention" ? tr("干预实验") : tr("工具调查"), 1: session.title, 2: String(r.request.asOf)}) } });
  }
  async function create(e: FormEvent) {
    e.preventDefault(); if (!config) return; setBusy(true); setError(""); setNotice("");
    try {
      const data = await api<Session>("/simulations", { config, title: title || undefined, workspaceId });
      setSessions(previous => [data, ...previous]); setChosen(data.id); setConfigOpen(false); setNotice("New trajectory computed and saved locally.");
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function save() {
    if (!session || !sessionReady) return; setBusy(true); setError("");
    const savingId = session.id;
    try {
      const dataset = await api<Dataset>(`/simulations/${session.id}/save`, { workspaceId: saveWorkspace, name: session.title });
      setSession(s => s?.id === savingId ? { ...s, workspaceId: saveWorkspace, datasetId: dataset.id } : s); onSaved?.(dataset);
      if (activeSession.current === savingId) setNotice("Dataset and process model linked to the workspace. Saved experiments reopen with this session.");
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  function record(run: Run) { if (activeSession.current === session?.id) setRuns(previous => [run, ...previous]); }
  const currentHypothesis = analysis ? (hypothesis?.key === contextKey ? hypothesis.id : analysis.diagnosis.candidates[0]?.id || "") : "";
  function selectHypothesis(id:string) { if (analysis && contextKey) setHypothesis({key:contextKey,id}); }
  return <div className={`ws-shell ws-runtime platform-workspace${embedded ? " model-specialist" : ""}`}>
    {!embedded && <div className="ws-page-title"><div><div className="ws-kicker">{tr("PROCESS MODEL / RUNTIME COMPUTATION")}</div><h1>{tr("Build a scenario. Follow the evidence.")}</h1><p>{tr("Generate observations, investigate any moment, and compare your own model experiments.")}</p></div><span className="ws-badge">{tr("18 CHANNELS · 12 FAULT MODELS")}</span></div>}
    <ErrorText error={error} />
    {!embedded && catalog && config && <details className="ws-panel runtime-config" open={configOpen} onToggle={e => setConfigOpen(e.currentTarget.open)}><summary>{tr("Configure a simulation / create a new trajectory")}</summary><form onSubmit={create}>
      <div className="ws-form-grid ws-three"><label>{tr("Scenario name")}<input value={title} onChange={e => setTitle(e.target.value)} maxLength={160} placeholder={tr("Name this experiment")} /></label><label>{tr("Fault template")}<select value={config.fault} onChange={e => setConfig({ ...config, fault: e.target.value })}>{Object.entries(catalog.faults).map(([id, name]) => <option key={id} value={id}>{tr(name)}</option>)}</select></label><label>{tr("Random seed")}<input type="number" min={0} step={1} value={config.seed ?? ""} placeholder={tr("Random on each new run")} onChange={e => setConfig({ ...config, seed: e.target.value === "" ? null : Number(e.target.value) })} /></label>
        {fields.map(([key, label, min, max]) => <label key={key}>{tr(label)}<input type="number" min={min} max={Number.isFinite(max) ? max : undefined} step="any" required value={config[key] ?? ""} onChange={e => setConfig({ ...config, [key]: Number(e.target.value) })} /></label>)}
      </div><p className="ws-notice">{tr("A stable first 20 seconds supports process diagnosis. Integration step 0.05–1 s; numerical runs use at most 100,000 steps.")}</p><button className="ws-primary" disabled={busy}>{tr("Run new simulation ↗")}</button>
    </form></details>}
    {sessions.length > 0 && <div className="ws-panel runtime-sessionbar"><label>{tr("Saved simulation")}<select value={chosen} onChange={e => setChosen(e.target.value)}>{sessions.map(s => <option value={s.id} key={s.id}>{s.title} · {s.id.slice(0, 8)}</option>)}</select></label>{session && sessionReady && <><label>{tr("Save dataset to workspace")}<select value={saveWorkspace} onChange={e => setSaveWorkspace(e.target.value)}><option value="">{tr("Choose a workspace")}</option>{workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label><button onClick={save} disabled={busy || !saveWorkspace}>{tr("Save dataset & model ↗")}</button>{session.datasetId && <><a className="ws-link" href={`#/workspaces/${session.workspaceId}/datasets/${session.datasetId}`}>{tr("Open Dataset ↗")}</a><a className="ws-link" href={`#/workspaces/${session.workspaceId}/experiments/new/${session.datasetId}`}>{tr("Create detector experiment ↗")}</a></>}</>}</div>}
    {notice && <p className="ws-notice" role="status">{tr(notice)}</p>}
    {chosen && !sessionReady && <p role="status">{tr("Opening selected simulation…")}</p>}
    {session && sessionReady && context && <>
      <section className="ws-panel runtime-timeline" aria-label={tr("Observation window")}><div className="ws-inline ws-between"><h2>{session.title}</h2><span className="ws-muted">{session.rows.length}{" "}{tr("samples · seed")}{" "}{session.config.seed}{" "}{tr("· step")}{" "}{session.config.step}s</span></div>
        {session.config.fault !== "healthy" && session.config.start < 20 && <p className="ws-notice">{tr("The configured fault overlaps the initial 20-second reference interval. Process diagnosis assumes that interval is stable; adjust onset for observation fitting or use an explicit known-model trial.")}</p>}
        <div className="ws-form-grid"><label>{tr("Observation window start (s)")}<input type="number" min={0} max={time} step="any" value={windowStart} onChange={e => setWindowStart(Number(e.target.value))} /></label><label>{tr("Observe through (s)")}<input type="number" min={windowStart} max={session.config.duration} step="any" value={time} onChange={e => setTime(Number(e.target.value))} /></label></div>
        <input aria-label={tr("Observation time")} type="range" min={0} max={session.config.duration} step="any" value={time} onChange={e => setTime(Number(e.target.value))} />
        <p className="ws-muted" aria-live="polite">{analysis ? tr("Showing {0}–{1}s · {2} observed samples", {0: analysis.windowStart, 1: analysis.observedThrough, 2: analysis.samples}) : observation.pending ? tr("Updating evidence for {0}–{1}s…", {0: windowStart, 1: time}) : tr("No diagnosis available for the selected window.")}</p><ErrorText error={observation.error} />
        <div className="ws-inline"><button disabled={!analysis} onClick={() => analysis && exportJSON(`${session.id}-t${analysis.observedThrough}.json`, { sessionId:session.id, title:session.title, hypothesis:currentHypothesis, analysis, rows:session.rows.filter(r => r.t >= analysis.windowStart && r.t <= analysis.observedThrough) })}>{tr("Export observed dossier JSON ↓")}</button><button disabled={!catalog} onClick={() => { const keys=["t", ...catalog!.signals.map(s=>s.key)]; downloadFile(`${session.id}-observations.csv`, keys.join(",")+"\n"+session.rows.filter(r=>r.t>=windowStart&&r.t<=time).map(r=>keys.map(k=>r[k]??"").join(",")).join("\n"), "text/csv"); }}>{tr("Export observations CSV ↓")}</button></div>
      </section>
      <nav className="runtime-tabs" aria-label={tr("Process tools")}>{(Object.keys(labels) as Tab[]).map(t => <button key={t} className={t === tab ? "active" : ""} aria-pressed={tab === t} onClick={() => setTab(t)}>{labels[t]}</button>)}</nav>
      <div className="ws-panel incident-runtime-actions"><h2>{tr("持续事件调查")}</h2>{(workspaceId || session.workspaceId) ? <><p>{tr("把当前工作假设、已完成的工具调查和干预实验保存到事件，后续可从事件返回此模拟会话。")}</p><div className="ws-inline incident-actions"><button disabled={!analysis || !currentHypothesis} onClick={() => setLinking({ source: { kind: "simulation", simulationId: session.id, hypothesis: currentHypothesis, asOf: time, windowStart }, draft: { title: tr("{0} · 调查", {0: session.title}), start: windowStart, end: time, description: tr("工作假设：{0}；观察窗口 {1}–{2}s。", {0: catalog?.faults[currentHypothesis] || currentHypothesis, 1: windowStart, 2: time}) } })}>{tr("将当前候选解释关联到事件")}</button>{runs[0] && <button onClick={() => linkRun(runs[0])}>{tr("关联最近一次已完成结果")}</button>}</div></> : <p>{tr("先将数据和过程模型保存到一个 Workspace，再关联持久事件。")}</p>}</div>
      {analysis?.diagnosis.status === "insufficient_data" && <p className="ws-notice">{tr("Not enough observed data for diagnosis. Include a stable 20-second baseline and at least four seconds of subsequent observations.")}</p>}
      {tab === "evidence" && displayedAnalysis && <EvidenceView incident={{rows:session.rows.filter(r=>r.t>=windowStart && r.t<=time)}} analysis={analysis ?? displayedAnalysis} time={time} hypothesis={currentHypothesis} onHypothesis={selectHypothesis} updating={!analysis} />}
      {tab === "alarms" && displayedAnalysis && <EvidenceResult pending={!analysis}><AlarmView analysis={analysis ?? displayedAnalysis} /></EvidenceResult>}
      {catalog && (tab === "tools" || tab === "interventions") && <label className="runtime-hypothesis">{tr("Working hypothesis · choose any candidate")}<select value={currentHypothesis} disabled={!analysis} onChange={e => selectHypothesis(e.target.value)}><option value="" disabled>{observation.pending ? tr("Updating current-window hypotheses…") : tr("Select a hypothesis")}</option>{Object.entries(catalog.faults).filter(([id]) => id !== "healthy").map(([id, name]) => <option value={id} key={id}>{name}{" "}{tr("· support")}{" "}{analysis?.diagnosis.candidates.find(c => c.id === id)?.score ?? "pending"}</option>)}</select></label>}
      {tab === "tools" && catalog && <ToolConsole key={`${session.id}/${restore?.id || "new"}`} restore={restore} session={session} catalog={catalog} context={context} hypothesis={currentHypothesis} record={record} ready={Boolean(analysis)} />}
      {tab === "interventions" && catalog && <Interventions key={`${session.id}/${restore?.id || "new"}`} restore={restore} session={session} catalog={catalog} context={context} hypothesis={currentHypothesis} record={record} ready={Boolean(analysis)} />}
      {tab === "compare" && <SessionComparison session={session} sessions={sessions} context={context} analysis={analysis} />}
      {tab === "history" && <section className="ws-panel"><h2>{tr("Saved model experiments & investigations")}</h2><p>{tr("Each record retains the observation cutoff, chosen hypothesis, parameters and calculated output.")}</p>{!runs.length && <p className="ws-notice">{tr("Invoke a tool or run an intervention to save an experiment.")}</p>}{runs.map(r => <details key={r.id}><summary>{tr(r.kind)} · {dateLabel(r.createdAt)}{" "}{tr("· as of")}{" "}{String(r.request.asOf)}s</summary><div className="ws-inline incident-actions"><button onClick={() => exportJSON(`${r.id}.json`, r)}>{tr("Export result JSON ↓")}</button><button onClick={() => reopen(r)}>{tr("Reopen context & parameters ↗")}</button>{(workspaceId || session.workspaceId) && <button onClick={() => linkRun(r)}>{tr("关联到事件")}</button>}</div><details><summary>{tr("Saved inputs")}</summary><pre>{JSON.stringify(r.request,null,2)}</pre></details><SavedRunView run={r} /></details>)}</section>}
    </>}
    {linking && (workspaceId || session?.workspaceId) && <IncidentLinkDialog workspaceId={workspaceId || session!.workspaceId!} source={linking.source} draft={linking.draft} onClose={() => setLinking(null)} />}
  </div>;
}

function useRunContext(context: ObservationContext) {
  const key = observationKey(context), active = useRef(key), version = useRef(0);
  active.current = key;
  useEffect(() => () => { version.current++; }, [key]);
  return { key, begin() { const current = ++version.current; return () => active.current === key && version.current === current; } };
}

function ToolConsole({ session, catalog, context, hypothesis, record, restore, ready }: { session: Session; catalog: Catalog; context: ObservationContext; hypothesis:string; record:(r:Run)=>void;restore:Run|null;ready:boolean }) {
  useLocale();
  const initial = (restore?.kind !== "intervention" ? restore?.request.calls : undefined) as {tool:string;args:{signal?:string;controller?:string}}[] | undefined;
  const [tool, setTool] = useState(initial?.[0]?.tool || "inspect_signal_window"), [signal, setSignal] = useState(initial?.[0]?.args.signal || "valve"), [controller, setController] = useState(initial?.[0]?.args.controller || "TIC-101");
  const [comparison, setComparison] = useState("__all");
  const scope = useRunContext(context);
  const [output, setOutput] = useState<{key:string;trace:Trace[];reply:string;provider?:string;limitation?:string} | null>(() => restore && restore.kind !== "intervention" ? { key: observationKey({ sessionId: session.id, asOf: Number(restore.request.asOf ?? session.config.duration), windowStart: Number(restore.request.windowStart || 0) }), trace: (restore.result as { trace?: Trace[] }).trace || [], reply: (restore.result as { summary?: string }).summary || "", provider:(restore.result as {provider?:string}).provider, limitation:(restore.result as {limitation?:string}).limitation } : null), [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState({key:scope.key,busy:false,error:""});
  const busy = status.key === scope.key && status.busy, error = status.key === scope.key ? status.error : "";
  function calls() {
    const args = tool === "inspect_signal_window" || tool === "trace_downstream" ? { signal } : tool === "inspect_controller" ? { controller } : tool === "compare_hypotheses" ? { hypotheses: comparison === "__all" ? Object.keys(catalog.faults).filter(id=>id!=="healthy") : Array.from(new Set([hypothesis,comparison])) } : tool === "simulate_fault" ? { hypothesis } : {};
    return [{ tool, args }];
  }
  async function invoke(assistant = false) {
    if (!ready || !hypothesis) return;
    const isCurrent = scope.begin();
    setStatus({key:scope.key,busy:true,error:""});
    try {
      if (assistant) {
        const data = await api<{summary:string;limitation:string;trace:Trace[];provider:string;record:Run}>("/analyze", { simulationId: session.id, ...context, hypothesis, prompt, calls: calls() });
        record(data.record);
        if (isCurrent()) setOutput({key:scope.key,trace:data.trace,reply:data.summary,provider:data.provider,limitation:data.limitation});
      } else {
        const run = await api<Run>(`/simulations/${session.id}/tools`, { ...context, calls: calls(), hypothesis }); record(run);
        if (isCurrent()) setOutput({key:scope.key,trace:(run.result as {trace:Trace[]}).trace,reply:""});
      }
    } catch (e) { if (isCurrent()) setStatus({key:scope.key,busy:false,error:message(e)}); }
    finally { if (isCurrent()) setStatus(previous => ({...previous,busy:false})); }
  }
  return <section className="ws-panel"><h2>{tr("Invoke an investigation tool")}</h2><div className="ws-form-grid ws-three"><label>{tr("Tool")}<select value={tool} onChange={e => setTool(e.target.value)}>{catalog.tools.map(t => <option value={t} key={t}>{tr(t)}</option>)}</select></label>{["inspect_signal_window", "trace_downstream"].includes(tool) && <label>{tr("Signal")}<select value={signal} onChange={e => setSignal(e.target.value)}>{catalog.signals.map(s => <option key={s.key} value={s.key}>{s.tag} / {s.key}</option>)}</select></label>}{tool === "inspect_controller" && <label>{tr("Control loop")}<select value={controller} onChange={e => setController(e.target.value)}><option>TIC-101</option><option>FIC-102</option></select></label>}{tool === "compare_hypotheses" && <label>{tr("Compare with hypothesis")}<select value={comparison} onChange={e=>setComparison(e.target.value)}><option value="__all">{tr("All twelve hypotheses")}</option>{Object.entries(catalog.faults).filter(([id])=>id!=="healthy").map(([id,name])=><option value={id} key={id}>{tr(name)}</option>)}</select></label>}</div><p className="ws-notice">{tr("Uses observations in")}{" "}{context.windowStart}–{context.asOf}{tr("s. Hypothesis:")}{" "}{tr(hypothesis)}{tr(". Window analysis uses its first 20 seconds as the assumed stable baseline.")}</p><button className="ws-primary" disabled={busy || !ready || !hypothesis} onClick={() => void invoke()}>{tr("Compute tool result & save ↗")}</button>
    <div className="ws-section-heading"><h3>{tr("Analysis assistant")}</h3></div><label>{tr("Question or instruction")}<input value={prompt} onChange={e => setPrompt(e.target.value)} placeholder={tr("Ask about this window and the selected tool")} /></label><p className="ws-muted">{tr("Runs the selected Python tool. An optional configured external model summarizes its results.")}</p><button disabled={busy || !ready || !hypothesis || !prompt.trim()} onClick={() => void invoke(true)}>{tr("Ask using current observations ↗")}</button><ErrorText error={error} />{output && <EvidenceResult pending={!ready || output.key !== scope.key} pendingLabel="Run the tool for the selected observation window to view results.">{output.reply && <p className="ws-notice">{output.provider && `${tr(output.provider)}: `}{output.provider === "local" ? runtimeText(output.reply) : output.reply}{output.limitation && <> {output.provider === "local" ? tr(output.limitation) : output.limitation}</>}</p>}{output.trace.length > 0 && <TraceView analysis={{ trace:output.trace } as Analysis} />}</EvidenceResult>}
  </section>;
}

function Interventions({ session, catalog, context, hypothesis, record, restore, ready }: {session:Session;catalog:Catalog;context:ObservationContext;hypothesis:string;record:(r:Run)=>void;restore:Run|null;ready:boolean}) {
  useLocale();
  const initial = restore?.kind === "intervention" ? restore.request : {};
  const [mode, setMode] = useState((initial.mode as string) || "observed"), [at, setAt] = useState((initial.at as number) ?? context.asOf), [horizon, setHorizon] = useState((initial.horizon as number) ?? session.config.duration);
  const [actions, setActions] = useState((initial.actions as string[]) || ["bypass"]), [parameters, setParameters] = useState<Record<string,number>>(() => (initial.parameters as Record<string,number>) || Object.fromEntries(Object.entries(catalog.actionParameters).map(([k,v])=>[k,v.default])));
  const [search, setSearch] = useState(Boolean(initial.search)), [resolution, setResolution] = useState((initial.search as {resolution:number}|undefined)?.resolution ?? 5);
  const scope = useRunContext(context);
  const [forecast, setForecast] = useState<{key:string;value:Forecast} | null>(() => restore?.kind === "intervention" ? {key:observationKey({sessionId:session.id,asOf:Number(initial.asOf),windowStart:Number(initial.windowStart || 0)}),value:restore.result as Forecast} : null);
  const [previous, setPrevious] = useState<Forecast | null>(null), [status, setStatus] = useState({key:scope.key,busy:false,error:""});
  const busy = status.key === scope.key && status.busy, error = status.key === scope.key ? status.error : "";
  useEffect(() => { setAt(v => Math.max(v, context.asOf)); }, [context.asOf]);
  async function run(e:FormEvent) {
    e.preventDefault();
    if (!ready || !hypothesis || !actions.length) return;
    const isCurrent = scope.begin();
    setStatus({key:scope.key,busy:true,error:""});
    try {
      const r = await api<Run>(`/simulations/${session.id}/interventions`, { ...context, mode, hypothesis, at, horizon, actions, parameters, search: search ? { resolution } : undefined });
      record(r);
      if (isCurrent()) { setPrevious(forecast?.key === scope.key ? forecast.value : null); setForecast({key:scope.key,value:r.result as Forecast}); }
    } catch (e) { if (isCurrent()) setStatus({key:scope.key,busy:false,error:message(e)}); }
    finally { if (isCurrent()) setStatus(previous => ({...previous,busy:false})); }
  }
  const keys = new Set(actions.flatMap(a => applicable[a]));
  return <section className="ws-panel"><h2>{tr("Test a counterfactual")}</h2><form onSubmit={run}><div className="ws-form-grid ws-three"><label>{tr("Model source")}<select value={mode} onChange={e => setMode(e.target.value)}><option value="observed">{tr("Fit only the current observation window")}</option><option value="known">{tr("Known simulator parameters · hypothesis trial")}</option></select></label><label>{tr("Intervention starts at (s)")}<input type="number" min={context.asOf} max={horizon} step="any" value={at} onChange={e => setAt(Number(e.target.value))} required /></label><label>{tr("Prediction ends at (s)")}<input type="number" min={Math.max(context.asOf, at)} step="any" value={horizon} onChange={e => setHorizon(Number(e.target.value))} required /></label></div>
      <fieldset><legend>{tr("Actions to compare")}</legend><div className="ws-option-grid">{catalog.actions.map(a => <label key={a.id}><input type="checkbox" checked={actions.includes(a.id)} onChange={e => setActions(e.target.checked ? [...actions, a.id] : actions.filter(id => id !== a.id))} />{tr(a.name)}</label>)}</div></fieldset>
      <div className="ws-form-grid ws-three">{[...keys].map(k => <label key={k}>{parameterLabels[k]}<input type="number" min={catalog.actionParameters[k].min} max={catalog.actionParameters[k].max} step="any" required value={parameters[k]} onChange={e => setParameters(p => ({ ...p, [k]: Number(e.target.value) }))} /></label>)}</div>
      <div className="ws-form-grid"><label className="ws-inline"><input type="checkbox" checked={search} onChange={e => setSearch(e.target.checked)} />{tr("Search safe intervention start times")}</label>{search && <label>{tr("Search resolution (seconds)")}<input type="number" min={session.config.step} step="any" value={resolution} onChange={e => setResolution(Number(e.target.value))} /></label>}</div>
      <p className="ws-notice">{mode === "observed" ? tr("Fits {0} using only {1}–{2}s. Predictions are conditional on that fitted hypothesis.", {0: hypothesis, 1: context.windowStart, 2: context.asOf}) : tr("Uses your configured simulator parameters with the selected {0} model. This is a known-model experiment.", {0: hypothesis})}{" "}{tr("Pressure limits use physical pressure. All control is simulated.")}</p><ErrorText error={error} /><button className="ws-primary" disabled={busy || !ready || !hypothesis || !actions.length}>{busy ? tr("Computing predictions…") : tr("Run intervention comparison & save ↗")}</button></form>
      {forecast && <EvidenceResult pending={!ready || forecast.key !== scope.key} pendingLabel="Run the intervention for the selected observation window to view predictions."><ForecastView forecast={forecast.value} />{previous && <details><summary>{tr("Compare with previous parameter run ·")}{" "}{previous.mode}{tr(", start")}{" "}{previous.at}s</summary><ForecastView forecast={previous} /></details>}</EvidenceResult>}
    </section>;
}

function ForecastView({ forecast }: {forecast:Forecast}) {
  useLocale();
  const paths = [forecast.baseline, ...forecast.branches];
  const domain: [number, number] = [forecast.threshold, forecast.threshold];
  for (const path of paths) for (const value of path.pressure) { domain[0] = Math.min(domain[0], value); domain[1] = Math.max(domain[1], value); }
  const axis = { kind:"numeric" as const, column:"t", origin:null, start:forecast.baseline.times[0], end:forecast.horizon };
  return <div className="runtime-forecast">{forecast.search && <><h3>{tr("Recovery window search")}</h3><p className="ws-muted">{tr("Grid resolution")}{" "}{forecast.search.resolution}s · {forecast.search.evaluated}{" "}{tr("simulated trials. Latest starts refer to tested grid points.")}</p><table><thead><tr><th>{tr("Action")}</th><th>{tr("Latest tested safe start")}</th><th>{tr("Safe tested intervals")}</th></tr></thead><tbody>{forecast.search.actions.map(a=><tr key={a.id}><td>{tr(a.name)}</td><td>{a.latest == null ? tr("No recoverable trip boundary") : `${a.latest}s`}</td><td>{a.intervals.map(i=>i.join("–")+"s").join(", ") || tr("None")}</td></tr>)}</tbody></table></>}<p className="ws-notice">{tr(forecast.mode)}{" "}{tr("model ·")}{" "}{tr(forecast.hypothesis)}{" "}{tr("· observed through")}{" "}{forecast.observedThrough}{tr("s · action at")}{" "}{forecast.at}{tr("s · forecast to")}{" "}{forecast.horizon}s{forecast.fitError != null && tr(" · normalized fit error {0}", {0: forecast.fitError})}</p><div className="ws-table-scroll"><table><thead><tr><th>{tr("Branch")}</th><th>{tr("Max physical pressure (kPa)")}</th><th>{tr("Simulated limit crossing")}</th><th>{tr("Production loss (%)")}</th><th>{tr("Quality loss (pp)")}</th><th>{tr("Utility use (%·s)")}</th></tr></thead><tbody>{paths.map((p,i) => <tr key={i}><td>{tr(p.action) || tr("No intervention")}</td><td>{number(p.physicalPeak)}</td><td>{p.trip === null ? tr("None in horizon") : `${p.trip}s`}</td><td>{p.productionLoss}</td><td>{p.qualityLoss}</td><td>{p.utilityCost}</td></tr>)}</tbody></table></div>{paths.map((p,i) => <Plot key={i} title={tr("{0} · physical pressure", {0: tr(p.action) || tr("Baseline")})} times={p.times} values={p.pressure} threshold={forecast.threshold} thresholdLabel={tr("pressure limit")} domain={domain} axis={axis} color={i ? "#b5ed9a" : "#e9927d"} />)}<p className="ws-muted">{tr("Conditional reduced-order forecasts; model mismatch is not bounded.")}</p></div>;
}

export function SavedRunView({ run }: { run: RuntimeRun }) {
  useLocale();
  if (isModelForecast(run.result)) return <ModelForecastView forecast={run.result} />;
  if (run.modelId && run.modelId !== "triplens-synthetic-18-v2") return <ModelToolResult run={run} />;
  if (run.kind === "intervention") return <ForecastView forecast={run.result as Forecast} />;
  const result = run.result as { trace?: Trace[]; summary?: string; limitation?: string; provider?: string };
  return <div className="incident-saved-run">{result.summary && <p className="ws-notice">{result.provider === "local" ? runtimeText(result.summary) : result.summary}</p>}{result.trace?.length ? <TraceView analysis={{ trace: result.trace } as Analysis} /> : <p>{tr("此记录没有工具输出。")}</p>}{result.limitation && <p className="ws-muted">{result.provider === "local" ? tr(result.limitation) : result.limitation}</p>}</div>;
}

function SessionComparison({ session, sessions, context, analysis }: {session:Session;sessions:Session[];context:ObservationContext;analysis:Observation|null}) {
  useLocale();
  const [other, setOther] = useState(sessions.find(s => s.id !== session.id)?.id || "");
  const comparison = useObservation(other ? {...context,sessionId:other} : null);
  const result = comparison.analysis;
  return <section className="ws-panel"><h2>{tr("Compare observations at the same time")}</h2><label>{tr("Comparison session")}<select value={other} onChange={e => setOther(e.target.value)}><option value="">{tr("Choose a second simulation")}</option>{sessions.filter(s => s.id !== session.id).map(s => <option value={s.id} key={s.id}>{s.title} · {s.id.slice(0,8)}</option>)}</select></label><ErrorText error={comparison.error} />{comparison.pending && <p role="status">{tr("Updating comparison for the selected observation window…")}</p>}{analysis && result && <><div className="ws-table-scroll"><table><thead><tr><th>{tr("Observed evidence")}</th><th>{session.title}</th><th>{sessions.find(s => s.id === other)?.title}</th></tr></thead><tbody>{[
    [tr("Observed through"), `${analysis.observedThrough}s`, `${result.observedThrough}s`], [tr("Status"),analysis.diagnosis.status,result.diagnosis.status], [tr("Leading hypothesis"),analysis.diagnosis.candidates[0].name,result.diagnosis.candidates[0].name], [tr("Evidence support"),analysis.diagnosis.candidates[0].score,result.diagnosis.candidates[0].score], [tr("Alarm events"),analysis.alarms.eventCount,result.alarms.eventCount], [tr("First detection"),analysis.diagnosis.firstDetection ?? tr("None"),result.diagnosis.firstDetection ?? tr("None")], [tr("Observed propagation paths"),analysis.diagnosis.paths.length,result.diagnosis.paths.length]
  ].map(([name,a,b]) => <tr key={name}><th>{name}</th><td>{a}</td><td>{b}</td></tr>)}</tbody></table></div><button onClick={() => exportJSON("session-comparison.json", { first:session.id, second:other, context, observations:[analysis,result] })}>{tr("Export comparison JSON ↓")}</button></>}</section>;
}
