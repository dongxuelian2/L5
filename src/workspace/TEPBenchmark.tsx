import { t as tr, useLocale } from "../i18n";
import { useState } from "react";
import { algorithms } from "./AlgorithmControls";
import { number, type Dataset } from "./types";
import type { AlarmBurden, BenchmarkCell, DetectionWindow, ExperimentComparisonData } from "./experimentTypes";

const value = (v: number | null | undefined) => v == null ? "—" : number(v);
export type StudyCell = BenchmarkCell & { configuration?: string; windows?: Record<string, DetectionWindow>; burden?: Record<string, AlarmBurden>; unresolvedRuns?: number; pending?: number; delayDistribution?: Record<string,number> };

export function MatrixMetric({ metric, setMetric }: { metric: string; setMetric: (value: string) => void }) {
  useLocale();
  return <label>{tr("Matrix metric")}<select value={metric} onChange={e => setMetric(e.target.value)}>
    <option value="event">{tr("Event detection / eligible events")}</option><option value="1800">{tr("Detected within 30 minutes")}</option><option value="3600">{tr("Detected within 1 hour")}</option><option value="14400">{tr("Detected within 4 hours")}</option><option value="eventual">{tr("Eventual detection / all declared events")}</option>
    <option value="recall">{tr("Sample recall")}</option><option value="far">{tr("False alarm rate on labelled normal samples")}</option><option value="normalBurden">{tr("Normal alarm samples / episodes / seconds")}</option><option value="delay">{tr("First detection delay · median seconds")}</option><option value="sustained">{tr("Post-onset alarm fraction")}</option><option value="coverage">{tr("Valid observation coverage")}</option>
  </select></label>;
}

export function FaultMatrix({ cells, metric, onCell }: { cells: StudyCell[]; metric: string; onCell?: (cell: StudyCell) => void }) {
  useLocale();
  const faults = [...new Set(cells.map(c => c.faultNumber))].sort((a,b) => a-b);
  const columns = [...new Set(cells.map(c => c.condition))];
  function display(cell: StudyCell) {
    if (["1800","3600","14400","eventual"].includes(metric)) { const w = cell.windows?.[metric]; return w ? tr("{0}/{1} events", {0: w.detectedEvents, 1: w.totalEvents}) : tr("Not recorded"); }
    if (metric === "event") return cell.event.eligibleEvents ? tr("{0}/{1} events", {0: cell.event.detectedEvents, 1: cell.event.eligibleEvents}) : tr("No eligible events");
    if (metric === "recall") return value(cell.sample.recall);
    if (metric === "far") return value(cell.sample.falseAlarmRate);
    if (metric === "coverage") return value(cell.coverage);
    if (metric === "normalBurden") { const b = cell.burden?.normal; return b ? tr("{0}/{1} samples · {2} episodes · {3} s", {0: b.alarmSamples, 1: b.observedSamples, 2: b.alarmEvents, 3: value(b.alarmDuration)}) : tr("Not recorded"); }
    if (metric === "sustained") return value(cell.burden?.postInjection.alarmFraction);
    return `${value(cell.delay.median)} s`;
  }
  return <div className="ws-table-scroll"><table className="tep-fault-matrix"><thead><tr><th>{tr("Fault")}</th>{columns.map(key => <th key={key}>{algorithms[JSON.parse(key).algorithm]}{columns.filter(k => JSON.parse(k).algorithm === JSON.parse(key).algorithm).length > 1 && <small>{key}</small>}</th>)}</tr></thead><tbody>{faults.map(f => <tr key={f}><th>{f === 0 ? tr("0 · normal") : f}</th>{columns.map(key => { const c = cells.find(c => c.faultNumber === f && c.condition === key); return <td key={key}>{c ? <>
    {onCell ? <button className="ws-link" onClick={() => onCell(c)}>{display(c)}</button> : <strong>{display(c)}</strong>}
    <small>{c.succeeded}/{c.runCount}{" "}{tr("runs ·")}{" "}{c.failed}{" "}{tr("failed ·")}{" "}{c.labelledRuns}{" "}{tr("labelled")}</small>
    <details><summary>{tr("Distribution / counts")}</summary><p>{tr("TP/FP/TN/FN:")}{" "}{c.sample.TP}/{c.sample.FP}/{c.sample.TN}/{c.sample.FN}</p><p>{tr("Precision")}{" "}{value(c.sample.precision)} · F1 {value(c.sample.f1)}</p><p>{tr("Detected-only delay")}{" "}{value(c.delay.minimum)}–{value(c.delay.maximum)} s · n={c.delay.n}{tr("; missed")}{" "}{c.event.missedEvents}{tr(", unobserved")}{" "}{c.event.unobservedEvents}{tr("; unresolved runs")}{" "}{c.unresolvedRuns ?? 0}</p><p>{tr("Run recall median")}{" "}{value(c.recall.median)}{tr(", range")}{" "}{value(c.recall.minimum)}–{value(c.recall.maximum)} · n={c.recall.n}</p><p>{tr("Run FAR median")}{" "}{value(c.falseAlarmRate.median)}{tr(", range")}{" "}{value(c.falseAlarmRate.minimum)}–{value(c.falseAlarmRate.maximum)} · n={c.falseAlarmRate.n}</p><p>{tr("Alarm duration median")}{" "}{value(c.alarmDuration.median)}{" "}{tr("s, range")}{" "}{value(c.alarmDuration.minimum)}–{value(c.alarmDuration.maximum)} · n={c.alarmDuration.n}</p><p>{tr("Abstain")}{" "}{value(c.abstainFraction)}{" "}{tr("· score time median")}{" "}{value(c.durationMs.median)} ms</p>
    {c.windows && Object.entries(c.windows).map(([horizon,w]) => <p key={horizon}>{horizon === "eventual" ? tr("Eventual") : tr("≤{0} minutes", {0: Number(horizon)/60})}: {w.detectedEvents}/{w.totalEvents}{tr("; unobserved")}{" "}{w.unobservedEvents}{tr("; truncated")}{" "}{w.truncatedEvents}{tr("; unresolved")}{" "}{w.unresolvedEvents ?? 0}</p>)}</details>
    {c.delayDistribution && <details><summary>{tr("Delay distribution / missed events")}</summary><p>{tr("≤30m")}{" "}{c.delayDistribution.within30m}{tr("; 30m–1h")}{" "}{c.delayDistribution.from30mTo1h}{tr("; 1h–4h")}{" "}{c.delayDistribution.from1hTo4h}{tr("; later than 4h")}{" "}{c.delayDistribution.laterThan4h}{tr("; missed")}{" "}{c.delayDistribution.missed}{tr("; unresolved")}{" "}{c.delayDistribution.unresolved}.</p></details>}
  </> : "—"}</td>; })}</tr>)}</tbody></table></div>;
}

export function TEPBenchmark({ data, datasets = [], onSelect }: { data: ExperimentComparisonData; datasets?: Dataset[]; onSelect: (ids: string[]) => void }) {
  useLocale();
  const [metric, setMetric] = useState("event"), [batch, setBatch] = useState(""), [run, setRun] = useState("");
  const summary = data.benchmark;
  if (!summary?.cells.length) return null;
  const batchId = batch || data.experiment.runs[0]?.id;
  const cells = summary.cells.filter(c => c.runId === batchId);
  const tasks = data.tasks.filter(t => t.run_id === batchId && t.external);
  const trajectories = [...new Map(tasks.map(t => [t.datasetId, t])).values()];
  return <section id="experiment-benchmark" className="ws-panel tep-benchmark" aria-label={tr("TEP benchmark dashboard")}><div className="ws-section-heading"><h2>{tr("TEP / Fault × algorithm")}</h2><span className="ws-kicker">{tr("INDEPENDENT RUNS")}</span></div><p>{tr(summary.rules)}</p>
    <p><a className="ws-link" href={`#/workspaces/${data.experiment.workspace_id}/tep`}>{tr("Open protocol and training-configuration dashboard ↗")}</a></p>
    <div className="ws-form-grid"><label>{tr("Benchmark batch")}<select value={batchId} onChange={e => { setBatch(e.target.value); setRun(""); }}>{data.experiment.runs.map(r => <option key={r.id} value={r.id}>{r.id.slice(0,8)} · {tr(r.status)}</option>)}</select></label><MatrixMetric metric={metric} setMetric={setMetric} /></div>
    <FaultMatrix cells={cells} metric={metric} onCell={c => setRun(tasks.find(t => c.taskIds.includes(t.id))?.datasetId || "")} />
    <h3>{tr("Inspect one independent trajectory")}</h3><label>{tr("Fault / simulationRun")}<select value={run} onChange={e => setRun(e.target.value)}><option value="">{tr("Choose a test trajectory")}</option>{trajectories.map(t => <option key={t.datasetId} value={t.datasetId}>{tr("Fault")}{" "}{t.external!.faultNumber}{" "}{tr("· simulationRun")}{" "}{t.external!.simulationRun} · {t.datasetName}</option>)}</select></label><button disabled={!run} onClick={() => onSelect(tasks.filter(t => t.datasetId === run && t.status === "succeeded").slice(0,12).map(t => t.id))}>{tr("Compare algorithms for this trajectory")}</button>
    {run && <p><a className="ws-link" href={`#/workspaces/${data.experiment.workspace_id}/datasets/${run}`}>{tr("Open Dataset ↗")}</a> · <a className="ws-link" href={`#/workspaces/${data.experiment.workspace_id}/explorer/${(datasets.find(d => d.id === run) || data.analyses.find(a => a.dataset.id === run)?.dataset)?.metadata.columns.map(c => c.id).filter(Boolean).join(",") || ""}`}>{tr("Open Signal Explorer ↗")}</a>{" "}{tr("· Published injection")}{" "}{tasks.find(t => t.datasetId === run)?.external?.faultOnsetSeconds ?? "none"} s</p>}
  </section>;
}
