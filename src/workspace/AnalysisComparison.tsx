import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useState } from "react";
import { api, message } from "./api";
import { Plot } from "./Charts";
import { number, type AnalysisResult, type Dataset, type Job } from "./types";

export function AnalysisComparison({jobs,datasets}:{jobs:Job[];datasets:Dataset[]}) {
  useLocale();
  const [ids,setIds]=useState<string[]>([]),[results,setResults]=useState<AnalysisResult[]>([]),[error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController(); setError("");
    Promise.all(ids.map(id=>api<AnalysisResult>(`/analyses/${id}`,undefined,"GET",controller.signal))).then(setResults).catch(e=>{if(!controller.signal.aborted)setError(message(e));});
    return ()=>controller.abort();
  },[ids.join(",")]);
  return <details className="ws-panel"><summary>{tr("Compare saved algorithms and parameters")}</summary><div className="ws-option-grid">{jobs.map(j=><label key={j.id}><input type="checkbox" checked={ids.includes(j.id)} onChange={e=>setIds(e.target.checked?[...ids,j.id]:ids.filter(id=>id!==j.id))} />{j.name} · {j.id.slice(0,6)}</label>)}</div>{error&&<p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {results.length>0&&<><div className="ws-table-scroll"><table><thead><tr><th>{tr("Run")}</th><th>{tr("Dataset / window")}</th><th>{tr("Threshold")}</th><th>{tr("Alarm samples")}</th><th>{tr("First alarm")}</th><th>{tr("Abstained")}</th><th>{tr("Peak score")}</th></tr></thead><tbody>{results.map(r=><tr key={r.id}><td><a className="ws-link" href={`#/workspaces/${r.workspaceId}/analysis/${r.id}`}>{r.name}</a></td><td>{datasets.find(d=>d.id===r.datasetId)?.name} · {r.config.analysisRange.join("–")}s</td><td>{number(r.threshold)}</td><td>{r.summary.flaggedSamples}</td><td>{r.summary.firstDetection??tr("None")}</td><td>{r.summary.abstainedSamples??0}</td><td>{number(r.summary.peakScore)}</td></tr>)}</tbody></table></div><p className="ws-muted">{tr("Each plot uses its own calibrated score scale. Compare runs on matching data windows for an algorithm comparison.")}</p>{results.map(r=>{const d=datasets.find(d=>d.id===r.datasetId);return d&&<Plot key={r.id} title={`${r.name} · ${tr(r.algorithmLabel)}`} times={r.times} values={r.scores.map((s,i)=>r.states?.[i]==="abstain"?null:s)} threshold={r.threshold} axis={d.metadata.time} />;})}</>}
  </details>;
}
