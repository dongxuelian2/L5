import { errorMessage, t as tr } from "../../lib/text";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, go, message } from "../api";
import { type Incident, type IncidentSource, type IncidentStatus, type IncidentSummary } from "../types";

export const incidentStatuses: Record<IncidentStatus, string> = { get open() { return "Open"; }, get investigating() { return "Investigating"; }, get resolved() { return "Conclusion recorded"; }, get archived() { return "Archived"; } };
export type IncidentDraft = { title: string; start?: number | null; end?: number | null; origin?: string | null; description?: string };

export function IncidentLinkDialog({ workspaceId, source, draft, mode = "new", saveLinked, onClose }: {
  workspaceId: string; source?: IncidentSource; draft: IncidentDraft; mode?: "new" | "existing"; onClose: () => void;
  saveLinked?: (target: { title: string } | { incidentId: string }) => Promise<void>;
}) {
  const [action, setAction] = useState(mode), [events, setEvents] = useState<IncidentSummary[]>([]), [chosen, setChosen] = useState("");
  const [title, setTitle] = useState(draft.title), [description, setDescription] = useState(draft.description || "");
  const [start, setStart] = useState(draft.start == null ? "" : String(draft.start)), [end, setEnd] = useState(draft.end == null ? "" : String(draft.end));
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    if (dialog.current?.showModal) dialog.current.showModal();
    else dialog.current?.setAttribute("open", "");
    return () => previous?.focus();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api<{ incidents: IncidentSummary[] }>(`/workspaces/${workspaceId}/incidents`, undefined, "GET", controller.signal)
      .then(data => { setEvents(data.incidents); setChosen(data.incidents.find(i => i.status !== "archived")?.id || data.incidents[0]?.id || ""); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId]);
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      if (saveLinked) {
        await saveLinked(action === "new" ? { title } : { incidentId: chosen });
        onClose();
        return;
      }
      const incident = action === "new"
        ? await api<Incident>(`/workspaces/${workspaceId}/incidents`, { title, description, start_time: start === "" ? null : Number(start), end_time: end === "" ? null : Number(end), time_origin: draft.origin || null, source })
        : await api<Incident>(`/incidents/${chosen}/links`, source);
      onClose(); go(`workspaces/${workspaceId}/incidents/${incident.id}`);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="incident-dialog" aria-labelledby="incident-dialog-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={save} className="incident-form">
      <div className="ws-inline ws-between"><h2 id="incident-dialog-title">{action === "new" ? "Create incident" : "Add to existing incident"}</h2><button type="button" onClick={onClose} disabled={busy} aria-label={"Close incident dialog"}>×</button></div>
      {(source || saveLinked) && <div className="ws-inline"><button type="button" aria-pressed={action === "new"} onClick={() => setAction("new")}>Create incident</button><button type="button" aria-pressed={action === "existing"} onClick={() => setAction("existing")}>Add to existing incident</button></div>}
      <p className="ws-notice">{draft.description || "You confirm and maintain incidents, linking data, analyses and investigation records over time."}</p>
      {action === "new" ? <>
        <label>Incident title<input autoFocus required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label>
        {!saveLinked && <><div className="ws-form-grid"><label>Start time (seconds)<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label><label>End time (seconds)<input type="number" step="any" min={start === "" ? undefined : Number(start)} value={end} onChange={e => setEnd(e.target.value)} /></label></div>
        <p className="ws-muted">{draft.origin ? tr("Time is relative to {0}.", {0: draft.origin}) : "Time uses the source data’s seconds. Leave blank to add it later."}</p>
        <label>Incident description<textarea rows={4} value={description} maxLength={50000} onChange={e => setDescription(e.target.value)} /></label></>}
      </> : <><label>Select incident<select value={chosen} onChange={e => setChosen(e.target.value)} disabled={loading} required><option value="">{loading ? "Loading incidents…" : "Please select an incident"}</option>{events.map(i => <option key={i.id} value={i.id}>{i.title} · {incidentStatuses[i.status]}</option>)}</select></label>{!loading && !events.length && <p>This project has no incidents yet. Switch to “Create incident”.</p>}<p className="ws-muted">Adjust the time range in incident details after linking. Multiple detection intervals and algorithm results can belong to one incident.</p></>}
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      <button className="ws-primary" disabled={busy || (action === "existing" && (!chosen || (!source && !saveLinked)))}>{busy ? "Saving…" : saveLinked ? tr(action === "new" ? "Create incident" : "Link incident") : action === "new" ? "Create and open incident" : "Add and open incident"}</button>
    </form>
  </dialog>;
}
