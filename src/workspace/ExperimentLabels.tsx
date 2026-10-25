import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import type { Dataset } from "./types";
import type { LabelInterval, LabelSet } from "./experimentTypes";

export function ExperimentLabels({ dataset, value, onChange }: { dataset: Dataset; value?: string; onChange: (id?: string) => void }) {
  const [labels, setLabels] = useState<LabelSet[]>([]), [revision, setRevision] = useState(0), [error, setError] = useState("");
  const [name, setName] = useState("Reviewed labels"), [source, setSource] = useState(""), [intervals, setIntervals] = useState<LabelInterval[]>([]);
  const [importText, setImportText] = useState(""), [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const simulations = dataset.metadata.model ? [dataset.metadata.model.simulationId] : dataset.metadata.transformation?.sourceSimulations || [];
  const [simulation, setSimulation] = useState(simulations[0] || "");
  useEffect(() => {
    const controller = new AbortController(); generation.current++; setLabels([]); setIntervals([]); setError("");
    api<{ labels: LabelSet[] }>(`/datasets/${dataset.id}/labels`, undefined, "GET", controller.signal).then(data => { if (!controller.signal.aborted) setLabels(data.labels); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => { controller.abort(); generation.current++; };
  }, [dataset.id, revision]);
  async function save(triplens = false) {
    const request = generation.current; setBusy(true); setError("");
    try {
      const labels = await api<LabelSet>(`/datasets/${dataset.id}/labels${triplens ? "/triplens" : ""}`, triplens ? { simulationId: simulation || simulations[0] } : { name, timeSource: source, timeBasis: "dataset-seconds", intervals });
      if (request !== generation.current) return;
      onChange(labels.id); setRevision(v => v + 1);
    } catch (e) { if (request === generation.current) setError(message(e)); } finally { if (request === generation.current) setBusy(false); }
  }
  function importLabels(text: string) {
    setError("");
    try {
      const data = JSON.parse(text);
      if (!data || data.timeBasis !== "dataset-seconds" || !Array.isArray(data.intervals) || typeof data.timeSource !== "string") throw new Error("Import JSON needs timeBasis: dataset-seconds, timeSource, and intervals.");
      setIntervals(data.intervals); setSource(data.timeSource); if (typeof data.name === "string") setName(data.name);
    } catch (e) { setError(message(e)); }
  }
  const selected = labels.find(item => item.id === value);
  return <fieldset className="experiment-labels"><legend>Truth labels & evaluation</legend>
    <label>Evaluation labels<select value={value || ""} onChange={e => onChange(e.target.value || undefined)}><option value="">Unlabelled · detector behavior only</option>{labels.map(label => <option key={label.id} value={label.id}>{label.name} · v{label.version} · {label.source}</option>)}</select></label>
    <p className="ws-muted">Only explicit normal and anomaly intervals enter evaluation. Unlabelled time and abstain are excluded from TP/FP/TN/FN. Each run keeps its label version.</p>
    {selected && <p className="ws-notice">v{selected.version}: {selected.timeSource} · {selected.intervals.length} closed intervals · {selected.source === "triplens-simulation" ? "Known simulation truth, separate from detector predictions" : "User-supplied truth"}</p>}
    <details><summary>Create or import a label version</summary>
      <div className="ws-form-grid"><label>Label version name<input value={name} onChange={e => setName(e.target.value)} maxLength={160} /></label><label>Source of label times<input value={source} onChange={e => setSource(e.target.value)} placeholder="e.g. Reviewed operator log, native dataset clock" /></label></div>
      <p className="ws-muted">All times are elapsed seconds from this dataset’s time origin. Closed intervals must not overlap. Version changes do not edit previous runs.</p>
      {intervals.map((interval, index) => <div className="experiment-label-row" key={index}><label>Label {index+1}<select value={interval.kind} onChange={e => setIntervals(rows => rows.map((row, i) => i === index ? { ...row, kind: e.target.value as LabelInterval["kind"] } : row))}><option value="normal">Normal</option><option value="anomaly">Anomaly</option></select></label>{(["start", "end"] as const).map(key => <label key={key}>Label {index+1} {key} (s)<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={interval[key]} onChange={e => setIntervals(rows => rows.map((row, i) => i === index ? { ...row, [key]: Number(e.target.value) } : row))} /></label>)}<button type="button" onClick={() => setIntervals(rows => rows.filter((_, i) => i !== index))}>Remove label {index+1}</button></div>)}
      <div className="ws-inline"><button type="button" onClick={() => setIntervals(rows => [...rows, { kind: "anomaly", start: dataset.metadata.time.start, end: dataset.metadata.time.end }])}>Add label interval</button><button type="button" disabled={busy || !intervals.length || !source.trim()} onClick={() => void save()}>Save new label version</button></div>
      <details><summary>Import label JSON</summary><label>Label JSON<textarea value={importText} onChange={e => setImportText(e.target.value)} placeholder={'{"timeBasis":"dataset-seconds","timeSource":"Reviewed log","intervals":[{"kind":"anomaly","start":400,"end":459}]}'} /></label><button type="button" onClick={() => importLabels(importText)}>Load JSON into editor</button><label>Import JSON file<input type="file" accept=".json,application/json" onChange={e => { const file = e.target.files?.[0]; if (file) void file.text().then(importLabels).catch(error => setError(message(error))); e.target.value = ""; }} /></label></details>
      {simulations.length > 0 && <div className="ws-notice"><label>Known TripLens simulation<select value={simulation || simulations[0]} onChange={e => setSimulation(e.target.value)}>{simulations.map(id => <option key={id} value={id}>{id}</option>)}</select></label><button type="button" disabled={busy} onClick={() => void save(true)}>Use saved TripLens truth</button><p>Uses the saved fault onset and configuration. This is simulation ground truth.</p></div>}
    </details>
    {error && <p className="ws-error" role="alert">{error}</p>}
  </fieldset>;
}
