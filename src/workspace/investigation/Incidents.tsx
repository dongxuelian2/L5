import { errorMessage, t as tr } from "../../lib/text";
import { TransformationLineage } from "../data/TransformationWorkspace";
import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { api, message, prognosticSessionHref } from "../api";
import { SensorHealthResult } from "../monitoring/SensorHealthWorkspace";
import type { HealthResult } from "../monitoring/sensorHealthTypes";
import { Plot, SignalPlots } from "../Charts";
import { intervalWindow } from "../monitoring/findings";
import { IncidentLinkDialog, incidentStatuses } from "./IncidentLinkDialog";
import { Contributions } from "../monitoring/Results";
import { IncidentTimeline } from "./IncidentTimeline";
import { IncidentReport } from "./IncidentReport";
import { forecastStatus } from "../reliability/prognosticLabels";
import { dateLabel, datasetClock, datasetTimeLabel, namedSignal, number, safetyAssessmentHref, safetyEvidenceSummary, signalLabel, timeLabel, type AnalysisResult, type Dataset, type Incident, type IncidentEntry, type IncidentLink, type IncidentSource, type IncidentSummary, type Job, type RuntimeRun, type TimeAxis, type IncidentSelection } from "../types";

const SavedRunView = lazy(() => import("../modeling/RuntimeWorkbench").then(m => ({ default: m.SavedRunView })));
const entryKinds = { get note() { return "Investigation note"; }, get evidence() { return "Evidence"; }, get hypothesis() { return "Hypothesis"; } };
const stances = { get neutral() { return "Undecided"; }, get support() { return "Supports"; }, get oppose() { return "Opposes"; } };
const linkKinds = {
  dataset: "Dataset", analysis: "Analysis result", interval: "Anomaly interval",
  simulation: "Simulation session", run: "Investigation or intervention", "sensor-health": "Sensor health",
  prognostic: "Prognostic forecast", "safety-observed": "Observed constraint violation",
  "safety-predicted": "Predicted constraint violation",
};
const runKinds: Record<string, string> = { get tools() { return "Tool investigation"; }, get tool() { return "Tool investigation"; }, get assistant() { return "Assistant investigation"; }, get intervention() { return "Intervention experiment"; } };
const numericAxis: TimeAxis = { kind: "numeric", column: null, origin: null, start: 0, end: 0 };
function eventTime(incident: IncidentSummary, value: number | null, datasets: Dataset[] = []) {
  const dataset = datasets.find(d => `dataset:${d.id}` === incident.time_axis_key || d.metadata.model && `simulation:${d.metadata.model.simulationId}` === incident.time_axis_key);
  return value == null ? "Undetermined" : incident.time_origin ? timeLabel({ ...numericAxis, origin: incident.time_origin }, value) : dataset ? datasetTimeLabel(dataset, value) : timeLabel(numericAxis, value);
}
function entryTime(entry: IncidentEntry, incident: Incident, datasets: Dataset[]) {
  const link = incident.links.find(l => l.id === entry.source_link_id);
  const dataset = datasets.find(d => `dataset:${d.id}` === entry.observed_axis_key) || datasets.find(d => d.id === link?.details.datasetId);
  return entry.observed_at == null ? "" : entry.observed_axis_key?.startsWith("origin:") ? timeLabel({ ...numericAxis, origin: entry.observed_axis_key.slice(7) }, entry.observed_at) : dataset ? datasetTimeLabel(dataset, entry.observed_at) : eventTime(incident, entry.observed_at, datasets);
}

export function IncidentsPage({ workspaceId, incidentId, datasets, jobs }: { workspaceId: string; incidentId?: string; datasets: Dataset[]; jobs: Job[] }) {
  return incidentId ? <IncidentPage key={incidentId} workspaceId={workspaceId} incidentId={incidentId} datasets={datasets} jobs={jobs} /> : <IncidentList key={workspaceId} workspaceId={workspaceId} datasets={datasets} />;
}

function IncidentList({ workspaceId, datasets }: { workspaceId: string; datasets: Dataset[] }) {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]), [status, setStatus] = useState(""), [q, setQ] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState(""), [sort, setSort] = useState("updated");
  const [creating, setCreating] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    const timer = setTimeout(() => {
      const query = new URLSearchParams({ status, q, ...(start !== "" ? { start } : {}), ...(end !== "" ? { end } : {}) });
      api<{ incidents: IncidentSummary[] }>(`/workspaces/${workspaceId}/incidents?${query}`, undefined, "GET", controller.signal)
        .then(data => setIncidents(data.incidents)).catch(e => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [workspaceId, status, q, start, end]);
  const sorted = sort === "time" ? [...incidents].sort((a, b) => (b.start_time ?? -Infinity) - (a.start_time ?? -Infinity)) : incidents;
  return <div className="incident-workstation">
    <div className="ws-page-title"><div><div className="ws-kicker">05 / INCIDENT INVESTIGATION</div><h1>Incident investigation<span className="ws-accent">.</span></h1><p>Organize detection intervals, analyses and investigation work into an incident you can maintain over time.</p></div><button className="ws-primary" onClick={() => setCreating(true)}>＋ Create incident</button></div>
    <div className="ws-panel"><div className="ws-form-grid incident-filters">
      <label>Find incidents<input placeholder={"Title or incident description"} value={q} onChange={e => setQ(e.target.value)} /></label>
      <label>Investigation status<select value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{Object.entries(incidentStatuses).map(([key, label]) => <option key={key} value={key}>{tr(label)}</option>)}</select></label>
      <label>Intersecting range start (seconds)<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>Intersecting range end (seconds)<input type="number" step="any" value={end} onChange={e => setEnd(e.target.value)} /></label>
      <label>Sort by<select value={sort} onChange={e => setSort(e.target.value)}><option value="updated">Recently updated</option><option value="time">Incident time</option></select></label>
    </div><p className="ws-muted">Time search uses each incident’s own clock seconds and matches incidents intersecting the specified range.</p></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {loading ? <p role="status">Loading incidents…</p> : !error && (sorted.length ? <div className="ws-history">{sorted.map(i => <a className="ws-history-row" key={i.id} href={`#/workspaces/${workspaceId}/incidents/${i.id}`}>
      <div><span className="ws-kicker">{incidentStatuses[i.status]}{" "}· Updated{" "}{dateLabel(i.updated_at)}</span><h2>{i.title}</h2><p>{eventTime(i, i.start_time, datasets)} → {eventTime(i, i.end_time, datasets)}</p><p>{i.description.slice(0, 120)}</p></div><div><strong className="ws-accent">{i.analysis_count}{" "}analyses ·{" "}{i.interval_count}{" "}intervals</strong><span>Continue investigation ↗</span></div>
    </a>)}</div> : <div className="ws-empty"><h2>No matching incidents yet</h2><p>Create one here or start from “Create incident” in an anomaly detection result.</p></div>)}
    {creating && <IncidentLinkDialog workspaceId={workspaceId} draft={{ title: "New incident" }} onClose={() => setCreating(false)} />}
  </div>;
}

function IncidentPage({ workspaceId, incidentId, datasets, jobs }: { workspaceId: string; incidentId: string; datasets: Dataset[]; jobs: Job[] }) {
  const [incident, setIncident] = useState<Incident | null>(null), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Incident>(`/incidents/${incidentId}`, undefined, "GET", controller.signal).then(data => {
      if (data.workspace_id !== workspaceId) throw new Error("This incident belongs to another workspace.");
      setIncident(data);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [incidentId, workspaceId]);
  return error ? <p className="ws-error" role="alert">{errorMessage(error)}</p> : incident ? <IncidentDetail initial={incident} datasets={datasets} jobs={jobs} /> : <p role="status">Restoring incident and investigation records…</p>;
}

export function IncidentDetail({ initial, datasets, jobs }: { initial: Incident; datasets: Dataset[]; jobs: Job[] }) {
  const [incident, setIncident] = useState(initial), [draft, setDraft] = useState(initial), [conclusion, setConclusion] = useState(initial.conclusion);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(initial.links.find(l => l.kind === "interval")?.id || initial.links.find(l => l.details.datasetId && l.kind !== "safety-predicted")?.id || "");
  const [editing, setEditing] = useState<IncidentEntry | "new" | null>(null), [newKind, setNewKind] = useState<IncidentEntry["kind"]>("note");
  const [adding, setAdding] = useState(false);
  const [selection, setSelection] = useState<IncidentSelection | null>(null);
  const preview = useRef<HTMLDivElement>(null);
  const base = `/incidents/${incident.id}`;
  function inspect(sourceId: string) {
    setFocused(sourceId);
    const source = incident.links.find(l => l.id === sourceId), dataset = datasets.find(d => d.id === source?.details.datasetId);
    if (source) {
      const interval = sourceInterval(source);
      const range = interval && source.details.analysisRange ? intervalWindow(interval, source.details.analysisRange) : source.details.analysisRange || source.details.observationWindow && [source.details.observationWindow.windowStart, source.details.observationWindow.asOf] || (source.details.run ? [Number(source.details.run.request.windowStart || 0), Number(source.details.run.request.asOf)] : dataset && [dataset.metadata.time.start, dataset.metadata.time.end]);
      const clock = dataset ? datasetClock(dataset) : { axisId: `simulation:${source.details.simulationId}`, offset: 0 };
      if (range) setSelection({ axisId: clock.axisId, start: range[0]+clock.offset, end: range[1]+clock.offset, at: (interval?.peakTime ?? range[1])+clock.offset, linkId: sourceId, analysisId: source.details.analysisId, intervalIndex: source.details.intervalIndex });
    }
    preview.current?.scrollIntoView({ behavior: "instant", block: "start" });
  }
  function selectWindow(value: IncidentSelection) {
    setSelection(value);
    const source = incident.links.find(l => l.id === value.linkId) || incident.links.find(l => l.details.analysisId === value.analysisId && value.analysisId)
      || incident.links.find(l => { const dataset = datasets.find(d => d.id === l.details.datasetId); return dataset ? datasetClock(dataset).axisId === value.axisId : `simulation:${l.details.simulationId}` === value.axisId; });
    setFocused(source?.id || "");
    requestAnimationFrame(() => preview.current?.scrollIntoView({ behavior: "instant", block: "start" }));
  }
  async function mutate(path: string, body?: unknown, method?: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await api<Incident>(`${base}${path}`, body, method);
      setIncident(updated); setNotice("Saved to the workspace. Continue investigating the next time you open it.");
      if (focused && !updated.links.some(link => link.id === focused)) {
        setFocused(updated.links.find(link => (link.details.datasetId && link.kind !== "safety-predicted") || link.details.run)?.id || ""); setSelection(null);
      }
      return true;
    } catch (e) { setError(message(e)); return false; } finally { setBusy(false); }
  }
  function basic(e: FormEvent) {
    e.preventDefault();
    void mutate("", { title: draft.title, description: draft.description, start_time: draft.start_time, end_time: draft.end_time, time_origin: draft.time_origin, time_axis_key: draft.time_axis_key, status: draft.status }, "PATCH");
  }
  const hypotheses = incident.entries.filter(e => e.kind === "hypothesis"), records = incident.entries.filter(e => e.kind !== "hypothesis");
  const link = incident.links.find(l => l.id === focused);
  function begin(kind: IncidentEntry["kind"]) { setNewKind(kind); setEditing("new"); }
  return <div className="incident-workstation">
    <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/incidents`}>← Back to incidents</a>
    <div className="ws-page-title"><div><div className="ws-kicker">INCIDENT /{" "}{incident.id.slice(0, 8)}</div><h1>{incident.title}</h1><p>{incidentStatuses[incident.status]}{" "}· Created{" "}{dateLabel(incident.created_at)}{" "}· Updated{" "}{dateLabel(incident.updated_at)}</p></div><span className="ws-badge">{new Set(incident.links.filter(l => l.details.analysisId).map(l => l.details.analysisId)).size}{" "}linked analyses</span></div>
    <nav className="incident-nav" aria-label={"Incident investigation sections"}>{[["information", "Overview"], ["timeline", "Timeline"], ["comparison", "Analysis comparison"], ["sources", "Data and analysis"], ["investigation", "Investigation and evidence"], ["conclusion", "Investigation conclusion"], ["report", "Professional report"]].map(([id, title]) => <a key={id} href={`#incident-${id}`} onClick={e => { e.preventDefault(); document.getElementById(`incident-${id}`)?.scrollIntoView(); }}>{title}</a>)}</nav>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{notice && <p className="ws-saved" role="status">{tr(notice)}</p>}
    <form className="ws-panel incident-form" id="incident-information" onSubmit={basic}>
      <div className="ws-section-heading"><h2>Incident information</h2><span className="ws-muted">{eventTime(incident, incident.start_time, datasets)} → {eventTime(incident, incident.end_time, datasets)}</span></div>
      <div className="ws-form-grid"><label>Incident title<input required maxLength={160} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label><label>Investigation status<select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value as Incident["status"] })}>{Object.entries(incidentStatuses).map(([k, v]) => <option value={k} key={k}>{v}</option>)}</select></label></div>
      <div className="ws-form-grid"><label>Start time (seconds)<input type="number" step="any" value={draft.start_time ?? ""} onChange={e => setDraft({ ...draft, start_time: e.target.value === "" ? null : Number(e.target.value) })} /></label><label>End time (seconds)<input type="number" step="any" min={draft.start_time ?? undefined} value={draft.end_time ?? ""} onChange={e => setDraft({ ...draft, end_time: e.target.value === "" ? null : Number(e.target.value) })} /></label></div>
      <label>Time origin (date and time with timezone, optional)<input placeholder={"For example 2026-10-24T08:00:00Z"} value={draft.time_origin || ""} onChange={e => setDraft({ ...draft, time_origin: e.target.value || null })} /></label>
      <label>Reference source for incident seconds<select value={draft.time_axis_key || ""} onChange={e => setDraft({ ...draft, time_axis_key: e.target.value || null })}><option value="">Independent incident clock (not aligned to data)</option>{datasets.map(d => <option key={d.id} value={d.metadata.model ? `simulation:${d.metadata.model.simulationId}` : `dataset:${d.id}`}>{d.name}</option>)}</select></label><p className="ws-muted">The time origin takes precedence over the reference source. For older incidents without a reference, specify the dataset whose seconds they use.</p>
      <label>Incident description<textarea rows={3} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} maxLength={50000} /></label>
      <p className="ws-muted">You maintain the incident range. Each source’s curves and anomaly intervals retain their own clock; linking datasets does not automatically shift time.</p>
      <div className="ws-inline"><button className="ws-primary" disabled={busy}>Save information</button>{incident.status !== "archived" && <button type="button" disabled={busy} onClick={async () => { if (await mutate("", { status: "archived" }, "PATCH")) setDraft(d => ({ ...d, status: "archived" })); }}>Archive incident</button>}</div>
    </form>

    <IncidentTimeline incident={incident} selection={selection} onSelect={selectWindow} onRecord={event => { const entry = incident.entries.find(e => e.id === event.entryId); if (entry) setEditing(entry); }} onSection={id => document.getElementById(id)?.scrollIntoView()} />
    <div ref={preview} id="incident-window" className="incident-preview-anchor">{link ? <SourcePreview key={link.id} source={link} workspaceId={incident.workspace_id} datasets={datasets} selection={selection} onSelection={setSelection} /> : selection && <p className="ws-notice">No displayable measurements are linked to this clock. Link a source under Data and analysis.</p>}</div>

    <section id="incident-sources"><div className="ws-section-heading"><h2>Related data, analyses and simulations</h2><button className="ws-outlined" onClick={() => setAdding(!adding)}>{adding ? "Hide link selection" : "＋ Link existing record"}</button></div>
      {adding && <SourcePicker incident={incident} datasets={datasets} jobs={jobs} busy={busy} attach={source => mutate("/links", source)} />}
      {!incident.links.length && <p className="ws-notice">Link an existing dataset or analysis, or record a manual observation first. Incidents from ordinary CSV data can be investigated directly.</p>}
      <div className="incident-source-grid">{incident.links.map(source => <article className={`ws-panel incident-source ${source.id === focused ? "incident-selected" : ""}`} key={source.id}>
        <div className="ws-inline ws-between"><span className="ws-kicker">{linkKinds[source.kind]}</span><button className="ws-danger" disabled={busy} onClick={() => void mutate(`/links/${source.id}`, undefined, "DELETE")} aria-label={tr("Unlink {0}", {0: source.details.title})}>Unlink</button></div>
        <h3>{source.details.title}</h3><SourceSummary source={source} datasets={datasets} />{datasets.find(d => d.id === source.details.datasetId)?.metadata.transformation && <TransformationLineage dataset={datasets.find(d => d.id === source.details.datasetId)!} />}
        <div className="ws-inline incident-actions">{source.kind !== "prognostic" && source.details.datasetId && !source.details.safety && datasets.some(d => d.id === source.details.datasetId) && <button onClick={() => inspect(source.id)} aria-pressed={focused === source.id}>View original curves</button>}
          {source.details.assessmentId && <a className="ws-link" href={safetyAssessmentHref(incident.workspace_id, source.details.assessmentId)}>Open safety assessment ↗</a>}
          {source.details.diagnosticId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/sensor-health/${source.details.diagnosticId}`}>Open sensor diagnostics ↗</a>}{source.details.analysisId && <a className="ws-link" href={analysisHref(incident.workspace_id, source)}>Open original analysis ↗</a>}
          {source.details.simulationId && <a className="ws-link" href={simulationHref(incident.workspace_id, source)}>Return to simulation ↗</a>}
          {source.details.resilience?.runId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/resilience/runs/${source.details.resilience.runId}`}>Open resilience evidence ↗</a>}
          {source.details.resilience?.campaignId && source.details.resilience.caseId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/resilience/campaigns/${source.details.resilience.campaignId}/${source.details.resilience.caseId}`}>Open resilience evidence ↗</a>}
          {source.kind === "run" && <button onClick={() => inspect(source.id)} aria-pressed={focused === source.id}>View saved result</button>}
          <PrognosticSourceLink source={source} workspaceId={incident.workspace_id} />
          <button onClick={() => { setFocused(source.id); begin("evidence"); }}>Record source evidence</button>
        </div>
      </article>)}</div>
    </section>

    <section id="incident-investigation"><div className="ws-section-heading"><h2>Hypotheses and evidence relationships</h2><button className="ws-outlined" onClick={() => begin("hypothesis")}>＋ Add hypothesis</button></div>
      <div className="incident-hypotheses">{hypotheses.map(h => <article className="ws-panel" key={h.id} id={`incident-entry-${h.id}`}>
        <EntryHeading entry={h} busy={busy} edit={() => setEditing(h)} remove={() => mutate(`/entries/${h.id}`, undefined, "DELETE")} />
        <p className="incident-prose">{h.content}</p><EntrySource entry={h} incident={incident} />
        <div className="incident-evidence-columns">{(["support", "oppose", "neutral"] as const).map(stance => <div key={stance}><h3>{stances[stance]}Evidence</h3>{records.filter(e => e.hypothesis_id === h.id && e.stance === stance).map(e => <button className="incident-evidence-ref" key={e.id} onClick={() => setEditing(e)}><strong>{e.title}</strong><span>{e.content}</span></button>)}</div>)}</div>
      </article>)}</div>
      {!hypotheses.length && <p className="ws-notice">Write an explanation to test, then record observations or tool results as supporting, opposing or undecided evidence.</p>}
      <div className="ws-section-heading"><h2>Investigation evidence and notes</h2><div className="ws-inline"><button className="ws-outlined" onClick={() => begin("evidence")}>＋ Add evidence</button><button className="ws-outlined" onClick={() => begin("note")}>＋ Add note</button></div></div>
      {records.map(e => <article className="ws-panel" key={e.id} id={`incident-entry-${e.id}`}>
        <EntryHeading entry={e} busy={busy} edit={() => setEditing(e)} remove={() => mutate(`/entries/${e.id}`, undefined, "DELETE")} />
        <p className="incident-prose">{e.content}</p>{e.hypothesis_id && <p className={e.stance === "oppose" ? "ws-coral" : "ws-accent"}>{stances[e.stance]}: {hypotheses.find(h => h.id === e.hypothesis_id)?.title}</p>}
        {e.observed_at != null && <p className="ws-muted">Observation time:{entryTime(e, incident, datasets)}</p>}<EntrySource entry={e} incident={incident} />
      </article>)}
      {!records.length && <p className="ws-notice">Record field observations, analysis interpretations or next investigation steps. Saved records remain editable.</p>}
      {editing && <EntryEditor key={editing === "new" ? `new-${newKind}-${focused}` : editing.id} entry={editing === "new" ? undefined : editing} kind={newKind} incident={incident} sourceId={focused} busy={busy} error={error} onClose={() => setEditing(null)} save={async value => { if (await mutate(editing === "new" ? "/entries" : `/entries/${editing.id}`, value, editing === "new" ? "POST" : "PATCH")) setEditing(null); }} />}
    </section>

    <form className="ws-panel incident-form" id="incident-conclusion" onSubmit={e => { e.preventDefault(); void mutate("", { conclusion }, "PATCH"); }}><h2>Current investigation conclusion</h2><p className="ws-muted">Retain confirmed explanations, remaining uncertainty and follow-up actions.</p><label>Investigation conclusion<textarea rows={6} maxLength={50000} value={conclusion} onChange={e => setConclusion(e.target.value)} /></label><button className="ws-primary" disabled={busy}>Save investigation conclusion</button></form>
    <IncidentReport incident={incident} />
  </div>;
}

function EntryHeading({ entry, busy, edit, remove }: { entry: IncidentEntry; busy: boolean; edit: () => void; remove: () => Promise<boolean> }) {
  const [confirming, setConfirming] = useState(false);
  return <div className="ws-section-heading"><div><span className="ws-kicker">{entryKinds[entry.kind]} · {dateLabel(entry.updated_at)}</span><h3>{entry.title}</h3></div><div className="ws-inline"><button onClick={edit} disabled={busy}>Edit</button>{confirming ? <><button className="ws-danger" disabled={busy} onClick={() => void remove()}>Confirm removal</button><button onClick={() => setConfirming(false)}>Cancel</button></> : <button className="ws-danger" disabled={busy} onClick={() => setConfirming(true)}>Remove</button>}</div></div>;
}

function EntrySource({ entry, incident }: { entry: IncidentEntry; incident: Incident }) {
  const source = incident.links.find(l => l.id === entry.source_link_id);
  return source ? <p className="ws-muted">Source:{source.details.title} · {linkKinds[source.kind]} {source.details.diagnosticId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/sensor-health/${source.details.diagnosticId}`}>Open sensor diagnostics ↗</a>}{source.details.analysisId && <a className="ws-link" href={analysisHref(incident.workspace_id, source)}>Open analysis ↗</a>}{source.details.simulationId && <a className="ws-link" href={simulationHref(incident.workspace_id, source)}>Open simulation ↗</a>}<PrognosticSourceLink source={source} workspaceId={incident.workspace_id} /></p> : null;
}

function EntryEditor({ entry, kind, incident, sourceId, busy, error, onClose, save }: { entry?: IncidentEntry; kind: IncidentEntry["kind"]; incident: Incident; sourceId: string; busy: boolean; error: string; onClose: () => void; save: (value: Partial<IncidentEntry>) => Promise<void> }) {
  const [value, setValue] = useState({ kind: entry?.kind || kind, title: entry?.title || "", content: entry?.content || "", hypothesis_id: entry?.hypothesis_id || "", stance: entry?.stance || "neutral", source_link_id: entry ? entry.source_link_id || "" : kind === "evidence" ? sourceId : "", observed_at: entry?.observed_at == null ? "" : String(entry.observed_at) });
  const dialog = useRefDialog();
  return <dialog ref={dialog} className="incident-dialog" aria-labelledby="entry-editor-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}><form className="incident-form" onSubmit={e => { e.preventDefault(); void save({ ...value, hypothesis_id: value.hypothesis_id || null, source_link_id: value.source_link_id || null, observed_at: value.observed_at === "" ? null : Number(value.observed_at) }); }}>
    <div className="ws-inline ws-between"><h2 id="entry-editor-title">{entry ? "Edit" : "Add"}{entryKinds[value.kind]}</h2><button type="button" onClick={onClose} disabled={busy} aria-label={"Close investigation record dialog"}>×</button></div>
    <label>Record title<input autoFocus required maxLength={160} value={value.title} onChange={e => setValue({ ...value, title: e.target.value })} /></label><label>Record content<textarea rows={6} maxLength={50000} value={value.content} onChange={e => setValue({ ...value, content: e.target.value })} /></label>
    <label>Observation time (seconds, optional)<input type="number" step="any" value={value.observed_at} onChange={e => setValue({ ...value, observed_at: e.target.value })} /></label>
    <label>Evidence source<select value={value.source_link_id} onChange={e => setValue({ ...value, source_link_id: e.target.value })}><option value="">Manual record / incident clock</option>{incident.links.map(l => <option key={l.id} value={l.id}>{linkKinds[l.kind]} · {l.details.title}{l.details.interval ? ` · ${number(l.details.interval.start)}–${number(l.details.interval.end)}s` : ""}</option>)}</select></label><p className="ws-muted">Observation time uses the selected source’s clock, or the incident clock if no source is selected.</p>
    {value.kind === "evidence" && <div className="ws-form-grid"><label>Related hypothesis<select value={value.hypothesis_id} onChange={e => setValue({ ...value, hypothesis_id: e.target.value, stance: e.target.value ? value.stance : "neutral" })}><option value="">No link yet</option>{incident.entries.filter(e => e.kind === "hypothesis").map(h => <option key={h.id} value={h.id}>{h.title}</option>)}</select></label><label>Evidence relationship<select disabled={!value.hypothesis_id} value={value.stance} onChange={e => setValue({ ...value, stance: e.target.value as IncidentEntry["stance"] })}>{Object.entries(stances).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>}
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}<button className="ws-primary" disabled={busy}>Save investigation record</button>
  </form></dialog>;
}

// Both record editors and the linking dialog use native modal focus/escape behavior.
function useRefDialog() {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; if (dialog.current?.showModal) dialog.current.showModal(); else dialog.current?.setAttribute("open", ""); return () => previous?.focus(); }, []);
  return dialog;
}

function analysisHref(workspaceId: string, source: IncidentLink) {
  return `#/workspaces/${workspaceId}/analysis/${source.details.analysisId}${source.kind === "interval" ? `/${source.details.intervalIndex}` : ""}`;
}
function simulationHref(workspaceId: string, source: IncidentLink) {
  const context = source.details.observationWindow;
  return `#/workspaces/${workspaceId}/simulations/${source.details.simulationId}${source.details.run ? `/${source.details.run.id}` : context ? `/window/${context.windowStart}/${context.asOf}/${context.hypothesis || ""}` : ""}`;
}
function sourceInterval(source: IncidentLink): import("../types").Interval | undefined {
  const episode = source.details.episode;
  return source.details.interval || (episode ? { start: episode.start, end: episode.end, samples: episode.samples, peakScore: episode.severity, peakTime: episode.detectedAt, signals: episode.signals } : undefined);
}
function PrognosticSourceLink({ workspaceId, source }: { workspaceId: string; source: IncidentLink }) {
  return source.details.sessionId ? <a className="ws-link" href={prognosticSessionHref(workspaceId, source.details.sessionId)}>Open saved forecast ↗</a> : null;
}
function SourceSummary({ source, datasets }: { source: IncidentLink; datasets: Dataset[] }) {
  const d = source.details, dataset = datasets.find(ds => ds.id === d.datasetId), interval = sourceInterval(source);
  const experiment = d.experiment;
  if (source.kind === "prognostic") return <>
    <p>{[d.assetName, dataset?.name].filter(Boolean).join(" · ")}
      {d.cutoff != null && <> · Forecast cutoff {timeLabel(dataset?.metadata.time || numericAxis, d.cutoff)}</>}
    </p>
    {d.status && <p>{forecastStatus(d.status)}</p>}
    {d.rulMedian != null && <p>Median time to failure threshold · {number(d.rulMedian)} s</p>}
  </>;
  if (d.safety) return <><p><strong>{d.safety.constraintName}</strong>{dataset && ` · ${dataset.name}`}</p><p>{safetyEvidenceSummary(d.safety)}</p></>;
  if (experiment) return <><p><a className="ws-link" href={`#/workspaces/${dataset?.workspace_id}/experiments/${experiment.experimentId}`}>Return to source experiment ↗</a>{" "}· run{" "}{experiment.runId}{" "}· task{" "}{experiment.taskId}</p><SourceSummary source={{ ...source, details: { ...d, experiment: undefined } }} datasets={datasets} /></>;
  return <>{d.modelName && <p>{d.modelName} v{d.modelVersion}{" "}· scenario{" "}{d.scenarioId || "legacy / direct configuration"}{d.scenarioVersion ? ` v${d.scenarioVersion}` : ""}</p>}<p>{dataset?.name}{d.algorithmLabel && ` · ${d.algorithmLabel}`}</p>{interval && <><p>{dataset ? `${timeLabel(dataset.metadata.time, interval.start)} → ${timeLabel(dataset.metadata.time, interval.end)}` : `${interval.start}–${interval.end} s`}</p><p>Peak time{" "}{dataset ? timeLabel(dataset.metadata.time, interval.peakTime) : `${interval.peakTime}s`}{" "}· Score{" "}{number(interval.peakScore)}</p><p className="ws-accent">{interval.signals.map(s => dataset ? namedSignal(dataset, s) : s).join(" · ")}</p></>}{d.run && <p>{d.run.kind === "intervention" ? "Intervention experiment" : "Tool investigation"}{" "}· Observed through{" "}{String(d.run.request.asOf)} s · {dateLabel(d.run.createdAt)}</p>}{d.observationWindow && <p>Observation window{" "}{number(d.observationWindow.windowStart)}–{number(d.observationWindow.asOf)}{" "}s · Working hypothesis{" "}{d.observationWindow.hypothesis}</p>}</>;
}

function SourcePreview({ source, workspaceId, datasets, selection, onSelection }: { source: IncidentLink; workspaceId: string; datasets: Dataset[]; selection: IncidentSelection | null; onSelection: (value: IncidentSelection) => void }) {
  if (source.kind === "prognostic") return <section className="ws-panel incident-preview" aria-label={"Prognostic forecast"}>
    <h2>{source.details.title}</h2><SourceSummary source={source} datasets={datasets} /><PrognosticSourceLink source={source} workspaceId={workspaceId} />
  </section>;
  return <MeasurementSourcePreview source={source} datasets={datasets} selection={selection} onSelection={onSelection} />;
}

function MeasurementSourcePreview({ source, datasets, selection, onSelection }: { source: IncidentLink; datasets: Dataset[]; selection: IncidentSelection | null; onSelection: (value: IncidentSelection) => void }) {
  const [result, setResult] = useState<AnalysisResult | null>(null), [error, setError] = useState("");
  const [health, setHealth] = useState<HealthResult | null>(null);
  useEffect(() => {
    setHealth(null);
    if (!source.details.diagnosticId) return;
    const controller = new AbortController();
    api<HealthResult>(`/sensor-health/${source.details.diagnosticId}`, undefined, "GET", controller.signal).then(r => { if (!controller.signal.aborted) setHealth(r); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [source.details.diagnosticId]);
  const dataset = datasets.find(d => d.id === source.details.datasetId);
  const [signals, setSignals] = useState((source.details.interval?.signals || source.details.signals || dataset?.metadata.columns.map(c => c.name) || []).slice(0, 3));
  useEffect(() => {
    if (!source.details.analysisId) return;
    const controller = new AbortController();
    api<AnalysisResult>(`/analyses/${source.details.analysisId}`, undefined, "GET", controller.signal).then(setResult).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [source.details.analysisId]);
  const clock = source.details.clock ?? (dataset ? datasetClock(dataset) : { axisId: `simulation:${source.details.simulationId}`, offset: 0 });
  const interval = selection?.analysisId === result?.id && selection?.intervalIndex != null ? result?.intervals[selection.intervalIndex] : sourceInterval(source);
  const savedWindow = source.details.run ? [Number(source.details.run.request.windowStart || 0), Number(source.details.run.request.asOf)] : source.details.observationWindow ? [source.details.observationWindow.windowStart, source.details.observationWindow.asOf] : undefined;
  const fallback = interval && source.details.analysisRange ? intervalWindow(interval, source.details.analysisRange) : source.details.analysisRange || savedWindow || (dataset && [dataset.metadata.time.start, dataset.metadata.time.end]);
  const range: [number, number] | undefined = selection?.axisId === clock.axisId ? [selection.start-clock.offset, selection.end-clock.offset] : fallback ? [fallback[0], fallback[1]] : undefined;
  const selectedTime = selection?.axisId === clock.axisId ? selection.at-clock.offset : undefined;
  useEffect(() => {
    if (selection?.analysisId === source.details.analysisId && interval) setSignals(interval.signals.slice(0, 3));
  }, [selection?.analysisId, selection?.intervalIndex, result?.id]);
  function choose(at: number) {
    if (range) onSelection({ ...selection, axisId: clock.axisId, start: Math.min(range[0], at)+clock.offset, end: Math.max(range[1], at)+clock.offset, at: at+clock.offset, linkId: source.id, analysisId: source.details.analysisId });
  }
  const indexes = result?.times.map((t, i) => ({ t, i })).filter(({ t }) => !range || (range[0] <= t && t <= range[1]));
  return <section className="ws-panel incident-preview" aria-label={"Linked source details"}><h2>{source.details.title}</h2><SourceSummary source={source} datasets={datasets} />
    {range && <SharedWindow range={range} at={selectedTime ?? interval?.peakTime ?? range[1]} axis={dataset?.metadata.time || numericAxis} apply={(start, end, at) => onSelection({ ...selection, axisId: clock.axisId, start: start+clock.offset, end: end+clock.offset, at: at+clock.offset, linkId: source.id, analysisId: source.details.analysisId })} />}
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {result && dataset && indexes && <Plot title={tr("{0} · linked time window", {0: result.algorithmLabel})} times={indexes.map(v => v.t)} values={indexes.map(v => result.states?.[v.i] === "abstain" ? null : result.scores[v.i])} axis={dataset.metadata.time} threshold={result.threshold} intervals={interval ? [interval] : result.intervals} color="#e9927d" selectedTime={selectedTime} onSelectTime={choose} />}
    {interval && <Contributions values={interval.contributions} signals={interval.signals} metric={source.details.contributionMetric} label={s => dataset ? namedSignal(dataset, s) : s} />}
    {dataset && <><fieldset><legend>Original signal curves</legend><div className="ws-signal-list">{dataset.metadata.columns.map(c => <label key={c.name}><input type="checkbox" checked={signals.includes(c.name)} onChange={e => setSignals(e.target.checked ? [...signals, c.name] : signals.filter(s => s !== c.name))} />{signalLabel(c)}</label>)}</div></fieldset><SignalPlots dataset={dataset} signals={signals} range={range} intervals={interval ? [interval] : result?.intervals} selectedTime={selectedTime} onSelectTime={choose} />{selectedTime !== undefined && signals.length > 0 && <SignalSnapshot dataset={dataset} signals={signals} at={selectedTime} choose={choose} />}</>}
    {health && <SensorHealthResult result={health} dataset={dataset} embedded initialEpisode={source.details.episodeIndex} />}
    {source.details.run && <Suspense fallback={<p>Opening experiment result…</p>}><SavedRunView run={source.details.run} /></Suspense>}
  </section>;
}

function SharedWindow({ range, at, axis, apply }: { range: [number, number]; at: number; axis: TimeAxis; apply: (start: number, end: number, at: number) => void }) {
  const [start, setStart] = useState(String(range[0])), [end, setEnd] = useState(String(range[1]));
  useEffect(() => { setStart(String(range[0])); setEnd(String(range[1])); }, [range[0], range[1]]);
  return <form className="incident-window-controls" onSubmit={e => { e.preventDefault(); const a = Number(start), b = Number(end); if (a <= b) apply(a, b, Math.min(b, Math.max(a, at))); }}>
    <h3>Shared observation window</h3><p className="ws-muted">{timeLabel(axis, range[0])} → {timeLabel(axis, range[1])}{" "}· Selected{" "}{timeLabel(axis, at)}. The timeline, analysis comparison and original curves share this window.</p>
    <div className="ws-form-grid"><label>Window start (source seconds)<input required type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label><label>Window end (source seconds)<input required type="number" step="any" min={start} value={end} onChange={e => setEnd(e.target.value)} /></label><button>Apply observation window</button></div>
    <label>Synchronized observation time<input type="range" min={range[0]} max={range[1]} step="any" value={Math.min(range[1], Math.max(range[0], at))} onChange={e => apply(range[0], range[1], Number(e.target.value))} /></label>
    <label>Observation time (source seconds)<input type="number" step="any" min={range[0]} max={range[1]} value={at} onChange={e => { if (e.target.value !== "" && Number(e.target.value) >= range[0] && Number(e.target.value) <= range[1]) apply(range[0], range[1], Number(e.target.value)); }} /></label>
  </form>;
}

function SignalSnapshot({ dataset, signals, at, choose }: { dataset: Dataset; signals: string[]; at: number; choose: (value: number) => void }) {
  type Sample = { time: number; previousTime: number | null; nextTime: number | null; values: Record<string, number | null>; previous: Record<string, number | null> };
  const [sample, setSample] = useState<Sample | null>(null), [error, setError] = useState("");
  const names = signals.join("\u0000");
  useEffect(() => {
    const controller = new AbortController(); setSample(null); setError("");
    const timer = setTimeout(() => {
      const query = new URLSearchParams({ at: String(at) }); signals.forEach(s => query.append("signal", s));
      api<Sample>(`/datasets/${dataset.id}/sample?${query}`, undefined, "GET", controller.signal).then(setSample).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    }, 100);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [dataset.id, names, at]);
  return <section aria-label={"Multivariable observations at the same time"}><h3>Multivariable observations · nearest original sample</h3>{error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{sample && <>
    <p>{timeLabel(dataset.metadata.time, sample.time)}{" "}· Uses full data, not chart sampling</p>
    <div className="ws-inline"><button disabled={sample.previousTime == null} onClick={() => sample.previousTime != null && choose(sample.previousTime)}>Previous sample</button><button disabled={sample.nextTime == null} onClick={() => sample.nextTime != null && choose(sample.nextTime)}>Next sample</button></div>
    <div className="ws-table-scroll"><table><thead><tr><th>Variable (original units)</th><th>Current measurement</th><th>Previous sample</th><th>Change</th></tr></thead><tbody>{signals.map(signal => {
      const value = sample.values[signal], previous = sample.previous[signal];
      return <tr key={signal}><td>{namedSignal(dataset, signal)}</td><td>{value == null ? "Missing" : number(value)}</td><td>{previous == null ? "Missing / no previous sample" : number(previous)}</td><td>{value == null || previous == null ? "—" : number(value-previous)}</td></tr>;
    })}</tbody></table></div>
  </>}</section>;
}

function SourcePicker({ incident, datasets, jobs, busy, attach }: { incident: Incident; datasets: Dataset[]; jobs: Job[]; busy: boolean; attach: (source: IncidentSource) => Promise<boolean> }) {
  const [datasetId, setDatasetId] = useState(datasets[0]?.id || ""), [analysisId, setAnalysisId] = useState(jobs[0]?.id || "");
  const [simulations, setSimulations] = useState<{ id: string; title: string }[]>([]), [simulationId, setSimulationId] = useState("");
  const [runs, setRuns] = useState<RuntimeRun[]>([]), [runId, setRunId] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<{ simulations: { id: string; title: string }[] }>(`/simulations?workspaceId=${incident.workspace_id}`, undefined, "GET", controller.signal).then(data => { setSimulations(data.simulations); setSimulationId(data.simulations[0]?.id || ""); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [incident.workspace_id]);
  useEffect(() => {
    setRuns([]); setRunId(""); if (!simulationId) return;
    const controller = new AbortController();
    api<{ runs: RuntimeRun[] }>(`/simulations/${simulationId}/runs`, undefined, "GET", controller.signal).then(data => { setRuns(data.runs); setRunId(data.runs[0]?.id || ""); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [simulationId]);
  return <div className="ws-panel incident-form" aria-label={"Link existing record"}>
    <div className="ws-form-grid"><label>Existing dataset<select value={datasetId} onChange={e => setDatasetId(e.target.value)}><option value="">Please select a dataset</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><button disabled={busy || !datasetId} onClick={() => void attach({ kind: "dataset", datasetId })}>Link dataset</button></div>
    <div className="ws-form-grid"><label>Existing analysis<select value={analysisId} onChange={e => setAnalysisId(e.target.value)}><option value="">Please select an analysis</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select></label><div className="ws-inline"><button disabled={busy || !analysisId} onClick={() => void attach({ kind: "analysis", analysisId })}>Link analysis result</button>{analysisId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/analysis/${analysisId}`}>Open analysis and select an anomaly interval ↗</a>}</div></div>
    <div className="ws-form-grid"><label>Existing simulation session<select value={simulationId} onChange={e => setSimulationId(e.target.value)}><option value="">Please select a simulation session</option>{simulations.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label><button disabled={busy || !simulationId} onClick={() => void attach({ kind: "simulation", simulationId })}>Link simulation session</button></div>
    <div className="ws-form-grid"><label>Completed investigation / intervention<select value={runId} onChange={e => setRunId(e.target.value)}><option value="">Please select a completed record</option>{runs.map(r => <option key={r.id} value={r.id}>{runKinds[r.kind] || "Investigation record"} · {String(r.request.asOf)}s · {dateLabel(r.createdAt)}</option>)}</select></label><button disabled={busy || !runId} onClick={() => { const hypothesis = runs.find(r => r.id === runId)?.request.hypothesis; void attach({ kind: "run", simulationId, runId, ...(typeof hypothesis === "string" ? { hypothesis } : {}) }); }}>Link experiment and working hypothesis</button></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
  </div>;
}
