import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, go, message } from "./api";
import { Plot } from "./Charts";
import { IncidentLinkDialog } from "./IncidentLinkDialog";
import { datasetClock, number, signalLabel, timeLabel, type CatalogSignal, type Dataset, type ExplorerAxis, type ExplorerData, type ExplorerSample, type ExplorerSeries, type ExplorerView, type ExplorerWindow, type Job, type TimeAxis, type TimeReference } from "./types";
import "./signals.css";

type Mode = "signals" | "quality" | "explorer";
type Props = { workspaceId: string; datasets: Dataset[]; jobs: Job[]; mode: Mode; initialSignalIds?: string; onChanged: () => void; onAnalyze: (datasetId: string, signals: string[], range: [number, number]) => void };
const colors = ["#b5ed9a", "#e2bc75", "#9ccbdc", "#cfb2ed", "#eea496"];
const categories = ["Temperature", "Pressure", "Flow", "Current", "Voltage", "Vibration", "Speed", "Power", "State"];
function errorText(error: string) { return error && <p className="ws-error" role="alert">{errorMessage(error)}</p>; }
function axisTime(axis: ExplorerAxis): TimeAxis { return { kind: axis.origin ? "datetime" : "numeric", origin: axis.origin, column: null, start: axis.start, end: axis.end }; }
function qualityNumber(n: number | null | undefined) { return n == null ? "—" : number(n); }

export function SignalWorkspace({ workspaceId, datasets, jobs, mode, initialSignalIds, onChanged, onAnalyze }: Props) {
  useLocale();
  const [catalog, setCatalog] = useState<CatalogSignal[]>([]), [views, setViews] = useState<ExplorerView[]>([]);
  const [selected, setSelected] = useState<string[]>(initialSignalIds?.split(",").filter(Boolean) || []);
  const [windows, setWindows] = useState<Record<string, ExplorerWindow>>({}), [displayMode, setDisplayMode] = useState<"separate" | "overlay">("separate");
  const [viewId, setViewId] = useState(""), [name, setName] = useState(tr("Signal review")), [saved, setSaved] = useState("");
  const [error, setError] = useState(""), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<CatalogSignal | null>(null), [qualityId, setQualityId] = useState(datasets[0]?.id || "");
  const [data, setData] = useState<ExplorerData>({ axes: [], series: [] }), [plotting, setPlotting] = useState(false);
  const restored = useRef(false);
  const [filters, setFilters] = useState({ search: "", dataset: "", device: "", category: "", tag: "" });
  const prefix = `/workspaces/${workspaceId}`;
  function restore(view: ExplorerView) { setSelected(view.signalIds); setWindows(view.windows); setDisplayMode(view.displayMode); setName(view.name); setViewId(view.id); setSaved(tr("Opened saved view: {0}", {0: view.name})); }
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    Promise.all([api<{ signals: CatalogSignal[] }>(`${prefix}/signals`, undefined, "GET", controller.signal), api<{ views: ExplorerView[] }>(`${prefix}/views`, undefined, "GET", controller.signal)])
      .then(([c, v]) => {
        if (controller.signal.aborted) return;
        setCatalog(c.signals); setViews(v.views);
        if (!restored.current) { restored.current = true; if (!initialSignalIds && v.views[0]) restore(v.views[0]); }
      }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId, datasets, revision]);
  useEffect(() => { if (initialSignalIds) { setSelected(initialSignalIds.split(",").filter(Boolean)); setWindows({}); setViewId(""); setSaved(""); } }, [initialSignalIds]);
  const rangeKey = JSON.stringify(Object.fromEntries(Object.entries(windows).map(([id, w]) => [id, { start: w.start, end: w.end }])));
  const signalKey = JSON.stringify(selected);
  useEffect(() => {
    if (mode !== "explorer" || loading) return;
    const controller = new AbortController(); setPlotting(true); setError("");
    api<ExplorerData>(`${prefix}/explore`, { signalIds: JSON.parse(signalKey), windows: JSON.parse(rangeKey) }, "POST", controller.signal)
      .then(d => { if (!controller.signal.aborted) setData(d); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setPlotting(false); });
    return () => controller.abort();
  }, [mode, signalKey, rangeKey, loading, catalog]);
  function changed() { setRevision(v => v + 1); onChanged(); setSaved(""); }
  function toggle(id: string) { setSelected(previous => previous.includes(id) ? previous.filter(s => s !== id) : [...previous, id]); setSaved(""); }
  function open(signals: string[], dataset?: Dataset, start?: number, end?: number) {
    setSelected(signals); setViewId(""); setSaved("");
    if (dataset && start !== undefined && end !== undefined) {
      const clock = datasetClock(dataset), padding = Math.max((end-start) * .2, (dataset.metadata.time.typicalInterval || 1) * 2);
      setWindows({ [clock.axisId]: { start: start + clock.offset - padding, end: end + clock.offset + padding, at: start + clock.offset } });
    } else setWindows({});
    go(`workspaces/${workspaceId}/explorer`);
  }
  async function save(asNew = false) {
    setBusy(true); setError("");
    try {
      const activeWindows = Object.fromEntries(data.axes.map(a => [a.id, windows[a.id] || a.window]));
      const view = await api<ExplorerView>(`${prefix}/views${viewId && !asNew ? `/${viewId}` : ""}`, { name, signalIds: selected, windows: activeWindows, displayMode }, viewId && !asNew ? "PATCH" : "POST");
      setViewId(view.id); setViews(previous => [view, ...previous.filter(v => v.id !== view.id)]); setSaved(tr("Saved: {0}", {0: view.name}));
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const filtered = catalog.filter(s => (!filters.dataset || s.datasetId === filters.dataset) &&
    `${s.displayName} ${s.name} ${s.description} ${s.logicalKey}`.toLowerCase().includes(filters.search.toLowerCase()) &&
    (s.device || "").toLowerCase().includes(filters.device.toLowerCase()) && (s.category || "").toLowerCase().includes(filters.category.toLowerCase()) &&
    (s.tags || []).join(" ").toLowerCase().includes(filters.tag.toLowerCase()));
  const qualityDataset = datasets.find(d => d.id === qualityId) || datasets[0];
  const titles = { signals: [tr("Signal catalog"), tr("Give each measurement a name, unit and source you can follow.")], quality: [tr("Data quality"), tr("Inspect measured coverage, missing values and timestamp problems.")], explorer: [tr("Signal Explorer"), tr("Browse multiple sources with explicit clocks and original measurements.")] };
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("DATA FOUNDATION /")}{" "}{mode.toUpperCase()}</div><h1>{titles[mode][0]}<span className="ws-accent">.</span></h1><p>{titles[mode][1]}</p></div><span className="ws-badge">{catalog.length}{" "}{tr("SIGNALS /")}{" "}{datasets.length}{" "}{tr("SOURCES")}</span></div>
    {errorText(error)}{loading && <p role="status">{tr("Loading saved data settings…")}</p>}
    {selected.length > 0 && <p><a className="ws-primary" href={`#${prefix}/transformations/new/${selected.join(",")}`}>{tr("Transform selected signals (")}{selected.length}) ↗</a></p>}
    {!datasets.length && <p className="ws-notice">{tr("Start by")}{" "}<a className="ws-link" href={`#${prefix}/datasets`}>{tr("importing a CSV")}</a>{" "}{tr("or")}{" "}<a className="ws-link" href={`#${prefix}/simulations`}>{tr("saving a process simulation")}</a>.</p>}
    {mode === "signals" && <>
      <div className="ws-panel"><div className="ws-form-grid signal-filters">
        <label>{tr("Search signals")}<input value={filters.search} onChange={e => setFilters({ ...filters, search: e.target.value })} placeholder={tr("Name, column, description or measurement key")} /></label>
        <label>{tr("Source dataset")}<select value={filters.dataset} onChange={e => setFilters({ ...filters, dataset: e.target.value })}><option value="">{tr("All datasets")}</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        {(["device", "category", "tag"] as const).map(key => <label key={key}>{tr("Filter by")}{" "}{key}<input value={filters[key]} onChange={e => setFilters({ ...filters, [key]: e.target.value })} /></label>)}
      </div><div className="ws-inline ws-between"><span>{filtered.length}{" "}{tr("matching signals ·")}{" "}{selected.length}{" "}{tr("selected")}</span><button className="ws-primary" disabled={!selected.length} onClick={() => open(selected)}>{tr("Explore selected signals ↗")}</button></div></div>
      <div className="ws-table-scroll"><table className="signal-catalog"><thead><tr><th>{tr("Select / Signal")}</th><th>{tr("Source / clock")}</th><th>{tr("Semantics")}</th><th>{tr("Quality / coverage")}</th><th>{tr("Actions")}</th></tr></thead><tbody>{filtered.map(s => <tr key={s.id}>
        <td><label className="ws-inline"><input type="checkbox" aria-label={tr("Select {0} / {1}", {0: s.datasetName, 1: s.name})} checked={selected.includes(s.id)} onChange={() => toggle(s.id)} /><strong>{signalLabel(s)}</strong></label><small>{s.name}</small></td>
        <td>{s.datasetName}<small>{s.source}</small><small>{s.clock.label}</small></td>
        <td>{s.device || tr("No device")} · {s.category || tr("Unclassified")}<small>{s.logicalKey ? tr("Measurement: {0}", {0: s.logicalKey}) : tr("No measurement association")}</small><small>{s.tags?.join(" · ")}</small></td>
        <td>{s.quality.validCount.toLocaleString()}{" "}{tr("usable ·")}{" "}{number(s.quality.missingFraction*100)}{tr("% missing")}<small>{timeLabel(s.time, s.time.start)} → {timeLabel(s.time, s.time.end)}</small></td>
        <td><div className="signal-actions"><button onClick={() => setEditing(s)}>{tr("Edit metadata")}</button><button onClick={() => open([s.id])}>{tr("Open curve ↗")}</button><button onClick={() => { setQualityId(s.datasetId); go(`workspaces/${workspaceId}/quality`); }}>{tr("Inspect quality")}</button>{s.simulationId && <a className="ws-link" href={`#${prefix}/simulations/${s.simulationId}`}>{tr("Open simulation ↗")}</a>}</div></td>
      </tr>)}</tbody></table></div>
      {!loading && !filtered.length && catalog.length > 0 && <p className="ws-notice">{tr("No signals match these filters.")}</p>}
      <p className="ws-muted">{tr("A shared measurement key explicitly associates signals. Each source keeps its own unit; names and keys do not convert values.")}</p>
    </>}
    {mode === "quality" && qualityDataset && <>
      <label className="signal-dataset-select">{tr("Dataset to inspect")}<select value={qualityDataset.id} onChange={e => setQualityId(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
      <QualityExplorer dataset={qualityDataset} open={(signalIds, start, end) => open(signalIds, qualityDataset, start, end)} />
      <TimeReferenceEditor key={qualityDataset.id + JSON.stringify(qualityDataset.metadata.clock)} dataset={qualityDataset} datasets={datasets} onSaved={changed} />
    </>}
    {mode === "explorer" && <>
      <section className="ws-panel explorer-saved"><div className="ws-form-grid"><label>{tr("Saved browsing view")}<select aria-label={tr("Saved browsing view")} value={viewId} onChange={e => { const view = views.find(v => v.id === e.target.value); if (view) restore(view); else { setViewId(""); setSaved(""); } }}><option value="">{tr("Unsaved view")}</option>{views.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label><label>{tr("View name")}<input maxLength={160} required value={name} onChange={e => { setName(e.target.value); setSaved(""); }} /></label><label>{tr("Curve layout")}<select value={displayMode} onChange={e => { setDisplayMode(e.target.value as typeof displayMode); setSaved(""); }}><option value="separate">{tr("Separate signals / shared time")}</option><option value="overlay">{tr("Overlay matching units and categories")}</option></select></label></div>
        <div className="ws-inline"><button className="ws-primary" disabled={busy || plotting || !selected.length || !name.trim()} onClick={() => void save()}>{tr("Save browsing view")}</button>{viewId && <button onClick={() => void save(true)} disabled={busy || plotting}>{tr("Save as new view")}</button>}<span role="status" className="ws-saved">{saved}</span></div>
      </section>
      <details className="ws-panel" open={!selected.length}><summary>{tr("Choose signals ·")}{" "}{selected.length}{" "}{tr("selected")}</summary><div className="explorer-signal-pool">{datasets.map(d => <fieldset key={d.id}><legend>{d.name}</legend>{catalog.filter(s => s.datasetId === d.id).map(s => <label key={s.id}><input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggle(s.id)} />{signalLabel(s)}<small>{s.category || tr("Unclassified")}</small></label>)}</fieldset>)}</div><button onClick={() => { setSelected([]); setSaved(""); }}>{tr("Clear selection")}</button></details>
      {datasets.length > 0 && <details className="ws-panel"><summary>{tr("Time relationships · review or configure source clocks")}</summary><p className="ws-muted">{tr("Absolute sources share UTC. Relative sources stay on independent axes until you save a reference. Offset means source time + offset = reference time. Original timestamps remain unchanged.")}</p>{datasets.map(d => <TimeReferenceEditor key={d.id + JSON.stringify(d.metadata.clock)} dataset={d} datasets={datasets} onSaved={changed} />)}</details>}
      {plotting && <p role="status">{tr("Loading observation windows…")}</p>}
      {!selected.length && <p className="ws-notice">{tr("Choose measurements above or select them in the signal catalog.")}</p>}
      {!plotting && data.axes.length > 1 && <p className="ws-notice">{data.axes.length}{" "}{tr("independent clocks. Configure time relationships to synchronize these sources.")}</p>}
      {!plotting && data.axes.map(axis => <ExplorerGroup key={axis.id} workspaceId={workspaceId} axis={axis} series={data.series.filter(s => s.signal.clock.axisId === axis.id)} datasets={datasets} jobs={jobs} window={windows[axis.id] || axis.window} displayMode={displayMode} onWindow={w => { setWindows(previous => ({ ...previous, [axis.id]: w })); setSaved(""); }} onAnalyze={onAnalyze} />)}
    </>}
    {editing && <SignalEditor signal={editing} catalog={catalog} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); changed(); }} />}
  </>;
}

export function SignalEditor({ signal, catalog, onClose, onSaved }: { signal: CatalogSignal; catalog: CatalogSignal[]; onClose: () => void; onSaved: () => void }) {
  useLocale();
  const [draft, setDraft] = useState({ displayName: signal.displayName || signal.name, unit: signal.unit || "", description: signal.description || "", category: signal.category || "", device: signal.device || "", logicalKey: signal.logicalKey || "" });
  const [tags, setTags] = useState(signal.tags?.join(", ") || ""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement; if (dialog.current?.showModal) dialog.current.showModal(); else dialog.current?.setAttribute("open", ""); return () => previous?.focus(); }, []);
  async function save(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { await api(`/signals/${signal.id}`, { ...draft, tags: tags.split(",").map(t => t.trim()).filter(Boolean) }, "PATCH"); onSaved(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  return <dialog ref={dialog} className="incident-dialog signal-editor" aria-label={tr("Edit signal metadata")} onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}><form onSubmit={save} className="incident-form"><div className="ws-inline ws-between"><h2>{tr("Edit signal metadata")}</h2><button type="button" aria-label={tr("Close signal editor")} onClick={onClose} disabled={busy}>×</button></div><p className="ws-muted">{signal.datasetName} / {signal.name}<br />{tr("Stable signal ID:")}{" "}{signal.id}</p>
    <div className="ws-form-grid">{([ ["displayName", tr("Display name")], ["unit", tr("Physical unit")], ["category", tr("Category")], ["device", tr("Device / subsystem")], ["logicalKey", tr("Logical measurement key")] ] as const).map(([key, label]) => <label key={key}>{tr(label)}<input autoFocus={key === "displayName"} required={key === "displayName"} maxLength={160} value={draft[key]} list={key === "category" ? "signal-categories" : key === "logicalKey" ? "measurement-keys" : key === "device" ? "signal-devices" : undefined} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}<label>{tr("Tags (comma separated)")}<input value={tags} onChange={e => setTags(e.target.value)} /></label></div>
    <datalist id="signal-categories">{categories.map(c => <option key={c} value={c}>{tr(c)}</option>)}</datalist><datalist id="measurement-keys">{[...new Set(catalog.map(s => s.logicalKey).filter(Boolean))].map(k => <option key={k}>{k}</option>)}</datalist><datalist id="signal-devices">{[...new Set(catalog.map(s => s.device).filter(Boolean))].map(k => <option key={k}>{k}</option>)}</datalist>
    <label>{tr("Description")}<textarea maxLength={4000} rows={3} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} /></label><p className="ws-muted">{tr("Use the same measurement key to explicitly associate physical measurement points across datasets. Units are source metadata; values are not converted.")}</p>{errorText(error)}<button className="ws-primary" disabled={busy}>{busy ? tr("Saving…") : tr("Save signal metadata")}</button></form></dialog>;
}

export function TimeReferenceEditor({ dataset, datasets, onSaved }: { dataset: Dataset; datasets: Dataset[]; onSaved: () => void }) {
  useLocale();
  const clock = dataset.metadata.clock;
  const [draft, setDraft] = useState<TimeReference>(clock?.reference || { mode: "independent", offsetSeconds: 0 });
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function save(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { await api(`/datasets/${dataset.id}/time-reference`, draft, "PATCH"); onSaved(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  return <form className="time-reference" onSubmit={save} aria-label={tr("Time reference for {0}", {0: dataset.name})}><h3>{dataset.name}</h3><p className="ws-muted">{tr("Source:")}{" "}{tr(dataset.metadata.time.kind)} · {timeLabel(dataset.metadata.time, dataset.metadata.time.start)} → {timeLabel(dataset.metadata.time, dataset.metadata.time.end)}<br />{tr("Browsing clock:")}{" "}{clock?.label || dataset.name}{" "}{tr("· offset")}{" "}{number(clock?.offset || 0)} s</p>
    {dataset.metadata.transformation ? <p className="ws-saved">{tr("Frozen transformation clock · edit the transformation to generate a new dataset.")}</p> : dataset.metadata.time.origin ? <p className="ws-saved">{tr("Absolute source clock · UTC origin")}{" "}{dataset.metadata.time.origin}</p> : <><div className="ws-form-grid"><label>{tr("Time relationship")}<select value={draft.mode} onChange={e => setDraft({ ...draft, mode: e.target.value as TimeReference["mode"] })}><option value="independent">{tr("Independent relative clock")}</option><option value="reference">{tr("Reference another dataset")}</option><option value="utc">{tr("Set UTC origin for source zero")}</option></select></label>
      {draft.mode === "reference" && <label>{tr("Reference dataset")}<select required value={draft.referenceDatasetId || ""} onChange={e => setDraft({ ...draft, referenceDatasetId: e.target.value })}><option value="">{tr("Choose a reference")}</option>{datasets.filter(d => d.id !== dataset.id).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
      {draft.mode === "utc" && <label>{tr("Source zero (ISO date/time with timezone)")}<input required value={draft.utcOrigin || ""} placeholder="2026-10-24T08:00:00+08:00" onChange={e => setDraft({ ...draft, utcOrigin: e.target.value })} /></label>}
      {draft.mode !== "independent" && <label>{tr("Offset added to source seconds")}<input type="number" step="any" required value={draft.offsetSeconds || 0} onChange={e => setDraft({ ...draft, offsetSeconds: Number(e.target.value) })} /></label>}</div>{errorText(error)}<button className="ws-outlined" disabled={busy}>{tr("Save time relationship")}</button></>}
  </form>;
}

export function QualityExplorer({ dataset, open }: { dataset: Dataset; open: (signals: string[], start: number, end: number) => void }) {
  useLocale();
  const quality = dataset.metadata.quality;
  const [all, setAll] = useState(false);
  if (!quality) return <p className="ws-notice">{tr("Quality metadata is loading.")}</p>;
  const signals = dataset.metadata.columns, axis = dataset.metadata.time;
  const ids = signals.map(s => s.id!).filter(Boolean);
  const issues = [...quality.gaps.map(g => ({ kind: tr("Sampling gap"), start: g.start, end: g.end, detail: tr("{0} s without recorded samples", {0: number(g.duration)}), ids })),
    ...signals.flatMap(s => quality.signals[s.name].missingSpans.map(span => ({ kind: tr("Missing measurement"), start: span.start, end: span.end, detail: tr("{0} · {1} samples", {0: signalLabel(s), 1: span.count}), ids: [s.id!] }))),
    ...quality.duplicates.map(d => ({ kind: tr("Duplicate timestamp"), start: d.time, end: d.time, detail: tr("{0} rows at this time", {0: d.count}), ids })),
    ...quality.invalidTimes.map(i => ({ kind: tr("Invalid timestamp"), start: i.nearbyTime ?? quality.start, end: i.nearbyTime ?? quality.start, detail: tr("CSV row {0}: {1} · curve opens near the preceding valid time", {0: i.row, 1: i.raw}), ids }))].sort((a, b) => a.start - b.start);
  const x = (t: number) => 170 + (t-quality.start)/(quality.end-quality.start || 1)*740;
  return <section className="quality-explorer" aria-label={tr("Dataset quality overview")}><div className="ws-stats"><div><strong>{quality.totalCount.toLocaleString()}</strong><span>{tr("source rows /")}{" "}{quality.timedCount}{" "}{tr("valid timestamps")}</span></div><div><strong>{qualityNumber(quality.typicalInterval)} s</strong><span>{tr("median positive sampling interval")}</span></div><div><strong>{quality.gapCount}</strong><span>{tr("sampling gaps /")}{" "}{quality.irregularCount}{" "}{tr("irregular steps")}</span></div><div><strong>{quality.invalidTimeCount} / {quality.duplicateCount}</strong><span>{tr("invalid / extra duplicate timestamps")}</span></div></div>
    <p>{timeLabel(axis, quality.start)} → {timeLabel(axis, quality.end)}</p><p className="ws-muted">{tr("A gap exceeds 5× the median positive interval (")}{qualityNumber(quality.gapThreshold)}{" "}{tr("s). Irregular steps are the remaining intervals differing by more than 5%. Spans describe recorded sample groups, not continuous observation.")}</p>
    <div className="ws-panel quality-distribution"><h2>{tr("Quality over time")}</h2><p className="ws-muted">{tr("Green: sample spans · coral: missing measurements · amber: sampling gaps. Select a segment to inspect its curve.")}</p><svg viewBox={`0 0 940 ${50 + signals.length*34}`} role="img" aria-label={tr("Data quality time distribution")}>
      {signals.map((s, index) => <g key={s.name}><text x="0" y={24+index*34}>{signalLabel(s).slice(0, 24)}</text><line x1="170" x2="910" y1={20+index*34} y2={20+index*34} stroke="#30392d" />{quality.signals[s.name].availableSpans.map((span, i) => <rect key={`a${i}`} x={x(span.start)} width={Math.max(2, x(span.end)-x(span.start))} y={13+index*34} height="14" fill="#b5ed9a" opacity=".65" />)}{[...quality.gaps.map(g => ({ ...g, kind: tr("Sampling gap") })), ...quality.signals[s.name].missingSpans.map(g => ({ ...g, kind: tr("Missing measurement") }))].map((span, i) => <rect role="button" tabIndex={0} aria-label={tr("{0}: {1} {2} to {3}", {0: span.kind, 1: s.name, 2: span.start, 3: span.end})} key={`p${i}`} x={x(span.start)} width={Math.max(5, x(span.end)-x(span.start))} y={10+index*34} height="20" fill={span.kind === "Sampling gap" ? "#e2bc75" : "#e9927d"} onClick={() => open([s.id!], span.start, span.end)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open([s.id!], span.start, span.end); } }}><title>{tr(span.kind)}: {timeLabel(axis, span.start)} → {timeLabel(axis, span.end)}</title></rect>)}</g>)}<text x="170" y={45+signals.length*34}>{timeLabel(axis, quality.start)}</text><text x="910" y={45+signals.length*34} textAnchor="end">{timeLabel(axis, quality.end)}</text>
    </svg></div>
    <div className="ws-table-scroll"><table><thead><tr><th>{tr("Signal")}</th><th>{tr("Usable / total")}</th><th>{tr("Missing / ratio")}</th><th>{tr("Min / max")}</th><th>{tr("Mean / std")}</th><th>{tr("Sample spans")}</th></tr></thead><tbody>{signals.map(s => { const q = quality.signals[s.name]; return <tr key={s.name}><td><button onClick={() => open([s.id!], quality.start, quality.end)}>{signalLabel(s)} ↗</button></td><td>{q.validCount} / {q.totalCount}{q.invalidTimeMeasurements > 0 && <small>{q.invalidTimeMeasurements}{" "}{tr("finite values with invalid time")}</small>}</td><td>{q.missing} / {number(q.missingFraction*100)}%</td><td>{qualityNumber(q.min)} / {qualityNumber(q.max)}</td><td>{qualityNumber(q.mean)} / {qualityNumber(q.std)}</td><td>{q.availableSpans.length}<details><summary>{tr("Inspect spans")}</summary>{q.availableSpans.map((span, i) => <button className="quality-span" key={i} onClick={() => open([s.id!], span.start, span.end)}>{timeLabel(axis, span.start)} → {timeLabel(axis, span.end)} · {span.count}{" "}{tr("samples")}</button>)}</details></td></tr>; })}</tbody></table></div>
    <h2>{tr("Timestamp and measurement issues ·")}{" "}{issues.length}</h2><div className="quality-issues">{(all ? issues : issues.slice(0, 30)).map((issue, i) => <button key={i} className="quality-issue" onClick={() => open(issue.ids, issue.start, issue.end)}><strong>{tr(issue.kind)}</strong><span>{timeLabel(axis, issue.start)} → {timeLabel(axis, issue.end)}</span><small>{issue.detail}</small><span>{tr("Inspect curve ↗")}</span></button>)}</div>{issues.length > 30 && <button onClick={() => setAll(!all)}>{all ? tr("Show first 30 issues") : tr("Show all {0} issues", {0: issues.length})}</button>}{!issues.length && <p className="ws-notice">{tr("No missing measurements, long gaps or invalid / duplicate timestamps in this source.")}</p>}
  </section>;
}

export function ExplorerGroup({ workspaceId, axis, series, datasets, jobs, window: windowValue, displayMode, onWindow, onAnalyze }: { workspaceId: string; axis: ExplorerAxis; series: ExplorerSeries[]; datasets: Dataset[]; jobs: Job[]; window: ExplorerWindow; displayMode: "separate" | "overlay"; onWindow: (window: ExplorerWindow) => void; onAnalyze: Props["onAnalyze"] }) {
  useLocale();
  const [sourceId, setSourceId] = useState(series[0]?.signal.datasetId || ""), [linking, setLinking] = useState(false);
  const sourceIds = [...new Set(series.map(s => s.signal.datasetId))];
  const dataset = datasets.find(d => d.id === sourceId && sourceIds.includes(d.id)) || datasets.find(d => d.id === sourceIds[0]);
  const groups = new Map<string, ExplorerSeries[]>();
  for (const s of series) { const key = displayMode === "overlay" && s.signal.unit?.trim() && s.signal.category?.trim() ? `${s.signal.unit}\0${s.signal.category}` : s.signal.id; groups.set(key, [...(groups.get(key) || []), s]); }
  const nativeRange: [number, number] | undefined = dataset && [Math.max(dataset.metadata.time.start, windowValue.start-datasetClock(dataset).offset), Math.min(dataset.metadata.time.end, windowValue.end-datasetClock(dataset).offset)];
  const available = nativeRange && nativeRange[0] <= nativeRange[1];
  const chosen = series.filter(s => s.signal.datasetId === dataset?.id).map(s => s.signal.name);
  return <section className="explorer-group ws-panel" aria-label={tr("Explorer clock {0}", {0: axis.label})}><div className="ws-section-heading"><div><span className="ws-kicker">{axis.origin ? tr("SHARED UTC CLOCK") : tr("EXPLICIT RELATIVE CLOCK")}</span><h2>{axis.label}</h2></div><span>{series.length}{" "}{tr("signals /")}{" "}{sourceIds.length}{" "}{tr("sources")}</span></div>
    <ObservationWindow key={`${windowValue.start}:${windowValue.end}`} axis={axis} value={windowValue} apply={onWindow} />
    <div className="explorer-cursor"><label>{tr("Observation cursor")}<input aria-label={tr("Observation cursor {0}", {0: axis.label})} type="range" min={0} max={windowValue.end-windowValue.start} step="any" value={windowValue.at-windowValue.start} onChange={e => onWindow({ ...windowValue, at: windowValue.start+Number(e.target.value) })} /></label><label>{tr("Cursor offset from window start (s)")}<input type="number" step="any" min={0} max={windowValue.end-windowValue.start} value={windowValue.at-windowValue.start} onChange={e => { const offset = Number(e.target.value); if (e.target.value !== "" && offset >= 0 && offset <= windowValue.end-windowValue.start) onWindow({ ...windowValue, at: windowValue.start+offset }); }} /></label><span>{timeLabel(axisTime(axis), windowValue.at)}</span></div>
    <p className="ws-muted">{tr("Move over a curve or use the cursor to inspect original measurements. Each value shows its actual sample time; no interpolation. Amber shading marks sampling gaps.")}</p>
    {[...groups.entries()].map(([key, items], i) => { const nonempty = items.filter(s => s.times.length), first = nonempty[0]; return <div key={key} className="explorer-lane"><div className="explorer-legend">{items.map((s, j) => <span key={s.signal.id} style={{ color: colors[(i+j)%colors.length] }}>{signalLabel(s.signal)} · {s.signal.datasetName} · {s.sourceRows.toLocaleString()}{" "}{tr("samples")}</span>)}</div>{first ? <Plot title={items.map(s => signalLabel(s.signal)).join(" / ")} times={first.times} values={first.values} segmentIds={first.segmentIds} color={colors[i%colors.length]} overlays={nonempty.slice(1).map((s, j) => ({ times: s.times, values: s.values, segmentIds: s.segmentIds, title: `${signalLabel(s.signal)} · ${s.signal.datasetName}`, color: colors[(i+j+1)%colors.length] }))} axis={axisTime(axis)} timeDomain={[windowValue.start, windowValue.end]} selectedTime={windowValue.at} onSelectTime={at => onWindow({ ...windowValue, at })} onHoverTime={at => onWindow({ ...windowValue, at })} gaps={items.flatMap(s => (datasets.find(d => d.id === s.signal.datasetId)?.metadata.quality?.gaps || []).map(g => ({ start: g.start+s.signal.clock.offset, end: g.end+s.signal.clock.offset })))} /> : <p className="ws-notice">{tr("No samples from this source in the selected window.")}</p>}{items.some(s => s.displayRows < s.sourceRows) && <p className="ws-muted">{tr("Display sampling preserves extrema and missing-data boundaries. The cursor reads the full source arrays.")}</p>}</div>; })}
    <CursorReadout workspaceId={workspaceId} axis={axis} series={series} at={windowValue.at} />
    {dataset && <div className="explorer-workflow"><label>{tr("Continue with source")}<select value={dataset.id} onChange={e => setSourceId(e.target.value)}>{sourceIds.map(id => <option key={id} value={id}>{datasets.find(d => d.id === id)?.name}</option>)}</select></label><div className="ws-inline"><button className="ws-primary" disabled={!available} onClick={() => nativeRange && onAnalyze(dataset.id, chosen, nativeRange)}>{tr("Configure analysis for this window ↗")}</button><button disabled={!available} onClick={() => setLinking(true)}>{tr("创建事件 / selected window")}</button>{dataset.metadata.model && <a className="ws-link" href={`#/workspaces/${workspaceId}/simulations/${dataset.metadata.model.simulationId}`}>{tr("Open process investigation ↗")}</a>}</div><div className="ws-inline">{jobs.filter(j => j.dataset_id === dataset.id && nativeRange && j.config.analysisRange[1] >= nativeRange[0] && j.config.analysisRange[0] <= nativeRange[1]).map(j => <a className="ws-link" key={j.id} href={`#/workspaces/${workspaceId}/analysis/${j.id}`}>{tr("Open analysis:")}{" "}{j.name} ↗</a>)}</div></div>}
    {linking && dataset && nativeRange && <IncidentLinkDialog workspaceId={workspaceId} source={{ kind: "dataset", datasetId: dataset.id }} draft={{ title: tr("{0} · signal investigation", {0: dataset.name}), start: nativeRange[0], end: nativeRange[1], origin: dataset.metadata.time.origin, description: tr("Selected source: {0}. Signals: {1}. Observation: {2} → {3}.", {0: dataset.name, 1: series.filter(s => s.signal.datasetId === dataset.id).map(s => signalLabel(s.signal)).join(", "), 2: timeLabel(axisTime(axis), windowValue.start), 3: timeLabel(axisTime(axis), windowValue.end)}) }} onClose={() => setLinking(false)} />}
  </section>;
}

function ObservationWindow({ axis, value, apply }: { axis: ExplorerAxis; value: ExplorerWindow; apply: (value: ExplorerWindow) => void }) {
  useLocale();
  const relative = axis.origin ? axis.start : 0;
  const [start, setStart] = useState(String(value.start-relative)), [end, setEnd] = useState(String(value.end-relative));
  function zoom(factor: number) { const center = (value.start+value.end)/2, half = Math.max((value.end-value.start)*factor/2, .000001); apply({ start: center-half, end: center+half, at: Math.max(center-half, Math.min(center+half, value.at)) }); }
  return <form className="observation-window" onSubmit={e => { e.preventDefault(); const a = Number(start)+relative, b = Number(end)+relative; if (Number.isFinite(a) && Number.isFinite(b) && a <= b) apply({ start: a, end: b, at: Math.max(a, Math.min(b, value.at)) }); }}>
    {axis.origin && <p className="ws-muted">{tr("Window inputs: seconds from")}{" "}{timeLabel(axisTime(axis), axis.start)}</p>}<div className="ws-inline"><label>{tr("Window start (s)")}<input required type="number" step="any" value={start} onChange={e => setStart(e.target.value)} /></label><label>{tr("Window end (s)")}<input required type="number" step="any" min={start} value={end} onChange={e => setEnd(e.target.value)} /></label><button className="ws-outlined">{tr("Apply observation window")}</button><button type="button" onClick={() => zoom(.5)}>{tr("Zoom in")}</button><button type="button" onClick={() => zoom(2)}>{tr("Zoom out")}</button><button type="button" onClick={() => apply({ start: axis.start, end: axis.end, at: axis.start })}>{tr("Full coverage")}</button></div>
  </form>;
}

export function CursorReadout({ workspaceId, axis, series, at }: { workspaceId: string; axis: ExplorerAxis; series: ExplorerSeries[]; at: number }) {
  useLocale();
  const [samples, setSamples] = useState<ExplorerSample[]>([]), [error, setError] = useState("");
  const ids = JSON.stringify(series.map(s => s.signal.id));
  useEffect(() => {
    const controller = new AbortController(); setSamples([]); setError("");
    const timer = setTimeout(() => { void api<{ samples: ExplorerSample[] }>(`/workspaces/${workspaceId}/cursor`, { signalIds: JSON.parse(ids), at, axisId: axis.id }, "POST", controller.signal).then(d => { if (!controller.signal.aborted) setSamples(d.samples); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }); }, 80);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [workspaceId, axis.id, at, ids]);
  const statuses = { gap: tr("Sampling gap"), outside: tr("Outside source coverage"), missing: tr("Missing measurement"), measured: tr("Measured"), processed: tr("Processed value · not an original observation") };
  return <div className="ws-table-scroll cursor-readout" aria-label={tr("Original measurement values")}><h3>{tr("Original measurements at cursor")}</h3>{errorText(error)}<table><thead><tr><th>{tr("Signal / unit")}</th><th>{tr("Source")}</th><th>{tr("Value")}</th><th>{tr("Actual sample time")}</th><th>{tr("Observation status")}</th></tr></thead><tbody>{series.map(s => { const sample = samples.find(v => v.signalId === s.signal.id); return <tr key={s.signal.id}><td>{signalLabel(s.signal)}</td><td>{s.signal.datasetName}</td><td>{sample ? sample.value == null ? "—" : String(sample.value) : tr("Reading…")}</td><td>{sample && sample.status !== "outside" && sample.status !== "gap" ? <>{timeLabel(axisTime(axis), sample.time)}<small>{tr("Native")}{" "}{number(sample.nativeTime)} s · Δ {number(sample.deltaSeconds)}{" "}{tr("s · source index")}{" "}{sample.sourceIndex}</small></> : "—"}</td><td>{sample ? statuses[sample.status] : tr("Loading")}{sample && sample.duplicateCount > 1 && <small>{sample.duplicateCount}{" "}{tr("rows share this timestamp; first nearest source row shown")}</small>}</td></tr>; })}</tbody></table></div>;
}
