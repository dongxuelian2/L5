import { useEffect, useMemo, useState, type FormEvent } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, message } from "./api";
import type { LabelSet } from "./experimentTypes";
import type { RegimeAlgorithm, RegimeConfig, RegimeDefinition, RegimeDetector, RegimeReference } from "./regimeTypes";
import { number, signalLabel, type Dataset } from "./types";

const algorithms: Record<RegimeAlgorithm, string> = {
  "robust-maxz": "Robust Max-Z",
  "pca-q": "PCA-Q",
  "pca-t2": "PCA-T²",
};
const defaultDetector: RegimeDetector = { algorithm: "robust-maxz", alpha: .01, variance: .9 };
const fullRange = (dataset: Dataset): [number, number] => [dataset.metadata.time.start, dataset.metadata.time.end];

export function detectorName(algorithm: RegimeAlgorithm) {
  return tr(algorithms[algorithm] ?? algorithm);
}

function fractionRange(dataset: Dataset, low: number, high: number): [number, number] {
  const [start, end] = fullRange(dataset);
  const at = (fraction: number) => fraction === 0 ? start : Math.max(start, Math.min(end, Number((start + (end - start) * fraction).toPrecision(12))));
  return [at(low), at(high)];
}

function normalDatasets(datasets: Dataset[]) {
  return datasets.filter(dataset => !dataset.metadata.external ||
    dataset.metadata.external.faultNumber === 0 && dataset.metadata.external.split === "training");
}

function modeDefinition(id: string, dataset: Dataset, band?: [number, number]): RegimeDefinition {
  const [low, high] = band ?? [0, .79];
  const width = high - low;
  return {
    id,
    label: "",
    fit: [{ datasetId: dataset.id, range: fractionRange(dataset, low, low + .67 * width) }],
    calibration: [{ datasetId: dataset.id, range: fractionRange(dataset, low + .68 * width, high) }],
  };
}

function initialConfig(datasets: Dataset[]): RegimeConfig {
  const [first, second] = datasets;
  const modes = second
    ? [modeDefinition("mode-1", first), modeDefinition("mode-2", second)]
    : [modeDefinition("mode-1", first, [0, .39]), modeDefinition("mode-2", first, [.4, .79])];
  return {
    name: "",
    signals: [],
    modes,
    detector: defaultDetector,
    recognition: { recognitionSignals: [], recognitionAlpha: .01, shrinkage: .15, minMargin: 2, dwell: 3, persistence: 2, referenceMode: modes[0].id },
  };
}

export function validReference(reference: RegimeReference, datasets: Dataset[]) {
  const dataset = datasets.find(item => item.id === reference.datasetId);
  return Boolean(dataset && reference.range.every(Number.isFinite) &&
    reference.range[0] >= dataset.metadata.time.start && reference.range[1] <= dataset.metadata.time.end &&
    reference.range[0] <= reference.range[1]);
}

function NumberField({ label, value, onChange, min, max, step = "any" }: {
  label: string; value: number; onChange: (value: number) => void; min?: number; max?: number; step?: "any" | number;
}) {
  return <label>{label}<input type="number" required min={min} max={max} step={step} value={Number.isFinite(value) ? value : ""} onChange={e => onChange(e.target.valueAsNumber)} /></label>;
}

export function RegimeReferenceFields({ datasets, value, onChange, role, rangeFor }: {
  datasets: Dataset[]; value: RegimeReference; onChange: (value: RegimeReference) => void; role: "fit" | "calibration" | "evaluation";
  rangeFor?: (dataset: Dataset) => [number, number];
}) {
  useLocale();
  const dataset = datasets.find(item => item.id === value.datasetId);
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [labelSets, setLabelSets] = useState<LabelSet[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const isEvaluation = role === "evaluation";
  useEffect(() => {
    if (!labelsOpen || !dataset) return;
    const controller = new AbortController();
    setLabelSets([]); setError(""); setLoading(true);
    api<{ labels: LabelSet[] }>(`/datasets/${dataset.id}/labels`, undefined, "GET", controller.signal)
      .then(data => { if (!controller.signal.aborted) setLabelSets(data.labels); })
      .catch(e => { if (!controller.signal.aborted) setError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [dataset?.id, labelsOpen]);
  const selectedLabels = labelSets.find(set => set.id === value.labelSetId);
  const intervals = selectedLabels?.intervals.filter(interval => interval.kind === "normal") ?? [];
  const selectedInterval = intervals.findIndex(interval => interval.start === value.range[0] && interval.end === value.range[1]);
  const sourceLabel = role === "fit" ? tr("Fit dataset") : isEvaluation ? tr("Evaluation dataset") : tr("Calibration dataset");
  return <div className="regime-reference">
    <div className="regime-reference-fields">
      <label>{sourceLabel}<select required value={value.datasetId} onChange={e => {
        const selected = datasets.find(item => item.id === e.target.value);
        if (selected) onChange({ datasetId: selected.id, range: rangeFor ? rangeFor(selected) : role === "fit" ? fractionRange(selected, 0, .52)
          : fractionRange(selected, .53, .79) });
        else onChange({ datasetId: "", range: [NaN, NaN] });
      }}>
        <option value="">{tr("Choose a dataset")}</option>
        {value.datasetId && !dataset && <option value={value.datasetId}>{value.datasetId}</option>}
        {datasets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <NumberField label={tr("Start (source s)")} value={value.range[0]} min={dataset?.metadata.time.start} max={value.range[1]} onChange={start => onChange({ ...value, range: [start, value.range[1]] })} />
      <NumberField label={tr("End (source s)")} value={value.range[1]} min={value.range[0]} max={dataset?.metadata.time.end} onChange={end => onChange({ ...value, range: [value.range[0], end] })} />
    </div>
    {dataset && <details className="regime-labels" onToggle={e => setLabelsOpen(e.currentTarget.open)}>
      <summary>{tr(isEvaluation ? "Evaluation labels (optional)" : "Healthy labels (optional)")}{value.labelSetId ? " ✓" : ""}</summary>
      {labelsOpen && <div className="regime-form-grid">
        <label>{tr("Saved label version")}<select disabled={loading} value={value.labelSetId ?? ""} onChange={e => {
          const selected = labelSets.find(set => set.id === e.target.value);
          const firstNormal = selected?.intervals.find(interval => interval.kind === "normal");
          onChange({ ...value, labelSetId: selected?.id, range: !isEvaluation && firstNormal ? [firstNormal.start, firstNormal.end] : value.range });
        }}>
          <option value="">{tr(loading ? "Loading labels…" : "No label version")}</option>
          {value.labelSetId && !selectedLabels && <option value={value.labelSetId}>{value.labelSetId}</option>}
          {labelSets.filter(set => isEvaluation || set.intervals.some(interval => interval.kind === "normal")).map(set => <option key={set.id} value={set.id}>{set.name} · v{set.version}</option>)}
        </select></label>
        {!isEvaluation && selectedLabels && <label>{tr("Healthy interval")}<select value={selectedInterval} onChange={e => {
          const interval = intervals[Number(e.target.value)];
          if (interval) onChange({ ...value, range: [interval.start, interval.end] });
        }}><option value={-1}>{tr("Current source range")}</option>
          {intervals.map((interval, i) => <option key={i} value={i}>{number(interval.start)}–{number(interval.end)} s</option>)}
        </select></label>}
        {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
      </div>}
    </details>}
  </div>;
}

function DetectorFields({ detector, onChange }: { detector: RegimeDetector; onChange: (value: RegimeDetector) => void }) {
  return <div className="regime-form-grid">
    <label>{tr("Detector")}<select value={detector.algorithm} onChange={e => onChange({ ...detector, algorithm: e.target.value as RegimeAlgorithm })}>
      {(Object.keys(algorithms) as RegimeAlgorithm[]).map(key => <option key={key} value={key}>{detectorName(key)}</option>)}
    </select></label>
    <NumberField label={tr("Detector tail fraction")} value={detector.alpha} min={.000001} max={.499999} onChange={alpha => onChange({ ...detector, alpha })} />
    {detector.algorithm !== "robust-maxz" && <NumberField label={tr("PCA variance retained")} value={detector.variance} min={.5} max={.999999} onChange={variance => onChange({ ...detector, variance })} />}
  </div>;
}

function ModeFields({ mode, position, datasets, detector, onChange, onRemove }: {
  mode: RegimeDefinition; position: number; datasets: Dataset[]; detector: RegimeDetector; onChange: (value: RegimeDefinition) => void; onRemove?: () => void;
}) {
  return <fieldset className="regime-mode">
    <legend>{tr("Mode {0}", { 0: position + 1 })}</legend>
    <div className="regime-mode-heading">
      <label>{tr("Operating-mode label")}<input required maxLength={120} value={mode.label} placeholder={tr(position === 0 ? "e.g. Reduced load" : "e.g. Rated load")} onChange={e => onChange({ ...mode, label: e.target.value })} /></label>
      {onRemove && <button type="button" className="ws-outlined" onClick={onRemove}>{tr("Remove mode")}</button>}
    </div>
    {(["fit", "calibration"] as const).map(role => <div className="regime-mode-partition" key={role}>
      <h3>{tr(role === "fit" ? "Normal fit partitions" : "Normal calibration partitions")}</h3>
      {mode[role].map((ref, i) => <div className="regime-reference-row" key={i}>
        <RegimeReferenceFields role={role} datasets={datasets} value={ref} onChange={value => onChange({ ...mode, [role]: mode[role].map((item, j) => i === j ? value : item) })} />
        {mode[role].length > 1 && <button type="button" className="ws-outlined" onClick={() => onChange({ ...mode, [role]: mode[role].filter((_, j) => i !== j) })}>{tr("Remove partition")}</button>}
      </div>)}
      <button type="button" className="ws-outlined" disabled={mode[role].length >= 16} onClick={() => onChange({ ...mode, [role]: [...mode[role], { datasetId: "", range: [NaN, NaN] }] })}>{tr(role === "fit" ? "Add fit partition" : "Add calibration partition")}</button>
    </div>)}
    <label className="regime-check"><input type="checkbox" checked={Boolean(mode.detector)} onChange={e => onChange({ ...mode, detector: e.target.checked ? detector : undefined })} />{tr("Override detector for this mode")}</label>
    {mode.detector && <DetectorFields detector={{ ...detector, ...mode.detector }} onChange={value => onChange({ ...mode, detector: value })} />}
  </fieldset>;
}

function sharedSignals(datasets: Dataset[], modes: RegimeDefinition[]) {
  const ids = new Set(modes.flatMap(mode => [...mode.fit, ...mode.calibration]).map(ref => ref.datasetId).filter(Boolean));
  const sources = datasets.filter(item => ids.has(item.id));
  return sources[0]?.metadata.columns.filter(column => sources.every(source => source.metadata.columns.some(candidate => candidate.name === column.name && (candidate.unit ?? "") === (column.unit ?? "")))) ?? [];
}

export function RegimeSetup({ datasets, initial, busy, onFit }: {
  datasets: Dataset[]; initial?: RegimeConfig; busy: boolean; onFit: (config: RegimeConfig) => void;
}) {
  useLocale();
  const normal = useMemo(() => normalDatasets(datasets), [datasets]);
  if (!normal.length) return <section className="ws-panel"><h2>{tr("Add normal operating data")}</h2><p>{tr("Import normal datasets or labeled normal intervals to fit an operating-regime model.")}</p></section>;
  return <RegimeForm datasets={normal} initial={initial} busy={busy} onFit={onFit} />;
}

function RegimeForm({ datasets, initial, busy, onFit }: {
  datasets: Dataset[]; initial?: RegimeConfig; busy: boolean; onFit: (config: RegimeConfig) => void;
}) {
  const [config, setConfig] = useState(() => initial ?? initialConfig(datasets));
  const [allSignals, setAllSignals] = useState(!initial);
  const [filter, setFilter] = useState("");
  const common = useMemo(() => sharedSignals(datasets, config.modes), [datasets, config.modes]);
  const names = common.map(column => column.name);
  const signals = allSignals ? names : config.signals.filter(signal => names.includes(signal));
  const recognitionSignals = config.recognition.recognitionSignals.filter(signal => signals.includes(signal));
  const partitions = config.modes.flatMap(mode => [...mode.fit, ...mode.calibration]);
  const overlap = partitions.some((ref, i) => partitions.slice(i + 1).some(other =>
    ref.datasetId === other.datasetId && ref.range[0] <= other.range[1] && other.range[0] <= ref.range[1]));
  const outOfOrder = config.modes.some(mode => mode.fit.some(fit =>
    mode.calibration.some(calibration => fit.datasetId === calibration.datasetId && fit.range[1] >= calibration.range[0])));
  const complete = Boolean(config.name.trim() && config.modes.every(mode => mode.label.trim()) && signals.length && signals.length <= 128 && recognitionSignals.length &&
    partitions.every(ref => validReference(ref, datasets)) && !overlap && !outOfOrder);
  function recognition(changes: Partial<RegimeConfig["recognition"]>) {
    setConfig(value => ({ ...value, recognition: { ...value.recognition, ...changes } }));
  }
  function setModes(modes: RegimeDefinition[]) {
    setConfig(value => ({ ...value, modes, recognition: { ...value.recognition,
      referenceMode: modes.some(mode => mode.id === value.recognition.referenceMode) ? value.recognition.referenceMode : modes[0].id } }));
  }
  function addMode() {
    let id = config.modes.length + 1;
    while (config.modes.some(mode => mode.id === `mode-${id}`)) id++;
    const available = datasets.find(dataset => !partitions.some(ref => ref.datasetId === dataset.id));
    const mode = modeDefinition(`mode-${id}`, available ?? datasets[0]);
    if (!available) {
      mode.fit = [{ datasetId: "", range: [NaN, NaN] }];
      mode.calibration = [{ datasetId: "", range: [NaN, NaN] }];
    }
    setModes([...config.modes, mode]);
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    if (complete && !busy) onFit({ ...config, signals, recognition: { ...config.recognition, recognitionSignals } });
  }
  const filtered = common.filter(column => `${column.name} ${column.displayName ?? ""}`.toLowerCase().includes(filter.trim().toLowerCase()));
  return <form className="ws-panel regime-setup" onSubmit={submit}>
    <h2>{tr("Fit an operating-regime model")}</h2>
    <p>{tr("Assign healthy source windows to each mode. Fit and calibration windows must be disjoint, including their endpoints.")}{" "}{tr("Each mode needs 30 complete fit and 30 complete calibration samples.")}</p>
    <label className="regime-model-name">{tr("Model name")}<input required maxLength={160} value={config.name} placeholder={tr("e.g. Reactor load regimes")} onChange={e => setConfig({ ...config, name: e.target.value })} /></label>
    <div className="regime-modes">
      {config.modes.map((mode, i) => <ModeFields key={mode.id} mode={mode} position={i} datasets={datasets} detector={config.detector}
        onChange={next => setModes(config.modes.map((item, j) => i === j ? next : item))}
        onRemove={config.modes.length > 2 ? () => setModes(config.modes.filter((_, j) => i !== j)) : undefined} />)}
    </div>
    <button type="button" className="ws-outlined" onClick={addMode} disabled={config.modes.length >= 24}>{tr("Add operating mode")}</button>
    {overlap ? <p className="ws-notice" role="status">{tr("Normal partitions overlap on at least one dataset. Adjust their start and end times.")}</p>
      : outOfOrder && <p className="ws-notice" role="status">{tr("Fit must precede calibration within a mode on the same dataset.")}</p>}
    <fieldset className="regime-channels">
      <legend>{tr("Recognition and monitoring signals")}</legend>
      <p>{tr("Choose operating context for recognition, such as load or setpoint. Include additional measurements for fault monitoring.")}</p>
      {common.length ? <>
        <label className="regime-filter">{tr("Filter signals")}<input value={filter} onChange={e => setFilter(e.target.value)} /></label>
        <div className="regime-signal-grid">
          <span>{tr("Signal")}</span><span>{tr("Recognize")}</span><span>{tr("Monitor")}</span>
          {filtered.map(column => {
            const name = column.name, label = signalLabel(column);
            return <div className="regime-signal-row" key={name}><span>{label}</span>
              <input aria-label={tr("Recognize using {0}", { 0: label })} type="checkbox" checked={recognitionSignals.includes(name)} onChange={e => {
                const next = e.target.checked ? [...recognitionSignals, name] : recognitionSignals.filter(signal => signal !== name);
                setConfig({ ...config, signals: e.target.checked && !signals.includes(name) ? [...signals, name] : signals, recognition: { ...config.recognition, recognitionSignals: next } });
              }} />
              <input aria-label={tr("Monitor {0}", { 0: label })} type="checkbox" checked={signals.includes(name)} onChange={e => {
                setAllSignals(false);
                setConfig({ ...config, signals: e.target.checked ? [...signals, name] : signals.filter(signal => signal !== name),
                  recognition: { ...config.recognition, recognitionSignals: e.target.checked ? recognitionSignals : recognitionSignals.filter(signal => signal !== name) } });
              }} />
            </div>;
          })}
        </div>
      </> : <p className="ws-notice">{tr("The selected sources have no shared signal names and units.")}</p>}
      {signals.length > 128 && <p className="ws-notice">{tr("Select up to 128 monitoring signals.")}</p>}
    </fieldset>
    <fieldset className="regime-settings">
      <legend>{tr("Baseline detector and sequential decision settings")}</legend>
      <DetectorFields detector={config.detector} onChange={detector => setConfig({ ...config, detector })} />
      <div className="regime-form-grid">
        <label>{tr("Single-mode baseline") }<select value={config.recognition.referenceMode} onChange={e => recognition({ referenceMode: e.target.value })}>
          {config.modes.map((mode, i) => <option key={mode.id} value={mode.id}>{mode.label || tr("Mode {0}", { 0: i + 1 })}</option>)}
        </select></label>
        <NumberField label={tr("Mode confirmation samples")} value={config.recognition.dwell} min={1} step={1} onChange={dwell => recognition({ dwell })} />
        <NumberField label={tr("Alarm persistence samples")} value={config.recognition.persistence} min={1} step={1} onChange={persistence => recognition({ persistence })} />
      </div>
      <details><summary>{tr("Recognition calibration settings")}</summary><div className="regime-form-grid">
        <NumberField label={tr("Recognition tail fraction")} value={config.recognition.recognitionAlpha} min={.000001} max={.499999} onChange={recognitionAlpha => recognition({ recognitionAlpha })} />
        <NumberField label={tr("Covariance shrinkage")} value={config.recognition.shrinkage} min={.001} max={1} onChange={shrinkage => recognition({ shrinkage })} />
        <NumberField label={tr("Minimum discriminant margin")} value={config.recognition.minMargin} min={0} onChange={minMargin => recognition({ minMargin })} />
        <label>{tr("Acquisition gap override (s)")}<input type="number" step="any" min={.000001} placeholder={tr("Automatic from fit timestamps")} value={config.gapThreshold ?? ""} onChange={e => setConfig({ ...config, gapThreshold: e.target.value === "" ? null : e.target.valueAsNumber })} /></label>
      </div></details>
    </fieldset>
    <button className="ws-primary" disabled={busy || !complete}>{tr(busy ? "Fitting model…" : "Fit and save model")}</button>
  </form>;
}
