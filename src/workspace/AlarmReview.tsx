import { useMemo, useState, type FormEvent } from "react";
import { t as tr } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { message } from "./api";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { AlarmEvidence, alarmTime } from "./AlarmEvidence";
import { AlarmLoad, AlarmPages } from "./AlarmLoad";
import { priorityLabel } from "./AlarmSetup";
import { axisLabel, dateLabel, number, type Dataset, type IncidentAxis } from "./types";
import type { AlarmAction, AlarmAudit, AlarmEvent, AlarmGroup, AlarmPolicy, AlarmSession } from "./alarmTypes";

const measuredLabels = { active: "Active at analysis end", cleared: "Observed clear", unknown: "Observation interrupted" };
const endLabels: Record<string, string> = {
  "normal-sample": "Normal sample followed", "analysis-end": "Analysis window ended",
  "data-gap": "Sampling gap followed", abstention: "Detector abstained", "saved-boundary": "Saved interval boundary",
};
const reasonLabels: Record<string, string> = {
  "shared-signal": "Shared signal", "explicit-relationship": "Explicit signal relationship",
  "shared-equipment": "Shared equipment", "detector-agreement": "Agreement across detectors", repeat: "Repeated alarm source",
};
const actionLabels: Record<string, string> = {
  acknowledge: "Acknowledged", shelve: "Shelved", unshelve: "Unshelved",
  note: "Operator note", incident: "Incident linked", "link-incident": "Incident linked",
};
const groupPageSize = 20, eventPageSize = 20;

function operatorLabel(event: AlarmEvent) {
  if (event.operator.shelvedUntil) return "Shelved";
  if (event.operator.acknowledgedAt) return "Acknowledged";
  return "New alarm";
}

function needsAttention(event: AlarmEvent) {
  return event.measuredState === "active" && event.policyEligible && operatorLabel(event) === "New alarm";
}

function AlarmAuditList({ records, workspaceId }: { records: AlarmAudit[]; workspaceId: string }) {
  const [page, setPage] = useState(0);
  const ordered = records.slice().reverse();
  return <>
    {records.length ? <ol className="alarm-audit">
      {ordered.slice(page * eventPageSize, (page + 1) * eventPageSize).map(row => <li key={row.id}>
        <strong>{tr(actionLabels[row.kind] || row.kind)}</strong><span>{dateLabel(row.recordedAt)} · {row.actor}</span>
        {row.note && <p className="incident-prose">{row.note}</p>}
        {row.expiresAt && <small>{tr("Shelved until {0}", { 0: dateLabel(row.expiresAt) })}</small>}
        {row.incidentId && <a className="ws-link" href={`#/workspaces/${workspaceId}/incidents/${row.incidentId}`}>{tr("Open linked incident ↗")}</a>}
      </li>)}
    </ol> : <p className="ws-muted">{tr("No operator actions recorded.")}</p>}
    <AlarmPages page={page} pages={Math.ceil(records.length / eventPageSize)} setPage={setPage} />
  </>;
}

function OperatorActions({ event, policy, actor, busy, onAction }: {
  event: AlarmEvent; policy: AlarmPolicy; actor: string; busy: boolean;
  onAction: (action: AlarmAction) => Promise<void>;
}) {
  const [seconds, setSeconds] = useState(String(Math.min(300, policy.maxShelveSeconds)));
  const [note, setNote] = useState("");
  const [error, setError] = useState(""), [noteSaved, setNoteSaved] = useState(false);
  async function save(action: AlarmAction) {
    setError("");
    setNoteSaved(false);
    try {
      await onAction(action);
      if (action.kind === "note") { setNote(""); setNoteSaved(true); }
    } catch (err) {
      setError(message(err));
    }
  }
  async function annotate(e: FormEvent) {
    e.preventDefault();
    await save({ kind: "note", actor, note: note.trim() });
  }
  function shelve(e: FormEvent) {
    e.preventDefault();
    const expiry = new Date(Date.now() + Number(seconds) * 1000);
    if (!Number.isFinite(expiry.getTime())) { setError("Choose a valid shelf duration."); return; }
    void save({ kind: "shelve", actor, expiresAt: expiry.toISOString() });
  }
  return <section className="alarm-operator" aria-label={tr("Operator actions")}>
    <h3>{tr("Operator actions")}</h3>
    <p>{tr(measuredLabels[event.measuredState])} · {tr(operatorLabel(event))}{event.operator.escalated && <> · <span className="ws-coral">{tr("Escalated")}</span></>}</p>
    <p className="ws-muted">{tr(endLabels[event.endReason] || event.endReason)}</p>
    {event.operator.acknowledgedAt && <p className="ws-muted">{tr("Acknowledged at {0}", { 0: dateLabel(event.operator.acknowledgedAt) })}</p>}
    <div className="alarm-actions">
      {!event.operator.acknowledgedAt && <button className="ws-outlined" type="button" disabled={busy} onClick={() => void save({ kind: "acknowledge", actor })}>{tr("Acknowledge")}</button>}
      {event.operator.shelvedUntil ? <><button className="ws-outlined" type="button" disabled={busy} onClick={() => void save({ kind: "unshelve", actor })}>{tr("Unshelve")}</button>
        <span>{tr("Shelved until {0}", { 0: dateLabel(event.operator.shelvedUntil) })}</span></>
        : policy.maxShelveSeconds > 0 && <form className="alarm-shelf" onSubmit={shelve}>
          <label>{tr("Shelf duration (s)")}<input type="number" min="1" max={policy.maxShelveSeconds} step="any" required value={seconds} onChange={e => setSeconds(e.target.value)} /></label>
          <button className="ws-outlined" disabled={busy}>{tr("Shelve")}</button>
        </form>}
    </div>
    <form className="alarm-note" onSubmit={annotate}>
      <label>{tr("Operator note")}<textarea rows={2} required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label>
      <button className="ws-outlined" disabled={busy || !note.trim()}>{tr("Add note")}</button>
    </form>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {noteSaved && <p className="ws-muted" role="status">{tr("Note saved.")}</p>}
  </section>;
}

function GroupReview({ group, events, axis, datasets, session, busy, actor, onAction, onIncident }: {
  group: AlarmGroup; events: AlarmEvent[]; axis: IncidentAxis; datasets: Dataset[]; session: AlarmSession; busy: boolean; actor: string;
  onAction: (eventId: string, action: AlarmAction) => Promise<void>;
  onIncident: (groupId: string, body: ({ title: string } | { incidentId: string }) & { actor: string }) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState(""), [eventPage, setEventPage] = useState(0), [proofPage, setProofPage] = useState(0);
  const [incidentOpen, setIncidentOpen] = useState(false), [proofOpen, setProofOpen] = useState(false);
  const event = events.find(item => item.id === selectedId);
  const rows = events.slice(eventPage * eventPageSize, (eventPage + 1) * eventPageSize);
  const proofs = group.relationships.slice(proofPage * eventPageSize, (proofPage + 1) * eventPageSize);
  const eventIndex = useMemo(() => new Map(events.map((item, i) => [item.id, i + 1])), [events]);
  const incidentIds = [...new Set(events.flatMap(item => item.operator.incidentIds))];
  const datasetNames = new Map(datasets.map(dataset => [dataset.id, dataset.name]));
  const signalName = (signal: { datasetId: string; signal: string }) => `${datasetNames.get(signal.datasetId) || signal.datasetId} · ${signal.signal}`;
  return <div className="alarm-group-detail" aria-label={tr("Group details")}>
    <div className="alarm-section-heading"><h3>{tr("Original alarms")}</h3><span className="ws-muted">{tr("{0} source alarms", { 0: events.length })}</span></div>
    <p className="ws-muted">{alarmTime(axis, group.start)} → {alarmTime(axis, group.end)} · {priorityLabel(session.policy, group.priority)}</p>
    <div className="ws-table-scroll"><table>
      <thead><tr>{["Detector and dataset", "Observed interval", "Measured state", "Operator state", "Priority"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
      <tbody>{rows.map(item => <tr key={item.id} className={selectedId === item.id ? "alarm-selected-row" : ""}>
        <td><button className="alarm-event-button" aria-pressed={selectedId === item.id} onClick={() => setSelectedId(item.id)}>
          <strong>{eventIndex.get(item.id)} · {tr(item.detectorLabel)}</strong><span>{item.datasetName} · {item.analysisName}</span>
          <span>{item.signals.join(" · ")}</span></button></td>
        <td>{alarmTime(axis, item.start)}<small>{alarmTime(axis, item.end)}</small></td>
        <td>{tr(measuredLabels[item.measuredState])}{!item.policyEligible && <small>{tr("Below persistence requirement")}</small>}</td>
        <td>{tr(operatorLabel(item))}{item.operator.shelvedUntil && item.operator.acknowledgedAt && <small>{tr("Acknowledged")}</small>}{item.operator.escalated && <small className="ws-coral">{tr("Escalated")}</small>}{item.operator.incidentIds.length > 0 && <small>{tr("Investigation linked")}</small>}</td>
        <td>{priorityLabel(session.policy, item.priority)}{item.equipment.length > 0 && <small>{item.equipment.join(" · ")}</small>}</td>
      </tr>)}</tbody>
    </table></div>
    <AlarmPages page={eventPage} pages={Math.ceil(events.length / eventPageSize)} setPage={setEventPage} />
    <details onToggle={e => setProofOpen(e.currentTarget.open)}>
      <summary>{tr("Grouping evidence")} · {group.relationships.length.toLocaleString()}</summary>
      <p className="ws-muted">{tr("Associations describe timing and configured relationships. Confirm physical causes in an investigation.")}</p>
      {proofOpen && (proofs.length ? <ol className="alarm-proofs">
        {proofs.map(proof => <li key={`${proof.leftId}/${proof.rightId}`}>
          <strong>{tr("Alarm {0} ↔ {1}", { 0: eventIndex.get(proof.leftId), 1: eventIndex.get(proof.rightId) })}</strong>
          <span>{proof.temporal === "overlap" ? tr("Temporal overlap") : tr("{0} s apart", { 0: number(proof.gapSeconds) })} · {proof.reasons.map(reason => tr(reasonLabels[reason] || reason)).join(" · ")}</span>
          {proof.signals.length > 0 && <small>{proof.signals.map(signalName).join(" / ")}</small>}
          {proof.explicitPairs?.map(({ left, right }, i) => <small key={i}>{signalName(left)} ↔ {signalName(right)}</small>)}
          {proof.equipment.length > 0 && <small>{proof.equipment.join(" · ")}</small>}
        </li>)}
      </ol> : <p className="ws-muted">{tr("This alarm has no correlated source alarms.")}</p>)}
      <AlarmPages page={proofPage} pages={Math.ceil(group.relationships.length / eventPageSize)} setPage={setProofPage} />
    </details>
    <div className="alarm-actions alarm-incident">
      <button className="ws-outlined" type="button" disabled={busy} onClick={() => setIncidentOpen(true)}>{tr("Create or link incident")}</button>
      {incidentIds.map(id => <a className="ws-link" key={id} href={`#/workspaces/${session.workspaceId}/incidents/${id}`}>{tr("Open linked incident ↗")} · {id.slice(0, 8)}</a>)}
    </div>
    {incidentOpen && <IncidentLinkDialog workspaceId={session.workspaceId}
      draft={{ title: tr("{0} alarm group", { 0: session.name }).slice(0, 160), description: tr("The incident retains the group evidence, source analyses and operator observations.") }}
      saveLinked={target => onIncident(group.id, { ...target, actor })} onClose={() => setIncidentOpen(false)} />}
    {event && <div className="alarm-selected-event" key={event.id}>
      <AlarmEvidence event={event} dataset={datasets.find(d => d.id === event.datasetId)} axis={axis} workspaceId={session.workspaceId} />
      <OperatorActions event={event} policy={session.policy} actor={actor} busy={busy} onAction={action => onAction(event.id, action)} />
      <details><summary>{tr("Event history")}</summary><AlarmAuditList records={session.audit.filter(row => row.eventId === event.id || row.groupId === group.id)} workspaceId={session.workspaceId} /></details>
    </div>}
  </div>;
}

export function AlarmReview({ session, datasets, busy, onAction, onIncident }: {
  session: AlarmSession; datasets: Dataset[]; busy: boolean; onAction: Parameters<typeof GroupReview>[0]["onAction"];
  onIncident: Parameters<typeof GroupReview>[0]["onIncident"];
}) {
  const axes = session.axes;
  const [axisId, setAxisId] = useState(axes[0]?.id || "");
  const axis = axes.find(item => item.id === axisId) || axes[0];
  const flood = session.flood.axes.find(item => item.axisId === axis?.id);
  const [actor, setActor] = useState(""), [datasetId, setDatasetId] = useState(""), [priority, setPriority] = useState("");
  const [measured, setMeasured] = useState(""), [operator, setOperator] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState("");
  const [groupId, setGroupId] = useState(""), [page, setPage] = useState(0);
  const events = useMemo(() => new Map(session.events.map(event => [event.id, event])), [session.events]);
  const datasetNames = useMemo(() => new Map(session.events.map(event => [event.datasetId, event.datasetName])), [session.events]);
  const matching = useMemo(() => {
    const result = new Set<string>();
    if (!axis) return result;
    for (const event of session.events) {
      const status = operator === "Investigation linked" ? event.operator.incidentIds.length > 0
        : operator === "Escalated" ? event.operator.escalated
        : operator === "Acknowledged" ? Boolean(event.operator.acknowledgedAt)
        : operator === "Needs attention" ? needsAttention(event) : operatorLabel(event) === operator;
      if (event.axisId === axis.id && (!datasetId || event.datasetId === datasetId) && (!priority || event.priority === priority)
        && (!measured || event.measuredState === measured) && (!operator || status)
        && (start === "" || event.end >= axis.start + Number(start)) && (end === "" || event.start <= axis.start + Number(end))) result.add(event.id);
    }
    return result;
  }, [session.events, axis, datasetId, priority, measured, operator, start, end]);
  const groups = session.groups.filter(group => group.axisId === axis?.id && group.eventIds.some(id => matching.has(id)));
  const pages = Math.ceil(groups.length / groupPageSize);
  const pageIndex = Math.max(0, Math.min(page, pages - 1));
  const visibleGroups = groups.slice(pageIndex * groupPageSize, (pageIndex + 1) * groupPageSize);
  const group = visibleGroups.find(item => item.id === groupId) || visibleGroups[0];
  const members = group?.eventIds.flatMap(id => { const event = events.get(id); return event ? [event] : []; }) || [];
  const axisSpan = axis ? Math.max(1e-9, axis.end - axis.start) : 1;

  return <>
    <div className="alarm-facts alarm-summary">
      <div><span>{tr("Source alarms")}</span><strong>{session.flood.rawEventCount.toLocaleString()}</strong></div>
      <div><span>{tr("Correlated groups")}</span><strong>{session.flood.groupCount.toLocaleString()}</strong></div>
      <div><span>{tr("Saved analysis results")}</span><strong>{session.analysisIds.length.toLocaleString()}</strong></div>
      <div><span>{tr("Independent time axes")}</span><strong>{axes.length.toLocaleString()}</strong></div>
    </div>
    {axis && <div className="alarm-scope">
      <label>{tr("Timeline clock")}<select value={axis.id} onChange={e => { setAxisId(e.target.value); setStart(""); setEnd(""); setPage(0); }}>
        {axes.map(item => <option key={item.id} value={item.id}>{axisLabel(item, datasets)}</option>)}
      </select></label>
      <label>{tr("Operator name (optional)")}<input value={actor} maxLength={160} onChange={e => setActor(e.target.value)} autoComplete="name" /></label>
    </div>}
    {axis && flood && <AlarmLoad key={axis.id} axis={axis} flood={flood} datasetNames={datasetNames} />}
    {axis && <section className="ws-panel alarm-timeline" aria-label={tr("Alarm timeline")}>
      <div className="alarm-section-heading"><h2>{tr("Alarm timeline")}</h2><span className="ws-muted">{tr("{0} matching alarms in {1} groups", { 0: matching.size.toLocaleString(), 1: groups.length.toLocaleString() })}</span></div>
      <div className="ws-form-grid ws-three alarm-filters">
        <label>{tr("Source dataset")}<select value={datasetId} onChange={e => { setDatasetId(e.target.value); setPage(0); }}><option value="">{tr("All sources")}</option>
          {[...datasetNames].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label>{tr("Priority")}<select value={priority} onChange={e => { setPriority(e.target.value); setPage(0); }}><option value="">{tr("All priorities")}</option>
          {session.policy.priorities.map(({ id }) => <option key={id} value={id}>{priorityLabel(session.policy, id)}</option>)}</select></label>
        <label>{tr("Measured state")}<select value={measured} onChange={e => { setMeasured(e.target.value); setPage(0); }}><option value="">{tr("All measured states")}</option>
          {Object.entries(measuredLabels).map(([id, label]) => <option key={id} value={id}>{tr(label)}</option>)}</select></label>
        <label>{tr("Operator state")}<select value={operator} onChange={e => { setOperator(e.target.value); setPage(0); }}><option value="">{tr("All operator states")}</option>
          {["Needs attention", "New alarm", "Acknowledged", "Shelved", "Escalated", "Investigation linked"].map(label => <option key={label} value={label}>{tr(label)}</option>)}</select></label>
        <label>{tr("From offset (s)")}<input type="number" step="any" value={start} onChange={e => { setStart(e.target.value); setPage(0); }} /></label>
        <label>{tr("To offset (s)")}<input type="number" step="any" value={end} onChange={e => { setEnd(e.target.value); setPage(0); }} /></label>
      </div>
      <p className="ws-muted">{tr("Filter offsets are relative to {0}. Matched groups show all source alarms.", { 0: alarmTime(axis, axis.start) })}</p>
      {visibleGroups.length ? <div className="alarm-review-grid">
        <div className="alarm-group-list" aria-label={tr("Correlated groups")}>
          {visibleGroups.map(item => {
            const left = Math.min(99, Math.max(0, 100 * (item.start - axis.start) / axisSpan));
            const width = Math.min(100 - left, 100 * (item.end - item.start) / axisSpan);
            const count = item.eventIds.filter(id => matching.has(id)).length;
            const representative = events.get(item.eventIds[0]);
            return <button type="button" className="alarm-group-button" key={item.id} aria-pressed={group?.id === item.id} onClick={() => setGroupId(item.id)}>
              <span><strong>{alarmTime(axis, item.start)}</strong><small>{priorityLabel(session.policy, item.priority)}</small></span>
              <span>{representative?.equipment[0] || representative?.signals[0] || representative?.datasetName}<small>{tr("{0} source alarms", { 0: item.eventIds.length })}</small></span>
              <span className="alarm-track" aria-hidden="true"><i style={{ left: `${left}%`, width: `${width}%` }} /></span>
              {count !== item.eventIds.length && <small>{tr("{0} match filters", { 0: count })}</small>}
            </button>;
          })}
          <AlarmPages page={pageIndex} pages={pages} setPage={setPage} />
        </div>
        {group && <GroupReview key={group.id} group={group} events={members} axis={axis} datasets={datasets} session={session} busy={busy} actor={actor} onAction={onAction} onIncident={onIncident} />}
      </div> : <p className="alarm-empty">{tr("No alarms match these filters on this clock.")}</p>}
    </section>}
    <details className="ws-panel alarm-session-history"><summary>{tr("Session audit history")} · {session.audit.length.toLocaleString()}</summary>
      <AlarmAuditList records={session.audit} workspaceId={session.workspaceId} />
    </details>
  </>;
}
