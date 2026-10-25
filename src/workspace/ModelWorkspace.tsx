import { lazy, Suspense, useEffect, useState } from "react";
import { api, go, message } from "./api";
import { dateLabel, type Dataset } from "./types";
import type { ModelDescriptor, ModelSession, Scenario } from "./modelTypes";
import { ScenarioEditor } from "./ScenarioEditor";
import { ModelSimulation } from "./ModelSimulation";
import { ModelResearch } from "./ModelResearch";
import "./models.css";

const TripLensWorkbench = lazy(() => import("./RuntimeWorkbench").then(m => ({default:m.RuntimeWorkbench})));

export function ModelWorkspace({ workspaceId, simulationId, runId, initialWindow, onSaved }: {
  workspaceId: string; simulationId?: string; runId?: string; initialWindow?: {windowStart:number;asOf:number;hypothesis?:string}; onSaved: (dataset: Dataset) => void;
}) {
  const [models,setModels] = useState<ModelDescriptor[]>([]), [scenarios,setScenarios] = useState<Scenario[]>([]), [sessions,setSessions] = useState<ModelSession[]>([]);
  const [modelId,setModelId] = useState(""), [scenario,setScenario] = useState<Scenario|null>(null), [session,setSession] = useState<ModelSession|null>(null);
  const [error,setError] = useState(""), [loading,setLoading] = useState(true), [opening,setOpening] = useState(false), [editorOpen,setEditorOpen] = useState(true);
  const [editorKey,setEditorKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<{models:ModelDescriptor[]}>("/models",undefined,"GET",controller.signal),api<{scenarios:Scenario[]}>(`/workspaces/${workspaceId}/scenarios`,undefined,"GET",controller.signal),api<{simulations:ModelSession[]}>(`/simulations?workspaceId=${workspaceId}`,undefined,"GET",controller.signal)])
      .then(([m,s,r]) => { if (controller.signal.aborted) return;setModels(m.models);setScenarios(s.scenarios);setSessions(r.simulations);setModelId(id => id || m.models[0]?.modelId || ""); })
      .catch(e => {if (!controller.signal.aborted) setError(message(e));}).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  },[workspaceId]);
  useEffect(() => {
    if (!simulationId) {setSession(null);setOpening(false);return;}
    const controller = new AbortController();setOpening(true);setSession(null);setError("");
    api<ModelSession>(`/simulations/${simulationId}`,undefined,"GET",controller.signal).then(s => {
      if (controller.signal.aborted) return;
      setSession(s);setModelId(s.modelId);setScenario(s.scenarioSnapshot || null);setEditorOpen(false);
    }).catch(e => {if (!controller.signal.aborted) setError(message(e));}).finally(() => {if (!controller.signal.aborted) setOpening(false);});
    return () => controller.abort();
  },[simulationId,workspaceId]);
  const model = models.find(m => m.modelId===modelId);
  function chooseModel(id: string) {setModelId(id);setSession(null);setScenario(null);setEditorKey(k=>k+1);setEditorOpen(true);go(`workspaces/${workspaceId}/models`);}
  function savedScenario(next: Scenario) {setScenarios(previous => [next,...previous.filter(s => s.id!==next.id)]);setScenario(next);}
  function run(next: ModelSession) {setSessions(previous => [next,...previous]);setSession(next);setEditorOpen(false);go(`workspaces/${workspaceId}/simulations/${next.id}`);}
  function selectScenario(next: Scenario) {setScenario(next);setModelId(next.modelId);setEditorKey(k=>k+1);setEditorOpen(true);}
  return <div className="model-workspace"><div className="ws-page-title"><div><div className="ws-kicker">09 / MODELS & SCENARIOS</div><h1>Model the process<span className="ws-accent">.</span></h1><p>Choose a process model, save a scenario, and investigate its measured response.</p></div><span className="ws-badge">{models.length} REGISTERED MODELS</span></div>
    {error && <p className="ws-error" role="alert">{error}</p>}{loading && <p role="status">Loading model catalog…</p>}
    <div className="model-catalog">{models.map(m => <button key={m.modelId} aria-pressed={m.modelId===modelId} className={`ws-panel model-card ${m.modelId===modelId ? "selected" : ""}`} onClick={() => chooseModel(m.modelId)}><span className="ws-kicker">{m.category} / v{m.version}</span><h2>{m.name}</h2><p>{m.description}</p><div className="model-capabilities">{m.capabilities.map(c => <span key={c}>{c}</span>)}</div><small>{m.signals.length} signals · {Object.keys(m.faults).length-1} faults · {m.actions.length} actions</small></button>)}</div>
    {model && <><details className="ws-panel model-descriptor"><summary>{model.name} · signals, parameters and capabilities</summary><p>{model.source.url ? <a href={model.source.url} target="_blank" rel="noreferrer">{model.source.name} ↗</a> : model.source.name}</p><p className="ws-muted">Model ID {model.modelId} · version {model.version}</p><div className="ws-table-scroll"><table><thead><tr><th>Signal</th><th>Key</th><th>Unit</th></tr></thead><tbody>{model.signals.map(s => <tr key={s.key}><td>{s.label || s.tag}</td><td>{s.key}</td><td>{s.unit}</td></tr>)}</tbody></table></div><p>Faults: {Object.values(model.faults).join(" · ")}</p><p>Actions: {model.actions.map(a => a.name).join(" · ") || "None"}</p><p>Investigation: {model.toolDefinitions.map(t => t.name).join(" · ") || "None"}</p><ul>{model.limitations.map(l => <li key={l}>{l}</li>)}</ul></details>
      <section className="ws-panel model-navigation"><div className="ws-form-grid"><label>Saved scenarios<select aria-label="Saved scenarios" value={scenario?.modelId===modelId ? scenario.id : ""} onChange={e => {const chosen=scenarios.find(s => s.id===e.target.value);if (chosen) selectScenario(chosen);else {setScenario(null);setEditorKey(k=>k+1);setEditorOpen(true);}}}><option value="">New scenario</option>{scenarios.filter(s => s.modelId===modelId).map(s => <option key={s.id} value={s.id}>{s.name} · latest v{s.version}</option>)}</select></label><label>Saved model session<select aria-label="Saved model session" value={session?.id || simulationId || ""} onChange={e => {if (e.target.value) go(`workspaces/${workspaceId}/simulations/${e.target.value}`);}}><option value="">Choose a session</option>{sessions.filter(s => s.modelId===modelId).map(s => <option key={s.id} value={s.id}>{s.title} · {s.scenarioVersion ? `v${s.scenarioVersion}` : "legacy"} · {dateLabel(s.createdAt)} · {s.id.slice(0,6)}</option>)}</select></label></div><div className="ws-inline model-actions"><button onClick={() => setEditorOpen(!editorOpen)}>{editorOpen ? "Hide scenario editor" : "Open scenario editor"}</button><button onClick={() => {setScenario(null);setEditorKey(k=>k+1);setEditorOpen(true);}}>New scenario</button></div></section>
      {editorOpen && <ScenarioEditor key={`${modelId}/${editorKey}`} workspaceId={workspaceId} model={model} scenario={scenario} onSaved={savedScenario} onSelect={selectScenario} onRun={run} />}
    </>}
    {opening && <p role="status">Opening saved model session…</p>}
    {session && !opening && <><section className="ws-panel model-provenance"><div className="ws-kicker">SAVED MODEL SESSION / {session.status}</div><h2>{session.title}</h2><p>{session.modelDescriptor.name} v{session.modelVersion} · scenario {session.scenarioId || "legacy / direct configuration"}{session.scenarioVersion ? ` v${session.scenarioVersion}` : ""} · {session.rows.length} observations · seed {session.config.seed}</p><details><summary>Run configuration & fault truth</summary><pre>{JSON.stringify({config:session.config,groundTruth:session.groundTruth},null,2)}</pre></details></section>
      {session.modelId === "triplens-synthetic-18-v2" && session.modelDescriptor.capabilities.includes("diagnosis") ? <Suspense fallback={<p>Opening professional investigation…</p>}><TripLensWorkbench key={session.id} embedded workspaceId={workspaceId} simulationId={session.id} runId={runId} initialWindow={initialWindow} onSaved={onSaved} /></Suspense> : <ModelSimulation key={session.id} workspaceId={workspaceId} session={session} sessions={sessions} runId={runId} initialWindow={initialWindow} onSaved={onSaved} onDataset={d => setSession(s => s ? {...s,datasetId:d.id} : s)} />}
    </>}
    <details className="model-research-fold" open={!session}><summary>Research across models</summary><ModelResearch workspaceId={workspaceId} /></details>
  </div>;
}
