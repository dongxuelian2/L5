import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
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
  useLocale();
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
  return <div className="model-workspace"><div className="ws-page-title"><div><div className="ws-kicker">{tr("09 / MODELS & SCENARIOS")}</div><h1>{tr("Model the process")}<span className="ws-accent">.</span></h1><p>{tr("Choose a process model, save a scenario, and investigate its measured response.")}</p></div><span className="ws-badge">{models.length}{" "}{tr("REGISTERED MODELS")}</span></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{loading && <p role="status">{tr("Loading model catalog…")}</p>}
    <div className="model-catalog">{models.map(m => <button key={m.modelId} aria-pressed={m.modelId===modelId} className={`ws-panel model-card ${m.modelId===modelId ? "selected" : ""}`} onClick={() => chooseModel(m.modelId)}><span className="ws-kicker">{tr(m.category)} / v{m.version}</span><h2>{tr(m.name)}</h2><p>{tr(m.description)}</p><div className="model-capabilities">{m.capabilities.map(c => <span key={c}>{tr(c)}</span>)}</div><small>{m.signals.length}{" "}{tr("signals ·")}{" "}{Object.keys(m.faults).length-1}{" "}{tr("faults ·")}{" "}{m.actions.length}{" "}{tr("actions")}</small></button>)}</div>
    {model && <><details className="ws-panel model-descriptor"><summary>{tr(model.name)}{" "}{tr("· signals, parameters and capabilities")}</summary><p>{model.source.url ? <a href={model.source.url} target="_blank" rel="noreferrer">{model.source.name} ↗</a> : model.source.name}</p><p className="ws-muted">{tr("Model ID")}{" "}{model.modelId}{" "}{tr("· version")}{" "}{model.version}</p><div className="ws-table-scroll"><table><thead><tr><th>{tr("Signal")}</th><th>{tr("Key")}</th><th>{tr("Unit")}</th></tr></thead><tbody>{model.signals.map(s => <tr key={s.key}><td>{s.label || s.tag}</td><td>{s.key}</td><td>{s.unit}</td></tr>)}</tbody></table></div><p>{tr("Faults:")}{" "}{Object.values(model.faults).map(label => tr(label)).join(" · ")}</p><p>{tr("Actions:")}{" "}{model.actions.map(a => tr(a.name)).join(" · ") || tr("None")}</p><p>{tr("Investigation:")}{" "}{model.toolDefinitions.map(t => tr(t.name)).join(" · ") || tr("None")}</p><ul>{model.limitations.map(l => <li key={l}>{tr(l)}</li>)}</ul></details>
      <section className="ws-panel model-navigation"><div className="ws-form-grid"><label>{tr("Saved scenarios")}<select aria-label={tr("Saved scenarios")} value={scenario?.modelId===modelId ? scenario.id : ""} onChange={e => {const chosen=scenarios.find(s => s.id===e.target.value);if (chosen) selectScenario(chosen);else {setScenario(null);setEditorKey(k=>k+1);setEditorOpen(true);}}}><option value="">{tr("New scenario")}</option>{scenarios.filter(s => s.modelId===modelId).map(s => <option key={s.id} value={s.id}>{s.name}{" "}{tr("· latest v")}{s.version}</option>)}</select></label><label>{tr("Saved model session")}<select aria-label={tr("Saved model session")} value={session?.id || simulationId || ""} onChange={e => {if (e.target.value) go(`workspaces/${workspaceId}/simulations/${e.target.value}`);}}><option value="">{tr("Choose a session")}</option>{sessions.filter(s => s.modelId===modelId).map(s => <option key={s.id} value={s.id}>{s.title} · {s.scenarioVersion ? `v${s.scenarioVersion}` : tr("legacy")} · {dateLabel(s.createdAt)} · {s.id.slice(0,6)}</option>)}</select></label></div><div className="ws-inline model-actions"><button onClick={() => setEditorOpen(!editorOpen)}>{editorOpen ? tr("Hide scenario editor") : tr("Open scenario editor")}</button><button onClick={() => {setScenario(null);setEditorKey(k=>k+1);setEditorOpen(true);}}>{tr("New scenario")}</button></div></section>
      {editorOpen && <ScenarioEditor key={`${modelId}/${editorKey}`} workspaceId={workspaceId} model={model} scenario={scenario} onSaved={savedScenario} onSelect={selectScenario} onRun={run} />}
    </>}
    {opening && <p role="status">{tr("Opening saved model session…")}</p>}
    {session && !opening && <><section className="ws-panel model-provenance"><div className="ws-kicker">{tr("SAVED MODEL SESSION /")}{" "}{tr(session.status)}</div><h2>{session.title}</h2><p>{tr(session.modelDescriptor.name)} v{session.modelVersion}{" "}{tr("· scenario")}{" "}{session.scenarioId || tr("legacy / direct configuration")}{session.scenarioVersion ? ` v${session.scenarioVersion}` : ""} · {session.rows.length}{" "}{tr("observations · seed")}{" "}{session.config.seed}</p><details><summary>{tr("Run configuration & fault truth")}</summary><pre>{JSON.stringify({config:session.config,groundTruth:session.groundTruth},null,2)}</pre></details></section>
      {session.modelId === "triplens-synthetic-18-v2" && session.modelDescriptor.capabilities.includes("diagnosis") ? <Suspense fallback={<p>{tr("Opening professional investigation…")}</p>}><TripLensWorkbench key={session.id} embedded workspaceId={workspaceId} simulationId={session.id} runId={runId} initialWindow={initialWindow} onSaved={onSaved} /></Suspense> : <ModelSimulation key={session.id} workspaceId={workspaceId} session={session} sessions={sessions} runId={runId} initialWindow={initialWindow} onSaved={onSaved} onDataset={d => setSession(s => s ? {...s,datasetId:d.id} : s)} />}
    </>}
    <details className="model-research-fold" open={!session}><summary>{tr("Research across models")}</summary><ModelResearch workspaceId={workspaceId} /></details>
  </div>;
}
