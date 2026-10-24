import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { api, message } from "./api";
import { Plot, SignalPlots } from "./Charts";
import { intervalWindow } from "./findings";
import { IncidentLinkDialog, incidentStatuses } from "./IncidentLinkDialog";
import { Contributions } from "./Results";
import { dateLabel, number, timeLabel, type AnalysisResult, type Dataset, type Incident, type IncidentEntry, type IncidentLink, type IncidentSource, type IncidentSummary, type Job, type RuntimeRun, type TimeAxis } from "./types";

const SavedRunView = lazy(() => import("./RuntimeWorkbench").then(m => ({ default: m.SavedRunView })));
const entryKinds = { note: "调查笔记", evidence: "证据", hypothesis: "候选解释" };
const stances = { neutral: "待判断", support: "支持", oppose: "反对" };
const linkKinds = { dataset: "数据集", analysis: "分析结果", interval: "异常区间", simulation: "模拟会话", run: "调查工具 / 干预实验" };
const runKinds: Record<string, string> = { tools: "工具调查", tool: "工具调查", assistant: "助手调查", intervention: "干预实验" };
const numericAxis: TimeAxis = { kind: "numeric", column: null, origin: null, start: 0, end: 0 };
function eventTime(incident: IncidentSummary, value: number | null) {
  return value == null ? "未确定" : timeLabel({ ...numericAxis, origin: incident.time_origin }, value);
}
function entryTime(entry: IncidentEntry, incident: Incident, datasets: Dataset[]) {
  const link = incident.links.find(l => l.id === entry.source_link_id);
  const dataset = datasets.find(d => d.id === link?.details.datasetId);
  return entry.observed_at == null ? "" : dataset ? timeLabel(dataset.metadata.time, entry.observed_at) : eventTime(incident, entry.observed_at);
}

export function IncidentsPage({ workspaceId, incidentId, datasets, jobs }: { workspaceId: string; incidentId?: string; datasets: Dataset[]; jobs: Job[] }) {
  return incidentId ? <IncidentPage key={incidentId} workspaceId={workspaceId} incidentId={incidentId} datasets={datasets} jobs={jobs} /> : <IncidentList key={workspaceId} workspaceId={workspaceId} />;
}

function IncidentList({ workspaceId }: { workspaceId: string }) {
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
    <div className="ws-page-title"><div><div className="ws-kicker">05 / INCIDENT INVESTIGATION</div><h1>事件调查<span className="ws-accent">.</span></h1><p>把多个检测区间、分析结果和调查过程组织为一个持续维护的事件。</p></div><button className="ws-primary" onClick={() => setCreating(true)}>＋ 创建事件</button></div>
    <div className="ws-panel"><div className="ws-form-grid incident-filters">
      <label>查找事件<input placeholder="标题或事件说明" value={q} onChange={e => setQ(e.target.value)} /></label>
      <label>调查状态<select value={status} onChange={e => setStatus(e.target.value)}><option value="">全部状态</option>{Object.entries(incidentStatuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>相交区间起点（秒）<input type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label>
      <label>相交区间终点（秒）<input type="number" step="any" value={end} onChange={e => setEnd(e.target.value)} /></label>
      <label>排列方式<select value={sort} onChange={e => setSort(e.target.value)}><option value="updated">最近修改</option><option value="time">事件时间</option></select></label>
    </div><p className="ws-muted">时间查找使用每个事件的时间轴秒数，匹配与指定区间相交的事件。</p></div>
    {error && <p className="ws-error" role="alert">{error}</p>}
    {loading ? <p role="status">正在读取事件…</p> : !error && (sorted.length ? <div className="ws-history">{sorted.map(i => <a className="ws-history-row" key={i.id} href={`#/workspaces/${workspaceId}/incidents/${i.id}`}>
      <div><span className="ws-kicker">{incidentStatuses[i.status]} · 修改于 {dateLabel(i.updated_at)}</span><h2>{i.title}</h2><p>{eventTime(i, i.start_time)} → {eventTime(i, i.end_time)}</p><p>{i.description.slice(0, 120)}</p></div><div><strong className="ws-accent">{i.analysis_count} 个分析 · {i.interval_count} 个区间</strong><span>继续调查 ↗</span></div>
    </a>)}</div> : <div className="ws-empty"><h2>还没有符合条件的事件</h2><p>可以在这里创建，也可以从异常检测结果中的「创建事件」开始调查。</p></div>)}
    {creating && <IncidentLinkDialog workspaceId={workspaceId} draft={{ title: "新事件" }} onClose={() => setCreating(false)} />}
  </div>;
}

function IncidentPage({ workspaceId, incidentId, datasets, jobs }: { workspaceId: string; incidentId: string; datasets: Dataset[]; jobs: Job[] }) {
  const [incident, setIncident] = useState<Incident | null>(null), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<Incident>(`/incidents/${incidentId}`, undefined, "GET", controller.signal).then(data => {
      if (data.workspace_id !== workspaceId) throw new Error("此事件属于另一个 Workspace。");
      setIncident(data);
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [incidentId, workspaceId]);
  return error ? <p className="ws-error" role="alert">{error}</p> : incident ? <IncidentDetail initial={incident} datasets={datasets} jobs={jobs} /> : <p role="status">正在恢复事件和调查记录…</p>;
}

export function IncidentDetail({ initial, datasets, jobs }: { initial: Incident; datasets: Dataset[]; jobs: Job[] }) {
  const [incident, setIncident] = useState(initial), [draft, setDraft] = useState(initial), [conclusion, setConclusion] = useState(initial.conclusion);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(initial.links.find(l => l.kind === "interval")?.id || initial.links.find(l => l.details.datasetId)?.id || "");
  const [editing, setEditing] = useState<IncidentEntry | "new" | null>(null), [newKind, setNewKind] = useState<IncidentEntry["kind"]>("note");
  const [adding, setAdding] = useState(false);
  const preview = useRef<HTMLDivElement>(null);
  const base = `/incidents/${incident.id}`;
  function inspect(sourceId: string) {
    setFocused(sourceId);
    preview.current?.scrollIntoView({ behavior: "instant", block: "start" });
  }
  async function mutate(path: string, body?: unknown, method?: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await api<Incident>(`${base}${path}`, body, method);
      setIncident(updated); setNotice("已保存到 Workspace，可以在下次打开时继续调查。");
      return true;
    } catch (e) { setError(message(e)); return false; } finally { setBusy(false); }
  }
  function basic(e: FormEvent) {
    e.preventDefault();
    void mutate("", { title: draft.title, description: draft.description, start_time: draft.start_time, end_time: draft.end_time, time_origin: draft.time_origin, status: draft.status }, "PATCH");
  }
  const hypotheses = incident.entries.filter(e => e.kind === "hypothesis"), records = incident.entries.filter(e => e.kind !== "hypothesis");
  const link = incident.links.find(l => l.id === focused);
  function begin(kind: IncidentEntry["kind"]) { setNewKind(kind); setEditing("new"); }
  return <div className="incident-workstation">
    <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/incidents`}>← 返回事件列表</a>
    <div className="ws-page-title"><div><div className="ws-kicker">INCIDENT / {incident.id.slice(0, 8)}</div><h1>{incident.title}</h1><p>{incidentStatuses[incident.status]} · 创建于 {dateLabel(incident.created_at)} · 修改于 {dateLabel(incident.updated_at)}</p></div><span className="ws-badge">{new Set(incident.links.filter(l => l.details.analysisId).map(l => l.details.analysisId)).size} 个关联分析</span></div>
    <nav className="incident-nav" aria-label="事件调查分区"><a href="#incident-information" onClick={e => { e.preventDefault(); document.getElementById("incident-information")?.scrollIntoView(); }}>基本信息</a><a href="#incident-sources" onClick={e => { e.preventDefault(); document.getElementById("incident-sources")?.scrollIntoView(); }}>数据与分析</a><a href="#incident-investigation" onClick={e => { e.preventDefault(); document.getElementById("incident-investigation")?.scrollIntoView(); }}>证据与解释</a><a href="#incident-conclusion" onClick={e => { e.preventDefault(); document.getElementById("incident-conclusion")?.scrollIntoView(); }}>调查结论</a></nav>
    {error && <p className="ws-error" role="alert">{error}</p>}{notice && <p className="ws-saved" role="status">{notice}</p>}
    <form className="ws-panel incident-form" id="incident-information" onSubmit={basic}>
      <div className="ws-section-heading"><h2>事件基本信息</h2><span className="ws-muted">{eventTime(incident, incident.start_time)} → {eventTime(incident, incident.end_time)}</span></div>
      <div className="ws-form-grid"><label>事件标题<input required maxLength={160} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label><label>调查状态<select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value as Incident["status"] })}>{Object.entries(incidentStatuses).map(([k, v]) => <option value={k} key={k}>{v}</option>)}</select></label></div>
      <div className="ws-form-grid"><label>开始时间（秒）<input type="number" step="any" value={draft.start_time ?? ""} onChange={e => setDraft({ ...draft, start_time: e.target.value === "" ? null : Number(e.target.value) })} /></label><label>结束时间（秒）<input type="number" step="any" min={draft.start_time ?? undefined} value={draft.end_time ?? ""} onChange={e => setDraft({ ...draft, end_time: e.target.value === "" ? null : Number(e.target.value) })} /></label></div>
      <label>时间轴起点（带时区的日期时间，可留空）<input placeholder="例如 2026-10-24T08:00:00Z" value={draft.time_origin || ""} onChange={e => setDraft({ ...draft, time_origin: e.target.value || null })} /></label>
      <label>事件说明<textarea rows={3} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} maxLength={50000} /></label>
      <p className="ws-muted">事件范围由你维护。每份来源数据的曲线和异常区间保留自身时间轴，关联不同数据集不会自动平移时间。</p>
      <div className="ws-inline"><button className="ws-primary" disabled={busy}>保存基本信息</button>{incident.status !== "archived" && <button type="button" disabled={busy} onClick={async () => { if (await mutate("", { status: "archived" }, "PATCH")) setDraft(d => ({ ...d, status: "archived" })); }}>归档事件</button>}</div>
    </form>

    <section id="incident-sources"><div className="ws-section-heading"><h2>相关数据、分析与模拟实验</h2><button className="ws-outlined" onClick={() => setAdding(!adding)}>{adding ? "收起关联选择" : "＋ 关联已有记录"}</button></div>
      {adding && <SourcePicker incident={incident} datasets={datasets} jobs={jobs} busy={busy} attach={source => mutate("/links", source)} />}
      {!incident.links.length && <p className="ws-notice">可以关联已有数据集或分析，也可以先写下人工观察。普通 CSV 的事件可以直接开始调查。</p>}
      <div className="incident-source-grid">{incident.links.map(source => <article className={`ws-panel incident-source ${source.id === focused ? "incident-selected" : ""}`} key={source.id}>
        <div className="ws-inline ws-between"><span className="ws-kicker">{linkKinds[source.kind]}</span><button className="ws-danger" disabled={busy} onClick={() => void mutate(`/links/${source.id}`, undefined, "DELETE")} aria-label={`解除关联 ${source.details.title}`}>解除关联</button></div>
        <h3>{source.details.title}</h3><SourceSummary source={source} datasets={datasets} />
        <div className="ws-inline incident-actions">{source.details.datasetId && datasets.some(d => d.id === source.details.datasetId) && <button onClick={() => inspect(source.id)} aria-pressed={focused === source.id}>查看原始曲线</button>}
          {source.details.analysisId && <a className="ws-link" href={analysisHref(incident.workspace_id, source)}>打开原始分析 ↗</a>}
          {source.details.simulationId && <a className="ws-link" href={simulationHref(incident.workspace_id, source)}>返回模拟会话 ↗</a>}
          {source.kind === "run" && <button onClick={() => inspect(source.id)} aria-pressed={focused === source.id}>查看已保存结果</button>}
          <button onClick={() => { setFocused(source.id); begin("evidence"); }}>记录来源证据</button>
        </div>
      </article>)}</div>
      <div ref={preview} className="incident-preview-anchor">{link && <SourcePreview key={link.id} source={link} datasets={datasets} />}</div>
    </section>

    <section className="ws-panel" aria-label="关键时间点"><h2>关键时间点</h2><p className="ws-muted">检测峰值与人工观察按各自来源的时间轴显示。</p><ol className="incident-timeline">
      {incident.links.filter(l => l.details.interval).map(l => { const d = datasets.find(d => d.id === l.details.datasetId); return <li key={l.id}><button onClick={() => inspect(l.id)}>{d ? timeLabel(d.metadata.time, l.details.interval!.peakTime) : `${l.details.interval!.peakTime} s`} · 检测峰值</button><span>{d?.name} · {l.details.algorithmLabel}</span></li>; })}
      {incident.links.filter(l => l.details.run).map(l => {
        const run = l.details.run!, result = run.result as { observedThrough?: number; asOf?: number; at?: number };
        const through = result.observedThrough ?? result.asOf ?? Number(run.request.asOf);
        return <li key={l.id}><button onClick={() => inspect(l.id)}>{number(through)} s · 观察截止{result.at !== undefined && ` / ${number(result.at)} s · 干预开始`}</button><span>{l.details.title} · {runKinds[run.kind] || "调查记录"}</span></li>;
      })}
      {incident.entries.filter(e => e.observed_at != null).map(e => <li key={e.id}><strong>{entryTime(e, incident, datasets)}</strong><span>{e.title}</span></li>)}
      {!incident.links.some(l => l.details.interval || l.details.run) && !incident.entries.some(e => e.observed_at != null) && <li>关联异常区间、模拟实验或在调查记录中填写观察时间后，关键时间点会显示在这里。</li>}
    </ol></section>

    <section id="incident-investigation"><div className="ws-section-heading"><h2>候选解释与证据关系</h2><button className="ws-outlined" onClick={() => begin("hypothesis")}>＋ 添加候选解释</button></div>
      <div className="incident-hypotheses">{hypotheses.map(h => <article className="ws-panel" key={h.id}>
        <EntryHeading entry={h} busy={busy} edit={() => setEditing(h)} remove={() => mutate(`/entries/${h.id}`, undefined, "DELETE")} />
        <p className="incident-prose">{h.content}</p><EntrySource entry={h} incident={incident} />
        <div className="incident-evidence-columns">{(["support", "oppose", "neutral"] as const).map(stance => <div key={stance}><h3>{stances[stance]}证据</h3>{records.filter(e => e.hypothesis_id === h.id && e.stance === stance).map(e => <button className="incident-evidence-ref" key={e.id} onClick={() => setEditing(e)}><strong>{e.title}</strong><span>{e.content}</span></button>)}</div>)}</div>
      </article>)}</div>
      {!hypotheses.length && <p className="ws-notice">写下待验证的解释，再把观察或工具结果记为支持、反对或待判断的证据。</p>}
      <div className="ws-section-heading"><h2>调查证据与笔记</h2><div className="ws-inline"><button className="ws-outlined" onClick={() => begin("evidence")}>＋ 添加证据</button><button className="ws-outlined" onClick={() => begin("note")}>＋ 添加笔记</button></div></div>
      {records.map(e => <article className="ws-panel" key={e.id}>
        <EntryHeading entry={e} busy={busy} edit={() => setEditing(e)} remove={() => mutate(`/entries/${e.id}`, undefined, "DELETE")} />
        <p className="incident-prose">{e.content}</p>{e.hypothesis_id && <p className={e.stance === "oppose" ? "ws-coral" : "ws-accent"}>{stances[e.stance]}：{hypotheses.find(h => h.id === e.hypothesis_id)?.title}</p>}
        {e.observed_at != null && <p className="ws-muted">观察时间：{entryTime(e, incident, datasets)}</p>}<EntrySource entry={e} incident={incident} />
      </article>)}
      {!records.length && <p className="ws-notice">记录现场观察、分析解释或下一步调查计划。保存后可以继续编辑。</p>}
      {editing && <EntryEditor key={editing === "new" ? `new-${newKind}-${focused}` : editing.id} entry={editing === "new" ? undefined : editing} kind={newKind} incident={incident} sourceId={focused} busy={busy} error={error} onClose={() => setEditing(null)} save={async value => { if (await mutate(editing === "new" ? "/entries" : `/entries/${editing.id}`, value, editing === "new" ? "POST" : "PATCH")) setEditing(null); }} />}
    </section>

    <form className="ws-panel incident-form" id="incident-conclusion" onSubmit={e => { e.preventDefault(); void mutate("", { conclusion }, "PATCH"); }}><h2>当前调查结论</h2><p className="ws-muted">保留已经确认的解释、仍存在的不确定性，以及后续处理安排。</p><label>调查结论<textarea rows={6} maxLength={50000} value={conclusion} onChange={e => setConclusion(e.target.value)} /></label><button className="ws-primary" disabled={busy}>保存调查结论</button></form>
  </div>;
}

function EntryHeading({ entry, busy, edit, remove }: { entry: IncidentEntry; busy: boolean; edit: () => void; remove: () => Promise<boolean> }) {
  const [confirming, setConfirming] = useState(false);
  return <div className="ws-section-heading"><div><span className="ws-kicker">{entryKinds[entry.kind]} · {dateLabel(entry.updated_at)}</span><h3>{entry.title}</h3></div><div className="ws-inline"><button onClick={edit} disabled={busy}>编辑</button>{confirming ? <><button className="ws-danger" disabled={busy} onClick={() => void remove()}>确认移除</button><button onClick={() => setConfirming(false)}>取消</button></> : <button className="ws-danger" disabled={busy} onClick={() => setConfirming(true)}>移除</button>}</div></div>;
}

function EntrySource({ entry, incident }: { entry: IncidentEntry; incident: Incident }) {
  const source = incident.links.find(l => l.id === entry.source_link_id);
  return source ? <p className="ws-muted">来源：{source.details.title} · {linkKinds[source.kind]} {source.details.analysisId && <a className="ws-link" href={analysisHref(incident.workspace_id, source)}>打开分析 ↗</a>}{source.details.simulationId && <a className="ws-link" href={simulationHref(incident.workspace_id, source)}>打开模拟 ↗</a>}</p> : null;
}

function EntryEditor({ entry, kind, incident, sourceId, busy, error, onClose, save }: { entry?: IncidentEntry; kind: IncidentEntry["kind"]; incident: Incident; sourceId: string; busy: boolean; error: string; onClose: () => void; save: (value: Partial<IncidentEntry>) => Promise<void> }) {
  const [value, setValue] = useState({ kind: entry?.kind || kind, title: entry?.title || "", content: entry?.content || "", hypothesis_id: entry?.hypothesis_id || "", stance: entry?.stance || "neutral", source_link_id: entry ? entry.source_link_id || "" : kind === "evidence" ? sourceId : "", observed_at: entry?.observed_at == null ? "" : String(entry.observed_at) });
  const dialog = useRefDialog();
  return <dialog ref={dialog} className="incident-dialog" aria-labelledby="entry-editor-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}><form className="incident-form" onSubmit={e => { e.preventDefault(); void save({ ...value, hypothesis_id: value.hypothesis_id || null, source_link_id: value.source_link_id || null, observed_at: value.observed_at === "" ? null : Number(value.observed_at) }); }}>
    <div className="ws-inline ws-between"><h2 id="entry-editor-title">{entry ? "编辑" : "添加"}{entryKinds[value.kind]}</h2><button type="button" onClick={onClose} disabled={busy} aria-label="关闭调查记录窗口">×</button></div>
    <label>记录标题<input autoFocus required maxLength={160} value={value.title} onChange={e => setValue({ ...value, title: e.target.value })} /></label><label>记录内容<textarea rows={6} maxLength={50000} value={value.content} onChange={e => setValue({ ...value, content: e.target.value })} /></label>
    <label>观察时间（秒，可留空）<input type="number" step="any" value={value.observed_at} onChange={e => setValue({ ...value, observed_at: e.target.value })} /></label>
    <label>证据来源<select value={value.source_link_id} onChange={e => setValue({ ...value, source_link_id: e.target.value })}><option value="">人工记录 / 事件时间轴</option>{incident.links.map(l => <option key={l.id} value={l.id}>{linkKinds[l.kind]} · {l.details.title}{l.details.interval ? ` · ${number(l.details.interval.start)}–${number(l.details.interval.end)}s` : ""}</option>)}</select></label><p className="ws-muted">观察时间采用所选来源数据的时间轴；未选择来源时采用事件时间轴。</p>
    {value.kind === "evidence" && <div className="ws-form-grid"><label>关联候选解释<select value={value.hypothesis_id} onChange={e => setValue({ ...value, hypothesis_id: e.target.value, stance: e.target.value ? value.stance : "neutral" })}><option value="">暂不关联</option>{incident.entries.filter(e => e.kind === "hypothesis").map(h => <option key={h.id} value={h.id}>{h.title}</option>)}</select></label><label>证据关系<select disabled={!value.hypothesis_id} value={value.stance} onChange={e => setValue({ ...value, stance: e.target.value as IncidentEntry["stance"] })}>{Object.entries(stances).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>}
    {error && <p className="ws-error" role="alert">{error}</p>}<button className="ws-primary" disabled={busy}>保存调查记录</button>
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
function SourceSummary({ source, datasets }: { source: IncidentLink; datasets: Dataset[] }) {
  const d = source.details, dataset = datasets.find(ds => ds.id === d.datasetId), interval = d.interval;
  return <><p>{dataset?.name}{d.algorithmLabel && ` · ${d.algorithmLabel}`}</p>{interval && <><p>{dataset ? `${timeLabel(dataset.metadata.time, interval.start)} → ${timeLabel(dataset.metadata.time, interval.end)}` : `${interval.start}–${interval.end} s`}</p><p>峰值时间 {dataset ? timeLabel(dataset.metadata.time, interval.peakTime) : `${interval.peakTime}s`} · 分数 {number(interval.peakScore)}</p><p className="ws-accent">{interval.signals.join(" · ")}</p></>}{d.run && <p>{d.run.kind === "intervention" ? "干预实验" : "工具调查"} · 观察至 {String(d.run.request.asOf)} s · {dateLabel(d.run.createdAt)}</p>}{d.observationWindow && <p>观察窗口 {number(d.observationWindow.windowStart)}–{number(d.observationWindow.asOf)} s · 工作假设 {d.observationWindow.hypothesis}</p>}</>;
}

function SourcePreview({ source, datasets }: { source: IncidentLink; datasets: Dataset[] }) {
  const [result, setResult] = useState<AnalysisResult | null>(null), [error, setError] = useState("");
  const dataset = datasets.find(d => d.id === source.details.datasetId);
  const [signals, setSignals] = useState((source.details.interval?.signals || source.details.signals || dataset?.metadata.columns.map(c => c.name) || []).slice(0, 3));
  useEffect(() => {
    if (!source.details.analysisId) return;
    const controller = new AbortController();
    api<AnalysisResult>(`/analyses/${source.details.analysisId}`, undefined, "GET", controller.signal).then(setResult).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => controller.abort();
  }, [source.details.analysisId]);
  const interval = source.details.interval, range = interval && source.details.analysisRange ? intervalWindow(interval, source.details.analysisRange) : source.details.analysisRange;
  const indexes = result?.times.map((t, i) => ({ t, i })).filter(({ t }) => !range || (range[0] <= t && t <= range[1]));
  return <section className="ws-panel incident-preview" aria-label="关联来源详情"><h2>{source.details.title}</h2><SourceSummary source={source} datasets={datasets} />
    {error && <p className="ws-error" role="alert">{error}</p>}
    {result && dataset && indexes && <Plot title={`${result.algorithmLabel} · 关联时间窗口`} times={indexes.map(v => v.t)} values={indexes.map(v => result.states?.[v.i] === "abstain" ? null : result.scores[v.i])} axis={dataset.metadata.time} threshold={result.threshold} intervals={interval ? [interval] : result.intervals} color="#e9927d" />}
    {interval && <Contributions values={interval.contributions} signals={interval.signals} metric={source.details.contributionMetric} locale="zh" />}
    {dataset && <><fieldset><legend>原始信号曲线</legend><div className="ws-signal-list">{dataset.metadata.columns.map(c => <label key={c.name}><input type="checkbox" checked={signals.includes(c.name)} onChange={e => setSignals(e.target.checked ? [...signals, c.name] : signals.filter(s => s !== c.name))} />{c.name}</label>)}</div></fieldset><SignalPlots dataset={dataset} signals={signals} range={range} intervals={interval ? [interval] : result?.intervals} /></>}
    {source.details.run && <Suspense fallback={<p>正在打开实验结果…</p>}><SavedRunView run={source.details.run} /></Suspense>}
  </section>;
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
  return <div className="ws-panel incident-form" aria-label="关联已有记录">
    <div className="ws-form-grid"><label>已有数据集<select value={datasetId} onChange={e => setDatasetId(e.target.value)}><option value="">请选择数据集</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><button disabled={busy || !datasetId} onClick={() => void attach({ kind: "dataset", datasetId })}>关联数据集</button></div>
    <div className="ws-form-grid"><label>已有分析<select value={analysisId} onChange={e => setAnalysisId(e.target.value)}><option value="">请选择分析</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.name}</option>)}</select></label><div className="ws-inline"><button disabled={busy || !analysisId} onClick={() => void attach({ kind: "analysis", analysisId })}>关联分析结果</button>{analysisId && <a className="ws-link" href={`#/workspaces/${incident.workspace_id}/analysis/${analysisId}`}>打开分析，选择异常区间 ↗</a>}</div></div>
    <div className="ws-form-grid"><label>已有模拟会话<select value={simulationId} onChange={e => setSimulationId(e.target.value)}><option value="">请选择模拟会话</option>{simulations.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label><button disabled={busy || !simulationId} onClick={() => void attach({ kind: "simulation", simulationId })}>关联模拟会话</button></div>
    <div className="ws-form-grid"><label>已完成的调查 / 干预实验<select value={runId} onChange={e => setRunId(e.target.value)}><option value="">请选择已完成记录</option>{runs.map(r => <option key={r.id} value={r.id}>{runKinds[r.kind] || "调查记录"} · {String(r.request.asOf)}s · {dateLabel(r.createdAt)}</option>)}</select></label><button disabled={busy || !runId} onClick={() => { const hypothesis = runs.find(r => r.id === runId)?.request.hypothesis; void attach({ kind: "run", simulationId, runId, ...(typeof hypothesis === "string" ? { hypothesis } : {}) }); }}>关联实验及工作假设</button></div>
    {error && <p className="ws-error" role="alert">{error}</p>}
  </div>;
}
