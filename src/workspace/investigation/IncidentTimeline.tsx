import { errorMessage, t as tr } from "../../lib/text";
import { useEffect, useState } from "react";
import { api, message, prognosticSessionHref } from "../api";
import { axisLabel, timelineTitle, incidentAxis, dateLabel, number, safetyAssessmentHref, safetyEvidenceSummary, timeLabel, type Incident, type IncidentAxis, type IncidentSelection, type IncidentView, type TimelineEvent } from "../types";
import { IncidentComparison } from "./IncidentComparison";

const kinds: Record<string, string> = { get truth() { return "Known dataset fault"; }, get incident() { return "Incident range"; }, get alarm() { return "Algorithm alarm"; }, get note() { return "Investigation note"; }, get evidence() { return "Investigation evidence"; }, get hypothesis() { return "Hypothesis"; }, get investigation() { return "Tool investigation"; }, get experiment() { return "Intervention experiment"; }, get status() { return "Status change"; }, get conclusion() { return "Conclusion update"; }, prognostic: "Prognostic forecast", get "safety-observed"() { return "Observed constraint violation"; }, get "safety-predicted"() { return "Predicted constraint violation"; } };
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
  const [savedView, setView] = useState<IncidentView | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const view = savedView && { ...savedView, axes: savedView.axes.map(a => ({ ...a, label: axisLabel(a, savedView.datasets) })),
    events: savedView.events.map(event => ({ ...event, title: timelineTitle(event, savedView), content: event.diagnosticAssessment ? tr("{0} · severity {1}", {0: tr(event.diagnosticAssessment), 1: number(event.diagnosticSeverity!)}) : event.kind === "truth" ? tr(event.content) : event.content })) };
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
  const activeId = axisId || selection?.axisId || view?.events.find(e => e.start != null && (e.kind === "alarm" || e.kind === "safety-observed"))?.axisId || view?.primaryAxisId;
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
    <section id="incident-timeline" className="ws-panel" aria-label={"Interactive incident timeline"} aria-busy={loading}>
      <div className="ws-section-heading"><div><h2>Incident timeline</h2><p className="ws-muted">Click an alarm to focus its original curves, or a record to edit it. Experiment records restore their saved observation windows and parameters.</p></div>{loading && <span role="status">Synchronizing timeline…</span>}</div>
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      {view && axis && <>
        <div className="ws-form-grid timeline-filters">
          <label>Time axis<select value={axis.id} onChange={e => { setAxisId(e.target.value); setStart(""); setEnd(""); }}>
            {view.axes.map(a => <option key={a.id} value={a.id}>{a.label}{a.origin ? " · UTC" : " · Relative seconds"}</option>)}
          </select></label>
          <label>Event category<select value={kind} onChange={e => setKind(e.target.value)}><option value="">All categories</option>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>Analysis result<select value={analysisId} onChange={e => setAnalysisId(e.target.value)}><option value="">All sources</option>{view.analyses.map(a => <option key={a.id} value={a.id}>{a.result.name}</option>)}</select></label>
          <label>Filter start ({axis.origin ? "UTC Unix seconds" : "seconds"})<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label>
          <label>Filter end ({axis.origin ? "UTC Unix seconds" : "seconds"})<input type="number" step="any" value={end} onChange={e => setEnd(e.target.value)} /></label>
        </div>
        <p className="ws-muted">{axis.origin ? "Dataset observations align to UTC." : "Observations share a clock within their dataset or simulation."}</p>
        {invalidRange ? <p role="alert" className="ws-error">Filter end cannot precede its start.</p> : <>
          <TimelineLanes events={measured} axis={axis} selection={selection} activate={activate} />
          <ol className="incident-event-list">{measured.map(event => {
            const source = incident.links.find(link => link.id === event.linkId);
            return <li key={event.id} data-event-id={event.id} className={selection?.eventId === event.id ? "incident-selected" : ""}>
            <button onClick={() => activate(event)} aria-pressed={selection?.eventId === event.id}>
              <span className="ws-kicker">{kinds[event.kind]}{" "}{event.kind === "prognostic" ? "Forecast cutoff" : "· Actual observation"}{" "}{timeLabel(incidentAxis(axis), event.start!)}{event.end !== event.start && ` → ${timeLabel(incidentAxis(axis), event.end!)}`}</span>
              <strong>{event.title}</strong>{event.peakTime != null && <span>Peak{" "}{timeLabel(incidentAxis(axis), event.peakTime)}{" "}· Original score{" "}{number(event.rawPeakScore ?? event.peakScore!)}</span>}
              {event.content && <span>{event.content.slice(0, 180)}</span>}{event.stance && <span>Evidence relationship:{{ support: "Supports", oppose: "Opposes", neutral: "Undecided" }[event.stance]}</span>}
              {event.safety && <span>{safetyEvidenceSummary(event.safety)}</span>}
              {event.observationWindow && <span>Observation window{" "}{event.observationWindow.join("–")} s{event.actionAt != null ? tr(" · Intervention {0} s", {0: event.actionAt}) : ""}</span>}
              {event.recordedAt && <small>Record created:{dateLabel(event.recordedAt)}{event.updatedAt && event.updatedAt !== event.recordedAt ? tr(" · Updated: {0}", {0: dateLabel(event.updatedAt)}) : ""}</small>}
            </button>
            {source?.details.simulationId && <a className="ws-link" href={simulationEventHref(incident, event)}>Restore observation window and experiment parameters ↗</a>}
            {source?.details.sessionId && <a className="ws-link" href={prognosticSessionHref(incident.workspace_id, source.details.sessionId)}>Open saved forecast ↗</a>}
            {event.assessmentId && <a className="ws-link" href={safetyAssessmentHref(incident.workspace_id, event.assessmentId)}>Open safety assessment ↗</a>}
          </li>; })}</ol>
          {!measured.length && <p className="ws-notice">No actual observation records match. Select another clock or link an analysis.</p>}
        </>}
        <details className="incident-recorded"><summary>Investigation actions and records without observation times ({recorded.length})</summary>
          {recorded.map(event => <div key={event.id}><button onClick={() => activate(event)}>{dateLabel(event.recordedAt!)} · {event.title}</button>
            {event.safety && <p>{safetyEvidenceSummary(event.safety)}{" "}{event.assessmentId && <a className="ws-link" href={safetyAssessmentHref(incident.workspace_id, event.assessmentId)}>Open safety assessment ↗</a>}</p>}
            {event.changes && <div className="incident-change">{Object.entries(event.changes).map(([key, change]) => <p key={key}>{changeLabel(key)}: {changeText(key, change.before)} → {changeText(key, change.after)}</p>)}</div>}
          </div>)}
        </details>
      </>}
    </section>
    {view && <IncidentComparison view={view} selectedIds={validIds ?? view.analyses.map(a => a.id)} loading={loading} onIds={setSelectedIds} selection={selection} onSelect={onSelect} />}
  </>;
}

function changeLabel(key: string) { return ({ status: "Status", conclusion: "Conclusion", title: "Incident title", description: "Incident description", start_time: "Start time", end_time: "End time", time_origin: "Time origin", time_axis_key: "Time source" } as Record<string, string>)[key] || key; }
function changeText(key: string, value: unknown) { return key === "status" ? ({ open: "Open", investigating: "Investigating", resolved: "Conclusion recorded", archived: "Archived" } as Record<string, string>)[String(value)] || "Not set" : value == null ? "Not set" : String(value); }

export function simulationEventHref(incident: Incident, event: TimelineEvent) {
  const source = incident.links.find(l => l.id === event.linkId)!;
  const context = source.details.observationWindow;
  return `#/workspaces/${incident.workspace_id}/simulations/${source.details.simulationId}${source.details.run ? `/${source.details.run.id}` : context ? `/window/${context.windowStart}/${context.asOf}/${context.hypothesis || ""}` : ""}`;
}

function TimelineLanes({ events, axis, selection, activate }: { events: TimelineEvent[]; axis: IncidentAxis; selection: IncidentSelection | null; activate: (event: TimelineEvent) => void }) {
  const lanes = [...new Set(events.map(e => e.analysisId || e.kind))];
  if (!events.length) return null;
  const first = Math.min(...events.map(e => e.start!)), last = Math.max(...events.map(e => e.end!));
  const x = (t: number) => 175 + (t-first)/(last-first || 1)*755;
  return <div className="incident-lanes"><svg viewBox={`0 0 960 ${lanes.length * 34 + 45}`} role="group" aria-label={"Incident development timeline"}>
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
