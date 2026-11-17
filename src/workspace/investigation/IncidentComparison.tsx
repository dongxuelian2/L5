import { t as tr } from "../../lib/text";
import { Plot } from "../Charts";
import { Contributions } from "../monitoring/Results";
import { incidentAxis, number, timeLabel, type IncidentAnalysis, type IncidentSelection, type IncidentView } from "../types";

const segmentKinds = { get common() { return "Detected by all"; }, get unique() { return "Unique detection"; }, get partial() { return "Detected by some"; }, get uncompared() { return "No joint observations; not compared"; } };
export function IncidentComparison({ view, selectedIds, onIds, loading, selection, onSelect }: {
  view: IncidentView; selectedIds: string[]; onIds: (ids: string[]) => void; loading: boolean; selection: IncidentSelection | null; onSelect: (value: IncidentSelection) => void;
}) {
  function focus(a: IncidentAnalysis, start: number, end: number, at: number, intervalIndex?: number, linkId?: string) {
    const pad = Math.max((end-start)*.2, 1);
    onSelect({ axisId: a.axisId, start: start-pad, end: end+pad, at, analysisId: a.id, intervalIndex, linkId: linkId || a.linkId });
    document.getElementById("incident-window")?.scrollIntoView({ block: "start" });
  }
  return <section id="incident-comparison" className="ws-panel" aria-label={"Incident analysis comparison"} aria-busy={loading}>
    <h2>Incident analysis comparison</h2><p className="ws-muted">Compare linked analyses on compatible clocks. Each score and threshold retains its scale; compare timing, intervals and contributing variables across algorithms.</p>
    <div className="ws-option-grid">{view.analyses.map(a => <label key={a.id}><input type="checkbox" checked={selectedIds.includes(a.id)} onChange={e => onIds(e.target.checked ? [...selectedIds, a.id] : selectedIds.filter(id => id !== a.id))} />{a.result.name} · {tr(a.scope)}</label>)}</div>
    {!view.analyses.length && <p className="ws-notice">Link two or more analyses to inspect shared and unique alarms.</p>}
    {loading ? <p role="status">Updating comparison…</p> : view.comparisons.map(group => {
      const axis = view.axes.find(a => a.id === group.axisId)!, clock = incidentAxis(axis);
      const members = view.analyses.filter(a => group.analysisIds.includes(a.id));
      const intervals = members.flatMap(a => a.intervals);
      const first = Math.min(...intervals.map(i => i.start)), last = Math.max(...intervals.map(i => i.end));
      const x = (t: number) => 185 + (t-first)/(last-first || 1)*740;
      return <div key={axis.id} className="incident-comparison-group">
        <h3>{axis.label}</h3><p>First alarm:{group.firstDetection == null ? "Not detected" : timeLabel(clock, group.firstDetection)}{" "}· First-alarm spread:{group.firstAlarmSpread == null ? "Requires at least two analyses with alarms" : `${number(group.firstAlarmSpread)} s`}{" "}· Common intervals{" "}{group.common.length}{" "}items</p>
        {members.length === 1 && <p className="ws-muted">Only one selected analysis uses this clock. Numerical seconds from other datasets are not automatically aligned.</p>}
        {intervals.length > 0 && <div className="incident-lanes"><svg viewBox={`0 0 960 ${members.length*38+40}`} role="group" aria-label={tr("{0} algorithm detection intervals", {0: axis.label})}>
          {members.map((a, row) => <g key={a.id}><text x="0" y={row*38+25}>{tr(a.result.algorithmLabel).slice(0, 22)}</text><line x1="185" x2="925" y1={row*38+20} y2={row*38+20} stroke="#3d4936" />
            {a.intervals.map(i => <g key={i.index} role="button" tabIndex={0} aria-label={tr("{0} interval {1} to {2}", {0: a.result.name, 1: timeLabel(clock, i.start), 2: timeLabel(clock, i.end)})} onClick={() => focus(a, i.start, i.end, i.peakTime, i.index, i.linkId)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focus(a, i.start, i.end, i.peakTime, i.index, i.linkId); } }}>
              <rect x={x(i.start)} y={row*38+10} width={Math.max(6,x(i.end)-x(i.start))} height="20" rx="2" fill="#b5ed9a" opacity=".75" /><circle cx={x(i.peakTime)} cy={row*38+20} r="3" fill="#e2bc75" />
            </g>)}
          </g>)}<text x="185" y={members.length*38+26}>{timeLabel(clock, first)}</text><text x="925" textAnchor="end" y={members.length*38+26}>{timeLabel(clock, last)}</text>
        </svg></div>}
        <div className="ws-table-scroll"><table><thead><tr><th>Analysis / original result</th><th>First alarm</th><th>Peak time</th><th>Intervals / duration</th><th>Original peak / threshold</th><th>Main variables</th></tr></thead><tbody>{members.map(a => {
          const peak = [...a.intervals].sort((i, j) => j.peakScore-i.peakScore)[0];
          const limit = peak?.threshold ?? (a.result.regimeRunId ? null : a.result.threshold);
          return <tr key={a.id}><td><a className="ws-link" href={`#/workspaces/${view.incident.workspace_id}/analysis/${a.id}${selection?.analysisId === a.id && selection.intervalIndex != null ? `/${selection.intervalIndex}` : ""}`}>{a.result.name} ↗</a></td><td>{a.intervals.length ? timeLabel(clock, a.intervals[0].start) : "Not detected"}</td><td>{peak ? <button onClick={() => focus(a, peak.start, peak.end, peak.peakTime, peak.index, peak.linkId)}>{timeLabel(clock, peak.peakTime)}</button> : "Not detected"}</td><td>{a.intervals.length} / {number(a.intervals.reduce((v, i) => v+i.end-i.start, 0))} s</td><td>{peak ? number(peak.rawPeakScore ?? peak.peakScore) : "Not detected"} / {limit === null ? "—" : number(limit)}</td><td>{a.result.relatedSignals.slice(0, 3).join(" · ")}</td></tr>;
        })}</tbody></table></div>
        <p className="ws-muted">Duration is the time difference between the first and last sample; a single-point alarm has 0 s duration. Shared and unique intervals are classified only within jointly observed time. Abstain and time outside a window do not count as no alarm.</p>
        {members.length > 1 && <div className="ws-table-scroll"><table><thead><tr><th>Comparison class</th><th>Time range</th><th>Duration</th><th>Detecting analysis / focus</th></tr></thead><tbody>{group.segments.map((segment, index) => <tr key={index}><td>{segmentKinds[segment.kind]}</td><td>{timeLabel(clock, segment.start)} → {timeLabel(clock, segment.end)}</td><td>{number(segment.end-segment.start)} s</td><td>{segment.analysisIds.map(id => { const a = members.find(a => a.id === id)!; return <button key={id} onClick={() => focus(a, segment.start, segment.end, segment.start)}>{a.result.algorithmLabel}{" "}· Focus curves</button>; })}</td></tr>)}</tbody></table></div>}
        {selection?.axisId === axis.id && <div className="incident-comparison-scores"><h3>Detection scores in shared window</h3><p className="ws-muted">{timeLabel(clock, selection.start)} → {timeLabel(clock, selection.end)}. Each chart has its own vertical axis; selected time is synchronized across curves.</p>{members.map(a => {
          const indices = a.result.times.map((t, i) => ({ t: t+a.offset, i })).filter(p => p.t >= selection.start && p.t <= selection.end);
          const peak = a.intervals.find(i => i.index === selection.intervalIndex && a.id === selection.analysisId);
          return <details key={a.id} open={a.id === selection.analysisId}><summary>{a.result.name}{" "}{a.result.regimeRunId ? "· log1p(score) − log1p(threshold)" : "· Original scores and contributions"}</summary>
            {indices.length ? <Plot title={a.result.algorithmLabel} times={indices.map(p => p.t)} values={indices.map(p => a.result.states?.[p.i] === "abstain" ? null : a.result.scores[p.i])} threshold={a.result.threshold} thresholdLabel={"Threshold"} axis={clock} intervals={a.intervals} selectedTime={selection.at} onSelectTime={at => onSelect({ ...selection, at })} /> : <p>No samples from this analysis in the selected window.</p>}
            <Contributions values={peak?.contributions ?? a.result.signalContributions} signals={peak?.signals ?? a.result.relatedSignals} metric={a.result.contributionMetric} />
          </details>;
        })}</div>}
      </div>;
    })}
  </section>;
}
