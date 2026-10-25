import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import { Plot } from "./Charts";
import { downloadFile } from "../lib/download";
import { IncidentLinkDialog, type IncidentDraft } from "./IncidentLinkDialog";
import { ModelForecastView, ModelToolResult, isModelForecast } from "./ModelResults";
import { dateLabel, number, type Dataset, type IncidentSource, type RuntimeRun } from "./types";
import type { ModelSession } from "./modelTypes";

export function ModelSimulation({ workspaceId, session, sessions, runId, initialWindow, onSaved, onDataset }: {
  workspaceId: string; session: ModelSession; sessions: ModelSession[]; runId?: string;
  initialWindow?: {windowStart:number;asOf:number}; onSaved: (dataset: Dataset) => void; onDataset: (dataset: Dataset) => void;
}) {
  const model=session.modelDescriptor;
  const [start,setStart]=useState(initialWindow?.windowStart || 0), [asOf,setAsOf]=useState(initialWindow?.asOf ?? Math.min(93,session.config.duration));
  const [signals,setSignals]=useState(model.signals.slice(0,4).map(s=>s.key));
  const [runs,setRuns]=useState<RuntimeRun[]>([]),[restored,setRestored]=useState<RuntimeRun|null>(null);
  const [tool,setTool]=useState(model.tools[0] || ""),[actions,setActions]=useState(model.actions.slice(0,2).map(a=>a.id));
  const [parameters,setParameters]=useState(Object.fromEntries(Object.entries(model.actionParameters).map(([k,v])=>[k,v.default])));
  const [at,setAt]=useState(Math.min(100,session.config.duration)),[horizon,setHorizon]=useState(session.config.duration);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const [comparison,setComparison]=useState(""),[other,setOther]=useState<ModelSession|null>(null);
  const [linking,setLinking]=useState<{source:IncidentSource;draft:IncidentDraft}|null>(null);
  const [observation,setObservation]=useState<{key:string;result:{observedThrough:number;windowStart:number;samples:number}}|null>(null);
  const [observing,setObserving]=useState(false);
  const active=useRef(true);
  useEffect(()=>{active.current=true;return ()=>{active.current=false;};},[]);
  const key=`${start}/${asOf}`;
  const ready=observation?.key===key && !observing;
  const rows=session.rows.filter(r=>r.t>=start && r.t<=asOf);
  const last=rows[rows.length-1];
  useEffect(()=>{
    const controller=new AbortController();
    api<{runs:RuntimeRun[]}>(`/simulations/${session.id}/runs`,undefined,"GET",controller.signal)
      .then(data=>{if (!controller.signal.aborted) {setRuns(data.runs);const chosen=data.runs.find(r=>r.id===runId);if (chosen) reopen(chosen);}})
      .catch(e=>{if (!controller.signal.aborted) setError(message(e));});
    return ()=>controller.abort();
  },[session.id,runId]);
  useEffect(()=>{
    const controller=new AbortController();setObserving(true);
    api<{observedThrough:number;windowStart:number;samples:number}>(`/simulations/${session.id}/analysis`,{windowStart:start,asOf},"POST",controller.signal)
      .then(result=>{if (!controller.signal.aborted) {setObservation({key,result});setError("");}})
      .catch(e=>{if (!controller.signal.aborted) setError(message(e));}).finally(()=>{if (!controller.signal.aborted) setObserving(false);});
    return ()=>controller.abort();
  },[session.id,start,asOf]);
  useEffect(()=>{
    setOther(null);if (!comparison) return;
    const controller=new AbortController();
    api<ModelSession>(`/simulations/${comparison}`,undefined,"GET",controller.signal).then(s=>{if (!controller.signal.aborted) setOther(s);}).catch(e=>{if (!controller.signal.aborted) setError(message(e));});
    return ()=>controller.abort();
  },[comparison]);
  function reopen(run:RuntimeRun) {
    setStart(Number(run.request.windowStart ?? 0));setAsOf(Number(run.request.asOf ?? session.config.duration));setRestored(run);
    if (run.kind==="intervention") {
      setAt(Number(run.request.at));setHorizon(Number(run.request.horizon));
      setActions(run.request.actions as string[]);
      setParameters(p=>({...p,...run.request.parameters as Record<string,number>}));
    } else {
      const calls=run.request.calls as {tool:string}[] | undefined;
      if (calls?.[0]) setTool(calls[0].tool);
    }
  }
  async function invoke(operation:"tools"|"interventions") {
    setBusy(true);setError("");
    try {
      const body={windowStart:start,asOf,...(operation==="tools" ? {calls:[{tool,args:{}}]} : {mode:"known",hypothesis:session.config.fault,at,horizon,actions,parameters})};
      const run=await api<RuntimeRun>(`/simulations/${session.id}/${operation}`,body);
      if (active.current) {setRuns(previous=>[run,...previous]);setRestored(run);setNotice("Calculated result and its inputs saved to this session.");}
    } catch(e) {setError(message(e));} finally {setBusy(false);}
  }
  async function save() {
    setBusy(true);setError("");
    try {const dataset=await api<Dataset>(`/simulations/${session.id}/save`,{workspaceId});if (active.current) {onDataset(dataset);onSaved(dataset);setNotice("Dataset saved with signal units, model/scenario versions and fault truth.");}}
    catch(e) {setError(message(e));} finally {setBusy(false);}
  }
  function link(run?:RuntimeRun) {
    setLinking({source:run ? {kind:"run",simulationId:session.id,runId:run.id} : {kind:"simulation",simulationId:session.id,windowStart:start,asOf},
      draft:{title:`${session.title} · investigation`,start:run ? Number(run.request.windowStart || 0) : start,end:run ? Number(run.request.asOf) : asOf,description:`${model.name} v${session.modelVersion} · ${session.title}`}});
  }
  const activeParameters=[...new Set(model.actions.filter(a=>actions.includes(a.id)).flatMap(a=>a.parameters))];
  const validRestored=restored && Number(restored.request.windowStart ?? 0)===start && Number(restored.request.asOf ?? session.config.duration)===asOf;
  const sameModel=other?.modelId===session.modelId && other.modelVersion===session.modelVersion;
  const comparisonRows=sameModel ? other.rows.filter(r=>r.t>=start && r.t<=asOf) : [];
  return <div className="model-simulation">
    <section className="ws-panel"><div className="ws-section-heading"><h2>Simulation workspace</h2><span className="ws-kicker">OBSERVATIONS / SECONDS</span></div>
      <div className="ws-form-grid"><label>Window start (s)<input type="number" step="any" min={0} max={asOf} value={start} onChange={e=>setStart(Number(e.target.value))} /></label><label>Observe through (s)<input type="number" step="any" min={start} max={session.config.duration} value={asOf} onChange={e=>setAsOf(Number(e.target.value))} /></label></div>
      <input aria-label="Model observation time" type="range" min={0} max={session.config.duration} step="any" value={asOf} onChange={e=>setAsOf(Number(e.target.value))} />
      <p className="ws-muted" role="status">{ready ? `${observation.result.windowStart}–${observation.result.observedThrough}s · ${observation.result.samples} observed samples` : "Updating observation window…"}</p>
      <div className="ws-inline model-actions"><button disabled={busy} className="ws-primary" onClick={()=>void save()}>Save as Dataset ↗</button><button disabled={!ready} onClick={()=>link()}>Create / link Incident</button><button disabled={!rows.length} onClick={()=>{const keys=["t",...model.signals.map(s=>s.key)];downloadFile(`${session.id}-observations.csv`,keys.join(",")+"\n"+rows.map(r=>keys.map(k=>r[k]).join(",")).join("\n"),"text/csv");}}>Export observations CSV ↓</button></div>
      {session.datasetId && <div className="ws-inline model-actions"><a className="ws-link" href={`#/workspaces/${workspaceId}/datasets/${session.datasetId}`}>Open Dataset ↗</a><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/new/${session.datasetId}`}>Create detector experiment ↗</a></div>}
      {error && <p className="ws-error" role="alert">{error}</p>}{notice && <p className="ws-notice" role="status">{notice}</p>}
    </section>
    <section className="ws-panel"><h2>Measured signals & run comparison</h2><p className="ws-muted">Curves show saved measurements inside the selected window. Comparisons use elapsed seconds from each scenario origin.</p><fieldset><legend>Visible signals</legend><div className="ws-option-grid">{model.signals.map(s=><label key={s.key}><input type="checkbox" checked={signals.includes(s.key)} onChange={e=>setSignals(p=>e.target.checked ? [...p,s.key] : p.filter(k=>k!==s.key))} />{s.label || s.tag} ({s.unit})</label>)}</div></fieldset>
      <label>Compare saved run<select aria-label="Compare saved model run" value={comparison} onChange={e=>setComparison(e.target.value)}><option value="">No comparison</option>{sessions.filter(s=>s.id!==session.id && s.modelId===session.modelId && s.modelVersion===session.modelVersion).map(s=><option key={s.id} value={s.id}>{s.title} · scenario v{s.scenarioVersion || "legacy"} · {s.id.slice(0,6)}</option>)}</select></label>
      {sameModel && <p className="ws-notice">Overlay: {other.title} · scenario v{other.scenarioVersion || "legacy"} · seed {other.config.seed}. Each run retains its own sampling grid and configuration.</p>}
      {signals.map(k=>{const signal=model.signals.find(s=>s.key===k)!;return <Plot key={k} title={`${signal.label || signal.tag} (${signal.unit})`} times={rows.map(r=>r.t)} values={rows.map(r=>r[k])} axis={{kind:"numeric",column:"t",origin:null,start:0,end:session.config.duration}} selectedTime={asOf} overlays={comparisonRows.length ? [{times:comparisonRows.map(r=>r.t),values:comparisonRows.map(r=>r[k]),title:other!.title,color:"#e9927d"}] : []} />;})}
      {last && <div className="ws-table-scroll"><table><thead><tr><th>Signal</th><th>At {last.t}s</th><th>Change in window</th><th>Unit</th></tr></thead><tbody>{model.signals.map(s=><tr key={s.key}><td>{s.label || s.tag}</td><td>{number(last[s.key])}</td><td>{number(last[s.key]-rows[0][s.key])}</td><td>{s.unit}</td></tr>)}</tbody></table></div>}
      {model.capabilities.includes("topology") && <details><summary>Process topology</summary><div className="model-topology" role="img" aria-label={`${model.name} topology`}>{model.edges.map((edge,i)=><div key={i}><b>{edge.source}</b><span> → {edge.kind} → </span><b>{edge.target}</b></div>)}</div></details>}
    </section>
    {model.capabilities.includes("investigation-tools") && <section className="ws-panel"><h2>Investigation tools</h2><div className="ws-form-grid"><label>Investigation tool<select value={tool} onChange={e=>setTool(e.target.value)}>{model.toolDefinitions.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</select></label><div className="model-actions"><button disabled={busy || !ready || !tool} onClick={()=>void invoke("tools")}>Run tool & save</button></div></div><p className="ws-muted">Uses only the selected observation window. Residuals describe evidence and do not identify a fault by themselves.</p></section>}
    {model.capabilities.includes("interventions") && <section className="ws-panel"><h2>Intervention comparison</h2><p className="ws-notice">Uses the saved physical model and fault parameters. This model supports known-model forecasts. All actions are simulated.</p>
      <div className="ws-form-grid"><label>Action time (s)<input type="number" min={asOf} max={horizon} step="any" value={at} onChange={e=>setAt(Number(e.target.value))} /></label><label>Forecast horizon (s)<input type="number" min={Math.max(asOf,at)} step="any" value={horizon} onChange={e=>setHorizon(Number(e.target.value))} /></label></div>
      <fieldset><legend>Actions to compare</legend><div className="ws-option-grid">{model.actions.map(a=><label key={a.id}><input type="checkbox" checked={actions.includes(a.id)} onChange={e=>setActions(p=>e.target.checked ? [...p,a.id] : p.filter(id=>id!==a.id))} />{a.name}</label>)}</div></fieldset>
      <div className="ws-form-grid ws-three">{activeParameters.map(k=>{const p=model.actionParameters[k];return <label key={k}>{p.label}{p.unit ? ` (${p.unit})` : ""}<input type="number" min={p.min} max={p.max} step="any" value={parameters[k]} onChange={e=>setParameters(v=>({...v,[k]:Number(e.target.value)}))} /></label>;})}</div><button className="ws-primary" disabled={busy || !ready || !actions.length || at<asOf || horizon<at} onClick={()=>void invoke("interventions")}>Simulate actions & save comparison ↗</button>
    </section>}
    {restored && <section className="ws-panel"><h2>Saved {restored.kind} result</h2><p>{dateLabel(restored.createdAt)} · {restored.id}</p>{validRestored ? isModelForecast(restored.result) ? <ModelForecastView forecast={restored.result} /> : <ModelToolResult run={restored} /> : <p className="ws-notice">This saved result uses a different observation window. Reopen it to restore its inputs.</p>}<div className="ws-inline model-actions"><button onClick={()=>reopen(restored)}>Reopen result & parameters</button><button onClick={()=>link(restored)}>Link saved result to Incident</button></div></section>}
    <section className="ws-panel"><h2>Saved investigations & interventions</h2>{!runs.length && <p className="ws-muted">Run a tool or intervention to save a record.</p>}{runs.map(run=><details key={run.id}><summary>{run.kind} · {dateLabel(run.createdAt)} · {String(run.request.windowStart || 0)}–{String(run.request.asOf)}s</summary><div className="ws-inline model-actions"><button onClick={()=>reopen(run)}>Reopen inputs & result</button><button onClick={()=>link(run)}>Link to Incident</button><button onClick={()=>downloadFile(`${run.id}.json`,JSON.stringify(run,null,2))}>Export result JSON ↓</button></div><pre>{JSON.stringify(run.request,null,2)}</pre></details>)}</section>
    {linking && <IncidentLinkDialog workspaceId={workspaceId} source={linking.source} draft={linking.draft} onClose={()=>setLinking(null)} />}
  </div>;
}
