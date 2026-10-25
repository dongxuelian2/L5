import { useEffect, useState } from "react";
import { api, message } from "./api";
import { number } from "./types";

type ResearchRow={experimentId:string;experimentName:string;runId:string;taskId:string;datasetId:string;datasetName:string;
  models:{id:string;name:string;version:string;scenarioId:string|null;scenarioVersion:number|null}[];algorithm:string;status:string;resultId:string|null;labelVersion:number|null;
  metrics:{behavior:{alarmSamples:number;validSamples:number;coverageFraction:number};labelled:null|{sample:{precision:number|null;recall:number|null;f1:number|null}}}|null};

export function ModelResearch({workspaceId}:{workspaceId:string}) {
  const [rows,setRows]=useState<ResearchRow[]>([]),[scope,setScope]=useState("");
  const [error,setError]=useState(""),[revision,setRevision]=useState(0),[truncated,setTruncated]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();
    api<{rows:ResearchRow[];scope:string;truncated:boolean}>(`/workspaces/${workspaceId}/model-research`,undefined,"GET",controller.signal)
      .then(data=>{if(!controller.signal.aborted) {setRows(data.rows || []);setScope(data.scope);setTruncated(data.truncated);setError("");}})
      .catch(e=>{if(!controller.signal.aborted) setError(message(e));});
    return ()=>controller.abort();
  },[workspaceId,revision]);
  const ratio=(value:number|null|undefined)=>value==null ? "—" : number(value);
  return <section className="ws-panel model-research"><div className="ws-section-heading"><h2>Research across models</h2><button onClick={()=>setRevision(n=>n+1)}>Refresh research results</button></div>
    <p className="ws-muted">Compare saved detection behavior and labelled evaluation while retaining each dataset, model, scenario and label version. Physical signals and detector score scales differ between processes.</p>
    {error && <p className="ws-error" role="alert">{error}</p>}{!rows.length && <p>Save a model Dataset and run an Experiment to add research results.</p>}
    {rows.length>0 && <div className="ws-table-scroll"><table><thead><tr><th>Model / scenario</th><th>Dataset / experiment</th><th>Algorithm / status</th><th>Alarms / valid samples</th><th>Precision / Recall / F1</th><th>Label version</th></tr></thead><tbody>{rows.map(row=><tr key={row.taskId}><td>{row.models.map((m,i)=><div key={i}>{m.name || m.id} v{m.version || "legacy"}<br/><small>{m.scenarioId ? `${m.scenarioId.slice(0,8)} v${m.scenarioVersion}` : "Direct / legacy scenario"}</small></div>)}</td><td><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${row.experimentId}`}>{row.experimentName}</a><br/>{row.datasetName}<br/><small>run {row.runId.slice(0,8)} · task {row.taskId.slice(0,8)}</small></td><td>{row.resultId ? <a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${row.resultId}`}>{row.algorithm}</a> : row.algorithm}<br/>{row.status}</td><td>{row.metrics ? `${row.metrics.behavior.alarmSamples} / ${row.metrics.behavior.validSamples} · ${number(row.metrics.behavior.coverageFraction*100)}% coverage` : "—"}</td><td>{row.metrics?.labelled ? [row.metrics.labelled.sample.precision,row.metrics.labelled.sample.recall,row.metrics.labelled.sample.f1].map(ratio).join(" / ") : "Unlabelled behavior"}</td><td>{row.labelVersion || "None"}</td></tr>)}</tbody></table></div>}
    {scope && <p className="ws-muted">{scope}{truncated ? " Some older tasks are omitted; open the saved experiments for the complete history." : ""}</p>}
  </section>;
}
