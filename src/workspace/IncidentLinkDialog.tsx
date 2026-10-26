import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, go, message } from "./api";
import { type Incident, type IncidentSource, type IncidentStatus, type IncidentSummary } from "./types";

export const incidentStatuses: Record<IncidentStatus, string> = { get open() { return tr("待调查"); }, get investigating() { return tr("调查中"); }, get resolved() { return tr("已形成结论"); }, get archived() { return tr("已归档"); } };
export type IncidentDraft = { title: string; start?: number | null; end?: number | null; origin?: string | null; description?: string };

export function IncidentLinkDialog({ workspaceId, source, draft, mode = "new", onClose }: {
  workspaceId: string; source?: IncidentSource; draft: IncidentDraft; mode?: "new" | "existing"; onClose: () => void;
}) {
  useLocale();
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
      const incident = action === "new"
        ? await api<Incident>(`/workspaces/${workspaceId}/incidents`, { title, description, start_time: start === "" ? null : Number(start), end_time: end === "" ? null : Number(end), time_origin: draft.origin || null, source })
        : await api<Incident>(`/incidents/${chosen}/links`, source);
      onClose(); go(`workspaces/${workspaceId}/incidents/${incident.id}`);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="incident-dialog" aria-labelledby="incident-dialog-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={save} className="incident-form">
      <div className="ws-inline ws-between"><h2 id="incident-dialog-title">{action === "new" ? tr("创建事件") : tr("添加到已有事件")}</h2><button type="button" onClick={onClose} disabled={busy} aria-label={tr("关闭事件窗口")}>×</button></div>
      {source && <div className="ws-inline"><button type="button" aria-pressed={action === "new"} onClick={() => setAction("new")}>{tr("创建事件")}</button><button type="button" aria-pressed={action === "existing"} onClick={() => setAction("existing")}>{tr("添加到已有事件")}</button></div>}
      <p className="ws-notice">{draft.description || tr("事件由你确认和维护，可以持续关联数据、分析和调查记录。")}</p>
      {action === "new" ? <>
        <label>{tr("事件标题")}<input autoFocus required maxLength={160} value={title} onChange={e => setTitle(e.target.value)} /></label>
        <div className="ws-form-grid"><label>{tr("开始时间（秒）")}<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label><label>{tr("结束时间（秒）")}<input type="number" step="any" min={start === "" ? undefined : Number(start)} value={end} onChange={e => setEnd(e.target.value)} /></label></div>
        <p className="ws-muted">{draft.origin ? tr("时间相对于 {0}。", {0: draft.origin}) : tr("时间使用来源数据的秒数；可以留空，稍后补充。")}</p>
        <label>{tr("事件说明")}<textarea rows={4} value={description} maxLength={50000} onChange={e => setDescription(e.target.value)} /></label>
      </> : <><label>{tr("选择事件")}<select value={chosen} onChange={e => setChosen(e.target.value)} disabled={loading} required><option value="">{loading ? tr("正在读取事件…") : tr("请选择事件")}</option>{events.map(i => <option key={i.id} value={i.id}>{i.title} · {incidentStatuses[i.status]}</option>)}</select></label>{!loading && !events.length && <p>{tr("此项目还没有事件，可以切换到「创建事件」。")}</p>}<p className="ws-muted">{tr("加入后可在事件详情中调整时间范围，多个检测区间和算法结果可以归入同一事件。")}</p></>}
      {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      <button className="ws-primary" disabled={busy || (action === "existing" && (!chosen || !source))}>{busy ? tr("正在保存…") : action === "new" ? tr("创建并打开事件") : tr("添加并打开事件")}</button>
    </form>
  </dialog>;
}
