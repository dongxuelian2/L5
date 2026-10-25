import { useEffect, useState } from "react";
import { api, message } from "./api";
import { type Dataset, type TestDatasetPlan, type TrainingConfig, type TrainingReference } from "./types";
import type { ExperimentConfig, LabelSet } from "./experimentTypes";

export function IndependentTraining({ datasets, config, onChange }: { datasets: Dataset[]; config: ExperimentConfig; onChange: (changes: Partial<ExperimentConfig>) => void }) {
  const training = config.training;
  const normal = datasets.filter(d => !d.metadata.external || d.metadata.external.split === "training" && d.metadata.external.faultNumber === 0);
  const test = datasets.find(d => d.id === config.datasetId)!;
  function enable() {
    const fit = normal.find(d => d.id !== test.id) || normal[0];
    if (!fit) return;
    const cal = normal.find(d => d.id !== fit.id && d.id !== test.id) || fit;
    const axis = fit.metadata.time, split = axis.start+(axis.end-axis.start)*.7;
    const refs: TrainingConfig = { fit: { datasetId: fit.id, range: [axis.start, cal.id === fit.id ? split : axis.end] },
      calibration: { datasetId: cal.id, range: [cal.id === fit.id ? split+(axis.typicalInterval || 1) : cal.metadata.time.start, cal.metadata.time.end] } };
    onChange({ training: refs, signals: fit.metadata.columns.map(c => c.name), requiredSignals: [], baselineRange: refs.fit.range,
      analysisRange: [test.metadata.time.start, test.metadata.time.end], testDatasets: [{ datasetId: test.id, analysisRange: [test.metadata.time.start, test.metadata.time.end] }] });
  }
  function reference(key: keyof TrainingConfig, value: TrainingReference) {
    if (!training) return;
    onChange({ training: { ...training, [key]: value }, ...(key === "fit" ? { baselineRange: value.range } : {}) });
  }
  const tests = config.testDatasets || [];
  function updateTests(next: TestDatasetPlan[]) { if (next.length) onChange({ testDatasets: next, datasetId: next[0].datasetId, analysisRange: next[0].analysisRange, labelSetId: undefined }); }
  return <fieldset><legend>Training and independent evaluation</legend><label><input type="checkbox" checked={Boolean(training)} disabled={!training && !normal.length} onChange={e => { if (e.target.checked) enable(); else onChange({ training: undefined, testDatasets: undefined, labelSetId: undefined }); }} />Fit and calibrate on separate normal datasets</label>
    {training && <><p className="ws-muted">Ranges use each source’s own seconds. Normal fit data defines preprocessing; calibration freezes the threshold. Every test run starts fresh.</p>
      {(["fit", "calibration"] as const).map(key => { const ref = training[key], dataset = datasets.find(d => d.id === ref.datasetId); return <fieldset key={key}><legend>{key === "fit" ? "Normal fit source" : "Normal calibration source"}</legend><label>{key === "fit" ? "Fit dataset" : "Calibration dataset"}<select value={ref.datasetId} onChange={e => { const d = datasets.find(d => d.id === e.target.value)!; reference(key, { datasetId: d.id, range: [d.metadata.time.start, d.metadata.time.end] }); if (key === "fit") onChange({ training: { ...training, fit: { datasetId: d.id, range: [d.metadata.time.start, d.metadata.time.end] } }, signals: d.metadata.columns.map(c => c.name), requiredSignals: [] }); }}>{normal.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><div className="ws-form-grid">{([0,1] as const).map(i => <label key={i}>{key} {i === 0 ? "start" : "end"} (source s)<input type="number" step="any" required min={dataset?.metadata.time.start} max={dataset?.metadata.time.end} value={ref.range[i]} onChange={e => reference(key, { ...ref, range: i === 0 ? [Number(e.target.value), ref.range[1]] : [ref.range[0], Number(e.target.value)] })} /></label>)}</div></fieldset>; })}
      <fieldset><legend>Independent test runs · {tests.length}</legend><div className="ws-option-grid">{datasets.filter(d => ![training.fit.datasetId, training.calibration.datasetId].includes(d.id) && (!d.metadata.external || d.metadata.external.split === "testing")).map(d => <label key={d.id}><input type="checkbox" checked={tests.some(t => t.datasetId === d.id)} disabled={tests.length === 1 && tests[0].datasetId === d.id} onChange={e => updateTests(e.target.checked ? [...tests, { datasetId: d.id, analysisRange: [d.metadata.time.start, d.metadata.time.end] }] : tests.filter(t => t.datasetId !== d.id))} />{d.name}</label>)}</div>
        {tests.map((plan, index) => <TestPlan key={plan.datasetId} dataset={datasets.find(d => d.id === plan.datasetId)!} plan={plan} signals={config.signals} onChange={value => updateTests(tests.map((t,i) => i === index ? value : t))} />)}
      </fieldset><details><summary>Schema and signal matching</summary><p>Fit order: {config.signals.join(", ")}. Original column names and physical units must match. TEP also requires the identical verified 52-channel schema. Explicit mappings can be selected for each test; no positional or fuzzy matching is used.</p></details>
    </>}
  </fieldset>;
}

function TestPlan({ dataset, plan, signals, onChange }: { dataset: Dataset; plan: TestDatasetPlan; signals: string[]; onChange: (value: TestDatasetPlan) => void }) {
  const [labels, setLabels] = useState<LabelSet[]>([]), [error, setError] = useState(""), [mappingOpen, setMappingOpen] = useState(false);
  useEffect(() => { const controller = new AbortController(); api<{ labels: LabelSet[] }>(`/datasets/${dataset.id}/labels`, undefined, "GET", controller.signal).then(r => { if (!controller.signal.aborted) setLabels(r.labels); }).catch(e => { if (!controller.signal.aborted) setError(message(e)); }); return () => controller.abort(); }, [dataset.id]);
  return <details><summary>{dataset.name} · {plan.analysisRange.join("–")} s</summary><div className="ws-form-grid">{([0,1] as const).map(i => <label key={i}>Test {i ? "end" : "start"} (s)<input type="number" step="any" required min={dataset.metadata.time.start} max={dataset.metadata.time.end} value={plan.analysisRange[i]} onChange={e => onChange({ ...plan, analysisRange: i === 0 ? [Number(e.target.value), plan.analysisRange[1]] : [plan.analysisRange[0], Number(e.target.value)] })} /></label>)}</div>
    <label>Test truth label version<select value={plan.labelSetId || ""} onChange={e => onChange({ ...plan, labelSetId: e.target.value || undefined })}><option value="">Unlabelled · behavior only</option>{labels.map(l => <option key={l.id} value={l.id}>v{l.version} · {l.name} · {l.source}</option>)}</select></label>
    <details onToggle={e => setMappingOpen(e.currentTarget.open)}><summary>Explicit signal mapping</summary>{mappingOpen && (dataset.metadata.external ? <p>Verified TEP schema: all selected original names map identically in fit order. Renaming requires a verified schema adapter.</p> : <div className="ws-option-grid">{signals.map(s => <label key={s}>{s}<select value={plan.signalMapping?.[s] || s} onChange={e => onChange({ ...plan, signalMapping: { ...Object.fromEntries(signals.map(name => [name, name])), ...plan.signalMapping, [s]: e.target.value } })}>{dataset.metadata.columns.map(c => <option key={c.name} value={c.name}>{c.name}{c.unit ? ` (${c.unit})` : ""}</option>)}</select></label>)}</div>)}</details>{error && <p role="alert">{error}</p>}
  </details>;
}
