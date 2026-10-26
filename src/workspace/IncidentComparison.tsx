import { t as tr, useLocale } from "../i18n";
import { Plot } from "./Charts";
import { Contributions } from "./Results";
import { incidentAxis, number, timeLabel, type IncidentAnalysis, type IncidentSelection, type IncidentView } from "./types";

const segmentKinds = { get common() { return tr("全部共同检出"); }, get unique() { return tr("独有检出"); }, get partial() { return tr("部分共同检出"); }, get uncompared() { return tr("缺少共同观测，未比较"); } };
export function IncidentComparison({ view, selectedIds, onIds, loading, selection, onSelect }: {
  view: IncidentView; selectedIds: string[]; onIds: (ids: string[]) => void; loading: boolean; selection: IncidentSelection | null; onSelect: (value: IncidentSelection) => void;
}) {
  useLocale();
  function focus(a: IncidentAnalysis, start: number, end: number, at: number, intervalIndex?: number, linkId?: string) {
    const pad = Math.max((end-start)*.2, 1);
    onSelect({ axisId: a.axisId, start: start-pad, end: end+pad, at, analysisId: a.id, intervalIndex, linkId: linkId || a.linkId });
    document.getElementById("incident-window")?.scrollIntoView({ block: "start" });
  }
  return <section id="incident-comparison" className="ws-panel" aria-label={tr("事件级分析比较")} aria-busy={loading}>
    <h2>{tr("事件级分析比较")}</h2><p className="ws-muted">{tr("选择已关联分析，在兼容时间轴上比较报警。原始分数和阈值各自保留尺度，跨算法优先比较时间、区间和贡献变量。")}</p>
    <div className="ws-option-grid">{view.analyses.map(a => <label key={a.id}><input type="checkbox" checked={selectedIds.includes(a.id)} onChange={e => onIds(e.target.checked ? [...selectedIds, a.id] : selectedIds.filter(id => id !== a.id))} />{a.result.name} · {a.scope}</label>)}</div>
    {!view.analyses.length && <p className="ws-notice">{tr("关联两个或更多分析后，可以检查共同与独有报警。")}</p>}
    {loading ? <p role="status">{tr("正在更新比较…")}</p> : view.comparisons.map(group => {
      const axis = view.axes.find(a => a.id === group.axisId)!, clock = incidentAxis(axis);
      const members = view.analyses.filter(a => group.analysisIds.includes(a.id));
      const intervals = members.flatMap(a => a.intervals);
      const first = Math.min(...intervals.map(i => i.start)), last = Math.max(...intervals.map(i => i.end));
      const x = (t: number) => 185 + (t-first)/(last-first || 1)*740;
      return <div key={axis.id} className="incident-comparison-group">
        <h3>{axis.label}</h3><p>{tr("首次报警：")}{group.firstDetection == null ? tr("未检出") : timeLabel(clock, group.firstDetection)}{" "}{tr("· 首次报警时间差：")}{group.firstAlarmSpread == null ? tr("需要至少两个有报警的分析") : `${number(group.firstAlarmSpread)} s`}{" "}{tr("· 共同区间")}{" "}{group.common.length}{" "}{tr("个")}</p>
        {members.length === 1 && <p className="ws-muted">{tr("此时间轴只有一个所选分析；其他数据集的数值秒数不会自动对齐。")}</p>}
        {intervals.length > 0 && <div className="incident-lanes"><svg viewBox={`0 0 960 ${members.length*38+40}`} role="group" aria-label={tr("{0} 算法检测区间叠加", {0: axis.label})}>
          {members.map((a, row) => <g key={a.id}><text x="0" y={row*38+25}>{a.result.algorithmLabel.slice(0, 22)}</text><line x1="185" x2="925" y1={row*38+20} y2={row*38+20} stroke="#3d4936" />
            {a.intervals.map(i => <g key={i.index} role="button" tabIndex={0} aria-label={tr("{0} 区间 {1} 至 {2}", {0: a.result.name, 1: timeLabel(clock, i.start), 2: timeLabel(clock, i.end)})} onClick={() => focus(a, i.start, i.end, i.peakTime, i.index, i.linkId)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focus(a, i.start, i.end, i.peakTime, i.index, i.linkId); } }}>
              <rect x={x(i.start)} y={row*38+10} width={Math.max(6,x(i.end)-x(i.start))} height="20" rx="2" fill="#b5ed9a" opacity=".75" /><circle cx={x(i.peakTime)} cy={row*38+20} r="3" fill="#e2bc75" />
            </g>)}
          </g>)}<text x="185" y={members.length*38+26}>{timeLabel(clock, first)}</text><text x="925" textAnchor="end" y={members.length*38+26}>{timeLabel(clock, last)}</text>
        </svg></div>}
        <div className="ws-table-scroll"><table><thead><tr><th>{tr("分析 / 原始结果")}</th><th>{tr("首次报警")}</th><th>{tr("峰值时间")}</th><th>{tr("区间 / 持续时间")}</th><th>{tr("原始峰值 / 阈值")}</th><th>{tr("主要变量")}</th></tr></thead><tbody>{members.map(a => {
          const peak = [...a.intervals].sort((i, j) => j.peakScore-i.peakScore)[0];
          return <tr key={a.id}><td><a className="ws-link" href={`#/workspaces/${view.incident.workspace_id}/analysis/${a.id}${selection?.analysisId === a.id && selection.intervalIndex != null ? `/${selection.intervalIndex}` : ""}`}>{a.result.name} ↗</a></td><td>{a.intervals.length ? timeLabel(clock, a.intervals[0].start) : tr("未检出")}</td><td>{peak ? <button onClick={() => focus(a, peak.start, peak.end, peak.peakTime, peak.index, peak.linkId)}>{timeLabel(clock, peak.peakTime)}</button> : tr("未检出")}</td><td>{a.intervals.length} / {number(a.intervals.reduce((v, i) => v+i.end-i.start, 0))} s</td><td>{peak ? number(peak.peakScore) : tr("未检出")} / {number(a.result.threshold)}</td><td>{a.result.relatedSignals.slice(0, 3).join(" · ")}</td></tr>;
        })}</tbody></table></div>
        <p className="ws-muted">{tr("持续时间为首末样本时间差；单点报警为 0 s。共同与独有区间仅在各分析共同有有效观测的窗口内判断，abstain 和窗口外不视为未报警。")}</p>
        {members.length > 1 && <div className="ws-table-scroll"><table><thead><tr><th>{tr("比较类别")}</th><th>{tr("时间范围")}</th><th>{tr("持续时间")}</th><th>{tr("检出分析 / 定位")}</th></tr></thead><tbody>{group.segments.map((segment, index) => <tr key={index}><td>{segmentKinds[segment.kind]}</td><td>{timeLabel(clock, segment.start)} → {timeLabel(clock, segment.end)}</td><td>{number(segment.end-segment.start)} s</td><td>{segment.analysisIds.map(id => { const a = members.find(a => a.id === id)!; return <button key={id} onClick={() => focus(a, segment.start, segment.end, segment.start)}>{a.result.algorithmLabel}{" "}{tr("· 定位曲线")}</button>; })}</td></tr>)}</tbody></table></div>}
        {selection?.axisId === axis.id && <div className="incident-comparison-scores"><h3>{tr("共享窗口内的检测分数")}</h3><p className="ws-muted">{timeLabel(clock, selection.start)} → {timeLabel(clock, selection.end)}{tr("。各图独立纵轴；选中时间在所有曲线上同步。")}</p>{members.map(a => {
          const indices = a.result.times.map((t, i) => ({ t: t+a.offset, i })).filter(p => p.t >= selection.start && p.t <= selection.end);
          const peak = a.intervals.find(i => i.index === selection.intervalIndex && a.id === selection.analysisId);
          return <details key={a.id} open={a.id === selection.analysisId}><summary>{a.result.name}{" "}{tr("· 原始分数与贡献")}</summary>
            {indices.length ? <Plot title={a.result.algorithmLabel} times={indices.map(p => p.t)} values={indices.map(p => a.result.states?.[p.i] === "abstain" ? null : a.result.scores[p.i])} threshold={a.result.threshold} thresholdLabel={tr("阈值")} axis={clock} intervals={a.intervals} selectedTime={selection.at} onSelectTime={at => onSelect({ ...selection, at })} /> : <p>{tr("此分析在选中窗口没有样本。")}</p>}
            <Contributions values={peak?.contributions ?? a.result.signalContributions} signals={peak?.signals ?? a.result.relatedSignals} metric={a.result.contributionMetric} />
          </details>;
        })}</div>}
      </div>;
    })}
  </section>;
}
