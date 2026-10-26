import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useState } from "react";
import { api, message } from "./api";
import { number } from "./types";

type ResearchRow={experimentId:string;experimentName:string;runId:string;taskId:string;datasetId:string;datasetName:string;
  models:{id:string;name:string;version:string;scenarioId:string|null;scenarioVersion:number|null}[];algorithm:string;status:string;resultId:string|null;labelVersion:number|null;
  metrics:{behavior:{alarmSamples:number;validSamples:number;coverageFraction:number};labelled:null|{sample:{precision:number|null;recall:number|null;f1:number|null}}}|null};

export function ModelResearch({workspaceId}:{workspaceId:string}) {
  useLocale();
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
  return <section className="ws-panel model-research"><div className="ws-section-heading"><h2>{tr("Research across models")}</h2><button onClick={()=>setRevision(n=>n+1)}>{tr("Refresh research results")}</button></div>
    <p className="ws-muted">{tr("Compare saved detection behavior and labelled evaluation while retaining each dataset, model, scenario and label version. Physical signals and detector score scales differ between processes.")}</p>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{!rows.length && <p>{tr("Save a model Dataset and run an Experiment to add research results.")}</p>}
    {rows.length>0 && <div className="ws-table-scroll"><table><thead><tr><th>{tr("Model / scenario")}</th><th>{tr("Dataset / experiment")}</th><th>{tr("Algorithm / status")}</th><th>{tr("Alarms / valid samples")}</th><th>{tr("Precision / Recall / F1")}</th><th>{tr("Label version")}</th></tr></thead><tbody>{rows.map(row=><tr key={row.taskId}><td>{row.models.map((m,i)=><div key={i}>{tr(m.name || m.id)} v{m.version || "legacy"}<br/><small>{m.scenarioId ? `${m.scenarioId.slice(0,8)} v${m.scenarioVersion}` : tr("Direct / legacy scenario")}</small></div>)}</td><td><a className="ws-link" href={`#/workspaces/${workspaceId}/experiments/${row.experimentId}`}>{row.experimentName}</a><br/>{row.datasetName}<br/><small>{tr("run")}{" "}{row.runId.slice(0,8)}{" "}{tr("· task")}{" "}{row.taskId.slice(0,8)}</small></td><td>{row.resultId ? <a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${row.resultId}`}>{row.algorithm}</a> : row.algorithm}<br/>{tr(row.status)}</td><td>{row.metrics ? tr("{0} / {1} · {2}% coverage", {0: row.metrics.behavior.alarmSamples, 1: row.metrics.behavior.validSamples, 2: number(row.metrics.behavior.coverageFraction*100)}) : "—"}</td><td>{row.metrics?.labelled ? [row.metrics.labelled.sample.precision,row.metrics.labelled.sample.recall,row.metrics.labelled.sample.f1].map(ratio).join(" / ") : tr("Unlabelled behavior")}</td><td>{row.labelVersion || tr("None")}</td></tr>)}</tbody></table></div>}
    {scope && <p className="ws-muted">{tr(scope)}{truncated ? tr(" Some older tasks are omitted; open the saved experiments for the complete history.") : ""}</p>}
  </section>;
}
