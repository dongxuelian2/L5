import { useEffect, useRef, useState } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { alarmTime } from "./AlarmEvidence";
import { AlarmReview } from "./AlarmReview";
import { AlarmSetup } from "./AlarmSetup";
import { axisLabel, dateLabel, number, type Dataset, type Job } from "./types";
import type { AlarmAction, AlarmPolicy, AlarmSession, AlarmSessionSummary } from "./alarmTypes";
import "./alarms.css";

const sessionPath = (id: string) => `/alarm-sessions/${id}`;

function nextStateChange(session: AlarmSession) {
  const now = Date.parse(session.asOf);
  const escalation = Date.parse(session.createdAt) + (session.policy.escalationSeconds ?? 0) * 1000;
  let next = Infinity;
  for (const event of session.events) {
    const expiry = event.operator.shelvedUntil && Date.parse(event.operator.shelvedUntil);
    if (expiry && expiry > now) next = Math.min(expiry, next);
    if (session.policy.escalationSeconds != null && escalation > now && event.policyEligible
      && event.measuredState === "active" && !event.operator.acknowledgedAt) next = Math.min(escalation, next);
  }
  return next - now;
}

export function AlarmWorkspace({ workspaceId, datasets, jobs, sessionId }: {
  workspaceId: string; datasets: Dataset[]; jobs: Job[]; sessionId?: string;
}) {
  const locale = useLocale();
  const [sessions, setSessions] = useState<AlarmSessionSummary[]>([]);
  const [saved, setSaved] = useState<AlarmSession | null>(null);
  const [setup, setSetup] = useState<{ basedOn: AlarmSession | null } | null>(null);
  const [error, setError] = useState(""), [listError, setListError] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(false);
  const context = useRef(0);
  const listPath = `/workspaces/${workspaceId}/alarm-sessions`;
  const page = `workspaces/${workspaceId}/alarms`;
  const session = saved?.id === sessionId ? saved : null;
  useEffect(() => {
    const controller = new AbortController();
    api<{ sessions: AlarmSessionSummary[] }>(listPath, undefined, "GET", controller.signal)
      .then(result => setSessions(result.sessions))
      .catch(err => { if (!controller.signal.aborted) setListError(message(err)); });
    return () => controller.abort();
  }, [listPath]);
  useEffect(() => {
    context.current++;
    setError("");
    setBusy(false);
    setSetup(null);
    if (!sessionId) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    api<AlarmSession>(sessionPath(sessionId), undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted && data.workspaceId === workspaceId) setSaved(data); })
      .catch(err => { if (!controller.signal.aborted) setError(message(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); context.current++; };
  }, [sessionId, workspaceId]);
  useEffect(() => {
    if (!session || busy) return;
    const next = nextStateChange(session);
    if (!Number.isFinite(next)) return;
    const controller = new AbortController();
    // Timer delays are measured from the service's snapshot time.
    const timer = setTimeout(() => {
      api<AlarmSession>(sessionPath(session.id), undefined, "GET", controller.signal)
        .then(data => { if (!controller.signal.aborted) setSaved(data); })
        .catch(err => { if (!controller.signal.aborted) setError(message(err)); });
    }, Math.min(next + 50, 2_147_483_647));
    return () => { clearTimeout(timer); controller.abort(); };
  }, [session, busy]);
  async function create(name: string, analysisIds: string[], policy: AlarmPolicy) {
    const request = context.current;
    setBusy(true);
    setError("");
    try {
      const result = await api<AlarmSession>(listPath, { name, analysisIds, policy });
      if (request !== context.current) return;
      setSaved(result);
      setSessions(items => [result, ...items.filter(item => item.id !== result.id)]);
      setSetup(null);
      go(`${page}/${result.id}`);
    } catch (err) { if (request === context.current) setError(message(err)); }
    finally { if (request === context.current) setBusy(false); }
  }
  async function mutate(path: string, body: { actor?: string } & Record<string, unknown>) {
    const request = context.current;
    setBusy(true);
    setError("");
    try {
      const result = await api<AlarmSession>(path, { ...body, actor: body.actor?.trim() || undefined });
      if (request === context.current) setSaved(result);
    } finally { if (request === context.current) setBusy(false); }
  }
  async function act(eventId: string, action: AlarmAction) {
    if (session) await mutate(`${sessionPath(session.id)}/events/${eventId}/actions`, action);
  }
  return <div className="alarm-workspace notranslate" translate="no">
    <header className="ws-page-title"><div><h1>{tr("Alarm workspace")}<span className="ws-accent">.</span></h1>
      <p>{tr("Review related detector alarms, track operator actions and carry the evidence into an incident.")}</p></div>
      {!setup && <button className="ws-primary" onClick={() => setSetup({ basedOn: null })}>{tr("New alarm session")}</button>}
    </header>
    <div className="ws-panel alarm-session-bar">
      <label>{tr("Saved alarm session")}<select value={sessionId || ""} onChange={e => go(e.target.value ? `${page}/${e.target.value}` : page)}>
        <option value="">{tr("Choose a session")}</option>
        {sessionId && !sessions.some(item => item.id === sessionId) && <option value={sessionId}>{session?.name || tr("Opening alarm session…")}</option>}
        {sessions.map(item => <option key={item.id} value={item.id}>{item.name} · {dateLabel(item.createdAt)}</option>)}
      </select></label>
      {session && <div className="alarm-actions">
        <a className="ws-link" href={`/api${sessionPath(session.id)}/history.json`} download>{tr("Export history JSON")}</a>
        <a className="ws-link" href={`/api${sessionPath(session.id)}/report.html?lang=${locale}&download=1`} download>{tr("Export report HTML")}</a>
        {!setup && <button className="ws-outlined" onClick={() => setSetup({ basedOn: session })}>{tr("Regroup as new session")}</button>}
      </div>}
    </div>
    {(error || listError) && <p className="ws-error" role="alert">{errorMessage(error || listError)}</p>}
    {setup && <AlarmSetup datasets={datasets} jobs={jobs} basedOn={setup.basedOn} busy={busy} onCreate={create} onCancel={() => { setSetup(null); setError(""); }} />}
    {loading && !session && <p role="status">{tr("Opening alarm session…")}</p>}
    {session && <><div className="alarm-section-heading alarm-session-heading">
      <h2>{session.name}</h2><span className="ws-muted">{tr("Operator state as of {0}", { 0: dateLabel(session.asOf) })}</span>
    </div>
      {!!session.sources?.length && <details className="ws-panel alarm-policy-summary"><summary>{tr("Analysis sources")}</summary>
        <div className="ws-table-scroll"><table>
          <thead><tr>{["Analysis", "Detector and dataset", "Observed interval", "Analysis coverage", "Analysis abstentions"].map(label => <th key={label}>{tr(label)}</th>)}</tr></thead>
          <tbody>{session.sources.map(source => {
            const axis = session.axes.find(item => item.id === source.clock.axisId);
            return <tr key={source.analysisId}>
              <td><a className="ws-link" href={`#/workspaces/${workspaceId}/analysis/${source.analysisId}`}>{source.analysisName} ↗</a></td>
              <td>{tr(source.detectorLabel)} · {source.datasetName}</td>
              <td>{axis && <>{axisLabel(axis, datasets)}<br />{alarmTime(axis, source.start)} → {alarmTime(axis, source.end)}</>}</td>
              <td>{source.coverageFraction == null ? "—" : `${number(source.coverageFraction * 100)}%`}</td>
              <td>{source.abstainedSamples?.toLocaleString() ?? "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>
      </details>}
      <details className="ws-panel alarm-policy-summary"><summary>{tr("Saved alarm policy")}</summary>
        <p>{tr("Correlation {0} s · Repeat {1} s · Persistence {2} samples / {3} s", {
          0: number(session.policy.proximitySeconds), 1: number(session.policy.repeatWindowSeconds),
          2: session.policy.minSamples, 3: number(session.policy.minDurationSeconds),
        })}</p>
        <p>{tr("{0} signal mappings · {1} explicit relationships", { 0: session.policy.mappings.length, 1: session.policy.relationships.length })}</p>
      </details>
      <AlarmReview key={session.id} session={session} datasets={datasets} busy={busy} onAction={act}
        onIncident={(id, body) => mutate(`${sessionPath(session.id)}/groups/${id}/incident`, { ...body, locale })} />
    </>}
    {!sessionId && !setup && <div className="alarm-empty ws-panel">
      <h2>{tr(sessions.length ? "Open an alarm session" : "Build an alarm timeline")}</h2>
      <p>{tr(sessions.length ? "Choose a saved session to reopen its timeline and operator history." : "Select saved analyses and configure the policy for your first session.")}</p>
    </div>}
  </div>;
}
