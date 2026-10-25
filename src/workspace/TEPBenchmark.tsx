import { useState } from "react";
import { algorithms } from "./AlgorithmControls";
import { number, type Dataset } from "./types";
import type { BenchmarkCell, ExperimentComparisonData } from "./experimentTypes";

const value = (v: number | null | undefined) => v == null ? "—" : number(v);
export function TEPBenchmark({ data, datasets = [], onSelect }: { data: ExperimentComparisonData; datasets?: Dataset[]; onSelect: (ids: string[]) => void }) {
  const [metric, setMetric] = useState("event"), [batch, setBatch] = useState(""), [run, setRun] = useState("");
  const summary = data.benchmark;
  if (!summary?.cells.length) return null;
  const batchId = batch || data.experiment.runs[0]?.id;
  const cells = summary.cells.filter(c => c.runId === batchId);
  const faults = [...new Set(cells.map(c => c.faultNumber))].sort((a,b) => a-b);
  const columns = [...new Set(cells.map(c => c.condition))];
  const tasks = data.tasks.filter(t => t.run_id === batchId && t.external);
  const trajectories = [...new Map(tasks.map(t => [t.datasetId, t])).values()];
  function display(cell: BenchmarkCell) {
    if (metric === "event") return cell.event.eligibleEvents ? `${cell.event.detectedEvents}/${cell.event.eligibleEvents} events` : "No eligible events";
    if (metric === "recall") return value(cell.sample.recall);
    if (metric === "far") return value(cell.sample.falseAlarmRate);
    if (metric === "coverage") return value(cell.coverage);
    return `${value(cell.delay.median)} s`;
  }
  return <section id="experiment-benchmark" className="ws-panel tep-benchmark" aria-label="TEP benchmark dashboard"><div className="ws-section-heading"><h2>TEP / Fault × algorithm</h2><span className="ws-kicker">INDEPENDENT RUNS</span></div><p>{summary.rules}</p>
    <div className="ws-form-grid"><label>Benchmark batch<select value={batchId} onChange={e => { setBatch(e.target.value); setRun(""); }}>{data.experiment.runs.map(r => <option key={r.id} value={r.id}>{r.id.slice(0,8)} · {r.status}</option>)}</select></label><label>Matrix metric<select value={metric} onChange={e => setMetric(e.target.value)}><option value="event">Event detection / eligible events</option><option value="recall">Sample recall</option><option value="far">False alarm rate on labelled normal samples</option><option value="delay">First detection delay · median seconds</option><option value="coverage">Valid observation coverage</option></select></label></div>
    <div className="ws-table-scroll"><table><thead><tr><th>Fault</th>{columns.map(key => <th key={key}>{algorithms[JSON.parse(key).algorithm]}{columns.filter(k => JSON.parse(k).algorithm === JSON.parse(key).algorithm).length > 1 && <small>{key}</small>}</th>)}</tr></thead><tbody>{faults.map(f => <tr key={f}><th>{f === 0 ? "0 · normal" : f}</th>{columns.map(key => { const c = cells.find(c => c.faultNumber === f && c.condition === key); return <td key={key}>{c ? <><strong>{display(c)}</strong><small>{c.succeeded}/{c.runCount} runs · {c.failed} failed · {c.labelledRuns} labelled</small><details><summary>Distribution / counts</summary><p>TP/FP/TN/FN: {c.sample.TP}/{c.sample.FP}/{c.sample.TN}/{c.sample.FN}</p><p>Precision {value(c.sample.precision)} · F1 {value(c.sample.f1)}</p><p>Delay {value(c.delay.minimum)}–{value(c.delay.maximum)} s · n={c.delay.n}; missed {c.event.missedEvents}, unobserved {c.event.unobservedEvents}</p><p>Run recall median {value(c.recall.median)}, range {value(c.recall.minimum)}–{value(c.recall.maximum)} · n={c.recall.n}</p><p>Run FAR median {value(c.falseAlarmRate.median)}, range {value(c.falseAlarmRate.minimum)}–{value(c.falseAlarmRate.maximum)} · n={c.falseAlarmRate.n}</p><p>Alarm duration median {value(c.alarmDuration.median)} s, range {value(c.alarmDuration.minimum)}–{value(c.alarmDuration.maximum)} · n={c.alarmDuration.n}</p><p>Abstain {value(c.abstainFraction)} · score time median {value(c.durationMs.median)} ms</p></details></> : "—"}</td>; })}</tr>)}</tbody></table></div>
    <h3>Inspect one independent trajectory</h3><label>Fault / simulationRun<select value={run} onChange={e => setRun(e.target.value)}><option value="">Choose a test trajectory</option>{trajectories.map(t => <option key={t.datasetId} value={t.datasetId}>Fault {t.external!.faultNumber} · simulationRun {t.external!.simulationRun} · {t.datasetName}</option>)}</select></label><button disabled={!run} onClick={() => onSelect(tasks.filter(t => t.datasetId === run && t.status === "succeeded").slice(0,12).map(t => t.id))}>Compare algorithms for this trajectory</button>
    {run && <p><a className="ws-link" href={`#/workspaces/${data.experiment.workspace_id}/explorer/${(datasets.find(d => d.id === run) || data.analyses.find(a => a.dataset.id === run)?.dataset)?.metadata.columns.map(c => c.id).filter(Boolean).join(",") || ""}`}>Open Signal Explorer ↗</a> · Published injection {tasks.find(t => t.datasetId === run)?.external?.faultOnsetSeconds ?? "none"} s</p>}
  </section>;
}
