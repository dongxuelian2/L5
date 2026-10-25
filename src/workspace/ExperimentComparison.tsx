import { useEffect, useState } from "react";
import { api, message } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { Contributions } from "./Results";
import { number, timeLabel, type Dataset, type TimeAxis } from "./types";
import { taskParameters, type ComparedAnalysis, type ExperimentComparisonData } from "./experimentTypes";

const kinds = { common: "Common alarm", unique: "Unique alarm", partial: "Partial agreement", uncompared: "Outside joint observation" };
type Focus = { axisId: string; at: number };
const axisFor = (a: ComparedAnalysis): TimeAxis => ({ ...a.dataset.metadata.time, origin: a.axisId === "utc" ? "1970-01-01T00:00:00Z" : null });

export function ExperimentComparison({ data }: { data: ExperimentComparisonData }) {
  const [focus, setFocus] = useState<Focus | null>(null);
  if (!data.analyses.length) return <p className="ws-notice">Select completed tasks to compare alarm timing, independent score curves, contributions and original measurements.</p>;
  return <section id="experiment-comparison" className="experiment-comparison" aria-label="Detailed experiment comparison"><h2>Compare selected results</h2><p className="ws-muted">Scores and contribution magnitudes retain method-specific scales. Compare timing and behavior under matching conditions; unlabelled behavior is not detection accuracy.</p>
    {data.groups.map(group => {
      const members = data.analyses.filter(a => group.taskIds.includes(a.id)), axis = axisFor(members[0]);
      const first = Math.min(...members.map(a => a.result.times[0] + a.offset));
      const last = Math.max(...members.map(a => a.result.times[a.result.times.length-1] + a.offset));
      const at = focus?.axisId === group.axisId ? focus.at : first;
      const choose = (value: number) => setFocus({ axisId: group.axisId, at: value });
      const x = (t: number) => 195 + (t-first)/(last-first || 1)*730;
      return <div className="ws-panel" key={group.axisId}>
        <h3>{group.axisId === "utc" ? "UTC shared timeline" : "Shared source timeline"}</h3>
        {(!group.matchingWindows || !group.matchingCoverage) && <p className="ws-notice">Comparison conditions differ: {group.matchingWindows ? "matching windows" : "different analysis windows"}; {group.matchingCoverage ? "matching observation spans" : "different observation coverage"}. Common and unique alarms are classified only inside jointly evaluated time.</p>}
        {group.matchingInputs === false && <p className="ws-notice">Selected results use different dataset content, input signals, baselines or observation policies. These are different experimental conditions.</p>}
        {group.matchingLabelSets === false && <p className="ws-notice">Selected results use different truth label versions. Accuracy metrics do not share one evaluation reference.</p>}
        {members.length === 1 && data.groups.length > 1 && <p className="ws-notice">This result has an independent clock. It cannot be directly aligned with results in the other clock groups.</p>}
        <label>Shared observation time (clock seconds)<input type="number" step="any" min={first} max={last} value={at} onChange={e => { const v = Number(e.target.value); if (v >= first && v <= last) choose(v); }} /></label>
        <input type="range" aria-label="Shared experiment cursor" min={first} max={last} step="any" value={at} onChange={e => choose(Number(e.target.value))} />
        <p className="ws-muted">Cursor: {timeLabel(axis, at)} · Alarm duration uses last minus first sample time; single samples have zero duration.</p>
        <svg className="experiment-lanes" viewBox={`0 0 960 ${members.length*38+40}`} role="group" aria-label="Multi-algorithm alarm timeline">{members.map((a, row) => <g key={a.id}><text x="0" y={row*38+26}>{a.result.algorithmLabel.slice(0,20)} · {a.id.slice(0,4)}</text><line x1="195" x2="925" y1={row*38+20} y2={row*38+20} stroke="#3d4936" />{a.intervals.map((interval, i) => <rect key={i} role="button" tabIndex={0} aria-label={`${a.result.algorithmLabel} alarm ${interval.start} to ${interval.end}`} x={x(interval.start)} y={row*38+10} width={Math.max(4, x(interval.end)-x(interval.start))} height={20} fill="#b5ed9a" opacity=".8" onClick={() => choose(interval.start)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(interval.start); } }} />)}</g>)}<line x1={x(at)} x2={x(at)} y1={0} y2={members.length*38} stroke="#e2bc75" strokeDasharray="4 3" /><text x="195" y={members.length*38+25}>{timeLabel(axis, first)}</text><text x="925" textAnchor="end" y={members.length*38+25}>{timeLabel(axis, last)}</text></svg>
        <details><summary>Common and unique alarm intervals · {group.segments.length}</summary><div className="ws-table-scroll"><table><thead><tr><th>Classification</th><th>Start / end</th><th>Detected by task</th></tr></thead><tbody>{group.segments.map((segment, i) => <tr key={i}><td>{kinds[segment.kind]}</td><td><button onClick={() => choose(segment.start)}>{timeLabel(axis, segment.start)} → {timeLabel(axis, segment.end)}</button></td><td>{segment.analysisIds.map(id => `${members.find(a => a.id === id)?.result.algorithmLabel} ${id.slice(0,6)}`).join(" · ")}</td></tr>)}</tbody></table></div></details>
        {group.agreement.length > 0 && <details><summary>Alarm agreement on exact shared observations</summary><div className="ws-table-scroll"><table><thead><tr><th>Task pair</th><th>Joint observations</th><th>State agreement</th><th>Alarm Jaccard</th></tr></thead><tbody>{group.agreement.map(pair => <tr key={`${pair.left}-${pair.right}`}><td>{pair.left.slice(0,6)} / {pair.right.slice(0,6)}</td><td>{pair.jointSamples}</td><td>{pair.agreement == null ? "Undefined" : number(pair.agreement)}</td><td>{pair.alarmJaccard == null ? "Undefined · no alarm union" : number(pair.alarmJaccard)}</td></tr>)}</tbody></table></div></details>}
        {members.map(a => <details key={a.id} open={members.length <= 3}><summary>{a.result.algorithmLabel} · {taskParameters(a.task)} · task {a.id.slice(0,8)}</summary><Plot title={`${a.result.algorithmLabel} · ${a.id.slice(0,6)}`} times={a.result.times.map(t => t+a.offset)} values={a.result.scores.map((score, i) => a.result.states?.[i] === "abstain" ? null : score)} threshold={a.result.threshold} axis={axis} selectedTime={at} onSelectTime={choose} gaps={a.dataset.metadata.quality?.gaps.map(g => ({ start: g.start+a.offset, end: g.end+a.offset }))} /><Contributions values={a.result.signalContributions} signals={a.result.relatedSignals} metric={a.result.contributionMetric} /></details>)}
        {[...new Map(members.map(a => [a.dataset.id, a])).values()].map(a => <details key={a.dataset.id} open><summary>Original measurements · {a.dataset.name}</summary><SignalPlots dataset={a.dataset} signals={a.result.config.signals.slice(0,5)} range={a.result.config.analysisRange} selectedTime={at-a.offset} onSelectTime={value => choose(value+a.offset)} /><ExperimentSample dataset={a.dataset} signals={a.result.config.signals} at={at-a.offset} /></details>)}
      </div>;
    })}
  </section>;
}

function ExperimentSample({ dataset, signals, at }: { dataset: Dataset; signals: string[]; at: number }) {
  type Sample = { time: number; values: Record<string, number | null>; provenance?: Record<string, string>; observed?: Record<string, boolean> };
  const [sample, setSample] = useState<Sample | null>(null), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setSample(null); setError("");
    if (at < dataset.metadata.time.start || at > dataset.metadata.time.end) return;
    const query = new URLSearchParams({ at: String(at) }); signals.forEach(signal => query.append("signal", signal));
    const timer = setTimeout(() => { void api<Sample>(`/datasets/${dataset.id}/sample?${query}`, undefined, "GET", controller.signal).then(value => { if (!controller.signal.aborted) setSample(value); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }); }, 100);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [dataset.id, at, signals.join(",")]);
  return <div aria-label="Original measurement at shared cursor">{error && <p role="alert">{error}</p>}{sample && <p>{dataset.metadata.transformation ? "Nearest derived dataset sample" : "Nearest original measurement"} at {timeLabel(dataset.metadata.time, sample.time)}: {Object.entries(sample.values).map(([signal, value]) => `${signal}: ${value == null ? "missing" : number(value)}${sample.provenance?.[signal] ? ` (${sample.provenance[signal]}, ${sample.observed?.[signal] ? "observed" : "processed"})` : ""}`).join(" · ")}</p>}</div>;
}
