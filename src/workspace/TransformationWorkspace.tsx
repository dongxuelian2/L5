import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { analysisPath, api, go, message } from "./api";
import { Plot } from "./Charts";
import { dateLabel, number, signalLabel, timeLabel, type CatalogSignal, type Dataset } from "./types";
import type { DerivedSignal, EngineeringUnit, Transformation, TransformationConfig, TransformPreview, TransformSource } from "./transformationTypes";
import "./transformations.css";

const blank = (): TransformationConfig => ({ version: 1, sources: [], derived: [], grid: { mode: "intersection", intervalSeconds: 1 } });
const aliases: Record<string, string> = { C: "°C", degC: "°C", F: "°F", degF: "°F", "m3/s": "m³/s", "m3/h": "m³/h", "": "1" };
const provenanceLabels: Record<string, string> = { get missing() { return tr("missing"); }, measured: "measurement", interpolated: "interpolated", held: "held", aggregated: "aggregate", get "fixed-fill"() { return tr("fixed fill"); }, get "statistic-fill"() { return tr("statistic fill"); }, derived: "calculated", get nearest() { return tr("nearest sample"); }, get "processed-source"() { return tr("processed source"); } };
const shown = (value: number | null) => value == null ? "—" : number(value);

export function TransformationWorkspace({ workspaceId, datasets, definitionId, initialSignalIds, onGenerated }: {
  workspaceId: string; datasets: Dataset[]; definitionId?: string; initialSignalIds?: string; onGenerated: (dataset: Dataset) => void;
}) {
  useLocale();
  const [catalog, setCatalog] = useState<CatalogSignal[]>([]), [units, setUnits] = useState<EngineeringUnit[]>([]), [definitions, setDefinitions] = useState<Transformation[]>([]);
  const [config, setConfig] = useState<TransformationConfig>(blank), [name, setName] = useState(tr("Aligned process data")), [saved, setSaved] = useState<Transformation | null>(null);
  const [preview, setPreview] = useState<TransformPreview | null>(null), [generated, setGenerated] = useState<Dataset | null>(null);
  const [loading, setLoading] = useState(true), [previewing, setPreviewing] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(""), [previewError, setPreviewError] = useState(""), [status, setStatus] = useState("");
  const [search, setSearch] = useState(""), [nonce, setNonce] = useState(0);
  const restored = useRef("");
  const prefix = `/workspaces/${workspaceId}`;
  function sourceFor(signal: CatalogSignal, index: number): TransformSource {
    return { signalId: signal.id, key: `s_${index + 1}`, displayName: signal.displayName || signal.name, unit: signal.unit || "",
      resampling: "linear", maxGapSeconds: Math.max((signal.time.typicalInterval || 1) * 5, .000001), duplicatePolicy: "error", missing: { method: "keep" } };
  }
  function restore(definition: Transformation) {
    setConfig(definition.config); setName(definition.name); setSaved(definition); setGenerated(null); setStatus(tr("Opened revision {0}", {0: definition.revision})); setError("");
  }
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api<{ signals: CatalogSignal[] }>(`${prefix}/signals`, undefined, "GET", controller.signal), api<{ transformations: Transformation[] }>(`${prefix}/transformations`, undefined, "GET", controller.signal), api<{ units: EngineeringUnit[] }>("/units", undefined, "GET", controller.signal)])
      .then(([c, t, u]) => { if (!controller.signal.aborted) { setCatalog(c.signals); setDefinitions(t.transformations); setUnits(u.units); } })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [workspaceId, datasets]);
  useEffect(() => {
    if (loading) return;
    const key = `${definitionId || "new"}:${initialSignalIds || ""}`;
    if (restored.current === key) return;
    restored.current = key;
    if (definitionId && definitionId !== "new") {
      const definition = definitions.find(d => d.id === definitionId);
      if (definition) restore(definition); else setError(tr("Saved transformation was not found in this workspace."));
    } else if (initialSignalIds) {
      const selected = initialSignalIds.split(",").map(id => catalog.find(s => s.id === id)).filter((s): s is CatalogSignal => !!s);
      setConfig({ ...blank(), sources: selected.map(sourceFor) }); setSaved(null);
    }
  }, [loading, definitionId, initialSignalIds, definitions, catalog]);
  const configKey = JSON.stringify(config);
  useEffect(() => {
    setPreview(null); setPreviewError("");
    if (!config.sources.length) { setPreviewing(false); return; }
    const controller = new AbortController(); setPreviewing(true);
    const timer = setTimeout(() => {
      api<TransformPreview>(`${prefix}/transformations/preview`, { config: JSON.parse(configKey) }, "POST", controller.signal)
        .then(data => { if (!controller.signal.aborted) setPreview(data); })
        .catch(e => { if (!controller.signal.aborted) setPreviewError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setPreviewing(false); });
    }, 450);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [workspaceId, configKey, nonce]);
  function edit(next: TransformationConfig) { setConfig(next); setStatus(""); setGenerated(null); }
  function changeSource(index: number, change: Partial<TransformSource>) { edit({ ...config, sources: config.sources.map((source, i) => i === index ? { ...source, ...change } : source) }); }
  function changeDerived(index: number, change: Partial<DerivedSignal>) { edit({ ...config, derived: config.derived.map((output, i) => i === index ? { ...output, ...change } : output) }); }
  function toggle(signal: CatalogSignal) {
    if (config.sources.some(s => s.signalId === signal.id)) edit({ ...config, sources: config.sources.filter(s => s.signalId !== signal.id) });
    else {
      let index = config.sources.length;
      while ([...config.sources, ...config.derived].some(s => s.key === `s_${index + 1}`)) index++;
      edit({ ...config, sources: [...config.sources, sourceFor(signal, index)] });
    }
  }
  async function persist(): Promise<Transformation> {
    if (saved && name === saved.name && configKey === JSON.stringify(saved.config)) return saved;
    const definition = await api<Transformation>(saved ? `/transformations/${saved.id}` : `${prefix}/transformations`, { name, config }, saved ? "PATCH" : "POST");
    setSaved(definition); setConfig(definition.config); setDefinitions(previous => [definition, ...previous.filter(d => d.id !== definition.id)]);
    return definition;
  }
  async function save(execute: boolean) {
    setBusy(true); setError("");
    try {
      const definition = await persist();
      if (execute) {
        const dataset = await api<Dataset>(`/transformations/${definition.id}/execute`, { name: tr("{0} · revision {1}", {0: name, 1: definition.revision}) });
        setGenerated(dataset); onGenerated(dataset); setStatus(tr("Generated {0} samples. Previous datasets and analyses remain available.", {0: dataset.metadata.rowCount.toLocaleString()}));
      } else setStatus(tr("Configuration saved · revision {0}", {0: definition.revision}));
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const selectedSignals = config.sources.map(source => catalog.find(s => s.id === source.signalId));
  const axisIds = [...new Set(config.sources.map((s, i) => (s.clock || selectedSignals[i]?.clock)?.axisId).filter(Boolean))];
  const starts = config.sources.map((source, i) => { const signal = selectedSignals[i]; return signal ? signal.time.start + (source.clock || signal.clock).offset : 0; });
  const ends = config.sources.map((source, i) => { const signal = selectedSignals[i]; return signal ? signal.time.end + (source.clock || signal.clock).offset : 0; });
  const base = starts.length ? Math.min(...starts) : 0;
  const currentExecutions = datasets.filter(d => d.metadata.transformation?.definitionId === saved?.id && d.metadata.transformation);
  return <>
    <div className="ws-page-title"><div><div className="ws-kicker">{tr("DATA / TRANSFORMATIONS")}</div><h1>{tr("Transformation Workspace")}<span className="ws-accent">.</span></h1><p>{tr("Align measurements, calculate variables and save a traceable dataset.")}</p></div></div>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}{loading && <p role="status">{tr("Loading signals and saved transformations…")}</p>}
    <fieldset className="transform-editor" disabled={busy || loading}>
      <section className="ws-panel"><div className="ws-form-grid">
        <label>{tr("Saved transformation")}<select value={saved?.id || ""} onChange={e => { const d = definitions.find(t => t.id === e.target.value); if (d) { restore(d); go(`workspaces/${workspaceId}/transformations/${d.id}`); } else { edit(blank()); setSaved(null); setName(tr("Aligned process data")); go(`workspaces/${workspaceId}/transformations/new`); } }}><option value="">{tr("New configuration")}</option>{definitions.map(d => <option key={d.id} value={d.id}>{d.name}{" "}{tr("· revision")}{" "}{d.revision}</option>)}</select></label>
        <label>{tr("Transformation name")}<input value={name} maxLength={160} onChange={e => { setName(e.target.value); setStatus(""); }} /></label>
      </div>{saved && <p className="ws-muted">{tr("Revision")}{" "}{saved.revision}{" "}{tr("· saved")}{" "}{dateLabel(saved.updated_at)}{" "}{tr("· each execution creates a separate dataset.")}</p>}</section>
      <section className="ws-panel"><h2>{tr("1. Select source signals")}</h2><label>{tr("Find signals")}<input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={tr("Name, dataset or unit")} /></label>
        <div className="transform-catalog">{catalog.filter(s => `${s.datasetName} ${s.name} ${s.displayName} ${s.unit}`.toLowerCase().includes(search.toLowerCase())).map(signal => <label key={signal.id} className="transform-source-choice"><input type="checkbox" checked={config.sources.some(s => s.signalId === signal.id)} onChange={() => toggle(signal)} /><span><strong>{signalLabel(signal)}</strong><small>{signal.datasetName} · {signal.clock.axisId === "utc" ? "UTC" : signal.clock.label}</small></span></label>)}</div>
        {!catalog.length && <p className="ws-notice">{tr("Import CSV data or save a process simulation to choose source signals.")}</p>}
      </section>
      {config.sources.length > 0 && <>
        <section className="ws-panel"><h2>{tr("2. Choose the target time grid")}</h2><p className={axisIds.length > 1 ? "ws-error" : "ws-muted"}>{tr("Source clock:")}{" "}{axisIds.join(" / ")}{axisIds.length > 1 && tr(" · Save a time reference to connect these sources before transformation.")} <a className="ws-link" href={`#${prefix}/signals`}>{tr("Edit time relationships ↗")}</a></p>
          <p className="ws-muted">{tr("Time inputs are seconds from")}{" "}{axisIds[0] === "utc" ? new Date(base * 1000).toISOString() : tr("{0} s on the source axis", {0: number(base)})}{tr(". Output sample zero is the start of the selected grid.")}</p>
          <div className="ws-form-grid ws-three"><label>{tr("Coverage")}<select value={config.grid.mode} onChange={e => edit({ ...config, grid: { ...config.grid, mode: e.target.value as TransformationConfig["grid"]["mode"], start: Math.max(...starts), end: Math.min(...ends) } })}><option value="intersection">{tr("Common coverage")}</option><option value="union">{tr("All source coverage · preserve holes")}</option><option value="custom">{tr("Custom interval")}</option></select></label>
            <label>{tr("Sampling interval (s)")}<input type="number" min="0.000001" step="any" value={config.grid.intervalSeconds} onChange={e => edit({ ...config, grid: { ...config.grid, intervalSeconds: Number(e.target.value) } })} /></label>
            {config.grid.mode === "custom" && <><label>{tr("Grid start (s from reference)")}<input type="number" step="any" value={(config.grid.start ?? base) - base} onChange={e => edit({ ...config, grid: { ...config.grid, start: base + Number(e.target.value) } })} /></label><label>{tr("Grid end (s from reference)")}<input type="number" step="any" value={(config.grid.end ?? base) - base} onChange={e => edit({ ...config, grid: { ...config.grid, end: base + Number(e.target.value) } })} /></label></>}
          </div><p className="ws-notice">{tr("Coverage boundaries are retained. No method extrapolates beyond a source. Aggregation uses left-closed windows [time, time + interval).")}</p>
          <button type="button" className="ws-outlined" onClick={() => edit({ ...config, sources: config.sources.map((source, i) => ({ ...source, clock: selectedSignals[i]?.clock, sourceUnit: selectedSignals[i]?.unit || "" })) })}>{tr("Use current source clocks and units")}</button>
        </section>
        <section className="ws-panel"><h2>{tr("3. Convert, resample and handle missing values")}</h2>{config.sources.map((source, index) => {
          const signal = selectedSignals[index], sourceUnit = source.sourceUnit ?? signal?.unit ?? "";
          const group = units.find(u => u.name === (aliases[sourceUnit] ?? sourceUnit));
          const options = group && (!group.requiresRotationalMeaning || source.rotational) ? units.filter(u => u.dimension === group.dimension).map(u => u.name) : [sourceUnit];
          return <fieldset key={source.signalId} className="transform-signal"><legend>{signal?.datasetName} / {signal ? signalLabel(signal) : source.signalId}</legend>
            <p className="ws-muted">{tr("Source unit:")}{" "}{sourceUnit || "unspecified"}{" "}{tr("→ output:")}{" "}{source.unit || "unspecified"}{" "}{tr("· source ID")}{" "}<code>{source.signalId}</code></p>
            <div className="ws-form-grid ws-three"><label>{tr("Signal key")}{" "}{index + 1}<input value={source.key} maxLength={64} onChange={e => changeSource(index, { key: e.target.value })} /></label><label>{tr("Output name")}{" "}{index + 1}<input value={source.displayName} maxLength={160} onChange={e => changeSource(index, { displayName: e.target.value })} /></label>
              <label>{tr("Output unit")}{" "}{index + 1}<select value={source.unit} onChange={e => changeSource(index, { unit: e.target.value })}>{[...new Set([source.unit, ...options])].map(unit => <option key={unit} value={unit}>{unit || tr("Unspecified · preserved")}</option>)}</select></label>
              <label>{tr("Resampling")}{" "}{index + 1}<select value={source.resampling} onChange={e => changeSource(index, { resampling: e.target.value as TransformSource["resampling"] })}>{[["nearest", tr("Nearest sample")], ["linear", tr("Linear interpolation")], ["previous", tr("Previous value")], ["mean", tr("Window mean")], ["min", tr("Window minimum")], ["max", tr("Window maximum")]].map(([v, label]) => <option key={v} value={v}>{tr(label)}</option>)}</select></label>
              <label>{tr("Maximum gap (s)")}{" "}{index + 1}<input type="number" min="0.000001" step="any" value={source.maxGapSeconds} onChange={e => changeSource(index, { maxGapSeconds: Number(e.target.value) })} /></label>
              <label>{tr("Duplicate timestamps")}{" "}{index + 1}<select value={source.duplicatePolicy} onChange={e => changeSource(index, { duplicatePolicy: e.target.value as TransformSource["duplicatePolicy"] })}>{[["error", tr("Report conflict")], ["first", tr("First row")], ["last", tr("Last row")], ["mean", tr("Mean of finite values")]].map(([v, label]) => <option key={v} value={v}>{tr(label)}</option>)}</select></label>
              <label>{tr("Missing values")}{" "}{index + 1}<select value={source.missing.method} onChange={e => changeSource(index, { missing: { method: e.target.value as TransformSource["missing"]["method"], value: 0, statistic: "median" } })}>{[["keep", tr("Keep missing")], ["linear", tr("Linear interpolation")], ["previous", tr("Previous value")], ["fixed", tr("Fixed value")], ["statistic", tr("Known valid source statistic")]].map(([v, label]) => <option key={v} value={v}>{tr(label)}</option>)}</select></label>
              {source.missing.method === "fixed" && <label>{tr("Fill value")}{" "}{index + 1}<input type="number" step="any" value={source.missing.value ?? 0} onChange={e => changeSource(index, { missing: { ...source.missing, value: Number(e.target.value) } })} /></label>}
              {source.missing.method === "statistic" && <label>{tr("Statistic")}{" "}{index + 1}<select value={source.missing.statistic || "median"} onChange={e => changeSource(index, { missing: { ...source.missing, statistic: e.target.value as "mean" | "median" | "min" | "max" } })}>{["mean", "median", "min", "max"].map(v => <option key={v}>{v}</option>)}</select></label>}
            </div>{group?.requiresRotationalMeaning && <label className="ws-inline"><input type="checkbox" checked={source.rotational || false} onChange={e => changeSource(index, { rotational: e.target.checked })} />{tr("This signal represents rotational speed (rpm / Hz)")}</label>}
            <p className="ws-muted">{tr("Interpolation uses a maximum bracket span; previous value uses a maximum age. Statistical fills use original valid measurements inside the output window.")}</p>
          </fieldset>;
        })}</section>
        <section className="ws-panel"><h2>{tr("4. Calculate derived signals")}</h2><p className="ws-muted">{tr("Reference stable keys:")}{" "}{config.sources.map(s => `${s.key} [${s.unit || "unspecified"}]`).join(" · ")}{tr(". Later calculations can use earlier derived keys.")}</p>
          <p className="ws-muted">{tr("Arithmetic: + − * /. Scalar bounds in clip, minimum and maximum use the first input’s unit. Functions: abs, sqrt, log, exp, sin, cos, minimum, maximum, clip, diff, rate. rate uses elapsed seconds; its first sample is missing. Subtract absolute temperatures to obtain a temperature difference.")}</p>
          {config.derived.map((output, index) => <fieldset className="transform-signal" key={index}><legend>{tr("Derived signal")}{" "}{index + 1}</legend><div className="ws-form-grid ws-three"><label>{tr("Derived key")}{" "}{index + 1}<input value={output.key} maxLength={64} onChange={e => changeDerived(index, { key: e.target.value })} /></label><label>{tr("Derived name")}{" "}{index + 1}<input value={output.displayName} onChange={e => changeDerived(index, { displayName: e.target.value })} /></label><label>{tr("Derived unit")}{" "}{index + 1}<input value={output.unit} onChange={e => changeDerived(index, { unit: e.target.value })} placeholder={tr("Infer when possible")} /></label></div><label>{tr("Expression")}{" "}{index + 1}<input className="transform-expression" value={output.expression} onChange={e => changeDerived(index, { expression: e.target.value })} placeholder={tr("s_1 - s_2 or rate(s_1)")} /></label><label>{tr("Description")}{" "}{index + 1}<input value={output.description || ""} onChange={e => changeDerived(index, { description: e.target.value })} /></label><button className="ws-danger" onClick={() => edit({ ...config, derived: config.derived.filter((_, i) => i !== index) })}>{tr("Remove derived signal")}{" "}{index + 1}</button></fieldset>)}
          <button className="ws-outlined" onClick={() => { let i = config.derived.length + 1; while ([...config.sources, ...config.derived].some(s => s.key === `derived_${i}`)) i++; edit({ ...config, derived: [...config.derived, { key: `derived_${i}`, displayName: tr("Derived signal {0}", {0: i}), expression: config.sources[0].key, unit: "" }] }); }}>{tr("+ Add derived signal")}</button>
          <p className="ws-notice">{tr("Compatible additions and subtractions convert units automatically. Complex products require an explicit output unit; their numeric inputs use the units displayed above.")}</p>
        </section>
      </>}
    </fieldset>
    {previewing && <p role="status">{tr("Computing preview…")}</p>}{previewError && <p className="ws-error" role="alert">{previewError}</p>}
    {preview && <section className="ws-panel" aria-label={tr("Transformation preview")}><h2>{tr("5. Preview calculated data")}</h2><p>{preview.metadata.rowCount.toLocaleString()}{" "}{tr("samples ·")}{" "}{preview.metadata.columns.length}{" "}{tr("signals ·")}{" "}{timeLabel(preview.metadata.time, 0)} → {timeLabel(preview.metadata.time, preview.metadata.time.end)} · {number(config.grid.intervalSeconds)}{" "}{tr("s interval")}</p>
      <div className="ws-table-scroll"><table><thead><tr><th>{tr("Signal")}</th><th>{tr("Before fill: valid / missing")}</th><th>{tr("After fill: valid / missing")}</th><th>{tr("Range before → after fill")}</th><th>{tr("Original observations")}</th><th>{tr("Processed points")}</th></tr></thead><tbody>{preview.metadata.transformation?.quality.map(q => <tr key={q.key}><td>{q.key}</td><td>{q.before.validCount} / {(q.before.missingFraction * 100).toFixed(1)}%</td><td>{q.after.validCount} / {(q.after.missingFraction * 100).toFixed(1)}%</td><td>{shown(q.before.min)} – {shown(q.before.max)} → {shown(q.after.min)} – {shown(q.after.max)}</td><td>{q.observedCount}</td><td>{Object.entries(q.provenance).filter(([key, value]) => value > 0 && key !== "missing").map(([key, value]) => `${tr(provenanceLabels[key] || key)}: ${value}`).join(" · ")}</td></tr>)}</tbody></table></div>
      {preview.metadata.columns.map(column => <Plot key={column.name} times={preview.series.times} values={preview.series.values[column.name]} segmentIds={preview.series.segmentIds?.[column.name]} title={signalLabel(column)} axis={preview.metadata.time} />)}
      <details><summary>{tr("Inspect sample values and provenance")}</summary><div className="ws-table-scroll"><table><thead><tr><th>{tr("Time (s)")}</th>{preview.metadata.columns.map(c => <th key={c.name}>{signalLabel(c)}</th>)}</tr></thead><tbody>{preview.samples.map((sample, i) => <tr key={i}><td>{number(sample.time)}</td>{preview.metadata.columns.map(c => <td key={c.name}>{shown(sample.values[c.name])}<small className="transform-cell-note">{tr(provenanceLabels[sample.provenance[c.name]])} · {sample.observed[c.name] ? tr("original coverage") : tr("processed / missing")}</small></td>)}</tr>)}</tbody></table></div></details>
    </section>}
    <div className="ws-panel transform-actions"><button className="ws-outlined" disabled={busy || !config.sources.length} onClick={() => setNonce(v => v + 1)}>{tr("Recompute preview")}</button><button className="ws-outlined" disabled={busy || !preview || previewing || !!previewError || !name.trim()} onClick={() => void save(false)}>{tr("Save configuration")}</button><button className="ws-primary" disabled={busy || !preview || previewing || !!previewError || !name.trim()} onClick={() => void save(true)}>{busy ? tr("Saving and computing…") : tr("Generate new dataset ↗")}</button></div>
    {status && <p className="ws-notice" role="status">{tr(status)}</p>}{generated && <section className="ws-panel"><h2>{generated.name}</h2><p>{tr("The generated dataset is available in Signal catalog, Explorer, Analysis, Experiments and Incidents.")}</p><div className="ws-inline"><a className="ws-link" href={`#${prefix}/datasets/${generated.id}`}>{tr("Open dataset and provenance ↗")}</a><button className="ws-primary" onClick={() => { onGenerated(generated); go(analysisPath(workspaceId, generated.id, generated.metadata.columns.map(c => c.name))); }}>{tr("Analyze generated dataset ↗")}</button><a className="ws-link" href={`#${prefix}/experiments/new/${generated.id}`}>{tr("Create experiment from generated dataset ↗")}</a></div><TransformationLineage dataset={generated} /></section>}
    {currentExecutions.length > 0 && <section className="ws-panel"><h2>{tr("Saved executions")}</h2>{currentExecutions.map(dataset => <p key={dataset.id}><a className="ws-link" href={`#${prefix}/datasets/${dataset.id}`}>{dataset.name}</a> · {dateLabel(dataset.created_at)} · {dataset.metadata.rowCount}{" "}{tr("samples")}</p>)}</section>}
  </>;
}

export function TransformationLineage({ dataset }: { dataset: Dataset }) {
  useLocale();
  const lineage = dataset.metadata.transformation;
  if (!lineage) return null;
  return <details className="transform-lineage"><summary>{tr("Transformation provenance ·")}{" "}{lineage.definitionName}{" "}{tr("· revision")}{" "}{lineage.revision}</summary>
    <p>{lineage.createdAt && dateLabel(lineage.createdAt)} · {lineage.grid.samples}{" "}{tr("samples ·")}{" "}{number(lineage.grid.intervalSeconds)}{" "}{tr("s interval · execution")}{" "}<code>{lineage.executionId}</code></p>
    <p><a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/transformations/${lineage.definitionId}`}>{tr("Open editable configuration ↗")}</a></p>
    <p>{tr("Sources:")}{" "}{lineage.sources.map((source, index) => <span key={source.datasetId}>{index > 0 && " · "}<a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/datasets/${source.datasetId}`}>{source.datasetName}</a></span>)}</p>
    <p>{tr("Signals:")}{" "}{lineage.config.sources.map((source, index) => <span key={source.key}>{index > 0 && " · "}<a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/explorer/${source.signalId}`}>{source.displayName} [{source.sourceUnit || "unspecified"}] → {source.unit || "unspecified"}</a> / {source.resampling}{" "}{tr("/ max gap")}{" "}{source.maxGapSeconds}{" "}{tr("s / missing:")}{" "}{source.missing.method}{" "}{tr("/ duplicates:")}{" "}{source.duplicatePolicy}</span>)}</p>
    {lineage.config.derived.map(output => <p key={output.key}><code>{output.key} = {output.expression}</code> · {dataset.metadata.columns.find(c => c.name === output.key)?.unit || "unspecified"}</p>)}
    {lineage.sourceSimulations.map(id => <p key={id}><a className="ws-link" href={`#/workspaces/${dataset.workspace_id}/simulations/${id}`}>{tr("Open source process simulation ↗")}</a></p>)}
    <p className="ws-notice">{tr("This dataset keeps the values, source clocks and definition from its execution. Editing the saved configuration affects future executions.")}</p>
    <details><summary>{tr("Execution parameters, source hashes and quality")}</summary><pre className="transform-json">{JSON.stringify(lineage, null, 2)}</pre></details>
  </details>;
}
