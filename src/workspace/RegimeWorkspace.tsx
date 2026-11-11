import { useEffect, useRef, useState, type FormEvent } from "react";
import { t as tr, useLocale } from "../i18n";
import { errorMessage } from "../i18n/errors";
import { api, go, message } from "./api";
import { RegimeModelView } from "./RegimeModelView";
import { RegimeReferenceFields, RegimeSetup, validReference } from "./RegimeSetup";
import { RegimeResult } from "./RegimeResult";
import type { RegimeConfig, RegimeModel, RegimeModelSummary, RegimeReference, RegimeRun, RegimeRunSummary } from "./regimeTypes";
import { dateLabel, type Dataset } from "./types";
import "./regimes.css";

function EvaluationForm({ model, datasets, busy, onRun }: {
  model: RegimeModel; datasets: Dataset[]; busy: boolean; onRun: (name: string, evaluation: RegimeReference) => void;
}) {
  const [name, setName] = useState("");
  const refs = model.config.modes.flatMap(mode => [...mode.fit, ...mode.calibration]);
  const reference = model.sources[model.referenceDatasetId];
  const units = new Map(reference.metadata.columns.map(column => [column.name, column.unit ?? ""]));
  const eligible = datasets.filter(dataset => model.config.signals.every(signal => dataset.metadata.columns.some(column => column.name === signal && (column.unit ?? "") === units.get(signal))));
  function latestTrainingEnd(datasetId: string) {
    return refs.reduce((end, ref) => ref.datasetId === datasetId ? Math.max(end, ref.range[1]) : end, -Infinity);
  }
  function evaluationRange(dataset: Dataset): [number, number] {
    const axis = dataset.metadata.time, end = latestTrainingEnd(dataset.id);
    const first = end < axis.start ? axis.start : Math.min(axis.end, end + (axis.end - end) / 10000);
    return [first, axis.end];
  }
  const independent = eligible.find(dataset => !refs.some(ref => ref.datasetId === dataset.id));
  const first = independent ?? eligible.find(dataset => latestTrainingEnd(dataset.id) < dataset.metadata.time.end) ?? eligible[0];
  const [evaluation, setEvaluation] = useState<RegimeReference>(() => {
    if (!first) return { datasetId: "", range: [NaN, NaN] };
    return { datasetId: first.id, range: evaluationRange(first) };
  });
  const overlap = evaluation.range[0] <= latestTrainingEnd(evaluation.datasetId);
  const holdout = refs.some(ref => ref.datasetId === evaluation.datasetId);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && validReference(evaluation, eligible) && !overlap && !busy) onRun(name, evaluation);
  }
  return <form className="ws-panel regime-evaluate" onSubmit={submit}>
    <h2>{tr("Evaluate frozen detectors")}</h2>
    <p>{tr("Evaluation runs in source order. A window from a training source must begin after all fit and calibration windows.")}</p>
    {!eligible.length ? <p className="ws-notice">{tr("Import an evaluation dataset with all model signals.")}</p> : <>
      <label className="regime-model-name">{tr("Run name")}<input required value={name} maxLength={160} placeholder={tr("e.g. November process replay")} onChange={e => setName(e.target.value)} /></label>
      <RegimeReferenceFields role="evaluation" datasets={eligible} value={evaluation} onChange={setEvaluation} rangeFor={evaluationRange} />
      {overlap ? <p className="ws-notice" role="status">{tr("Choose an evaluation start after the last frozen training partition.")}</p>
        : evaluation.datasetId && <p className="ws-muted">{tr(holdout ? "Chronological holdout within a training source" : "Evaluation on a distinct dataset")}</p>}
      <button className="ws-primary" disabled={busy || !name.trim() || !validReference(evaluation, eligible) || overlap}>{tr(busy ? "Running chronological evaluation…" : "Run and save evaluation")}</button>
    </>}
  </form>;
}

function RegimeLibrary({ base, models, runs, datasets }: { base: string; models: RegimeModelSummary[]; runs: RegimeRunSummary[]; datasets: Dataset[] }) {
  return <div className="regime-library">
    <section className="ws-panel">
      <div className="regime-heading"><h2>{tr("Saved models")}</h2><span className="ws-muted">{models.length.toLocaleString()}</span></div>
      {!models.length ? <p>{tr("Fitted models appear here.")}</p> : <ul>{models.map(model => <li key={model.id}>
        <a href={`#/${base}/models/${model.id}`}><strong>{model.name}</strong><span>{tr("{0} operating modes", { 0: model.config.modes.length })} · {dateLabel(model.createdAt)}</span></a>
      </li>)}</ul>}
    </section>
    <section className="ws-panel">
      <div className="regime-heading"><h2>{tr("Saved evaluations")}</h2><span className="ws-muted">{runs.length.toLocaleString()}</span></div>
      {!runs.length ? <p>{tr("Completed evaluations appear here.")}</p> : <ul>{runs.map(run => <li key={run.id}>
        <a href={`#/${base}/runs/${run.id}`}><strong>{run.name}</strong><span>{datasets.find(dataset => dataset.id === run.datasetId)?.name ?? run.datasetId} · {dateLabel(run.createdAt)}</span></a>
      </li>)}</ul>}
    </section>
  </div>;
}

export function RegimeWorkspace({ workspaceId, datasets, section, itemId, intervalIndex }: {
  workspaceId: string; datasets: Dataset[]; section?: string; itemId?: string; intervalIndex?: number;
}) {
  useLocale();
  const base = `workspaces/${workspaceId}/regimes`, endpoint = `/${base}`;
  const [models, setModels] = useState<RegimeModelSummary[]>([]), [runs, setRuns] = useState<RegimeRunSummary[]>([]);
  const [model, setModel] = useState<RegimeModel | null>(null), [run, setRun] = useState<RegimeRun | null>(null);
  const [initial, setInitial] = useState<RegimeConfig | undefined>();
  const [busy, setBusy] = useState(false), [loadingLibrary, setLoadingLibrary] = useState(true), [loadingItem, setLoadingItem] = useState(false);
  const [error, setError] = useState(""), [libraryError, setLibraryError] = useState("");
  const [revision, setRevision] = useState(0);
  const active = useRef<AbortController | null>(null);
  const shownModel = model?.id === itemId && section === "models" ? model : null;
  const shownRun = run?.id === itemId && section === "runs" ? run : null;
  useEffect(() => {
    const controller = new AbortController();
    setLoadingLibrary(true); setLibraryError("");
    Promise.all([
      api<{ models: RegimeModelSummary[] }>(`${endpoint}/models`, undefined, "GET", controller.signal),
      api<{ runs: RegimeRunSummary[] }>(`${endpoint}/runs`, undefined, "GET", controller.signal),
    ]).then(([nextModels, nextRuns]) => {
      if (!controller.signal.aborted) { setModels(nextModels.models); setRuns(nextRuns.runs); }
    }).catch(e => { if (!controller.signal.aborted) setLibraryError(message(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoadingLibrary(false); });
    return () => controller.abort();
  }, [endpoint, revision]);
  useEffect(() => {
    setError(""); setBusy(false);
    const controller = new AbortController();
    if (itemId && (section === "models" || section === "runs")) {
      setLoadingItem(true);
      const read = section === "models"
        ? api<RegimeModel>(`${endpoint}/models/${itemId}`, undefined, "GET", controller.signal).then(data => { if (!controller.signal.aborted) setModel(data); })
        : api<RegimeRun>(`${endpoint}/runs/${itemId}`, undefined, "GET", controller.signal).then(data => { if (!controller.signal.aborted) setRun(data); });
      read.catch(e => { if (!controller.signal.aborted) setError(message(e)); })
        .finally(() => { if (!controller.signal.aborted) setLoadingItem(false); });
    } else {
      setLoadingItem(false);
    }
    return () => { controller.abort(); active.current?.abort(); active.current = null; };
  }, [endpoint, section, itemId]);
  async function fit(config: RegimeConfig) {
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError("");
    try {
      const saved = await api<RegimeModel>(`${endpoint}/fit`, config, "POST", controller.signal);
      if (!controller.signal.aborted) {
        setModel(saved); setInitial(undefined); setRevision(value => value + 1);
        go(`${base}/models/${saved.id}`);
      }
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) { setBusy(false); active.current = null; } }
  }
  async function evaluate(name: string, evaluation: RegimeReference) {
    if (!shownModel) return;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError("");
    try {
      const saved = await api<RegimeRun>(`${endpoint}/runs`, { name, evaluation, modelId: shownModel.id }, "POST", controller.signal);
      if (!controller.signal.aborted) {
        setRun(saved); setRevision(value => value + 1);
        go(`${base}/runs/${saved.id}`);
      }
    } catch (e) { if (!controller.signal.aborted) setError(message(e)); }
    finally { if (!controller.signal.aborted) { setBusy(false); active.current = null; } }
  }
  return <div className="regime-workspace">
    <header className="ws-page-title regime-title"><div>
      <h1>{tr("Operating regime monitoring")}</h1>
      <p>{tr("Recognize operating modes from process context and compare frozen anomaly detectors on the same timeline.")}</p>
    </div>{section && <a className="ws-link" href={`#/${base}`} onClick={() => setInitial(undefined)}>{tr("← Regime library")}</a>}</header>
    {error && <p className="ws-error" role="alert">{errorMessage(error)}</p>}
    {!section && <>
      {loadingLibrary && <p role="status">{tr("Opening saved regime sessions…")}</p>}
      {libraryError && <p className="ws-error" role="alert">{errorMessage(libraryError)}</p>}
      <RegimeLibrary base={base} models={models} runs={runs} datasets={datasets} />
      <RegimeSetup datasets={datasets} initial={initial} busy={busy} onFit={config => void fit(config)} />
    </>}
    {loadingItem && !shownModel && !shownRun && <p role="status">{tr("Opening saved regime session…")}</p>}
    {shownModel && <>
      <section className="ws-panel regime-frozen-heading">
        <div className="regime-heading"><div><h2>{shownModel.name}</h2><p>{tr("Fitted {0}", { 0: dateLabel(shownModel.createdAt) })}</p></div>
          <button className="ws-outlined" type="button" onClick={() => {
            const config = shownModel.config;
            const modes = config.modes.map(mode => mode.detector && mode.detector.algorithm === config.detector.algorithm &&
              mode.detector.alpha === config.detector.alpha && mode.detector.variance === config.detector.variance
              ? { ...mode, detector: undefined } : mode);
            setInitial({ ...config, modes, name: "" }); go(base);
          }}>{tr("Use settings for a new model")}</button>
        </div>
      </section>
      <EvaluationForm key={`evaluation-${shownModel.id}`} model={shownModel} datasets={datasets} busy={busy} onRun={(name, evaluation) => void evaluate(name, evaluation)} />
      <RegimeModelView key={`model-${shownModel.id}`} model={shownModel} datasets={Object.values(shownModel.sources)} />
    </>}
    {shownRun && <RegimeResult key={`${shownRun.id}/${intervalIndex ?? ""}`} run={shownRun} workspaceId={workspaceId} initialIntervalIndex={intervalIndex} />}
  </div>;
}
