import { errorMessage } from "../i18n/errors";
import { t as tr, useLocale } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { api, message } from "./api";
import type { Dataset } from "./types";
import type { LabelInterval, LabelSet } from "./experimentTypes";

export function ExperimentLabels({ dataset, value, onChange }: { dataset: Dataset; value?: string; onChange: (id?: string) => void }) {
  useLocale();
  const [labels, setLabels] = useState<LabelSet[]>([]), [revision, setRevision] = useState(0), [error, setError] = useState("");
  const [name, setName] = useState(tr("Reviewed labels")), [source, setSource] = useState(""), [intervals, setIntervals] = useState<LabelInterval[]>([]);
  const [importText, setImportText] = useState(""), [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const simulations = dataset.metadata.model ? [dataset.metadata.model.simulationId] : dataset.metadata.transformation?.sourceSimulations || [];
  const [simulation, setSimulation] = useState(simulations[0] || "");
  useEffect(() => {
    const controller = new AbortController(); generation.current++; setLabels([]); setIntervals([]); setError("");
    api<{ labels: LabelSet[] }>(`/datasets/${dataset.id}/labels`, undefined, "GET", controller.signal).then(data => { if (!controller.signal.aborted) setLabels(data.labels); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); });
    return () => { controller.abort(); generation.current++; };
  }, [dataset.id, revision]);
  async function save(simulationTruth = false) {
    const request = generation.current; setBusy(true); setError("");
    try {
      const labels = await api<LabelSet>(`/datasets/${dataset.id}/labels${simulationTruth ? "/simulation" : ""}`, simulationTruth ? { simulationId: simulation || simulations[0] } : { name, timeSource: source, timeBasis: "dataset-seconds", intervals });
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
  return <fieldset className="experiment-labels"><legend>{tr("Truth labels & evaluation")}</legend>
    <label>{tr("Evaluation labels")}<select value={value || ""} onChange={e => onChange(e.target.value || undefined)}><option value="">{tr("Unlabelled · detector behavior only")}</option>{labels.map(label => <option key={label.id} value={label.id}>{label.name} · v{label.version} · {label.source}</option>)}</select></label>
    <p className="ws-muted">{tr("Only explicit normal and anomaly intervals enter evaluation. Unlabelled time and abstain are excluded from TP/FP/TN/FN. Each run keeps its label version.")}</p>
    {selected && <p className="ws-notice">v{selected.version}: {selected.timeSource} · {selected.intervals.length}{" "}{tr("closed intervals ·")}{" "}{["triplens-simulation", "model-simulation"].includes(selected.source) ? tr("Known simulation truth, separate from detector predictions") : tr("User-supplied truth")}</p>}
    <details><summary>{tr("Create or import a label version")}</summary>
      <div className="ws-form-grid"><label>{tr("Label version name")}<input value={name} onChange={e => setName(e.target.value)} maxLength={160} /></label><label>{tr("Source of label times")}<input value={source} onChange={e => setSource(e.target.value)} placeholder={tr("e.g. Reviewed operator log, native dataset clock")} /></label></div>
      <p className="ws-muted">{tr("All times are elapsed seconds from this dataset’s time origin. Closed intervals must not overlap. Version changes do not edit previous runs.")}</p>
      {intervals.map((interval, index) => <div className="experiment-label-row" key={index}><label>{tr("Label")}{" "}{index+1}<select value={interval.kind} onChange={e => setIntervals(rows => rows.map((row, i) => i === index ? { ...row, kind: e.target.value as LabelInterval["kind"] } : row))}><option value="normal">{tr("Normal")}</option><option value="anomaly">{tr("Anomaly")}</option></select></label>{(["start", "end"] as const).map(key => <label key={key}>{tr("Label")}{" "}{index+1} {key} (s)<input type="number" step="any" min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={interval[key]} onChange={e => setIntervals(rows => rows.map((row, i) => i === index ? { ...row, [key]: Number(e.target.value) } : row))} /></label>)}<button type="button" onClick={() => setIntervals(rows => rows.filter((_, i) => i !== index))}>{tr("Remove label")}{" "}{index+1}</button></div>)}
      <div className="ws-inline"><button type="button" onClick={() => setIntervals(rows => [...rows, { kind: "anomaly", start: dataset.metadata.time.start, end: dataset.metadata.time.end }])}>{tr("Add label interval")}</button><button type="button" disabled={busy || !intervals.length || !source.trim()} onClick={() => void save()}>{tr("Save new label version")}</button></div>
      <details><summary>{tr("Import label JSON")}</summary><label>{tr("Label JSON")}<textarea value={importText} onChange={e => setImportText(e.target.value)} placeholder={'{"timeBasis":"dataset-seconds","timeSource":"Reviewed log","intervals":[{"kind":"anomaly","start":400,"end":459}]}'} /></label><button type="button" onClick={() => importLabels(importText)}>{tr("Load JSON into editor")}</button><label>{tr("Import JSON file")}<input type="file" accept=".json,application/json" onChange={e => { const file = e.target.files?.[0]; if (file) void file.text().then(importLabels).catch(error => setError(message(error))); e.target.value = ""; }} /></label></details>
      {simulations.length > 0 && <div className="ws-notice"><label>{tr("Known model simulation")}<select value={simulation || simulations[0]} onChange={e => setSimulation(e.target.value)}>{simulations.map(id => <option key={id} value={id}>{id}</option>)}</select></label><button type="button" disabled={busy} onClick={() => void save(true)}>{tr("Use saved simulation truth")}</button><p>{tr("Uses the saved model fault intervals and configuration. Recovery after a finite fault remains unlabelled.")}</p></div>}
    </details>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
  </fieldset>;
}
