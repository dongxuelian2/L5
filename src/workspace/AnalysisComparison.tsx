import { useEffect, useState } from "react";
import { api, message } from "./api";
import { Plot } from "./Charts";
import { number, type AnalysisResult, type Dataset, type Job } from "./types";

export function AnalysisComparison({jobs,datasets}:{jobs:Job[];datasets:Dataset[]}) {
  const [ids,setIds]=useState<string[]>([]),[results,setResults]=useState<AnalysisResult[]>([]),[error,setError]=useState("");
  useEffect(()=>{
    const controller=new AbortController(); setError("");
    Promise.all(ids.map(id=>api<AnalysisResult>(`/analyses/${id}`,undefined,"GET",controller.signal))).then(setResults).catch(e=>{if(!controller.signal.aborted)setError(message(e));});
    return ()=>controller.abort();
  },[ids.join(",")]);
  return <details className="ws-panel"><summary>Compare saved algorithms and parameters</summary><div className="ws-option-grid">{jobs.map(j=><label key={j.id}><input type="checkbox" checked={ids.includes(j.id)} onChange={e=>setIds(e.target.checked?[...ids,j.id]:ids.filter(id=>id!==j.id))} />{j.name} · {j.id.slice(0,6)}</label>)}</div>{error&&<p className="ws-error" role="alert">{error}</p>}
    {results.length>0&&<><div className="ws-table-scroll"><table><thead><tr><th>Run</th><th>Dataset / window</th><th>Threshold</th><th>Alarm samples</th><th>First alarm</th><th>Abstained</th><th>Peak score</th></tr></thead><tbody>{results.map(r=><tr key={r.id}><td><a className="ws-link" href={`#/workspaces/${r.workspaceId}/analysis/${r.id}`}>{r.name}</a></td><td>{datasets.find(d=>d.id===r.datasetId)?.name} · {r.config.analysisRange.join("–")}s</td><td>{number(r.threshold)}</td><td>{r.summary.flaggedSamples}</td><td>{r.summary.firstDetection??"None"}</td><td>{r.summary.abstainedSamples??0}</td><td>{number(r.summary.peakScore)}</td></tr>)}</tbody></table></div><p className="ws-muted">Each plot uses its own calibrated score scale. Compare runs on matching data windows for an algorithm comparison.</p>{results.map(r=>{const d=datasets.find(d=>d.id===r.datasetId);return d&&<Plot key={r.id} title={`${r.name} · ${r.algorithmLabel}`} times={r.times} values={r.scores.map((s,i)=>r.states?.[i]==="abstain"?null:s)} threshold={r.threshold} axis={d.metadata.time} />;})}</>}
  </details>;
}
