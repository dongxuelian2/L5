import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useState } from "react";
import { api, message } from "./api";
import { incidentAxis, dateLabel, number, timeLabel, type Incident, type IncidentAxis, type IncidentSelection, type IncidentView, type TimelineEvent } from "./types";
import { IncidentComparison } from "./IncidentComparison";

const kinds: Record<string, string> = { get truth() { return tr("数据集已知故障"); }, get incident() { return tr("事件范围"); }, get alarm() { return tr("算法报警"); }, get note() { return tr("调查笔记"); }, get evidence() { return tr("调查证据"); }, get hypothesis() { return tr("候选解释"); }, get investigation() { return tr("工具调查"); }, get experiment() { return tr("干预实验"); }, get status() { return tr("状态变更"); }, get conclusion() { return tr("结论更新"); } };
export function selectTimelineEvent(event: TimelineEvent, axis: IncidentAxis): IncidentSelection | null {
  if (event.start == null) return null;
  const duration = (event.end ?? event.start) - event.start;
  const padding = Math.max(duration * .25, (axis.end - axis.start) * .025, .1);
  return { axisId: axis.id, start: event.start - padding, end: (event.end ?? event.start) + padding, at: event.peakTime ?? event.start,
    eventId: event.id, linkId: event.linkId || undefined, analysisId: event.analysisId, intervalIndex: event.intervalIndex };
}

export function IncidentTimeline({ incident, selection, onSelect, onRecord, onSection }: {
  incident: Incident; selection: IncidentSelection | null; onSelect: (value: IncidentSelection) => void;
  onRecord: (event: TimelineEvent) => void; onSection: (id: string) => void;
}) {
  useLocale();
  const [view, setView] = useState<IncidentView | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<string[] | null>(null);
  const [axisId, setAxisId] = useState(""), [kind, setKind] = useState(""), [analysisId, setAnalysisId] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState("");
  const availableIds = new Set(incident.links.flatMap(link => link.details.analysisId ? [link.details.analysisId] : []));
  const validIds = selectedIds?.filter(id => availableIds.has(id)) ?? null;
  useEffect(() => { if (selection) setAxisId(selection.axisId); }, [selection?.axisId]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    const query = new URLSearchParams();
    if (validIds) { if (!validIds.length) query.append("analysis", ""); else validIds.forEach(id => query.append("analysis", id)); }
    api<IncidentView>(`/incidents/${incident.id}/timeline?${query}`, undefined, "GET", controller.signal)
      .then(setView).catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [incident, selectedIds]);
  const activeId = axisId || selection?.axisId || view?.events.find(e => e.start != null && e.kind === "alarm")?.axisId || view?.primaryAxisId;
  const axis = view?.axes.find(a => a.id === activeId) || view?.axes[0];
  const measured = view?.events.filter(e => e.axisId === axis?.id && e.start != null && (!kind || kind === e.kind) && (!analysisId || e.analysisId === analysisId)
    && (start === "" || (e.end ?? e.start!) >= Number(start)) && (end === "" || e.start! <= Number(end))) || [];
  const recorded = view?.events.filter(e => e.start == null && (!kind || kind === e.kind) && !analysisId).sort((a, b) => (a.recordedAt || "").localeCompare(b.recordedAt || "")) || [];
  function activate(event: TimelineEvent) {
    const clock = view?.axes.find(a => a.id === event.axisId);
    const next = clock && selectTimelineEvent(event, clock);
    if (next) { onSelect(next); setAxisId(clock!.id); }
    if (event.target === "entry") onRecord(event);
    else if (event.target === "conclusion") onSection("incident-conclusion");
    else if (event.target === "information") onSection("incident-information");
  }
  const invalidRange = start !== "" && end !== "" && Number(start) > Number(end);
  return <>
    <section id="incident-timeline" className="ws-panel" aria-label={tr("事件交互时间线")} aria-busy={loading}>
      <div className="ws-section-heading"><div><h2>{tr("事件时间线")}</h2><p className="ws-muted">{tr("点击报警定位原始曲线；点击记录继续编辑；实验记录可恢复保存的观察窗口与参数。")}</p></div>{loading && <span role="status">{tr("正在同步时间线…")}</span>}</div>
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      {view && axis && <>
        <div className="ws-form-grid timeline-filters">
          <label>{tr("时间轴")}<select value={axis.id} onChange={e => { setAxisId(e.target.value); setStart(""); setEnd(""); }}>
            {view.axes.map(a => <option key={a.id} value={a.id}>{a.label}{a.origin ? " · UTC" : tr(" · 相对秒数")}</option>)}
          </select></label>
          <label>{tr("事件类别")}<select value={kind} onChange={e => setKind(e.target.value)}><option value="">{tr("全部类别")}</option>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>{tr("分析结果")}<select value={analysisId} onChange={e => setAnalysisId(e.target.value)}><option value="">{tr("全部来源")}</option>{view.analyses.map(a => <option key={a.id} value={a.id}>{a.result.name}</option>)}</select></label>
          <label>{tr("筛选起点（")}{axis.origin ? tr("UTC Unix 秒") : tr("秒")}）<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label>
          <label>{tr("筛选终点（")}{axis.origin ? tr("UTC Unix 秒") : tr("秒")}）<input type="number" step="any" value={end} onChange={e => setEnd(e.target.value)} /></label>
        </div>
        <p className="ws-muted">{tr("当前时间轴：")}{axis.label}。{axis.origin ? tr("已按各数据集 UTC 起点换算为绝对时间。") : tr("仅同一数据集／模拟会话共享此时间轴。")}{tr("实际观察时间与记录创建时间分开显示。")}</p>
        {invalidRange ? <p role="alert" className="ws-error">{tr("筛选终点不能早于起点。")}</p> : <>
          <TimelineLanes events={measured} axis={axis} selection={selection} activate={activate} />
          <ol className="incident-event-list">{measured.map(event => <li key={event.id} data-event-id={event.id} className={selection?.eventId === event.id ? "incident-selected" : ""}>
            <button onClick={() => activate(event)} aria-pressed={selection?.eventId === event.id}>
              <span className="ws-kicker">{kinds[event.kind]}{" "}{tr("· 实际观察")}{" "}{timeLabel(incidentAxis(axis), event.start!)}{event.end !== event.start && ` → ${timeLabel(incidentAxis(axis), event.end!)}`}</span>
              <strong>{event.title}</strong>{event.peakTime != null && <span>{tr("峰值")}{" "}{timeLabel(incidentAxis(axis), event.peakTime)}{" "}{tr("· 原始分数")}{" "}{number(event.peakScore!)}</span>}
              {event.content && <span>{event.content.slice(0, 180)}</span>}{event.stance && <span>{tr("证据关系：")}{{ support: tr("支持"), oppose: tr("反对"), neutral: tr("待判断") }[event.stance]}</span>}
              {event.observationWindow && <span>{tr("观察窗口")}{" "}{event.observationWindow.join("–")} s{event.actionAt != null ? tr(" · 干预 {0} s", {0: event.actionAt}) : ""}</span>}
              {event.recordedAt && <small>{tr("记录创建：")}{dateLabel(event.recordedAt)}{event.updatedAt && event.updatedAt !== event.recordedAt ? tr(" · 更新：{0}", {0: dateLabel(event.updatedAt)}) : ""}</small>}
            </button>
            {event.linkId && incident.links.find(l => l.id === event.linkId)?.details.simulationId && <a className="ws-link" href={simulationEventHref(incident, event)}>{tr("恢复观察窗口与实验参数 ↗")}</a>}
          </li>)}</ol>
          {!measured.length && <p className="ws-notice">{tr("当前条件下没有实际观察记录。可选择其他时间轴或关联分析。")}</p>}
        </>}
        <details className="incident-recorded"><summary>{tr("调查操作与未标注观察时间的记录（")}{recorded.length}）</summary><p className="ws-muted">{tr("下列时间表示记录操作时间，不表示设备异常发生时间。实际观察范围筛选不作用于此列表。")}</p>
          {recorded.map(event => <div key={event.id}><button onClick={() => activate(event)}>{dateLabel(event.recordedAt!)} · {event.title}</button>
            {event.changes && <div className="incident-change">{Object.entries(event.changes).map(([key, change]) => <p key={key}>{changeLabel(key)}：{changeText(key, change.before)} → {changeText(key, change.after)}</p>)}</div>}
          </div>)}
        </details>
      </>}
    </section>
    {view && <IncidentComparison view={view} selectedIds={validIds ?? view.analyses.map(a => a.id)} loading={loading} onIds={setSelectedIds} selection={selection} onSelect={onSelect} />}
  </>;
}

function changeLabel(key: string) { return ({ status: tr("状态"), conclusion: tr("结论"), title: tr("事件标题"), description: tr("事件说明"), start_time: tr("开始时间"), end_time: tr("结束时间"), time_origin: tr("时间原点"), time_axis_key: tr("时间来源") } as Record<string, string>)[key] || key; }
function changeText(key: string, value: unknown) { return key === "status" ? ({ open: tr("待调查"), investigating: tr("调查中"), resolved: tr("已形成结论"), archived: tr("已归档") } as Record<string, string>)[String(value)] || tr("未设置") : value == null ? tr("未设置") : String(value); }

export function simulationEventHref(incident: Incident, event: TimelineEvent) {
  const source = incident.links.find(l => l.id === event.linkId)!;
  const context = source.details.observationWindow;
  return `#/workspaces/${incident.workspace_id}/simulations/${source.details.simulationId}${source.details.run ? `/${source.details.run.id}` : context ? `/window/${context.windowStart}/${context.asOf}/${context.hypothesis || ""}` : ""}`;
}

function TimelineLanes({ events, axis, selection, activate }: { events: TimelineEvent[]; axis: IncidentAxis; selection: IncidentSelection | null; activate: (event: TimelineEvent) => void }) {
  useLocale();
  const lanes = [...new Set(events.map(e => e.analysisId || e.kind))];
  if (!events.length) return null;
  const first = Math.min(...events.map(e => e.start!)), last = Math.max(...events.map(e => e.end!));
  const x = (t: number) => 175 + (t-first)/(last-first || 1)*755;
  return <div className="incident-lanes"><svg viewBox={`0 0 960 ${lanes.length * 34 + 45}`} role="group" aria-label={tr("事件演变时间轴")}>
    {selection?.axisId === axis.id && selection.end >= first && selection.start <= last && <rect x={x(Math.max(first, selection.start))} y="0" width={Math.max(2, x(Math.min(last, selection.end))-x(Math.max(first, selection.start)))} height={lanes.length*34} fill="#e2bc75" opacity=".08" />}
    {lanes.map((lane, index) => <g key={lane}><text x="0" y={index*34+22}>{events.find(e => (e.analysisId || e.kind) === lane)!.title.slice(0, 19)}</text><line x1="175" x2="930" y1={index*34+18} y2={index*34+18} stroke="#3d4936" /></g>)}
    {events.map(event => { const y = lanes.indexOf(event.analysisId || event.kind)*34+9; return <g key={event.id} role="button" tabIndex={0} aria-label={`${event.title} ${timeLabel(incidentAxis(axis), event.start!)}`} aria-pressed={selection?.eventId === event.id} onClick={() => activate(event)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(event); } }}>
      <title>{event.title} · {timeLabel(incidentAxis(axis), event.start!)} → {timeLabel(incidentAxis(axis), event.end!)}</title>
      <rect x={x(event.start!)} y={y} width={Math.max(7, x(event.end!)-x(event.start!))} height="18" rx="3" fill={event.kind === "alarm" ? "#e9927d" : event.kind === "experiment" ? "#b4a0db" : "#b5ed9a"} opacity={selection?.eventId === event.id ? 1 : .65} />
      {event.peakTime != null && <circle cx={x(event.peakTime)} cy={y+9} r="3" fill="#e2bc75" />}
    </g>; })}
    {selection?.axisId === axis.id && selection.at >= first && selection.at <= last && <line data-timeline-time={selection.at} x1={x(selection.at)} x2={x(selection.at)} y1="0" y2={lanes.length*34} stroke="#e2bc75" strokeDasharray="4 3" />}
    <text x="175" y={lanes.length*34+28}>{timeLabel(incidentAxis(axis), first)}</text><text x="930" textAnchor="end" y={lanes.length*34+28}>{timeLabel(incidentAxis(axis), last)}</text>
  </svg></div>;
}
